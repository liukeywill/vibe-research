# 自动成稿模式

本指南中的 SKILL 指统一 Vibe Research 技能根目录，不是 references 目录，也不是旧 auto-paper 安装目录；已有项目优先使用其 runtime-snapshot 内冻结脚本。

默认简体中文，当前 Codex 是任务执行者。一次委托连续完成当前材料允许的全部阶段，不能只输出计划、技能清单或 next 结果。v3 新项目默认 structured：JSON 用于机器校验与模块交互，Markdown 用于阅读，两者须一致。

## 定位与共用基础

本模式拥有连续执行与结构化验收流程，重点是完成当前证据允许的论文及材料包。希望逐阶段核查时使用统一入口的人工核查模式；普通文章、局部表达编辑使用 Vibe Writing。用户已明确要求中途决策时沿用现有 human_decisions 交接，不假造批准，不将自动模式改成逐阶段固定停等。

启动与恢复先读 [Research Core 自动模式适配与版本](automatic-research-core-adapter.md)，按本项目采用的版本读取共享基础。新安装包已内置：

| 阶段 | 共用模块 |
|---|---|
| scope、design、analyze | [问题、设计与验证](../shared/research-core/references/question-design.md) |
| search、read、synthesize | [文献与证据](../shared/research-core/references/evidence.md) |
| package、review | [主张、写作与审查](../shared/research-core/references/claims-review.md) |
| init、恢复与失效复核 | [记录与追溯](../shared/research-core/references/traceability.md) |

共享基础不增加人工确认、不建立第二套状态机。Vibe Research 的人工决定记录不能通过改名直接导入 pipeline；需要迁移时逐项核对前置材料与已执行范围。

## 调用参数与无人值守模式

调用：`使用 $vibe-research，模式：自动成稿；选题：城市遗产更新；学科：文旅与社会学；字数：8000；语言：中文。全程自动生成完整论文。` 也可传 JSON：`{"topic":"城市遗产更新","discipline":"文旅与社会学","length":8000,"language":"zh-CN"}`。仅 topic 必填，其余默认学科自动推断、正文8000字、zh-CN；中文按正文非空白字符、英文按正文词数，默认容差±10%。参数、章节预算、大纲与自动衔接见 [自动成稿模式](autonomous-manuscript.md)。

自动成稿默认不询问缺省参数，不逐阶段确认，不要求用户下载、登录或解验证码。源受阻则自动替换可访问的中文期刊官网、开放正文和其他来源；保持中英文证据覆盖。没有真实数据且未限定类型时自动完成综述或理论论文；必须依赖不存在的数据或全部可信来源受阻时记录实际未完成项并自动结束，不虚构成果，不宣称任何网络条件下必定成功。用户明确要求中途决策时才启用相应人工交接。

## 默认终点是北大核心期刊投稿稿件

“启动自动科研/按默认流程”表示按北大核心期刊投稿要求准备完整稿件，不得以研究方案、证据报告或“下一步采集”代替正文。新 CLI 项目默认 `--deliverable-profile manuscript`：package 必须有 manuscript.json、manuscript.md、manuscript.docx；缺论文不能 complete。report.json/md 是内部论断台账与附件。只有用户明确只要方案/综述报告时才选 `--deliverable-profile report`。程序 API 的旧调用及冻结旧项目保留兼容，不自动改变旧项目的快照。

在 scope 确定可真实完成的论文类型：有合适真实数据为实证论文；无数据且用户未限定类型，默认以公开正文证据写完整整合性综述或理论论文，明确说明所选类型，继续至成稿。不得把研究方案改名为论文，不把有限检索称为系统综述。用户明确要求实证论文时先寻找可用公开数据；缺少不可替代数据时交付已写部分和缺项，准确标注未完成，不暗改论文类型或伪造结果。分析planned只说明未来实证未做，不能成为无数据综述/理论论文停止写作的理由。

默认质量目标为北大核心期刊的选题价值、实质创新、严谨方法、充分真实证据、国内外文献对话及目标刊格式。未指定期刊时自动核验适配候选的核心目录版本、官方投稿指南和近期文章，选择写作目标，不实际投稿。执行 [核心期刊投稿准备度](core-journal-readiness.md) 审查；技术 complete 不等于学术达标，只有逐项有依据通过才能标注“按目标刊要求完成投稿前准备”，否则标注“核心期刊目标稿，尚待完善”并列明缺口。不能仅把初稿改称可发表文章。

