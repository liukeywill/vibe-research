#!/usr/bin/env python3
"""Auditable deterministic triage; uncertain/near-duplicate records are not deleted."""
import argparse
from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
import re
import sys

import collect_sources
import contracts
import pipeline
import workspace


def norm(value): return re.sub(r'[^\w]+',' ',str(value).casefold()).strip()
def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')


def screen(records,criteria,threshold=0.92):
    contracts.validate('screening',{'schema_version':1,'id':'screening','criteria':criteria,'decisions':[],'dedup':{'exact_duplicates':[],'possible_duplicates':[]}})
    if not 0 <= threshold <= 1: raise ValueError('similarity threshold must be 0..1')
    seen=[]; exact=[]; possible=[]; decisions=[]
    ids=[x['id'] for x in records]
    if len(ids)!=len(set(ids)): raise ValueError('candidate IDs must be unique')
    for rec in records:
        contracts.validate('source-record',rec)
        text=norm(rec['title']+' '+rec.get('abstract',''))
        duplicate=next((old for old in seen if collect_sources.identities(old)&collect_sources.identities(rec)),None)
        if duplicate:
            exact.append({'kept_id':duplicate['id'],'removed_id':rec['id'],'reason':'shared DOI/ERIC/stable identity; record retained with exclusion'})
            decision,reason,rule_ids='exclude','重复题录（保留原记录以便审计）',['duplicate_identity']
        else:
            seen.append(rec)
            for old in seen[:-1]:
                title_a,title_b=norm(old['title']),norm(rec['title'])
                sim=SequenceMatcher(None,title_a,title_b).ratio()
                if sim>=threshold and title_a and (old.get('year') is None or rec.get('year') is None or old['year']==rec['year']):
                    possible.append({'source_ids':[old['id'],rec['id']],'similarity':sim,'reason':'near title with compatible year; human review required, not merged'})
            year=rec.get('year'); decision,reason,rule_ids='include','满足当前自动初筛规则，尚未完成全文评价',['rule_match']
            if any(norm(term) in text for term in criteria['exclude_terms']): decision,reason,rule_ids='exclude','命中排除关键词',['exclude_term']
            elif criteria['include_terms'] and not any(norm(term) in text for term in criteria['include_terms']): decision,reason,rule_ids='exclude','未命中纳入关键词；可能存在漏检，需按课题复核',['include_term_absent']
            elif year is None and (criteria['year_min'] is not None or criteria['year_max'] is not None): decision,reason,rule_ids='uncertain','缺少年份，无法判定时间范围',['year_missing']
            elif year is not None and ((criteria['year_min'] is not None and year<criteria['year_min']) or (criteria['year_max'] is not None and year>criteria['year_max'])): decision,reason,rule_ids='exclude','发表年份超出纳排范围',['year_range']
            elif criteria['require_abstract'] and not rec.get('abstract','').strip(): decision,reason,rule_ids='uncertain','摘要缺失，需要人工或正文核对',['abstract_missing']
        decisions.append({'source_id':rec['id'],'decision':decision,'reason':reason,'rule_ids':rule_ids,'reviewer':'deterministic-rule-screen-v1','reviewed_at':now()})
    out={'schema_version':1,'id':'screening','criteria':criteria,'decisions':decisions,'dedup':{'exact_duplicates':exact,'possible_duplicates':possible}}
    contracts.validate('screening',out)
    return out


def run(root,criteria_file,threshold=0.92,force=False):
    with pipeline.locked(root):
        target=pipeline.path(root,'research/screening.json')
        if target.exists() and not force: raise workspace.WorkspaceError('已有筛选记录；复核后用 --force 或新项目，防止覆盖人工判断。')
        criteria=json.loads(pipeline.path(root,criteria_file).read_text())
        # Validate complete criteria even when no candidates exist.
        contracts.validate('screening',{'schema_version':1,'id':'screening','criteria':criteria,'decisions':[],'dedup':{'exact_duplicates':[],'possible_duplicates':[]}})
        records=json.loads(pipeline.path(root,'research/search-results.json').read_text())
        out=screen(records,criteria,threshold);collect_sources.save(root,'research/screening.json',out)
        return out


def adjudicate(root,source_id,decision,reason,reviewer):
    if not reason.strip() or not reviewer.strip(): raise ValueError('reason/reviewer required')
    with pipeline.locked(root):
        out=contracts.load_validate('screening',pipeline.path(root,'research/screening.json'))
        record=next((x for x in out['decisions'] if x['source_id']==source_id),None)
        if record is None: raise ValueError('source ID not screened')
        audit=pipeline.path(root,'research/screening-history.jsonl')
        with audit.open('a') as f: f.write(json.dumps({'at':now(),'before':dict(record),'new_decision':decision,'reason':reason,'reviewer':reviewer},ensure_ascii=False)+'\n')
        record.update(decision=decision,reason=reason,reviewer=reviewer,reviewed_at=now(),rule_ids=['reviewed_override'])
        contracts.validate('screening',out);collect_sources.save(root,'research/screening.json',out)
        return out


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('run');a.add_argument('--project',required=True);a.add_argument('--criteria',required=True);a.add_argument('--threshold',type=float,default=.92);a.add_argument('--force',action='store_true')
    a=sub.add_parser('adjudicate');a.add_argument('--project',required=True);a.add_argument('--source-id',required=True);a.add_argument('--decision',choices=['include','exclude','uncertain'],required=True);a.add_argument('--reason',required=True);a.add_argument('--reviewer',required=True)
    a=p.parse_args()
    try:
        root=workspace.project_path(a.project)
        result=run(root,a.criteria,a.threshold,a.force) if a.command=='run' else adjudicate(root,a.source_id,a.decision,a.reason,a.reviewer)
        print(json.dumps({'status':'ok','decisions':len(result['decisions']),'counts':{key:sum(d['decision']==key for d in result['decisions']) for key in ['include','exclude','uncertain']}},ensure_ascii=False));return 0
    except (OSError,ValueError,KeyError,TypeError) as e: print(json.dumps({'status':'error','error':str(e)},ensure_ascii=False));return 2
if __name__=='__main__':sys.exit(main())
