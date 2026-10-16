#!/usr/bin/env python3
"""Local stage ledger. Codex executes the tasks returned by next; no model calls."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

import workspace

LIMITATION = "仅调度并检查文件/证据记录结构与哈希；不证明学术真实性、充分性或投稿就绪。任务由当前 Codex 执行。"
MAX_FAILURES = 3
STAGES = {
    "scope": (("question.md",), ("research-ideation",)),
    "search": (("research/search-results.json", "research/search-log.md"), ("academic-research-suite", "autonomous-research")),
    "read": (("research/sources.json", "research/reading-notes.md", "research/evidence.json"), ("literature-reading-and-synthesis",)),
    "synthesize": (("research/synthesis.md",), ("literature-reading-and-synthesis", "map-literature-contradictions")),
    "design": (("research/study-plan.md",), ("research-ideation", "experimental-design", "statistical-power")),
    "analyze": (("research/analysis.md",), ("statistical-analysis", "statsmodels", "scientific-visualization", "interview-analyst")),
    "package": (("report.md",), ("documents", "pdf")),
    "review": (("review/audit.md",), ("paper-self-review",)),
}
NAMES = list(STAGES)
STATES = {"pending", "succeeded", "failed", "blocked", "stale", "running"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def path(root, relative):
    return workspace.contained_path(root, relative)


def digest(root, relative):
    target = path(root, relative)
    return hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None


def structured(state):
    return state.get("profile") == "structured"


def outputs(stage, state):
    extra = []
    if structured(state):
        import stage_contracts
        extra = list(stage_contracts.ARTIFACTS[stage])
    if stage == "package" and state.get("deliverable_profile") == "manuscript":
        extra += ["manuscript.json", "manuscript.md", "manuscript.docx"]
    return list(dict.fromkeys(list(STAGES[stage][0]) + extra))


def inputs(stage, state=None):
    state = state or {}
    base = ["project.json"] + (["pipeline-policy.json"] if structured(state) else [])
    return base + [f for s in NAMES[:NAMES.index(stage)] for f in outputs(s, state)]


def human_pending(root, stage):
    folder = path(root, "decisions")
    pending = []
    if folder.exists():
        import contracts
        for f in folder.glob("*.json"):
            record = contracts.load_validate("human-decision", path(root, f.relative_to(root).as_posix()))
            if record["stage"] == stage and record["status"] == "requested": pending.append(record["id"])
    return pending


@contextmanager
def locked(root):
    with path(root, ".pipeline.lock").open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise workspace.WorkspaceError("项目正被另一调度进程使用。") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def save(root, state, event, stage=None, detail=None):
    state["updated_at"] = now()
    state["event_count"] += 1
    record = {"seq": state["event_count"], "at": state["updated_at"], "event": event,
              "stage": stage, "detail": detail or {}}
    state_file = path(root, "pipeline-state.json")
    event_file = path(root, "events.jsonl")
    # Event first: an interrupted state save leaves an observable attempt.
    with event_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    fd, name = tempfile.mkstemp(prefix=".pipeline-", suffix=".json", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, state_file)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def source_snapshots(root):
    records = json.loads(path(root, "research/sources.json").read_text(encoding="utf-8"))
    snapshots, mismatches = {}, []
    for source in records:
        if not isinstance(source, dict) or "local_text" not in source:
            continue
        relative = source["local_text"]
        if not isinstance(relative, str) or not relative.startswith("research/texts/"):
            raise workspace.WorkspaceError("local_text 必须指向项目 research/texts/ 内的原文。")
        actual, expected = digest(root, relative), source.get("content_sha256")
        if not actual or actual != expected:
            mismatches.append(relative)
        else:
            snapshots[relative] = actual
    return snapshots, mismatches


def load(root):
    state = json.loads(path(root, "pipeline-state.json").read_text(encoding="utf-8"))
    if (not isinstance(state, dict) or state.get("schema_version") != 1
            or not isinstance(state.get("stages"), dict) or list(state["stages"]) != NAMES
            or type(state.get("event_count")) is not int):
        raise workspace.WorkspaceError("调度状态格式损坏，拒绝推定已完成。")
    for stage, record in state["stages"].items():
        if (not isinstance(record, dict) or record.get("status") not in STATES
                or type(record.get("failures")) is not int or record["failures"] < 0):
            raise workspace.WorkspaceError(f"阶段状态损坏：{stage}")
        if record["status"] == "succeeded":
            for key, expected in (("inputs", inputs(stage, state)), ("outputs", outputs(stage, state))):
                hashes = record.get(key)
                if (not isinstance(hashes, dict) or set(hashes) != set(expected)
                        or any(not isinstance(h, str) or len(h) != 64 or any(c not in "0123456789abcdef" for c in h) for h in hashes.values())):
                    raise workspace.WorkspaceError(f"阶段哈希记录不完整：{stage}/{key}")
    log = path(root, "events.jsonl")
    try:
        entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        valid = (len(entries) == state["event_count"]
                 and all(isinstance(e, dict) and e.get("seq") == n for n, e in enumerate(entries, 1)))
    except (OSError, ValueError):
        valid = False
    if not valid:
        raise workspace.WorkspaceError("events.jsonl 与 pipeline-state.json 不一致，可能有中断的未提交尾记录；保留两文件并核对修复日志尾部后再继续，不能推定已完成。")
    return state


def refresh(root, state):
    changed = []
    upstream_stale = False
    for stage, record in state["stages"].items():
        if record["status"] == "succeeded":
            mismatches = [f for group in ("inputs", "outputs", "tracked")
                          for f, old in record.get(group, {}).items() if digest(root, f) != old]
            if stage == "read":
                try:
                    snapshots, source_mismatches = source_snapshots(root)
                    mismatches.extend(source_mismatches)
                    mismatches.extend(f for f, old in record.get("source_texts", {}).items()
                                      if snapshots.get(f) != old)
                except (OSError, ValueError, TypeError):
                    mismatches.append("research/sources.json:local_text")
            if upstream_stale or mismatches:
                record.update(status="stale", reason="upstream_changed" if upstream_stale else "artifact_changed",
                              changed_files=sorted(set(mismatches)))
                changed.append(stage)
        if record["status"] != "succeeded":
            upstream_stale = True
    if changed:
        save(root, state, "invalidated", detail={"stages": changed})


def view(state):
    stage = next((s for s in NAMES if state["stages"][s]["status"] != "succeeded"), None)
    result = {"status": "complete" if stage is None else "in_progress", "next": None,
              "stages": state["stages"], "limitation": LIMITATION}
    if stage:
        record = state["stages"][stage]
        max_failures = state.get("policy", {}).get("max_failures", MAX_FAILURES)
        waiting = bool(record.get("next_retry_at") and now() < record["next_retry_at"])
        pending_humans = record.get("human_decision_ids", [])
        blocked = record["status"] == "blocked" or record["failures"] >= max_failures or bool(pending_humans)
        result["status"] = "blocked" if blocked else "in_progress"
        result["next"] = {"stage": stage, "runnable": not blocked and not waiting,
                          "dependencies": NAMES[:NAMES.index(stage)],
                          "skills": list(STAGES[stage][1]), "required_artifacts": outputs(stage, state),
                          "inputs": inputs(stage, state), "reason": record.get("reason", ""),
                          "action": "resolve blocker then retry --stage" if blocked else "execute with Codex tools then complete --stage"}
        if structured(state):
            import contracts
            result["next"].update(schema_version=1, id="task-"+stage, status=record["status"],
                                  retry={"attempt":record["failures"],"max_attempts":max_failures,
                                         "next_retry_at":record.get("next_retry_at")},
                                  human_decision_ids=pending_humans)
            contracts.validate("stage-task", result["next"])
    return result


def initialize(root, topic, profile="legacy", deliverable_profile=None):
    if deliverable_profile not in (None, "manuscript", "report"):
        raise workspace.WorkspaceError("Unknown deliverable profile")
    if deliverable_profile == "manuscript" and profile != "structured":
        raise workspace.WorkspaceError("manuscript requires structured profile")
    if not root.exists() or not any(root.iterdir()):
        workspace.init_project(root, topic)
    else:
        report = workspace.inspect_project(root)
        if not report["structure_valid"] or report["topic"] != topic:
            raise workspace.WorkspaceError("已有目录不是同主题有效项目，拒绝覆盖。")
    with locked(root):
        if path(root, "pipeline-state.json").exists() or path(root, "events.jsonl").exists():
            raise workspace.WorkspaceError("已有流水线状态；请使用 next/status 继续。")
        state = {"schema_version": 1, "topic": topic, "created_at": now(), "event_count": 0,
                 "stages": {s: {"status": "pending", "failures": 0} for s in NAMES}}
        if deliverable_profile is not None:
            state["deliverable_profile"] = deliverable_profile
        if profile == "structured":
            import contracts
            import provenance
            provenance.capture(root)
            policy={"schema_version":1,"id":"pipeline-policy","max_failures":3,"backoff_seconds":1.0,"max_backoff_seconds":30.0}
            contracts.validate("pipeline-policy",policy)
            policy_path=path(root,"pipeline-policy.json")
            if policy_path.exists(): policy=contracts.load_validate("pipeline-policy",policy_path)
            else: policy_path.write_text(json.dumps(policy,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
            state.update(profile="structured",policy=policy)
        save(root, state, "initialized")
    return view(state)


def validate(root, stage, disposition, reason, state=None):
    state = state or {}
    for relative in outputs(stage, state):
        target = path(root, relative)
        if not target.is_file() or not target.stat().st_size:
            raise workspace.WorkspaceError(f"缺少非空必需产物：{relative}")
        if target.suffix != ".docx" and not target.read_text(encoding="utf-8").strip():
            raise workspace.WorkspaceError(f"缺少非空必需产物：{relative}")
    check = workspace.inspect_project(root)
    if not check["structure_valid"]:
        raise workspace.WorkspaceError("证据结构错误：" + json.dumps(check["errors"], ensure_ascii=False))
    if stage == "search":
        candidates = json.loads(path(root, "research/search-results.json").read_text(encoding="utf-8"))
        if (not isinstance(candidates, list) or not candidates
                or any(not isinstance(c, dict) or any(not isinstance(c.get(k), str) or not c[k].strip()
                                                     for k in ("id", "title", "url")) for c in candidates)):
            raise workspace.WorkspaceError("检索候选须为非空数组；每条必须包含 id/title/url。")
        if len({c["id"] for c in candidates}) != len(candidates):
            raise workspace.WorkspaceError("检索候选 id 重复。")
    if NAMES.index(stage) >= NAMES.index("read") and not check["qualifying_evidence_ids"]:
        raise workspace.WorkspaceError("至少需要一条独立核验且可定位的全文证据；metadata/abstract 不可通过。")
    if NAMES.index(stage) >= NAMES.index("read"):
        _, mismatches = source_snapshots(root)
        if mismatches:
            raise workspace.WorkspaceError("原文快照与登记哈希不一致：" + ", ".join(mismatches))
    if disposition != "executed" and (stage != "analyze" or not reason.strip()):
        raise workspace.WorkspaceError("planned/not_applicable 只用于 analyze，必须说明原因。")
    if stage == "analyze" and disposition != "executed":
        text = path(root, STAGES[stage][0][0]).read_text(encoding="utf-8")
        if disposition not in text or reason.strip() not in text:
            raise workspace.WorkspaceError("analysis.md 须包含 disposition 及同一未执行原因。")

    if structured(state):
        import stage_contracts
        stage_contracts.validate_stage(root,stage,disposition)
        if stage in ("package", "review") and state.get("deliverable_profile") == "manuscript":
            import manuscript
            manuscript.validate_project(root)


def operate(root, command, stage=None, reason="", disposition="executed"):
    with locked(root):
        state = load(root)
        refresh(root, state)
        if structured(state):
            import contracts
            state["policy"]=contracts.load_validate("pipeline-policy",path(root,"pipeline-policy.json"))
            for key,rec in state["stages"].items(): rec["human_decision_ids"]=human_pending(root,key)
        if command in ("next", "status"):
            return view(state)
        if structured(state):
            import provenance
            provenance.assert_execution(root)
        record = state["stages"][stage]
        first = view(state)["next"]
        if not first or first["stage"] != stage:
            raise workspace.WorkspaceError("只能操作下一待处理阶段；先解决前置阶段或检查已有产物。")
        if command == "start":
            if not first["runnable"]: raise workspace.WorkspaceError("阶段等待重试时间或人工输入。")
            record.update(status="running",started_at=now())
        elif command == "retry":
            if record["status"] not in ("failed", "blocked"):
                raise workspace.WorkspaceError("只有失败或阻塞阶段可显式重试。")
            if not reason.strip():
                raise workspace.WorkspaceError("重试须记录故障已解决的依据。")
            if record.get("human_decision_ids"): raise workspace.WorkspaceError("人工决策尚未答复。")
            record.update(status="pending", failures=0, reason=reason)
            record.pop("next_retry_at",None)
        elif command in ("fail", "block"):
            if not reason.strip():
                raise workspace.WorkspaceError("失败或阻塞须说明实际原因。")
            count = record["failures"] + (command == "fail")
            maximum=state.get("policy",{}).get("max_failures",MAX_FAILURES)
            if structured(state) and command=="fail" and count < maximum:
                policy=state["policy"]
                delay=min(policy["max_backoff_seconds"],policy["backoff_seconds"]*2**(count-1))
                record["next_retry_at"]=(datetime.now(timezone.utc)+timedelta(seconds=delay)).isoformat(timespec="seconds")
            record.update(status="blocked" if command == "block" or count >= maximum else "failed",
                          failures=count, reason=reason)
        elif command == "complete":
            if not first["runnable"]:
                raise workspace.WorkspaceError("阶段被阻塞；解决原因后使用 retry。")
            validate(root, stage, disposition, reason, state)
            record.update(status="succeeded", completed_at=now(), disposition=disposition, reason=reason,
                          inputs={f: digest(root, f) for f in inputs(stage, state)},
                          outputs={f: digest(root, f) for f in outputs(stage,state)})
            record.pop("next_retry_at",None)
            if structured(state):
                import stage_contracts
                record["tracked"]=stage_contracts.tracked_files(root,stage)
            if stage == "read":
                snapshots, _ = source_snapshots(root)
                record.update(source_texts=snapshots,
                              snapshot_status="registered_texts_verified" if snapshots else "not_registered")
            record.pop("changed_files", None)
        save(root, state, command, stage, record)
        return view(state)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "next", "status", "start", "complete", "fail", "block", "retry"):
        p = sub.add_parser(command)
        p.add_argument("--project", required=True)
        if command == "init":
            p.add_argument("--topic", required=True)
            p.add_argument("--profile",choices=("structured","legacy"),default="structured")
            p.add_argument("--deliverable-profile",choices=("manuscript","report"),default="manuscript")
        elif command not in ("next", "status"):
            p.add_argument("--stage", choices=NAMES, required=True)
            p.add_argument("--reason", default="")
            if command == "complete":
                p.add_argument("--disposition", choices=("executed", "planned", "not_applicable"), default="executed")
    args = parser.parse_args(argv)
    try:
        root = workspace.project_path(args.project)
        if args.command == "init":
            result = initialize(root, args.topic, args.profile, args.deliverable_profile)
        else:
            result = operate(root, args.command, getattr(args, "stage", None),
                             getattr(args, "reason", ""), getattr(args, "disposition", "executed"))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (workspace.WorkspaceError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc), "limitation": LIMITATION}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
