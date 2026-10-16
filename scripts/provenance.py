"""Freeze the engine, schemas and adopted research rules; not a semantic quality claim."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys

import workspace


def assert_execution(root):
    """Refuse mutation with an installed engine that differs from the frozen version."""
    manifest_path=workspace.contained_path(root,'engine-manifest.json')
    if not manifest_path.is_file(): return  # Existing structured projects without a snapshot.
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    base=Path(__file__).resolve().parent.parent
    for record in manifest['files']:
        relative=record['path'].removeprefix('runtime-snapshot/')
        source=base/relative
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=record['sha256']:
            raise workspace.WorkspaceError('当前执行代码与冻结版本不一致；使用项目 runtime-snapshot/scripts 继续: '+relative)


def research_core_files(base):
    """Validate the bundled rule receipt before freezing a new structured project."""
    lock_path = base / 'shared/research-core.lock.json'
    module_base = base / 'shared/research-core'
    try:
        lock = json.loads(lock_path.read_text(encoding='utf-8'))
        module = json.loads((module_base / 'module.json').read_text(encoding='utf-8'))
        if lock.get('name') != 'research-core' or module.get('name') != 'research-core':
            raise ValueError('module name')
        if lock.get('version') != module.get('version') or not module.get('version'):
            raise ValueError('module version')
        source_commit = lock.get('source_commit', '')
        if len(source_commit) != 40 or any(c not in '0123456789abcdef' for c in source_commit):
            raise ValueError('source commit')
        records = lock['files']
        if set(records) != {'module.json', *module['files']}:
            raise ValueError('file inventory')
        actual = {p.relative_to(module_base).as_posix() for p in module_base.rglob('*') if p.is_file() or p.is_symlink()}
        if actual != set(records):
            raise ValueError('unexpected or missing module files')
        sources = [lock_path]
        for relative, expected in records.items():
            part = Path(relative)
            source = module_base / part
            if part.is_absolute() or '..' in part.parts or source.is_symlink() or not source.resolve().is_relative_to(module_base.resolve()):
                raise ValueError('module path')
            actual_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            if actual_hash != expected or (relative != 'module.json' and actual_hash != module['files'][relative]):
                raise ValueError('module hash: ' + relative)
            sources.append(source)
        return sources, lock
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise workspace.WorkspaceError('Research Core 随包模块或锁文件无效: ' + str(error)) from error


def capture(root):
    base=Path(__file__).resolve().parent.parent
    manifest_path=workspace.contained_path(root,'engine-manifest.json')
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        for record in manifest['files']:
            target=workspace.contained_path(root,record['path'])
            if hashlib.sha256(target.read_bytes()).hexdigest()!=record['sha256']:
                raise workspace.WorkspaceError('冻结运行代码已改变: '+record['path'])
        return manifest
    foundation_sources, foundation_lock = research_core_files(base)
    files=[]
    candidates=[p for p in sorted((base/'scripts').glob('*.py')) if not p.name.startswith('test_')]
    candidates+=sorted((base/'schemas').glob('*.schema.json'))
    candidates+=foundation_sources
    for source in candidates:
        relative='runtime-snapshot/'+source.relative_to(base).as_posix()
        target=workspace.contained_path(root,relative)
        target.parent.mkdir(parents=True,exist_ok=True)
        data=source.read_bytes()
        if target.exists() and target.read_bytes()!=data:
            raise workspace.WorkspaceError('拒绝覆盖不同运行代码: '+relative)
        if not target.exists(): target.write_bytes(data)
        files.append({'path':relative,'sha256':hashlib.sha256(data).hexdigest()})
    packages={}
    for name in ('jsonschema','numpy','pandas','scipy','statsmodels'):
        try: packages[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: packages[name]=None
    manifest={'schema_version':1,'id':'engine-manifest','contract_version':1,
              'runtime':{'python':sys.version.split()[0],'system':platform.system(),'machine':platform.machine(),'packages':packages},
              'files':files,'research_core':{'version':foundation_lock['version'],'source_commit':foundation_lock['source_commit'],
                                           'snapshot':'runtime-snapshot/shared/research-core/'},
              'model_identity':'current Codex session; exact model ID and token usage unavailable',
              'meaning':'Frozen code and schemas, not a transcript or a claim of semantic correctness'}
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return manifest
