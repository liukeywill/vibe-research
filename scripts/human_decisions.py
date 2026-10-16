#!/usr/bin/env python3
"""Structured human handoffs. Answers must come from actual user messages."""
import argparse
import json
import sys
from datetime import datetime, timezone
import contracts
import pipeline
import workspace


def record(root, stage, question, options):
    if stage not in pipeline.NAMES: raise ValueError('unknown stage')
    with pipeline.locked(root):
        state=pipeline.load(root);pipeline.refresh(root,state)
        task=pipeline.view(state)['next']
        if not task or task['stage']!=stage: raise ValueError('human request must belong to the active stage')
        ident='decision-'+str(state['event_count']+1)
        out={'schema_version':1,'id':ident,'stage':stage,'status':'requested','question':question,'options':options,'requested_at':pipeline.now(),'answer':None,'answered_at':None,'actor':None}
        contracts.validate('human-decision',out)
        dest=pipeline.path(root,'decisions/'+ident+'.json');dest.parent.mkdir(exist_ok=True);dest.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
        state['stages'][stage].update(status='blocked',reason='human_input_required',human_decision_ids=[ident])
        pipeline.save(root,state,'human_requested',stage,{'id':ident})
        return out


def answer(root,ident,text,actor):
    if not text.strip() or not actor.strip():raise ValueError('actual answer and actor must be recorded')
    with pipeline.locked(root):
        p=pipeline.path(root,'decisions/'+ident+'.json');out=contracts.load_validate('human-decision',p)
        if out['status']!='requested': raise ValueError('decision already resolved')
        out.update(status='answered',answer=text,actor=actor,answered_at=pipeline.now());contracts.validate('human-decision',out)
        state=pipeline.load(root)
        p.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
        rec=state['stages'][out['stage']]
        pending=pipeline.human_pending(root,out['stage']);rec['human_decision_ids']=pending
        if not pending:rec.update(status='pending',failures=0,reason='human_answer_received')
        pipeline.save(root,state,'human_answered',out['stage'],{'id':ident,'actor':actor})
        return out


def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('request');a.add_argument('--project',required=True);a.add_argument('--stage',required=True);a.add_argument('--question',required=True);a.add_argument('--options',nargs='*',default=[])
    a=sub.add_parser('answer');a.add_argument('--project',required=True);a.add_argument('--id',required=True);a.add_argument('--text',required=True);a.add_argument('--actor',required=True)
    a=p.parse_args()
    try:
        root=workspace.project_path(a.project);out=record(root,a.stage,a.question,a.options) if a.command=='request' else answer(root,a.id,a.text,a.actor)
        print(json.dumps(out,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,KeyError) as e:print(json.dumps({'status':'error','message':str(e)},ensure_ascii=False));return 2
if __name__=='__main__':sys.exit(main())
