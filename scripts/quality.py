#!/usr/bin/env python3
"""Evaluate declared quality gates without presenting structural checks as truth."""
from __future__ import annotations
import argparse
from contextlib import nullcontext
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from workspace import contained_path, project_path
from analyze_data import locked, local, write, dumps, clean_csv, fit_rows

METRIC_IDS = ("citation_resolution_rate", "verified_claim_coverage", "screening_decision_coverage", "fulltext_ratio", "schema_pass_rate", "analysis_reproducibility", "screening_precision", "screening_recall")
SCHEMA_FILES = {
    "project-spec.json": "project-spec", "research/search-query.json": "search-query", "research/screening.json": "screening",
    "research/sources.json": "source-record", "research/evidence.json": "evidence-record", "research/synthesis.json": "synthesis",
    "research/study-design.json": "study-design", "research/analysis-result.json": "analysis-result", "report.json": "research-report",
}
DEFAULT_POLICY = {"schema_version": 1, "id": "quality-default", "metrics": [
    {"id": name, "min": 1.0, "severity": "error", "required": True} for name in ("citation_resolution_rate", "verified_claim_coverage", "schema_pass_rate", "screening_decision_coverage")
] + [{"id": "analysis_reproducibility", "min": 1.0, "severity": "error", "required": False},
     {"id": "fulltext_ratio", "min": 0.0, "severity": "warning", "required": False},
     {"id": "screening_precision", "min": 0.0, "severity": "warning", "required": False},
     {"id": "screening_recall", "min": 0.0, "severity": "warning", "required": False}]}


