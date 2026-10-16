# 统一结构化契约

由 `scripts/contracts.py docs` 从实际 JSON Schema 生成；字段类型、必填项与嵌套结构以 schemas/ 文件为准。

所有契约使用 JSON Schema Draft 2020-12。新对象要求整数 `schema_version: 1` 与非空 `id`。来源与证据记录允许省略 schema_version，并兼容历史扩展字段；其余已定义对象默认拒绝未知字段。

标为 extensible 的参数、结果、模型输出及响应 schema 是显式扩展接口；具体模型输出还必须按请求的 response_schema 校验。

结构通过不代表语义正确、文献真实或科研质量达标。来源 ID、证据 ID、文件路径和哈希之间的关联由工作流及质量模块检查。

Python 接口：`validate(name, data) -> None`；`load_validate(name, path) -> data`。失败抛出 `ContractError(ValueError)`。

条件约束：analysis-result.status=executed 时 code 必须有路径和 SHA-256，input_files 非空、results 非空、output_rows ≥ 1；human-decision.status=answered 时 answer、answered_at、actor 均非空；requested 时 answer 与 answered_at 必须为 null。

## analysis-result

文件：`schemas/analysis-result.schema.json`。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 是 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `status` | enum: executed, planned, not_applicable | 是 | — |
| `reason` | string | 是 | minLength=1; pattern=\S |
| `input_files` | array<file> | 是 | minItems=0 |
| `input_files[].path` | string | 是 | minLength=1; pattern=\S |
| `input_files[].sha256` | string | 是 | pattern=^[a-f0-9]{64}$ |
| `code` | file / null | 是 | — |
| `code.path` | string | 是 | minLength=1; pattern=\S |
| `code.sha256` | string | 是 | pattern=^[a-f0-9]{64}$ |
| `environment` | object | 是 | — |
| `environment.python` | string | 是 | minLength=1; pattern=\S |
| `environment.platform` | string | 是 | minLength=1; pattern=\S |
| `environment.packages` | object (extensible) | 是 | — |
| `method` | string | 是 | minLength=1; pattern=\S |
| `parameters` | object (extensible) | 是 | — |
| `sample` | object | 是 | — |
| `sample.input_rows` | integer | 是 | minimum=0 |
| `sample.output_rows` | integer | 是 | minimum=0 |
| `sample.dropped_rows` | integer | 是 | minimum=0 |
| `results` | object (extensible) | 是 | — |
| `limitations` | array<string> | 是 | minItems=0 |
| `artifacts` | array<file> | 否 | minItems=0 |
| `artifacts[].path` | string | 是 | minLength=1; pattern=\S |
| `artifacts[].sha256` | string | 是 | pattern=^[a-f0-9]{64}$ |
| `reproducibility` | object | 否 | — |
| `reproducibility.status` | enum: verified, failed, not_evaluated | 是 | — |
| `reproducibility.max_abs_difference` | number / null | 是 | — |

## cleaning-log

文件：`schemas/cleaning-log.schema.json`。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 是 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `record_number_definition` | string | 是 | minLength=1; pattern=\S |
| `input_rows` | integer | 是 | minimum=0 |
| `output_rows` | integer | 是 | minimum=0 |
| `rules` | array<object> | 是 | minItems=0 |
| `rules[].rule` | enum: exact_duplicates, missing_selected_numeric | 是 | — |
| `rules[].policy` | enum: drop, keep, error, complete_case | 是 | — |
| `rules[].before` | integer | 是 | minimum=0 |
| `rules[].after` | integer | 是 | minimum=0 |
| `rules[].affected_records` | array<integer> | 是 | minItems=0 |
| `rules[].details` | array<object> | 否 | minItems=0 |
| `rules[].details[].source_record` | integer | 是 | minimum=1 |
| `rules[].details[].columns` | array<string> | 是 | minItems=0 |
| `kept_source_records` | array<integer> | 是 | minItems=0 |
| `selected_columns` | array<string> | 是 | minItems=1 |

## dataset-spec

