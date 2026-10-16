"""Shared rule versioning must not alter old receipts or bypass human decisions."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pipeline
import provenance
import workspace


class ResearchCoreSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = (Path(self.temp.name) / 'project').resolve()
        pipeline.initialize(self.root, 'Offline research-core fixture', profile='structured')

    def read_manifest(self):
        return json.loads((self.root / 'engine-manifest.json').read_text())

    def test_new_project_freezes_adopted_rules_and_lock(self):
        manifest = self.read_manifest()
        entries = {r['path']: r['sha256'] for r in manifest['files']}
        expected = 'runtime-snapshot/shared/research-core/references/evidence.md'
        self.assertIn(expected, entries)
        self.assertIn('runtime-snapshot/shared/research-core.lock.json', entries)
        self.assertEqual(hashlib.sha256((self.root / expected).read_bytes()).hexdigest(), entries[expected])
        adopted = json.loads((Path(provenance.__file__).resolve().parent.parent / 'shared/research-core.lock.json').read_text())
        self.assertEqual(manifest['research_core']['version'], adopted['version'])
        self.assertEqual(manifest['research_core']['source_commit'], adopted['source_commit'])
        pipeline.operate(self.root, 'start', 'scope')
        self.assertEqual(pipeline.load(self.root)['stages']['scope']['status'], 'running')

    def test_tampered_rules_cannot_be_reaccepted_or_executed_from_snapshot(self):
        target = self.root / 'runtime-snapshot/shared/research-core/references/evidence.md'
        target.write_text('changed rules')
        with self.assertRaises(workspace.WorkspaceError):
            provenance.capture(self.root)
        with patch.object(provenance, '__file__', str(self.root / 'runtime-snapshot/scripts/provenance.py')):
            with self.assertRaises(workspace.WorkspaceError):
                provenance.assert_execution(self.root)

    def test_legacy_manifest_is_not_silently_upgraded(self):
        manifest = self.read_manifest()
        manifest['files'] = [r for r in manifest['files'] if not r['path'].startswith('runtime-snapshot/shared/')]
        manifest.pop('research_core')
        path = self.root / 'engine-manifest.json'
        path.write_text(json.dumps(manifest))
        before = path.read_bytes()
        self.assertNotIn('research_core', provenance.capture(self.root))
        self.assertEqual(before, path.read_bytes())

    def test_missing_bundled_rules_refuse_new_capture(self):
        installation = Path(self.temp.name) / 'incomplete-skill'
        (installation / 'scripts').mkdir(parents=True)
        other = (Path(self.temp.name) / 'new-project').resolve()
        other.mkdir()
        with patch.object(provenance, '__file__', str(installation / 'scripts/provenance.py')):
            with self.assertRaisesRegex(workspace.WorkspaceError, 'Research Core'):
                provenance.capture(other)
        self.assertFalse((other / 'engine-manifest.json').exists())


    def test_completed_delivery_keeps_frozen_research_rules(self):
        import io
        import zipfile
        import export_bundle
        from test_structured_workflow import StructuredWorkflowTests
        fixture = StructuredWorkflowTests()
        fixture.setUp()
        try:
            fixture.through('review')
            payload, _, _ = export_bundle.build(fixture.root, pipeline.load(fixture.root))
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                expected = 'runtime-snapshot/shared/research-core/references/evidence.md'
                self.assertEqual(archive.read(expected), (fixture.root / expected).read_bytes())
                self.assertIn('runtime-snapshot/shared/research-core.lock.json', archive.namelist())
        finally:
            fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
