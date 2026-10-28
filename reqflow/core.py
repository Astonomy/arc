"""Deterministic requirement validation and explicitly approved goal revisions."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

import yaml

from .upstream import resolve_contracts


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text")
    return value


def validate_tree(tree):
    if not isinstance(tree, dict):
        raise ValueError("requirements must be a mapping")
    tree = deepcopy(tree)
    if isinstance(tree.get("root"), dict):
        tree = tree["root"]
    elif "id" not in tree and isinstance(tree.get("requirement"), dict):
        tree = tree["requirement"]
    if tree.get("id") != "ROOT":
        raise ValueError("root id must be ROOT")
    if tree.get("type") == "ROOT":
        tree["type"] = "FOLDER"
    if tree.get("type") != "FOLDER":
        raise ValueError("ROOT must be a FOLDER")
    nodes = {}

    def walk(node):
        if not isinstance(node, dict):
            raise ValueError("each requirement must be a mapping")
        identity = _text(node.get("id"), "id")
        if identity in nodes:
            raise ValueError(f"duplicate requirement id: {identity}")
        nodes[identity] = node
        for field in ("name", "description"):
            _text(node.get(field), f"{identity}.{field}")
        if node.get("type") not in {"FOLDER", "ATOMIC"}:
            raise ValueError(f"invalid requirement type: {identity}")
        children = node.get("children", [])
        dependencies = node.get("dependencies", [])
        if not isinstance(children, list) or not isinstance(dependencies, list):
            raise ValueError(f"children/dependencies must be lists: {identity}")
        if any(not isinstance(dep, str) or not dep.strip() for dep in dependencies):
            raise ValueError(f"dependency IDs must be text: {identity}")
        if len(set(dependencies)) != len(dependencies):
            raise ValueError(f"duplicate dependencies: {identity}")
        if node["type"] == "ATOMIC":
            if children:
                raise ValueError(f"ATOMIC cannot have children: {identity}")
            scenarios = node.get("scenarios")
            if not isinstance(scenarios, list) or not scenarios:
                raise ValueError(f"ATOMIC needs acceptance scenarios: {identity}")
            for scenario in scenarios:
                if not isinstance(scenario, dict):
                    raise ValueError(f"scenario must be a mapping: {identity}")
                _text(scenario.get("name"), f"{identity}.scenario.name")
                steps = scenario.get("steps")
                if not isinstance(steps, list):
                    raise ValueError(f"scenario steps must be a list: {identity}")
                keywords = []
                for step in steps:
                    if not isinstance(step, dict) or step.get("keyword") not in {"GIVEN", "WHEN", "THEN", "AND", "BUT"}:
                        raise ValueError(f"invalid scenario step: {identity}")
                    _text(step.get("content"), f"{identity}.step.content")
                    keywords.append(step["keyword"])
                if not all(keyword in keywords for keyword in ("GIVEN", "WHEN", "THEN")) or not keywords.index("GIVEN") < keywords.index("WHEN") < keywords.index("THEN"):
                    raise ValueError(f"scenario requires ordered GIVEN/WHEN/THEN: {identity}")
        elif not children:
            raise ValueError(f"FOLDER needs children: {identity}")
        for child in children:
            walk(child)

    walk(tree)
    graph = {}
    for identity, node in nodes.items():
        dependencies = node.get("dependencies", [])
        if identity in dependencies or any(dep not in nodes for dep in dependencies):
            raise ValueError(f"unknown or self dependency: {identity}")
        graph[identity] = dependencies
    _topological(graph)
    _atomic_plan(tree)  # Folder expansion can introduce additional cycles.
    return resolve_contracts(tree)


def _topological(graph):
    ordered, visiting, visited = [], set(), set()

    def visit(identity):
        if identity in visiting:
            raise ValueError(f"dependency cycle at {identity}")
        if identity in visited:
            return
        visiting.add(identity)
        for dependency in graph[identity]:
            visit(dependency)
        visiting.remove(identity)
        visited.add(identity)
        ordered.append(identity)

    for identity in graph:
        visit(identity)
    return ordered


def _atomic_plan(tree):
    nodes, inherited = {}, {}

    def walk(node, dependencies):
        nodes[node["id"]] = node
        inherited[node["id"]] = [*dependencies, *node.get("dependencies", [])]
        for child in node.get("children", []):
            walk(child, inherited[node["id"]])

    walk(tree, [])

    def leaves(identity):
        node = nodes[identity]
        if node["type"] == "ATOMIC":
            return [identity]
        return [leaf for child in node.get("children", []) for leaf in leaves(child["id"])]

    graph = {
        identity: list(dict.fromkeys(leaf for dep in inherited[identity] for leaf in leaves(dep)))
        for identity, node in nodes.items() if node["type"] == "ATOMIC"
    }
    return [{**deepcopy(nodes[identity]), "dependencies": graph[identity]} for identity in _topological(graph)]


def atomic_plan(tree):
    return _atomic_plan(validate_tree(tree))


def _write(path, value, as_json=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n" if as_json else yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".reqflow-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _goals(flow_dir):
    path = Path(flow_dir) / "goals.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8-sig")) if path.exists() else {"version": 1, "goals": []}


def _goal(data, identity):
    for goal in data["goals"]:
        if goal["id"] == identity:
            return goal
    raise ValueError(f"unknown goal: {identity}")


def _save_goals(flow_dir, data):
    # Invalidate first: a crash cannot leave old approval enabled for edited goals.
    _write(Path(flow_dir) / "readiness.json", {"approved": False, "unresolved": ["goal revision changed"]}, True)
    _write(Path(flow_dir) / "goals.yaml", data)


def create_goal(flow_dir, title, questions):
    _text(title, "goal title")
    if not isinstance(questions, list):
        raise ValueError("questions must be a list")
    for question in questions:
        _text(question, "question")
    data = _goals(flow_dir)
    goal = {"id": f"GOAL-{len(data['goals']) + 1:03d}", "version": 1, "title": title,
            "questions": [{"id": f"Q-{index}", "question": question, "answer": None} for index, question in enumerate(questions, 1)],
            "approved_by": None, "status": "blocked" if questions else "draft"}
    data["goals"].append(goal)
    _save_goals(flow_dir, data)
    return goal


def answer_goal(flow_dir, goal_id, answers):
    if not isinstance(answers, dict) or not answers:
        raise ValueError("answers must be a nonempty Q-ID to text mapping")
    data = _goals(flow_dir)
    goal = _goal(data, goal_id)
    known = {question["id"] for question in goal["questions"]}
    if any(identity not in known for identity in answers):
        raise ValueError("unknown question id")
    for answer in answers.values():
        _text(answer, "answer")
    for question in goal["questions"]:
        if question["id"] in answers:
            question["answer"] = answers[question["id"]]
    goal.update(version=goal["version"] + 1, approved_by=None,
                status="blocked" if any(not item["answer"] for item in goal["questions"]) else "draft")
    _save_goals(flow_dir, data)
    return goal


def approve_goal(flow_dir, goal_id, confirmed_by):
    _text(confirmed_by, "confirmed_by")
    data = _goals(flow_dir)
    goal = _goal(data, goal_id)
    if any(not item["answer"] for item in goal["questions"]):
        raise ValueError("unresolved questions block approval")
    goal.update(status="approved", approved_by=confirmed_by)
    _save_goals(flow_dir, data)
    return goal


def publish_requirements(flow_dir, candidate_path, goal_id, confirmed_by):
    _text(confirmed_by, "confirmed_by")
    flow_dir = Path(flow_dir)
    data = _goals(flow_dir)
    goal = _goal(data, goal_id)
    if goal["status"] != "approved" or not goal["approved_by"]:
        raise ValueError("explicit goal approval is required before publishing")
    unresolved = [f"{item['id']}/{question['id']}" for item in data["goals"] for question in item["questions"] if not question["answer"]]
    if unresolved:
        raise ValueError("unresolved questions block formal requirements")
    tree = validate_tree(yaml.safe_load(Path(candidate_path).read_text(encoding="utf-8-sig")))
    from .gaps import analyze_gaps
    gaps = analyze_gaps(flow_dir, tree)
    if gaps["unresolved"]:
        raise ValueError("existing-project differences require confirmation; see gaps.json")
    _write(flow_dir / "readiness.json", {"approved": False, "unresolved": ["publishing"]}, True)
    _write(flow_dir / "requirements.yaml", tree)
    ready = {"approved": True, "unresolved": [], "goal_id": goal_id, "goal_version": goal["version"],
             "approved_by": confirmed_by, "approved_at": datetime.now(timezone.utc).isoformat(),
             "requirements_sha256": hashlib.sha256((flow_dir / "requirements.yaml").read_bytes()).hexdigest(),
             "goals_sha256": hashlib.sha256((flow_dir / "goals.yaml").read_bytes()).hexdigest()}
    if (flow_dir / "project.yaml").exists():
        ready["project_sha256"] = hashlib.sha256((flow_dir / "project.yaml").read_bytes()).hexdigest()
    _write(flow_dir / "readiness.json", ready, True)
    return ready