成稿执行见 [论文写作与终点验收](manuscript.md)。正文应独立可读，有摘要、引言、资料与方法、实质分析、讨论、结论、真实参考文献；工作流、质量分数、采集待办放附件。写完实际自审并修改，按 documents skill 创建、渲染和逐页检查 Word。脚本检查结构、引用、正文一致性及哈希，不能判定创新性或可发表性。

## 连续执行

1. 读取本技能 runtime.json 的 python（发布版为 python3），先检查该解释器能否 import jsonschema；缺少时自动准备项目外隔离环境并安装 requirements.txt，保留真实依赖安装与版本记录，不宣称未运行的安装已完成。下文以 PYTHON 代指隔离解释器，以 SKILL、PROJECT 代指技能和项目绝对路径。v3 契约需要 jsonschema，不得用缺少依赖的系统 Python 宣称通过。已有项目先读 project.json、pipeline-state.json、task_plan.md、notes.md，沿用其 profile；新项目使用用户目录，未指定则在当前工作目录的 科研项目/<简短主题>/，创建父目录后执行 `PYTHON SKILL/scripts/pipeline.py init --project PROJECT --topic TOPIC`。不重新初始化已有流水线。structured init 冻结脚本/schema 并生成 engine-manifest；随后用项目 runtime-snapshot 下的脚本运行。对于有 engine-manifest 的 structured 项目，start/complete 等阶段变更会拒绝实际运行代码/schema 与冻结 SHA 不符；next/status 仍可检查状态和失效。旧项目无快照时明确保留未冻结限制。
2. 读取 `pipeline.py next --project PROJECT` 返回的 stage-task。按 required_artifacts 和下表实际执行；开始时用 start --stage STAGE。next/start 只交接任务，不会自行调用模型或工具。模型产物通过 [模型接口](interfaces.md) 保存实际请求和完成回执；needs_execution 不是完成。
3. 按 [schema 字段规范](schema-reference.md) 写产物；核对事实、方法和 Markdown/JSON 一致后执行 complete --stage STAGE。它验证 schema、跨文件 ID、输入/输出哈希及阶段门槛；仍需实际学术审查。不要手改状态为 succeeded。
4. 持续 next → start → 实际任务 → complete，直到完成、合理替代路径已耗尽，或需要不可替代的用户输入。更新进度，不逐阶段重复要求批准；已给定条件直接使用。可并行独立检索、不同论文精读、反驳审查，主线程合并 sources/evidence，避免同时改同一索引。
5. 短暂故障记录 fail --reason，按 next_retry_at 退避后修复或替换来源；默认第三次实际失败转 blocked。自动成稿优先替换来源或在证据范围内收窄问题，不因常规参数或访问验证创建人工请求。不可替代条件缺失用 block，准确交付保存材料与未完成原因。仅用户已指定人工交接或任务确需新授权且未选择自动退出时用 human_decisions.py request，答复必须来自实际用户，不能由代理代填批准。解障后记录依据再 retry。操作和人工交接见 [执行接口](execution.md)。
6. 修改已登记产物、原文或分析依赖会使相关阶段及后续 stale。从最早失效阶段复核并重新 complete，最后重算质量。不能只修改可编辑的 pass 字段。
7. review 阶段运行 quality.py --project PROJECT，处理必需指标失败；complete review 按报告的 evaluation_config 保留原策略/独立标注集重算，并核对 evaluation_inputs 的科学输入 SHA。成果包按精确收据纳入这些项目内文件。运行 workspace.py check、pipeline.py status，完成后 export_bundle.py --project PROJECT 生成本地 delivery 包。准确交代 executed、planned、未测和实际交付位置。

## 八阶段产物与方法

