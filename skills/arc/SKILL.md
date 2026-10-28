---
name: arc
description: 将自然语言开发要求澄清并编译为 TDD REQ，在目标项目 .arc 保存产物、打开实时 Canvas，并可将 REQ 加入 scheduler 任务树等待定时执行。
---

# ARC

源码与 CLI 位于 `D:/code/arc`，先阅读该目录 `README.md`。Windows 使用该目录 `.venv/Scripts/python.exe -m reqflow`；WSL 使用 `/home/ssh/.cache/reqflow-arc-venv/bin/python`，从 `/mnt/d/code/arc` 运行。同一项目不混用 OS/runtime。

## 从自然语言到 REQ

1. 确定用户实际开发的目标项目，`intake <项目绝对路径> --text <原始要求>`，长文本使用 `--file`。产物位于目标项目 `.arc/requests/<请求ID>`，复用返回的 `flow_dir`。相同原文复用现有请求；修订要求建立新请求，保留历史。已有 `.reqflow` 可继续显式使用，不自动搬迁。
2. 当前调用本技能的 Agent 完成语义分析：阅读项目相关源码、测试和约束，识别目标、范围、依赖、正常/异常行为以及可验证的结果。不要仅复制原文或用关键词判断是否清晰。记录格式见 [references/analysis.md](references/analysis.md)。CLI 负责持久化和校验，不会自行调用模型理解任意自然语言。
3. 分析 YAML 放在该请求目录的 `review.yaml`，通过 `--flow-dir <flow> analyze --review <review.yaml>` 记录。有影响实现或验收的歧义时，记录带稳定 ID 的问题，向开发者提问，停止生成该请求的 REQ 和调度任务。不要自行补齐业务决策，不将示例、默认值或猜测当作答复。此时只记录原文、分析和问题，不提前生成 candidate、正式 REQ 或测试计划文件。
4. 收到开发者实际答复后，使用 `answer Q-ID <答复> --by <实际回答人>`；重新分析、更新 review，再 `analyze`。保留先前问题；`analyze` 自动保留已记录答复，不可在 review 中伪造回答。将答复落实到验收场景和 TDD 计划。
5. 信息齐备后标记 `status: ready`，`reviewed_by` 填实际分析者（Agent 名称可用，不冒充开发者批准）。提供 ARC FOLDER/ATOMIC 需求树和每个原子 REQ 的测试 argv、测试路径、代码路径及 RED 原因。执行 `compile`；只有返回 compiled 才声称生成 REQ。该命令不运行测试，计划与实际证据必须区分。

用户的开发请求授权生成明确要求对应的 REQ，不额外强制逐份批准。需要业务决策时必须先问。已编译请求不可覆盖，变更使用新请求。既有项目差异映射仍依据源码和开发者决策记录，不凭扫描结果推断已实现。

## 可视化与实际验证

使用返回的 flow 启动 `--flow-dir <flow> serve`，保留长运行进程并继续 CLI 工作。默认自动打开浏览器，返回实际输出的 URL；无桌面才加 `--no-open`。PowerShell 后台启动使用 `Start-Process -WindowStyle Hidden`。服务只读，每两秒刷新；离线使用 `view --output <flow>/report.html`。不重复启动相同流程的服务。

开发时按 REQ 的 RED → GREEN → 回归操作，使用 `verify REQ-ID --workspace <workspace> --command <测试argv>` 和 `evidence` 记录真实结果。ARC 文件与测试日志保留在目标项目 `.arc`，不将计划当作通过证据。

## 与新版 scheduler 同时使用

先完成澄清并 compile，再 `enqueue --task <外部task.json> --workspace <开发项目> --state-dir <外部state目录>`；可用 `--parent <节点ID>` 加入现有无 checkpoint 的树。默认追加到根节点原有子树之后；REQ 子链按依赖排序，适配 scheduler 深度优先执行。重复加入相同 REQ 不增加节点。已开始调度的树不可修改，使用新任务文件和 ID。scheduler 运行任务文件和状态仍在 workspace 之外，`.arc/requests/<ID>/scheduler.json` 保存交接索引。

只加入任务并告知用户已排队，不要为了验证而立即 tick 或执行开发。现有 watch 只读取启动时的树；更新未运行的树后，由 scheduler 技能按用户授权启动 watch 等待定时执行。不自行注册 OS 周期任务。排队本身不启动后台服务，没有 watch/定时器时明确告知尚未轮询。

按 scheduler 技能使用自动账户额度和北京时间调度，不要求旧版人工 quota、readiness、clean checkout 或摘要门槛。ARC 自己的生成与验收检查不交给 scheduler 执行。status 可只读核对排队状态，turn 完成不等于业务验收通过。

收到已派发节点时，只执行指定 REQ、flow 和 workspace，不重复 intake/enqueue 自身。保持原会话恢复语义，失败或歧义如实报告。
