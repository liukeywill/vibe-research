# 数据整理、分析与质量门槛

## 职责与适用边界

`analyze_data.py` 只处理用户已选择并放入项目内的 CSV；不扫描个人文件、不下载数据、不把模拟数据当作实测数据。当前可执行分析适配器是含截距的数值 OLS，报告 HC3 协方差、t 参考分布和 95% 置信区间；它估计观察数据中的条件关联。类别变量编码、聚类、重复测量、因果识别、定性访谈需要相应技能和研究者设计，不能默认塞入这个回归。

数据清洗前必须有 `data/dataset-spec.json`，通过 `dataset-spec.schema.json` 校验；明确原始 CSV 的相对路径、SHA-256、来源、许可、观察单位、字段类型和含义、缺失标记、重复政策。`delimiter` 缺省为逗号，可设为分号。`drop_exact_duplicates=false` 保留完全相同的记录并报告，避免把不同但同值的受访者误删；`true` 仅按完整 CSV 行去重，不是按入模列去重。原始 CSV 不变。

```bash
PYTHON /absolute/path/vibe-research/scripts/analyze_data.py \
  --project PROJECT --spec data/dataset-spec.json \
  --outcome SCORE --predictors predictor1 predictor2
```

`PYTHON` 使用安装了 `numpy pandas scipy statsmodels jsonschema` 的隔离解释器。本地已配置路径见工作台使用说明。

## 清洗和分析交互

1. 项目锁 `.pipeline.lock` 防止并发写入；项目根及子路径拒绝符号链接和越界路径。
2. schema 校验后核对原始数据 SHA；字段必须已声明，必需列缺失直接失败。
3. 仅对显式选定的数值结局与预测变量进行值校验；其他声明字段只是数据字典，当前脚本不声称做了整表语义质量审计。非数值、无穷和未列为缺失标记的 NaN 都失败，不静默强转为缺失。
4. 按完整行处理重复，再对入模列应用 `complete_case` 或 `error` 缺失政策。日志包含规则、前后行数、受影响原记录编号及保留编号。编号指 CSV 逻辑记录，标题为 1；含引号换行时不等于物理文本行号。
5. 检查设计矩阵满秩、样本数大于参数数、结局非恒定，然后拟合 OLS。HC3 不解决聚类、混杂或非线性；条件数、最大杠杆和残差 RMSE 仅为数值诊断，不自动认证假设。
6. 冻结原始 CSV 和数据字典副本，保存 `data/cleaned.csv`、`data/cleaning-log.json`、环境版本、`analysis-code/reproduce.py`、`research/analysis-result.json` 和 `research/analysis.md`。
7. 独立子进程执行所生成的复现代码，检查清洗结果及系数、标准误、置信区间、p 值和 R²，绝对容差 `1e-10`。代码只依赖科学 Python 包，不依赖工作台安装目录。

所有 JSON 使用 `schema_version=1` 和 `id`，字段规范以 `schemas/` 中的 JSON Schema 为准。分析结果区分 `executed/planned/not_applicable`；后两类不得伪装成已做实证检验。输入、数据字典、代码、清洗日志、环境和复现输出保留 SHA 或版本。默认分析不搜索最佳显著模型、不自动排除离群值、不通过检验筛选假设。

## 质量指标

执行 `quality.py --project PROJECT [--policy quality-policy.json] [--benchmark benchmark.json]`。输出 `review/quality-report.json`；退出码 0 表示配置门槛通过，1 表示失败或未满足必测项，2 表示配置或运行错误。报告每项的分子、分母、值、阈值、状态与原因。分母为 0 时值为 `null`，不把没有观测当成 100%。

| 指标 | 分子 / 分母与边界 |
| --- | --- |
| citation_resolution_rate | 已解析的报告引用和引用关系 / 报告参考文献、章节到论断、论断到证据或分析的全部关系。参考文献需匹配已核验来源的题名和 URL；这是映射登记检查，不是重新联网检测 URL 或 DOI。 |
| verified_claim_coverage | 所有证据均有已登记全文来源、核验者/时间且核验通过、或链接已复现分析的支持性论断 / 除显式假设外的全部报告论断。只度量审阅登记覆盖；无法自动证明句子的含义确实得到支持。 |
| screening_decision_coverage | 有人员、时间、理由的纳入或排除决定 / 全部注册来源 ID。`uncertain` 仍视为未解决。 |
| fulltext_ratio | 标记为全文的来源 / 全部注册来源。不会因为是全文就视为高质量，也不默认要求全为全文。 |
| schema_pass_rate | 通过校验的必需结构文件 / 固定清单的全部文件。缺失也计入分母；来源、证据数组须逐项通过。实际分析时额外要求数据字典和清洗日志。 |
| analysis_reproducibility | 当前输入/代码/成果哈希与独立重算一致为 1，否则为 0。检查实际文件和重新计算结果，不只相信先前保存的 `verified` 标签。planned/not_applicable 为不适用。 |
| screening_precision | 独立标注子集中真正应纳入且被纳入 / 该子集中系统纳入数。 |
| screening_recall | 独立标注子集中真正应纳入且被纳入 / 该子集中标注应纳入数。不能外推为整个学术文献世界的召回率。 |

最后两项要求符合 `screening-benchmark` 契约的独立人工标签；不提供时保留 `null/not_measured`。测试夹具标签只用于程序测试，不能报告成实际科研准确率。非独立标签不可作为独立准确率评测。

默认硬性门槛是 schema、引用映射、核心论断核验登记、筛选决定覆盖均为 1。数据分析若执行则复现失败是 error；计划型分析不要求伪造数据。`fulltext_ratio` 无默认 100% 要求。用户可在 `quality-policy.json` 中为可选指标配置阈值和 `warning/error`；核心正确性门槛不能被削弱。未知指标、重复指标和超出 0–1 的阈值均拒绝。

`status=fail,severity=warning` 不阻断总体通过，但保留警告；error 失败使 `overall_status=fail`。必测但未测使整体 `incomplete`；可选 precision/recall 未测不阻断其他已满足门槛，仍必须披露“未评估”。通过不等于可投稿、理论正确或因果成立。

## 程序接口和重算

`analyze(project, spec_path, outcome, predictors)` 持有项目锁并返回分析结果。

`quality.evaluate(project, policy_path=None, benchmark_path=None, acquire_lock=True, write_report=True)` 返回质量报告。编排器已持有锁时可显式传 `acquire_lock=False`；`write_report=False` 只计算不写默认策略或报告。只有协调器使用免锁入口，外部命令默认加锁。验收时应重算质量，不能仅信任可编辑的 pass 字段。

当前统计后端支持面有限是明确接口边界。扩展新模型时须同时实现可执行拟合、统一 `analysis-result`、输入和代码收据、复现评估及回归测试；仅修改 `method` 字符串不会自动获得可复现能力。
