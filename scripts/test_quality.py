import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import analyze_data
import quality
import workspace
from test_analyze_data import RAW, dataset


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        workspace.init_project(self.root, "quality unit test")
        self.put("research/sources.json", [{"id": "s1", "title": "Study", "url": "https://example.org/paper", "access_level": "fulltext", "metadata_status": "verified"}])
        self.put("research/evidence.json", [{"id": "e1", "source_id": "s1", "claim": "Registered test claim", "locator": "p.1", "support_status": "supports", "claim_verification": "verified", "reviewer": "test-only reviewer", "reviewed_at": "2026-10-06T00:00:00Z"}])
        self.put("research/screening.json", {"decisions": [{"source_id": "s1", "decision": "include", "reason": "test inclusion", "reviewer": "test reviewer", "reviewed_at": "2026-10-06T00:00:00Z"}]})
        self.put("research/analysis-result.json", {"status": "planned"})
        self.put("report.json", {"claims": [{"id": "c1", "status": "supported", "evidence_ids": ["e1"], "analysis_ids": []}], "references": [{"source_id": "s1", "title": "Study", "url": "https://example.org/paper"}]})

    def tearDown(self):
        self.temp.cleanup()

    def put(self, path, obj):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(obj))

    def evaluate_metrics_only(self, **kwargs):
        # Separate semantic metric tests from the independently tested full schema gate.
        with patch.object(quality, "schema_measure", return_value=(9, 9, [])):
            return quality.evaluate(self.root, **kwargs)

    def test_optional_benchmark_unmeasured_does_not_fake_accuracy(self):
        result = self.evaluate_metrics_only()
        self.assertEqual(result["overall_status"], "pass")
        metrics = {m["id"]: m for m in result["metrics"]}
        self.assertIsNone(metrics["screening_precision"]["value"])
        self.assertEqual(metrics["screening_recall"]["status"], "not_measured")
        self.assertEqual(metrics["analysis_reproducibility"]["status"], "not_applicable")

    def test_zero_denominator_not_one_hundred_percent(self):
        self.put("report.json", {"claims": [], "references": []})
        result = self.evaluate_metrics_only()
        self.assertEqual(result["overall_status"], "incomplete")
        metric = next(m for m in result["metrics"] if m["id"] == "citation_resolution_rate")
        self.assertIsNone(metric["value"])
        self.assertEqual(metric["denominator"], 0)

    def test_unknown_metric_rejected(self):
        policy = copy.deepcopy(quality.DEFAULT_POLICY)
        policy["metrics"].append({"id": "invented_accuracy", "min": 1.0, "severity": "error", "required": True})
        self.put("quality-policy.json", policy)
        with self.assertRaises(ValueError):
            quality.evaluate(self.root)

    def test_core_threshold_cannot_be_weakened(self):
        policy = copy.deepcopy(quality.DEFAULT_POLICY)
        policy["metrics"][0]["min"] = 0.5
        with self.assertRaisesRegex(ValueError, "core gate"):
            quality.validate_policy(policy)

    def test_unreviewed_claim_fails_core_gate(self):
        self.put("research/evidence.json", [{"id": "e1", "source_id": "s1", "claim_verification": "verified", "support_status": "supports", "locator": "p1"}])
        result = self.evaluate_metrics_only()
        self.assertEqual(result["overall_status"], "fail")
        self.assertEqual(next(m for m in result["metrics"] if m["id"] == "verified_claim_coverage")["value"], 0)

    def test_unknown_section_claim_fails(self):
        report = json.loads((self.root / "report.json").read_text())
        report["sections"] = [{"id": "s", "heading": "Test", "text": "body", "claim_ids": ["missing"]}]
        self.put("report.json", report)
        self.assertEqual(self.evaluate_metrics_only()["overall_status"], "fail")

    def test_abstract_cannot_support_verified_claim(self):
        source = json.loads((self.root / "research/sources.json").read_text())
        source[0]["access_level"] = "abstract"
        self.put("research/sources.json", source)
        self.assertEqual(self.evaluate_metrics_only()["overall_status"], "fail")

    def test_unknown_reference_fails(self):
        report = json.loads((self.root / "report.json").read_text())
        report["references"][0]["source_id"] = "missing"
        self.put("report.json", report)
        self.assertEqual(self.evaluate_metrics_only()["overall_status"], "fail")

    def test_uncertain_screening_remains_unresolved(self):
        self.put("research/screening.json", {"decisions": [{"source_id": "s1", "decision": "uncertain", "reason": "needs fulltext", "reviewer": "test reviewer", "reviewed_at": "2026-10-06T00:00:00Z"}]})
        self.assertEqual(self.evaluate_metrics_only()["overall_status"], "fail")

    def test_missing_schema_files_are_failures_not_skipped(self):
        result = quality.evaluate(self.root)
        metric = next(m for m in result["metrics"] if m["id"] == "schema_pass_rate")
        self.assertEqual(metric["denominator"], 9)
        self.assertLess(metric["value"], 1)
        self.assertEqual(result["overall_status"], "fail")

    def test_optional_warning_threshold(self):
        source = json.loads((self.root / "research/sources.json").read_text())
        source.append({"id": "s2", "title": "Abstract only", "url": "https://example.org/abstract", "access_level": "abstract", "metadata_status": "verified"})
        screening = json.loads((self.root / "research/screening.json").read_text())
        screening["decisions"].append({"source_id": "s2", "decision": "exclude", "reason": "fulltext unavailable", "reviewer": "test reviewer", "reviewed_at": "2026-10-06T00:00:00Z"})
        self.put("research/screening.json", screening)
        self.put("research/sources.json", source)
        policy = copy.deepcopy(quality.DEFAULT_POLICY)
        next(m for m in policy["metrics"] if m["id"] == "fulltext_ratio")["min"] = 0.9
        self.put("quality-policy.json", policy)
        result = self.evaluate_metrics_only()
        self.assertEqual(result["overall_status"], "pass")
        self.assertEqual(next(m for m in result["metrics"] if m["id"] == "fulltext_ratio")["status"], "fail")

    def test_numerical_reproduction_and_tampered_artifact(self):
        (self.root / "data").mkdir()
        (self.root / "data/input.csv").write_bytes(RAW)
        self.put("data/dataset-spec.json", dataset())
        analysis = analyze_data.analyze(self.root, "data/dataset-spec.json", "y", ["x", "z"])
        self.assertEqual(quality.reproduction_measure(self.root, analysis)[:2], (1, 1))
        changed_parameters = copy.deepcopy(analysis)
        changed_parameters["parameters"]["confidence_level"] = 0.80
        self.assertEqual(quality.reproduction_measure(self.root, changed_parameters)[:2], (0, 1))
        (self.root / "data/cleaned.csv").write_text("tampered")
        numerator, denominator, _, reason = quality.reproduction_measure(self.root, analysis)
        self.assertEqual((numerator, denominator), (0, 1))
        self.assertIn("hash differs", reason)

    def test_benchmark_precision_recall(self):
        self.put("benchmark.json", {"schema_version": 1, "id": "test-labelled-fixture", "labeler": "human-test-fixture", "labelled_at": "2026-10-06T00:00:00Z", "independent": True, "labels": [{"source_id": "s1", "include": True}]})
        result = self.evaluate_metrics_only(benchmark_path="benchmark.json")
        metrics = {m["id"]: m for m in result["metrics"]}
        self.assertEqual(metrics["screening_precision"]["value"], 1)
        self.assertEqual(metrics["screening_recall"]["value"], 1)

    def test_evaluation_config_records_project_relative_paths_and_hashes(self):
        import hashlib
        self.put("review/policy.json", copy.deepcopy(quality.DEFAULT_POLICY))
        self.put("review/benchmark.json", {"schema_version": 1, "id": "test-labelled-fixture", "labeler": "human-test-fixture", "labelled_at": "2026-10-06T00:00:00Z", "independent": True, "labels": [{"source_id": "s1", "include": True}]})
        result = self.evaluate_metrics_only(policy_path=str((self.root / "review/policy.json").resolve()), benchmark_path=str((self.root / "review/benchmark.json").resolve()))
        self.assertEqual(result["evaluation_config"], {"policy_path": "review/policy.json", "benchmark_path": "review/benchmark.json"})
        receipts = {x["path"]: x["sha256"] for x in result["evaluation_inputs"]}
        for path in ("review/policy.json", "review/benchmark.json", "report.json"):
            self.assertEqual(receipts[path], hashlib.sha256((self.root/path).read_bytes()).hexdigest())


