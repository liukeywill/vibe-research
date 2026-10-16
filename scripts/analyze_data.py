#!/usr/bin/env python3
"""Reproducible, local-only numeric OLS with an explicit dataset contract."""
from __future__ import annotations
import argparse
import csv
import fcntl
import hashlib
import inspect
import io
import json
import math
import platform
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from workspace import WorkspaceError, contained_path, project_path


class AnalysisError(ValueError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def dumps(data):
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def local(root, value):
    candidate = Path(value)
    if candidate.is_absolute():
        try:
            value = str(candidate.relative_to(root))
        except ValueError as exc:
            raise AnalysisError("input must be inside the project") from exc
    return contained_path(root, str(value))


@contextmanager
def locked(root):
    with contained_path(root, ".pipeline.lock").open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AnalysisError("project is busy") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def write(root, relative, content, immutable=False):
    target = contained_path(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = content if isinstance(content, bytes) else content.encode("utf-8")
    if immutable and target.exists():
        if target.read_bytes() != data:
            raise AnalysisError(f"refusing to replace frozen input: {relative}")
        return
    temporary = contained_path(root, relative + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(data)
    temporary.replace(target)


def clean_csv(raw, spec, outcome, predictors):
    """Return selected complete numeric rows and a record-index audit log."""
    selected = [outcome] + list(predictors)
    if not predictors or len(selected) != len(set(selected)):
        raise ValueError("outcome and at least one distinct predictor are required")
    declared = {x["name"]: x for x in spec["columns"]}
    if len(declared) != len(spec["columns"]):
        raise ValueError("duplicate column declarations")
    for name in selected:
        if name not in declared or declared[name]["type"] not in ("number", "integer"):
            raise ValueError(f"selected column must be declared numeric: {name}")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter=spec.get("delimiter", ","))
    headers = reader.fieldnames
    if not headers or len(headers) != len(set(headers)):
        raise ValueError("CSV must have unique column headers")
    missing_columns = [x for x, c in declared.items() if c["required"] and x not in headers]
    missing_columns += [x for x in selected if x not in headers]
    if missing_columns:
        raise ValueError(f"missing columns: {sorted(set(missing_columns))}")
    rows = list(reader)
    if not rows:
        raise ValueError("CSV is empty")
    if any(None in r or any(v is None for v in r.values()) for r in rows):
        raise ValueError("CSV has malformed row widths")
    missing = {str(x) for x in spec["missing_values"] if x is not None}
    missing.add("")
    seen, duplicates, missing_rows, invalid, kept = set(), [], [], [], []
    for number, row in enumerate(rows, 2):
        signature = tuple(row[h] for h in headers)
        duplicate = signature in seen
        seen.add(signature)
        if duplicate:
            duplicates.append(number)
        numeric = {}
        absent = []
        for name in selected:
            value = row[name].strip()
            if value in missing:
                absent.append(name)
                continue
            try:
                number_value = float(value)
                if not math.isfinite(number_value):
                    raise ValueError()
                if declared[name]["type"] == "integer" and not number_value.is_integer():
                    raise ValueError()
                numeric[name] = number_value
            except (ValueError, OverflowError):
                invalid.append({"source_record": number, "column": name})
        if duplicate and spec["cleaning"]["drop_exact_duplicates"]:
            continue
        if absent:
            missing_rows.append({"source_record": number, "columns": absent})
            continue
        kept.append({"__source_record__": number, **numeric})
    if invalid:
        raise ValueError("invalid/non-finite numeric values: " + json.dumps(invalid))
    if missing_rows and spec["cleaning"]["missing_policy"] == "error":
        raise ValueError("missing selected values: " + json.dumps(missing_rows))
    if spec["cleaning"]["missing_policy"] not in ("error", "complete_case"):
        raise ValueError("unsupported missing policy")
    after_duplicates = len(rows) - (len(duplicates) if spec["cleaning"]["drop_exact_duplicates"] else 0)
    log = {"schema_version": 1, "id": "cleaning", "record_number_definition": "1-based CSV logical record; header is record 1 (not physical line with embedded newlines)",
           "input_rows": len(rows), "output_rows": len(kept),
           "rules": [{"rule": "exact_duplicates", "policy": "drop" if spec["cleaning"]["drop_exact_duplicates"] else "keep", "before": len(rows), "after": after_duplicates, "affected_records": duplicates},
                     {"rule": "missing_selected_numeric", "policy": spec["cleaning"]["missing_policy"], "before": after_duplicates, "after": len(kept), "affected_records": [x["source_record"] for x in missing_rows], "details": missing_rows}],
           "kept_source_records": [x["__source_record__"] for x in kept], "selected_columns": selected}
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["__source_record__"] + selected, lineterminator="\n")
    writer.writeheader()
    writer.writerows(kept)
    return kept, output.getvalue().encode("utf-8"), log


def fit_rows(rows, outcome, predictors):
    import numpy as np
    import statsmodels.api as sm
    y = np.asarray([r[outcome] for r in rows], dtype=float)
    x = np.asarray([[1.0] + [r[p] for p in predictors] for r in rows], dtype=float)
    if len(rows) <= len(predictors) + 1:
        raise ValueError("insufficient complete observations for residual degrees of freedom")
    if np.linalg.matrix_rank(x) != x.shape[1]:
        raise ValueError("rank-deficient design; constant or collinear predictors")
    if np.ptp(y) == 0:
        raise ValueError("constant outcome cannot support regression inference")
    result = sm.OLS(y, x).fit(cov_type="HC3", use_t=True)
    interval = result.conf_int(alpha=0.05)
    coefficients = []
    for i, term in enumerate(["intercept"] + list(predictors)):
        coefficients.append({"term": term, "estimate": float(result.params[i]), "std_error": float(result.bse[i]), "ci_low": float(interval[i, 0]), "ci_high": float(interval[i, 1]), "p_value": float(result.pvalues[i])})
    output = {"coefficients": coefficients, "r_squared": float(result.rsquared), "adjusted_r_squared": float(result.rsquared_adj), "residual_df": int(result.df_resid),
              "diagnostics": {"condition_number": float(result.condition_number), "max_leverage": float(result.get_influence().hat_matrix_diag.max()), "residual_rmse": float(np.sqrt(np.mean(result.resid ** 2))), "independence": "requires design review; not established by numeric fit", "linearity": "not certified; inspect residual plots or preplanned sensitivity analyses"}}
    json.dumps(output, allow_nan=False)
    return output


def reproduction_code(raw_relative, spec_relative, raw_hash, spec_hash, outcome, predictors):
    # Embed the actual pure cleaning/fitting functions; no dependency on installed workbench.
    header = "import csv, io, json, math, hashlib, argparse\nfrom pathlib import Path\n"
    config = repr({"raw": raw_relative, "spec": spec_relative, "raw_sha256": raw_hash, "spec_sha256": spec_hash, "outcome": outcome, "predictors": predictors})
    return header + "\n" + inspect.getsource(clean_csv) + "\n" + inspect.getsource(fit_rows) + "\nCONFIG = " + config + '''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='data/reproduced-result.json')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    def safe(relative):
        part = Path(relative)
        if part.is_absolute() or '..' in part.parts:
            raise ValueError('project-relative paths required')
        current = root
        for component in part.parts:
            current = current / component
            if current.is_symlink():
                raise ValueError('symlink rejected')
        return current
    raw = safe(CONFIG['raw']).read_bytes()
    spec_bytes = safe(CONFIG['spec']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG['raw_sha256'] or hashlib.sha256(spec_bytes).hexdigest() != CONFIG['spec_sha256']:
        raise ValueError('frozen input hash mismatch')
    spec = json.loads(spec_bytes)
    rows, cleaned, log = clean_csv(raw, spec, CONFIG['outcome'], CONFIG['predictors'])
    result = fit_rows(rows, CONFIG['outcome'], CONFIG['predictors'])
    result['cleaned_sha256'] = hashlib.sha256(cleaned).hexdigest()
    result['n_analyzed'] = len(rows)
    safe(args.output).write_text(json.dumps(result, indent=2, allow_nan=False) + '\\n', encoding='utf-8')

if __name__ == '__main__':
    main()
'''


def analyze(project, spec_path, outcome, predictors):
    root = project_path(project)
    if not (root / "project.json").is_file():
        raise AnalysisError("initialize a research project first")
    with locked(root):
        spec_file = local(root, spec_path)
        spec_bytes = spec_file.read_bytes()
        spec = json.loads(spec_bytes)
        from contracts import validate
        validate("dataset-spec", spec)
        raw_file = local(root, spec["path"])
        raw = raw_file.read_bytes()
        if sha(raw) != spec["sha256"]:
            raise AnalysisError("dataset sha256 differs from declared frozen input")
        rows, cleaned, log = clean_csv(raw, spec, outcome, predictors)
        results = fit_rows(rows, outcome, predictors)
        raw_relative = f"data/frozen/{sha(raw)}.csv"
        spec_relative = f"data/frozen/{sha(spec_bytes)}.json"
        write(root, raw_relative, raw, immutable=True)
        write(root, spec_relative, spec_bytes, immutable=True)
        write(root, "data/cleaned.csv", cleaned)
        validate("cleaning-log", log)
        write(root, "data/cleaning-log.json", dumps(log))
        code = reproduction_code(raw_relative, spec_relative, sha(raw), sha(spec_bytes), outcome, predictors)
        write(root, "analysis-code/reproduce.py", code)
        import importlib.metadata
        environment = {"python": platform.python_version(), "platform": platform.platform(), "packages": {name: importlib.metadata.version(name) for name in ("numpy", "pandas", "scipy", "statsmodels")}}
        write(root, "data/environment.json", dumps(environment))
        completed = subprocess.run([sys.executable, str(contained_path(root, "analysis-code/reproduce.py"))], capture_output=True, text=True, timeout=120, cwd=root)
        if completed.returncode:
            raise AnalysisError("independent reproduction failed: " + completed.stderr[-2000:])
        reproduced = json.loads(contained_path(root, "data/reproduced-result.json").read_text())
        differences = [abs(results[key] - reproduced[key]) for key in ("r_squared", "adjusted_r_squared")]
        for expected, actual in zip(results["coefficients"], reproduced["coefficients"]):
            differences.extend(abs(expected[key] - actual[key]) for key in ("estimate", "std_error", "ci_low", "ci_high", "p_value"))
        matched = reproduced["cleaned_sha256"] == sha(cleaned) and reproduced["n_analyzed"] == len(rows) and max(differences) <= 1e-10
        reproducibility = {"status": "verified" if matched else "failed", "max_abs_difference": max(differences)}
        def receipt(relative):
            return {"path": relative, "sha256": sha(contained_path(root, relative).read_bytes())}
        limitations = ["OLS coefficients are observed conditional associations, not causal effects.", "HC3 uncertainty does not address clustering, selection, confounding or misspecified mean structure.", "Complete-case exclusion may bias estimates; missingness assumptions require substantive review.", "No automatic model selection, p-value thresholding or outcome-driven removal was performed.", "Linearity, independence and external validity require research-design review; numerical success does not certify assumptions."]
        result = {"schema_version": 1, "id": "analysis_" + spec["id"], "status": "executed", "reason": "Prespecified numeric OLS executed on declared local data; independent script rerun compared.",
                  "input_files": [receipt(raw_relative), receipt(spec_relative), receipt(str(spec_file.relative_to(root))), receipt(str(raw_file.relative_to(root)))],
                  "code": receipt("analysis-code/reproduce.py"), "environment": environment, "method": "OLS",
                  "parameters": {"outcome": outcome, "predictors": predictors, "intercept": True, "covariance": "HC3", "confidence_level": 0.95, "use_t": True, "missing_policy": spec["cleaning"]["missing_policy"], "drop_exact_duplicates": spec["cleaning"]["drop_exact_duplicates"]},
                  "sample": {"input_rows": log["input_rows"], "output_rows": len(rows), "dropped_rows": log["input_rows"] - len(rows)}, "results": results, "limitations": limitations,
                  "artifacts": [receipt(p) for p in ("data/cleaned.csv", "data/cleaning-log.json", "data/environment.json", "data/reproduced-result.json")], "reproducibility": reproducibility}
        validate("analysis-result", result)
        write(root, "research/analysis-result.json", dumps(result))
        lines = ["# 数据分析结果", "", f"状态：executed；数据集：{spec['id']}；观察单位：{spec['unit_of_analysis']}。", "", f"输入 {log['input_rows']} 行，分析 {len(rows)} 行，移除 {log['input_rows'] - len(rows)} 行。", f"OLS 含截距；HC3 稳健协方差、t 参考分布与 95% 置信区间；R²={results['r_squared']:.6f}，调整 R²={results['adjusted_r_squared']:.6f}。", "", "| 项 | 估计 | 95% CI | p |", "| --- | ---: | --- | ---: |"]
        for c in results["coefficients"]:
            lines.append(f"| {c['term']} | {c['estimate']:.6g} | [{c['ci_low']:.6g}, {c['ci_high']:.6g}] | {c['p_value']:.6g} |")
        lines += ["", "解释：以上系数仅表示观察数据中的条件关联，不能据此推断因果。", "", "复现：独立运行 analysis-code/reproduce.py；冻结数据、数据字典、清洗规则、代码和环境均有哈希或版本记录。", f"本次数值复现：{reproducibility['status']}，最大绝对差 {reproducibility['max_abs_difference']:.3g}。", "", "局限："] + ["- " + x for x in limitations]
        write(root, "research/analysis.md", "\n".join(lines) + "\n")
        if not matched:
            raise AnalysisError("numeric reproduction differs; analysis-result records failure")
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--spec", default="data/dataset-spec.json")
    parser.add_argument("--outcome", required=True)
    parser.add_argument("--predictors", nargs="+", required=True)
    args = parser.parse_args()
    try:
        result = analyze(args.project, args.spec, args.outcome, args.predictors)
        print(dumps({"status": result["status"], "sample": result["sample"], "reproducibility": result["reproducibility"]}), end="")
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(dumps({"status": "error", "reason": str(exc)}), end="")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
