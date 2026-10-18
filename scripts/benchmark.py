#!/usr/bin/env python3
"""Fixed-task Codex handoff and deterministic regression scoring; no model API calls."""
import argparse
import json
from pathlib import Path

import research_tools as rt
import workspace

SUITE = Path(__file__).resolve().parent.parent / 'assets/research-regression.json'
LIMITATION = ('公开合成任务的机械回归评测，不是独立科研能力评估。reason 未作语义评分；'
              'origin、模型身份和用量为执行者登记，非供应商认证。不证明学术正确或可发表。')


def suite_load(path):
    suite = rt.read(path)
    if suite.get('schema_version') != 1 or suite.get('kind') != 'synthetic_regression':
        raise ValueError('Unsupported suite')
    rt.text(suite['id'], 'suite id')
    ids = []
    for c in suite['cases']:
        rt.text(c['id'], 'case id')
        rt.text(c['prompt'], 'prompt')
        if not isinstance(c['materials'], list) or not isinstance(c['expected']['evidence_ids'], list):
            raise ValueError('Invalid case materials/expected evidence')
        rt.text(c['expected']['decision'], 'expected decision')
        ids.append(c['id'])
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Suite requires unique, nonempty cases')
    return suite


def request_for(suite, budget):
    return {'suite_id': suite['id'], 'budget': budget,
            'instruction': '仅据所给合成材料作答。逐项给出 decision、evidence_ids、reason。不要查阅评分参考。',
            'decisions': ['supported', 'needs_fulltext', 'association_only', 'not_executed',
                          'needs_recheck', 'unchecked', 'incomplete', 'contradicted'],
            'cases': [{k: c[k] for k in ('id', 'prompt', 'materials')} for c in suite['cases']]}


def prepare(run, candidate, label, suite_path=SUITE, model='current-codex-session',
            max_model_calls=1, max_tool_calls=0):
    run = workspace.project_path(run)
    if run.exists() and any(run.iterdir()):
        raise ValueError('Run directory must be new or empty')
    if type(max_model_calls) is not int or max_model_calls < 1 or type(max_tool_calls) is not int or max_tool_calls < 0:
        raise ValueError('Invalid budget')
    rt.text(label, 'label')
    rt.text(model, 'model')
    suite = suite_load(suite_path)
    budget = {'max_model_calls_per_case': max_model_calls, 'max_tool_calls_per_case': max_tool_calls}
    request = request_for(suite, budget)
    candidate = workspace.project_path(candidate)
    inventory = rt.fingerprint(candidate)
    manifest = {'schema_version': 1, 'label': label, 'created_at': rt.now(),
                'suite_sha256': rt.content_sha(suite), 'request_sha256': rt.content_sha(request),
                'candidate_sha256': inventory['sha256'], 'candidate_path': str(candidate),
                'model': model, 'budget': budget, 'limitation': LIMITATION}
    run.mkdir(parents=True, exist_ok=True)
    rt.write(run / 'suite.json', suite)
    rt.write(run / 'candidate-inventory.json', inventory)
    rt.write(run / 'request.json', request)
    rt.write(run / 'manifest.json', manifest)
    return manifest


def load_run(run):
    root = workspace.project_path(run)
    manifest = rt.read(workspace.contained_path(root, 'manifest.json'))
    suite = suite_load(workspace.contained_path(root, 'suite.json'))
    request = rt.read(workspace.contained_path(root, 'request.json'))
    inventory = rt.read(workspace.contained_path(root, 'candidate-inventory.json'))
    if (rt.content_sha(suite) != manifest['suite_sha256'] or
            rt.content_sha(request) != manifest['request_sha256'] or
            request != request_for(suite, manifest['budget']) or
            rt.content_sha(inventory['files']) != inventory['sha256'] or
            inventory['sha256'] != manifest['candidate_sha256']):
        raise ValueError('Run inputs or candidate inventory changed')
    return root, manifest, suite