def read(root, relative, fallback=None):
    try:
        return json.loads(contained_path(root, relative).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def validate_policy(policy):
    from contracts import validate
    validate("quality-policy", policy)
    ids = [x["id"] for x in policy["metrics"]]
    if len(ids) != len(set(ids)) or set(ids) - set(METRIC_IDS):
        raise ValueError("duplicate or unknown quality metric id")
    for item in policy["metrics"]:
        if not 0 <= item["min"] <= 1:
            raise ValueError("quality thresholds must be in [0, 1]")
    # Core correctness gates cannot be disabled by an incomplete custom policy.
    core = {x["id"] for x in DEFAULT_POLICY["metrics"] if x["required"]}
    supplied = {x["id"]: x for x in policy["metrics"]}
    for name in core:
        if name not in supplied or not supplied[name]["required"] or supplied[name]["severity"] != "error" or supplied[name]["min"] != 1.0:
            raise ValueError(f"core gate requires min=1, required=true and severity=error: {name}")


def schema_measure(root, analysis):
    from contracts import validate
    mappings = dict(SCHEMA_FILES)
    import manuscript
    if manuscript.enabled(root): mappings["manuscript.json"] = "manuscript"
    if isinstance(analysis, dict) and analysis.get("status") == "executed":
        mappings["data/dataset-spec.json"] = "dataset-spec"
        mappings["data/cleaning-log.json"] = "cleaning-log"
    passed, errors = 0, []
    for relative, schema in mappings.items():
        try:
            data = json.loads(contained_path(root, relative).read_text(encoding="utf-8"))
            if relative in ("research/sources.json", "research/evidence.json"):
                if not isinstance(data, list):
                    raise ValueError("expected record array")
                for record in data:
                    validate(schema, record)
                ids = [x["id"] for x in data]
                if len(ids) != len(set(ids)):
                    raise ValueError("duplicate record ids")
            else:
                validate(schema, data)
            if relative == "manuscript.json": manuscript.validate_project(root)
            passed += 1
        except (ValueError, OSError, TypeError, KeyError) as exc:
            errors.append(f"{relative}: {exc}")
    return passed, len(mappings), errors


def reproduction_measure(root, analysis):
    root = project_path(root)
    if analysis.get("status") != "executed":
        return None, None, "not_applicable", "Analysis is explicitly planned/not_applicable; no observed-data reproduction claim."
    try:
        receipts = analysis["input_files"] + analysis.get("artifacts", []) + [analysis["code"]]
        for receipt in receipts:
            actual = hashlib.sha256(local(root, receipt["path"]).read_bytes()).hexdigest()
            if actual != receipt["sha256"]:
                raise ValueError("artifact hash differs: " + receipt["path"])
        spec = read(root, "data/dataset-spec.json")
        if not isinstance(spec, dict):
            raise ValueError("dataset-spec unavailable")
        raw = local(root, spec["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != spec["sha256"]:
            raise ValueError("raw data hash differs")
        params = analysis["parameters"]
        if analysis["method"] != "OLS" or params.get("covariance") != "HC3" or params.get("intercept") is not True or params.get("confidence_level") != 0.95 or params.get("use_t") is not True or params.get("missing_policy") != spec["cleaning"]["missing_policy"] or params.get("drop_exact_duplicates") != spec["cleaning"]["drop_exact_duplicates"]:
            raise ValueError("unsupported reproduction method/configuration")
        rows, cleaned, log = clean_csv(raw, spec, params["outcome"], params["predictors"])
        actual = fit_rows(rows, params["outcome"], params["predictors"])
        expected = analysis["results"]
        if len(rows) != analysis["sample"]["output_rows"] or log["input_rows"] != analysis["sample"]["input_rows"]:
            raise ValueError("sample counts differ")
        if cleaned != contained_path(root, "data/cleaned.csv").read_bytes():
            raise ValueError("cleaned data differs")
        if len(actual["coefficients"]) != len(expected["coefficients"]):
            raise ValueError("coefficient count differs")
        differences = [abs(actual[k] - expected[k]) for k in ("r_squared", "adjusted_r_squared")]
        for a, b in zip(actual["coefficients"], expected["coefficients"]):
            if a["term"] != b["term"]:
                raise ValueError("coefficient terms differ")
            differences.extend(abs(a[k] - b[k]) for k in ("estimate", "std_error", "ci_low", "ci_high", "p_value"))
        if max(differences) > 1e-10:
            raise ValueError(f"numeric difference exceeds tolerance: {max(differences)}")
        return 1, 1, None, "Current artifact hashes and independent numeric recalculation agree at absolute tolerance 1e-10; this is reproducibility, not causal validity."
    except (ValueError, OSError, KeyError, TypeError, ImportError) as exc:
        return 0, 1, None, str(exc)


def evaluate(project, policy_path=None, benchmark_path=None, acquire_lock=True, write_report=True):
    root = project_path(project)
    if not contained_path(root, "project.json").is_file():
        raise ValueError("initialize a research project first")
    with locked(root) if acquire_lock else nullcontext():
        evaluation_config = {"policy_path": None, "benchmark_path": None}
        evaluation_paths = set()
        if policy_path is None:
            default_path = contained_path(root, "quality-policy.json")
            if default_path.exists():
                policy_bytes = default_path.read_bytes()
                policy = json.loads(policy_bytes)
            else:
                policy = DEFAULT_POLICY
                policy_bytes = dumps(policy).encode()
                if write_report:
                    write(root, "quality-policy.json", policy_bytes)
            if default_path.exists():
                evaluation_config["policy_path"] = default_path.relative_to(root).as_posix()
        else:
            policy_file = local(root, policy_path)
            evaluation_config["policy_path"] = policy_file.relative_to(root).as_posix()
            policy_bytes = policy_file.read_bytes()
            policy = json.loads(policy_bytes)
        if evaluation_config["policy_path"]:
            evaluation_paths.add(evaluation_config["policy_path"])
        validate_policy(policy)
        sources = read(root, "research/sources.json", [])
        evidence = read(root, "research/evidence.json", [])
        screening = read(root, "research/screening.json", {})
        report = read(root, "report.json", {})
        analysis = read(root, "research/analysis-result.json", {})
        sources = sources if isinstance(sources, list) else []
        evidence = evidence if isinstance(evidence, list) else []
        screening = screening if isinstance(screening, dict) else {}
        report = report if isinstance(report, dict) else {}
        analysis = analysis if isinstance(analysis, dict) else {}
        by_source = {x.get("id"): x for x in sources if isinstance(x, dict) and isinstance(x.get("id"), str)}
        by_evidence = {x.get("id"): x for x in evidence if isinstance(x, dict) and isinstance(x.get("id"), str)}
        references = report.get("references", [])
        references = references if isinstance(references, list) else []
        reference_edges = [isinstance(r, dict) and isinstance(r.get("source_id"), str) and (s := by_source.get(r.get("source_id"))) is not None and s.get("metadata_status") == "verified" and r.get("title") == s.get("title") and r.get("url") == s.get("url") for r in references]
        reference_ids = {r.get("source_id") for r in references if isinstance(r, dict) and isinstance(r.get("source_id"), str)}
        all_claims = report.get("claims", [])
        all_claims = [x for x in all_claims if isinstance(x, dict)] if isinstance(all_claims, list) else []
        claim_ids = {c.get("id") for c in all_claims if isinstance(c.get("id"), str)}
        citation_edges = list(reference_edges)
        for section in report.get("sections", []) if isinstance(report.get("sections", []), list) else []:
            if isinstance(section, dict) and isinstance(section.get("claim_ids"), list):
                citation_edges.extend(isinstance(cid, str) and cid in claim_ids for cid in section["claim_ids"])
        for claim in all_claims:
            if isinstance(claim.get("evidence_ids"), list):
                citation_edges.extend(isinstance(eid, str) and eid in by_evidence and isinstance(by_evidence[eid].get("source_id"), str) and by_evidence[eid].get("source_id") in reference_ids for eid in claim["evidence_ids"])
            if isinstance(claim.get("analysis_ids"), list):
                citation_edges.extend(isinstance(aid, str) and aid == analysis.get("id") for aid in claim["analysis_ids"])
        claims = report.get("claims", [])
        claims = [x for x in claims if isinstance(x, dict) and x.get("status") != "hypothesis"] if isinstance(claims, list) else []
        reproduction = reproduction_measure(root, analysis)
        def supported(c):
            if c.get("status") != "supported":
                return False
            eids, aids = c.get("evidence_ids", []), c.get("analysis_ids", [])
            if not isinstance(eids, list) or not isinstance(aids, list) or any(not isinstance(x, str) for x in eids + aids):
                return False
            if not eids and not aids:
                return False
            for eid in eids:
                e = by_evidence.get(eid, {})
                s = by_source.get(e.get("source_id"), {}) if isinstance(e.get("source_id"), str) else {}
                if e.get("claim_verification") != "verified" or e.get("support_status") != "supports" or not e.get("locator") or s.get("metadata_status") != "verified" or s.get("access_level") != "fulltext" or not e.get("reviewer") or not e.get("reviewed_at"):
                    return False
            if aids and (aids != [analysis.get("id")] or reproduction[0] != 1):
                return False
            return True
        decisions = screening.get("decisions", [])
        decisions = decisions if isinstance(decisions, list) else []
        definitive = {d.get("source_id") for d in decisions if isinstance(d, dict) and isinstance(d.get("source_id"), str) and d.get("decision") in ("include", "exclude") and d.get("reason") and d.get("reviewer") and d.get("reviewed_at")}
        passed, total, schema_errors = schema_measure(root, analysis)
        values = {
            "citation_resolution_rate": (sum(citation_edges), len(citation_edges), None, "Denominator: report reference entries + section-to-claim links + claim-to-evidence/analysis links; numerator: resolved links (references require verified matching source metadata; evidence must link to a listed source). Not a new network resolution test."),
            "verified_claim_coverage": (sum(supported(c) for c in claims), len(claims), None, "Denominator: report claims except explicitly labelled hypotheses; numerator: supported claims whose every evidence link has a named review registration and verified source, or a reproduced analysis ID. This measures review registration coverage, not semantic accuracy."),
            "screening_decision_coverage": (len(set(by_source) & definitive), len(by_source), None, "Denominator: unique registered source IDs; numerator: documented include/exclude decisions. Uncertain records remain unresolved."),
            "fulltext_ratio": (sum(s.get("access_level") == "fulltext" for s in by_source.values()), len(by_source), None, "Denominator: unique registered sources; numerator: records marked fulltext. Fulltext coverage is not completeness or study quality."),
            "schema_pass_rate": (passed, total, None, "Denominator: fixed required schema files (never skip absent artifacts); record arrays must all validate. " + ("; ".join(schema_errors) if schema_errors else "All required structures valid.")),
            "analysis_reproducibility": reproduction,
            "screening_precision": (None, None, "not_measured", "No independent labelled benchmark supplied."),
            "screening_recall": (None, None, "not_measured", "No independent labelled benchmark supplied."),
        }
        if benchmark_path:
            benchmark_file = local(root, benchmark_path)
            evaluation_config["benchmark_path"] = benchmark_file.relative_to(root).as_posix()
            evaluation_paths.add(evaluation_config["benchmark_path"])
            benchmark = json.loads(benchmark_file.read_text())
            from contracts import validate
            validate("screening-benchmark", benchmark)
            if not benchmark["independent"]:
                raise ValueError("benchmark must have independent labels; non-independent labels cannot measure accuracy")
            labels = benchmark["labels"]
            ids = [x["source_id"] for x in labels]
            if len(ids) != len(set(ids)) or set(ids) - set(by_source):
                raise ValueError("benchmark IDs must be unique and present in sources")
            predicted = {x.get("source_id") for x in decisions if isinstance(x, dict) and x.get("decision") == "include"}
            positive = {x["source_id"] for x in labels if x["include"]}
            predicted &= set(ids)
            tp = len(predicted & positive)
            values["screening_precision"] = (tp, len(predicted), None, "Independent benchmark subset only: TP / predicted include; not retrieval precision for the unseen literature.")
            values["screening_recall"] = (tp, len(positive), None, "Independent benchmark subset only: TP / labelled include; not recall of all existing literature.")
        metrics, failed, incomplete = [], False, False
        configurations = {x["id"]: x for x in policy["metrics"]}
        for name in METRIC_IDS:
            numerator, denominator, forced, reason = values[name]
            configuration = configurations.get(name, {"min": None, "severity": "info", "required": False})
            threshold = configuration["min"]
            value = numerator / denominator if denominator not in (None, 0) and numerator is not None else None
            status = forced or ("not_measured" if value is None else "fail" if threshold is not None and value < threshold else "pass")
            if denominator == 0:
                reason += " Denominator is zero; no 100% success is inferred."
            if status == "fail" and configuration["severity"] == "error":
                failed = True
            if status in ("not_measured", "not_applicable") and configuration["required"]:
                incomplete = True
            metrics.append({"id": name, "name": name, "value": value, "numerator": numerator, "denominator": denominator, "threshold": threshold, "status": status, "severity": configuration["severity"], "reason": reason})
        evaluation_paths.update(SCHEMA_FILES)
        import manuscript
        if manuscript.enabled(root):
            evaluation_paths.update(("manuscript.json", "manuscript.md", "manuscript.docx"))
        if analysis.get("status") == "executed":
            evaluation_paths.update(("data/dataset-spec.json", "data/cleaning-log.json", "data/cleaned.csv"))
            for receipt in analysis.get("input_files", []) + analysis.get("artifacts", []) + ([analysis["code"]] if isinstance(analysis.get("code"), dict) else []):
                if isinstance(receipt, dict) and isinstance(receipt.get("path"), str):
                    evaluation_paths.add(local(root, receipt["path"]).relative_to(root).as_posix())
        evaluation_inputs = []
        for relative in sorted(evaluation_paths):
            target = contained_path(root, relative)
            if target.is_file():
                evaluation_inputs.append({"path": relative, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
        result = {"schema_version": 1, "id": "quality-report", "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "metrics": metrics, "overall_status": "fail" if failed else "incomplete" if incomplete else "pass", "policy_sha256": hashlib.sha256(policy_bytes).hexdigest(),
                  "evaluation_config": evaluation_config, "evaluation_inputs": evaluation_inputs,
                  "limitations": ["Structure, registered reviews, citation mapping and numerical reproducibility cannot certify scientific truth or publication quality.", "Precision/recall require independent human labels and describe that benchmark subset only; absent labels remain not_measured.", "No metric estimates comprehensive literature-search recall without an independently specified gold standard."]}
        from contracts import validate
        validate("quality-report", result)
        if write_report:
            write(root, "review/quality-report.json", dumps(result))
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--policy")
    parser.add_argument("--benchmark")
    args = parser.parse_args()
    try:
        result = evaluate(args.project, args.policy, args.benchmark)
        print(dumps(result), end="")
        return 0 if result["overall_status"] == "pass" else 1
    except (ValueError, OSError) as exc:
        print(dumps({"status": "error", "reason": str(exc)}), end="")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
