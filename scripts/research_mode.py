#!/usr/bin/env python3
"""Inspect a research project's mode without creating or changing any files."""
import argparse
import json
from pathlib import Path


class ModeError(ValueError):
    pass


def select_mode(project=None, requested=None):
    if requested not in (None, 'manual', 'automatic'):
        raise ModeError('Unknown requested mode')
    default = requested or 'manual'
    if project is None:
        return {'mode': default, 'action': 'new_project', 'reason': 'explicit_request' if requested else 'entrypoint_default'}
    root = Path(project).expanduser().resolve()
    if not root.exists():
        return {'mode': default, 'action': 'new_project', 'project': str(root)}
    if not root.is_dir():
        raise ModeError('Project path must be a directory')
    manual = root / 'state.json'
    automatic = root / 'pipeline-state.json'
    if manual.exists() and automatic.exists():
        raise ModeError('Both mode state files exist; choose and inspect the actual project before writing')
    state_file = manual if manual.exists() else automatic if automatic.exists() else None
    if state_file is None:
        if any(root.iterdir()):
            raise ModeError('Nonempty directory has no recognized project state; do not initialize over it')
        return {'mode': default, 'action': 'new_project', 'project': str(root)}
    try:
        data = json.loads(state_file.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise ModeError('Unreadable project state; preserve and inspect it') from error
    if not isinstance(data, dict) or not isinstance(data.get('stages'), dict):
        raise ModeError('Invalid project state; do not guess its mode')
    if state_file == manual:
        if data.get('workflow') not in (None, 'vibe-research-human-review') or type(data.get('current_stage')) is not int or data['current_stage'] not in range(1, 9):
            raise ModeError('Unrecognized manual workflow or stage')
        mode = 'manual'
    else:
        mode = 'automatic'
    result = {'mode': mode, 'action': 'resume', 'project': str(root), 'state_file': state_file.name}
    if requested and requested != mode:
        result.update(action='needs_migration', requested_mode=requested,
                      reason='Preserve existing state and prepare a separate continuation project')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--requested', choices=['manual', 'automatic'])
    args = parser.parse_args()
    try:
        result = select_mode(args.project, args.requested)
    except ModeError as error:
        parser.exit(1, str(error) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result['action'] == 'needs_migration' else 0


if __name__ == '__main__':
    raise SystemExit(main())
