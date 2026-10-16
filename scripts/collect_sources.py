#!/usr/bin/env python3
"""Keyless Crossref/ERIC collection; metadata retrieval never verifies claims."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import urllib.parse
import urllib.request

import workspace
from providers import doi, normalized, make_provider, run_search, ProviderFailure


def path(root, relative):
    return workspace.contained_path(root, relative)


def project(value):
    root = workspace.project_path(value)
    if not root.is_dir() or not path(root, "project.json").is_file():
        raise workspace.WorkspaceError("需要已初始化的科研项目。")
    return root


@contextmanager
def locked(root):
    with path(root, ".pipeline.lock").open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def read_records(root, relative):
    target = path(root, relative)
    data = json.loads(target.read_text(encoding="utf-8")) if target.exists() else []
    if not isinstance(data, list) or any(not isinstance(x, dict) for x in data):
        raise workspace.WorkspaceError(f"{relative} 必须是记录数组，拒绝覆盖。")
    return data


def save(root, relative, data):
    target = path(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".collect-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path(root, relative))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def identities(record):
    keys = set()
    url = str(record.get("url", ""))
    doi_value = record.get("doi") or (url if re.match(r"https?://(?:dx\.)?doi\.org/", url, re.I) else "")
    if doi_value:
        keys.add("doi:" + doi(doi_value))
    if record.get("eric_id"):
        keys.add("eric:" + str(record["eric_id"]).upper())
    parsed = urllib.parse.urlparse(url)
    eric_id = urllib.parse.parse_qs(parsed.query).get("id", [""])[0] if parsed.hostname == "eric.ed.gov" else ""
    eric = re.fullmatch(r"(?:ERIC_)?((?:ED|EJ)\d+)", eric_id or str(record.get("id", "")), re.I)
    if eric:
        keys.add("eric:" + eric[1].upper())
    if record.get("id"):
        keys.add("id:" + str(record["id"]))
    return keys


def merge(existing, incoming):
    """Keep existing IDs, reading status, evidence, and all user-supplied fields."""
    result = [dict(x) for x in existing]
    for item in incoming:
        match = next((old for old in result if identities(old) & identities(item)), None)
        if match is None:
            result.append(dict(item))
        else:
            for key, value in item.items():
                if key not in match:
                    match[key] = value
    return result


def search(root, query, eric_query=None, limit=5, provider_names=None, provider_options=None, max_attempts=1, filters=None, provider_queries=None):
    if not query.strip() or not 1 <= limit <= 100:
        raise workspace.WorkspaceError("query 不能为空，limit 必须为 1–100。")
    names = provider_names if provider_names is not None else ["crossref", "eric"]
    if not names or len(names) != len(set(names)):
        raise workspace.WorkspaceError("providers 必须为非空且不重复的名称列表。")
    if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
        raise workspace.WorkspaceError("max-attempts 必须为 1–5。")
    filters = filters or {"year_min": None, "year_max": None}
    from contracts import validate
    request = {"schema_version": 1, "id": "collector-query", "query": query, "providers": names,
               "limit": limit, "filters": filters}
    if provider_queries:
        request["provider_queries"] = provider_queries
    validate("search-query", request)
    if (filters.get("year_min") is not None and filters.get("year_max") is not None
            and filters["year_min"] > filters["year_max"]):
        raise workspace.WorkspaceError("year_min cannot exceed year_max")
    if set(provider_queries or {}) - set(names):
        raise workspace.WorkspaceError("provider_queries contains an unselected provider")
    requests = [(name, make_provider(name, (provider_options or {}).get(name))) for name in names]
    with locked(root):
        existing = read_records(root, "research/sources.json")
        previous_candidates = read_records(root, "research/search-results.json")
        log_path = path(root, "research/search-log.md")
        responses = path(root, "research/search-responses")
        responses.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        records, outcomes = [], []
        for provider, adapter in requests:
            text = (provider_queries or {}).get(provider) or ((eric_query or query) if provider == "eric" else query)
            outcome = {"provider": provider, "query": text, "at": stamp}
            try:
                result = run_search(adapter, text, limit, max_attempts=max_attempts)
                relative = f"research/search-responses/{stamp}-{provider}.json"
                path(root, relative).write_bytes(result["raw"])
                candidates = result["records"]
                found, excluded = [], []
                for item in candidates:
                    year = item.get("year")
                    bounded = filters["year_min"] is not None or filters["year_max"] is not None
                    outside = bounded and (year is None or
                        (filters["year_min"] is not None and year < filters["year_min"]) or
                        (filters["year_max"] is not None and year > filters["year_max"]))
                    if outside:
                        excluded.append({"id": item["id"], "reason": "year_missing" if year is None else "year_outside_filter"})
                    else:
                        found.append(item)
                for item in found:
                    item["retrieved_at"], item["raw_response"] = stamp, relative
                records.extend(found)
                outcome.update(status="ok", count=len(found), raw_response=relative,
                               url=result["url"], attempts=result["attempts"],
                               filters=filters, filter_excluded=excluded, retrieved_count=len(candidates))
            except ProviderFailure as exc:
                outcome.update(status="error", count=0, error=str(exc), url=exc.url, attempts=exc.attempts)
                if exc.raw is not None:
                    relative = f"research/search-responses/{stamp}-{provider}-invalid.json"
                    path(root, relative).write_bytes(exc.raw)
                    outcome["raw_response"] = relative
                save(root, f"research/search-responses/{stamp}-{provider}-error.json", outcome)
            outcomes.append(outcome)
        successes = sum(o["status"] == "ok" for o in outcomes)
        status = "ok" if successes == len(names) else "partial" if successes else "failed"
        unique = merge([], records)
        if successes:
            save(root, "research/sources.json", merge(existing, unique))
            if unique or status == "ok":
                save(root, "research/search-results.json", merge(previous_candidates, unique))
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n## API 检索 {stamp} · {status}\n\n")
            for o in outcomes:
                handle.write("- " + json.dumps(o, ensure_ascii=False) + "\n")
        return {"status": status, "count": len(unique), "providers": outcomes,
                "limitation": "仅检索候选与元数据；未阅读全文，未核验论断。"}


def search_request(root, request, provider_options=None, max_attempts=1):
    from contracts import validate
    validate("search-query", request)
    request_bytes = json.dumps(request, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    request_file = "research/search-requests/" + hashlib.sha256(request_bytes).hexdigest() + ".json"
    with locked(root):
        save(root, request_file, request)
    result = search(root, request["query"], limit=request["limit"], provider_names=request["providers"],
                    provider_options=provider_options, max_attempts=max_attempts,
                    filters=request["filters"], provider_queries=request.get("provider_queries"))
    result["request_id"], result["request_file"] = request["id"], request_file
    return result


def capture(root, source_id, input_path):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", source_id):
        raise workspace.WorkspaceError("source-id 必须是安全文件名。")
    with locked(root):
        records = read_records(root, "research/sources.json")
        source = next((x for x in records if x.get("id") == source_id), None)
        if source is None:
            raise workspace.WorkspaceError("source-id 尚未登记。")
        incoming = Path(input_path).expanduser()
        if incoming.is_symlink() or not incoming.is_file():
            raise workspace.WorkspaceError("输入必须是普通文本文件，不能是符号链接。")
        content = incoming.read_bytes()
        if not content.decode("utf-8").strip():
            raise workspace.WorkspaceError("输入必须是非空 UTF-8 文本。")
        relative = f"research/texts/{source_id}.txt"
        target = path(root, relative)
        if target.exists() and target.read_bytes() != content:
            raise workspace.WorkspaceError("已存在不同原文，拒绝覆盖；请先核对来源版本。")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        source.update(local_text=relative, content_sha256=hashlib.sha256(content).hexdigest())
        save(root, "research/sources.json", records)
        return {"status": "captured", "source_id": source_id, "local_text": relative,
                "content_sha256": source["content_sha256"],
                "limitation": "文本已保存；阅读等级与论断核验状态未提升。"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    lookup = sub.add_parser("search")
    lookup.add_argument("--project", required=True)
    terms = lookup.add_mutually_exclusive_group(required=True)
    terms.add_argument("--query")
    terms.add_argument("--request", help="JSON validated with search-query schema; replaces query/providers/limit")
    lookup.add_argument("--eric-query")
    lookup.add_argument("--limit", type=int, default=5)
    lookup.add_argument("--providers", default="crossref,eric", help="comma-separated registered provider names")
    lookup.add_argument("--local-json", help="normalized local source array, required for local-json provider")
    lookup.add_argument("--max-attempts", type=int, default=1)
    copy = sub.add_parser("capture")
    copy.add_argument("--project", required=True)
    copy.add_argument("--source-id", required=True)
    copy.add_argument("--input", required=True)
    args = parser.parse_args(argv)
    try:
        root = project(args.project)
        if args.command == "search":
            options = {"local-json": {"file": args.local_json}} if args.local_json else {}
            if args.request:
                from contracts import load_validate
                request = load_validate("search-query", args.request)
                result = search_request(root, request, options, args.max_attempts)
            else:
                result = search(root, args.query, args.eric_query, args.limit,
                                [name.strip() for name in args.providers.split(",")], options, args.max_attempts)
        else:
            result = capture(root, args.source_id, args.input)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["status"] == "failed" else 0
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
