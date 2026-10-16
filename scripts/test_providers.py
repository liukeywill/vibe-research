"""Provider replacement and retry policies; all HTTP fixtures are offline mocks."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import providers


class ProviderTests(unittest.TestCase):
    def test_retry_503_then_success_records_both_attempts(self):
        body = {"message": {"items": []}}
        error = urllib.error.HTTPError("https://example.invalid", 503, "unavailable", {}, None)
        with patch("urllib.request.urlopen", side_effect=[error, io.BytesIO(json.dumps(body).encode())]), patch("providers.time.sleep") as sleep:
            found = providers.run_search(providers.CrossrefProvider(), "adult", 1, max_attempts=3)
        self.assertEqual(len(found["attempts"]), 2)
        self.assertTrue(found["attempts"][0]["retryable"])
        sleep.assert_called_once_with(0.25)

    def test_429_and_timeout_are_retryable_but_403_and_bad_json_are_not(self):
        for error in (urllib.error.HTTPError("url", 429, "slow", {}, None), TimeoutError("slow")):
            with patch("urllib.request.urlopen", side_effect=error) as http, patch("providers.time.sleep"):
                with self.assertRaises(providers.ProviderFailure) as raised:
                    providers.run_search(providers.EricProvider(), "adult", 1, max_attempts=3)
            self.assertEqual(http.call_count, 3)
            self.assertEqual(len(raised.exception.attempts), 3)
        for response in (urllib.error.HTTPError("url", 403, "forbidden", {}, None), io.BytesIO(b"not-json")):
            with patch("urllib.request.urlopen", side_effect=response if isinstance(response, Exception) else None, return_value=response) as http:
                with self.assertRaises(providers.ProviderFailure):
                    providers.run_search(providers.EricProvider(), "adult", 1, max_attempts=3)
            self.assertEqual(http.call_count, 1)

    def test_default_does_not_retry(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("slow")) as http:
            with self.assertRaises(providers.ProviderFailure):
                providers.run_search(providers.CrossrefProvider(), "adult", 1)
        self.assertEqual(http.call_count, 1)

    def test_local_provider_replacement_keeps_candidates_unverified(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "items.json"
            source.write_text(json.dumps([{"id": "L1", "title": "Adult learning", "url": "https://example.invalid/paper", "metadata_status": "verified", "access_level": "fulltext"}]))
            adapter = providers.make_provider("local-json", {"file": str(source)})
            found = providers.run_search(adapter, "*", 3)
            self.assertEqual(found["records"][0]["metadata_status"], "unverified")
            self.assertEqual(found["records"][0]["access_level"], "metadata")
            self.assertEqual(providers.run_search(adapter, "tourism", 3)["records"], [])
            alias = Path(temporary) / "link.json"
            alias.symlink_to(source)
            with self.assertRaises(ValueError):
                providers.make_provider("local-json", {"file": str(alias)})

    def test_new_provider_registers_without_collector_edits(self):
        class Fixture:
            def search(self, query, limit):
                return {"records": [], "raw": b"[]", "url": "fixture://empty"}
        with patch.dict(providers._REGISTRY, clear=False):
            providers.register_provider("mock-fixture", Fixture)
            self.assertEqual(providers.run_search(providers.make_provider("mock-fixture"), "q", 1)["records"], [])
        for name in ("../evil", "crossref"):
            with self.assertRaises(ValueError):
                providers.register_provider(name, Fixture)

    def test_custom_provider_invalid_source_shape_cannot_reach_collector(self):
        class Invalid:
            def search(self, query, limit):
                return {"records": [{"id": "missing-title-and-url"}], "raw": b"[]", "url": "fixture://invalid"}
        with self.assertRaises(providers.ProviderFailure) as error:
            providers.run_search(Invalid(), "q", 1, max_attempts=3)
        self.assertEqual(len(error.exception.attempts), 1)
        self.assertFalse(error.exception.attempts[0]["retryable"])

    def test_validation_precedes_network(self):
        with patch("urllib.request.urlopen") as http:
            for kwargs in ({"max_attempts": 0}, {"max_attempts": 20}, {"backoff": 5}):
                with self.assertRaises(ValueError):
                    providers.run_search(providers.CrossrefProvider(), "q", 1, **kwargs)
            http.assert_not_called()


if __name__ == "__main__":
    unittest.main()
