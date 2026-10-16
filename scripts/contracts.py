#!/usr/bin/env python3
"""Validate local workbench contracts using JSON Schema Draft 2020-12.

Schema validation establishes shape and type, not source truth or scientific
adequacy. Project path authorization remains the caller's responsibility.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from functools import lru_cache
import json
import re
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlsplit

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"


class ContractError(ValueError):
    """Invalid contract name, input, schema, or missing validator dependency."""


def names() -> list[str]:
    return sorted(p.name.removesuffix(".schema.json") for p in SCHEMA_DIR.glob("*.schema.json"))


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict:
    if name not in names():
        raise ContractError(f"Unknown contract: {name!r}; choose {', '.join(names())}")
    try:
        return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError(f"Cannot load {name}: {exc}") from exc


def _library():
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:
        raise ContractError("jsonschema is required; use the research-workbench isolated Python runtime.") from exc
    def checker_factory():
        checker = FormatChecker()

        @checker.checks("date-time", raises=(ValueError, TypeError))
        def date_time(value):
            if not isinstance(value, str):
                return True
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})", value):
                return False
            parsed = datetime.fromisoformat(value.replace('t', 'T').replace('z', '+00:00').replace('Z', '+00:00'))
            return parsed.utcoffset() is not None

        @checker.checks("uri", raises=(ValueError, TypeError))
        def uri(value):
            if not isinstance(value, str):
                return True
            if re.search(r"\s", value) or not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:.+", value):
                return False
            parts = urlsplit(value)
            if parts.scheme in ('http', 'https'):
                # Accessing .port rejects invalid network ports.
                return bool(parts.hostname) and (parts.port is None or 0 <= parts.port <= 65535)
            return bool(parts.scheme)

        return checker

    return Draft202012Validator, checker_factory


def format_checker():
    """Return a checker with deterministic date-time and URI validation."""
    _, factory = _library()
    return factory()


def check_schemas() -> int:
    validator, _ = _library()
    for name in names():
        try:
            validator.check_schema(load_schema(name))
        except Exception as exc:
            raise ContractError(f"Invalid schema {name}: {exc}") from exc
    return len(names())


def validate(name: str, data: dict | list) -> None:
    """Raise ContractError on invalid data. No coercion or repair is performed."""
    try:
        json.dumps(data, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ContractError(f"{name}: input must contain only finite JSON values: {exc}") from exc
    validator, format_checker = _library()
    schema = load_schema(name)
    try:
        validator.check_schema(schema)
        errors = sorted(validator(schema, format_checker=format_checker()).iter_errors(data),
                        key=lambda error: '/'.join(str(x) for x in error.absolute_path))
    except Exception as exc:
        raise ContractError(f"Cannot validate {name}: {exc}") from exc
    if errors:
        summaries = []
        for error in errors[:8]:
            location = '/'.join(str(x) for x in error.absolute_path) or '$'
            summaries.append(f"{location}: {error.message}")
        remaining = f" (+{len(errors)-8} more)" if len(errors) > 8 else ""
        raise ContractError(f"{name}: " + '; '.join(summaries) + remaining)


def load_validate(name: str, path: str | Path) -> Any:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"),
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Non-finite JSON number: {value}")))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ContractError(f"Cannot read {name} at {path}: {exc}") from exc
    validate(name, data)
    return data


def _type_text(schema: dict) -> str:
    if '$ref' in schema:
        return schema['$ref'].rsplit('/', 1)[-1]
    if 'const' in schema:
        return f"{schema.get('type', 'value')} = {json.dumps(schema['const'])}"
    if 'enum' in schema:
        return 'enum: ' + ', '.join(str(v) for v in schema['enum'])
    if 'anyOf' in schema or 'oneOf' in schema:
        return ' / '.join(_type_text(v) for v in schema.get('anyOf', schema.get('oneOf', [])))
    kind = schema.get('type', 'any')
    if kind == 'array':
        return f"array<{_type_text(schema.get('items', {}))}>"
    if schema.get('format'):
        return f"{kind} ({schema['format']})"
    if kind == 'object' and schema.get('additionalProperties', True) is not False:
        return 'object (extensible)'
    return str(kind)


def _field_rows(schema: dict, prefix: str = '') -> list[str]:
    rows = []
    if '$ref' in schema:
        schema = load_schema('project-spec')['$defs'][schema['$ref'].rsplit('/', 1)[-1]]
    if 'oneOf' in schema and 'properties' not in schema:
        # Source/evidence accept one record or an array of the same records.
        schema = schema['oneOf'][0]
    required = set(schema.get('required', []))
    for name, definition in schema.get('properties', {}).items():
        label = f"{prefix}.{name}" if prefix else name
        constraints = []
        for key in ('minimum', 'maximum', 'minLength', 'minItems', 'pattern'):
            if key in definition:
                constraints.append(f"{key}={definition[key]}")
        rows.append(f"| `{label}` | {_type_text(definition).replace('|', '/')} | {'是' if name in required else '否'} | {'; '.join(constraints) or '—'} |")
        if definition.get('type') == 'object' or '$ref' in definition:
            rows.extend(_field_rows(definition, label))
        if definition.get('type') == 'array' and isinstance(definition.get('items'), dict):
            rows.extend(_field_rows(definition['items'], label+'[]'))
        for branch in definition.get('anyOf', []):
            if branch.get('type') == 'object' or '$ref' in branch:
                rows.extend(_field_rows(branch, label))
    return rows


def export_reference(target: str | Path) -> None:
    lines = ['# 统一结构化契约', '',
             '由 `scripts/contracts.py docs` 从实际 JSON Schema 生成；字段类型、必填项与嵌套结构以 schemas/ 文件为准。', '',
             '所有契约使用 JSON Schema Draft 2020-12。新对象要求整数 `schema_version: 1` 与非空 `id`。来源与证据记录允许省略 schema_version，并兼容历史扩展字段；其余已定义对象默认拒绝未知字段。', '',
             '标为 extensible 的参数、结果、模型输出及响应 schema 是显式扩展接口；具体模型输出还必须按请求的 response_schema 校验。', '',
             '结构通过不代表语义正确、文献真实或科研质量达标。来源 ID、证据 ID、文件路径和哈希之间的关联由工作流及质量模块检查。', '',
             'Python 接口：`validate(name, data) -> None`；`load_validate(name, path) -> data`。失败抛出 `ContractError(ValueError)`。', '',
             '条件约束：analysis-result.status=executed 时 code 必须有路径和 SHA-256，input_files 非空、results 非空、output_rows ≥ 1；human-decision.status=answered 时 answer、answered_at、actor 均非空；requested 时 answer 与 answered_at 必须为 null。', '']
    for name in names():
        schema = load_schema(name)
        lines += [f'## {name}', '', f'文件：`schemas/{name}.schema.json`。', '']
        if name in ('source-record', 'evidence-record'):
            lines += ['接受单条对象或对象数组。下表描述单条对象。', '']
        lines += ['| 字段 | 类型 | 必填 | 约束 |', '| --- | --- | --- | --- |']
        lines += _field_rows(schema)
        lines += ['']
    Path(target).write_text('\n'.join(lines)+'\n', encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('self-check')
    check = sub.add_parser('validate')
    check.add_argument('--schema', required=True)
    check.add_argument('--input', required=True)
    docs = sub.add_parser('docs')
    docs.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'self-check':
            result = {'status':'ok', 'schema_count':check_schemas(), 'draft':'2020-12'}
        elif args.command == 'validate':
            load_validate(args.schema, args.input)
            result = {'status':'ok', 'schema':args.schema}
        else:
            export_reference(args.output)
            result = {'status':'ok', 'output':args.output}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except ContractError as exc:
        print(json.dumps({'status':'error','error':str(exc)},ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
