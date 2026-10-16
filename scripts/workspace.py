#!/usr/bin/env python3
"""Create and inspect a local research workspace using only the standard library.

This tool validates records supplied by the researcher. It does not retrieve
sources, verify their contents, or assess whether evidence is sufficient.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MODES = {"auto", "review", "empirical", "conceptual"}
ACCESS_LEVELS = {"metadata", "abstract", "fulltext"}
VERIFICATION_STATES = {"verified", "unverified"}
SUPPORT_STATES = {"supports", "contradicts", "unclear"}
DIRECTORIES = ("research", "drafts", "review")
REQUIRED_FILES = (
    "project.json",
    "task_plan.md",
    "notes.md",
    "research/sources.json",
    "research/evidence.json",
    "research/search-log.md",
)
LIMITATION = (
    "仅检查项目及证据记录结构；不联网核验来源、不判定学术质量、"
    "证据充分性或投稿就绪。verified 是填写者的核验声明。"
    "来源元数据已核验不代表具体论断已核验。"
)


class WorkspaceError(ValueError):
    """An unsafe path or unsupported workspace operation."""


def project_path(value: str | Path) -> Path:
    """Resolve a user-selected directory without accepting a symlink as root."""
    candidate = Path(value).expanduser()
    if candidate.is_symlink():
        raise WorkspaceError("项目根目录不能是符号链接。")
    return candidate.resolve()


def contained_path(root: Path, relative: str) -> Path:
    """Return a fixed project path, rejecting escapes and linked components."""
    subpath = Path(relative)
    if subpath.is_absolute() or ".." in subpath.parts:
        raise WorkspaceError("项目文件路径必须位于项目目录内。")
    candidate = root / subpath
    current = root
    for component in subpath.parts:
        current = current / component
        if current.is_symlink():
            raise WorkspaceError(f"不读取或写入项目内的符号链接：{relative}")
    try:
        candidate.resolve().relative_to(root)
    except ValueError as exc:
        raise WorkspaceError("项目文件路径越过项目目录边界。") from exc
    return candidate


def init_project(project: str | Path, topic: str, mode: str = "auto") -> dict[str, Any]:
    if not isinstance(topic, str) or not topic.strip():
        raise WorkspaceError("研究主题不能为空。")
    if mode not in MODES:
        raise WorkspaceError(f"不支持的研究模式：{mode}")
    root = project_path(project)
    if root.exists():
        if not root.is_dir():
            raise WorkspaceError("目标路径已存在且不是目录。")
        if any(root.iterdir()):
            raise WorkspaceError("目标目录非空，拒绝覆盖已有项目或文件。")
    elif not root.parent.is_dir():
        raise WorkspaceError("项目父目录不存在；请先创建或选择已有父目录。")

    manifest = {
        "schema_version": 1,
        "topic": topic.strip(),
        "mode": mode,
        "language": "zh-CN",
        "status": "initialized",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    contents = {
        "project.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        "research/sources.json": "[]\n",
        "research/evidence.json": "[]\n",
        "research/search-log.md": (
            "# 检索记录\n\n"
            "记录实际执行的检索，保留未检得或排除的结果。\n\n"
            "| 日期 | 数据库／网站 | 完整检索式 | 筛选条件 | 结果数量 | 纳入来源 ID | 备注 |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
        ),
        "task_plan.md": (
            "# 研究任务计划\n\n"
            "- [ ] 明确研究问题、范围与成果类型\n"
            "- [ ] 制定并记录检索和材料收集方案\n"
            "- [ ] 阅读原文并填写来源及证据记录\n"
            "- [ ] 检查反例、证据局限与研究方法\n"
            "- [ ] 根据证据撰写工作稿\n"
            "- [ ] 复核论断、引用、方法与格式\n\n"
            "当前阶段：研究准备。结构检查通过不代表证据充分或可以投稿。\n"
        ),
        "notes.md": (
            "# 研究笔记\n\n"
            "## 已确认事实\n\n"
            "## 待检验判断\n\n"
            "## 反例与证据局限\n\n"
            "## 待办与研究者决策\n"
        ),
    }
    created_files: list[Path] = []
    created_directories: list[Path] = []
    try:
        if not root.exists():
            root.mkdir()
            created_directories.append(root)
        for relative in DIRECTORIES:
            folder = contained_path(root, relative)
            folder.mkdir()
            created_directories.append(folder)
        for relative, content in contents.items():
            target = contained_path(root, relative)
            # Exclusive creation ensures an unexpected existing file is never replaced.
            with target.open("x", encoding="utf-8") as handle:
                created_files.append(target)
                handle.write(content)
    except (OSError, WorkspaceError):
        # Roll back only entries this invocation created, and never linked entries.
        for target in reversed(created_files):
            if not target.is_symlink():
                target.unlink(missing_ok=True)
        for folder in reversed(created_directories):
            if not folder.is_symlink():
                try:
                    folder.rmdir()
                except OSError:
                    pass
        raise
    return {"project": str(root), "status": "initialized", "files_created": list(contents)}


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def inspect_project(project: str | Path) -> dict[str, Any]:
    root = project_path(project)
    if not root.is_dir():
        raise WorkspaceError("项目目录不存在或不是目录。")
    errors: list[dict[str, str]] = []
    warnings: list[str] = []
    loaded: dict[str, Any] = {}

    def error(code: str, location: str, message: str) -> None:
        errors.append({"code": code, "path": location, "message": message})

    for relative in DIRECTORIES:
        try:
            target = contained_path(root, relative)
            if not target.is_dir():
                error("missing_directory", relative, "缺少项目目录。")
        except WorkspaceError as exc:
            error("unsafe_path", relative, str(exc))
    for relative in REQUIRED_FILES:
        try:
            target = contained_path(root, relative)
            if not target.is_file():
                error("missing_file", relative, "缺少项目文件。")
                continue
            if target.suffix == ".json":
                loaded[relative] = json.loads(target.read_text(encoding="utf-8"))
        except WorkspaceError as exc:
            error("unsafe_path", relative, str(exc))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            error("unreadable_json", relative, f"无法读取有效 UTF-8 JSON：{exc}")

    manifest = loaded.get("project.json")
    if "project.json" in loaded:
        if not isinstance(manifest, dict):
            error("invalid_manifest", "project.json", "项目配置必须是 JSON 对象。")
        else:
            if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
                error("invalid_schema_version", "project.json/schema_version", "schema_version 必须为整数 1。")
            for field in ("topic", "status", "created_at"):
                if not _nonempty_string(manifest.get(field)):
                    error("missing_field", f"project.json/{field}", "此字段必须是非空字符串。")
            if not isinstance(manifest.get("mode"), str) or manifest["mode"] not in MODES:
                error("invalid_mode", "project.json/mode", "mode 必须为 auto、review、empirical 或 conceptual。")
            if manifest.get("language") != "zh-CN":
                error("invalid_language", "project.json/language", "language 必须为 zh-CN。")
            if _nonempty_string(manifest.get("created_at")):
                try:
                    datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00"))
                except ValueError:
                    error("invalid_timestamp", "project.json/created_at", "created_at 必须为 ISO 8601 日期时间。")

    sources = loaded.get("research/sources.json", [])
    evidence = loaded.get("research/evidence.json", [])
    for name, value in (("sources", sources), ("evidence", evidence)):
        if not isinstance(value, list):
            error("invalid_collection", f"research/{name}.json", "记录集合必须为 JSON 数组。")
    sources = sources if isinstance(sources, list) else []
    evidence = evidence if isinstance(evidence, list) else []
    by_id: dict[str, dict[str, Any]] = {}
    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        location = f"research/sources.json/{index}"
        if not isinstance(source, dict):
            error("invalid_record", location, "每条来源记录必须为 JSON 对象。")
            continue
        for field in ("id", "title", "url"):
            if not _nonempty_string(source.get(field)):
                error("missing_field", f"{location}/{field}", "此字段必须是非空字符串。")
        source_id = source.get("id")
        if _nonempty_string(source_id):
            if source_id in source_ids:
                error("duplicate_id", f"{location}/id", "来源 ID 重复。")
            source_ids.add(source_id)
            by_id[source_id] = source
        if not isinstance(source.get("access_level"), str) or source["access_level"] not in ACCESS_LEVELS:
            error("invalid_access_level", f"{location}/access_level", "必须为 metadata、abstract 或 fulltext。")
        if not isinstance(source.get("metadata_status"), str) or source["metadata_status"] not in VERIFICATION_STATES:
            error("invalid_metadata_status", f"{location}/metadata_status", "必须为 verified 或 unverified。")
        if "doi" in source and not _nonempty_string(source["doi"]):
            error("invalid_doi", f"{location}/doi", "doi 如填写，必须为非空字符串；无 DOI 时省略此字段。")

    evidence_ids: set[str] = set()
    qualifying_ids: list[str] = []
    for index, record in enumerate(evidence):
        location = f"research/evidence.json/{index}"
        if not isinstance(record, dict):
            error("invalid_record", location, "每条证据记录必须为 JSON 对象。")
            continue
        for field in ("id", "source_id", "claim", "locator"):
            if not _nonempty_string(record.get(field)):
                error("missing_field", f"{location}/{field}", "此字段必须是非空字符串。")
        record_id = record.get("id")
        if _nonempty_string(record_id):
            if record_id in evidence_ids:
                error("duplicate_id", f"{location}/id", "证据 ID 重复。")
            evidence_ids.add(record_id)
        if not isinstance(record.get("support_status"), str) or record["support_status"] not in SUPPORT_STATES:
            error("invalid_support_status", f"{location}/support_status", "必须为 supports、contradicts 或 unclear。")
        if not isinstance(record.get("claim_verification"), str) or record["claim_verification"] not in VERIFICATION_STATES:
            error("invalid_claim_verification", f"{location}/claim_verification", "具体论断必须独立标为 verified 或 unverified；不能由元数据状态推定。")
        source_id = record.get("source_id")
        source = by_id.get(source_id) if isinstance(source_id, str) else None
        if _nonempty_string(source_id) and source is None:
            error("dangling_source_id", f"{location}/source_id", "证据引用的来源 ID 不存在。")
        if source and source.get("access_level") == "fulltext" and source.get("metadata_status") == "verified":
            if (
                record.get("claim_verification") == "verified"
                and record.get("support_status") in ("supports", "contradicts")
                and all(_nonempty_string(record.get(field)) for field in ("id", "claim", "locator"))
            ):
                qualifying_ids.append(record["id"])

    if not sources:
        warnings.append("来源库为空；请先检索并记录实际来源。")
    if not evidence:
        warnings.append("证据库为空；可以继续检索或制定研究问题卡。")
    if not qualifying_ids:
        warnings.append(
            "尚无符合最低门槛的全文证据记录：需要完整可读来源、已核验元数据、"
            "独立核验的具体论断、非空定位，以及支持或反驳关系。"
            "仅摘要或元数据不能支撑实质论文论断。"
        )
    ready = not errors and bool(qualifying_ids)
    return {
        "project": str(root),
        "topic": manifest.get("topic") if isinstance(manifest, dict) else None,
        "project_status": manifest.get("status") if isinstance(manifest, dict) else None,
        "readiness": "evidence_record_structure_ready" if ready else "not_ready",
        "structure_valid": not errors,
        "counts": {"sources": len(sources), "evidence": len(evidence), "qualifying_fulltext_evidence": len(qualifying_ids)},
        "qualifying_evidence_ids": qualifying_ids,
        "errors": errors,
        "warnings": warnings,
        "limitation": LIMITATION,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="创建和检查本地科研项目；不联网。")
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("init", help="初始化新项目；拒绝覆盖非空目录")
    initialize.add_argument("--project", required=True)
    initialize.add_argument("--topic", required=True)
    initialize.add_argument("--mode", choices=sorted(MODES), default="auto")
    for name in ("status", "check"):
        command = commands.add_parser(name, help="查看状态" if name == "status" else "检查结构及最低证据记录门槛")
        command.add_argument("--project", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = init_project(args.project, args.topic, args.mode)
        else:
            result = inspect_project(args.project)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "check":
            if result["errors"]:
                return 2
            if result["readiness"] == "not_ready":
                return 1
        return 0
    except (WorkspaceError, OSError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
