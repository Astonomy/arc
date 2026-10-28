"""Export gated scheduler waves and record actual subprocess verification evidence."""
from datetime import datetime, timezone
import hashlib
import fnmatch
import json
from pathlib import Path
import subprocess
import uuid
import threading

import yaml

from .core import atomic_plan, validate_tree


def _read(path, default=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _approved(flow_dir):
    ready = _read(flow_dir / "readiness.json", {})
    if ready.get("approved") is not True or ready.get("unresolved") != []:
        raise ValueError("requirements have unresolved questions or lack approval")
    for key, filename in (("requirements_sha256", "requirements.yaml"), ("goals_sha256", "goals.yaml")):
        if ready.get(key) != _digest(flow_dir / filename):
            raise ValueError(f"{filename} changed after approval")
    if "project_sha256" in ready and ready["project_sha256"] != _digest(flow_dir / "project.yaml"):
        raise ValueError("project configuration changed after approval")
    if not ready.get("approved_by"):
        raise ValueError("approval requires approved_by")
    return ready


def _plan(flow_dir):
    tree = yaml.safe_load((flow_dir / "requirements.yaml").read_text(encoding="utf-8-sig"))
    return atomic_plan(validate_tree(tree))


def _project(flow_dir):
    path = flow_dir / "project.yaml"
    return (yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}) if path.exists() else {}


def _workspace_guard(flow_dir, workspace):
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise ValueError("execution workspace must exist")
    config = _project(flow_dir)
    repository = config.get("repository")
    if config.get('execution_mode') == 'in-place' and repository and workspace == Path(repository).resolve():
        return workspace
    if repository and workspace == Path(repository).resolve():
        raise ValueError("imported repository must execute in an isolated Git worktree")
    if repository:
        result = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=repository,
                                capture_output=True, text=True, timeout=30)
        members = [Path(line[9:]).resolve() for line in result.stdout.splitlines() if line.startswith("worktree ")]
        if result.returncode or workspace not in members:
            raise ValueError("workspace is not a registered worktree of the imported repository")
    return workspace


def _trace(flow_dir):
    trace = _read(flow_dir / "traceability.json", {"version": 1, "requirements": {}})
    if trace.get("version") != 1 or not isinstance(trace.get("requirements"), dict):
        raise ValueError("invalid traceability metadata")
    return trace


def _accepted(entry, digest, workspace):
    return bool(entry and entry.get("status") == "accepted" and entry.get("requirements_sha256") == digest
                and entry.get("workspace") == str(workspace)
                and any(r.get("exit_code") == 0 and not r.get("timed_out") for r in entry.get("test_runs", [])))


def export_tasks(flow_dir: Path, workspace: Path, quota_file: Path, output_dir: Path,
                 scope: list[str] | None = None) -> list[dict]:
    flow_dir, output_dir = Path(flow_dir).resolve(), Path(output_dir).resolve()
    ready = _approved(flow_dir)
    workspace = _workspace_guard(flow_dir, Path(workspace))
    plan = _plan(flow_dir)
    ids = {item["id"] for item in plan}
    selected = set(scope) if scope is not None else ids
    if selected - ids:
        raise ValueError("scope contains unknown or non-atomic requirements")
    trace = _trace(flow_dir)["requirements"]
    digest = ready["requirements_sha256"]
    project = _project(flow_dir)
    if project.get("repository") and not project.get("allowed_paths"):
        raise ValueError("imported projects require explicit allowed_paths before export")
    exported = []
    for requirement in plan:
        req_id = requirement["id"]
        if req_id not in selected or _accepted(trace.get(req_id), digest, workspace):
            continue
        if any(not _accepted(trace.get(dep), digest, workspace) for dep in requirement.get("dependencies", [])):
            continue
        prompt = (
            f"Implement only approved requirement {req_id}: {requirement.get('name', '')}\n"
            f"Requirement: {json.dumps(requirement, ensure_ascii=False)}\n"
            f"Project constraints: {json.dumps(project, ensure_ascii=False)}\n"
            f"Requirement source: {flow_dir / 'requirements.yaml'}\n"
            "Use test-first development: write/run a failing test (RED), implement the smallest change (GREEN), "
            "then run regression tests. Preserve the existing architecture and unrelated files. "
            "Respect configured allowed_paths and stop on conflicts or unclear behavior. "
            "Save an artifact receipt with REQ id, test argv and exit codes, changed code paths and logs. "
            "Do not mark acceptance yourself; Reqflow must verify actual test execution."
        )
        identity = hashlib.sha256((str(workspace) + digest + req_id + prompt).encode()).hexdigest()[:20]
        task = dict(version=1, id=f"req-{identity}", workspace=str(workspace), prompt=prompt,
                    requirements=str(flow_dir / "requirements.yaml"), readiness=str(flow_dir / "readiness.json"),
                    quota_file=str(Path(quota_file).resolve()), min_remaining_percent=10, require_clean=True)
        if project.get("codex"):
            task["codex"] = project["codex"]
        _write(output_dir / (task["id"] + ".json"), task)
        exported.append(task)
    return exported


