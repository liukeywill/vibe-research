"""Deterministic local export tests using explicitly synthetic research records."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import export_bundle
import pipeline
import workspace


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "study"
        pipeline.initialize(self.root, "合成结构测试，不代表实际科研")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, relative, data):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")

    def complete(self):
        self.write("research/texts/S1.txt", "离线合成原文，不是研究证据。")
        self.write("research/search-results.json", [{"id": "S1", "title": "Fixture", "url": "https://example.org"}])
        self.write("research/sources.json", [{"id": "S1", "title": "Fixture", "url": "https://example.org",
            "access_level": "fulltext", "metadata_status": "verified", "local_text": "research/texts/S1.txt",
            "content_sha256": pipeline.digest(self.root, "research/texts/S1.txt")}])
        self.write("research/evidence.json", [{"id": "E1", "source_id": "S1", "claim": "Fixture",
            "locator": "Paragraph 1", "support_status": "supports", "claim_verification": "verified"}])
        for stage, (outputs, _) in pipeline.STAGES.items():
            for name in outputs:
                if not (self.root / name).exists():
                    self.write(name, "合成测试产物，不是实际研究结果。")
            pipeline.operate(self.root, "complete", stage)

    def test_reproducible_sorted_archive_hashes_and_closed_allowlist(self):
        self.complete()
        self.write("notes.md", "不应被打包的用户私人笔记")
        self.write("contributor-info.md", "私人身份资料")
        self.write("research/analysis-code/.env", "不应被读取的配置")
        self.write("research/analysis-code/contributor-info.md", "身份信息")
        self.write("research/analysis-code/main.py", "print('fixture')\n")
        self.write("research/search-responses/response.json", {"source": "fixture"})
        first = export_bundle.export(self.root)
        second = export_bundle.export(self.root)
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(first["sha256"], second["sha256"])
        with zipfile.ZipFile(first["archive"]) as archive:
            names = archive.namelist()
            self.assertEqual(names, sorted(names))
            self.assertNotIn("notes.md", names)
            self.assertNotIn("contributor-info.md", names)
            self.assertFalse(any("delivery/" in n or ".env" in n or "contributor-info" in n for n in names))
            manifest = json.loads(archive.read("manifest.json"))
            self.assertIn("原文可访问", manifest["notice"])
            self.assertEqual({r["path"] for r in manifest["files"]}, set(names) - {"manifest.json"})
            for row in manifest["files"]:
                content = archive.read(row["path"])
                self.assertEqual(row["sha256"], hashlib.sha256(content).hexdigest())
                self.assertEqual(row["size"], len(content))
            self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()))

    def test_incomplete_project_is_not_exported(self):
        with self.assertRaisesRegex(workspace.WorkspaceError, "未完成"):
            export_bundle.export(self.root)
        self.assertFalse((self.root / "delivery").exists())

    def test_changed_source_text_prevents_export(self):
        self.complete()
        self.write("research/texts/S1.txt", "改变后的原文")
        with self.assertRaises(workspace.WorkspaceError):
            export_bundle.export(self.root)
        self.assertFalse((self.root / "delivery").exists())

    def test_symlink_inside_allowed_tree_is_never_followed(self):
        self.complete()
        external = self.base / "private.txt"
        external.write_text("私人内容")
        (self.root / "research/texts/link.txt").symlink_to(external)
        with self.assertRaises(workspace.WorkspaceError):
            export_bundle.export(self.root)
        self.assertEqual(external.read_text(), "私人内容")

    def test_different_existing_output_requires_force(self):
        self.complete()
        first = export_bundle.export(self.root)
        output = Path(first["archive"])
        output.write_bytes(b"user-owned-existing-file")
        with self.assertRaisesRegex(workspace.WorkspaceError, "--force"):
            export_bundle.export(self.root)
        self.assertEqual(output.read_bytes(), b"user-owned-existing-file")
        replaced = export_bundle.export(self.root, force=True)
        self.assertEqual(replaced["sha256"], first["sha256"])

    def test_known_credential_pattern_blocks_bundle(self):
        self.complete()
        self.write("research/analysis-code/example.txt", "ghp_" + "f" * 30)
        with self.assertRaisesRegex(workspace.WorkspaceError, "凭据"):
            export_bundle.export(self.root)
        self.assertFalse((self.root / "delivery").exists())

    def test_output_traversal_and_linked_delivery_are_rejected(self):
        self.complete()
        with self.assertRaises(workspace.WorkspaceError):
            export_bundle.export(self.root, "../outside.zip")
        outside = self.base / "outside"
        outside.mkdir()
        (self.root / "delivery").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(workspace.WorkspaceError):
            export_bundle.export(self.root)
        self.assertEqual(list(outside.iterdir()), [])


class StructuredExportTests(unittest.TestCase):
    """Synthetic records, but OLS and its separate reproduction really execute."""

    def setUp(self):
        # Import locally so unittest does not discover and rerun the fixture's tests.
        from test_structured_workflow import StructuredWorkflowTests
        self.fixture = StructuredWorkflowTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root
        self.base = self.fixture.base

    def receipts(self):
        from model_backends import CodexBackend
        request = {"schema_version": 1, "id": "fixture-scope", "task": "scope",
                   "prompt": "Offline export fixture, not a real research task", "context": [],
                   "response_schema": {"type": "object"}, "model": "fixture-current-codex",
                   "parameters": {}}
        backend = CodexBackend(self.root)
        self.assertEqual(backend.generate(request)["status"], "needs_execution")
        backend.accept(request, {"fixture": "Explicitly synthetic output receipt"})

    def test_structured_analysis_and_receipts_export_with_quality_manifest(self):
        self.receipts()
        self.fixture.write("research/search-requests/fixture.json", {"query": "Offline fixture"})
        self.fixture.write("research/search-responses/fixture.json", {"records": []})
        self.fixture.write("runtime-snapshot/scripts/fixture.py", "# Executable snapshot fixture\n")
        self.fixture.write("runtime-snapshot/schemas/fixture.schema.json", {"type": "object"})
        self.fixture.write("runtime-snapshot/environment.json", {"python": "test-environment"})
        self.fixture.write("decisions/history.jsonl", '{"fixture":"No real human decision"}\n')
        self.fixture.through("review")
        # Neither arbitrary sibling data nor identity files are admitted by a tree scan.
        self.fixture.write("data/unrelated.csv", "Private sibling, not declared as an analysis input\n")
        self.fixture.write("model-io/contributor-info.json", {"identity": "Not exported"})
        first = export_bundle.export(self.root)
        second = export_bundle.export(self.root)
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(first["sha256"], second["sha256"])
        with zipfile.ZipFile(first["archive"]) as archive:
            names = set(archive.namelist())
            expected = {"project-spec.json", "pipeline-policy.json", "quality-policy.json",
                        "research/search-query.json", "research/screening.json", "research/synthesis.json",
                        "research/study-design.json", "research/analysis-result.json", "report.json",
                        "review/quality-report.json", "data/raw.csv", "data/dataset-spec.json",
                        "data/cleaned.csv", "data/cleaning-log.json", "data/environment.json",
                        "data/reproduced-result.json", "analysis-code/reproduce.py",
                        "model-io/fixture-scope.request.json", "model-io/fixture-scope.response.json",
                        "research/search-requests/fixture.json", "research/search-responses/fixture.json",
                        "runtime-snapshot/scripts/fixture.py", "runtime-snapshot/schemas/fixture.schema.json",
                        "runtime-snapshot/environment.json", "engine-manifest.json", "decisions/history.jsonl"}
            self.assertTrue(expected <= names)
            self.assertTrue(any(name.startswith("data/frozen/") and name.endswith(".csv") for name in names))
            self.assertTrue(any(name.startswith("data/frozen/") and name.endswith(".json") for name in names))
            self.assertNotIn("data/unrelated.csv", names)
            self.assertNotIn("model-io/contributor-info.json", names)
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["profile"], "structured")
            self.assertEqual(manifest["quality_gate"]["status"], "pass")
            self.assertEqual(manifest["quality_gate"]["policy_sha256"], pipeline.digest(self.root, "quality-policy.json"))
            self.assertEqual(manifest["analysis_disposition"], "executed")
            self.assertEqual(manifest["stage_status"], "schema_and_required_quality_gates_complete")
            for row in manifest["files"]:
                self.assertEqual(hashlib.sha256(archive.read(row["path"])).hexdigest(), row["sha256"])

    def test_tracked_hash_is_checked_during_build(self):
        self.fixture.through("review")
        state = pipeline.load(self.root)
        tracked = state["stages"]["analyze"]["tracked"]
        self.assertIn("data/raw.csv", tracked)
        self.fixture.write("data/raw.csv", "score,x\n99,1\n")
        with self.assertRaisesRegex(workspace.WorkspaceError, "改变"):
            export_bundle.build(self.root, state)
        self.assertFalse((self.root / "delivery").exists())

    def test_raw_or_code_tampering_stales_project_before_export(self):
        self.fixture.through("review")
        self.fixture.write("analysis-code/reproduce.py", "# Tampered after numerical reproduction\n")
        with self.assertRaisesRegex(workspace.WorkspaceError, "未完成"):
            export_bundle.export(self.root)
        self.assertFalse((self.root / "delivery").exists())

    def test_completed_model_receipt_tampering_is_not_exported(self):
        self.receipts()
        self.fixture.through("review")
        state = pipeline.load(self.root)
        self.assertIn("model-io/fixture-scope.response.json", state["stages"]["scope"]["tracked"])
        response = self.fixture.read("model-io/fixture-scope.response.json")
        response["output"] = {"fixture": "Changed after completed scope"}
        self.fixture.write("model-io/fixture-scope.response.json", response)
        with self.assertRaisesRegex(workspace.WorkspaceError, "未完成"):
            export_bundle.export(self.root)
        self.assertFalse((self.root / "delivery").exists())

    def test_declared_analysis_input_outside_project_is_rejected(self):
        self.fixture.through("review")
        external = self.base / "private.csv"
        external.write_text("Private data never admitted\n")
        result = self.fixture.read("research/analysis-result.json")
        result["input_files"].append({"path": "../private.csv", "sha256": hashlib.sha256(external.read_bytes()).hexdigest()})
        self.fixture.write("research/analysis-result.json", result)
        with self.assertRaises(ValueError):
            export_bundle.selected_files(self.root, pipeline.load(self.root))
        self.assertFalse((self.root / "delivery").exists())

    def test_declared_sensitive_analysis_input_is_rejected(self):
        self.fixture.through("review")
        self.fixture.write("data/contributor-info.csv", "Private identity fixture\n")
        result = self.fixture.read("research/analysis-result.json")
        result["input_files"].append({"path": "data/contributor-info.csv",
                                     "sha256": pipeline.digest(self.root, "data/contributor-info.csv")})
        self.fixture.write("research/analysis-result.json", result)
        with self.assertRaisesRegex(workspace.WorkspaceError, "身份"):
            export_bundle.selected_files(self.root, pipeline.load(self.root))

    def test_structured_snapshot_symlink_is_rejected(self):
        self.fixture.through("review")
        external = self.base / "private.json"
        external.write_text('{"private":"fixture"}\n')
        folder = self.root / "runtime-snapshot"
        folder.mkdir(exist_ok=True)
        (folder / "linked.json").symlink_to(external)
        with self.assertRaises(workspace.WorkspaceError):
            export_bundle.export(self.root)
        self.assertEqual(external.read_text(), '{"private":"fixture"}\n')

    def test_failed_quality_gate_is_never_exported(self):
        self.fixture.through("review")
        state = pipeline.load(self.root)
        report = self.fixture.read("review/quality-report.json")
        report["overall_status"] = "fail"
        self.fixture.write("review/quality-report.json", report)
        # The direct builder also rejects a failed gate even if supplied a stale ledger.
        state["stages"]["review"]["outputs"]["review/quality-report.json"] = pipeline.digest(self.root, "review/quality-report.json")
        with self.assertRaisesRegex(workspace.WorkspaceError, "门禁"):
            export_bundle.build(self.root, state)

    def custom_quality(self):
        from copy import deepcopy
        import quality
        self.fixture.through("package")
        self.fixture.write("evaluation-inputs/custom-policy.json", deepcopy(quality.DEFAULT_POLICY))
        self.fixture.write("evaluation-inputs/independent-labels.json", {
            "schema_version": 1, "id": "independent-test-fixture", "labeler": "independent-test-reviewer",
            "labelled_at": "2026-10-06T00:00:00Z", "independent": True,
            "labels": [{"source_id": "S1", "include": True}]})
        quality.evaluate(self.root, policy_path="evaluation-inputs/custom-policy.json",
                         benchmark_path="evaluation-inputs/independent-labels.json")
        pipeline.operate(self.root, "complete", "review")

    def test_custom_quality_inputs_are_explicitly_included_without_default_policy(self):
        self.custom_quality()
        self.assertFalse((self.root / "quality-policy.json").exists())
        self.fixture.write("evaluation-inputs/unrelated.json", {"private": "Unrelated sibling"})
        result = export_bundle.export(self.root)
        with zipfile.ZipFile(result["archive"]) as archive:
            names = set(archive.namelist())
            self.assertIn("evaluation-inputs/custom-policy.json", names)
            self.assertIn("evaluation-inputs/independent-labels.json", names)
            self.assertNotIn("evaluation-inputs/unrelated.json", names)
            gate = json.loads(archive.read("manifest.json"))["quality_gate"]
            self.assertEqual(gate["evaluation_config"], {
                "policy_path": "evaluation-inputs/custom-policy.json",
                "benchmark_path": "evaluation-inputs/independent-labels.json"})
            self.assertEqual(gate["policy_sha256"], pipeline.digest(self.root, "evaluation-inputs/custom-policy.json"))

    def test_changed_custom_quality_input_hash_is_rejected_by_builder(self):
        self.custom_quality()
        state = pipeline.load(self.root)
        for relative in ("evaluation-inputs/custom-policy.json", "evaluation-inputs/independent-labels.json"):
            with self.subTest(relative=relative):
                original = (self.root / relative).read_bytes()
                (self.root / relative).write_bytes(original + b"\n")
                try:
                    with self.assertRaisesRegex(workspace.WorkspaceError, "改变"):
                        export_bundle.build(self.root, state)
                finally:
                    (self.root / relative).write_bytes(original)

    def test_changed_custom_benchmark_stales_review_before_export(self):
        self.custom_quality()
        labels = self.fixture.read("evaluation-inputs/independent-labels.json")
        labels["labels"][0]["include"] = False
        self.fixture.write("evaluation-inputs/independent-labels.json", labels)
        with self.assertRaisesRegex(workspace.WorkspaceError, "未完成"):
            export_bundle.export(self.root)
        self.assertFalse((self.root / "delivery").exists())


if __name__ == "__main__":
    unittest.main()
