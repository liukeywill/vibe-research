# 现有工作台的自动成稿模式

沿用八阶段 pipeline、现有 manuscript.schema.json、claim/evidence 台账与 Word 验收，不建立第二套论文状态机。当前 Codex 是检索、阅读、写作与修订执行者；脚本不自行调用模型或生成全文。自动模式不新增后台服务或外部 API 配置。

## 输入参数

| 字段 | 类型 | 必填 | 默认 |
|---|---|---|---|
| topic | string | 是 | 用户本次选题或正在讨论的明确选题 |
| discipline | string | 否 | auto，自动判断 |
| length | integer，≥1000 | 否 | 8000，正文目标长度 |
| language | string | 否 | zh-CN，中文；英文使用 en |

使用 `PYTHON SKILL/scripts/paper_request.py normalize --topic TOPIC [--discipline DISCIPLINE --length N --language LANGUAGE]` 得到归一化 JSON。将输出原样加上前缀 `paper_request:` 写入 project-spec.json 的 constraints 数组，按原 scope schema 校验；不要添加原 schema 不允许的顶层字段。其 language 与 project-spec.language 保持一致。输入留在既有范围契约中，受到阶段输入哈希与导出机制追踪。旧项目没有该约束时保留原篇幅要求，不默认为其追加8000字。

中文 length 为章节段落的非空白字符数（含标点、夹杂外文），英文为按空白切分的词数；不包括标题、章节标题、摘要、关键词、引文标号和参考文献。默认±10%；用户给硬上限时在 constraints 另明示并实际核查。学科和语言决定概念、章节与文风。默认北大核心投稿目标；未给目标刊时自动核验适配候选与现行官方指南，按 core-journal-readiness.md 执行，不虚构期刊要求。明确目标刊的实际字数、摘要、引文要求优先于缺省值；用户显式参数冲突时如实保留并标注适配缺口，不静默篡改。引用沿用工作台的顺序编号与真实书目规范；章节名称、摘要和关键词使用用户语言。

## 自动衔接

scope：在 question.md/project-spec.json 明确研究问题、概念关系、竞争解释、论文类型和参数。过宽题目自动收窄并说明理由。

search/read：在既有检索日志与证据台账完成真实中英文检索、纳排、全文阅读和逐论断定位。知网验证码、登录和权限要求在自动模式下直接记录受阻并换来源，不交用户处理；政策不能代替中文学术研究。只读摘要不升级全文状态，中文 DOI 缺少 Crossref 记录不等于文献不存在。

synthesize/design：在 synthesis.md 保存研究框架，在 study-plan.md 追加论文大纲、每章中心论点、关键 evidence/claim ID、反例和正文篇幅预算。预算总和等于 length。综述方法描述实际检索，不虚构系统检索、双人筛选或已完成实验。

analyze/package：真实数据才做实证；默认无数据论文将分析正确标为 not_applicable，综述的实质分析在正文展开。依大纲撰写所有章节，JSON stance 沿用 source_fact/interpretation/proposal；先正文修订后写摘要、关键词和标题。整合成 manuscript.json/md/docx，不交付只有框架或研究计划的文件。

review：另按 core-journal-readiness.md 完成核心期刊投稿准备度逐项审查，结论写入 review/audit.md，核心缺口未解决时不得称投稿就绪。至少完成一次反驳审查与一次逐段引文核对并修复关键问题。现有 manuscript.validate_content 自动读取 paper_request 约束并检查实际篇幅；package/review 均经过同一 gate。实际打开原文核对来源与论断，schema或标记检查不能证明语义真实。Word沿用 documents 创建、渲染、逐页检查和全文一致性验收。

默认输出按北大核心期刊要求准备的完整可编辑 manuscript.docx、manuscript.md、manuscript.json，结构包括标题、摘要、关键词、引言、方法、实质正文、讨论、结论、参考文献；内部 report、检索和证据、研究框架、大纲、质量记录随原 delivery 包交付。所有章节角色和字段仍使用 references/schema-reference.md 与 schemas/manuscript.schema.json，不另造不兼容格式。

## 自动替代与结束

短暂请求最多实际重试两次，再更换独立可信来源。资料不足先补检索，再收窄不受支持的论断；不按固定引用数凑文献，不填造作者、卷期页、数字、访谈或审批。默认类型可选择完整整合性综述或理论论文，但不能暗改用户明确要求的实证交付。

遇不可替代的真实数据缺失、全部证据路线失败、文档工具不可用等，保留材料并在既有 pipeline-state/audit 中标注 blocked 或未完成；可在 review/failure.json 保存 failed_stage、reason、attempted_alternatives、saved_outputs。自动结束并说明具体未完成项，不造人工批准，不改 gate 使残稿通过，不反复询问。无人值守是不用人推进步骤，不是保证学术创新、发表或外部平台访问可用。

已有冻结项目按原快照继续；使用新增篇幅检查需建立承接旧材料的新项目，不能修改冻结脚本或冒充旧项目已接受新能力。仅本地更新，不自动同步GitHub、公开发布或投稿。
