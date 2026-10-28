# ARC 复用与兼容性审计

核对日期：2026-10-27。源码保存在 `../upstream/`，原始 MIT LICENSE 原样保留。

- [Agentic Requirement Compiler](https://github.com/code-philia/agentic-requirement-compiler)，固定提交 `5a02a173d33ebd9251b28d97c70f6a0cb5b20deb`，包 `arc-compiler 1.2.0`，Python ≥3.11，CLI `arc = main:main`。
- [ARC-Bench](https://github.com/code-philia/arc-bench) 当时 HEAD `c40e142a3726bae823810dc20a4b73039c0c5636`。它提供基准需求/测试资产，本次没有复制未经许可核对的基准实现或其完整测试集。

| 决策 | 证据与接入方式 |
| --- | --- |
| 直接复用需求格式 | 上游 `example/ticketbooking-quickstart/requirements.yaml` 为 `id: ROOT`、`type: FOLDER`、children ATOMIC，dependencies 和 steps(keyword/content) 场景。根包装 root/requirement 也兼容。 |
| 直接调用数据/交互契约 | `src/arcbench_agent_runtime/requirement_contracts.py:resolve_requirement_contracts` 仅用标准库。`reqflow/upstream.py` 从固定源码加载实际函数，验证生命周期、引用和交互字段，不复制实现。 |
| 适配依赖规划 | 保留上游的需求层级，补充严格结构校验、循环检测、文件夹依赖展开，执行状态单独存储。 |
| 适配追踪 | 上游 `traceability.py` 定义 requirement/scenario/interface/test/node-state JSON 表；本版保留 REQ→测试→代码→运行证据的关联，但不宣称直接兼容其内部全部表结构。 |
| 暂不调用完整编译器 | `core/workflow.py` 已有 scaffold/evolution 模式，并在 evolution 下跳过模板播种；但仍初始化编译运行环境、Git、数据库及后端操作契约。不能把 evolution 等同任意架构兼容。 |
| CCE 不直接用其 web runner | `app_type_handler/web.py` 的 `_resolve_web_test_target` 和 `_build_web_test_execution` 使用 backend/frontend 目录、npm/npx 命令；CCE 使用 apps、packages 和 pnpm，且 PostgreSQL 不可替换为 SQLite。 |
| 禁止默认清理已有仓库 | 上游 `main.py:cmd_compile` 的 --clean 会递归删除输出目录；本工具未暴露该选项。 |

上游数据库路径 `core/database.py:application_db_path` 指向 web 的 backend 数据库；`database_sql.py` 导入 sqlite3 并应用数据库计划。增量模式仍不能证明会保留 CCE PostgreSQL/API/前后端边界。因此本版使用需求契约 + Codex 适配器；不向 CCE 注入 SQLite、React/Express 模板或上游迁移。

## 已完成的非破坏验证

1. 实际调用上游 `core.files.load_requirements` 读取其 ticketbooking-quickstart 示例，得到 ROOT 和一个 ATOMIC；二次调用解析器不改变结果。
2. 本地单元测试通过真实上游解析器验证 unknown data 引用被拒绝、视觉字段保留。
3. 合成仓库的注册 Git worktree 中执行真实 unittest RED→最小代码改动→GREEN，保存 `examples/demo/.reqflow/runs/` 和 traceability；原仓库只保留基线。
4. WSL 只读扫描真实 CCE，输出技术栈、目录、命令和历史报告至 `examples/cce`；没有执行 CCE 的安装/构建/测试。

本次没有调用需要模型凭据的完整 ARC 编译过程，因此其在 CCE 上的完整应用编译兼容性为“未通过验证，保持禁用”，不能据此宣称完整上游编译已集成。

OpenAI 执行/插件接口依据：[官方插件打包](https://developers.openai.com/plugins/build/plugins)、[Codex 非交互执行](https://learn.chatgpt.com/docs/non-interactive-mode)。同时检查本机 `codex exec --help`、`codex exec resume --help`。调度测试使用模拟 Codex 事件，账户额度不由测试伪装读取。
