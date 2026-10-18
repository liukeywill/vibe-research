"""Exa results remain unverified candidates and fit the existing import contract."""
import json
from pathlib import Path
import tempfile
import unittest
import agent_reach_search as adapter
import collect_sources
import workspace


class AgentReachTests(unittest.TestCase):
    def payload(self, text):
        return {'content':[{'type':'text','text':text}]}

    def test_error_and_empty_are_not_sources(self):
        for value in ({'isError':True,'content':[]}, self.payload('Please log in'), self.payload('Title: No URL')):
            with self.assertRaises(ValueError):
                adapter.candidates(value)

    def test_deduplicates_and_does_not_promote_search_highlights(self):
        text = 'Title: A\nURL: https://example.org/a\nHighlights: Full text\nTitle: Duplicate\nURL: https://example.org/a\nTitle: B\nURL: https://example.org/b'
        records = adapter.candidates(self.payload(text))
        self.assertEqual(len(records), 2)
        for record in records:
            self.assertEqual(record['access_level'], 'metadata')
            self.assertEqual(record['metadata_status'], 'unverified')
            self.assertNotIn('content_sha256', record)
        self.assertEqual(adapter.candidates(self.payload(text), 1), records[:1])

    def test_credential_url_is_not_imported(self):
        with self.assertRaises(ValueError):
            adapter.candidates(self.payload('Title: Hidden\nURL: https://user:secret@example.org/a'))

    def test_real_collector_import_preserves_existing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()/'project'
            workspace.init_project(root, '合成测试项目', 'review')
            record = adapter.candidates(self.payload('Title: Example\nURL: https://example.org/paper'))[0]
            previous = dict(record, access_level='fulltext', metadata_status='verified', local_text='research/texts/existing.txt', read_scope='full paper')
            (root/'research/sources.json').write_text(json.dumps([previous]))
            incoming = Path(tmp)/'candidates.json'
            incoming.write_text(json.dumps([record]))
            result=collect_sources.search(root,'*',provider_names=['local-json'],provider_options={'local-json':{'file':str(incoming)}})
            self.assertEqual(result['status'],'ok')
            retained=json.loads((root/'research/sources.json').read_text())
            self.assertEqual(len(retained), 1)
            for key, value in previous.items():
                self.assertEqual(retained[0][key], value)
            candidate=json.loads((root/'research/search-results.json').read_text())[0]
            self.assertEqual(candidate['metadata_status'],'unverified')
            self.assertEqual(candidate['access_level'],'metadata')


if __name__=='__main__':
    unittest.main()
