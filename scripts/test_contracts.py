"""Contract boundary tests: validation must reject malformed nested artifacts."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from contracts import ContractError, check_schemas, export_reference, load_schema, load_validate, names, validate

NOW = '2026-10-06T12:00:00+08:00'
HASH = 'a' * 64
FILE = {'path': 'data/raw.csv', 'sha256': HASH}
SOURCE = {'id': 'S1', 'title': 'Verified API title', 'url': 'https://example.org/source',
          'access_level': 'fulltext', 'metadata_status': 'verified'}
EVIDENCE = {'id': 'E1', 'source_id': 'S1', 'claim': 'A bounded reported observation',
            'locator': 'p. 4, table 2', 'support_status': 'supports', 'claim_verification': 'verified'}


def v(**data):
    return {'schema_version': 1, 'id': 'test', **data}


def fixtures():
    return {
        'project-spec': v(topic='Adult learning', mode='empirical', language='zh-CN', created_at=NOW,
                          question='How is learning associated with support?', deliverable='Research report'),
        'search-query': v(query='adult learning', providers=['crossref'], limit=5,
                         filters={'year_min': None, 'year_max': 2026}),
        'source-record': SOURCE,
        'evidence-record': EVIDENCE,
        'screening': v(criteria={'include_terms': ['adult'], 'exclude_terms': [], 'year_min': None,
                                  'year_max': None, 'require_abstract': True},
                       decisions=[{'source_id': 'S1', 'decision': 'include', 'reason': 'Matches scope',
                                   'rule_ids': ['term'], 'reviewer': 'Codex', 'reviewed_at': NOW}],
                       dedup={'exact_duplicates': [{'kept_id': 'S1', 'removed_id': 'S2', 'reason': 'Same DOI'}],
                              'possible_duplicates': [{'source_ids': ['S1', 'S3'], 'similarity': .93,
                                                       'reason': 'Similar titles, uncertain identity'}]}),
        'synthesis': v(question='Question', findings=[{'id': 'F1', 'claim': 'Claim', 'evidence_ids': ['E1'],
                                                     'source_ids': ['S1'], 'confidence': 'low'}],
                       comparisons=[{'dimension': 'Sample', 'source_ids': ['S1'], 'summary': 'Limited scope'}],
                       contradictions=[], gaps=['Replicate elsewhere'], limitations=['Few sources']),
        'study-design': v(question='Question', hypotheses=[{'id': 'H1', 'statement': 'Hypothesis',
                              'evidence_ids': ['E1'], 'status': 'proposed'}], method='Comparative',
                          design='Observational', variables=[{'name': 'score', 'role': 'outcome',
                              'type': 'number', 'description': 'Learning measure'}],
                          analysis_plan='OLS with HC3 uncertainty', sample_plan='Available sample', limitations=[]),
        'dataset-spec': v(path='data/raw.csv', sha256=HASH, source_url='https://example.org/data',
                         license='CC0', unit_of_analysis='school', columns=[{'name': 'score', 'type': 'number',
                         'required': True, 'description': 'Score'}], missing_values=['', None],
                         cleaning={'drop_exact_duplicates': False, 'missing_policy': 'complete_case'}),
        'analysis-result': v(status='executed', reason='Analyze supplied public data', input_files=[FILE],
                             code={'path': 'analysis/reproduce.py', 'sha256': HASH},
                             environment={'python': '3.12', 'platform': 'macOS', 'packages': {'numpy': '2.3'}},
                             method='OLS', parameters={'outcome': 'score'},
                             sample={'input_rows': 10, 'output_rows': 9, 'dropped_rows': 1},
                             results={'coefficient': .23}, limitations=['Observational']),
        'research-report': v(title='Report', sections=[{'id': 'intro', 'heading': 'Introduction',
                            'text': 'Bounded results', 'claim_ids': ['C1']}],
                            claims=[{'id': 'C1', 'text': 'Claim', 'evidence_ids': ['E1'],
                                     'analysis_ids': [], 'status': 'supported'}],
                            references=[{'source_id': 'S1', 'title': 'Source', 'url': 'https://example.org/source'}],
                            limitations=[]),
        'manuscript': v(title='Synthetic manuscript',paper_type='conceptual',abstract='Synthetic abstract for contract validation only. '*5,
                       keywords=['fixture','schema','paper'],sections=[{'id':str(i),'heading':role,'role':role,'paragraphs':[{'id':'p'+str(i),'text':'Synthetic test paragraph for checking a manuscript schema, not scientific evidence.','stance':'interpretation','source_ids':['S1'],'claim_ids':[]}]} for i,role in enumerate(['introduction','methods','findings','discussion','conclusion'])],
                       references=[{'source_id':'S1','citation':'Synthetic author. Synthetic source.','url':'https://example.org/source'}]),
        'quality-report': v(evaluated_at=NOW, metrics=[{'id': 'schema_pass_rate', 'name': 'Schema pass rate',
                            'value': 1.0, 'numerator': 3, 'denominator': 3, 'threshold': 1.0,
                            'status': 'pass', 'severity': 'error', 'reason': 'All checked schemas pass'}],
                            overall_status='pass', limitations=[]),
        'screening-benchmark': v(labels=[{'source_id': 'S1', 'include': True}], labeler='Independent reviewer', labelled_at=NOW, independent=True),
        'quality-policy': v(metrics=[{'id': 'schema_pass_rate', 'min': 1.0, 'severity': 'error', 'required': True}]),
        'model-request': v(task='summarize', prompt='Compare grounded claims', context=[{'role': 'user',
                           'content': 'Context'}], response_schema={'type': 'object'}, model='current-session', parameters={}),
        'model-response': v(request_id='request-1', backend='codex', model='current-session',
                            status='needs_execution', output={}, usage={},
                            provenance={'created_at': NOW, 'backend_version': '1', 'execution_mode': 'codex-handoff'}),
        'human-decision': v(stage='design', status='requested', question='Confirm an unresolved research aim',
                            options=['A', 'B'], requested_at=NOW, answer=None, answered_at=None, actor=None),
        'stage-task': v(stage='read', status='pending', runnable=True, dependencies=['search'],
                        skills=['literature-reading-and-synthesis'], required_artifacts=['research/evidence.json'],
                        inputs=['research/sources.json'], reason='', action='Read full texts',
                        retry={'attempt': 0, 'max_attempts': 3, 'next_retry_at': None}, human_decision_ids=[]),
        'pipeline-policy': v(max_failures=3, backoff_seconds=1, max_backoff_seconds=10),
        'cleaning-log': v(record_number_definition='1-based data row excluding header', input_rows=10,
                          output_rows=9, rules=[{'rule': 'missing_selected_numeric', 'policy': 'complete_case',
                          'before': 10, 'after': 9, 'affected_records': [2],
                          'details': [{'source_record': 2, 'columns': ['score']}]}],
                          kept_source_records=[1, 3, 4, 5, 6, 7, 8, 9, 10], selected_columns=['score']),
    }


class ContractsTest(unittest.TestCase):
    def test_all_schema_files_are_valid_draft_2020_12(self):
        self.assertEqual(check_schemas(), 20)
        for name in names():
            self.assertEqual(load_schema(name)['$schema'], 'https://json-schema.org/draft/2020-12/schema')

    def test_every_schema_has_a_valid_example(self):
        self.assertEqual(set(names()), set(fixtures()))
        for name, data in fixtures().items():
            with self.subTest(name=name):
                validate(name, data)

    def test_all_new_documents_require_integer_version_and_id(self):
        for name, data in fixtures().items():
            if name in ('source-record', 'evidence-record'):
                continue
            for field in ('schema_version', 'id'):
                broken = deepcopy(data)
                del broken[field]
                with self.subTest(name=name, field=field), self.assertRaises(ContractError):
                    validate(name, broken)
            broken = deepcopy(data)
            broken['schema_version'] = '1'
            with self.subTest(name=name), self.assertRaises(ContractError):
                validate(name, broken)

    def test_new_document_rejects_unknown_top_level_fields(self):
        for name, data in fixtures().items():
            if name in ('source-record', 'evidence-record'):
                continue
            broken = deepcopy(data)
            broken['accidentally_misspelled'] = True
            with self.subTest(name=name), self.assertRaises(ContractError):
                validate(name, broken)

    def test_nested_missing_field_is_rejected(self):
        data = fixtures()['screening']
        del data['decisions'][0]['reason']
        with self.assertRaises(ContractError):
            validate('screening', data)

    def test_nested_unknown_field_is_rejected(self):
        data = fixtures()['dataset-spec']
        data['columns'][0]['requred'] = True
        with self.assertRaises(ContractError):
            validate('dataset-spec', data)

    def test_nested_wrong_type_is_rejected(self):
        data = fixtures()['research-report']
        data['claims'][0]['evidence_ids'] = 'E1'
        with self.assertRaises(ContractError):
            validate('research-report', data)

    def test_nested_invalid_enum_is_rejected(self):
        data = fixtures()['study-design']
        data['hypotheses'][0]['status'] = 'proven'
        with self.assertRaises(ContractError):
            validate('study-design', data)

    def test_date_time_is_checked(self):
        data = fixtures()['quality-report']
        data['evaluated_at'] = 'yesterday'
        with self.assertRaises(ContractError):
            validate('quality-report', data)

    def test_uri_is_checked_without_optional_format_extras(self):
        for value in ('not a URI', 'https://', 'https://example.org:bad/path'):
            data = deepcopy(SOURCE)
            data['url'] = value
            with self.subTest(value=value), self.assertRaises(ContractError):
                validate('source-record', data)

    def test_impossible_date_is_rejected(self):
        data = fixtures()['quality-report']
        data['evaluated_at'] = '2026-02-30T01:00:00Z'
        with self.assertRaises(ContractError):
            validate('quality-report', data)

    def test_hash_is_checked(self):
        data = fixtures()['dataset-spec']
        data['sha256'] = 'not-a-digest'
        with self.assertRaises(ContractError):
            validate('dataset-spec', data)

    def test_boolean_is_not_integer(self):
        data = fixtures()['stage-task']
        data['retry']['attempt'] = True
        with self.assertRaises(ContractError):
            validate('stage-task', data)

    def test_nonfinite_numbers_are_rejected(self):
        for value in (float('nan'), float('inf'), float('-inf')):
            data = fixtures()['quality-report']
            data['metrics'][0]['value'] = value
            with self.subTest(value=value), self.assertRaises(ContractError):
                validate('quality-report', data)

    def test_legacy_source_and_evidence_records_accept_arrays_and_metadata(self):
        for name, record in (('source-record', SOURCE), ('evidence-record', EVIDENCE)):
            row = dict(record, provider_specific_history={'old': True})
            validate(name, row)
            validate(name, [row])
            broken = dict(row)
            del broken['id']
            with self.assertRaises(ContractError):
                validate(name, [broken])

    def test_executed_analysis_requires_code_and_results(self):
        for field, value in [('code', None), ('results', {}), ('input_files', [])]:
            data = fixtures()['analysis-result']
            data[field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                validate('analysis-result', data)

    def test_planned_analysis_has_explicit_reason_but_no_fake_results(self):
        data = fixtures()['analysis-result']
        data.update(status='planned', reason='Original data is not available', code=None, input_files=[], results={},
                    sample={'input_rows': 0, 'output_rows': 0, 'dropped_rows': 0})
        validate('analysis-result', data)
        data['reason'] = ''
        with self.assertRaises(ContractError):
            validate('analysis-result', data)

    def test_answered_human_decision_requires_actor_answer_and_time(self):
        data = fixtures()['human-decision']
        data['status'] = 'answered'
        with self.assertRaises(ContractError):
            validate('human-decision', data)
        data.update(answer='A', answered_at=NOW, actor='user')
        validate('human-decision', data)

    def test_policy_unknown_metric_is_rejected(self):
        data = fixtures()['quality-policy']
        data['metrics'][0]['id'] = 'imaginary_semantic_accuracy'
        with self.assertRaises(ContractError):
            validate('quality-policy', data)

    def test_unknown_schema_name_does_not_resolve_arbitrary_files(self):
        with self.assertRaises(ContractError):
            validate('../../config', {})

    def test_load_validate_reports_json_and_validation_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'query.json'
            path.write_text('{"bad":NaN}')
            with self.assertRaises(ContractError):
                load_validate('search-query', path)
            path.write_text(json.dumps(fixtures()['search-query']))
            self.assertEqual(load_validate('search-query', path)['limit'], 5)

    def test_reference_generated_from_actual_nested_schema(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'reference.md'
            export_reference(path)
            text = path.read_text()
            for name in names():
                self.assertIn('## '+name, text)
            self.assertIn('`decisions[].reason`', text)
            self.assertIn('`columns[].required`', text)
            self.assertIn('`code.sha256`', text)


if __name__ == '__main__':
    unittest.main()
