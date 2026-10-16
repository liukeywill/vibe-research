"""Deterministic manuscript rendering and completion gate; not peer review."""
import json
import re
import zipfile
from xml.etree import ElementTree as ET
import contracts
import workspace
import paper_request

ROLES = {"introduction", "methods", "findings", "discussion", "conclusion"}

def read(root, name):
    return json.loads(workspace.contained_path(root, name).read_text(encoding="utf-8"))

def enabled(root):
    state=workspace.contained_path(root,"pipeline-state.json")
    return state.is_file() and read(root, "pipeline-state.json").get("deliverable_profile") == "manuscript"

def bibliography(paper):
    return {r["source_id"]: i+1 for i,r in enumerate(paper["references"])}

def reference_text(r, n):
    return f"[{n}] " + r["citation"] + " " + r["url"]

def paragraphs(paper, language="zh-CN"):
    numbers=bibliography(paper)
    english=language.lower().startswith("en")
    out=[paper["title"], "Abstract" if english else "摘要", paper["abstract"], ("Keywords: " if english else "关键词：")+("; " if english else "；").join(paper["keywords"])]
    for section in paper["sections"]:
        out.append(section["heading"])
        for p in section["paragraphs"]:
            out.append(p["text"]+"".join(f"[{numbers[sid]}]" for sid in p["source_ids"]))
    out += ["References" if english else "参考文献"]+[reference_text(r,i+1) for i,r in enumerate(paper["references"])]
    return out

def markdown(paper, language="zh-CN"):
    numbers=bibliography(paper)
    english=language.lower().startswith("en")
    lines=["# "+paper["title"],"","## Abstract" if english else "## 摘要","",paper["abstract"],"",("Keywords: " if english else "关键词：")+("; " if english else "；").join(paper["keywords"]),""]
    for section in paper["sections"]:
        lines += ["## "+section["heading"],""]
        for p in section["paragraphs"]:
            lines += [p["text"]+"".join(f"[{numbers[sid]}]" for sid in p["source_ids"]),""]
    lines += ["## References" if english else "## 参考文献",""]+[reference_text(r,i+1) for i,r in enumerate(paper["references"])]
    return "\n".join(lines)+"\n"

def render(root):
    paper=read(root,"manuscript.json");validate_content(root,paper)
    workspace.contained_path(root,"manuscript.md").write_text(markdown(paper,paper_request.language(root)),encoding="utf-8")

def validate_content(root,paper):
    contracts.validate("manuscript",paper)
    roles={s["role"] for s in paper["sections"]}
    if not ROLES <= roles: raise workspace.WorkspaceError("论文缺少引言、方法、分析、讨论或结论")
    if paper["paper_type"]=="empirical" and read(root,"research/analysis-result.json")["status"]!="executed":
        raise workspace.WorkspaceError("没有执行真实分析，不能交付完整实证论文")
    sources={s["id"]:s for s in read(root,"research/sources.json")}
    claims={c["id"]:c for c in read(root,"report.json")["claims"]}
    evidence={e["id"]:e for e in read(root,"research/evidence.json")}
    refs=bibliography(paper)
    if len(refs)!=len(paper["references"]):raise workspace.WorkspaceError("参考文献重复")
    for ref in paper["references"]:
        source=sources.get(ref["source_id"])
        if not source or source["metadata_status"]!="verified" or source["access_level"]!="fulltext" or ref["url"]!=source["url"]:
            raise workspace.WorkspaceError("论文参考文献须有已核对正文与一致来源URL")
    ids=[];used=set();count=0
    for section in paper["sections"]:
        if not section["paragraphs"]:raise workspace.WorkspaceError("论文不能只有标题")
        for p in section["paragraphs"]:
            ids.append(p["id"]);count+=len(p["text"].strip());used.update(p["source_ids"])
            if re.search(r"TODO|待补写|此处填写|\[待填\]|PLACEHOLDER",p["text"],re.I):
                raise workspace.WorkspaceError("论文正文仍有未写占位内容")
            if set(p["source_ids"])-refs.keys():raise workspace.WorkspaceError("论文引用没有参考文献")
            for cid in p["claim_ids"]:
                c=claims.get(cid)
                if not c or c["status"]=="unsupported":raise workspace.WorkspaceError("论文引用不存在或无支持的claim")
                if c["status"]=="hypothesis" and p["stance"] not in ("proposal","interpretation"):
                    raise workspace.WorkspaceError("假设不能进入已证明事实段")
                required={evidence[eid]["source_id"] for eid in c["evidence_ids"]}
                if not required<=set(p["source_ids"]):raise workspace.WorkspaceError("正文claim缺少对应来源引用")
            if p["stance"]=="source_fact" and not p["claim_ids"]:raise workspace.WorkspaceError("原文事实段须登记claim映射")
    if len(ids)!=len(set(ids)):raise workspace.WorkspaceError("论文段落ID重复")
    if count<1000:raise workspace.WorkspaceError("正文不足1000字符，仅提纲不能通过论文终点检查")
    if used!=set(refs):raise workspace.WorkspaceError("参考文献含未在正文引用的条目")
    budget=paper_request.validate_budget(root,paper)
    return {"body_characters":count,"paragraphs":len(ids),"references":len(refs),**budget}

def validate_project(root):
    paper=read(root,"manuscript.json");result=validate_content(root,paper)
    language=paper_request.language(root)
    if workspace.contained_path(root,"manuscript.md").read_text(encoding="utf-8")!=markdown(paper,language):
        raise workspace.WorkspaceError("论文Markdown与结构化正文不同")
    try:
        with zipfile.ZipFile(workspace.contained_path(root,"manuscript.docx")) as z:
            tree=ET.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile,KeyError,OSError,ET.ParseError) as exc:
        raise workspace.WorkspaceError("论文DOCX不是可读取的Word文件") from exc
    ns={"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    actual=["".join(t.text or "" for t in p.findall(".//w:t",ns)) for p in tree.findall(".//w:body/w:p",ns)]
    if [t for t in actual if t.strip()]!=paragraphs(paper,language):raise workspace.WorkspaceError("DOCX正文与论文JSON不同")
    return result