def _artifact_paths(items, workspace, flow_dir, allow_runs=False):
    result = []
    for item in items:
        path = (workspace / item).resolve()
        allowed = path.is_relative_to(workspace) or (allow_runs and path.is_relative_to(flow_dir / "runs"))
        if not allowed or not path.is_file():
            raise ValueError(f"artifact missing or outside permitted directories: {item}")
        result.append(str(path))
    return result


def record_evidence(flow_dir, req_id, workspace, tests: list[str], code: list[str], logs: list[str], status: str,
                    interface_scopes=None) -> dict:
    flow_dir, workspace = Path(flow_dir).resolve(), Path(workspace).resolve()
    if status not in {"pending", "failed", "accepted"}:
        raise ValueError("status must be pending, failed or accepted")
    ready = _approved(flow_dir)
    if req_id not in {item["id"] for item in _plan(flow_dir)}:
        raise ValueError("unknown atomic requirement")
    trace = _trace(flow_dir)
    existing = trace["requirements"].get(req_id, {})
    if status == "accepted" and not _accepted(existing, ready["requirements_sha256"], workspace):
        raise ValueError("acceptance requires a successful verify run for current requirements/workspace")
    entry = {**existing, "status": status, "requirements_sha256": ready["requirements_sha256"],
             "workspace": str(workspace), "tests": _artifact_paths(tests, workspace, flow_dir),
             "code": _artifact_paths(code, workspace, flow_dir),
             "logs": _artifact_paths(logs, workspace, flow_dir, allow_runs=True)}
    if interface_scopes is not None:
        if not isinstance(interface_scopes, dict):
            raise ValueError('interface_scopes must map code paths to scope names')
        scopes = {}
        for path, scope in interface_scopes.items():
            if not isinstance(path, str) or not isinstance(scope, str) or not scope.strip():
                raise ValueError('interface scope requires a code path and nonempty name')
            resolved = str((workspace / path).resolve())
            if resolved not in entry['code']:
                raise ValueError('interface scope path must be in associated code')
            scopes[resolved] = scope.strip()
        entry['interface_scopes'] = scopes
    trace["requirements"][req_id] = entry
    _write(flow_dir / "traceability.json", trace)
    return entry