文件：`schemas/dataset-spec.schema.json`。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 是 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `path` | string | 是 | minLength=1; pattern=\S |
| `sha256` | string | 是 | pattern=^[a-f0-9]{64}$ |
| `source_url` | string (uri) | 是 | minLength=1 |
| `license` | string | 是 | minLength=1; pattern=\S |
| `unit_of_analysis` | string | 是 | minLength=1; pattern=\S |
| `columns` | array<object> | 是 | minItems=1 |
| `columns[].name` | string | 是 | minLength=1; pattern=\S |
| `columns[].type` | enum: number, integer, string, boolean | 是 | — |
| `columns[].required` | boolean | 是 | — |
| `columns[].description` | string | 是 | minLength=1; pattern=\S |
| `missing_values` | array<string / null> | 是 | minItems=0 |
| `cleaning` | object | 是 | — |
| `cleaning.drop_exact_duplicates` | boolean | 是 | — |
| `cleaning.missing_policy` | enum: complete_case, error | 是 | — |
| `delimiter` | string | 否 | minLength=1 |

## evidence-record

文件：`schemas/evidence-record.schema.json`。

接受单条对象或对象数组。下表描述单条对象。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 否 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `source_id` | string | 是 | minLength=1; pattern=\S |
| `claim` | string | 是 | minLength=1; pattern=\S |
| `locator` | string | 是 | minLength=1; pattern=\S |
| `support_status` | enum: supports, contradicts, unclear | 是 | — |
| `claim_verification` | enum: verified, unverified | 是 | — |
| `allowed_wording` | string | 否 | — |
| `forbidden_wording` | string | 否 | — |
| `limitations` | string / array<string> | 否 | — |
| `quote` | string | 否 | — |
| `verified_at` | string | 否 | minLength=1; pattern=\S |
| `verifier` | string | 否 | minLength=1; pattern=\S |
| `extensions` | object (extensible) | 否 | — |
| `reviewer` | string | 否 | minLength=1; pattern=\S |
| `reviewed_at` | string (date-time) | 否 | — |

## human-decision

文件：`schemas/human-decision.schema.json`。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 是 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `stage` | string | 是 | minLength=1; pattern=\S |
| `status` | enum: requested, answered, cancelled | 是 | — |
| `question` | string | 是 | minLength=1; pattern=\S |
| `options` | array<string> | 是 | minItems=0 |
| `requested_at` | string (date-time) | 是 | — |
| `answer` | string / null | 是 | — |
| `answered_at` | string (date-time) / null | 是 | — |
| `actor` | string / null | 是 | — |

## manuscript

文件：`schemas/manuscript.schema.json`。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | value = 1 | 是 | — |
| `id` | string | 是 | minLength=1 |
| `title` | string | 是 | minLength=1 |
| `paper_type` | enum: integrative_review, conceptual, empirical | 是 | — |
| `abstract` | string | 是 | minLength=150 |
| `keywords` | array<string> | 是 | minItems=3 |
| `sections` | array<object> | 是 | minItems=5 |
| `sections[].id` | string | 是 | — |
| `sections[].heading` | string | 是 | — |
| `sections[].role` | enum: introduction, methods, findings, discussion, conclusion | 是 | — |
| `sections[].paragraphs` | array<object> | 是 | minItems=1 |
| `sections[].paragraphs[].id` | string | 是 | minLength=1 |
| `sections[].paragraphs[].text` | string | 是 | minLength=30 |
| `sections[].paragraphs[].stance` | enum: source_fact, interpretation, proposal | 是 | — |
| `sections[].paragraphs[].source_ids` | array<string> | 是 | — |
| `sections[].paragraphs[].claim_ids` | array<string> | 是 | — |
| `references` | array<object> | 是 | minItems=1 |
| `references[].source_id` | string | 是 | — |
| `references[].citation` | string | 是 | minLength=10 |
| `references[].url` | string (uri) | 是 | — |

## model-request

文件：`schemas/model-request.schema.json`。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 是 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `task` | string | 是 | minLength=1; pattern=\S |
| `prompt` | string | 是 | minLength=1; pattern=\S |
| `context` | array<object> | 是 | minItems=0 |
| `context[].role` | enum: system, user, assistant | 是 | — |
| `context[].content` | string | 是 | minLength=1; pattern=\S |
| `response_schema` | object (extensible) | 是 | — |
| `model` | string | 是 | minLength=1; pattern=\S |
| `parameters` | object (extensible) | 是 | — |
| `input_files` | array<file> | 否 | minItems=0 |
| `input_files[].path` | string | 是 | minLength=1; pattern=\S |
| `input_files[].sha256` | string | 是 | pattern=^[a-f0-9]{64}$ |

## model-response

