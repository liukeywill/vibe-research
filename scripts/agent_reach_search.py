#!/usr/bin/env python3
"""Read-only Exa discovery via Agent Reach's mcporter backend; never verifies evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlsplit


def candidates(payload, limit=5):
    if payload.get('isError'):
        raise ValueError('Exa returned an error, not search results')
    text = '\n'.join(x.get('text', '') for x in payload.get('content', []) if x.get('type') == 'text')
    found, seen = [], set()
    for match in re.finditer(r'^Title:\s*([^\n]+)\nURL:\s*(https?://\S+)', text, re.M):
        title, url = match.groups()
        parsed = urlsplit(url)
        if not parsed.hostname or parsed.username or parsed.password or url in seen:
            continue
        seen.add(url)
        found.append({'id': 'AR_' + hashlib.sha256(url.encode()).hexdigest()[:16],
                      'title': title.strip(), 'url': url, 'provider': 'agent-reach-exa',
                      'access_level': 'metadata', 'metadata_status': 'unverified',
                      'source_type': 'discovery_candidate',
                      'verification_scope': 'Search lead only; original source, metadata and claims require verification'})
        if len(found) >= limit:
            break
    if not found:
        raise ValueError('No recognizable nonempty Title/URL records; inspect raw response, do not invent candidates')
    return found


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--query', required=True)
    p.add_argument('--limit', type=int, default=5)
    p.add_argument('--output-dir', required=True, help='New directory outside frozen runtime-snapshot')
    a = p.parse_args()
    if not a.query.strip() or not 1 <= a.limit <= 20:
        p.error('query must be nonempty and limit must be 1..20')
    target = Path(a.output_dir).expanduser()
    if target.exists() or 'runtime-snapshot' in target.parts:
        p.error('output directory must be new and outside runtime-snapshot')
    cli = shutil.which('mcporter')
    if not cli:
        p.error('mcporter missing; use native web search or configure Agent Reach explicitly')
    request = {'query': a.query, 'limit': a.limit, 'backend': 'exa.web_search_exa',
               'retrieved_at': datetime.now(timezone.utc).isoformat()}
    target.mkdir(parents=True, exist_ok=False)
    (target/'request.json').write_text(json.dumps(request, ensure_ascii=False, indent=2))
    try:
        result = subprocess.run([cli, 'call', 'exa.web_search_exa', 'query='+a.query,
                                 'numResults='+str(a.limit), '--output', 'json'],
                                capture_output=True, text=True, timeout=60, check=False)
        (target/'response.json').write_text(result.stdout)
        if result.returncode:
            raise ValueError(f'mcporter failed with exit code {result.returncode}; no verified results')
        records = candidates(json.loads(result.stdout), a.limit)
        for record in records:
            record['retrieved_at'] = request['retrieved_at']
        (target/'candidates.json').write_text(json.dumps(records, ensure_ascii=False, indent=2)+'\n')
        (target/'receipt.json').write_text(json.dumps({**request, 'status':'candidates_only', 'count':len(records),
            'response_sha256':hashlib.sha256(result.stdout.encode()).hexdigest()}, ensure_ascii=False, indent=2))
        print(json.dumps({'status':'candidates_only','count':len(records),'directory':str(target.resolve())},ensure_ascii=False))
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        (target/'error.json').write_text(json.dumps({'status':'failed','reason':str(error)},ensure_ascii=False))
        raise SystemExit(str(error))


if __name__ == '__main__':
    main()
