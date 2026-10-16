# 可替换数据源与模型接口

本地版本 3；2026-10-06。字段的机器可执行定义在 `schemas/`，字段、类型、必填项汇总由 `contracts.py` 生成。这里说明边界、扩展点和实际执行语义。

## 共同约定

- 使用 UTF-8 JSON，`schema_version: 1`。输入不自动修复、缺字段不自动补造；NaN、Infinity 被拒绝。
- 使用科研工作台隔离 Python 环境。`jsonschema` 是契约校验必需依赖；缺失时明确报错，不降级为“已校验”。
- 数据源产出候选元数据；阅读、纳排判断和论断核验属于后续模块。来源可信度与返回格式正确是两回事。
- 执行模型提供内容；调度器拥有项目状态和成果的最终写入/验收权，模型不能凭“已完成”文字使阶段通过。

## 数据源接口

Python 协议：

```python
class SourceProvider(Protocol):
    name: str
    def search(self, query: str, limit: int) -> dict: ...
# 返回 {"records": list[dict], "raw": bytes, "url": str}
```

输入对应 `search-query.schema.json`：

```json
{
  "schema_version": 1,
  "id": "Q001",
  "query": "adult learning feedback",
  "providers": ["crossref", "eric"],
  "limit": 20,
  "filters": {"year_min": 2020, "year_max": null},
  "provider_queries": {"eric": "adult learning AND feedback"}
}
```

`provider_queries` 是可选的逐源查询语法，键必须属于已选择的源。`limit` 为每源最多检索条数（1–100），不是总文献数量。年份筛选作用于取回的候选；缺年份项在存在年份边界时排除并记录 `year_missing`。此版不自动补页，因此年份筛选后可能少于 `limit`，不能宣称完整检索。纳排标准与近似去重由独立筛选模块处理。

标准来源行满足 `source-record.schema.json`：必填 `id/title/url/access_level/metadata_status`；DOI 可缺失。Crossref、ERIC 的 `metadata_status: verified` 只表示取回规范 API 元数据。`local-json` 导入一律设为元数据候选、未核验，即使导入文件写了 fulltext/verified，也不自动升级。

调用：

```bash
"$WORKBENCH_PYTHON" "$SKILL/scripts/collect_sources.py" search \
  --project "$PROJECT" --request "$PROJECT/research/search-query.json" --max-attempts 3
```

兼容旧入口：`search --project ... --query "主题" --providers crossref,eric --limit 5`。切换到本地导入：

```bash
"$WORKBENCH_PYTHON" "$SKILL/scripts/collect_sources.py" search \
  --project "$PROJECT" --query '*' --providers local-json --local-json /absolute/path/sources.json
```

本地文件是规范化来源对象数组；`*` 导入全部，其他查询按标题/摘要的全部词项匹配。单次输入/响应最多 8 MiB。

`providers.make_provider(name, options)` 创建适配器；新源实现上述协议后，调用 `register_provider("new-source", Factory)` 注册，再把名称交给 `collect_sources.search`。注册不覆盖已有名称，不从检索结果或配置中的远程代码自动加载插件。调用者负责显式可信的模块导入。

`run_search` 统一做输出契约验证和有限重试：默认 1 次，可配置 1–5 次；仅超时、HTTP 429、HTTP 5xx 重试。HTTP 4xx（429 除外）、坏 JSON、schema 错误不重试。指数退避为 0.25、0.5、1、2 秒，单次上限 2 秒；每次 attempt 的序号、结果、错误分类、下一次延迟均保存。未实现跨进程配额协调或无限重试。

每次检索保存原始 API 响应与逐源结果，失败返回 `failed`（CLI 退出 1），部分源成功返回 `partial`。全部失败保留旧结果；部分成功保留有效候选。结构化请求按内容哈希存入 `research/search-requests/`。来源合并保留已有 ID、阅读状态和用户字段；默认精确去重依据 DOI、ERIC ID。

## 模型接口

Python 协议：`ModelBackend.generate(request: dict) -> dict`。

`model-request.schema.json`：

```json
{
  "schema_version": 1,
  "id": "M001",
  "task": "scope",
  "prompt": "根据上下文输出可检验的研究问题。",
  "context": [{"role": "user", "content": "研究对象为成人学习者。"}],
  "response_schema": {
    "type": "object",
    "properties": {"question": {"type": "string", "minLength": 1}},
    "required": ["question"],
    "additionalProperties": false
  },
  "model": "current-session",
  "parameters": {}
}
```