路径相对于项目。完整嵌套字段、类型、必填项和约束来自 schemas/*.schema.json；字段汇总见 [schema 规范](schema-reference.md)，不自行用散文代替契约。

| 阶段 | 实际工作与技能 | 必需产物 |
|---|---|---|
| scope | research-ideation：问题、对象、范围、纳排标准、交付目标、竞争解释 | question.md、project-spec.json |
| search | Crossref/ERIC 或显式数据源检索；screen_sources.py 初筛和重复提示；按主题补官方中文资料，深度综述用 academic-research-suite | research/search-query.json、research/search-results.json、research/search-log.md、research/screening.json |
| read | literature-reading-and-synthesis：实际阅读正文、方法、图表、局限，逐论断留定位与核验记录 | research/sources.json、research/evidence.json、research/reading-notes.md |
| synthesize | 同上生成横向矩阵；有分歧才用 map-literature-contradictions，按样本/方法/情境分析 | research/synthesis.json、research/synthesis.md |
| design | 读 [社科适配](social-science.md)；实证用 experimental-design、statistical-power；访谈用 interview-analyst；概念路线说明适用边界 | research/study-design.json、research/study-plan.md |
| analyze | 真数据用 statistical-analysis/statsmodels 或 interview-analyst；当前内置数值适配器为 OLS+HC3，其他方法按接口扩展；无数据为 planned | research/analysis-result.json、research/analysis.md；executed 另需数据字典、清洗日志、代码及复现记录 |
| package | academic-research-suite：从证据到完整论文，论证、自审修订及正文引用；report 为附件；documents 创建并逐页检查 Word | report.json、report.md；默认另需 manuscript.json、manuscript.md、manuscript.docx |
| review | paper-self-review 核查论断、反例、推断和方法；quality.py 计算质量；有真实外审才用 review-response | review/audit.md、review/quality-report.json |

## 检索、全文与证据

按项目冻结版本的 Research Core 文献与证据要求执行。中国情境的教育、社科与文旅默认中英文并行检索，中文学术研究参与缺口判断和论证，政策不代替学术文献。[中文文献与知网](chinese-literature.md) 规定浏览器检索、实际权限和受阻替代；不是已接通的官方 API 或无限制下载服务。

本引擎保留结构化 search-query、原始响应和请求快照；Crossref/ERIC 的 metadata_status 只标元数据状态。精确 DOI/ERIC 去重与近似标题提示分开处理。筛选改判用 adjudicate，保留 include/exclude/uncertain 和实际核验主体，未决来源不直接进入已核验证据。

实际阅读后用 collect_sources.py capture 保存 UTF-8 文本及 SHA，并登记 access_level、read_scope、URL、locator、reviewer、reviewed_at、support_status、claim_verification；保存动作不能自动升级阅读状态。read 起至少一条可定位全文证据是技术下限，不是学术充分性标准。详细字段与跨 ID 关系见 [证据规范](evidence-schema.md) 和 schemas/。

## 数据、质量与边界

- 清洗前写 data/dataset-spec.json：原始路径与 SHA、来源许可、观察单位、字段、缺失和重复政策。当前 analyze_data.py 可执行选定数值变量的 OLS+截距+HC3，保存逐规则清洗日志、冻结输入、环境、analysis-code/reproduce.py，并在独立子进程重算。类别编码、整群/重复测量、因果推断及访谈不能默认套用这个适配器；见 [数据与质量](data-and-quality.md)。
- 无实测数据时，analysis-result 的 status 为 planned，代码/样本/结果明确为空或未执行，analysis.md 写同一原因；complete --stage analyze --disposition planned --reason。无分析环节为 not_applicable。不得虚构样本、访谈引语、实验效果或审批号。
- 样本量假设、聚类/流失及敏感性范围须明示。观察关联不能升级为因果，研究空白仅限当前检索范围。调查、招募、现场采集、伦理决定和投稿实施依赖真实条件，准备工具不等于已开展。
- 质量门槛检查 schema、引用映射、论断核验登记覆盖、筛选覆盖及执行分析的复现；不证明语义真值或学术可发表性。没有独立人工标注集时 precision/recall 保留 null/not_measured，分母为零不记 100%。
- 默认当前 Codex 会话执行，不新增模型 API、常驻服务或定时任务。Codex handoff 保存实际请求/回执；无法获知精确模型版本和 token 时分别写 current-codex-session 和 null，不猜测。可选 command 后端是 JSON stdin/stdout 接口，真实外部模型连接需要另行配置；mock 测试不等于外部模型实测。
- 个人资料默认留本地；不读取或修改 sheqing-minyi 身份文件。外发、公开、投稿、付费、定时和外部知识库写入须符合用户当前授权；本地成果包不代表全文可公开分发。

来源、许可、跨仓库选型与适配见 [组件来源](components.md)。中断后说“继续 Vibe Research 自动项目，项目在……”即可按状态恢复。
