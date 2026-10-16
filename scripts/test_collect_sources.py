"""Offline contracts for API collection and evidence-preserving text capture."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import collect_sources as collect
import workspace


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "study"
        workspace.init_project(self.root, "成人学习与文旅", "review")
        self.crossref = {"message": {"items": [{"DOI": "10.1234/demo", "title": ["Adult learning"], "author": [{"family": "Example"}], "issued": {"date-parts": [[2024]]}}]}}
        self.eric = {"response": {"docs": [{"id": "ED123456", "title": "Tourism education", "author": ["Author"], "publicationdateyear": 2025, "description": "Indexed abstract"}]}}

    def tearDown(self):
        self.temporary.cleanup()

    def fetch(self, request, timeout):
        self.assertEqual(timeout, 25)
        body = self.crossref if "api.crossref.org" in request.full_url else self.eric
        return io.BytesIO(json.dumps(body).encode())

    def records(self, name="sources"):
        return json.loads((self.root / f"research/{name}.json").read_text())

    def test_real_request_contract_and_no_doi_record(self):
        with patch("urllib.request.urlopen", side_effect=self.fetch) as http:
            result = collect.search(self.root, "adult learning", '"adult learning"', 2)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(self.records()), 2)
        eric = next(x for x in self.records() if x["provider"] == "eric")
        self.assertNotIn("doi", eric)
        self.assertEqual(eric["url"], "https://eric.ed.gov/?id=ED123456")
        self.assertEqual(eric["access_level"], "metadata")
        self.assertEqual(eric["abstract"], "Indexed abstract")
        self.assertIn("fields=", http.call_args_list[1].args[0].full_url)
        self.assertEqual(len(list((self.root / "research/search-responses").glob("*.json"))), 2)

    def test_preserves_existing_reading_and_evidence_and_deduplicates(self):
        original = {"id": "S1", "doi": "https://doi.org/10.1234/DEMO", "title": "Original", "access_level": "fulltext", "metadata_status": "verified", "notes": {"keep": True}, "evidence_ids": ["E1"]}
        (self.root / "research/sources.json").write_text(json.dumps([original]))
        with patch("urllib.request.urlopen", side_effect=self.fetch):
            collect.search(self.root, "adult learning")
            collect.search(self.root, "adult learning")
        result = self.records()
        self.assertEqual(len(result), 2)
        kept = next(x for x in result if x["id"] == "S1")
        for key, value in original.items():
            self.assertEqual(kept[key], value)

    def test_all_failed_preserves_previous_results_and_returns_nonzero(self):
        before = '[{"id":"old","title":"Earlier result"}]\n'
        (self.root / "research/search-results.json").write_text(before)
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("unavailable")):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = collect.main(["search", "--project", str(self.root), "--query", "topic"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "failed")
        self.assertEqual((self.root / "research/search-results.json").read_text(), before)
        self.assertEqual(self.records(), [])
        self.assertIn("unavailable", (self.root / "research/search-log.md").read_text())

    def test_partial_success_is_kept(self):
        def fetch(request, timeout):
            if "crossref" in request.full_url:
                raise TimeoutError("timeout")
            return self.fetch(request, timeout)
        with patch("urllib.request.urlopen", side_effect=fetch):
            result = collect.search(self.root, "topic")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.records()[0]["eric_id"], "ED123456")

    def test_multiple_queries_keep_previous_candidates(self):
        with patch("urllib.request.urlopen", side_effect=self.fetch):
            collect.search(self.root, "first query")
            self.eric["response"]["docs"][0]["id"] = "ED654321"
            collect.search(self.root, "second query")
        candidates = self.records("search-results")
        self.assertEqual(len(candidates), 3)
        self.assertEqual({x.get("eric_id") for x in candidates if x.get("eric_id")}, {"ED123456", "ED654321"})

    def test_manual_eric_url_deduplicates_without_replacing_source_id(self):
        original = {"id": "manual", "url": "https://eric.ed.gov/?id=ED123456", "notes": "keep"}
        incoming = collect.normalized("eric", self.eric)
        combined = collect.merge([original], incoming)
        self.assertEqual(len(combined), 1)
        self.assertEqual(combined[0]["id"], "manual")
        self.assertEqual(combined[0]["notes"], "keep")

    def test_capture_never_promotes_access_or_claims(self):
        source = {"id": "S1", "title": "Original", "access_level": "metadata", "claim_verification": "unverified"}
        (self.root / "research/sources.json").write_text(json.dumps([source]))
        incoming = self.base / "paper.txt"
        incoming.write_text("已取得的中文原文。", encoding="utf-8")
        result = collect.capture(self.root, "S1", incoming)
        self.assertEqual(result["content_sha256"], hashlib.sha256(incoming.read_bytes()).hexdigest())
        self.assertEqual(self.records()[0]["access_level"], "metadata")
        self.assertEqual(self.records()[0]["claim_verification"], "unverified")
        self.assertEqual(self.records("evidence"), [])
        incoming.write_text("另一个版本", encoding="utf-8")
        with self.assertRaises(workspace.WorkspaceError):
            collect.capture(self.root, "S1", incoming)

    def test_symlink_and_broken_existing_records_are_rejected_before_network(self):
        target = self.root / "research/sources.json"
        target.write_text('{"not":"an array"}')
        with patch("urllib.request.urlopen") as http:
            with self.assertRaises(workspace.WorkspaceError):
                collect.search(self.root, "topic")
            http.assert_not_called()
        target.unlink()
        target.symlink_to(self.base / "outside.json")
        with self.assertRaises(workspace.WorkspaceError):
            collect.search(self.root, "topic")

    def test_capture_checks_identity_before_input_and_rejects_symlink(self):
        with self.assertRaisesRegex(workspace.WorkspaceError, "尚未登记"):
            collect.capture(self.root, "unknown", self.base / "missing.txt")
        (self.root / "research/sources.json").write_text(json.dumps([{"id": "S1"}]))
        source = self.base / "paper.txt"
        source.write_text("source text")
        alias = self.base / "linked.txt"
        alias.symlink_to(source)
        with self.assertRaisesRegex(workspace.WorkspaceError, "符号链接"):
            collect.capture(self.root, "S1", alias)

class ProviderReplacementTests(unittest.TestCase):
    def test_local_json_can_replace_both_remote_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base / "study"
            workspace.init_project(root, "本地数据源", "review")
            local = base / "source.json"
            local.write_text(json.dumps([{"id": "L1", "title": "Adult learning", "url": "https://example.invalid/paper"}]))
            with patch("urllib.request.urlopen") as http:
                result = collect.search(root, "*", provider_names=["local-json"], provider_options={"local-json": {"file": str(local)}})
            http.assert_not_called()
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["providers"][0]["provider"], "local-json")
            self.assertEqual(result["providers"][0]["attempts"], [{"attempt": 1, "status": "ok"}])
            self.assertEqual(json.loads((root / "research/search-results.json").read_text())[0]["id"], "L1")

    def test_structured_query_filters_are_validated_and_logged(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base / "study"
            workspace.init_project(root, "本地年份筛选", "review")
            local = base / "source.json"
            local.write_text(json.dumps([
                {"id": "L1", "title": "Adult learning", "url": "https://example.invalid/1", "year": 2020},
                {"id": "L2", "title": "Adult learning", "url": "https://example.invalid/2", "year": 2025},
                {"id": "L3", "title": "Adult learning", "url": "https://example.invalid/3"}]))
            request = {"schema_version": 1, "id": "Q1", "query": "*", "providers": ["local-json"], "limit": 10,
                       "filters": {"year_min": 2024, "year_max": None}}
            result = collect.search_request(root, request, {"local-json": {"file": str(local)}})
            self.assertEqual(result["request_id"], "Q1")
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["providers"][0]["filter_excluded"], [
                {"id": "L1", "reason": "year_outside_filter"}, {"id": "L3", "reason": "year_missing"}])
            request["filters"]["year_max"] = 2022
            with patch("urllib.request.urlopen") as http:
                with self.assertRaises(ValueError):
                    collect.search_request(root, request, {"local-json": {"file": str(local)}})
                http.assert_not_called()


if __name__ == "__main__":
    unittest.main()
