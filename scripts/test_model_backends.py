"""Backend contract tests. Command fixtures are mocks, never an LLM quality test."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import model_backends as models
import workspace


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "study"
        workspace.init_project(self.root, "模型接口测试", "review")
        self.request = {"schema_version": 1, "id": "REQ1", "task": "scope", "prompt": "Return the structured fixture.",
                        "context": [{"role": "user", "content": "Offline interface test"}],
                        "response_schema": {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False},
                        "model": "fixture-model-not-llm", "parameters": {}}

    def tearDown(self):
        self.temporary.cleanup()

    def command(self, code, timeout=5):
        return models.make_backend({"backend": "command", "argv": [sys.executable, "-c", code], "timeout": timeout})

    def test_codex_handoff_does_not_claim_execution_and_accepts_bound_receipt(self):
        adapter = models.make_backend({"backend": "codex", "project": str(self.root)})
        pending = adapter.generate(self.request)
        self.assertEqual(pending["status"], "needs_execution")
        self.assertEqual(pending["output"], {})
        self.assertFalse((self.root / pending["provenance"]["response_file"]).exists())
        receipt = adapter.accept(self.request, {"answer": "Actual fixture output supplied by test"})
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(adapter.generate(self.request), receipt)
        with self.assertRaises(models.BackendError):
            adapter.accept(self.request, {"answer": "Different output"})

    def test_codex_cannot_overwrite_request_or_accept_invalid_output(self):
        adapter = models.CodexBackend(str(self.root))
        adapter.generate(self.request)
        changed = {**self.request, "prompt": "different"}
        with self.assertRaises(models.BackendError):
            adapter.generate(changed)
        with self.assertRaises(models.BackendError):
            adapter.accept(self.request, {"wrong": True})
        self.assertFalse((self.root / "model-io/REQ1.response.json").exists())

    def test_backend_switch_with_same_request_and_no_controller_change(self):
        pending = models.make_backend({"backend": "codex", "project": str(self.root)}).generate(self.request)
        command = self.command('import sys,json; r=json.load(sys.stdin); print(json.dumps({"output":{"answer":r["task"]},"usage":{"input_tokens":0,"output_tokens":0}}))')
        completed = command.generate(self.request)
        self.assertEqual(completed["output"], {"answer": "scope"})
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(pending["provenance"]["request_sha256"], completed["provenance"]["request_sha256"])
        self.assertIn("command_sha256", completed["provenance"])

    def test_command_bad_exit_timeout_json_and_output_schema(self):
        cases = [('raise SystemExit(7)', "exited"), ('print("not json")', "valid JSON"),
                 ('print(\'{"output":{"answer":4}}\')', "schema violation"),
                 ('print(\'{"answer":"missing wrapper"}\')', "output object")]
        for code, pattern in cases:
            with self.subTest(pattern=pattern), self.assertRaisesRegex(models.BackendError, pattern):
                self.command(code).generate(self.request)
        with self.assertRaisesRegex(models.BackendError, "timed out"):
            self.command("import time; time.sleep(5)", timeout=0.03).generate(self.request)

    def test_rejects_shell_string_and_unknown_configuration(self):
        with self.assertRaises(models.BackendError):
            models.make_backend({"backend": "command", "argv": "echo something"})
        with self.assertRaises(models.BackendError):
            models.make_backend({"backend": "command", "argv": ["echo"], "shell": True})
        malformed = copy.deepcopy(self.request)
        malformed["context"][0]["role"] = "tool"
        with self.assertRaises(models.BackendError):
            models.CodexBackend(str(self.root)).generate(malformed)

    def test_invalid_or_remote_output_schema_is_rejected_before_execution(self):
        for schema in ({"type": "not-a-jsonschema-type"}, {"$ref": "https://example.invalid/schema"}):
            request = {**self.request, "response_schema": schema}
            with self.assertRaises(models.BackendError):
                models.CodexBackend(str(self.root)).generate(request)
        self.assertFalse((self.root / "model-io").exists())

    def test_output_formats_and_usage_types_are_enforced(self):
        request = {**self.request, "response_schema": {"type": "object", "properties": {"answer": {"type": "string", "format": "date-time"}}, "required": ["answer"]}}
        with self.assertRaisesRegex(models.BackendError, "schema violation"):
            self.command('print(\'{"output":{"answer":"not-a-date"}}\')').generate(request)
        with self.assertRaises(models.BackendError):
            self.command('print(\'{"output":{"answer":"fixture"},"usage":[]}\')').generate(self.request)

    def test_old_receipt_cannot_be_reused_for_changed_request(self):
        adapter = models.CodexBackend(str(self.root))
        response = adapter.accept(self.request, {"answer": "fixture"})
        changed = {**self.request, "prompt": "changed"}
        with self.assertRaisesRegex(models.BackendError, "request hash"):
            models.validate_response(changed, response)


if __name__ == "__main__":
    unittest.main()
