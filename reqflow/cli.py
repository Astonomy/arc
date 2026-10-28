"""Explicit, scriptable workflow steps. No external model calls on import or planning."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import yaml

from . import core, execution, gaps, importer, upstream, view, intake, queue


def parser():
    cli = argparse.ArgumentParser(prog="reqflow", description="ARC 通用需求工作流")
    cli.add_argument("--flow-dir", type=Path, default=Path(".arc"), help="工作流状态目录，默认 .arc；也支持既有 .reqflow")
    commands = cli.add_subparsers(dest="action", required=True)
    init = commands.add_parser('init', help='在目标项目内创建 .arc')
    init.add_argument('project', type=Path)
    request = commands.add_parser('intake', help='保存自然语言要求，尚不生成 REQ')
    request.add_argument('project', type=Path)
    source = request.add_mutually_exclusive_group(required=True)
    source.add_argument('--text')
    source.add_argument('--file', type=Path)
    analyze = commands.add_parser('analyze', help='记录 skill/Agent 的语义分析与澄清问题')
    analyze.add_argument('--review', type=Path, required=True)
    clarification = commands.add_parser('answer', help='记录开发者对歧义的实际回答')
    clarification.add_argument('question_id')
    clarification.add_argument('text')
    clarification.add_argument('--by', required=True)
    commands.add_parser('compile', help='仅在语义分析就绪且无待澄清问题时生成 TDD REQ')
    enqueue = commands.add_parser('enqueue', help='将已生成 REQ 加入 scheduler 任务树，不立即执行')
    enqueue.add_argument('--task', type=Path, required=True)
    enqueue.add_argument('--workspace', type=Path, required=True)
    enqueue.add_argument('--state-dir', type=Path)
    enqueue.add_argument('--parent')
    scan = commands.add_parser("import", help="只读导入既有仓库，结果写入外部目录")
    scan.add_argument("repository", type=Path)
    scan.add_argument("--output", type=Path, help="兼容旧外部导入；默认写入目标项目 .arc")
    goal = commands.add_parser("goal-add", help="建立候选目标；未回答问题会阻塞发布")
    goal.add_argument("title")
    goal.add_argument("--question", action="append", default=[])
    answer = commands.add_parser("goal-answer")
    answer.add_argument("goal_id")
    answer.add_argument("question_id")
    answer.add_argument("answer")
    approve = commands.add_parser("goal-approve")
    approve.add_argument("goal_id")
    approve.add_argument("--by", required=True)
    publish = commands.add_parser("publish", help="显式确认候选需求并发布正式需求")
    publish.add_argument("candidate", type=Path)
    publish.add_argument("--goal", required=True)
    publish.add_argument("--by", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("candidate", type=Path)
    commands.add_parser("plan", help="输出依赖排序后的原子任务")
    diff = commands.add_parser("diff", help="比较候选需求、现有映射与历史测试证据")
    diff.add_argument("candidate", type=Path)
    export = commands.add_parser("export", help="导出前置已验收的调度任务")
    export.add_argument("--workspace", type=Path, required=True)
    export.add_argument("--quota-file", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--req", action="append", help="可选原子 REQ ID，允许重复指定")
    verify = commands.add_parser("verify", help="实际执行测试 argv，保存退出码与证据")
    verify.add_argument("req_id")
    verify.add_argument("--workspace", type=Path, required=True)
    verify.add_argument("--command", nargs=argparse.REMAINDER, required=True, help="后续所有参数构成测试 argv")
    evidence = commands.add_parser("evidence", help="关联已有代码、测试和运行日志")
    evidence.add_argument("req_id")
    evidence.add_argument("--workspace", type=Path, required=True)
    evidence.add_argument("--test", action="append", default=[])
    evidence.add_argument("--code", action="append", default=[])
    evidence.add_argument('--interface-scope', action='append', help='代码路径=SCOPE，可重复，如 src/api.py=API')
    evidence.add_argument("--log", action="append", default=[])
    evidence.add_argument("--status", choices=["pending", "failed", "accepted"], default="pending")
    report = commands.add_parser("view", help="生成交互式本地证据快照")
    report.add_argument("--output", type=Path, required=True)
    serve = commands.add_parser("serve", help="打开浏览器，实时查看编译与验收 Canvas")
    serve.add_argument("--port", type=int, default=0)
    serve.add_argument("--no-open", action="store_true")
    audit = commands.add_parser("audit", help="生成完整 ARC 编译器兼容性检查结果")
    audit.add_argument("repository", type=Path)
    commands.add_parser("doctor", help="检查依赖与本地 ARC 源码版本")
    return cli


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    flow = args.flow_dir.resolve()
    try:
        if args.action == 'init':
            result = {'flow_dir': str(intake.initialize(args.project))}
        elif args.action == 'intake':
            result = intake.intake(args.project, args.text if args.text is not None else args.file.read_text(encoding='utf-8-sig'))
        elif args.action == 'analyze':
            result = intake.analyze(flow, args.review)
        elif args.action == 'answer':
            result = intake.answer(flow, args.question_id, args.text, args.by)
        elif args.action == 'compile':
            result = intake.compile_request(flow)
            if result['status'] == 'needs_clarification':
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 2
        elif args.action == 'enqueue':
            result = queue.enqueue(flow, args.task, args.workspace, args.state_dir, args.parent)
        elif args.action == "import":
            result = importer.write_import(args.repository, args.output)
        elif args.action == "goal-add":
            result = core.create_goal(flow, args.title, args.question)
        elif args.action == "goal-answer":
            result = core.answer_goal(flow, args.goal_id, {args.question_id: args.answer})
        elif args.action == "goal-approve":
            result = core.approve_goal(flow, args.goal_id, args.by)
        elif args.action == "publish":
            result = core.publish_requirements(flow, args.candidate, args.goal, args.by)
            tree = yaml.safe_load((flow / "requirements.yaml").read_text(encoding="utf-8"))
            (flow / "requirements.md").write_text(view.render_markdown(tree), encoding="utf-8")
        elif args.action in {"validate", "plan"}:
            path = args.candidate if args.action == "validate" else flow / "requirements.yaml"
            tree = core.validate_tree(yaml.safe_load(path.read_text(encoding="utf-8-sig")))
            result = {"valid": True, "atomic_count": len(core.atomic_plan(tree))} if args.action == "validate" else core.atomic_plan(tree)
        elif args.action == "diff":
            tree = core.validate_tree(yaml.safe_load(args.candidate.read_text(encoding="utf-8-sig")))
            result = gaps.analyze_gaps(flow, tree)
        elif args.action == "export":
            result = execution.export_tasks(flow, args.workspace, args.quota_file, args.output, args.req)
        elif args.action == "verify":
            command = args.command
            if command and command[0] == "--":
                command = command[1:]
            result = execution.verify_requirement(flow, args.req_id, args.workspace, command)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "accepted" else 2
        elif args.action == "evidence":
            scopes = None
            if args.interface_scope is not None:
                scopes = {}
                for item in args.interface_scope:
                    path, separator, scope = item.rpartition('=')
                    if not separator or not path or not scope.strip():
                        raise ValueError('interface-scope must use code-path=SCOPE')
                    scopes[path] = scope
            result = execution.record_evidence(flow, args.req_id, args.workspace, args.test, args.code, args.log, args.status, scopes)
        elif args.action == "view":
            result = {"output": str(view.render_view(flow, args.output))}
        elif args.action == "serve":
            from .server import serve
            serve(flow, args.port, open_browser=not args.no_open)
            return 0
        elif args.action == "audit":
            result = upstream.compatibility_report(args.repository)
        elif args.action == "doctor":
            actual = subprocess.run(["git", "-C", str(upstream.UPSTREAM), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30)
            result = {"python": sys.version.split()[0], "yaml": yaml.__version__, "upstream_expected": upstream.REVISION,
                      "upstream_actual": actual.stdout.strip(), "ok": actual.returncode == 0 and actual.stdout.strip() == upstream.REVISION}
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, yaml.YAMLError, subprocess.SubprocessError) as exc:
        print(f"reqflow: {exc}", file=sys.stderr)
        return 1
