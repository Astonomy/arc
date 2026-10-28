# 验证记录

最新开发验证见 [Canvas、自然语言编译与新版 scheduler](verification/canvas.md)：ARC 36 项、新版 scheduler 19 项测试通过。以下为首版历史记录，人工额度与旧摘要门槛不代表新版 scheduler 行为。

2026-10-27，先完成 scheduler，再完成 ARC 接入。执行 `scripts/check.py` 将实际测试输出保存到 [verification/](verification/)；Windows 和 Ubuntu WSL 分别使用各自 Python，未共用虚拟环境。

| 项目 | 检查 |
| --- | --- |
| scheduler | 16 项行为测试：额度未知/过期/不足、时间窗口、目标及项目摘要、工作区互斥、多进程重复触发、停止、超时、大 stdin、准确会话恢复、Windows 检查点并发读取与无会话 ID 崩溃阻塞。 |
| ARC | 27 项行为测试：上游契约、schema/依赖、澄清与批准、差异冲突、导入只读及历史失败、隔离工作树、执行依赖、真实测试失败与通过、包含已提交改动的范围检查、调度器接口、CLI 和 HTML 数据转义。 |
| TDD 演示 | [summary.json](../examples/demo/summary.json)：真实测试 RED exit 1、GREEN exit 0，没有模型调用。测试代码、实现和 stdout/stderr 均保留于演示目录。 |
| 浏览器 | 使用现有 Playwright + Chromium 检查需求选择、筛选、页面 JS 错误，以及 390px 手机宽度是否横向溢出；[browser-check.json](../examples/demo/browser-check.json)、desktop.png、mobile.png 保存结果。 |
| CCE 导入 | WSL 识别 Node ≥24、pnpm ≥11、Next.js、Vue、PostgreSQL；发现 102 个测试资产路径、99 个 API 线索、42 个数据库线索、79 个文档路径。线索数量不等于功能或测试数量。4 份可识别历史 Playwright 摘要当时为 passed；未运行本轮 CCE 测试。 |

CCE 当时已有大量未提交文件。扫描结果保留 dirty 状态；没有提交、暂存、回滚或修改其业务代码。没有配置具体 CCE 增量目标，因此没有发布 CCE 正式需求。

没有用真实账户运行 Codex 或上游 ARC 编译，也没有安装插件、信任 hooks、注册周期任务。账户自动额度读取、无人值守全链路和完整 ARC 在 CCE 上的兼容性不属于本次已验证结论。
