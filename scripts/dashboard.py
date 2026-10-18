#!/usr/bin/env python3
"""Render an offline, searchable research dashboard without changing project state."""
import argparse
import html
import json
import os
from pathlib import Path
from urllib.parse import quote, urlsplit

import research_mode
import research_tools as rt
import workspace


LIMITATION = '看板展示已登记记录与文件检查；不证明原文已读、论断正确或人工已核查。缺失和未核验项保留。'


def snapshot(project):
    root = workspace.project_path(project)
    selection = research_mode.select_mode(root)
    if selection['action'] != 'resume':
        raise ValueError('需要已有项目状态；看板不会初始化项目')
    warnings = []

    def load(relative, default):
        target = workspace.contained_path(root, relative)
        if not target.exists():
            return default
        try:
            data = rt.read(target)
            if not isinstance(data, type(default)):
                raise ValueError('unexpected record type')
            return data
        except (OSError, ValueError) as error:
            warnings.append(relative + ': ' + str(error))
            return default

    mode = selection['mode']
    state = load(selection['state_file'], {})
    if mode == 'automatic':
        # load validates state/log consistency; refresh would mutate state and is not used.
        import pipeline
        state = pipeline.load(root)
    stages = []
    for name, record in state['stages'].items():
        if not isinstance(record, dict):
            warnings.append('Invalid stage: ' + name)
            continue
        artifacts = []
        if mode == 'manual':
            artifacts = [dict(a, **rt.file_record(root, a['path']))
                         for a in record.get('artifacts', [])]
        else:
            for group in ('inputs', 'outputs', 'tracked', 'source_texts'):
                for relative, expected in record.get(group, {}).items():
                    item = rt.file_record(root, relative)
                    item.update(group=group, expected_sha256=expected,
                                integrity='matches' if item['sha256'] == expected else 'changed_or_missing')
                    artifacts.append(item)
        for a in artifacts:
            if not a['exists'] or a.get('integrity') == 'changed_or_missing':
                warnings.append('成果缺失或改变，需复核：' + a['path'])
        stages.append({'stage': name, 'status': record.get('status', 'unknown'),
                       'artifacts': artifacts, 'human_checks': record.get('human_checks', []),
                       'open_items': record.get('open_items', []),
                       'reason': record.get('reason', '')})
    sources = load('research/sources.json', [])
    evidence = load('research/evidence.json', [])
    analysis = load('research/analysis-result.json', {})
    def unique_index(records, label):
        index, ambiguous = {}, set()
        for record in records:
            key = record['id']
            if key in index:
                ambiguous.add(key)
            index[key] = record
        for key in ambiguous:
            warnings.append(label + ' ID重复，不能确认关联：' + key)
            del index[key]
        return index

    source_map = unique_index(sources, '来源')
    evidence_map = unique_index(evidence, '证据')
    claims = []
    for relative, field in [('report.json', 'claims'), ('manuscript.json', 'claims'),
                            ('research/synthesis.json', 'findings')]:
        for claim in load(relative, {}).get(field, []):
            links = []
            for eid in claim.get('evidence_ids', []):
                e = evidence_map.get(eid)
                source = source_map.get(e.get('source_id')) if e else None
                links.append({'evidence_id': eid, 'evidence': e, 'source': source})
                if not e or not source:
                    warnings.append('证据关联缺失：' + eid)
            claims.append({'origin': relative, **claim, 'links': links,
                           'analyses': [analysis] if analysis.get('id') in claim.get('analysis_ids', []) else []})
    source_files = []
    for source in sources:
        if source.get('local_text'):
            item = rt.file_record(root, source['local_text'])
            expected = source.get('content_sha256')
            item['integrity'] = ('not_registered' if expected is None else
                                 'matches' if item['sha256'] == expected else 'changed_or_missing')
            source_files.append(item)
            if not item['exists'] or item['integrity'] == 'changed_or_missing':
                warnings.append('原文快照缺失或改变：' + item['path'])
    analysis_files = []
    for record in analysis.get('input_files', []) + ([analysis['code']] if analysis.get('code') else []):
        item = rt.file_record(root, record['path'])
        item['integrity'] = 'matches' if item['sha256'] == record.get('sha256') else 'changed_or_missing'
        analysis_files.append(item)
        if item['integrity'] != 'matches':
            warnings.append('分析输入或代码缺失/改变：' + item['path'])
    events = []
    event_path = workspace.contained_path(root, 'events.jsonl')
    if event_path.exists():
        for line in event_path.read_text(encoding='utf-8').splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                warnings.append('events.jsonl 存在损坏行')
    receipts = []
    # Show receipt metadata; full inputs/outputs remain in the linked local record.
    receipt_dir = workspace.contained_path(root, 'model-io')
    if receipt_dir.is_dir():
        for target in sorted(receipt_dir.rglob('*.json')):
            relative = target.relative_to(root).as_posix()
            data = load(relative, {})
            if 'request_id' in data and 'backend' in data:
                receipts.append({'path': relative, 'request_id': data['request_id'],
                                 'status': data.get('status'), 'model': data.get('model'),
                                 'usage': data.get('usage'), 'provenance': data.get('provenance')})
    extras = []
    for relative in ('project.md', 'decisions.md', 'research/analysis-result.json',
                     'review/quality-report.json', 'review/audit.md'):
        item = rt.file_record(root, relative)
        if item['exists']:
            extras.append(item)
    ledger = load('review/improvements.json', {})
    evaluations = []
    eval_dir = workspace.contained_path(root, 'review/evals')
    if eval_dir.is_dir():
        import benchmark
        for manifest_path in sorted(eval_dir.glob('*/manifest.json')):
            relative = manifest_path.relative_to(root).as_posix()
            workspace.contained_path(root, relative)
            try:
                manifest = load(relative, {})
                response_path = workspace.contained_path(root, (manifest_path.parent / 'responses.json').relative_to(root).as_posix())
                result = benchmark.score(manifest_path.parent) if response_path.is_file() else None
                evaluations.append({'label': manifest.get('label'), 'path': relative,
                                    'status': '已登记作答' if result else '待作答', 'result': result})
            except (OSError, ValueError, KeyError, TypeError) as error:
                warnings.append('评测记录需复核：' + relative + ': ' + str(error))
    return {'schema_version': 1, 'generated_at': rt.now(), 'project': str(root),
            'title': state.get('title') or load('project.json', {}).get('topic') or root.name,
            'mode': mode, 'current_stage': state.get('current_stage'), 'stages': stages,
            'sources': sources, 'evidence': evidence, 'claims': claims, 'events': events,
            'receipts': receipts, 'files': extras + source_files + analysis_files, 'analysis': analysis,
            'improvements': ledger, 'evaluations': evaluations,
            'warnings': sorted(set(warnings)), 'limitation': LIMITATION}


