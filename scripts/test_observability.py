"""All projects, answers and human records here are synthetic test fixtures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import benchmark
import dashboard
import improvement
import pipeline
import research_mode
import research_tools as rt


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        self.state = {'current_stage': 2, 'title': '合成测试项目', 'stages': {
            '2': {'status': 'awaiting_human_check', 'artifacts': [],
                  'human_checks': [{'id': 'H1', 'status': 'unchecked'}]}}}
        rt.write(self.project / 'state.json', self.state)
        self.base = self.root / 'base-skill'
        self.candidate = self.root / 'candidate-skill'
        for directory, text in [(self.base, 'old fixture'), (self.candidate, 'new fixture')]:
            rt.write(directory / 'SKILL.md', text)

    def run_fixture(self, name, candidate=None, wrong=(), origin='fixture', missing=()):
        run = self.project / 'review/evals' / name
        benchmark.prepare(run, candidate or self.candidate, name)
        _, manifest, suite = benchmark.load_run(run)
        answers = []
        for case in suite['cases']:
            if case['id'] in missing:
                continue
            answers.append({'case_id': case['id'], 'decision': 'wrong' if case['id'] in wrong else case['expected']['decision'],
                            'evidence_ids': case['expected']['evidence_ids'], 'reason': 'synthetic test response',
                            'model_calls': None, 'tool_calls': None})
        response = {'request_sha256': manifest['request_sha256'], 'origin': origin,
                    'model': manifest['model'], 'answers': answers}
        path = self.root / (name + '-responses.json')
        rt.write(path, response)
        benchmark.submit(run, path)
        return run, response


class DashboardTests(Fixture):
    def test_manual_dashboard_preserves_state_and_unchecked_items(self):
        before = (self.project / 'state.json').read_bytes()
        result = dashboard.build(self.project)
        snap = rt.read(result['json'])
        self.assertEqual((self.project / 'state.json').read_bytes(), before)
        self.assertEqual(snap['mode'], 'manual')
        self.assertEqual(snap['stages'][0]['human_checks'][0]['status'], 'unchecked')
        self.assertEqual(research_mode.select_mode()['mode'], 'manual')

    def test_claim_evidence_source_chain_and_missing_reference(self):
        rt.write(self.project / 'research/sources.json', [{'id': 'S1', 'title': 'test source'}])
        rt.write(self.project / 'research/evidence.json', [{'id': 'E1', 'source_id': 'S1', 'locator': '表2'}])
        rt.write(self.project / 'report.json', {'claims': [{'id': 'C1', 'text': 'test claim', 'evidence_ids': ['E1', 'missing']}]})
        snap = dashboard.snapshot(self.project)
        self.assertEqual(snap['claims'][0]['links'][0]['source']['id'], 'S1')
        self.assertEqual(snap['claims'][0]['links'][0]['evidence']['locator'], '表2')
        self.assertTrue(snap['warnings'])

    def test_duplicate_source_ids_are_ambiguous_not_silently_linked(self):
        rt.write(self.project / 'research/sources.json', [{'id': 'S1', 'title': 'first'}, {'id': 'S1', 'title': 'different'}])
        rt.write(self.project / 'research/evidence.json', [{'id': 'E1', 'source_id': 'S1'}])
        rt.write(self.project / 'report.json', {'claims': [{'id': 'C1', 'evidence_ids': ['E1']}]})
        snap = dashboard.snapshot(self.project)
        self.assertIsNone(snap['claims'][0]['links'][0]['source'])
        self.assertIn('ID重复', str(snap['warnings']))

    def test_untrusted_html_and_javascript_urls_are_inert(self):
        self.state['title'] = '<script>alert(1)</script>'
        rt.write(self.project / 'state.json', self.state)
        rt.write(self.project / 'research/sources.json', [{'id': 'S1', 'title': '<img onerror=alert(1)>', 'url': 'javascript:alert(1)'}])
        result = dashboard.build(self.project)
        html = Path(result['html']).read_text()
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertNotIn('href="javascript:', html)
        self.assertIn('&lt;script&gt;', html)

    def test_missing_artifact_is_explicit(self):
        self.state['stages']['2']['artifacts'] = [{'path': 'missing.md', 'verification': 'unverified'}]
        rt.write(self.project / 'state.json', self.state)
        self.assertIn('missing.md', str(dashboard.snapshot(self.project)['warnings']))

    def test_conflicting_modes_fail_without_changing_either_state(self):
        rt.write(self.project / 'pipeline-state.json', {'stages': {}})
        before = {p.name: p.read_bytes() for p in self.project.glob('*.json')}
        with self.assertRaises(ValueError):
            dashboard.build(self.project)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.project.glob('*.json')})

    def test_path_escape_and_symlink_are_rejected(self):
        with self.assertRaises(ValueError):
            dashboard.build(self.project, '../outside.html')
        (self.project / 'review').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            dashboard.build(self.project)

    def test_model_receipts_are_linked(self):
        rt.write(self.project / 'model-io/test.response.json', {'request_id': 'test', 'backend': 'codex', 'status': 'completed', 'output': {'secret_material': 'not embedded'}})
        snap = dashboard.snapshot(self.project)
        self.assertEqual(len(snap['receipts']), 1)
        self.assertNotIn('secret_material', json.dumps(snap['receipts']))

    def test_automatic_dashboard_detects_changed_hash_without_invalidating_state(self):
        automatic = self.root / 'automatic'
        pipeline.initialize(automatic, 'synthetic', profile='legacy')
        state = pipeline.load(automatic)
        rt.write(automatic / 'question.md', 'old')
        pipeline.operate(automatic, 'start', 'scope')
        pipeline.operate(automatic, 'complete', 'scope')
        rt.write(automatic / 'question.md', 'changed')
        before = (automatic / 'pipeline-state.json').read_bytes()
        snap = dashboard.snapshot(automatic)
        self.assertIn('question.md', str(snap['warnings']))
        self.assertEqual(before, (automatic / 'pipeline-state.json').read_bytes())

    def test_new_directory_is_not_initialized(self):
        path = self.root / 'absent'
        with self.assertRaises(ValueError):
            dashboard.build(path)
        self.assertFalse(path.exists())

    def test_dashboard_cannot_overwrite_quality_report(self):
        rt.write(self.project / 'review/quality-report.json', {'keep': True})
        with self.assertRaises(ValueError):
            dashboard.build(self.project, 'review/quality-report.html')
        self.assertEqual(rt.read(self.project / 'review/quality-report.json'), {'keep': True})

    def test_source_snapshot_changes_are_visible(self):
        rt.write(self.project / 'research/texts/source.txt', 'original')
        rt.write(self.project / 'research/sources.json', [{'id': 'S1', 'local_text': 'research/texts/source.txt',
                                                         'content_sha256': rt.sha(self.project / 'research/texts/source.txt')}])
        rt.write(self.project / 'research/texts/source.txt', 'changed')
        self.assertIn('原文快照', str(dashboard.snapshot(self.project)['warnings']))


class BenchmarkTests(Fixture):
    def test_changed_candidate_cannot_receive_old_run_responses(self):
        run, response = self.run_fixture('run')
        rt.write(self.candidate / 'SKILL.md', 'changed candidate')
        response_path = self.root / 'retry.json'
        rt.write(response_path, response)
        with self.assertRaises(ValueError):
            benchmark.submit(run, response_path)

    def test_actual_and_fixture_results_cannot_be_mixed(self):
        base, _ = self.run_fixture('base', self.base, origin='actual')
        new, _ = self.run_fixture('new', origin='fixture')
        with self.assertRaises(ValueError):
            benchmark.compare(base, new)

    def test_new_structured_snapshot_includes_fixed_suite(self):
        import provenance
        directory = self.root / 'frozen'
        directory.mkdir()
        manifest = provenance.capture(directory)
        self.assertIn('runtime-snapshot/assets/research-regression.json', [f['path'] for f in manifest['files']])
        self.assertTrue((directory / 'runtime-snapshot/scripts/dashboard.py').is_file())

    def test_prepare_is_only_a_handoff_and_snapshot_contains_no_expected_answers(self):
        path = self.root / 'unexecuted'
        benchmark.prepare(path, self.base, 'baseline')
        self.assertNotIn('expected', (path / 'request.json').read_text())
        self.assertFalse((path / 'score.json').exists())
        with self.assertRaises(OSError):
            benchmark.score(path)

    def test_missing_answer_counts_as_failure(self):
        run, _ = self.run_fixture('missing', missing=['causal-boundary'])
        result = benchmark.score(run)
        self.assertEqual((result['coverage'], result['total'], result['passed']), (7, 8, 7))

    def test_fixture_improvement_does_not_authorize_adoption(self):
        base, _ = self.run_fixture('base', self.base, wrong=['causal-boundary'])
        new, _ = self.run_fixture('new')
        self.assertFalse(benchmark.compare(base, new)['eligible_for_human_review'])

    def test_tie_retains_parent(self):
        base, _ = self.run_fixture('base', self.base, origin='actual')
        new, _ = self.run_fixture('new', origin='actual')
        self.assertEqual(benchmark.compare(base, new)['decision'], 'retain_parent')

    def test_higher_total_with_a_regression_is_ineligible(self):
        base, _ = self.run_fixture('base', self.base, wrong=['abstract-access', 'causal-boundary'], origin='actual')
        new, _ = self.run_fixture('new', wrong=['planned-analysis'], origin='actual')
        comparison = benchmark.compare(base, new)
        self.assertEqual(comparison['regressions'], ['planned-analysis'])
        self.assertFalse(comparison['eligible_for_human_review'])

    def test_strict_improvement_has_to_change_candidate_content(self):
        base, _ = self.run_fixture('base', self.base, wrong=['abstract-access'], origin='actual')
        new, _ = self.run_fixture('new', self.base, origin='actual')
        self.assertFalse(benchmark.compare(base, new)['eligible_for_human_review'])

    def test_duplicate_unknown_or_stale_answers_are_rejected(self):
        run, response = self.run_fixture('run')
        for altered in [dict(response, request_sha256='0' * 64),
                        dict(response, answers=response['answers'] + [response['answers'][0]])]:
            with self.assertRaises(ValueError):
                benchmark.evaluate(run, altered)
        other = copy.deepcopy(response)
        other['answers'][0]['case_id'] = 'unknown'
        with self.assertRaises(ValueError):
            benchmark.evaluate(run, other)

    def test_budget_and_unknown_usage_are_reported(self):
        run, response = self.run_fixture('run')
        response['answers'][0]['tool_calls'] = 1
        score = benchmark.evaluate(run, response)
        self.assertEqual(score['passed'], 7)
        self.assertFalse(score['usage_measured'])

    def test_saved_score_cannot_override_actual_responses(self):
        run, _ = self.run_fixture('run', wrong=['abstract-access'])
        rt.write(run / 'score.json', {'score': 1})
        self.assertEqual(benchmark.score(run)['passed'], 7)

    def test_suite_tampering_and_overwriting_completed_answers_fail(self):
        run, response = self.run_fixture('run')
        changed = copy.deepcopy(response)
        changed['answers'][0]['reason'] = 'changed'
        altered = self.root / 'altered.json'
        rt.write(altered, changed)
        with self.assertRaises(ValueError):
            benchmark.submit(run, altered)
        suite = rt.read(run / 'suite.json')
        suite['cases'].pop()
        rt.write(run / 'suite.json', suite)
        with self.assertRaises(ValueError):
            benchmark.score(run)

    def test_mismatched_model_or_budget_cannot_be_compared(self):
        base, _ = self.run_fixture('base', self.base)
        new, _ = self.run_fixture('new')
        manifest = rt.read(new / 'manifest.json')
        manifest['model'] = 'different-model'
        rt.write(new / 'manifest.json', manifest)
        with self.assertRaises(ValueError):
            benchmark.compare(base, new)


class ImprovementTests(Fixture):
    def proposal(self):
        rt.write(self.project / 'review/error.txt', 'synthetic observed failure')
        rt.write(self.project / 'review/change.patch', 'synthetic patch')
        improvement.record_issue(self.project, {'id': 'I1', 'origin': 'tool', 'observation': 'fixture failure', 'evidence_paths': ['review/error.txt']})
        return improvement.propose(self.project, {'id': 'P1', 'issue_ids': ['I1'], 'hypothesis': 'fixture hypothesis', 'change': 'fixture change', 'patch_path': 'review/change.patch'}, self.candidate)

    def assessment(self, origin='actual'):
        self.proposal()
        base, _ = self.run_fixture('base', self.base, wrong=['abstract-access'], origin=origin)
        new, _ = self.run_fixture('new', origin=origin)
        rt.write(self.project / 'review/comparison.json', benchmark.compare(base, new))
        return improvement.assess(self.project, 'P1', 'review/comparison.json')

    def decision(self, proposal, source='user', choice='approve'):
        path = self.project / 'review/decision.json'
        rt.write(path, {'source': source, 'proposal_id': 'P1', 'candidate_sha256': proposal['candidate_sha256'],
                        'decision': choice, 'reviewer': 'synthetic test actor', 'quote': 'synthetic decision, not a real user'})
        return 'review/decision.json'

    def test_end_to_end_requires_human_record_and_exact_installed_content(self):
        before = (self.project / 'state.json').read_bytes()
        proposal = self.assessment()
        self.assertEqual(proposal['status'], 'evaluated')
        with self.assertRaises(ValueError):
            improvement.verify_deployment(self.project, 'P1', self.candidate)
        decision = self.decision(proposal)
        self.assertEqual(improvement.decide(self.project, 'P1', decision)['status'], 'approved')
        with self.assertRaises(ValueError):
            improvement.verify_deployment(self.project, 'P1', self.base)
        self.assertEqual(improvement.verify_deployment(self.project, 'P1', self.candidate)['status'], 'adopted')
        self.assertEqual((self.project / 'state.json').read_bytes(), before)
        history = rt.read(self.project / improvement.LEDGER)['history']
        self.assertEqual([e['seq'] for e in history], list(range(1, 6)))

    def test_fixture_assessment_cannot_be_approved(self):
        proposal = self.assessment(origin='fixture')
        self.assertEqual(proposal['status'], 'needs_revision')
        with self.assertRaises(ValueError):
            improvement.decide(self.project, 'P1', self.decision(proposal))

    def test_model_decision_cannot_approve(self):
        proposal = self.assessment()
        with self.assertRaises(ValueError):
            improvement.decide(self.project, 'P1', self.decision(proposal, source='model'))

    def test_missing_issue_evidence_and_changed_patch_are_rejected(self):
        with self.assertRaises(ValueError):
            improvement.record_issue(self.project, {'id': 'I1', 'origin': 'model', 'observation': 'no file', 'evidence_paths': ['missing.md']})
        proposal = self.assessment()
        rt.write(self.project / 'review/change.patch', 'modified since evaluation')
        with self.assertRaises(ValueError):
            improvement.decide(self.project, 'P1', self.decision(proposal))

    def test_changed_responses_are_detected_at_approval(self):
        proposal = self.assessment()
        path = self.project / 'review/evals/new/responses.json'
        response = rt.read(path)
        response['answers'][0]['reason'] = 'changed since comparison'
        rt.write(path, response)
        with self.assertRaises(ValueError):
            improvement.decide(self.project, 'P1', self.decision(proposal))

    def test_changed_human_record_is_detected_before_deployment(self):
        proposal = self.assessment()
        decision = self.decision(proposal)
        improvement.decide(self.project, 'P1', decision)
        rt.write(self.project / decision, {'decision': 'reject'})
        with self.assertRaises(ValueError):
            improvement.verify_deployment(self.project, 'P1', self.candidate)

    def test_unevaluated_proposal_can_be_rejected(self):
        proposal = self.proposal()
        decision = self.decision(proposal, choice='reject')
        self.assertEqual(improvement.decide(self.project, 'P1', decision)['status'], 'rejected')


if __name__ == '__main__':
    unittest.main()