`context` 的 role 仅为 system/user/assistant。`response_schema` 是本次输出的 JSON Schema，允许内嵌 `$defs`，引用仅允许 `#` 本地片段；不会按模型提供的远程地址下载 schema。`parameters` 是后端扩展边界，含义由显式配置的 wrapper 定义。

`model-response.schema.json`：

```json
{
  "schema_version": 1,
  "id": "M001-response",
  "request_id": "M001",
  "backend": "codex",
  "model": "current-session",
  "status": "needs_execution",
  "output": {},
  "usage": {"input_tokens": null, "output_tokens": null},
  "provenance": {
    "created_at": "2026-10-06T00:00:00+00:00",
    "backend_version": "1.0",
    "execution_mode": "codex-handoff",
    "request_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "request_file": "model-io/M001.request.json",
    "response_file": "model-io/M001.response.json"
  }
}
```

示例中的全零哈希只是字段展示，真实接口计算请求的规范化 SHA-256，读取回执时核对。未知 token 使用 null，不以 0 冒充测量。`completed` 的 output 必须同时通过模型响应契约和本次 `response_schema`，其结构正确仍不证明事实正确。

### 当前 Codex 后端

配置 `{"backend":"codex","project":"/absolute/project"}`。`generate` 将请求保存到项目 `model-io/` 并返回 `needs_execution`；这一步没有调用另一模型，也没有执行研究任务。当前 Codex 必须实际完成 prompt、调用所需工具、校验内容，再保存纯 output 对象并执行：

模型 output 必须是对象。来源或证据等数组先封装为 `{"records": [...]}`，并将 response_schema 写成具有 records 数组属性的对象 schema；再将 records 写入模块索引。直接把数组作为 output 会被接口拒绝。阶段索引仍按各自 schema 校验并登记 SHA；回执是所产内容的记录，不是供应商认证。

```bash
"$WORKBENCH_PYTHON" "$SKILL/scripts/model_backends.py" accept-codex \
  --project "$PROJECT" --request "$PROJECT/model-io/M001.request.json" \
  --output "$PROJECT/model-io/M001.output.json"
```

随后再次 generate 返回经过请求哈希绑定的已完成回执。相同 ID 内容变化、不同已完成输出、过期请求哈希均被拒绝。`model: current-session` 表示会话执行环境；只有能确认实际模型标识时才填写具体名称。该回执是本地追溯记录，不是服务商签名认证。

### 命令后端

配置示例（wrapper 路径须由用户实际配置）：

```json
{
  "backend": "command",
  "argv": ["/absolute/python", "/absolute/my_model_wrapper.py"],
  "timeout": 60
}
```

`make_backend(config).generate(request)` 与 Codex 使用完全相同的请求，无须修改调度器。接口将请求 JSON 写入命令 stdin；命令 stdout 必须只输出：

```json
{"output": {"question": "实际模型产出的研究问题"}, "usage": {"input_tokens": null, "output_tokens": null}, "model": "实际后端模型名"}
```

只有 output 必填，usage/model 可省略。wrapper 可接本地模型、机构服务或其他 API；其认证、参数翻译和费用属于该显式配置的 wrapper。本版未配置或调用额外收费模型。argv 直接执行，`shell=False`；拒绝字符串 shell 命令和未知配置键。非零退出码、超时、坏 JSON、超大输出、schema 不符都使调用失败；命令错误不会伪造 completed。stderr 不进入回执，以免 wrapper 日志含密钥。

主程序负责保存 CommandBackend 的请求/响应回执、关联阶段、处理重试政策；后端本身不自动重复可能收费的请求。命令摘要保存 argv 哈希，输出内容与实际模型标识保存在响应中。测试以 Python fixture 验证协议切换，**不是本地模型或另一 API 的能力验收**。

统一 CLI：

```bash
"$WORKBENCH_PYTHON" "$SKILL/scripts/model_backends.py" generate \
  --config /absolute/backend.json --request /absolute/request.json
```

正常返回 JSON；配置/执行/校验错误退出 2。Codex 的 needs_execution 是正常待执行状态，不能据此将科研阶段标为完成。
