"""Offline behavioral tests. Fixtures are synthetic, never research findings."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import pipeline
import workspace


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "study"
        pipeline.initialize(self.root, "离线结构测试，不是科研结果")

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, content):
        target = self.root / relative
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        target.write_text(content, encoding="utf-8")

    def records(self, access="fulltext"):
        self.write("research/sources.json", [{"id": "S1", "title": "合成测试来源",
                   "url": "https://example.org/fixture", "access_level": access,
                   "metadata_status": "verified"}])
        self.write("research/evidence.json", [{"id": "E1", "source_id": "S1", "claim": "测试记录",
                   "locator": "fixture paragraph 1", "support_status": "supports",
                   "claim_verification": "verified"}])
        self.write("research/reading-notes.md", "合成 fixture 阅读记录；不是实际研究结论。")

    def execute_fixture(self, stage):
        if stage == "search":
            self.write("research/search-results.json", [{"id": "S1", "title": "合成测试来源", "url": "https://example.org/fixture"}])
            self.write("research/search-log.md", "离线合成记录；未进行真实联网检索。")
        elif stage == "read":
            self.records()
        else:
            for relative in pipeline.STAGES[stage][0]:
                self.write(relative, "合成 fixture 非真实成果；" + stage)
        return pipeline.operate(self.root, "complete", stage)

    def through(self, last):
        result = None
        for stage in pipeline.NAMES[:pipeline.NAMES.index(last) + 1]:
            result = self.execute_fixture(stage)
        return result

    def test_missing_and_empty_artifacts_cannot_complete(self):
        for content in (None, " "):
            if content is not None:
                self.write("question.md", content)
            with self.assertRaises(workspace.WorkspaceError):
                pipeline.operate(self.root, "complete", "scope")
        self.assertEqual(pipeline.operate(self.root, "next")["next"]["stage"], "scope")

    def test_dependency_cannot_be_skipped(self):
        self.write("research/study-plan.md", "存在文件也不能跳过依赖")
        with self.assertRaises(workspace.WorkspaceError):
            pipeline.operate(self.root, "complete", "design")

    def test_initialize_does_not_overwrite(self):
        state = (self.root / "pipeline-state.json").read_bytes()
        self.write("notes.md", "用户笔记")
        with self.assertRaises(workspace.WorkspaceError):
            pipeline.initialize(self.root, "离线结构测试，不是科研结果")
        self.assertEqual((self.root / "notes.md").read_text(), "用户笔记")
        self.assertEqual((self.root / "pipeline-state.json").read_bytes(), state)
        other = self.base / "other"
        other.mkdir()
        (other / "keep").write_text("保留")
        with self.assertRaises(workspace.WorkspaceError):
            pipeline.initialize(other, "其他主题")
        self.assertEqual(list(other.iterdir()), [other / "keep"])

    def test_full_flow_hashes_and_events(self):
        result = self.through("review")
        self.assertEqual(result["status"], "complete")
        self.assertIsNone(result["next"])
        state = pipeline.load(self.root)
        for stage, record in state["stages"].items():
            self.assertEqual(record["status"], "succeeded")
            for group in ("inputs", "outputs"):
                self.assertTrue(record[group])
                for name, stored in record[group].items():
                    self.assertEqual(stored, pipeline.digest(self.root, name))
        events = [json.loads(line) for line in (self.root / "events.jsonl").read_text().splitlines()]
        self.assertEqual([e["seq"] for e in events], list(range(1, 10)))
        self.assertIn("不证明学术真实性", result["limitation"])

    def test_metadata_and_abstract_do_not_pass_read(self):
        self.through("search")
        for access in ("metadata", "abstract"):
            self.records(access)
            with self.assertRaisesRegex(workspace.WorkspaceError, "全文证据"):
                pipeline.operate(self.root, "complete", "read")
        self.assertEqual(pipeline.operate(self.root, "next")["next"]["stage"], "read")

    def test_empty_candidates_do_not_pass_search(self):
        self.through("scope")
        self.write("research/search-results.json", [])
        with self.assertRaises(workspace.WorkspaceError):
            pipeline.operate(self.root, "complete", "search")

    def test_read_enrichment_does_not_invalidate_search(self):
        self.through("search")
        self.records("metadata")
        self.records("fulltext")
        result = pipeline.operate(self.root, "complete", "read")
        self.assertEqual(result["stages"]["search"]["status"], "succeeded")
        self.assertEqual(result["next"]["stage"], "synthesize")

    def test_changed_output_invalidates_downstream(self):
        self.through("review")
        self.write("research/reading-notes.md", "重新阅读后的材料")
        result = pipeline.operate(self.root, "next")
        self.assertEqual(result["next"]["stage"], "read")
        self.assertEqual(result["stages"]["search"]["status"], "succeeded")
        for stage in pipeline.NAMES[2:]:
            self.assertEqual(result["stages"][stage]["status"], "stale")
        with self.assertRaises(workspace.WorkspaceError):
            pipeline.operate(self.root, "complete", "review")

    def test_changed_project_input_invalidates_every_stage(self):
        self.through("review")
        manifest = json.loads((self.root / "project.json").read_text())
        manifest["mode"] = "empirical"
        self.write("project.json", manifest)
        result = pipeline.operate(self.root, "next")
        self.assertEqual(result["next"]["stage"], "scope")
        self.assertTrue(all(r["status"] == "stale" for r in result["stages"].values()))

    def test_failure_limit_block_and_explicit_recovery(self):
        for _ in range(pipeline.MAX_FAILURES):
            result = pipeline.operate(self.root, "fail", "scope", reason="临时错误")
        self.assertEqual(result["status"], "blocked")
        self.write("question.md", "已准备")
        with self.assertRaises(workspace.WorkspaceError):
            pipeline.operate(self.root, "complete", "scope")
        pipeline.operate(self.root, "retry", "scope", reason="故障已解决，保留旧日志")
        self.assertEqual(pipeline.operate(self.root, "complete", "scope")["next"]["stage"], "search")

    def test_no_evidence_can_block_and_resume(self):
        self.through("search")
        result = pipeline.operate(self.root, "block", "read", reason="全文尚不可访问")
        self.assertFalse(result["next"]["runnable"])
        self.records()
        pipeline.operate(self.root, "retry", "read", reason="已取得 fixture 原文记录")
        self.assertEqual(pipeline.operate(self.root, "complete", "read")["next"]["stage"], "synthesize")

    def test_no_data_disposition_requires_matching_reason(self):
        self.through("design")
        self.write("research/analysis.md", "尚无数据，不能声称完成实证分析。")
        with self.assertRaises(workspace.WorkspaceError):
            pipeline.operate(self.root, "complete", "analyze", reason="数据未采集", disposition="planned")
        self.write("research/analysis.md", "status: planned\n原因：数据未采集\n分析脚本和计划待执行。")
        result = pipeline.operate(self.root, "complete", "analyze", reason="数据未采集", disposition="planned")
        self.assertEqual(result["stages"]["analyze"]["disposition"], "planned")

    def test_symlink_and_path_escape_are_rejected(self):
        external = self.base / "outside.txt"
        external.write_text("不可读取或更改的外部文件")
        (self.root / "question.md").symlink_to(external)
        with self.assertRaises(workspace.WorkspaceError):
            pipeline.operate(self.root, "complete", "scope")
        with self.assertRaises(workspace.WorkspaceError):
            pipeline.path(self.root, "../outside.txt")
        self.assertEqual(external.read_text(), "不可读取或更改的外部文件")

    def test_lock_and_corrupted_hashes_fail_closed(self):
        with pipeline.locked(self.root):
            with self.assertRaises(workspace.WorkspaceError):
                pipeline.operate(self.root, "status")
        self.through("scope")
        state = pipeline.load(self.root)
        state["stages"]["scope"]["outputs"]["question.md"] = None
        self.write("pipeline-state.json", state)
        with self.assertRaises(workspace.WorkspaceError):
            pipeline.operate(self.root, "status")

    def test_source_text_change_invalidates_and_cannot_complete(self):
        self.through("search")
        self.records()
        (self.root / "research/texts").mkdir()
        self.write("research/texts/S1.txt", "源文本 fixture")
        sources = json.loads((self.root / "research/sources.json").read_text())
        sources[0].update(local_text="research/texts/S1.txt",
                          content_sha256=pipeline.digest(self.root, "research/texts/S1.txt"))
        self.write("research/sources.json", sources)
        pipeline.operate(self.root, "complete", "read")
        self.execute_fixture("synthesize")
        self.write("research/texts/S1.txt", "改写后的源文本")
        result = pipeline.operate(self.root, "next")
        self.assertEqual(result["next"]["stage"], "read")
        self.assertEqual(result["stages"]["synthesize"]["status"], "stale")
        with self.assertRaisesRegex(workspace.WorkspaceError, "快照"):
            pipeline.operate(self.root, "complete", "read")

    def test_legacy_without_snapshot_is_not_marked_snapshot_verified(self):
        result = self.through("read")
        self.assertEqual(result["stages"]["read"]["snapshot_status"], "not_registered")

    def test_uncommitted_event_tail_stops_resume(self):
        with (self.root / "events.jsonl").open("a") as handle:
            handle.write('{"seq":2,"event":"complete"}\n')
        with self.assertRaisesRegex(workspace.WorkspaceError, "未提交"):
            pipeline.operate(self.root, "next")

    def test_cli_application_errors_are_json(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = pipeline.main(["complete", "--project", str(self.root), "--stage", "scope"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "error")


if __name__ == "__main__":
    unittest.main()
