#!/usr/bin/env python3
"""Export a completed local research project using a closed file allowlist."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

import pipeline
import workspace

REQUIRED = {"project.json", "pipeline-state.json", "events.jsonl"} | {
    name for outputs, _ in pipeline.STAGES.values() for name in outputs}
OPTIONAL_TREES = {
    "research/search-responses": {".json"},
    "research/texts": {".txt", ".md", ".pdf"},
    "research/analysis-code": {".py", ".r", ".ipynb", ".json", ".csv", ".tsv", ".md", ".txt", ".yaml", ".yml"},
}
STRUCTURED_TREES = {
    "research/search-requests": {".json"},
    "model-io": {".json"},
    "decisions": {".json", ".jsonl"},
    "analysis-code": {".py", ".r", ".ipynb", ".json", ".csv", ".tsv", ".md", ".txt", ".yaml", ".yml"},
    "data/frozen": {".csv", ".tsv", ".json", ".txt"},
    "runtime-snapshot": {".py", ".json", ".txt"},
    "runtime-snapshot/shared/research-core/references": {".md"},
}
SENSITIVE_NAME = re.compile(r"(^|[-_.])(auth|secrets?|credentials?|passwords?|private[-_]?key|contributor[-_]?info)([-_.]|$)", re.I)
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----"),
    re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(rb"\b(?:ghp_|github_pat_|sk-proj-|sk-ant-)[A-Za-z0-9_-]{20,}\b"),
)
NOTICE = "本地研究材料包；原文可访问或保存在本机不代表获准公开分发。白名单与凭据模式检查不等于完整个人信息审查；对外分享前应单独核查许可、隐私和研究资料授权。"
README = ("# 本地科研成果包\n\n" + NOTICE + "\n\n"
          "本包由项目白名单生成，不递归导出工作目录、个人技能、身份资料、Git 历史或 delivery。\n"
          "manifest.json 记录每个载荷文件的 SHA-256 与大小；清单自身不递归自哈希。\n"
          "固定 ZIP 条目时间、权限、文件顺序及无压缩模式保证相同输入得到相同 ZIP。\n"
          "阶段 complete 代表已通过结构检查；不证明研究结论真实、证据充分或已可投稿。\n")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe_explicit_path(root, relative):
    """Validate a declared artifact without admitting configuration or identity files."""
    target = pipeline.path(root, relative)
    parts = Path(relative).parts
    if (not parts or any(part.startswith(".") or SENSITIVE_NAME.search(part) for part in parts)
            or parts[0] == "delivery"):
        raise workspace.WorkspaceError(f"声明产物不能指向配置、身份资料或导出目录：{relative}")
    return target


def analysis_receipts(root, state):
    """Only the structured analysis result may explicitly add original data paths."""
    if not pipeline.structured(state):
        return []
    import contracts
    result = contracts.load_validate("analysis-result", pipeline.path(root, "research/analysis-result.json"))
    if result["status"] != "executed":
        return []
    receipts = result["input_files"] + [result["code"]] + result.get("artifacts", [])
    for receipt in receipts:
        safe_explicit_path(root, receipt["path"])
    return receipts


def quality_receipts(root, state):
    """Admit only the actual project-local inputs recorded by quality evaluation."""
    if not pipeline.structured(state):
        return []
    import contracts
    report = contracts.load_validate("quality-report", pipeline.path(root, "review/quality-report.json"))
    receipts = report.get("evaluation_inputs", [])
    for receipt in receipts:
        safe_explicit_path(root, receipt["path"])
    return receipts


def selected_files(root, state=None):
    state = state or {}
    names = set(REQUIRED)
    trees = dict(OPTIONAL_TREES)
    if pipeline.structured(state):
        names = {"project.json", "pipeline-state.json", "events.jsonl", "pipeline-policy.json"}
        names.update(name for stage in pipeline.NAMES for name in pipeline.outputs(stage, state))
        trees.update(STRUCTURED_TREES)
        names.update(receipt["path"] for receipt in analysis_receipts(root, state))
        names.update(receipt["path"] for receipt in quality_receipts(root, state))
        if pipeline.path(root, "quality-policy.json").exists():
            names.add("quality-policy.json")
        if pipeline.path(root, "engine-manifest.json").exists():
            names.add("engine-manifest.json")
        if pipeline.path(root, "research/screening-history.jsonl").exists():
            names.add("research/screening-history.jsonl")
    for prefix, extensions in trees.items():
        folder = pipeline.path(root, prefix)
        if not folder.exists():
            continue
        if not folder.is_dir():
            raise workspace.WorkspaceError(f"白名单原文/代码目录不是目录：{prefix}")
        stack = [folder]
        while stack:
            current = stack.pop()
            for item in sorted(current.iterdir()):
                relative = item.relative_to(root).as_posix()
                item = pipeline.path(root, relative)  # Reject all symlinks, including directories.
                if item.name.startswith(".") or SENSITIVE_NAME.search(item.name):
                    continue
                if item.is_dir():
                    stack.append(item)
                elif item.is_file() and item.suffix.lower() in extensions:
                    names.add(relative)
    return sorted(names)


def build(root, state):
    payload = {}
    expected = {}
    for record in state["stages"].values():
        for group in ("inputs", "outputs", "source_texts", "tracked"):
            for relative, value in record.get(group, {}).items():
                if relative in expected and expected[relative] != value:
                    raise workspace.WorkspaceError(f"阶段哈希记录冲突：{relative}")
                expected[relative] = value
    for receipt in analysis_receipts(root, state) + quality_receipts(root, state):
        if receipt["path"] in expected and expected[receipt["path"]] != receipt["sha256"]:
            raise workspace.WorkspaceError(f"产物声明与阶段哈希冲突：{receipt['path']}")
        expected[receipt["path"]] = receipt["sha256"]
    names = selected_files(root, state)
    omitted = set(expected) - set(names)
    if omitted:
        raise workspace.WorkspaceError(f"追踪产物不在封闭导出白名单，拒绝丢弃血缘：{sorted(omitted)}")
    for relative in names:
        safe_explicit_path(root, relative)
        target = pipeline.path(root, relative)
        if not target.is_file():
            raise workspace.WorkspaceError(f"白名单必需文件缺失：{relative}")
        data = target.read_bytes()
        if relative in expected and sha(data) != expected[relative]:
            raise workspace.WorkspaceError(f"读取过程中已完成产物改变：{relative}；重新核验阶段后导出。")
        if any(pattern.search(data) for pattern in SECRET_PATTERNS):
            raise workspace.WorkspaceError(f"检测到疑似凭据，未生成成果包：{relative}")
        payload[relative] = data
    payload["BUNDLE_README.md"] = README.encode("utf-8")
    is_structured = pipeline.structured(state)
    quality_gate = {"status": "not_available", "report_path": None, "policy_sha256": None}
    if is_structured:
        import contracts
        report = contracts.load_validate("quality-report", pipeline.path(root, "review/quality-report.json"))
        if report["overall_status"] != "pass":
            raise workspace.WorkspaceError("必需质量门禁未通过，拒绝导出。")
        quality_gate = {"status": report["overall_status"], "report_path": "review/quality-report.json",
                        "policy_sha256": report.get("policy_sha256"),
                        "evaluation_config": report.get("evaluation_config")}
    manifest = {
        "schema_version": 1, "scope": "local_only", "notice": NOTICE,
        "profile": "structured" if is_structured else "legacy", "quality_gate": quality_gate,
        "privacy_check": "closed_file_allowlist_and_known_secret_patterns_not_personal_data_certification",
        "stage_status": "schema_and_required_quality_gates_complete" if is_structured else "structurally_complete",
        "analysis_disposition": state["stages"]["analyze"].get("disposition", "unknown"),
        "snapshot_status": state["stages"]["read"].get("snapshot_status", "not_registered"),
        "manifest_self_hash": "excluded_to_avoid_recursive_hash",
        "files": [{"path": relative, "sha256": sha(data), "size": len(data)}
                  for relative, data in sorted(payload.items())],
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    payload["manifest.json"] = manifest_bytes
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for relative, data in sorted(payload.items()):
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return buffer.getvalue(), manifest_bytes, manifest


def atomic_write(target, data):
    fd, name = tempfile.mkstemp(prefix=".bundle-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def export(project, name="research-bundle.zip", force=False):
    root = workspace.project_path(project)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}\.zip", name):
        raise workspace.WorkspaceError("name 只能是安全的 .zip 文件名，输出固定在项目 delivery/。")
    with pipeline.locked(root):
        state = pipeline.load(root)
        pipeline.refresh(root, state)
        if pipeline.view(state)["status"] != "complete":
            raise workspace.WorkspaceError("项目尚未完成或已失效；先完成 next 返回的阶段。")
        _, changed = pipeline.source_snapshots(root)
        if changed:
            raise workspace.WorkspaceError("登记原文哈希不一致，拒绝导出。")
        archive_bytes, manifest_bytes, manifest = build(root, state)
        folder = pipeline.path(root, "delivery")
        archive_path = pipeline.path(root, "delivery/" + name)
        manifest_path = pipeline.path(root, "delivery/" + name[:-4] + ".manifest.json")
        outputs = ((archive_path, archive_bytes), (manifest_path, manifest_bytes))
        for target, data in outputs:
            if target.exists() and (not target.is_file() or target.read_bytes() != data) and not force:
                raise workspace.WorkspaceError("存在不同的同名本地成果；使用其他 --name 或明确 --force 后才可替换。")
            if target.exists() and not target.is_file():
                raise workspace.WorkspaceError("输出目标不是普通文件。")
        folder.mkdir(exist_ok=True)
        unchanged = all(target.exists() and target.read_bytes() == data for target, data in outputs)
        for target, data in outputs:
            if not target.exists() or target.read_bytes() != data:
                atomic_write(target, data)
        return {"status": "unchanged" if unchanged else "exported", "archive": str(archive_path),
                "manifest": str(manifest_path), "sha256": sha(archive_bytes), "size": len(archive_bytes),
                "payload_files": len(manifest["files"]), "notice": NOTICE}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--name", default="research-bundle.zip")
    parser.add_argument("--force", action="store_true", help="仅允许替换同名本地成果；不会上传。")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(export(args.project, args.name, args.force), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