文件：`schemas/model-response.schema.json`。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 是 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `request_id` | string | 是 | minLength=1; pattern=\S |
| `backend` | string | 是 | minLength=1; pattern=\S |
| `model` | string | 是 | minLength=1; pattern=\S |
| `status` | enum: completed, needs_execution | 是 | — |
| `output` | object (extensible) | 是 | — |
| `usage` | object | 是 | — |
| `usage.input_tokens` | integer / null | 否 | — |
| `usage.output_tokens` | integer / null | 否 | — |
| `provenance` | object | 是 | — |
| `provenance.created_at` | string (date-time) | 是 | — |
| `provenance.backend_version` | string | 是 | minLength=1; pattern=\S |
| `provenance.execution_mode` | enum: codex-handoff, command | 否 | — |
| `provenance.request_sha256` | string | 否 | pattern=^[a-f0-9]{64}$ |
| `provenance.command_sha256` | string | 否 | pattern=^[a-f0-9]{64}$ |
| `provenance.request_file` | string | 否 | minLength=1; pattern=\S |
| `provenance.response_file` | string | 否 | minLength=1; pattern=\S |

## pipeline-policy

文件：`schemas/pipeline-policy.schema.json`。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 是 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `max_failures` | integer | 是 | minimum=1 |
| `backoff_seconds` | number | 是 | minimum=0 |
| `max_backoff_seconds` | number | 是 | minimum=0 |

## project-spec

文件：`schemas/project-spec.schema.json`。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 是 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `topic` | string | 是 | minLength=1; pattern=\S |
| `mode` | enum: auto, review, empirical, conceptual | 是 | — |
| `language` | string | 是 | minLength=1; pattern=\S |
| `created_at` | string (date-time) | 是 | — |
| `question` | string | 是 | minLength=1; pattern=\S |
| `deliverable` | string | 是 | minLength=1; pattern=\S |
| `scope` | string | 否 | — |
| `constraints` | array<string> | 否 | minItems=0 |
| `input_files` | array<file> | 否 | minItems=0 |
| `input_files[].path` | string | 是 | minLength=1; pattern=\S |
| `input_files[].sha256` | string | 是 | pattern=^[a-f0-9]{64}$ |

## quality-policy

文件：`schemas/quality-policy.schema.json`。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 是 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `metrics` | array<object> | 是 | minItems=1 |
| `metrics[].id` | enum: citation_resolution_rate, verified_claim_coverage, screening_decision_coverage, fulltext_ratio, schema_pass_rate, analysis_reproducibility, screening_precision, screening_recall | 是 | — |
| `metrics[].min` | number | 是 | — |
| `metrics[].severity` | enum: error, warning | 是 | — |
| `metrics[].required` | boolean | 是 | — |

## quality-report

文件：`schemas/quality-report.schema.json`。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 是 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `evaluated_at` | string (date-time) | 是 | — |
| `metrics` | array<object> | 是 | minItems=0 |
| `metrics[].id` | string | 是 | minLength=1; pattern=\S |
| `metrics[].name` | string | 是 | minLength=1; pattern=\S |
| `metrics[].value` | number / null | 是 | — |
| `metrics[].numerator` | integer / null | 是 | — |
| `metrics[].denominator` | integer / null | 是 | — |
| `metrics[].threshold` | number / null | 是 | — |
| `metrics[].status` | enum: pass, fail, not_measured, not_applicable | 是 | — |
| `metrics[].severity` | enum: error, warning, info | 是 | — |
| `metrics[].reason` | string | 是 | minLength=1; pattern=\S |
| `overall_status` | enum: pass, fail, incomplete | 是 | — |
| `limitations` | array<string> | 是 | minItems=0 |
| `policy_sha256` | string | 否 | pattern=^[a-f0-9]{64}$ |
| `evaluation_config` | object | 否 | — |
| `evaluation_config.policy_path` | nonemptyString / null | 是 | — |
| `evaluation_config.benchmark_path` | nonemptyString / null | 是 | — |
| `evaluation_inputs` | array<file> | 否 | — |
| `evaluation_inputs[].path` | string | 是 | minLength=1; pattern=\S |
| `evaluation_inputs[].sha256` | string | 是 | pattern=^[a-f0-9]{64}$ |

## research-report

