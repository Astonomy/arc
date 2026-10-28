from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

from reqflow import intake, queue
from test_core import tree


class IntakeQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = (self.root / 'project').resolve()
        self.project.mkdir()
        self.source = '新增可验证行为；按依赖完成两个步骤。'
        self.flow = Path(intake.intake(self.project, self.source)['flow_dir'])
        self.review = self.root / 'review.yaml'

    def analysis(self):
        return {'source': self.source, 'status': 'ready', 'reviewed_by': 'test-agent',
                'questions': [], 'requirements': tree(),
                'tdd': {r: {'test_command': ['python', '-m', 'unittest'],
                            'tests': ['tests/test_app.py'], 'code': ['app.py'],
                            'red': '新行为尚未实现时断言失败'} for r in ('REQ-1', 'REQ-2')}}

    def record(self, value):
        self.review.write_text(yaml.safe_dump(value, allow_unicode=True), encoding='utf-8')
        return intake.analyze(self.flow, self.review)

    def test_intake_uses_project_arc_reuses_source_and_creates_no_req(self):
        self.assertTrue(self.flow.is_relative_to(self.project / '.arc'))
        self.assertEqual(intake.intake(self.project, self.source)['flow_dir'], str(self.flow))
        self.assertFalse((self.flow / 'requirements.yaml').exists())
        with self.assertRaisesRegex(ValueError, 'ready'):
            intake.compile_request(self.flow)

    def test_unanswered_question_blocks_all_req_files_until_answer_and_review(self):
        analysis = self.analysis()
        analysis['questions'] = [{'id': 'Q-1', 'question': '失败时返回什么？'}]
        self.record(analysis)
        self.assertEqual(intake.compile_request(self.flow)['status'], 'needs_clarification')
        self.assertFalse(list(self.flow.glob('*requirement*')))
        intake.answer(self.flow, 'Q-1', '返回明确错误信息', 'developer')
        with self.assertRaisesRegex(ValueError, 're-review'):
            intake.compile_request(self.flow)
        self.record(analysis)
        result = intake.compile_request(self.flow)
        self.assertEqual(result['status'], 'compiled')
        receipt = yaml.safe_load((self.flow / 'reqs/REQ-1.yaml').read_text(encoding='utf-8'))
        self.assertIn('test_command', receipt['tdd'])
        self.assertEqual(intake.read_analysis(self.flow)['questions'][0]['answered_by'], 'developer')

    def test_invented_answers_stale_source_and_incomplete_tdd_rejected(self):
        analysis = self.analysis()
        analysis['questions'] = [{'id': 'Q-1', 'question': '返回什么', 'answer': 'guess', 'answered_by': 'agent'}]
        with self.assertRaisesRegex(ValueError, 'invented'):
            self.record(analysis)
        analysis = self.analysis()
        analysis['source'] = 'another request'
        with self.assertRaises(ValueError):
            self.record(analysis)
        analysis = self.analysis()
        del analysis['tdd']['REQ-2']['test_command']
        self.record(analysis)
        with self.assertRaisesRegex(ValueError, 'test_command'):
            intake.compile_request(self.flow)
        self.assertFalse((self.flow / 'requirements.yaml').exists())
        self.assertFalse((self.flow / 'reqs').exists())

    def test_enqueue_requires_compiled_req_then_appends_in_dependency_order(self):
        task = self.root / 'tasks/task.json'
        with self.assertRaises((OSError, ValueError)):
            queue.enqueue(self.flow, task, self.project)
        self.record(self.analysis())
        intake.compile_request(self.flow)
        result = queue.enqueue(self.flow, task, self.project)
        payload = json.loads(task.read_text(encoding='utf-8'))
        self.assertTrue(payload['tree']['id'].endswith('REQ-1'))
        self.assertTrue(payload['tree']['children'][0]['id'].endswith('REQ-2'))
        self.assertNotIn('quota_file', payload)
        self.assertNotIn('readiness', payload)
        self.assertEqual(queue.enqueue(self.flow, task, self.project)['status'], 'already_queued')
        self.assertEqual(len(payload['tree']['children']), 1)
        scheduler = Path(__file__).resolve().parents[2] / 'scheduler'
        if scheduler.is_dir():
            status = subprocess.run([sys.executable, '-m', 'reqflow_scheduler', 'status', str(task),
                                     '--state-dir', str(self.root / 'state')], cwd=scheduler,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertEqual(json.loads(status.stdout)['status'], 'queued')
        self.assertFalse((self.root / 'state').exists())
        # Existing trees retain all original prompts and children.
        existing = self.root / 'tasks/existing.json'
        original = {'version': 1, 'id': 'existing', 'workspace': str(self.project),
                    'tree': {'id': 'root', 'prompt': 'existing work', 'children': [{'id': 'other', 'prompt': 'other work'}]}}
        existing.write_text(json.dumps(original), encoding='utf-8')
        queue.enqueue(self.flow, existing, self.project, parent_id='other')
        merged = json.loads(existing.read_text(encoding='utf-8'))
        self.assertEqual(merged['tree']['prompt'], 'existing work')
        self.assertEqual(merged['tree']['children'][0]['prompt'], 'other work')
        state = self.root / 'state/existing/state.json'
        state.parent.mkdir(parents=True)
        state.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'checkpoints'):
            queue.enqueue(self.flow, existing, self.project, state_dir=self.root / 'state')

    def test_compiled_request_is_immutable(self):
        self.record(self.analysis())
        intake.compile_request(self.flow)
        with self.assertRaisesRegex(ValueError, 'immutable'):
            self.record(self.analysis())
        with self.assertRaisesRegex(ValueError, 'already compiled'):
            intake.compile_request(self.flow)

    def test_updated_scheduler_waits_for_window_then_consumes_req_chain(self):
        scheduler = Path(__file__).resolve().parents[2] / 'scheduler'
        if not scheduler.is_dir():
            self.skipTest('adjacent scheduler unavailable')
        sys.path.insert(0, str(scheduler))
        from reqflow_scheduler.scheduler import load_task, tick
        self.record(self.analysis())
        intake.compile_request(self.flow)
        task_file = self.root / 'task.json'
        state_dir = self.root / 'state'
        queue.enqueue(self.flow, task_file, self.project, state_dir)
        self.assertFalse(state_dir.exists())
        task = load_task(task_file)
        prompts = []
        def dispatch(task, state, save, *_args):
            prompts.append(task['prompt'])
            state['status'] = 'completed'
            save(state)
        quota = {'blocked_until': None, 'resets_at': '2026-10-28T01:00:00+00:00'}
        with patch('reqflow_scheduler.scheduler.quota_adapter.query', return_value=quota), patch('reqflow_scheduler.scheduler.dispatch.run', side_effect=dispatch):
            # Beijing 20:00, outside the daytime reset window: no dispatch.
            waiting = tick(task, state_dir, datetime(2026, 10, 27, 12, tzinfo=timezone.utc))
            self.assertEqual(waiting['status'], 'waiting')
            self.assertEqual(prompts, [])
            # Beijing 06:00, sleep window: consume in dependency order.
            completed = tick(task, state_dir, datetime(2026, 10, 27, 22, tzinfo=timezone.utc))
        self.assertEqual(completed['status'], 'completed')
        self.assertIn('Implement only REQ-1', prompts[0])
        self.assertIn('Implement only REQ-2', prompts[1])
