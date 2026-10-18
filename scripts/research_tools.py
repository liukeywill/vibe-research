"""Local support for views and evaluations; never advances research state."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone

import workspace


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def content_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.research-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + ' must be nonempty text')
    return value


def fingerprint(directory):
    """Content inventory including instructions; ignore only runtime/cache/VCS files."""
    root = workspace.project_path(directory)
    if not root.is_dir():
        raise ValueError('Candidate directory does not exist')
    files = {}
    for item in sorted(root.rglob('*')):
        relative = item.relative_to(root)
        if any(part in {'.git', '__pycache__', '.venv', '.DS_Store'} for part in relative.parts):
            continue
        if item.is_symlink():
            raise ValueError('Candidate symlinks are not supported: ' + str(relative))
        if item.is_file():
            files[relative.as_posix()] = sha(item)
    if not files or 'SKILL.md' not in files:
        raise ValueError('Candidate must contain SKILL.md')
    return {'sha256': content_sha(files), 'files': files}


def file_record(root, relative):
    target = workspace.contained_path(root, relative)
    return {'path': relative, 'exists': target.is_file(),
            'sha256': sha(target) if target.is_file() else None}