文件：`schemas/research-report.schema.json`。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 是 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `title` | string | 是 | minLength=1; pattern=\S |
| `sections` | array<object> | 是 | minItems=1 |
| `sections[].id` | string | 是 | minLength=1; pattern=\S |
| `sections[].heading` | string | 是 | minLength=1; pattern=\S |
| `sections[].text` | string | 是 | minLength=1; pattern=\S |
| `sections[].claim_ids` | array<string> | 是 | minItems=0 |
| `claims` | array<object> | 是 | minItems=0 |
| `claims[].id` | string | 是 | minLength=1; pattern=\S |
| `claims[].text` | string | 是 | minLength=1; pattern=\S |
| `claims[].evidence_ids` | array<string> | 是 | minItems=0 |
| `claims[].analysis_ids` | array<string> | 是 | minItems=0 |
| `claims[].status` | enum: supported, hypothesis, unsupported | 是 | — |
| `references` | array<object> | 是 | minItems=0 |
| `references[].source_id` | string | 是 | minLength=1; pattern=\S |
| `references[].title` | string | 是 | minLength=1; pattern=\S |
| `references[].url` | string (uri) | 是 | minLength=1 |
| `limitations` | array<string> | 是 | minItems=0 |

## screening

文件：`schemas/screening.schema.json`。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 是 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `criteria` | object | 是 | — |
| `criteria.include_terms` | array<string> | 是 | minItems=0 |
| `criteria.exclude_terms` | array<string> | 是 | minItems=0 |
| `criteria.year_min` | integer / null | 是 | — |
| `criteria.year_max` | integer / null | 是 | — |
| `criteria.require_abstract` | boolean | 是 | — |
| `decisions` | array<object> | 是 | minItems=0 |
| `decisions[].source_id` | string | 是 | minLength=1; pattern=\S |
| `decisions[].decision` | enum: include, exclude, uncertain | 是 | — |
| `decisions[].reason` | string | 是 | minLength=1; pattern=\S |
| `decisions[].rule_ids` | array<string> | 是 | minItems=0 |
| `decisions[].reviewer` | string | 是 | minLength=1; pattern=\S |
| `decisions[].reviewed_at` | string (date-time) | 是 | — |
| `dedup` | object | 是 | — |
| `dedup.exact_duplicates` | array<object> | 是 | minItems=0 |
| `dedup.exact_duplicates[].kept_id` | string | 是 | minLength=1; pattern=\S |
| `dedup.exact_duplicates[].removed_id` | string | 是 | minLength=1; pattern=\S |
| `dedup.exact_duplicates[].reason` | string | 是 | minLength=1; pattern=\S |
| `dedup.possible_duplicates` | array<object> | 是 | minItems=0 |
| `dedup.possible_duplicates[].source_ids` | array<string> | 是 | minItems=2 |
| `dedup.possible_duplicates[].similarity` | number | 是 | minimum=0; maximum=1 |
| `dedup.possible_duplicates[].reason` | string | 是 | minLength=1; pattern=\S |

## screening-benchmark

文件：`schemas/screening-benchmark.schema.json`。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 是 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `labels` | array<object> | 是 | minItems=1 |
| `labels[].source_id` | string | 是 | minLength=1; pattern=\S |
| `labels[].include` | boolean | 是 | — |
| `labeler` | string | 是 | minLength=1; pattern=\S |
| `labelled_at` | string (date-time) | 是 | — |
| `independent` | boolean | 是 | — |

## search-query

文件：`schemas/search-query.schema.json`。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 是 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `query` | string | 是 | minLength=1; pattern=\S |
| `providers` | array<string> | 是 | minItems=1 |
| `limit` | integer | 是 | minimum=1; maximum=100 |
| `filters` | object | 是 | — |
| `filters.year_min` | integer / null | 是 | — |
| `filters.year_max` | integer / null | 是 | — |
| `provider_queries` | object (extensible) | 否 | — |

## source-record

文件：`schemas/source-record.schema.json`。

接受单条对象或对象数组。下表描述单条对象。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 否 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `title` | string | 是 | minLength=1; pattern=\S |
| `url` | string (uri) | 是 | minLength=1 |
| `access_level` | enum: metadata, abstract, fulltext | 是 | — |
| `metadata_status` | enum: verified, unverified | 是 | — |
| `doi` | string | 否 | minLength=1; pattern=\S |
| `authors` | array<string> | 否 | minItems=0 |
| `year` | integer / null | 否 | — |
| `provider` | string | 否 | minLength=1; pattern=\S |
| `abstract` | string | 否 | — |
| `verification_scope` | string | 否 | — |
| `eric_id` | string | 否 | minLength=1; pattern=\S |
| `retrieved_at` | string | 否 | minLength=1; pattern=\S |
| `raw_response` | string | 否 | minLength=1; pattern=\S |
| `local_text` | string | 否 | minLength=1; pattern=\S |
| `content_sha256` | string | 否 | pattern=^[a-f0-9]{64}$ |
| `fulltext_url` | string (uri) | 否 | minLength=1 |
| `license` | string | 否 | — |
| `license_url` | string (uri) | 否 | minLength=1 |
| `read_at` | string | 否 | minLength=1; pattern=\S |
| `read_scope` | string | 否 | — |
| `read_status` | string | 否 | minLength=1; pattern=\S |
| `reading_note` | string | 否 | — |
| `source_type` | string | 否 | minLength=1; pattern=\S |
| `extensions` | object (extensible) | 否 | — |

