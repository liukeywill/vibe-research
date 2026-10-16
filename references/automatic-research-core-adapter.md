# Research Core 在自动成稿模式中的应用

Research Core 只统一研究语义，不接管 pipeline、schema、自动重试、人工请求或交付验收。已有八阶段及产物路径不变。

| 共同对象 | Auto Paper 的现有契约 |
|---|---|
| 研究问题与设计 | project-spec.json、study-design.json、study-plan.md |
| 来源与纳排 | search-query、search-results、screening、sources |
| 证据及核验 | evidence.json 的 source_id、locator 和核验字段 |
| 主张与论文 | report.json、manuscript.json 的 claim/evidence 对应及正文 |
| 执行、版本与复现 | pipeline-state、输入输出 SHA、engine-manifest、runtime-snapshot |
| 审查与人工决定 | review/audit.md；仅实际需要时使用现有 human_decisions |

新 structured 项目由 provenance.capture 将 `shared/research-core/` 及 `shared/research-core.lock.json` 与代码、schema 一起冻结到 runtime-snapshot。后续从项目快照读取相应模块；manifest 会检查其哈希。缺少随包模块或锁文件、内容与清单不符时拒绝初始化，不通过联网或另装 Skill 静默替代。

已有 engine-manifest 的项目继续使用原快照；若旧 manifest 不包含模块，就按原规则执行并注明未冻结 Research Core，不在原项目补写 adopted/pass。确需切换版本时建立承接材料的新项目，记录版本变化和待复核范围。legacy 项目沿用其原 profile，shared 规范不自动改变其验收条件。

共享规范中的最小验证按研究类型应用：实证设计检查关键可行性与数据条件，理论／综述检查推理、反例与材料覆盖；没有实际测试就标记未执行。无需为套流程新建“pilot”阶段或凭空开展实验。

自动模式内部建立和审查主张—证据关系并连续起草、自审修订，不等待 Vibe Research 式论证表批准。只有用户要求或实际授权条件触发时进入人工交接；助手审查不能登记为人工确认。技术 complete、结构校验与共同规范都不保证学术质量或可发表性。