class EvaluationReplayTests(unittest.TestCase):
    """Real schema/OLS/pipeline fixtures; labels are explicitly test-only."""
    def setUp(self):
        from test_structured_workflow import StructuredWorkflowTests
        self.workflow = StructuredWorkflowTests('test_full_structured_fixture_completes_all_stages')
        self.workflow.setUp()
        self.root = self.workflow.root
        self.workflow.through('package')
        self.workflow.write('review/custom-policy.json', copy.deepcopy(quality.DEFAULT_POLICY))
        self.workflow.write('review/benchmark.json', {'schema_version': 1, 'id': 'independent-test-fixture', 'labeler': 'independent-test-reviewer', 'labelled_at': '2026-10-06T00:00:00Z', 'independent': True, 'labels': [{'source_id': 'S1', 'include': True}]})

    def tearDown(self):
        self.workflow.tearDown()

    def evaluate(self):
        return quality.evaluate(self.root, policy_path='review/custom-policy.json', benchmark_path='review/benchmark.json')

    def test_custom_policy_and_benchmark_replayed_by_review(self):
        import pipeline
        result = self.evaluate()
        self.assertEqual(result['overall_status'], 'pass')
        self.assertEqual(next(x for x in result['metrics'] if x['id']=='screening_precision')['value'], 1)
        self.assertEqual(pipeline.operate(self.root, 'complete', 'review')['status'], 'complete')
        tracked = pipeline.load(self.root)['stages']['review']['tracked']
        self.assertIn('review/custom-policy.json', tracked)
        self.assertIn('review/benchmark.json', tracked)

    def test_changed_benchmark_stales_completed_review(self):
        import pipeline
        self.evaluate()
        pipeline.operate(self.root, 'complete', 'review')
        value = self.workflow.read('review/benchmark.json')
        value['labels'][0]['include'] = False
        self.workflow.write('review/benchmark.json', value)
        status = pipeline.operate(self.root, 'status')
        self.assertEqual(status['next']['stage'], 'review')
        self.assertEqual(status['stages']['review']['status'], 'stale')
        self.assertIn('review/benchmark.json', status['stages']['review']['changed_files'])

    def test_changed_benchmark_before_review_rejected(self):
        import pipeline
        self.evaluate()
        value = self.workflow.read('review/benchmark.json')
        value['labeler'] = 'different-independent-test-reviewer'
        self.workflow.write('review/benchmark.json', value)
        with self.assertRaisesRegex(workspace.WorkspaceError, '评估输入已改变'):
            pipeline.operate(self.root, 'complete', 'review')


if __name__ == '__main__':
    unittest.main()