## stage-task

文件：`schemas/stage-task.schema.json`。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 是 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `stage` | enum: scope, search, read, synthesize, design, analyze, package, review | 是 | — |
| `status` | enum: pending, succeeded, failed, blocked, stale, running | 是 | — |
| `runnable` | boolean | 是 | — |
| `dependencies` | array<enum: scope, search, read, synthesize, design, analyze, package, review> | 是 | minItems=0 |
| `skills` | array<string> | 是 | minItems=0 |
| `required_artifacts` | array<string> | 是 | minItems=0 |
| `inputs` | array<string> | 是 | minItems=0 |
| `reason` | string | 是 | — |
| `action` | string | 是 | minLength=1; pattern=\S |
| `retry` | object | 是 | — |
| `retry.attempt` | integer | 是 | minimum=0 |
| `retry.max_attempts` | integer | 是 | minimum=1 |
| `retry.next_retry_at` | string (date-time) / null | 是 | — |
| `human_decision_ids` | array<string> | 是 | minItems=0 |

## study-design

文件：`schemas/study-design.schema.json`。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 是 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `question` | string | 是 | minLength=1; pattern=\S |
| `hypotheses` | array<object> | 是 | minItems=0 |
| `hypotheses[].id` | string | 是 | minLength=1; pattern=\S |
| `hypotheses[].statement` | string | 是 | minLength=1; pattern=\S |
| `hypotheses[].evidence_ids` | array<string> | 是 | minItems=0 |
| `hypotheses[].status` | enum: proposed, tested, rejected | 是 | — |
| `method` | string | 是 | minLength=1; pattern=\S |
| `design` | string | 是 | minLength=1; pattern=\S |
| `variables` | array<object> | 是 | minItems=0 |
| `variables[].name` | string | 是 | minLength=1; pattern=\S |
| `variables[].role` | string | 是 | minLength=1; pattern=\S |
| `variables[].type` | string | 是 | minLength=1; pattern=\S |
| `variables[].description` | string | 是 | minLength=1; pattern=\S |
| `analysis_plan` | string | 是 | minLength=1; pattern=\S |
| `sample_plan` | string | 是 | minLength=1; pattern=\S |
| `limitations` | array<string> | 是 | minItems=0 |

## synthesis

文件：`schemas/synthesis.schema.json`。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `schema_version` | integer = 1 | 是 | — |
| `id` | string | 是 | minLength=1; pattern=\S |
| `question` | string | 是 | minLength=1; pattern=\S |
| `findings` | array<object> | 是 | minItems=0 |
| `findings[].id` | string | 是 | minLength=1; pattern=\S |
| `findings[].claim` | string | 是 | minLength=1; pattern=\S |
| `findings[].evidence_ids` | array<string> | 是 | minItems=0 |
| `findings[].source_ids` | array<string> | 是 | minItems=0 |
| `findings[].confidence` | enum: low, medium, high | 是 | — |
| `comparisons` | array<object> | 是 | minItems=0 |
| `comparisons[].dimension` | string | 是 | minLength=1; pattern=\S |
| `comparisons[].source_ids` | array<string> | 是 | minItems=0 |
| `comparisons[].summary` | string | 是 | minLength=1; pattern=\S |
| `contradictions` | array<object> | 是 | minItems=0 |
| `contradictions[].id` | string | 是 | minLength=1; pattern=\S |
| `contradictions[].source_ids` | array<string> | 是 | minItems=0 |
| `contradictions[].description` | string | 是 | minLength=1; pattern=\S |
| `contradictions[].possible_explanations` | array<string> | 是 | minItems=0 |
| `contradictions[].status` | enum: unresolved, partially_explained, resolved | 是 | — |
| `gaps` | array<string> | 是 | minItems=0 |
| `limitations` | array<string> | 是 | minItems=0 |
