#!/usr/bin/env python3
"""Evidence-backed issue → proposal → evaluation → human decision → deployment receipt."""
import argparse
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import re

import benchmark
import research_mode
import research_tools as rt
import workspace

LEDGER = 'review/improvements.json'


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}', value):
        raise ValueError('Invalid record id')
    return value


@contextmanager
def ledger(project):
    root = workspace.project_path(project)
    if research_mode.select_mode(root)['action'] != 'resume':
        raise ValueError('An existing research project is required')
    lock_path = workspace.contained_path(root, 'review/.improvements.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        target = workspace.contained_path(root, LEDGER)
        data = rt.read(target) if target.exists() else {'schema_version': 1, 'issues': [], 'proposals': [], 'history': []}
        if data.get('schema_version') != 1 or any(not isinstance(data.get(k), list) for k in ('issues', 'proposals', 'history')):
            raise ValueError('Invalid improvement ledger; preserve it for inspection')
        try:
            yield root, data
            rt.write(target, data)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def event(data, action, record_id, detail):
    data['history'].append({'seq': len(data['history']) + 1, 'at': rt.now(),
                            'action': action, 'record_id': record_id, 'detail': detail})


def find(data, group, record_id):
    values = [v for v in data[group] if v['id'] == record_id]
    if len(values) != 1:
        raise ValueError('Missing or ambiguous ' + record_id)
    return values[0]


def capture(root, relative):
    item = rt.file_record(root, relative)
    if not item['exists']:
        raise ValueError('Evidence file is missing: ' + relative)
    return {'path': item['path'], 'sha256': item['sha256']}


def check_captures(root, records):
    for record in records:
        if capture(root, record['path']) != record:
            raise ValueError('Recorded evidence changed: ' + record['path'])


def record_issue(project, issue):
    with ledger(project) as (root, data):
        issue_id = identifier(issue['id'])
        if any(i['id'] == issue_id for i in data['issues']):
            raise ValueError('Issue id already exists')
        if issue['origin'] not in ('user', 'model', 'tool'):
            raise ValueError('origin must be user, model or tool')
        rt.text(issue['observation'], 'observation')
        if not isinstance(issue['evidence_paths'], list) or not issue['evidence_paths']:
            raise ValueError('At least one actual evidence file is required')
        result = {'id': issue_id, 'origin': issue['origin'], 'observation': issue['observation'],
                  'evidence': [capture(root, p) for p in issue['evidence_paths']],
                  'created_at': rt.now(), 'status': 'recorded'}
        data['issues'].append(result)
        event(data, 'issue_recorded', issue_id, result)
        return result


def propose(project, proposal, candidate):
    with ledger(project) as (root, data):
        proposal_id = identifier(proposal['id'])
        if any(p['id'] == proposal_id for p in data['proposals']):
            raise ValueError('Proposal id already exists')
        issue_ids = proposal['issue_ids']
        if not isinstance(issue_ids, list) or not issue_ids or len(issue_ids) != len(set(issue_ids)):
            raise ValueError('Unique issue IDs are required')
        for iid in issue_ids:
            check_captures(root, find(data, 'issues', iid)['evidence'])
        for key in ('hypothesis', 'change'):
            rt.text(proposal[key], key)
        result = {'id': proposal_id, 'issue_ids': issue_ids,
                  'hypothesis': proposal['hypothesis'], 'change': proposal['change'],
                  'patch': capture(root, proposal['patch_path']),
                  'candidate_sha256': rt.fingerprint(candidate)['sha256'],
                  'created_at': rt.now(), 'status': 'proposed'}
        data['proposals'].append(result)
        event(data, 'proposal_recorded', proposal_id, result)
        return result


def verify_assessment(root, proposal):
    record = proposal.get('comparison')
    if not record:
        raise ValueError('No evaluation is attached')
    check_captures(root, [record, proposal['patch']])
    comparison = rt.read(workspace.contained_path(root, record['path']))
    recomputed = benchmark.compare(comparison['baseline_run'], comparison['candidate_run'])
    if recomputed != comparison:
        raise ValueError('Comparison inputs changed; use a fresh assessment')
    if comparison['candidate']['candidate_sha256'] != proposal['candidate_sha256']:
        raise ValueError('Comparison evaluates a different candidate')
    return comparison


def assess(project, proposal_id, comparison_path):
    with ledger(project) as (root, data):
        proposal = find(data, 'proposals', proposal_id)
        if proposal['status'] not in ('proposed', 'needs_revision', 'evaluated'):
            raise ValueError('Proposal decision already recorded; create a new proposal')
        proposal['comparison'] = capture(root, comparison_path)
        comparison = verify_assessment(root, proposal)
        for iid in proposal['issue_ids']:
            check_captures(root, find(data, 'issues', iid)['evidence'])
        proposal['status'] = 'evaluated' if comparison['eligible_for_human_review'] else 'needs_revision'
        event(data, 'evaluation_attached', proposal_id, {'status': proposal['status'], 'comparison': proposal['comparison']})
        return proposal


def decide(project, proposal_id, decision_path):
    with ledger(project) as (root, data):
        proposal = find(data, 'proposals', proposal_id)
        if proposal['status'] not in ('proposed', 'needs_revision', 'evaluated'):
            raise ValueError('Decision already recorded')
        decision = rt.read(workspace.contained_path(root, decision_path))
        if (decision.get('source') != 'user' or decision.get('proposal_id') != proposal_id or
                decision.get('candidate_sha256') != proposal['candidate_sha256'] or
                decision.get('decision') not in ('approve', 'reject')):
            raise ValueError('An explicit user decision for this candidate is required')
        rt.text(decision.get('quote'), 'actual user quote')
        rt.text(decision.get('reviewer'), 'reviewer')
        if decision['decision'] == 'approve':
            for iid in proposal['issue_ids']:
                check_captures(root, find(data, 'issues', iid)['evidence'])
            if proposal['status'] != 'evaluated' or not verify_assessment(root, proposal)['eligible_for_human_review']:
                raise ValueError('Approval requires an eligible actual evaluation')
        proposal['human_decision'] = capture(root, decision_path)
        proposal['status'] = 'approved' if decision['decision'] == 'approve' else 'rejected'
        event(data, 'human_decision', proposal_id, {'status': proposal['status'], 'record': proposal['human_decision']})
        return proposal


def verify_deployment(project, proposal_id, installed):
    with ledger(project) as (root, data):
        proposal = find(data, 'proposals', proposal_id)
        if proposal['status'] != 'approved':
            raise ValueError('Deployment receipt requires prior human approval')
        if not verify_assessment(root, proposal)['eligible_for_human_review']:
            raise ValueError('Evaluation is no longer eligible')
        for iid in proposal['issue_ids']:
            check_captures(root, find(data, 'issues', iid)['evidence'])
        check_captures(root, [proposal['human_decision']])
        if rt.fingerprint(installed)['sha256'] != proposal['candidate_sha256']:
            raise ValueError('Installed content differs from approved candidate')
        proposal['status'] = 'adopted'
        proposal['deployment'] = {'path': str(Path(installed).resolve()), 'at': rt.now(),
                                  'candidate_sha256': proposal['candidate_sha256']}
        event(data, 'deployment_verified', proposal_id, proposal['deployment'])
        return proposal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('record')
    p.add_argument('--input', required=True)
    p = sub.add_parser('propose')
    p.add_argument('--input', required=True)
    p.add_argument('--candidate', required=True)
    p = sub.add_parser('assess')
    p.add_argument('--id', required=True)
    p.add_argument('--comparison', required=True)
    p = sub.add_parser('decide')
    p.add_argument('--id', required=True)
    p.add_argument('--decision-file', required=True)
    p = sub.add_parser('verify')
    p.add_argument('--id', required=True)
    p.add_argument('--installed', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'record':
            result = record_issue(args.project, rt.read(args.input))
        elif args.command == 'propose':
            result = propose(args.project, rt.read(args.input), args.candidate)
        elif args.command == 'assess':
            result = assess(args.project, args.id, args.comparison)
        elif args.command == 'decide':
            result = decide(args.project, args.id, args.decision_file)
        else:
            result = verify_deployment(args.project, args.id, args.installed)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
