# 组件来源与适配

安装日期：2026-10-06。适用平台：当前 Codex 本地技能环境。

新安装的研究构思、自审与审稿回复模块来自：
- 仓库：https://github.com/Galaxy-Dawn/claude-scholar
- 分支：codex
- 固定提交：b672e80951a2348dd6136316d096603bf2dc5b83
- 路径：skills/research-ideation、skills/paper-self-review、skills/review-response
- 许可：MIT；许可副本保留在工具搭建目录。

三个上游目录保留工作流与参考文件；仅将 version/tags 移入兼容的 metadata，并去掉 review-response 描述中未经验证的录用率承诺。原始及安装文件哈希保存在安装清单。工作台在调用时指定社科适配：不强制机器学习实验项目、不直接套用计算机会议格式、Zotero 为可选连接。上游技能里的安装命令、示例和服务名不是已安装/已连接的证明。

复用现有 `academic-research-suite` 3.22.2、`academic-humanizer`、`autonomous-research`、`statistical-analysis`、`statsmodels`、`scientific-visualization`、`seaborn`、`matplotlib` 和文档/PDF工具。各自来源与许可由其安装包维护；本工作台不重写它们。

本工作台为本机定制的协调入口与项目脚本，没有安装上游全局 AGENTS.md、config.toml、hooks、GitHub App 或后台服务。

## v2 跨仓库选型与可执行流水线

2026-10-06 新增五个局部模块，保留各自 MIT LICENSE 和 UPSTREAM.json，不安装仓库全局配置：

| 本地 skill | 官方仓库 / 固定提交 | 作用 |
|---|---|---|
| literature-reading-and-synthesis | jjfroehlich/agent-skills-for-academic-research @ 9b1b256e99055006725fe4c6b8f90d301ceef7b0 | 精读、论断证据分离、跨文献矩阵 |
| map-literature-contradictions | xingtaxueshu/literature-review-skills @ 84de3ba1f3853334d565fbbe6ac4f321cba6bd6b | 分歧条件、反例、解释边界 |
| experimental-design | K-Dense-AI/scientific-agent-skills @ 92ace75ac21efe19a620434e0ca4e356081fe807 | 设计、区组/分层/整群随机化 |
| statistical-power | 同上 | 样本量、功效、敏感性计算 |
| interview-analyst | nealcaren/social-data-analysis @ dda68b6cb9e324b2035c7da0f24c8e66d5863fb1 | 定性编码、变异、反例、引语证据 |

前两个保留上游内容。K-Dense 两模块缩短触发描述，将 compatibility 放入 metadata，补充本机 runtime 提示，计算代码未改动。访谈入口改用当前 Codex/继承模型、项目相对路径、本地进度记录；已委托的流程自动经过常规检查点，不默认创建 Git 提交或逐阶段停等。六份方法阶段指南保持原始内容，路径按入口映射。

完整选型说明、原始入口备份与安装前后 SHA256：`<local-research-workbench>/`。复用 ARS 的许可证为 CC-BY-NC 4.0；不是整个组合都统一为 MIT，也没有将这些本地组件重新发布。

新增自编标准库脚本：pipeline.py（八阶段状态、失效与恢复）、collect_sources.py（Crossref/ERIC 与原文快照）、export_bundle.py（白名单本地交付包）。它们与已有workspace.py共同工作。Codex实际执行任务，Python不直接调用模型；没有常驻服务、第二模型API或后台自动化。
