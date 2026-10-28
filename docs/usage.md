# REQFlow ARC

把自然语言开发要求澄清并编译为 TDD REQ，在目标项目内保存产物，提供实时 Canvas，并将任务交给相邻的 [scheduler](https://github.com/Astonomy/scheduler) 定时执行。原始设计记录见 [PLAN.md](../PLAN.md)，旧演示保留以便追溯。

## 调用 skill

技能源文件是 [skills/arc/SKILL.md](../skills/arc/SKILL.md)，本机安装到 `D:/VScode/.codex/skills/arc`。新会话可以使用：

```text
$arc 为 D:/code/my-project 解析以下开发要求，打开 Canvas，澄清完成后生成 TDD REQ，并加入 scheduler 的任务树等待执行：……
```

语义分析由调用技能的 Agent 完成，CLI 负责保存、校验与编译，不自行调用模型 API。发现影响实现或验收的歧义时，先向开发者提问；尚有问题、未复核答复或缺少测试计划时，不生成该请求的 REQ，也不入队。

## 项目内的 .arc

默认 `--flow-dir` 是当前目录 `.arc`；推荐以 `intake` 返回的请求目录为 flow，避免多个要求覆盖彼此。所有 ARC 产物保留在目标项目内：

```text
my-project/.arc/
  project.yaml
  requests/<请求ID>/
    source.md                 原始自然语言
    review.yaml               Agent 编写的分析输入
    analysis.yaml             持久化分析、问题和开发者回答
    project.yaml              该请求的项目约束快照
    requirements.yaml         澄清完成后生成的完整需求树
    requirements.md
    reqs/REQ-ID.yaml           原子 REQ + TDD 测试计划
    traceability.json          实际证据（验证后产生）
    runs/                     实际测试日志
    scheduler.json            外部调度任务索引（入队后产生）
```

相同原文重用已有请求；修改要求建立新请求。已编译请求不原地覆盖。旧 `.reqflow` 仍可显式传入，不自动迁移。scheduler 任务运行文件、状态和日志按其约定放在 workspace 外部；ARC 内保存交接索引。

## 自然语言解析与编译

Python 3.11+、Git、uv，唯一第三方运行依赖是 PyYAML。上游 ARC 契约解析器从固定源码加载，不启用其完整应用编译器。

```powershell
cd D:/code/arc
./scripts/setup-upstream.ps1
uv sync --locked
./.venv/Scripts/python.exe -m reqflow init D:/code/my-project
./.venv/Scripts/python.exe -m reqflow intake D:/code/my-project --text '实际开发要求'
# 长要求也可用 --file <utf8文本文件>。使用上一步返回的 flow_dir：
./.venv/Scripts/python.exe -m reqflow --flow-dir <flow> analyze --review <flow>/review.yaml
./.venv/Scripts/python.exe -m reqflow --flow-dir <flow> answer Q-1 '开发者的实际回答' --by developer
# Agent 根据答复重新分析，保留原问题，更新 review.yaml 并再次 analyze：
./.venv/Scripts/python.exe -m reqflow --flow-dir <flow> compile
```

分析记录格式见 [analysis.md](../skills/arc/references/analysis.md)。明确的要求可以直接得到 ready 分析；有疑问时仅保存原文和澄清记录，compile 返回 needs_clarification（退出码 2）。每个原子 REQ 必须具备有序 Given/When/Then 场景和 TDD 计划：测试 argv、代码/测试路径、RED 预期。compile 不执行测试，也不证明语义正确性；Agent 必须基于实际项目分析，不能用空 questions 绕过已发现的歧义。

compile 使用分析者身份记录编译就绪状态，不冒充额外的开发者批准。旧 goal-add / goal-answer / goal-approve / publish 流程保留用于已有工作流，其显式批准规则不变。

## 简约 Canvas

```powershell
./.venv/Scripts/python.exe -m reqflow --flow-dir <flow> serve
# 自动打开浏览器；默认动态端口，URL 由命令输出。无桌面用 --no-open。
./.venv/Scripts/python.exe -m reqflow --flow-dir <flow> view --output <flow>/report.html
```

只监听 `127.0.0.1`，每两秒只读更新，Ctrl+C 停止。左侧阶段，右侧 Requirements、Interfaces、Tests 三栏内容纵向居中。SVG 曲线表示父子需求及同 REQ 的代码/测试关联；没有关联记录时不凭空连接。编译后的计划代码/测试单独显示“计划”，实际证据按记录状态显示。支持缩放、Fit、工件栏隐藏、节点详情、追溯与差异页。离线 view 不实时更新。

Interfaces 按 scope 分组：默认 UI、API、FUNC、DB，支持自定义名称，无标注时放入“未指定 scope”。优先使用证据或 TDD 计划中的 `interface_scopes: {代码路径: SCOPE}`，其次继承需求树节点/父节点的 `scope`。同一 REQ 的不同代码文件可以属于不同 scope，连线仍按原 REQ 保留。记录实际工件时可用 `evidence ... --code src/api.py --interface-scope src/api.py=API`（可重复）。

节点以底色和文字同时标识状态：黄为待实现/计划，蓝为执行中，绿为通过，红为失败，灰为未知。verify 启动测试前写入 running，测试完成后更新结果；实时 Canvas 下次轮询会同步颜色，历史失败运行仍保留红色。

## 与新版 scheduler 配合

必须先 compile 成功，再加入任务树。enqueue 不调用模型、不查额度、不启动 tick 或 watch：

```powershell
./.venv/Scripts/python.exe -m reqflow --flow-dir <flow> enqueue --task D:/scheduler-tasks/my-project.json --workspace D:/code/my-project --state-dir D:/scheduler-state
# 可以加 --parent <已有节点ID> 指定加入位置。
cd D:/code/scheduler
./.venv/Scripts/python.exe -m reqflow_scheduler status D:/scheduler-tasks/my-project.json --state-dir D:/scheduler-state
# 用户授权开始等待调度时运行：
./.venv/Scripts/python.exe -m reqflow_scheduler watch D:/scheduler-tasks/my-project.json --state-dir D:/scheduler-state
```

新文件会生成 v1 tree；已有未调度任务默认在根节点原有子树之后追加，保留原节点。REQ 按拓扑顺序组成子链，适配 scheduler 的深度优先遍历及多个前置依赖；重复入队不会重复节点。有 checkpoint 的树不修改，改用新任务文件和 ID。节点提示包含 REQ 与 TDD 计划，要求实际验证前置 REQ 的通过证据。

scheduler 按其规则读取真实账户额度，北京时间 01:00–09:00 深度优先执行；其他时段在五小时额度重置前 30 分钟提交当前节点。无需旧人工 quota、readiness、clean checkout 或文件摘要检查。scheduler 的 turn 完成不等于 ARC 验收通过。未运行 watch 或 OS 定时器时，排队文件不会自己执行；本项目不自动注册周期任务。

旧 `export --quota-file ...` 只用于兼容旧流程，仍导出单 prompt 任务，不用于新任务树交接；新版 scheduler 忽略其 legacy gate 字段。

## 盘点与真实验收

`import <repository>` 默认把盘点写入该仓库 `.arc`，扫描排除 `.arc`，不执行发现的命令。指定 `--output <外部目录>` 保留旧版输出 `<外部目录>/.reqflow` 的行为。扫描线索不自动变成正式需求，既有行为差异与冲突须依据实际材料确认。新建 intake 会继承 `.arc/project.yaml`、已有导入基线和映射，未知差异仍阻止编译。

```powershell
./.venv/Scripts/python.exe -m reqflow --flow-dir <flow> verify REQ-ID --workspace <workspace> --command python -m unittest discover -s tests -v
./.venv/Scripts/python.exe -m reqflow --flow-dir <flow> evidence REQ-ID --workspace <workspace> --test tests/test_feature.py --code feature.py --status accepted
./.venv/Scripts/python.exe scripts/check.py
```

verify 运行真实 argv（默认最多 300 秒），保存退出码和 stdout/stderr，失败不记为 accepted；evidence 不能绕过成功测试。allowed_paths 用于验收范围检查，`.arc` 工件不算业务代码越界。默认本地导入允许在原项目工作区验证；旧外部导入保留隔离 worktree 规则。不要自动清理、提交或覆盖用户改动。

WSL 使用 `/home/ssh/.cache/reqflow-arc-venv/bin/python`，从 `/mnt/d/code/arc` 运行。原始上游固定提交为 `5a02a173d33ebd9251b28d97c70f6a0cb5b20deb`，安装步骤见 setup-upstream.ps1。wheel 不包含上游，需从源码/可编辑安装使用。

[验证记录](verification/canvas.md) · [示例 Canvas](../examples/demo/report.html) · [ARC 复用范围](ARC-AUDIT.md)
