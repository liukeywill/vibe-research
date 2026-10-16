# 项目证据格式

这些 JSON 是本工作台的项目索引，不与其他技能的同名文件 schema 自动兼容。`workspace.py` 仅验证最基本的结构和引用关系，必须配合人工/模型阅读与方法审查。

`research/sources.json` 为对象数组，每个来源拥有唯一 `id`：

```json
{
  "id": "S-001",
  "title": "实际文献或原始材料标题",
  "url": "https://实际来源网址或本地材料的file URI",
  "doi": "有则填写，无则省略",
  "access_level": "metadata",
  "metadata_status": "unverified",
  "source_type": "journal_article",
  "checked_at": "YYYY-MM-DD",
  "verification_note": "实际核验途径、日期或失败原因"
}
```

- `access_level`：`metadata`（仅题录）、`abstract`（已读摘要）、`fulltext`（已读全文或相关完整原始材料）。只检索到链接不能标全文。
- `metadata_status`：`verified` 或 `unverified`。已确认题录存在不代表已阅读，也不证明任何论断。
- `source_type` 可用 `journal_article`、`book`、`policy`、`statistics`、`archive`、`interview`、`survey_data`、`analysis_artifact`；按真实材料补充。
- 本地访谈/调查可指向项目内匿名化材料，不在此文件保存真实身份对照表、密码或联系方式。

`research/evidence.json` 为对象数组，每个记录拥有唯一 `id`：

```json
{
  "id": "E-001",
  "source_id": "S-001",
  "claim": "要核验的具体论断",
  "locator": "页码/章节/表号，或数据文件及分析输出位置",
  "support_status": "unclear",
  "claim_verification": "unverified",
  "allowed_wording": "当前证据允许的表述",
  "forbidden_wording": "更强但不受支持的推断",
  "limitations": "样本、范围、方法或访问局限"
}
```

`support_status` 是 `supports`、`contradicts` 或 `unclear`。`claim_verification` 为 `verified` 或 `unverified`，与来源题录核验分开。只有阅读相应位置并完成论断核对后才记录 verified 和支持/反驳，不能由题目推断。检索候选可保持空证据库；自检返回未就绪是正常结果，应继续获取资料。

至少一条完整、可追溯记录只能证明有材料可开始相关论证；整篇论文每个实质论断是否充分受支持须逐条审查。机械校验成功时也不能称“可投稿”。

## 原文快照和阅读范围（v2）

采集器 `capture` 会补充 `local_text`（必须在项目 research/texts/ 内）和 `content_sha256`。这是已保存文本的证据，不自动设置 fulltext。完成真实阅读后另记 `reading_scope`（完整正文/所读章节/图表范围）、`fulltext_url`、`extraction_method`、`read_at`；字段可按实际材料补充，但不能虚填。

题录里含摘要时，初次采集仍为 metadata；阅读摘要后可显式改 abstract。fulltext 表示已经接触完整正文并阅读相关证据，不保证逐字读完全部文章，具体范围以 reading_scope 为准。PDF页码、HTML标题+段落或本地文本行号应能让他人回查。下载文本与论文身份一致、表图提取准确也需要实际检查。

流水线从 read 阶段起核对已登记文本的哈希；文字变动会使 read 及后续失效。旧项目没有local_text时可继续兼容，但状态标 not_registered，不能称原文快照已验证。全部核心论断仍需要学术内容审查。

`research/search-results.json` 保存检索候选快照，来源和证据的阅读补全只改 sources/evidence，避免每读一篇又把检索阶段无故作废。新的查询会合并候选并追加 search-log，因此从 search 起重新核验相应后续成果。
