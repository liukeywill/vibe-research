"""Offline structured workflow integration fixtures; these are not research results."""
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

import analyze_data
import contracts
import quality
import human_decisions
import pipeline
import screen_sources
import stage_contracts
import model_backends
import provenance
import workspace
from test_contracts import fixtures, NOW, SOURCE, EVIDENCE


class StructuredWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'study'
        pipeline.initialize(self.root, 'Offline integration fixture', profile='structured')
        self.prepare()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def read(self, path):
        return json.loads((self.root / path).read_text())

    def prepare(self):
        values = deepcopy(fixtures())
        for stage in pipeline.NAMES:
            for path in pipeline.STAGES[stage][0]:
                if not path.endswith('.json'):
                    self.write(path, '# '+stage+'\n\nOffline integration fixture; not real research.\n')
        self.write('project-spec.json', values['project-spec'])
        self.write('research/search-query.json', values['search-query'])
        self.write('research/search-results.json', [SOURCE])
        values['screening']['dedup'] = {'exact_duplicates': [], 'possible_duplicates': []}
        self.write('research/screening.json', values['screening'])
        self.write('research/texts/S1.txt', 'This is a local synthetic source fixture, not scientific evidence.')
        source = dict(SOURCE, local_text='research/texts/S1.txt', content_sha256=pipeline.digest(self.root, 'research/texts/S1.txt'))
        self.write('research/sources.json', [source])
        self.write('research/evidence.json', [dict(EVIDENCE, reviewer='fixture-reviewer', reviewed_at=NOW)])
        self.write('research/synthesis.json', values['synthesis'])
        self.write('research/study-design.json', values['study-design'])
        self.write('data/raw.csv', 'score,x\n10,1\n13,2\n14,3\n16,4\n20,5\n21,6\n25,7\n25,8\n29,9\n30,10\n')
        self.write('analysis/reproduce.py', '# Offline fixture, not an executed analysis.\n')
        dataset = values['dataset-spec']
        dataset['sha256'] = pipeline.digest(self.root, 'data/raw.csv')
        dataset['columns'].append({'name':'x','type':'number','required':True,'description':'Synthetic predictor'})
        self.write('data/dataset-spec.json', dataset)
        analysis = values['analysis-result']
        analysis['input_files'] = [{'path': 'data/raw.csv', 'sha256': dataset['sha256']}]
        analysis['code'] = {'path': 'analysis/reproduce.py', 'sha256': pipeline.digest(self.root, 'analysis/reproduce.py')}
        self.write('research/analysis-result.json', analysis)
        values['research-report']['references'][0].update(title=SOURCE['title'],url=SOURCE['url'])
        self.write('report.json', values['research-report'])
        self.write('review/quality-report.json', values['quality-report'])

    def through(self, last):
        result = None
        for stage in pipeline.NAMES[:pipeline.NAMES.index(last)+1]:
            if stage == 'analyze':
                analyze_data.analyze(self.root, 'data/dataset-spec.json', 'score', ['x'])
            if stage == 'review':
                quality.evaluate(self.root)
            result = pipeline.operate(self.root, 'complete', stage)
        return result

    def test_full_structured_fixture_completes_all_stages(self):
        result = self.through('review')
        self.assertEqual(result['status'], 'complete')
        state = pipeline.load(self.root)
        self.assertEqual(state['profile'], 'structured')
        self.assertTrue(all(record['status'] == 'succeeded' for record in state['stages'].values()))
        self.assertIn('data/raw.csv', state['stages']['analyze']['tracked'])
        self.assertIn('analysis-code/reproduce.py', state['stages']['analyze']['tracked'])
        self.assertIn('data/dataset-spec.json', state['stages']['analyze']['tracked'])

    def test_runtime_snapshot_change_stales_scope(self):
        self.through('review')
        self.write('runtime-snapshot/scripts/contracts.py', '# deliberately changed fixture\n')
        result=pipeline.operate(self.root,'next')
        self.assertEqual(result['next']['stage'],'scope')
        self.assertEqual(result['stages']['review']['status'],'stale')

    def test_execution_engine_must_match_frozen_receipt(self):
        provenance.assert_execution(self.root)
        manifest=self.read('engine-manifest.json')
        manifest['files'][0]['sha256']='f'*64
        self.write('engine-manifest.json',manifest)
        with self.assertRaisesRegex(workspace.WorkspaceError,'执行代码'):
            pipeline.operate(self.root,'start','scope')

    def codex_scope_request(self):
        return {'schema_version':1,'id':'fixture-scope','task':'scope','prompt':'Synthetic integration fixture',
                'context':[],'response_schema':contracts.load_schema('project-spec'),'model':'fixture-current-session',
                'parameters':{'artifact_path':'project-spec.json'},'input_files':[]}

    def test_incomplete_model_handoff_cannot_complete_stage(self):
        model_backends.CodexBackend(self.root).generate(self.codex_scope_request())
        with self.assertRaises(OSError):pipeline.operate(self.root,'complete','scope')

    def test_completed_model_receipt_tracked_and_change_invalidates(self):
        req=self.codex_scope_request()
        model_backends.CodexBackend(self.root).accept(req,self.read('project-spec.json'))
        self.through('review')
        self.assertIn('model-io/fixture-scope.response.json',pipeline.load(self.root)['stages']['scope']['tracked'])
        self.write('model-io/fixture-scope.response.json',{})
        self.assertEqual(pipeline.operate(self.root,'next')['next']['stage'],'scope')

    def test_receipt_output_must_match_current_artifact(self):
        req=self.codex_scope_request()
        wrong=self.read('project-spec.json');wrong['question']='Different fixture question'
        model_backends.CodexBackend(self.root).accept(req,wrong)
        with self.assertRaisesRegex(workspace.WorkspaceError,'回执'):
            pipeline.operate(self.root,'complete','scope')

    def test_excluded_source_cannot_be_registered_as_read_evidence(self):
        self.through('search')
        screening=self.read('research/screening.json')
        screening['decisions'][0]['decision']='exclude'
        self.write('research/screening.json',screening)
        # Direct read gate check isolates source admission from upstream staleness.
        with self.assertRaisesRegex(workspace.WorkspaceError,'纳入'):
            stage_contracts.validate_stage(self.root,'read','executed')

    def test_schema_missing_nested_field_blocks_complete(self):
        self.through('read')
        synthesis = self.read('research/synthesis.json')
        del synthesis['findings'][0]['claim']
        self.write('research/synthesis.json', synthesis)
        with self.assertRaises(contracts.ContractError):
            pipeline.operate(self.root, 'complete', 'synthesize')
        self.assertEqual(pipeline.operate(self.root, 'status')['next']['stage'], 'synthesize')

    def test_missing_structured_json_is_not_replaced_by_markdown(self):
        (self.root / 'project-spec.json').unlink()
        with self.assertRaises(workspace.WorkspaceError):
            pipeline.operate(self.root, 'complete', 'scope')

    def test_raw_data_change_stales_analysis_and_downstream(self):
        self.through('review')
        self.write('data/raw.csv', 'score,x\n10,1\n99,2\n14,3\n')
        view = pipeline.operate(self.root, 'next')
        self.assertEqual(view['next']['stage'], 'analyze')
        self.assertEqual(view['stages']['design']['status'], 'succeeded')
        for stage in ('analyze', 'package', 'review'):
            self.assertEqual(view['stages'][stage]['status'], 'stale')
        with self.assertRaisesRegex(workspace.WorkspaceError, '哈希'):
            pipeline.operate(self.root, 'complete', 'analyze')

    def test_analysis_code_change_stales_analysis_and_downstream(self):
        self.through('review')
        self.write('analysis-code/reproduce.py', '# Changed after recorded analysis.\n')
        view = pipeline.operate(self.root, 'next')
        self.assertEqual(view['next']['stage'], 'analyze')
        self.assertEqual(view['stages']['package']['status'], 'stale')
        self.assertEqual(view['stages']['review']['status'], 'stale')

    def test_supported_claim_cannot_reference_planned_analysis(self):
        self.through('design')
        analysis = self.read('research/analysis-result.json')
        analysis.update(status='planned', reason='No original data', input_files=[], code=None, results={},
                        sample={'input_rows': 0, 'output_rows': 0, 'dropped_rows': 0})
        self.write('research/analysis-result.json', analysis)
        self.write('research/analysis.md', 'planned\nNo original data\n')
        pipeline.operate(self.root, 'complete', 'analyze', disposition='planned', reason='No original data')
        report = self.read('report.json')
        report['claims'][0].update(evidence_ids=[], analysis_ids=[analysis['id']], status='supported')
        self.write('report.json', report)
        with self.assertRaisesRegex(workspace.WorkspaceError, 'planned'):
            pipeline.operate(self.root, 'complete', 'package')
        report['claims'][0]['status'] = 'hypothesis'
        self.write('report.json', report)
        self.assertEqual(pipeline.operate(self.root, 'complete', 'package')['next']['stage'], 'review')

    def test_supported_claim_cannot_treat_unclear_evidence_as_support(self):
        evidence = self.read('research/evidence.json')
        evidence[0]['support_status'] = 'unclear'
        evidence.append(dict(EVIDENCE, id='E2', reviewer='fixture-reviewer', reviewed_at=NOW))
        self.write('research/evidence.json', evidence)
        self.through('analyze')
        with self.assertRaises(workspace.WorkspaceError):
            pipeline.operate(self.root, 'complete', 'package')

    def test_supported_claim_rejects_unverified_source_metadata(self):
        sources = self.read('research/sources.json')
        sources[0]['metadata_status'] = 'unverified'
        self.write('research/sources.json', sources)
        with self.assertRaises(workspace.WorkspaceError):
            stage_contracts.validate_stage(self.root, 'package', 'executed')

    def test_human_request_blocks_retry_until_fixture_answer(self):
        request = human_decisions.record(self.root, 'scope', 'Fixture question, not a real user request', ['A','B'])
        view = pipeline.operate(self.root, 'next')
        self.assertEqual(view['status'], 'blocked')
        self.assertFalse(view['next']['runnable'])
        self.assertIn(request['id'], view['next']['human_decision_ids'])
        with self.assertRaisesRegex(workspace.WorkspaceError, '人工'):
            pipeline.operate(self.root, 'retry', 'scope', reason='No actual answer yet')
        with self.assertRaises(workspace.WorkspaceError):
            pipeline.operate(self.root, 'complete', 'scope')
        answer = human_decisions.answer(self.root, request['id'], 'A (synthetic test answer)', 'offline-test-fixture')
        self.assertEqual(answer['status'], 'answered')
        view = pipeline.operate(self.root, 'next')
        self.assertTrue(view['next']['runnable'])
        self.assertEqual(view['next']['human_decision_ids'], [])
        self.assertEqual(pipeline.operate(self.root, 'complete', 'scope')['next']['stage'], 'search')

    def test_human_answer_cannot_be_fabricated_by_empty_fields(self):
        request = human_decisions.record(self.root, 'scope', 'Fixture question', ['A'])
        with self.assertRaises(ValueError):
            human_decisions.answer(self.root, request['id'], '', 'offline-test-fixture')
        self.assertEqual(pipeline.operate(self.root, 'next')['status'], 'blocked')

    def test_retry_policy_enforces_backoff_and_failure_limit(self):
        policy = self.read('pipeline-policy.json')
        policy.update(backoff_seconds=60, max_backoff_seconds=60)
        self.write('pipeline-policy.json', policy)
        result = pipeline.operate(self.root, 'start', 'scope')
        self.assertEqual(result['next']['status'], 'running')
        result = pipeline.operate(self.root, 'fail', 'scope', reason='Synthetic transient failure')
        self.assertEqual(result['next']['status'], 'failed')
        self.assertFalse(result['next']['runnable'])
        self.assertIsNotNone(result['next']['retry']['next_retry_at'])
        with self.assertRaises(workspace.WorkspaceError):
            pipeline.operate(self.root, 'complete', 'scope')
        pipeline.operate(self.root, 'fail', 'scope', reason='Synthetic second failure')
        result = pipeline.operate(self.root, 'fail', 'scope', reason='Synthetic third failure')
        self.assertEqual(result['status'], 'blocked')
        result = pipeline.operate(self.root, 'retry', 'scope', reason='Fixture repair completed')
        self.assertTrue(result['next']['runnable'])
        self.assertEqual(result['next']['retry']['attempt'], 0)
        events = [json.loads(line) for line in (self.root/'events.jsonl').read_text().splitlines()]
        self.assertEqual(sum(event['event'] == 'fail' for event in events), 3)

    def test_quality_fail_blocks_review(self):
        self.through('package')
        report = self.read('review/quality-report.json')
        report['overall_status'] = 'fail'
        report['metrics'][0].update(value=0, numerator=0, status='fail', reason='Fixture failure')
        self.write('review/quality-report.json', report)
        with self.assertRaisesRegex(workspace.WorkspaceError, '质量'):
            pipeline.operate(self.root, 'complete', 'review')
        self.assertEqual(pipeline.operate(self.root, 'next')['next']['stage'], 'review')

    def test_screening_must_cover_all_candidates(self):
        self.through('scope')
        screening = self.read('research/screening.json')
        screening['decisions'] = []
        self.write('research/screening.json', screening)
        with self.assertRaisesRegex(workspace.WorkspaceError, '覆盖'):
            pipeline.operate(self.root, 'complete', 'search')

    def test_exact_duplicate_excluded_near_duplicate_kept_with_audit(self):
        records = [dict(SOURCE, id='A', title='Adult learning support effects', doi='10.1234/a', year=2025),
                   dict(SOURCE, id='B', title='Adult learning support effects duplicate record', doi='10.1234/a', year=2025),
                   dict(SOURCE, id='C', title='Adult learning support effect', doi='10.1234/c', year=2025)]
        before = deepcopy(records)
        criteria = {'include_terms':['adult'], 'exclude_terms':[], 'year_min':None,'year_max':None,'require_abstract':False}
        report = screen_sources.screen(records, criteria)
        by_id = {row['source_id']:row for row in report['decisions']}
        self.assertEqual(by_id['B']['decision'], 'exclude')
        self.assertEqual(len(report['dedup']['exact_duplicates']), 1)
        self.assertEqual(by_id['C']['decision'], 'include')
        self.assertTrue(report['dedup']['possible_duplicates'])
        self.assertEqual(len(report['decisions']), 3)
        self.assertEqual(records, before)

    def test_screening_empty_criteria_rejected_before_write(self):
        self.write('research/criteria.json', {})
        original = (self.root/'research/screening.json').read_bytes()
        with self.assertRaises(contracts.ContractError):
            screen_sources.run(self.root, 'research/criteria.json', force=True)
        self.assertEqual((self.root/'research/screening.json').read_bytes(), original)

    def test_cli_defaults_to_structured_but_legacy_api_remains_compatible(self):
        other = self.base/'cli-default'
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = pipeline.main(['init','--project',str(other),'--topic','CLI fixture'])
        self.assertEqual(code,0)
        task = json.loads(stream.getvalue())['next']
        contracts.validate('stage-task', task)
        self.assertIn('project-spec.json', task['required_artifacts'])
        legacy = self.base/'legacy'
        pipeline.initialize(legacy,'Legacy fixture')
        self.assertNotIn('profile', pipeline.load(legacy))
        (legacy/'question.md').write_text('Legacy scope fixture')
        self.assertEqual(pipeline.operate(legacy,'complete','scope')['next']['stage'],'search')


if __name__ == '__main__':
    unittest.main()
