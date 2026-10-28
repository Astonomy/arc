"""Persist natural-language analysis and compile only complete TDD requirements.

Semantic analysis is supplied by the calling skill/agent; this module validates
its records rather than guessing business decisions from keywords.
"""
from pathlib import Path
import re
import uuid

import yaml

from . import core, view


def initialize(project):
    project = Path(project).resolve()
    if not project.is_dir():
        raise ValueError("project directory must exist")
    folder = project / ".arc"
    if folder.is_symlink():
        raise ValueError('project .arc must be a local directory, not a symlink')
    folder.mkdir(exist_ok=True)
    if not (folder / "project.yaml").exists():
        core._write(folder / "project.yaml", {"version": 1, "workspace": str(project)})
    return folder


def intake(project, text):
    core._text(text, "natural-language request")
    folder = initialize(project)
    # Repeated invocation of the same request reuses its clarification history.
    for previous in sorted((folder / "requests").glob("*/source.md")):
        if previous.read_text(encoding="utf-8") == text:
            return {"flow_dir": str(previous.parent), "status": "existing"}
    flow = folder / "requests" / uuid.uuid4().hex[:12]
    flow.mkdir(parents=True)
    (flow / "source.md").write_text(text, encoding="utf-8")
    core._write(flow / "project.yaml", yaml.safe_load((folder / "project.yaml").read_text(encoding="utf-8")))
    for name in ('import-baseline.yaml', 'mappings.yaml'):
        if (folder / name).exists():
            (flow / name).write_bytes((folder / name).read_bytes())
    core._write(flow / "analysis.yaml", {"status": "pending", "source": text, "questions": []})
    return {"flow_dir": str(flow), "status": "pending_analysis"}


def read_analysis(flow):
    flow = Path(flow)
    analysis = yaml.safe_load((flow / "analysis.yaml").read_text(encoding="utf-8"))
    if not isinstance(analysis, dict) or analysis.get("source") != (flow / "source.md").read_text(encoding="utf-8"):
        raise ValueError("analysis must refer to the current source text")
    questions = analysis.get("questions")
    if not isinstance(questions, list):
        raise ValueError("analysis.questions must be a list")
    seen = set()
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError("question must be a mapping")
        identity = core._text(question.get("id"), "question.id")
        core._text(question.get("question"), "question.question")
        if identity in seen:
            raise ValueError("duplicate question id")
        seen.add(identity)
    return analysis


def analyze(flow, review):
    flow = Path(flow)
    if (flow / "requirements.yaml").exists():
        raise ValueError("compiled request is immutable; intake a revised request")
    analysis = yaml.safe_load(Path(review).read_text(encoding="utf-8-sig"))
    if not isinstance(analysis, dict) or analysis.get("source") != (flow / "source.md").read_text(encoding="utf-8"):
        raise ValueError("review must include the exact source text")
    # Validate in memory before replacing the persisted review.
    questions = analysis.get("questions")
    if not isinstance(questions, list) or any(not isinstance(q, dict) or not q.get("id") or not q.get("question") for q in questions):
        raise ValueError("review needs a questions list with id/question records")
    previous = read_analysis(flow)
    answers = {q['id']: q for q in previous['questions'] if q.get('answer') and q.get('answered_by')}
    for q in questions:
        old = answers.get(q['id'])
        if old and old['question'] == q['question']:
            q.update(answer=old['answer'], answered_by=old['answered_by'])
        elif q.get('answer') or q.get('answered_by'):
            raise ValueError("developer answers must be recorded with answer, not invented in review")
    if set(answers) - {q['id'] for q in questions}:
        raise ValueError("review cannot discard recorded clarification answers")
    for old in previous['questions']:
        if not any(q['id'] == old['id'] and q['question'] == old['question'] for q in questions):
            raise ValueError("review cannot discard or replace a clarification question")
    core._write(flow / "analysis.yaml", analysis)
    return {"status": "analyzed", "questions": questions}


def answer(flow, question_id, text, by):
    flow = Path(flow)
    if (flow / "requirements.yaml").exists():
        raise ValueError("compiled request is immutable; intake a revised request")
    analysis = read_analysis(flow)
    core._text(text, "answer")
    core._text(by, "answered_by")
    question = next((q for q in analysis['questions'] if q['id'] == question_id), None)
    if question is None:
        raise ValueError("unknown clarification question")
    question.update(answer=text, answered_by=by)
    analysis['status'] = 'pending_review'
    core._write(flow / "analysis.yaml", analysis)
    return {"status": "pending_review", "question": question}


def compile_request(flow):
    flow = Path(flow)
    if (flow / "requirements.yaml").exists():
        raise ValueError("request already compiled; reuse its REQ files")
    analysis = read_analysis(flow)
    unresolved = [q for q in analysis['questions'] if not (q.get('answer') and q.get('answered_by'))]
    if unresolved:
        return {"status": "needs_clarification", "questions": unresolved}
    if analysis.get('status') != 'ready':
        raise ValueError("semantic analysis must be ready; re-review after clarification")
    reviewer = core._text(analysis.get('reviewed_by'), 'reviewed_by')
    tree = core.validate_tree(analysis.get('requirements'))
    plan = core.atomic_plan(tree)
    tdd = analysis.get('tdd', {})
    for req in plan:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,70}', req['id']):
            raise ValueError("REQ id must be a safe filename/identifier")
        item = tdd.get(req['id'], {})
        for field in ('test_command', 'tests', 'code'):
            values = item.get(field)
            if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError(f"{req['id']} needs TDD {field}")
        core._text(item.get('red'), req['id'] + '.red')
        scopes = item.get('interface_scopes', {})
        if not isinstance(scopes, dict) or any(path not in item['code'] or not isinstance(scope, str) or not scope.strip() for path, scope in scopes.items()):
            raise ValueError(f"{req['id']} interface_scopes must map planned code paths to scope names")
    from .gaps import analyze_gaps
    if analyze_gaps(flow, tree, save=False)['unresolved']:
        raise ValueError("existing-project differences need clarification")
    # No requirement files are written until every clarification/schema/TDD check passes.
    candidate = flow / 'requirements.candidate.yaml'
    core._write(candidate, tree)
    goal = core.create_goal(flow, tree['name'], [])
    core.approve_goal(flow, goal['id'], reviewer)
    core.publish_requirements(flow, candidate, goal['id'], reviewer)
    (flow / 'requirements.md').write_text(view.render_markdown(tree), encoding='utf-8')
    for req in plan:
        core._write(flow / 'reqs' / (req['id'] + '.yaml'), {"requirement": req, "tdd": tdd[req['id']]})
    return {"status": "compiled", "flow_dir": str(flow.resolve()), "requirements": [r['id'] for r in plan]}