def render(data, output):
    esc = lambda value: html.escape(str(value), quote=True)
    root = Path(data['project'])

    def local_link(relative):
        target = workspace.contained_path(root, relative)
        if not target.is_file():
            return esc(relative) + '（缺失）'
        href = quote(os.path.relpath(target, output.parent), safe='/')
        return '<a href="' + esc(href) + '">' + esc(relative) + '</a>'

    def dump(value):
        return '<pre>' + esc(json.dumps(value, ensure_ascii=False, indent=2)) + '</pre>'

    def detail(title, value):
        return '<details class="item"><summary>' + esc(title) + '</summary>' + dump(value) + '</details>'

    labels = {'not_started': '未开始', 'pending': '待开始', 'in_progress': '进行中', 'running': '执行中',
              'awaiting_human_check': '等待人工核查', 'accepted': '人工已接受', 'succeeded': '自动阶段已完成',
              'advanced_unchecked': '已推进，仍未核查', 'needs_recheck': '需重新核查', 'stale': '已失效',
              'failed': '失败', 'blocked': '受阻', 'unchecked': '未核查', 'proposed': '候选修改',
              'evaluated': '已评测，待决定', 'needs_revision': '评测未通过', 'approved': '已批准，待部署',
              'rejected': '已拒绝', 'adopted': '已核对部署', 'recorded': '已登记',
              'unverified': '未核验', 'verified': '登记已核验', 'matches': '内容匹配',
              'changed_or_missing': '已改变或缺失', 'not_registered': '未登记哈希'}

    sections = []
    for stage in data['stages']:
        artifacts = ''.join('<li>' + local_link(a['path']) + ' · ' +
                            esc(labels.get(a.get('integrity', a.get('verification')), '未核验')) + '</li>'
                            for a in stage['artifacts'])
        sections.append('<article class="item"><h3>阶段 ' + esc(stage['stage']) + ' <span>' +
                        esc(labels.get(stage['status'], stage['status'])) + '</span></h3><ul>' + artifacts + '</ul>' +
                        detail('人工核查与未决项', {k: stage[k] for k in ('human_checks', 'open_items', 'reason')}) + '</article>')
    claims = ''
    for c in data['claims']:
        chain = ''
        for link in c['links']:
            e, s = link['evidence'] or {}, link['source'] or {}
            chain += '<li>' + esc(link['evidence_id']) + ' → ' + esc(s.get('title', '来源缺失')) + ' → ' + esc(e.get('locator', '定位缺失')) + ' · ' + esc(labels.get(e.get('claim_verification'), '未核验')) + '</li>'
        claims += '<article class="item"><h3>' + esc(c.get('text', c.get('claim', ''))) + '</h3><ul>' + chain + '</ul>' + detail('证据、分析与限定条件', c) + '</article>'
    claims = claims or '<p>未登记结构化主张；可从阶段成果查看原记录。</p>'
    def source_for(e):
        matches = [s for s in data['sources'] if s['id'] == e.get('source_id')]
        return matches[0] if len(matches) == 1 else None

    evidence = ''.join(detail(e.get('id', '') + ' · ' + e.get('claim', ''),
                             {'evidence': e, 'source': source_for(e)})
                       for e in data['evidence']) or '<p>暂无结构化证据记录。</p>'
    sources = ''
    for s in data['sources']:
        url = s.get('url', '')
        link = ('<a href="' + esc(url) + '" rel="noreferrer">打开来源</a>'
                if isinstance(url, str) and urlsplit(url).scheme in ('https', 'http') else '')
        sources += '<article class="item">' + detail(s['id'] + ' · ' + s.get('title', ''), s) + link + '</article>'
    events = ''.join(detail(str(e.get('at', '')) + ' · ' + str(e.get('event', '记录')), e)
                     for e in data['events']) or '<p>暂无执行事件；不能据此推定已执行。</p>'
    receipts = ''.join('<article class="item">' + local_link(r['path']) + dump(r) + '</article>'
                       for r in data['receipts'])
    warnings = ''.join('<li>' + esc(w) + '</li>' for w in data['warnings']) or '<li>无文件完整性告警；学术核验状态以原记录为准。</li>'
    improvements = ''
    for issue in data['improvements'].get('issues', []):
        improvements += detail('问题 ' + issue['id'] + ' · ' + issue['observation'], issue)
    for proposal in data['improvements'].get('proposals', []):
        improvements += detail('修改 ' + proposal['id'] + ' · ' + labels.get(proposal['status'], proposal['status']), proposal)
    evaluations = ''
    for evaluation in data['evaluations']:
        result = evaluation['result']
        summary = evaluation['status']
        if result:
            summary += ' · ' + ('合成测试夹具' if result['origin'] == 'fixture' else '实际作答登记') + ' · ' + str(result['passed']) + '/' + str(result['total'])
        evaluations += detail(str(evaluation['label']) + ' · ' + summary, evaluation)
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Vibe Research · 研究看板</title><style>
:root{font-family:system-ui,sans-serif;color:#172c37;background:#f3f5f4}*{box-sizing:border-box}
body{margin:0}main{max-width:1080px;margin:auto;padding:36px 24px}header{background:#153d3b;color:#fff;padding:28px;border-radius:18px}
h1{font-size:30px;margin:8px 0}h2{font-size:21px;margin:0 0 18px}h3{font-size:16px}p{line-height:1.7}
.eyebrow{font-size:12px;letter-spacing:.12em;color:#b8d7cf}.meta{color:#d5e7e0;font-size:14px}
nav{display:flex;flex-wrap:wrap;gap:16px;padding:22px 0}a{color:#12625b;text-underline-offset:3px}header a{color:#fff}
section{background:white;padding:24px;border-radius:14px;margin:18px 0;border:1px solid #dde4e0}
.notice{background:#fff7e5}input{width:100%;padding:14px;border:1px solid #bccdc5;border-radius:9px;font:inherit}
.item{border-bottom:1px solid #e6ece8;padding:12px 0}summary{cursor:pointer;line-height:1.7}span{font-size:12px;font-weight:500;color:#50776d}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7f5;padding:16px;border-radius:8px;font-size:12px;line-height:1.6}
li{line-height:1.8}small{color:#516761} [hidden]{display:none!important}
@media(max-width:600px){main{padding:16px}header,section{padding:18px}h1{font-size:24px}}
</style><main><header><div class="eyebrow">VIBE RESEARCH / LOCAL WORKSPACE</div><h1>''' + esc(data['title']) + '''</h1><p class="meta">''' + esc('人工核查模式' if data['mode'] == 'manual' else '自动成稿模式') + ' · <time datetime="' + esc(data['generated_at']) + '">' + esc(data['generated_at']) + '''</time></p></header>
<nav><a href="#stages">研究进度</a><a href="#claims">主张与证据</a><a href="#sources">来源</a><a href="#trajectory">执行记录</a><a href="#evaluations">固定评测</a><a href="#improvements">纠错改进</a></nav>
<label for="search">筛选记录</label><input id="search" type="search" placeholder="搜索主张、来源、状态或文件…">
<section class="notice"><h2>待复核与边界</h2><p>''' + esc(data['limitation']) + '</p><ul>' + warnings + '''</ul></section>
<section id="stages"><h2>研究进度</h2>''' + ''.join(sections) + '''</section>
<section id="claims"><h2>主张 → 证据 → 原文位置</h2>''' + claims + evidence + '''</section>
<section id="sources"><h2>来源与阅读范围</h2>''' + (sources or '<p>暂无结构化来源。</p>') + '''</section>
<section id="trajectory"><h2>执行、回执与成果</h2>''' + events + receipts + '<ul>' + ''.join('<li>' + local_link(f['path']) + '</li>' for f in data['files']) + '''</ul></section>
<section id="evaluations"><h2>固定任务评测</h2><p>公开合成任务用于流程回归；得分不代表独立科研准确率。</p>''' + (evaluations or '<p>暂无评测运行。</p>') + '''</section>
<section id="improvements"><h2>纠错改进闭环</h2>''' + (improvements or '<p>暂无纠错记录。</p>') + '''</section>
<small>离线快照。更新记录后重新生成；看板不会推进阶段或登记人工通过。</small></main>
<script>const t=document.querySelector('time');t.textContent=new Date(t.dateTime).toLocaleString('zh-CN',{hour12:false});document.getElementById('search').addEventListener('input',function(){const q=this.value.toLowerCase();document.querySelectorAll('section > .item').forEach(e=>{e.hidden=!e.textContent.toLowerCase().includes(q)})});</script></html>'''


def build(project, relative='review/dashboard.html'):
    root = workspace.project_path(project)
    if not relative.endswith('.html'):
        raise ValueError('看板输出必须为 .html')
    output = workspace.contained_path(root, relative)
    # Fixed output namespace avoids replacing scientific inputs or project state.
    if relative != 'review/dashboard.html' and not relative.startswith('review/dashboards/'):
        raise ValueError('看板输出必须为 review/dashboard.html 或位于 review/dashboards/ 内')
    data = snapshot(root)
    rt.write(output, render(data, output))
    rt.write(output.with_suffix('.json'), data)
    return {'html': str(output), 'json': str(output.with_suffix('.json')), 'warnings': data['warnings']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--output', default='review/dashboard.html')
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.project, args.output), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
