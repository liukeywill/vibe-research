"""Versioned artifact contracts and cross-file integrity for structured projects."""
import hashlib
import json
from pathlib import Path

import workspace

ARTIFACTS = {
 'scope': {'project-spec.json':'project-spec'},
 'search': {'research/search-query.json':'search-query','research/screening.json':'screening'},
 'read': {'research/sources.json':'source-record[]','research/evidence.json':'evidence-record[]'},
 'synthesize': {'research/synthesis.json':'synthesis'},
 'design': {'research/study-design.json':'study-design'},
 'analyze': {'research/analysis-result.json':'analysis-result'},
 'package': {'report.json':'research-report'},
 'review': {'review/quality-report.json':'quality-report'},
}

def read(root, relative):
    return json.loads(workspace.contained_path(root,relative).read_text(encoding='utf-8'))

def validate_file(root, relative, schema):
    import contracts
    data=read(root,relative)
    if schema.endswith('[]'):
        if not isinstance(data,list): raise workspace.WorkspaceError(f'{relative}: expected array')
        for record in data: contracts.validate(schema[:-2],record)
    else: contracts.validate(schema,data)
    return data

def references(ids, available, label):
    missing=set(ids)-set(available)
    if missing: raise workspace.WorkspaceError(f'{label}引用不存在: {sorted(missing)}')

def validate_stage(root,stage,disposition):
    for file,schema in ARTIFACTS[stage].items(): validate_file(root,file,schema)
    if stage=='search':
        candidates=validate_file(root,'research/search-results.json','source-record[]')
        decisions=read(root,'research/screening.json')['decisions']
        ids=[d['source_id'] for d in decisions]
        if len(ids)!=len(set(ids)) or set(ids)!={c['id'] for c in candidates}:
            raise workspace.WorkspaceError('筛选必须覆盖每个候选且不得重复。')
    if stage=='read':
        sources={s['id']:s for s in read(root,'research/sources.json')}
        evidence=read(root,'research/evidence.json')
        decisions={d['source_id']:d['decision'] for d in read(root,'research/screening.json')['decisions']}
        for item in evidence:
            references([item['source_id']],sources,'精读证据来源')
            if decisions.get(item['source_id'])!='include':
                raise workspace.WorkspaceError('证据来源须先完成筛选并纳入: '+item['source_id'])
    if stage in ('synthesize','design','package'):
        evidence={e['id']:e for e in read(root,'research/evidence.json')}
        sources={s['id']:s for s in read(root,'research/sources.json')}
        if stage=='synthesize':
            obj=read(root,'research/synthesis.json')
            for f in obj['findings']:
                references(f['evidence_ids'],evidence,'综合证据');references(f['source_ids'],sources,'综合来源')
            for item in obj['comparisons']+obj['contradictions']: references(item['source_ids'],sources,'横向比较')
        if stage=='design':
            for h in read(root,'research/study-design.json')['hypotheses']: references(h['evidence_ids'],evidence,'研究假设')
        if stage=='package':
            report=read(root,'report.json');claims={c['id']:c for c in report['claims']}
            if len(claims)!=len(report['claims']): raise workspace.WorkspaceError('报告claim ID重复')
            analysis=read(root,'research/analysis-result.json')
            for section in report['sections']: references(section['claim_ids'],claims,'报告章节')
            for c in claims.values():
                references(c['evidence_ids'],evidence,'报告证据')
                references(c['analysis_ids'],[analysis['id']],'分析结果')
                if c['status']=='supported':
                    if not c['evidence_ids'] and not c['analysis_ids']: raise workspace.WorkspaceError('supported论断缺少证据或分析')
                    if c['analysis_ids'] and analysis['status']!='executed': raise workspace.WorkspaceError('planned分析不能支撑结果论断')
                    for eid in c['evidence_ids']:
                        e=evidence[eid];s=sources[e['source_id']]
                        if e['claim_verification']!='verified' or s['access_level']!='fulltext' or s['metadata_status']!='verified' or e['support_status']=='unclear':
                            raise workspace.WorkspaceError('supported论断引用未核验全文证据')
            references([r['source_id'] for r in report['references']],sources,'参考文献')
    if stage=='analyze':
        obj=read(root,'research/analysis-result.json')
        if obj['status']!=disposition: raise workspace.WorkspaceError('JSON分析状态与阶段disposition不一致')
        if disposition=='executed':
            validate_file(root,'data/dataset-spec.json','dataset-spec')
            if not obj['input_files'] or not obj['code']: raise workspace.WorkspaceError('执行分析缺少原始数据/代码血缘')
            for f in obj['input_files']+[obj['code']]+obj.get('artifacts',[]):
                p=workspace.contained_path(root,f['path'])
                if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=f['sha256']:
                    raise workspace.WorkspaceError('分析输入、代码或产物哈希不一致: '+f['path'])
    if stage=='review':
        recorded=read(root,'review/quality-report.json')
        if recorded['overall_status']!='pass': raise workspace.WorkspaceError('必需质量指标未通过；核对质量报告并修复。')
        for receipt in recorded.get('evaluation_inputs',[]):
            target=workspace.contained_path(root,receipt['path'])
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=receipt['sha256']:
                raise workspace.WorkspaceError('质量评估输入已改变: '+receipt['path'])
        config=recorded.get('evaluation_config',{})
        import quality
        actual=quality.evaluate(root,policy_path=config.get('policy_path'),benchmark_path=config.get('benchmark_path'),acquire_lock=False,write_report=False)
        if (actual['overall_status']!='pass' or recorded['metrics']!=actual['metrics']
            or recorded.get('policy_sha256')!=actual.get('policy_sha256')
            or recorded.get('evaluation_config')!=actual.get('evaluation_config')
            or recorded.get('evaluation_inputs')!=actual.get('evaluation_inputs')):
            raise workspace.WorkspaceError('质量报告不是当前输入的计算结果，重新运行quality.py。')

