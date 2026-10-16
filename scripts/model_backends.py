#!/usr/bin/env python3
"""Model adapter contract: truthful Codex file handoff or explicit JSON subprocess."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Protocol

import workspace

VERSION = "1.0"
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


class BackendError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def contract(name, value):
    # Fail closed: no silent fallback from JSON Schema to a few hand-written checks.
    try:
        from contracts import validate
        validate(name, value)
    except ImportError as exc:
        raise BackendError("contracts.py and jsonschema are required for model validation") from exc
    except ValueError as exc:
        raise BackendError(str(exc)) from exc


def validate_request(request):
    contract("model-request", request)
    try:
        from jsonschema import Draft202012Validator
        from contracts import format_checker
        from jsonschema.exceptions import SchemaError
        try:
            Draft202012Validator.check_schema(request["response_schema"])
        except SchemaError as exc:
            raise BackendError(f"invalid response_schema: {exc.message}") from exc
        canonical(request)
        pending = [request["response_schema"]]
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                if "format" in item and item["format"] not in format_checker().checkers:
                    raise BackendError(f"unsupported or missing JSON Schema format checker: {item['format']}")
                for key in ("$ref", "$dynamicRef"):
                    if key in item and not str(item[key]).startswith("#"):
                        raise BackendError("response_schema references must be local fragments")
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
    except (TypeError, ValueError) as exc:
        raise BackendError(f"invalid request or response_schema: {exc}") from exc
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", request["id"]):
        raise BackendError("request id must be a safe file name")


def validate_response(request, response):
    contract("model-response", response)
    if response["request_id"] != request["id"]:
        raise BackendError("response request_id does not match")
    if response["provenance"].get("request_sha256") != digest(request):
        raise BackendError("response is not bound to the current request hash")
    if response["status"] == "completed":
        from jsonschema import Draft202012Validator
        from contracts import format_checker
        errors = sorted(Draft202012Validator(request["response_schema"], format_checker=format_checker()).iter_errors(response["output"]), key=lambda error: str(error.path))
        if errors:
            raise BackendError("model output schema violation: " + "; ".join(error.message for error in errors[:5]))
    return response


def response_for(request, backend, status, output, model=None, usage=None, extra=None):
    return {"schema_version": 1, "id": request["id"] + "-response", "request_id": request["id"],
            "backend": backend, "model": model or request["model"], "status": status,
            "output": output, "usage": {"input_tokens": None, "output_tokens": None} if usage is None else usage,
            "provenance": {"created_at": datetime.now(timezone.utc).isoformat(), "backend_version": VERSION,
                           "request_sha256": digest(request), **(extra or {})}}


class ModelBackend(Protocol):
    def generate(self, request: dict) -> dict: ...


class CodexBackend:
    """No model is called. Current Codex must perform the task and supply a receipt."""
    name = "codex"

    def __init__(self, project):
        self.root = workspace.project_path(project)
        if not self.root.is_dir() or not workspace.contained_path(self.root, "project.json").is_file():
            raise BackendError("Codex handoff requires an initialized project")

    def files(self, request):
        return (f"model-io/{request['id']}.request.json", f"model-io/{request['id']}.response.json")

    def generate(self, request):
        validate_request(request)
        request_name, response_name = self.files(request)
        target = workspace.contained_path(self.root, request_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if json.loads(target.read_text(encoding="utf-8")) != request:
                raise BackendError("request id already exists with different content; use a new id")
        else:
            with target.open("x", encoding="utf-8") as handle:
                json.dump(request, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write("\n")
        receipt = workspace.contained_path(self.root, response_name)
        if receipt.is_file():
            response = validate_response(request, json.loads(receipt.read_text(encoding="utf-8")))
            if response["backend"] != "codex" or response["status"] != "completed":
                raise BackendError("Codex receipt must be a completed codex response")
            return response
        response = response_for(request, "codex", "needs_execution", {}, extra={
            "execution_mode": "codex-handoff", "request_file": request_name, "response_file": response_name})
        return validate_response(request, response)

    def accept(self, request, output, model=None):
        """Record current-session output only after the actual task has been executed."""
        validate_request(request)
        existing = self.generate(request)
        response = response_for(request, "codex", "completed", output, model=model, extra={
            "execution_mode": "codex-handoff", "request_file": self.files(request)[0], "response_file": self.files(request)[1]})
        validate_response(request, response)
        if existing["status"] == "completed":
            if existing["output"] != output:
                raise BackendError("a different completed response already exists")
            return existing
        destination = workspace.contained_path(self.root, self.files(request)[1])
        with destination.open("x", encoding="utf-8") as handle:
            json.dump(response, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        return response


class CommandBackend:
    """Execute only explicitly configured argv; JSON stdin/stdout, never a shell."""
    name = "command"

    def __init__(self, argv, timeout=60):
        if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in argv):
            raise BackendError("command backend needs a nonempty argv string array")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 300:
            raise BackendError("command timeout must be 0–300 seconds")
        self.argv, self.timeout = list(argv), timeout

    def generate(self, request):
        validate_request(request)
        # Files cap memory usage. Stderr content is intentionally not exposed: wrappers
        # sometimes log credentials. Exit status is enough to identify a failed call.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                done = subprocess.run(self.argv, input=canonical(request), stdout=stdout, stderr=stderr,
                                      timeout=self.timeout, check=False, shell=False)
            except subprocess.TimeoutExpired as exc:
                raise BackendError(f"model command timed out after {self.timeout} seconds") from exc
            except OSError as exc:
                raise BackendError(f"model command could not start: {type(exc).__name__}") from exc
            if done.returncode != 0:
                raise BackendError(f"model command exited with code {done.returncode}")
            stdout.seek(0)
            data = stdout.read(MAX_OUTPUT_BYTES + 1)
        if len(data) > MAX_OUTPUT_BYTES:
            raise BackendError("model response exceeds 8 MiB")
        try:
            result = json.loads(data)
        except (ValueError, UnicodeError) as exc:
            raise BackendError("model command did not return valid JSON") from exc
        if not isinstance(result, dict) or not isinstance(result.get("output"), dict):
            raise BackendError("wrapper stdout must be an object containing output object")
        unexpected = set(result) - {"output", "usage", "model"}
        if unexpected:
            raise BackendError("unknown wrapper fields: " + ", ".join(sorted(unexpected)))
        response = response_for(request, "command", "completed", result["output"],
                                model=result.get("model"), usage=result.get("usage"), extra={
                                    "execution_mode": "command", "command_sha256": digest(self.argv)})
        return validate_response(request, response)


def make_backend(config):
    if not isinstance(config, dict):
        raise BackendError("backend config must be an object")
    name = config.get("backend")
    if name == "codex" and set(config) <= {"backend", "project"}:
        return CodexBackend(config["project"])
    if name == "command" and set(config) <= {"backend", "argv", "timeout"}:
        return CommandBackend(config["argv"], config.get("timeout", 60))
    raise BackendError("backend must be codex or command with only documented config fields")


def read_json(file):
    value = Path(file)
    if value.is_symlink() or not value.is_file():
        raise BackendError("input must be an ordinary JSON file")
    return json.loads(value.read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--config", required=True)
    generate.add_argument("--request", required=True)
    accept = sub.add_parser("accept-codex")
    accept.add_argument("--project", required=True)
    accept.add_argument("--request", required=True)
    accept.add_argument("--output", required=True, help="JSON output object actually produced in the current Codex session")
    accept.add_argument("--model", help="actual model identifier when available; never guess")
    args = parser.parse_args(argv)
    try:
        request = read_json(args.request)
        if args.command == "generate":
            result = make_backend(read_json(args.config)).generate(request)
        else:
            result = CodexBackend(args.project).accept(request, read_json(args.output), args.model)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
