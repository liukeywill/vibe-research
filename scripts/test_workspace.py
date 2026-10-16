"""Focused safety and evidence-gate tests for workspace.py."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.project = self.base / "study"
        workspace.init_project(self.project, "乡村旅游学习研究", "empirical")

    def tearDown(self):
        self.temporary.cleanup()

    def write_records(self, access="fulltext", source_id="S1", claim_verification="verified", locator="第 3 节第 2 段"):
        source = {"id": "S1", "title": "测试来源", "url": "https://example.org/source", "access_level": access, "metadata_status": "verified"}
        evidence = {"id": "E1", "source_id": source_id, "claim": "待考察的具体论断", "locator": locator, "support_status": "supports", "claim_verification": claim_verification}
        (self.project / "research/sources.json").write_text(json.dumps([source]), encoding="utf-8")
        (self.project / "research/evidence.json").write_text(json.dumps([evidence]), encoding="utf-8")

    def run_cli(self, command):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = workspace.main([command, "--project", str(self.project)])
        return code, json.loads(output.getvalue())

    def test_refuses_overwrite_and_preserves_content(self):
        note = self.project / "notes.md"
        note.write_text("保留已有研究", encoding="utf-8")
        with self.assertRaises(workspace.WorkspaceError):
            workspace.init_project(self.project, "另一个主题")
        self.assertEqual(note.read_text(encoding="utf-8"), "保留已有研究")

    def test_rejects_unrelated_nonempty_directory(self):
        other = self.base / "other"
        other.mkdir()
        sentinel = other / "important.txt"
        sentinel.write_text("keep", encoding="utf-8")
        with self.assertRaises(workspace.WorkspaceError):
            workspace.init_project(other, "主题")
        self.assertEqual(list(other.iterdir()), [sentinel])

    def test_empty_project_can_be_inspected_but_is_not_ready(self):
        code, result = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertEqual(result["readiness"], "not_ready")
        self.assertTrue(result["structure_valid"])
        self.assertEqual(self.run_cli("status")[0], 0)

    def test_metadata_only_does_not_pass(self):
        self.write_records(access="metadata")
        code, result = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertEqual(result["counts"]["qualifying_fulltext_evidence"], 0)

    def test_abstract_only_does_not_pass(self):
        self.write_records(access="abstract")
        self.assertEqual(self.run_cli("check")[0], 1)

    def test_dangling_source_reference_does_not_pass(self):
        self.write_records(source_id="missing")
        code, result = self.run_cli("check")
        self.assertEqual(code, 2)
        self.assertIn("dangling_source_id", [error["code"] for error in result["errors"]])

    def test_valid_fulltext_evidence_passes_structure_gate(self):
        self.write_records()
        code, result = self.run_cli("check")
        self.assertEqual(code, 0)
        self.assertEqual(result["readiness"], "evidence_record_structure_ready")
        self.assertIn("不判定学术质量", result["limitation"])

    def test_metadata_verification_cannot_verify_a_claim(self):
        self.write_records(claim_verification="unverified")
        self.assertEqual(self.run_cli("check")[0], 1)

    def test_missing_locator_does_not_pass(self):
        self.write_records(locator=" ")
        self.assertEqual(self.run_cli("check")[0], 2)

    def test_generated_paths_remain_inside_project(self):
        for relative in workspace.REQUIRED_FILES:
            self.assertTrue((self.project / relative).resolve().is_relative_to(self.project))
        with self.assertRaises(workspace.WorkspaceError):
            workspace.contained_path(self.project, "../outside.json")
        with self.assertRaises(workspace.WorkspaceError):
            workspace.contained_path(self.project, str(self.base / "outside.json"))

    def test_symlink_does_not_read_external_source_file(self):
        external = self.base / "outside.json"
        external.write_text("private-invalid-json", encoding="utf-8")
        target = self.project / "research/sources.json"
        target.unlink()
        target.symlink_to(external)
        code, result = self.run_cli("check")
        self.assertEqual(code, 2)
        self.assertIn("unsafe_path", [error["code"] for error in result["errors"]])
        self.assertNotIn("private-invalid-json", json.dumps(result))
        self.assertEqual(external.read_text(encoding="utf-8"), "private-invalid-json")

    def test_symlink_project_root_is_rejected(self):
        link = self.base / "link"
        link.symlink_to(self.project, target_is_directory=True)
        with self.assertRaises(workspace.WorkspaceError):
            workspace.inspect_project(link)

    def test_invalid_json_is_reported_without_crashing(self):
        (self.project / "research/evidence.json").write_text("[", encoding="utf-8")
        code, result = self.run_cli("check")
        self.assertEqual(code, 2)
        self.assertIn("unreadable_json", [error["code"] for error in result["errors"]])


if __name__ == "__main__":
    unittest.main()