def tracked_files(root,stage):
    """Explicit local dependencies; never recursively ingest the workspace."""
    found={}
    if stage=='scope':
        manifest=workspace.contained_path(root,'engine-manifest.json')
        if manifest.is_file():
            obj=read(root,'engine-manifest.json')
            for record in obj['files']:
                target=workspace.contained_path(root,record['path'])
                if hashlib.sha256(target.read_bytes()).hexdigest()!=record['sha256']:
                    raise workspace.WorkspaceError('运行快照哈希不一致: '+record['path'])
                found[record['path']]=record['sha256']
            found['engine-manifest.json']=hashlib.sha256(manifest.read_bytes()).hexdigest()
    if stage=='search':
        for prefix in ('research/search-responses','research/search-requests'):
            folder=workspace.contained_path(root,prefix)
            if folder.exists():
                for p in sorted(folder.glob('*.json')):
                    relative=p.relative_to(root).as_posix();target=workspace.contained_path(root,relative)
                    found[relative]=hashlib.sha256(target.read_bytes()).hexdigest()
        history=workspace.contained_path(root,'research/screening-history.jsonl')
        if history.is_file(): found[history.relative_to(root).as_posix()]=hashlib.sha256(history.read_bytes()).hexdigest()
    folder=workspace.contained_path(root,'model-io')
    if folder.exists():
        import model_backends
        for request_file in sorted(folder.glob('*.request.json')):
            relative=request_file.relative_to(root).as_posix()
            request=read(root,relative)
            if request.get('task')!=stage: continue
            model_backends.validate_request(request)
            response_relative=f"model-io/{request['id']}.response.json"
            response=read(root,response_relative)
            model_backends.validate_response(request,response)
            if response['status']!='completed': raise workspace.WorkspaceError('模型任务尚未实际完成: '+request['id'])
            for item in request.get('input_files',[]):
                target=workspace.contained_path(root,item['path'])
                if hashlib.sha256(target.read_bytes()).hexdigest()!=item['sha256']:
                    raise workspace.WorkspaceError('模型输入已改变: '+item['path'])
            artifact=request.get('parameters',{}).get('artifact_path')
            if artifact and response['output']!=read(root,artifact):
                raise workspace.WorkspaceError('模型回执与当前产物不一致: '+artifact)
            for name in (relative,response_relative):
                found[name]=hashlib.sha256(workspace.contained_path(root,name).read_bytes()).hexdigest()
    if stage=='analyze':
        obj=read(root,'research/analysis-result.json')
        if obj['status']=='executed':
            for f in obj['input_files']+[obj['code']]+obj.get('artifacts',[]): found[f['path']]=f['sha256']
            for name in ['data/dataset-spec.json','data/cleaning-log.json','data/cleaned.csv','data/environment.json','data/reproduced-result.json']:
                p=workspace.contained_path(root,name)
                if p.is_file(): found[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    if stage=='review':
        for receipt in read(root,'review/quality-report.json').get('evaluation_inputs',[]):
            target=workspace.contained_path(root,receipt['path'])
            actual=hashlib.sha256(target.read_bytes()).hexdigest()
            if actual!=receipt['sha256']: raise workspace.WorkspaceError('质量评估输入已改变: '+receipt['path'])
            found[receipt['path']]=actual
    return found

def render_report(root):
    report=validate_file(root,'report.json','research-report')
    lines=['# '+report['title'],'']
    for section in report['sections']:
        lines += ['## '+section['heading'],'',section['text'],'']
        for cid in section['claim_ids']:
            c=next(c for c in report['claims'] if c['id']==cid)
            refs=', '.join(c['evidence_ids']+c['analysis_ids']) or '无验证证据'
            lines += [f"- [{c['status']}] {c['text']}（证据：{refs}）"]
        lines+=['']
    lines+=['## 参考资料','']+[f"- [{r['title']}]({r['url']}) — {r['source_id']}" for r in report['references']]
    lines+=['','## 局限','']+['- '+x for x in report['limitations']]
    workspace.contained_path(root,'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
