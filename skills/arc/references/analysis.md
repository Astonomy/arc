# 自然语言分析记录

由调用 ARC 的 Agent 进行语义解析，再通过 CLI 保存。先读 flow 内 `source.md`、`analysis.yaml` 和项目有关源码与测试。

有歧义时，review 只需包含准确原文和问题：

```yaml
source: 原始要求（必须与 source.md 完全一致）
status: needs_clarification
reviewed_by: codex
questions:
  - id: Q-1
    question: 输入无效时应抛出异常还是返回错误对象？
```

使用 `answer Q-1 '开发者实际回答' --by developer` 后，review 保留相同 id 和问题原文，答案由 `analyze` 自动合并。回答会将状态改为 pending_review，不能直接 compile。

无歧义的最小示例（不是其他项目的默认业务决策）：

```yaml
source: 提供 add(a,b) 返回两个整数之和，add(2,3) 应返回 5，只需支持整数输入。
status: ready
reviewed_by: codex
questions: []
requirements:
  id: ROOT
  type: FOLDER
  name: 整数加法
  description: 仅支持整数输入的加法行为
  children:
    - id: REQ-ADD
      type: ATOMIC
      name: 两个整数求和
      description: add(a,b) 返回两个整数之和
      dependencies: []
      scenarios:
        - name: 2 加 3
          steps:
            - keyword: GIVEN
              content: 整数输入 2 和 3
            - keyword: WHEN
              content: 调用 add(2,3)
            - keyword: THEN
              content: 结果等于 5
tdd:
  REQ-ADD:
    test_command: [python, -m, unittest, discover, -s, tests, -v]
    tests: [tests/test_calculator.py]
    code: [calculator.py]
    interface_scopes:
      calculator.py: 整数运算
    red: 求和断言在 add 尚未实现时失败
```

按项目技术栈选择真实可执行 argv，不机械沿用示例命令。代码和测试路径可指向计划新建的文件；compile 不执行它们。使用场景明确可观察输出、错误行为与边界条件，不凭空扩大范围。业务选择、缺失输入/输出、互相矛盾的规则必须先问开发者。

scope 根据要求的实际职责在 REQ 中声明，不套用固定的前后端分类。可在需求节点设置 `scope`（子节点继承），或通过 TDD 的 `interface_scopes` 按代码路径声明任意领域名称，如机械控制、传感器采集、数据清洗。Canvas 仅动态显示当前 REQ 涉及的 scope，不靠证据元数据或文件后缀推断。

`compile` 校验问题已实际回答、分析已复核、schema 和依赖无误、每个原子 REQ 的 TDD 字段齐全，才生成 `requirements.yaml`、`requirements.md` 和 `reqs/REQ-ID.yaml`。编译记录不代表测试通过。未知业务语义能否被发现仍依赖 Agent 的分析质量，CLI 不声称能自动证明自然语言不存在歧义。
