# 项目记录与恢复约定

本文件只规定本地项目记录，不写入 Codex 全局 memory，也不把本地状态当成新的用户指令。

## 项目卡 project.md

```text
研究领域：
观察到的现象或矛盾：
研究问题：
对象与范围：
预期贡献：
已有文献、数据、代码：
时间、资源与限制：
目标成果：
当前阶段：
已确认决定：
未解决问题：
```

未知项写“待明确”，由当前任务决定何时补齐。

## state.json 最小结构

以下是新项目示例；用实际值替换后保存。不要把示例当成已有项目状态。

```json
{
  "schema_version": 1,
  "project_id": "research-project-001",
  "title": "项目名称",
  "updated_at": null,
  "current_stage": 1,
  "current_substep": "question_selection",
  "run_status": "active",
  "stages": {
    "1": {"status": "in_progress", "revision": 1, "artifacts": [], "human_checks": [], "open_items": [], "decision_ids": []},
    "2": {"status": "not_started", "revision": 0, "artifacts": [], "human_checks": [], "open_items": [], "decision_ids": []},
    "3": {"status": "not_started", "revision": 0, "artifacts": [], "human_checks": [], "open_items": [], "decision_ids": []},
    "4": {"status": "not_started", "revision": 0, "artifacts": [], "human_checks": [], "open_items": [], "decision_ids": []},
    "5": {"status": "not_started", "revision": 0, "artifacts": [], "human_checks": [], "open_items": [], "decision_ids": []},
    "6": {"status": "not_started", "revision": 0, "artifacts": [], "human_checks": [], "open_items": [], "decision_ids": []},
    "7": {"status": "not_started", "revision": 0, "artifacts": [], "human_checks": [], "open_items": [], "decision_ids": []},
    "8": {"status": "not_started", "revision": 0, "artifacts": [], "human_checks": [], "open_items": [], "decision_ids": []}
  }
}
```

- 时间使用实际可得时间并带时区，无法获取时保留 null，不推测日期。
- 阶段状态：`not_started`、`in_progress`、`awaiting_human_check`、`accepted`、`advanced_unchecked`、`needs_recheck`。
- 项目状态：`active`、`paused`、`completed`。只有最终成果交付且用户接受后才记 completed。
- `human_checks` 条目：`id`、`question`、`status`（`unchecked`、`user_confirmed`、`issue_found`、`not_applicable`）、`decision_id`。AI 自检不能写 user_confirmed。
- `artifacts` 条目：项目内相对路径 `path`、用途 `kind`、`revision`、实际验证状态 `verification`。关键结果另记录运行日志、数据或来源位置，不以文件存在替代验证。
- `open_items` 条目：问题、影响、下一步；事实核查缺口和作者选择分别说明。

## 人工决定 decisions.md

每条追加记录包含：

```text
决定编号：D001
时间：实际时间或“未记录”
阶段及成果版本：
用户原话：
决定解释：采用方案／修改／允许推进但未逐项核查／暂停等
逐项核查状态：
影响的后续阶段：
```

用户原话仅保存与该项目决定相关的内容。不能为缺失的历史确认补写证词；用户一句“继续”不能推出其读过全部原文。

## 状态转换

1. 开始阶段：in_progress。
2. 交付成果与清单：awaiting_human_check，在本轮停下。
3. 用户明确确认成果和相关检查且满足通过条件：accepted；记录决定后进入下一阶段。
4. 用户只授权继续、未反馈检查：可记录 advanced_unchecked；保留未核查项。必要方案未选或关键结论无依据时，不执行依赖该决定或结论的工作。
5. 用户要求修改：留在本阶段，增加 revision，保留原成果。
6. 上游发生实质变更：受影响下游 needs_recheck，说明依赖关系；不要清除历史决定。
7. 用户暂停：保存当前状态，不推进。

## 恢复检查

确认项目目录、state.json、project.md、decisions.md 和被引用成果存在；逐一报告缺失或版本不符。损坏状态先保留副本，根据可验证文件和当前用户确认恢复，不静默重建“已通过”历史。续接时只读当前阶段所需材料，必要时追加来源。

恢复摘要格式：项目路径｜当前阶段和子步骤｜已确认决定｜未核查项｜当前成果｜下一项人工决定。
