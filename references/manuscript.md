# 从研究主题到核心期刊目标稿

scope 明确 paper_type、具体问题、拟贡献、可反驳论点及证据边界；按实际材料选择 empirical、integrative_review 或 conceptual。没有指定期刊时自动核验适配北大核心候选及官方要求，依 references/core-journal-readiness.md 选择目标刊和论文类型；无法核实则按学科通用规范完成目标稿并说明期刊适配未核实，不冒称投稿就绪。不用固定文献数或字数取代充分性判断；实际证据薄弱时继续检索最近邻论文和反例，或收窄问题。技术 gate 的1000字符仅防止提纲被误判，绝非论文篇幅目标。

## 写作与修订

1. 先把研究问题收敛为一个论证，而非罗列所有可做选题。形成按证据展开的论证骨架；同一段区分原文发现、作者推论与待检验命题。
2. 写连贯正文。综述的发现是文献比较与可界定的理论综合；概念论文解释概念差异、机制和边界；实证论文报告实际数据、方法、结果及不支持假设的发现。研究设计只放讨论中的后续验证，不能占据全文主体。
3. literature-reading-and-synthesis 提供原文定位；academic-research-suite 用于写作；必要时 academic-humanizer 改善表达。每项事实的 claim_id 与 report.json 对应并链接原文证据。推论写为 interpretation，假设写为 proposal；假设不可写在 source_fact 段。
4. paper-self-review 针对论证跳跃、最近邻重复、证据缺口、反例和过强结论审查。实际修改后才交付；review/audit.md 记重要修改和仍存在的限制，不用评分代替审查。

## 结构化论文与格式

manuscript.schema.json 是全文规范。title、paper_type、abstract、keywords、sections 与 references 为必填。section.role 包括 introduction、methods、findings、discussion、conclusion，可各含多个小节；paragraph 包含 id、text、stance、source_ids 和 claim_ids。references 使用真实完整书目 citation 与 sources 中一致的 URL；禁止补造卷页或作者。正文用 source_ids 生成顺序编号，reference 顺序确定后由 manuscript.render(root) 输出 manuscript.md。生成 Word 的段落文本必须与 manuscript.paragraphs(paper, project_spec_language) 完全一致（中文默认参数仍兼容）；排版可变化。

用 documents 的真实打包运行环境创建 Word，随后 render_docx.py 渲染并查看每页PNG。正文应只含学术内容、实际方法及研究局限，不混入Codex执行日志、接口schema、阶段状态或待办清单。没有个人作者资料就留无署名稿，不读取无关身份文件。

macOS的打包headless渲染器可能找不到中文字体。若PNG只有英文而中文空白，先查看打包配置，在项目review目录准备fontconfig配置，以FONTCONFIG_FILE只为该渲染进程指定已存在的中文字体目录及打包字体目录；不修改受管理的运行环境。渲染成功不等于字形齐全，必须目视核对。删除默认Word标题样式的边框，避免出现无意的彩色线。

package/review 均由 manuscript.validate_project 检查全文结构、非占位正文、引用和claim映射、真实分析限制及Word/Markdown/JSON一致性。quality 的schema指标纳入此验收，evaluation_inputs纳入三份论文哈希，export包纳入必需论文。检查通过不证明语义正确，逐段原文核对和论证审查由当前Codex实际执行。

## 旧项目继续成稿

不修改已冻结旧运行代码或手改完成状态。旧项目只有report时，建立同主题论文项目（说明承接旧项目），复制已核验材料与原始检索响应、正文文本和证据；重新登记范围与当前Codex请求/回执并通过新契约。保留旧报告作为附件，追加真正论文。模型回执只表示当前会话完成实际写作，不伪造精确模型版本、token或外部审稿意见。
