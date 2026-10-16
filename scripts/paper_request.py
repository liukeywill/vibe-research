"""Normalize manuscript requests and enforce budgets; does not write papers."""
import argparse
import json
import re
import workspace

PREFIX = "paper_request:"

def normalize(value):
    if not isinstance(value, dict) or set(value) - {"topic", "discipline", "length", "language"}:
        raise workspace.WorkspaceError("论文参数不是对象或含未知字段")
    result = {"discipline": "auto", "length": 8000, "language": "zh-CN", **value}
    for key in ("topic", "discipline", "language"):
        if not isinstance(result.get(key), str) or not result[key].strip():
            raise workspace.WorkspaceError(f"论文参数 {key} 必须为非空字符串")
        result[key] = result[key].strip()
    if type(result["length"]) is not int or result["length"] < 1000:
        raise workspace.WorkspaceError("论文 length 必须为不小于1000的整数")
    aliases = {"中文": "zh-CN", "简体中文": "zh-CN", "Chinese": "zh-CN", "英文": "en", "英语": "en", "English": "en"}
    result["language"] = aliases.get(result["language"], result["language"])
    return result

def request(root):
    path = workspace.contained_path(root, "project-spec.json")
    if not path.is_file():
        return None
    spec = json.loads(path.read_text(encoding="utf-8"))
    values = [c[len(PREFIX):] for c in spec.get("constraints", []) if isinstance(c, str) and c.startswith(PREFIX)]
    if not values:
        return None
    if len(values) != 1:
        raise workspace.WorkspaceError("论文输入约束重复")
    try:
        value = normalize(json.loads(values[0]))
    except (ValueError, TypeError) as exc:
        raise workspace.WorkspaceError("论文输入约束不是有效JSON") from exc
    if value["topic"] != spec["topic"] or value["language"] != spec["language"]:
        raise workspace.WorkspaceError("论文输入选题或语言与project-spec不一致")
    return value

def language(root):
    path = workspace.contained_path(root, "project-spec.json")
    return json.loads(path.read_text(encoding="utf-8")).get("language", "zh-CN") if path.is_file() else "zh-CN"

def validate_budget(root, paper):
    value = request(root)
    if value is None:
        return {}
    body = "\n".join(p["text"] for s in paper["sections"] for p in s["paragraphs"])
    english = value["language"].lower().startswith("en")
    count = len(body.split()) if english else len(re.sub(r"\s", "", body))
    if not value["length"] * .9 <= count <= value["length"] * 1.1:
        raise workspace.WorkspaceError(f"论文正文实际长度{count}不在目标{value['length']}的±10%范围内")
    return {"requested_length": value["length"], "body_length": count,
            "length_unit": "words" if english else "non_whitespace_characters"}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    norm = sub.add_parser("normalize")
    norm.add_argument("--topic", required=True)
    norm.add_argument("--discipline", default="auto")
    norm.add_argument("--length", type=int, default=8000)
    norm.add_argument("--language", default="zh-CN")
    args = parser.parse_args()
    try:
        result = normalize({k: getattr(args, k) for k in ("topic", "discipline", "length", "language")})
    except workspace.WorkspaceError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