def verify_requirement(flow_dir, req_id, workspace, command: list[str], *, _auto=True) -> dict:
    flow_dir = Path(flow_dir).resolve()
    ready = _approved(flow_dir)
    workspace = _workspace_guard(flow_dir, Path(workspace))
    plan = _plan(flow_dir)
    if req_id not in {item["id"] for item in plan}:
        raise ValueError("unknown atomic requirement")
    if not isinstance(command, list) or not command or not all(isinstance(arg, str) and arg for arg in command):
        raise ValueError("test command must be a nonempty argv array")
    if Path(command[0]).suffix.lower() in {".cmd", ".bat"}:
        raise ValueError("use the test program executable directly; batch shims are unsupported")
    trace = _trace(flow_dir)
    dependencies = next(item for item in plan if item["id"] == req_id).get("dependencies", [])
    if any(not _accepted(trace["requirements"].get(dep), ready["requirements_sha256"], workspace) for dep in dependencies):
        raise ValueError("prerequisite requirements must be accepted first")
    run_id = uuid.uuid4().hex
    run_dir = flow_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    run = dict(id=run_id, command=command, started_at=datetime.now(timezone.utc).isoformat(),
               requirements_sha256=ready["requirements_sha256"], timed_out=False)
    previous = trace['requirements'].get(req_id, {})
    history = previous.get('test_runs', []) if previous.get('requirements_sha256') == ready['requirements_sha256'] and previous.get('workspace') == str(workspace) else []
    _write(flow_dir / 'traceability.json', {**trace, 'requirements': {**trace['requirements'], req_id: {
        **previous, 'status': 'running', 'requirements_sha256': ready['requirements_sha256'],
        'workspace': str(workspace), 'test_runs': [*history, run]}}})
    with (run_dir / "stdout.log").open("wb") as stdout, (run_dir / "stderr.log").open("wb") as stderr:
        try:
            result = subprocess.run(command, cwd=workspace, stdout=stdout, stderr=stderr, timeout=300)
            run["exit_code"] = result.returncode
        except subprocess.TimeoutExpired:
            run.update(exit_code=None, timed_out=True)
        except OSError as exc:
            run.update(exit_code=None, error=str(exc))
    run.update(finished_at=datetime.now(timezone.utc).isoformat(), stdout=str(run_dir / "stdout.log"), stderr=str(run_dir / "stderr.log"))
    # A requirement file edited during the test invalidates that run's acceptance.
    try:
        unchanged = ready == _approved(flow_dir)
    except (ValueError, OSError):
        unchanged = False
    allowed_paths = _project(flow_dir).get("allowed_paths", [])
    if allowed_paths:
        project = _project(flow_dir)
        baseline_path = flow_dir / "import-baseline.yaml"
        baseline = yaml.safe_load(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else {}
        base = project.get("base_commit") or (baseline or {}).get("git", {}).get("head")
        if not base and project.get("repository"):
            original = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project["repository"], capture_output=True, text=True, timeout=30)
            base = original.stdout.strip() if original.returncode == 0 else None
        changed = subprocess.run(["git", "diff", "--name-only", base or "HEAD", "-z"], cwd=workspace, capture_output=True, timeout=30)
        untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=workspace, capture_output=True, timeout=30)
        paths = (changed.stdout + untracked.stdout).decode("utf-8").split("\0")
        violations = [path for path in paths if path and not path.startswith('.arc/') and not any(fnmatch.fnmatchcase(path, pattern) for pattern in allowed_paths)]
        if changed.returncode or untracked.returncode or violations:
            unchanged = False
            run["scope_violations"] = violations
    _write(run_dir / "result.json", run)
    existing = trace["requirements"].get(req_id, {})
    runs = existing.get("test_runs", []) if existing.get("requirements_sha256") == ready["requirements_sha256"] and existing.get("workspace") == str(workspace) else []
    entry = {**existing, "status": "accepted" if run["exit_code"] == 0 and unchanged else "failed",
             "requirements_sha256": ready["requirements_sha256"], "workspace": str(workspace),
             "test_runs": [*runs, run], "logs": [str(run_dir / "stdout.log"), str(run_dir / "stderr.log")]}
    trace["requirements"][req_id] = entry
    _write(flow_dir / "traceability.json", trace)
    if _auto and entry["status"] == "failed" and _project(flow_dir).get("auto_rerun") is True:
        rerun_failed(flow_dir, [req_id])
        return _trace(flow_dir)["requirements"][req_id]
    return entry


