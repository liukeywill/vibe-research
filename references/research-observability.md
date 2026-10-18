# 研究看板、固定评测与纠错闭环

这些能力通过 `$vibe-research` 调用，不建立新技能、模式或研究状态机。脚本只用标准库；已有结构化流水线仍需要原有 jsonschema 等依赖。

## 研究看板

```text
$vibe-research 查看 /项目绝对路径 的研究看板。
```

```bash
python3 SKILL/scripts/dashboard.py --project PROJECT
```

生成 `review/dashboard.html` 与同名 JSON 快照。HTML 可离线搜索、展开记录、打开本地成果与原始来源。展示人工或自动阶段、未核查项、report/synthesis 中的主张与来源链、证据定位、文件缺失/自动阶段哈希变更、model-io 回执元数据和纠错台账。不解析 Markdown 自行创造主张 ID；人工项目没有结构化证据时展示阶段文件及 decisions.md。

首次保存项目、阶段交付、恢复、变更后刷新，并向用户提供链接。没有项目状态或两套状态冲突时报告错误，不初始化或猜选模式。自动项目日志和状态不一致时保留文件并报告。看板不运行分析、不自动核验语义，也不更改阶段/人工决定。

## 固定任务评测

```text
$vibe-research 用固定任务比较这个候选版本与当前版本，保留逐题结果。
```

内置 `assets/research-regression.json` 包含八个公开合成任务：全文访问、因果边界、计划与执行、材料变更、人工核查、缺失数据、阴性结果、限定范围内的支持。它们用于发现流程退步；不等同盲测、独立科研准确率或模型训练。公开参考不能作为作答阶段的输入。

1. 保留旧版和候选版两个独立技能目录。用相同 suite、模型身份与预算分别 prepare。指纹包含 SKILL.md、references、scripts、schemas 等内容；忽略缓存和 Git 元数据。
2. 作答时读取对应版本的 SKILL.md 及必要参考，仅向作答上下文提供 request.json 的问题和材料，不提供 suite.json 的评分参考。当前 Codex 实际作答；脚本不调用模型。一次会话中的自测应明确披露，不称为独立盲测。没有独立模型/上下文时不能宣称测得了两个版本的因果效果。
3. 保存真实答案和执行来源；submit 机械核对 decision、evidence_ids 和已登记调用预算。reason 供人读，不假装已检查其推理质量。未知模型版本用 current-codex-session；未知调用数/token 用 null，不猜数。预算是交接条件，调用计数是执行者登记，不是宿主强制限额或供应商认证。
4. compare 要求同任务、同模型标识、同预算，逐题记录退步；缺答计失败。只有完整覆盖、实际作答、候选内容不同、分数严格改善且无逐题退步，才可进入人工采用判断；平分保留旧版。fixture 不进入采用判断。

```bash
python3 SKILL/scripts/benchmark.py prepare --run PROJECT/review/evals/base \
  --candidate BASE_SKILL --label baseline
python3 SKILL/scripts/benchmark.py prepare --run PROJECT/review/evals/candidate \
  --candidate CANDIDATE_SKILL --label candidate
python3 SKILL/scripts/benchmark.py submit --run PROJECT/review/evals/base --responses BASE_ANSWERS
python3 SKILL/scripts/benchmark.py submit --run PROJECT/review/evals/candidate --responses CANDIDATE_ANSWERS
python3 SKILL/scripts/benchmark.py compare --baseline PROJECT/review/evals/base \
  --candidate PROJECT/review/evals/candidate --output PROJECT/review/comparison.json
```

prepare 创建新运行目录并冻结题目、候选内容清单和请求哈希；仅表示等待作答。答案文件结构：

```json
{
  "request_sha256": "复制本次 manifest.json 中的实际请求哈希",
  "origin": "actual",
  "model": "current-codex-session",
  "answers": [
    {"case_id":"实际题目ID","decision":"实际判断","evidence_ids":[],
     "reason":"根据材料给出的理由","model_calls":null,"tool_calls":null}
  ]
}
```

actual 只用于真实执行；测试生成的答案必须为 fixture。模型身份和 origin 都是本地声明。得分重算而不信任可编辑的 score.json；更换题目/预算、重复 ID、过期请求哈希、覆盖不全和篡改比较材料都不能作为改善证明。已提交答案不可覆盖，重测创建新运行。

可用同格式自定义领域套题，保留来源、许可、固定版本与独立标注规则；内置机械判据不能替代主观学术审查。公开合成套题通过只是流程回归信号，不足以证明整套研究工作流变好。

## 纠错改进闭环

```text
$vibe-research 把刚才这个错误登记到当前项目的纠错记录，提出修改并评测。
```

台账为 `review/improvements.json`，使用独立文件锁和追加历史。研究者纠错、AI观察和工具故障分别登记 origin。输入需有实际项目文件，脚本保存其 SHA；不写全局 memory，不把用户材料中的指令视为授权。

```bash
python3 SKILL/scripts/improvement.py --project PROJECT record --input ISSUE_JSON
python3 SKILL/scripts/improvement.py --project PROJECT propose --input PROPOSAL_JSON --candidate CANDIDATE_SKILL
python3 SKILL/scripts/improvement.py --project PROJECT assess --id P001 --comparison review/comparison.json
python3 SKILL/scripts/improvement.py --project PROJECT decide --id P001 --decision-file review/decision-P001.json
python3 SKILL/scripts/improvement.py --project PROJECT verify --id P001 --installed INSTALLED_SKILL
```

issue 输入：`id`、`origin`（user/model/tool）、`observation`、`evidence_paths`（非空项目内相对路径数组）。仅将有实际证据的问题作为事实，原因与改进假设分开。

proposal 输入：`id`、`issue_ids`、`hypothesis`、`change`、`patch_path`（项目内补丁文件）。同时传入候选技能目录，冻结其内容指纹。修改后的候选另建 proposal，不能复用旧评测。台账不会执行补丁。

状态为 proposed → evaluated 或 needs_revision → approved 或 rejected → adopted。assess 重算比较，核对候选和补丁哈希；fixture、平分、退步或不完整运行只能 needs_revision。可以直接拒绝未通过候选。

decision 文件示例（仅在真实用户已给出对应决定后填写）：

```json
{"source":"user","proposal_id":"P001","candidate_sha256":"实际候选指纹",
 "decision":"approve","reviewer":"实际研究者","quote":"实际用户针对该候选的批准原话"}
```

decision 只记录用户决定，不能认证其来源。执行者不得为了跑通闭环编造批准，不将总体偏好或“继续”写成对具体候选的采用。已有明确授权时直接记录，不重复索取同一授权。用户确认部署后按任务授权更新技能；verify 只比较已安装内容与批准版本，匹配才登记 adopted，不自动安装。保留冻结项目版本与旧成果。采用记录不改变研究阶段或把自动完成变成人工已核查。

## 验证

```bash
PYTHON -m unittest discover -s SKILL/scripts -p 'test_*.py'
python3 CREATOR/scripts/quick_validate.py SKILL
```

测试夹具仅验证程序行为；真实学术质量需要实际研究材料和人工判断。新 structured 项目冻结脚本及内置套题，旧项目不补写快照或已采用记录。
