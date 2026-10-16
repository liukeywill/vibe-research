import json
from pathlib import Path
import tempfile
import unittest

from research_mode import ModeError, select_mode


class ResearchModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def state(self, name, value):
        (self.root / name).write_text(json.dumps(value))

    def test_default_and_explicit_modes(self):
        self.assertEqual(select_mode()['mode'], 'manual')
        self.assertEqual(select_mode(requested='automatic')['mode'], 'automatic')
        self.assertEqual(select_mode(legacy_auto=True)['mode'], 'automatic')
        self.assertEqual(select_mode(requested='manual', legacy_auto=True)['mode'], 'manual')

    def test_nonexistent_project_is_not_created(self):
        path = self.root / 'not-created'
        self.assertEqual(select_mode(path)['action'], 'new_project')
        self.assertFalse(path.exists())

    def test_legacy_auto_name_does_not_override_manual_project(self):
        self.state('state.json', {'current_stage': 1, 'stages': {}})
        before = (self.root / 'state.json').read_bytes()
        self.assertEqual(select_mode(self.root, legacy_auto=True)['mode'], 'manual')
        self.assertEqual(before, (self.root / 'state.json').read_bytes())

    def test_explicit_switch_preserves_state_and_requires_migration(self):
        self.state('pipeline-state.json', {'profile': 'legacy', 'stages': {}})
        before = (self.root / 'pipeline-state.json').read_bytes()
        result = select_mode(self.root, requested='manual')
        self.assertEqual(result['action'], 'needs_migration')
        self.assertEqual(result['mode'], 'automatic')
        self.assertEqual(before, (self.root / 'pipeline-state.json').read_bytes())

    def test_conflicting_states_are_not_resolved_by_guessing(self):
        self.state('state.json', {'current_stage': 2, 'stages': {}})
        self.state('pipeline-state.json', {'stages': {}})
        with self.assertRaisesRegex(ModeError, 'Both'):
            select_mode(self.root, requested='automatic')

    def test_corrupt_or_unrecognized_state_is_preserved(self):
        path = self.root / 'state.json'
        path.write_text('{')
        with self.assertRaises(ModeError):
            select_mode(self.root)
        self.assertEqual(path.read_text(), '{')
        self.state('state.json', {'stages': {}, 'current_stage': 1, 'workflow': 'unrelated'})
        with self.assertRaises(ModeError):
            select_mode(self.root)

    def test_nonempty_unrecognized_directory_is_not_initialized(self):
        (self.root / 'draft.md').write_text('keep original work')
        with self.assertRaises(ModeError):
            select_mode(self.root)
        self.assertEqual((self.root / 'draft.md').read_text(), 'keep original work')


if __name__ == '__main__':
    unittest.main()
