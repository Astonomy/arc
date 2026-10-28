"""Append compiled REQ work to an unstarted scheduler tree, never dispatch it."""
from copy import deepcopy
import json
import subprocess
import sys
import uuid
from pathlib import Path

import yaml

from . import core, execution


def enqueue(flow, task_file, workspace, state_dir=None, parent_id=None):
    flow, task_file, workspace = Path(flow).resolve(), Path(task_file).resolve(), Path(workspace).resolve()
    if not workspace.is_dir():
        raise ValueError('workspace must exist')
    if task_file.is_relative_to(workspace):
        raise ValueError('scheduler task and runtime state belong outside the workspace')
    execution._approved(flow)
    plan = execution._plan(flow)
    # Each node embeds the compiled file, including its executable TDD plan.
    receipts = []
    from .intake import read_analysis
    analysis = read_analysis(flow) if (flow / 'source.md').exists() else None
    for req in plan:
        path = flow / 'reqs' / (req['id'] + '.yaml')
        receipt = yaml.safe_load(path.read_text(encoding='utf-8'))
        if receipt.get('requirement') != req or not receipt.get('tdd'):
            raise ValueError('REQ receipt differs from compiled requirements')
        if analysis and receipt['tdd'] != analysis.get('tdd', {}).get(req['id']):
            raise ValueError('REQ TDD receipt differs from reviewed analysis')
        receipts.append((req, path, receipt))
    state_dir = Path(state_dir or Path.home() / '.reqflow-scheduler').resolve()
    if state_dir.is_relative_to(workspace):
        raise ValueError('scheduler runtime state belongs outside the workspace')
    if task_file.exists():
        task = json.loads(task_file.read_text(encoding='utf-8-sig'))
        if task.get('version') != 1 or 'tree' not in task:
            raise ValueError('existing task must be a scheduler v1 tree')
        if (task_file.parent / task['workspace']).resolve() != workspace:
            raise ValueError('task workspace differs')
    else:
        identity = 'arc-' + flow.name + '-' + execution._digest(flow / 'requirements.yaml')[:12]
        task = dict(version=1, id=identity, workspace=str(workspace))
        config = execution._project(flow)
        if config.get('codex'):
            task['codex'] = config['codex']
    if (state_dir / task['id'] / 'state.json').exists():
        raise ValueError('task has scheduling checkpoints; use a new task file/id')

    def walk(node):
        yield node
        for child in node.get('children', []):
            yield from walk(child)

    task = deepcopy(task)
    existing = list(walk(task['tree'])) if 'tree' in task else []
    # Namespace REQs so separate requests may use the same local IDs.
    prefix = 'arc-' + flow.name + '-'
    nodes = []
    for req, path, receipt in receipts:
        prompt = (
            f"Implement only {req['id']} from ARC REQ file {path}.\n"
            f"Compiled REQ and TDD plan:\n{yaml.safe_dump(receipt, allow_unicode=True, sort_keys=False)}\n"
            f"ARC flow directory: {flow}\n"
            "Check that the REQ file still matches this task; stop on changes or unclear requirements. "
            "Do not enqueue this task again. Run the specified failing test first (RED), implement the minimum "
            "change (GREEN), then run regression tests. Verify prerequisite REQs have passing evidence before "
            "starting. Use ARC verify/evidence to record real results, test/code paths and logs in this flow. "
            "If tests or prerequisite verification fail, stop and report the failure; do not claim acceptance."
        )
        nodes.append(dict(id=prefix + req['id'], prompt=prompt, children=[]))
    existing_by_id = {n['id']: n for n in existing}
    duplicates = [n for n in nodes if n['id'] in existing_by_id]
    if duplicates:
        if len(duplicates) == len(nodes) and all(existing_by_id[n['id']]['prompt'] == n['prompt'] for n in nodes):
            return {"status": "already_queued", "task": str(task_file), "id": task['id']}
        raise ValueError('partial or conflicting REQ nodes already exist')
    # A linear child chain enforces topological order under scheduler DFS, including joins.
    for first, second in zip(nodes, nodes[1:]):
        first['children'].append(second)
    if existing:
        if parent_id:
            parent = existing_by_id.get(parent_id)
            if parent is None:
                raise ValueError('unknown scheduler parent node')
        else:
            parent = task['tree']
        parent.setdefault('children', []).append(nodes[0])
    else:
        if parent_id:
            raise ValueError('parent requires an existing task tree')
        task['tree'] = nodes[0]
    core._write(task_file, task, as_json=True)
    execution._write(flow / 'scheduler.json', {"task": str(task_file), "id": task['id'], "state_dir": str(state_dir)})
    return {"status": "queued", "task": str(task_file), "id": task['id'], "nodes": [n['id'] for n in nodes]}



def schedule_repair(flow, workspace, req_id, prompt, scheduler, state, stdout, stderr):
    """Submit a fresh immutable task and wait for scheduler-controlled execution."""
    source_path = Path(scheduler['task']).resolve()
    source = json.loads(source_path.read_text(encoding='utf-8-sig'))
    if (source_path.parent / source['workspace']).resolve() != workspace:
        raise ValueError('scheduler workspace differs from failed test workspace')
    task = {**source, 'id': 'arc-rerun-' + uuid.uuid4().hex,
            'workspace': str(workspace),
            'tree': {'id': req_id, 'prompt': prompt, 'children': []}}
    task.pop('prompt', None)
    task_path = source_path.parent / (task['id'] + '.json')
    state_dir = Path(scheduler['state_dir']).resolve()
    if task_path.is_relative_to(workspace) or state_dir.is_relative_to(workspace):
        raise ValueError('scheduler tasks and state must stay outside workspace')
    execution._write(task_path, task)
    state.update(scheduler_task=str(task_path), scheduler_id=task['id'], status='running')
    execution._write(flow / 'rerun.json', state)
    scheduler_repo = Path(__file__).resolve().parents[2] / 'scheduler'
    python = scheduler_repo / '.venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    if not scheduler_repo.is_dir():
        raise ValueError('scheduler checkout unavailable; re-run task saved for scheduling')
    result = subprocess.run([str(python) if python.exists() else sys.executable,
                             '-m', 'reqflow_scheduler', 'watch', str(task_path),
                             '--state-dir', str(state_dir)], cwd=scheduler_repo,
                            stdout=stdout, stderr=stderr)
    checkpoint = execution._read(state_dir / task['id'] / 'state.json', {})
    if result.returncode or checkpoint.get('status') != 'completed':
        raise ValueError(f"scheduler repair did not complete; inspect {task_path}")
