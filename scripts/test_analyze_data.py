import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import analyze_data as a
import workspace


RAW = b'y,x,z\n1,0,2\n4,1,0\n4,2,1\n7,3,0\n9,4,3\n9,5,2\n14,6,4\n'


def dataset(raw=RAW):
    return {"schema_version": 1, "id": "fixture", "path": "data/input.csv", "sha256": hashlib.sha256(raw).hexdigest(), "source_url": "https://example.org/explicit-test-fixture", "license": "test fixture", "unit_of_analysis": "synthetic test row; never empirical evidence", "columns": [{"name": n, "type": "number", "required": True, "description": "test column"} for n in ("y", "x", "z")], "missing_values": ["NA", None], "cleaning": {"drop_exact_duplicates": False, "missing_policy": "complete_case"}}


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        workspace.init_project(self.root, "unit test")
        (self.root / "data").mkdir()
        (self.root / "data/input.csv").write_bytes(RAW)
        self.spec = dataset()
        self.save_spec()

    def tearDown(self):
        self.temp.cleanup()

    def save_spec(self):
        (self.root / "data/dataset-spec.json").write_text(json.dumps(self.spec))

    def test_cleaning_missing_and_duplicates_preserves_source_records(self):
        raw = RAW + b'4,1,0\nNA,7,2\n'
        spec = dataset(raw)
        spec["cleaning"]["drop_exact_duplicates"] = True
        rows, clean, log = a.clean_csv(raw, spec, "y", ["x", "z"])
        self.assertEqual(len(rows), 7)
        self.assertEqual(log["rules"][0]["affected_records"], [9])
        self.assertEqual(log["rules"][1]["affected_records"], [10])
        self.assertEqual(log["kept_source_records"], list(range(2, 9)))
        self.assertIn(b'__source_record__', clean)

    def test_duplicate_keep_is_explicit(self):
        raw = RAW + b'4,1,0\n'
        rows, _, log = a.clean_csv(raw, dataset(raw), "y", ["x"])
        self.assertEqual(len(rows), 8)
        self.assertEqual(log["rules"][0]["policy"], "keep")

    def test_missing_error(self):
        raw = RAW + b'NA,7,1\n'
        spec = dataset(raw)
        spec["cleaning"]["missing_policy"] = "error"
        with self.assertRaisesRegex(ValueError, "missing selected"):
            a.clean_csv(raw, spec, "y", ["x"])

    def test_invalid_values_not_silently_coerced(self):
        for value in (b'bad', b'inf', b'nan'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "invalid/non-finite"):
                a.clean_csv(RAW + value + b',8,1\n', dataset(), "y", ["x"])

    def test_missing_column_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing columns"):
            a.clean_csv(b'y,z\n1,2\n', dataset(), "y", ["x"])

    def test_semicolon_delimiter(self):
        raw = RAW.replace(b',', b';')
        spec = dataset(raw)
        spec["delimiter"] = ";"
        rows, _, _ = a.clean_csv(raw, spec, "y", ["x"])
        self.assertEqual(len(rows), 7)

    def test_hash_mismatch_rejected_before_output(self):
        self.spec["sha256"] = "0" * 64
        self.save_spec()
        with self.assertRaisesRegex(ValueError, "sha256"):
            a.analyze(self.root, "data/dataset-spec.json", "y", ["x"])
        self.assertFalse((self.root / "research/analysis-result.json").exists())

    def test_outside_input_rejected(self):
        self.spec["path"] = "../outside.csv"
        self.save_spec()
        with self.assertRaises(ValueError):
            a.analyze(self.root, "data/dataset-spec.json", "y", ["x"])

    def test_rank_deficiency(self):
        rows = [{"y": float(i), "x": 1.0} for i in range(5)]
        with self.assertRaisesRegex(ValueError, "rank-deficient"):
            a.fit_rows(rows, "y", ["x"])

    def test_real_execution_and_independent_reproduction(self):
        result = a.analyze(self.root, "data/dataset-spec.json", "y", ["x", "z"])
        self.assertEqual(result["status"], "executed")
        self.assertEqual(result["sample"]["output_rows"], 7)
        self.assertEqual(result["reproducibility"]["status"], "verified")
        code = self.root / "analysis-code/reproduce.py"
        completed = subprocess.run([sys.executable, str(code), "--output", "data/second-result.json"], capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        second = json.loads((self.root / "data/second-result.json").read_text())
        self.assertEqual(second["coefficients"], result["results"]["coefficients"])
        self.assertIn("不能据此推断因果", (self.root / "research/analysis.md").read_text())
        self.assertTrue(all((self.root / r["path"]).is_file() for r in result["input_files"]))


if __name__ == '__main__':
    unittest.main()
