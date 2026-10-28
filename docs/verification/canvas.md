# Canvas 与 skill 验证（2026-10-27）

动态 scope 更新：`check-canvas-states.cjs` 已验证只从当前 REQ 的 scope 和 TDD interface_scopes 生成分组，支持机械控制、传感器采集等领域名及父级 scope 继承；未涉及的固定分组不出现，历史 REQ/证据中的额外 scope 不影响分组。声明 scope 但尚无工件时保留空组，无 REQ 时无预设组。现有连线、状态底色、纵向居中和移动布局检查仍通过。

2026-10-28 更新：ARC 37 项测试通过。新增验证覆盖 verify 执行中的 running 状态及最终状态、scope 元数据保存；`scripts/check-canvas-states.cjs` 验证 UI/API/FUNC/DB、自定义和未指定 scope 分组，五种不同底色、运行状态变化、工件连线及移动端布局。截图见 `examples/demo/scope-states.png`。

- Windows：ARC 36 项、相邻新版 scheduler 19 项 unittest 通过，见 `windows.json` 和对应日志。
- 自然语言工作流：原文保存到项目 `.arc/requests/<ID>`；未回答澄清问题、答复后未重新分析、来源不符、缺少任一 REQ 的 TDD 字段时不生成 REQ。测试覆盖真实答复的合并、编译后不可覆盖、同原文复用。
- scheduler 集成：真实 CLI 读取新任务树，status 为 queued；未生成 REQ 不能入队、重复入队不重复节点、保留原树节点、已有 checkpoint 禁止改树。调度测试使用真实 tick 逻辑、模拟额度和模型执行，确认白天非允许窗口等待、北京时间 06:00 按依赖次序消费 REQ 子链；没有访问真实账户或执行开发。
- Playwright：`scripts/check-view.cjs` 验证需求/实现/测试关联曲线存在，三栏内容纵向居中，节点详情、缩放、Fit、工件栏隐藏、记录页筛选正常；页面异常为空，移动端无页面横向溢出。截图见 `examples/demo/canvas.png`、`canvas-mobile.png`、`desktop.png`、`mobile.png`。
- Playwright：`scripts/check-live.cjs` 在临时目录验证服务读取新增澄清问题后，不刷新页面即可显示“1 项待开发者回答”，页面异常为空。
- HTTP 测试验证快照不缓存、状态更新可见、文件目录不公开。
- 默认项目内导入写入 `.arc`，扫描排除 `.arc`；外部旧导入仍可使用。
- `quick_validate.py skills/arc` 通过；新版 skill 及 analysis 参考文件安装到 `D:/VScode/.codex/skills/arc/`。

自然语言语义分析由调用技能的 Agent 完成；CLI 不能自动证明原文无歧义。测试覆盖的是已记录问题和 TDD 结构门槛，不是任意自然语言的语义准确率。

本次没有调用模型 API 或消耗真实 Codex 额度。Canvas 区分计划与实际测试记录，未启用上游完整应用编译器。enqueue 仅保存任务树，不启动 watch、注册 OS 定时器或执行开发。新版 scheduler 自行查询额度并按其调度窗口运行，不再消费旧的人工 quota 或 ARC readiness 检查。