def evaluate(run, responses):
    root, manifest, suite = load_run(run)
    if responses.get('request_sha256') != manifest['request_sha256']:
        raise ValueError('Responses do not match this request')
    if responses.get('origin') not in ('actual', 'fixture'):
        raise ValueError('Declare origin actual or fixture')
    if responses.get('model') != manifest['model']:
        raise ValueError('Model identity differs from prepared run')
    answers = responses.get('answers')
    if not isinstance(answers, list) or any(not isinstance(a, dict) for a in answers):
        raise ValueError('answers must be a list of objects')
    ids = [a.get('case_id') for a in answers]
    expected_ids = [c['id'] for c in suite['cases']]
    if len(ids) != len(set(ids)) or set(ids) - set(expected_ids):
        raise ValueError('Duplicate or unknown case IDs')
    by_id = {a['case_id']: a for a in answers}
    results = []
    for case in suite['cases']:
        answer = by_id.get(case['id'])
        reasons = []
        if answer is None:
            reasons.append('missing_response')
        else:
            rt.text(answer.get('reason'), 'reason')
            evidence = answer.get('evidence_ids')
            if not isinstance(evidence, list) or any(not isinstance(e, str) for e in evidence) or len(evidence) != len(set(evidence)):
                raise ValueError('Invalid evidence IDs')
            if answer.get('decision') != case['expected']['decision']:
                reasons.append('decision_mismatch')
            if set(evidence) != set(case['expected']['evidence_ids']):
                reasons.append('evidence_mismatch')
            for key, limit in [('model_calls', 'max_model_calls_per_case'), ('tool_calls', 'max_tool_calls_per_case')]:
                count = answer.get(key)
                if count is not None and (type(count) is not int or count < 0):
                    raise ValueError('Invalid call count')
                if count is not None and count > manifest['budget'][limit]:
                    reasons.append('budget_exceeded')
        results.append({'case_id': case['id'], 'passed': not reasons, 'reasons': reasons})
    passed = sum(c['passed'] for c in results)
    return {'schema_version': 1, 'run': str(root), 'manifest_sha256': rt.content_sha(manifest),
            'response_sha256': rt.content_sha(responses), 'suite_sha256': manifest['suite_sha256'],
            'candidate_sha256': manifest['candidate_sha256'], 'origin': responses['origin'],
            'coverage': len(answers), 'total': len(results), 'passed': passed,
            'score': passed / len(results), 'cases': results,
            'usage_measured': all(a.get('model_calls') is not None and a.get('tool_calls') is not None for a in answers),
            'limitation': LIMITATION}


def submit(run, response_path):
    root, manifest, _ = load_run(run)
    if rt.fingerprint(manifest['candidate_path'])['sha256'] != manifest['candidate_sha256']:
        raise ValueError('Candidate changed after prepare; start a fresh run')
    responses = rt.read(response_path)
    result = evaluate(root, responses)
    receipt = workspace.contained_path(root, 'responses.json')
    if receipt.exists() and rt.read(receipt) != responses:
        raise ValueError('Completed responses are immutable; prepare a new run')
    rt.write(receipt, responses)
    rt.write(workspace.contained_path(root, 'score.json'), result)
    return result


def score(run):
    root, _, _ = load_run(run)
    return evaluate(root, rt.read(workspace.contained_path(root, 'responses.json')))


def compare(baseline, candidate):
    _, bm, _ = load_run(baseline)
    _, cm, _ = load_run(candidate)
    for key in ('suite_sha256', 'request_sha256', 'model', 'budget'):
        if bm[key] != cm[key]:
            raise ValueError('Comparison requires identical ' + key)
    old, new = score(baseline), score(candidate)
    if old['origin'] != new['origin']:
        raise ValueError('Cannot mix fixture and actual runs')
    regressions = [a['case_id'] for a, b in zip(old['cases'], new['cases']) if a['passed'] and not b['passed']]
    eligible = (old['coverage'] == old['total'] and new['coverage'] == new['total']
                and old['origin'] == 'actual' and new['passed'] > old['passed'] and not regressions
                and bm['candidate_sha256'] != cm['candidate_sha256'])
    return {'schema_version': 1, 'baseline_run': str(Path(baseline).resolve()),
            'candidate_run': str(Path(candidate).resolve()), 'baseline': old, 'candidate': new,
            'regressions': regressions, 'eligible_for_human_review': eligible,
            'decision': 'review_candidate' if eligible else 'retain_parent',
            'reason': '必须同任务、同预算、完整覆盖、实际作答、严格改善且无退步；相同分数保留旧版。',
            'limitation': LIMITATION}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--run', required=True)
    p.add_argument('--candidate', required=True)
    p.add_argument('--label', required=True)
    p.add_argument('--suite', default=str(SUITE))
    p.add_argument('--model', default='current-codex-session')
    p.add_argument('--max-model-calls', type=int, default=1)
    p.add_argument('--max-tool-calls', type=int, default=0)
    p = sub.add_parser('submit')
    p.add_argument('--run', required=True)
    p.add_argument('--responses', required=True)
    p = sub.add_parser('score')
    p.add_argument('--run', required=True)
    p = sub.add_parser('compare')
    p.add_argument('--baseline', required=True)
    p.add_argument('--candidate', required=True)
    p.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            result = prepare(args.run, args.candidate, args.label, args.suite, args.model,
                             args.max_model_calls, args.max_tool_calls)
        elif args.command == 'submit':
            result = submit(args.run, args.responses)
        elif args.command == 'score':
            result = score(args.run)
        else:
            result = compare(args.baseline, args.candidate)
            output = Path(args.output)
            if output.exists():
                raise ValueError('Use a new comparison output path')
            rt.write(output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
