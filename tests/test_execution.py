from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

from reqflow import core, execution
from test_core import tree


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "source"
        self.repo.mkdir()
        self.git("init")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Test fixture")
        (self.repo / "app.py").write_text("answer = 42\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "fixture baseline")
        self.workspace = self.root / "worktree"
        self.git("worktree", "add", "-b", "test-work", str(self.workspace))
        self.flow = self.root / ".reqflow"
        self.flow.mkdir()
        (self.flow / "project.yaml").write_text(yaml.safe_dump({"repository": str(self.repo), "allowed_paths": ["app.py", "test_app.py"]}), encoding="utf-8")
        self.candidate = self.root / "candidate.yaml"
        self.candidate.write_text(yaml.safe_dump(tree(), allow_unicode=True), encoding="utf-8")
        goal = core.create_goal(self.flow, "Fixture goal", [])
        core.approve_goal(self.flow, goal["id"], "automated-fixture")
        core.publish_requirements(self.flow, self.candidate, goal["id"], "automated-fixture")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, check=True)

    def export(self, workspace=None):
        return execution.export_tasks(self.flow, workspace or self.workspace, self.root / "quota.json", self.root / "tasks")

    def test_only_accepted_predecessor_unlocks_next_wave(self):
        tasks = self.export()
        self.assertEqual(len(tasks), 1)
        self.assertIn("REQ-1", tasks[0]["prompt"])
        with self.assertRaisesRegex(ValueError, "prerequisite"):
            execution.verify_requirement(self.flow, "REQ-2", self.workspace, [sys.executable, "-c", "pass"])
        failed = execution.verify_requirement(self.flow, "REQ-1", self.workspace, [sys.executable, "-c", "raise SystemExit(3)"])
        self.assertEqual(failed["status"], "failed")
        self.assertIn("REQ-1", self.export()[0]["prompt"])
        accepted = execution.verify_requirement(self.flow, "REQ-1", self.workspace, [sys.executable, "-c", "from app import answer; assert answer == 42"])
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(accepted["test_runs"][-1]["exit_code"], 0)
        self.assertIn("REQ-2", self.export()[0]["prompt"])

    def test_manual_rerun_repairs_scope_with_failure_output(self):
        execution.verify_requirement(self.flow, 'REQ-1', self.workspace,
                                     [sys.executable, '-c', "print('broken scope'); raise SystemExit(1)"])
        original = subprocess.run
        prompts = []
        def repair(command, **kwargs):
            if command[:2] == ['codex', 'exec']:
                prompts.append(kwargs['input'])
                return subprocess.CompletedProcess(command, 0)
            return original(command, **kwargs)
        with patch('reqflow.execution.subprocess.run', side_effect=repair):
            result = execution.rerun_failed(self.flow)
        self.assertEqual(result['REQ-1']['status'], 'failed')
        self.assertEqual(len(prompts), 1)
        self.assertIn('broken scope', prompts[0])
        self.assertIn('Original requirement:', prompts[0])
        self.assertEqual(len(result['REQ-1']['test_runs']), 2)

    def test_auto_rerun_repeats_until_original_test_passes(self):
        config = yaml.safe_load((self.flow / 'project.yaml').read_text())
        config['auto_rerun'] = True
        (self.flow / 'project.yaml').write_text(yaml.safe_dump(config))
        ready = json.loads((self.flow / 'readiness.json').read_text())
        ready['project_sha256'] = execution._digest(self.flow / 'project.yaml')
        execution._write(self.flow / 'readiness.json', ready)
        original = subprocess.run
        repairs = []
        def repair(command, **kwargs):
            if command[:2] == ['codex', 'exec']:
                repairs.append(command)
                if len(repairs) == 2:
                    (self.workspace / 'app.py').write_text('answer = 43\n')
                return subprocess.CompletedProcess(command, 0)
            return original(command, **kwargs)
        with patch('reqflow.execution.subprocess.run', side_effect=repair):
            result = execution.verify_requirement(self.flow, 'REQ-1', self.workspace,
                [sys.executable, '-c', "assert '43' in open('app.py').read()"])
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(len(repairs), 2)
        self.assertEqual(len(result['test_runs']), 3)

    def test_rerun_executor_failure_is_reported_and_unlocks_retry(self):
        execution.verify_requirement(self.flow, 'REQ-1', self.workspace,
                                     [sys.executable, '-c', 'raise SystemExit(1)'])
        original = subprocess.run
        def repair(command, **kwargs):
            if command[:2] == ['codex', 'exec']:
                return subprocess.CompletedProcess(command, 9)
            return original(command, **kwargs)
        with patch('reqflow.execution.subprocess.run', side_effect=repair):
            with self.assertRaisesRegex(ValueError, 'Codex repair failed'):
                execution.rerun_failed(self.flow)
        state = json.loads((self.flow / 'rerun.json').read_text())
        self.assertEqual(state['status'], 'failed')
        self.assertFalse(execution._rerun_lock.locked())

    def test_rerun_uses_scheduler_when_original_request_was_scheduled(self):
        execution.verify_requirement(self.flow, 'REQ-1', self.workspace,
                                     [sys.executable, '-c', 'raise SystemExit(1)'])
        task_path = self.root / 'original.json'
        execution._write(task_path, {'version': 1, 'id': 'original',
            'workspace': str(self.workspace), 'codex': ['custom-codex'],
            'tree': {'id': 'root', 'prompt': 'original', 'children': []}})
        execution._write(self.flow / 'scheduler.json', {'task': str(task_path),
            'id': 'original', 'state_dir': str(self.root / 'scheduler-state')})
        original = subprocess.run
        scheduled = []
        def dispatch(command, **kwargs):
            self.assertNotEqual(command[:2], ['codex', 'exec'])
            if 'reqflow_scheduler' in command:
                self.assertIn('watch', command)
                task = json.loads(Path(command[4]).read_text(encoding='utf-8'))
                scheduled.append(task)
                execution._write(self.root / 'scheduler-state' / task['id'] / 'state.json',
                                 {'status': 'completed'})
                return subprocess.CompletedProcess(command, 0)
            return original(command, **kwargs)
        with patch('reqflow.execution.subprocess.run', side_effect=dispatch):
            execution.rerun_failed(self.flow)
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(scheduled[0]['codex'], ['custom-codex'])
        self.assertIn('Original requirement:', scheduled[0]['tree']['prompt'])
        self.assertEqual(json.loads(task_path.read_text())['tree']['prompt'], 'original')

    def test_source_and_unrelated_repositories_rejected(self):
        for workspace in (self.repo, self.root):
            with self.assertRaises(ValueError):
                self.export(workspace)

    def test_verify_exposes_running_state_and_preserves_run_history(self):
        original = subprocess.run
        observed = []
        def run(command, **kwargs):
            if command[0] == sys.executable:
                live = json.loads((self.flow / 'traceability.json').read_text(encoding='utf-8'))['requirements']['REQ-1']
                observed.append(live['status'])
                self.assertNotIn('exit_code', live['test_runs'][-1])
            return original(command, **kwargs)
        with patch('reqflow.execution.subprocess.run', side_effect=run):
            result = execution.verify_requirement(self.flow, 'REQ-1', self.workspace, [sys.executable, '-c', 'pass'])
        self.assertEqual(observed, ['running'])
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(len(result['test_runs']), 1)
        evidence = execution.record_evidence(self.flow, 'REQ-1', self.workspace, [], ['app.py'], [], 'accepted', {'app.py': 'FUNC'})
        self.assertEqual(evidence['interface_scopes'], {str(self.workspace.resolve() / 'app.py'): 'FUNC'})

    def test_legacy_export_still_loads_in_updated_scheduler(self):
        scheduler = Path(__file__).resolve().parents[2] / "scheduler"
        if not scheduler.is_dir():
            self.skipTest("adjacent scheduler checkout not installed")
        task = self.export()[0]
        task_file = self.root / "tasks" / (task['id'] + '.json')
        state = self.root / 'scheduler-state'
        result = subprocess.run(
            [sys.executable, '-m', 'reqflow_scheduler', 'status', str(task_file), '--state-dir', str(state)],
            cwd=scheduler, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'queued')
        self.assertFalse((self.workspace / 'test_app.py').exists())

    def test_goal_and_project_edits_revoke_export(self):
        for name in ("goals.yaml", "project.yaml"):
            path = self.flow / name
            original = path.read_bytes()
            path.write_bytes(original + b"\n# changed\n")
            with self.assertRaises(ValueError):
                self.export()
            path.write_bytes(original)

    def test_out_of_scope_changes_fail_acceptance(self):
        (self.workspace / "unrelated.py").write_text("changed = True\n", encoding="utf-8")
        result = execution.verify_requirement(self.flow, "REQ-1", self.workspace, [sys.executable, "-c", "pass"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("unrelated.py", result["test_runs"][-1]["scope_violations"])

    def test_committing_out_of_scope_change_does_not_bypass_scope_check(self):
        (self.workspace / "unrelated.py").write_text("changed = True\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.workspace), "add", "unrelated.py"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.workspace), "commit", "-m", "unrelated change"], check=True, capture_output=True)
        result = execution.verify_requirement(self.flow, "REQ-1", self.workspace, [sys.executable, "-c", "pass"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("unrelated.py", result["test_runs"][-1]["scope_violations"])

    def test_verify_cli_reports_actual_test_failure(self):
        import contextlib
        import io
        from reqflow.cli import main
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = main(["--flow-dir", str(self.flow), "verify", "REQ-1", "--workspace", str(self.workspace),
                           "--command", sys.executable, "-c", "raise SystemExit(4)"])
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(output.getvalue())["test_runs"][-1]["exit_code"], 4)

    def test_unverified_artifacts_cannot_mark_accepted(self):
        with self.assertRaises(ValueError):
            execution.record_evidence(self.flow, "REQ-1", self.workspace, [], ["app.py"], [], "accepted")
        with self.assertRaises(ValueError):
            execution.record_evidence(self.flow, "REQ-1", self.workspace, [], ["../source/app.py"], [], "pending")
        execution.verify_requirement(self.flow, "REQ-1", self.workspace, [sys.executable, "-c", "from app import answer; assert answer == 42"])
        result = execution.record_evidence(self.flow, "REQ-1", self.workspace, [], ["app.py"], [], "accepted")
        self.assertEqual(result["code"], [str((self.workspace / "app.py").resolve())])

    def test_scheduler_dispatch_contract_integration(self):
        scheduler_root = Path(__file__).resolve().parents[2] / "scheduler"
        sys.path.insert(0, str(scheduler_root))
        from reqflow_scheduler.scheduler import load_task
        tasks = self.export()
        # The updated scheduler retains single-prompt format compatibility.
        task = load_task(self.root / "tasks" / (tasks[0]["id"] + ".json"))
        self.assertEqual(task['tree']['prompt'], tasks[0]['prompt'])


if __name__ == "__main__":
    unittest.main()