_rerun_lock = threading.Lock()


def rerun_failed(flow_dir, req_ids=None):
    """Repair failed requirements and verify their original commands."""
    flow = Path(flow_dir).resolve()
    if not _rerun_lock.acquire(blocking=False):
        raise ValueError("a re-run is already in progress")
    state = {"status": "running"}
    try:
        _approved(flow)
        plan = {req['id']: req for req in _plan(flow)}
        failed = {key: entry for key, entry in _trace(flow)['requirements'].items()
                  if entry.get('status') == 'failed' and entry.get('test_runs')}
        selected = list(failed) if req_ids is None else req_ids
        if not selected or any(key not in failed for key in selected):
            raise ValueError("re-run requires failed tests")
        _write(flow / 'rerun.json', state)
        for req_id in selected:
            commands = []
            for previous_run in failed[req_id]['test_runs']:
                command = previous_run['command']
                if command not in commands:
                    commands.append(command)
            while True:
                ready = _approved(flow)
                entry = _trace(flow)['requirements'][req_id]
                workspace = _workspace_guard(flow, Path(entry['workspace']))
                if entry.get('requirements_sha256') != ready['requirements_sha256']:
                    raise ValueError('failed tests refer to outdated requirements')
                run = entry['test_runs'][-1]
                errors = {}
                for key in ('stdout', 'stderr'):
                    path = Path(run.get(key, ''))
                    if path.is_file() and path.resolve().is_relative_to(flow / 'runs'):
                        errors[key] = path.read_text(encoding='utf-8', errors='replace')
                receipt = flow / 'reqs' / (req_id + '.yaml')
                prompt = (
                    f"Repair only the scope of approved requirement {req_id}.\n"
                    f"Original requirement: {json.dumps(plan[req_id], ensure_ascii=False)}\n"
                    f"Original request: {(flow / 'source.md').read_text(encoding='utf-8') if (flow / 'source.md').exists() else ''}\n"
                    f"TDD plan: {receipt.read_text(encoding='utf-8') if receipt.exists() else ''}\n"
                    f"Project constraints: {json.dumps(_project(flow), ensure_ascii=False)}\n"
                    f"Failed test: {json.dumps(run, ensure_ascii=False)}\n"
                    f"Test output: {json.dumps(errors, ensure_ascii=False)}\n"
                    "Fix the implementation using the original requirements and test errors. "
                    "Preserve unrelated scopes. Do not weaken tests, edit ARC metadata or invoke ARC verify; "
                    "the caller will rerun the original test command."
                )
                repair_dir = flow / 'runs' / ('repair-' + uuid.uuid4().hex)
                repair_dir.mkdir(parents=True)
                state.update(req_id=req_id, logs=str(repair_dir))
                _write(flow / 'rerun.json', state)
                with (repair_dir / 'stdout.log').open('wb') as out, (repair_dir / 'stderr.log').open('wb') as err:
                    scheduler = _read(flow / 'scheduler.json')
                    if scheduler is not None:
                        from .queue import schedule_repair
                        schedule_repair(flow, workspace, req_id, prompt, scheduler, state, out, err)
                    else:
                        result = subprocess.run(['codex', 'exec', '--full-auto', '-'], cwd=workspace,
                                                input=prompt, text=True, encoding='utf-8', stdout=out, stderr=err)
                        if result.returncode:
                            raise ValueError(f"Codex repair failed (exit {result.returncode}); see {repair_dir}")
                for command in commands:
                    entry = verify_requirement(flow, req_id, workspace, command, _auto=False)
                    if entry['status'] != 'accepted':
                        break
                if entry['status'] == 'accepted' or _project(flow).get('auto_rerun') is not True:
                    break
        state['status'] = 'finished'
        return {key: _trace(flow)['requirements'][key] for key in selected}
    except Exception as exc:
        state.update(status='failed', error=str(exc))
        raise
    finally:
        _write(flow / 'rerun.json', state)
        _rerun_lock.release()
