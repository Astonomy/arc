"""Reproducible local TDD demonstration; uses no model calls or account quotas."""
from pathlib import Path
import json
import subprocess
import sys

import yaml

from reqflow import core, execution, view


def main():
    destination = Path(sys.argv[1] if len(sys.argv) > 1 else "examples/demo").resolve()
    source, worktree, flow = destination / "repository", destination / "worktree", destination / ".reqflow"
    if source.exists() or worktree.exists():
        raise SystemExit("Demo workspace exists; use a new output directory to preserve prior evidence.")
    source.mkdir(parents=True)

    def git(*args):
        subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True)

    git("init")
    git("config", "user.name", "REQFlow demo fixture")
    git("config", "user.email", "fixture@example.invalid")
    (source / "calculator.py").write_text("def add(a, b):\n    return 0\n", encoding="utf-8")
    (source / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Demo baseline with missing behavior")
    git("worktree", "add", "-b", "demo-increment", str(worktree))
    flow.mkdir()
    project = {"version": 1, "repository": str(source), "allowed_paths": ["calculator.py", "test_calculator.py"],
               "constraints": ["Synthetic demonstration only; never CCE business requirements."]}
    (flow / "project.yaml").write_text(yaml.safe_dump(project, allow_unicode=True), encoding="utf-8")
    tree = {"id": "ROOT", "name": "可复现 TDD 演示", "type": "FOLDER", "description": "仅用于验证工具链的合成需求", "children": [
        {"id": "REQ-ADD", "name": "两数相加", "type": "ATOMIC", "description": "add(a,b) 返回数字之和",
         "dependencies": [], "scenarios": [{"name": "两个整数相加", "steps": [
             {"keyword": "GIVEN", "content": "输入整数 2 和 3"}, {"keyword": "WHEN", "content": "调用 add(2,3)"},
             {"keyword": "THEN", "content": "结果为 5"}]}]}]}
    candidate = destination / "requirements.candidate.yaml"
    candidate.write_text(yaml.safe_dump(tree, allow_unicode=True, sort_keys=False), encoding="utf-8")
    goal = core.create_goal(flow, "合成测试：加法", [])
    core.approve_goal(flow, goal["id"], "automated-demo-fixture")
    core.publish_requirements(flow, candidate, goal["id"], "automated-demo-fixture")
    tasks = execution.export_tasks(flow, worktree, destination / "quota-not-configured.json", destination / "tasks")
    (worktree / "test_calculator.py").write_text("import unittest\nfrom calculator import add\n\nclass AdditionTest(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n", encoding="utf-8")
    command = [sys.executable, "-m", "unittest", "discover", "-s", ".", "-v"]
    red = execution.verify_requirement(flow, "REQ-ADD", worktree, command)
    if red["status"] != "failed":
        raise RuntimeError("Demo RED phase unexpectedly passed")
    (worktree / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    green = execution.verify_requirement(flow, "REQ-ADD", worktree, command)
    if green["status"] != "accepted":
        raise RuntimeError("Demo GREEN phase failed")
    execution.record_evidence(flow, "REQ-ADD", worktree, ["test_calculator.py"], ["calculator.py"], green["logs"], "accepted")
    view.render_view(flow, destination / "report.html")
    (flow / "requirements.md").write_text(view.render_markdown(tree), encoding="utf-8")
    summary = {"fixture_only": True, "model_calls": 0, "red_exit": red["test_runs"][-1]["exit_code"],
               "green_exit": green["test_runs"][-1]["exit_code"], "exported_tasks": len(tasks), "report": str(destination / "report.html")}
    (destination / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
