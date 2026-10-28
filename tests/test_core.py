from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import yaml

from reqflow.core import (approve_goal, answer_goal, atomic_plan, create_goal,
                          publish_requirements, validate_tree)


def atomic(identity, dependencies=None):
    return {"id": identity, "name": identity, "type": "ATOMIC", "description": "可验证行为",
            "dependencies": dependencies or [], "scenarios": [{"name": "正常场景", "steps": [
                {"keyword": keyword, "content": keyword + " condition"} for keyword in ("GIVEN", "WHEN", "THEN")]}]}


def tree():
    return {"id": "ROOT", "type": "FOLDER", "name": "目标", "description": "目标集", "children": [atomic("REQ-1"), atomic("REQ-2", ["REQ-1"])]}


class RequirementTests(unittest.TestCase):
    def test_wrappers_and_upstream_fields_preserved(self):
        source = tree()
        source["children"][0]["visual_reference"] = ["reference/page.png"]
        result = validate_tree({"root": source})
        self.assertEqual(result["children"][0]["visual_reference"], ["reference/page.png"])
        self.assertNotIn("resolved_data", source)
        self.assertIn("resolved_data", result)

    def test_missing_duplicate_and_cyclic_dependencies(self):
        for dependency in ("missing", "REQ-2"):
            candidate = tree()
            candidate["children"][0]["dependencies"] = [dependency]
            with self.assertRaises(ValueError):
                validate_tree(candidate)
        candidate = tree()
        candidate["children"][1]["id"] = "REQ-1"
        with self.assertRaises(ValueError):
            validate_tree(candidate)

    def test_malformed_scenarios_and_nodes_rejected(self):
        for mutation in (lambda t: t["children"][0].update(scenarios=[]),
                         lambda t: t["children"][0]["scenarios"][0]["steps"].reverse(),
                         lambda t: t["children"][0].update(children=[atomic("REQ-3")]),
                         lambda t: t["children"][0].update(description=" ")):
            candidate = tree()
            mutation(candidate)
            with self.assertRaises(ValueError):
                validate_tree(candidate)

    def test_folder_dependencies_expand_and_inherit(self):
        source = tree()
        source["children"] = [
            {"id": "SCOPE-2", "type": "FOLDER", "name": "第二阶段", "description": "后继", "dependencies": ["SCOPE-1"], "children": [atomic("REQ-3")]},
            {"id": "SCOPE-1", "type": "FOLDER", "name": "第一阶段", "description": "前置", "children": [atomic("REQ-1"), atomic("REQ-2")]},
        ]
        plan = atomic_plan(source)
        self.assertEqual([item["id"] for item in plan], ["REQ-1", "REQ-2", "REQ-3"])
        self.assertEqual(plan[-1]["dependencies"], ["REQ-1", "REQ-2"])

    def test_expanded_folder_cycle_rejected(self):
        source = tree()
        source["children"][0]["dependencies"] = ["ROOT"]
        with self.assertRaises(ValueError):
            validate_tree(source)

    def test_upstream_data_contract_is_reused(self):
        source = tree()
        source["children"][0]["data"] = {"requires": ["unknown-data"]}
        with self.assertRaisesRegex(ValueError, "Unknown data"):
            validate_tree(source)


class GoalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.flow = Path(self.directory.name) / ".reqflow"
        self.candidate = Path(self.directory.name) / "candidate.yaml"
        self.candidate.write_text(yaml.safe_dump(tree(), allow_unicode=True), encoding="utf-8")

    def test_unanswered_and_unapproved_never_publish(self):
        goal = create_goal(self.flow, "实现搜索", ["使用哪种数据源？"])
        with self.assertRaises(ValueError):
            approve_goal(self.flow, goal["id"], "developer")
        with self.assertRaises(ValueError):
            publish_requirements(self.flow, self.candidate, goal["id"], "developer")
        self.assertFalse((self.flow / "requirements.yaml").exists())
        answer_goal(self.flow, goal["id"], {"Q-1": "现有 PostgreSQL"})
        with self.assertRaises(ValueError):
            publish_requirements(self.flow, self.candidate, goal["id"], "developer")
        self.assertFalse((self.flow / "requirements.yaml").exists())

    def test_answer_approve_publish_and_edit_revokes_readiness(self):
        goal = create_goal(self.flow, "实现搜索", ["数据源？"])
        revised = answer_goal(self.flow, goal["id"], {"Q-1": "PostgreSQL"})
        self.assertEqual(revised["version"], 2)
        approve_goal(self.flow, goal["id"], "developer")
        ready = publish_requirements(self.flow, self.candidate, goal["id"], "developer")
        self.assertTrue(ready["approved"])
        self.assertEqual(ready["goal_version"], 2)
        self.assertIn("goals_sha256", ready)
        answer_goal(self.flow, goal["id"], {"Q-1": "修改后的决定"})
        self.assertFalse(json.loads((self.flow / "readiness.json").read_text(encoding="utf-8"))["approved"])
        with self.assertRaises(ValueError):
            publish_requirements(self.flow, self.candidate, goal["id"], "developer")

    def test_other_unresolved_goal_blocks_publish(self):
        approved = create_goal(self.flow, "已明确目标", [])
        approve_goal(self.flow, approved["id"], "developer")
        create_goal(self.flow, "待澄清目标", ["待决定问题"])
        with self.assertRaisesRegex(ValueError, "unresolved"):
            publish_requirements(self.flow, self.candidate, approved["id"], "developer")

    def test_invalid_answer_or_empty_confirmer_does_not_approve(self):
        goal = create_goal(self.flow, "目标", ["问题"])
        for answers in ({"other": "答案"}, {"Q-1": ""}, {}):
            with self.assertRaises(ValueError):
                answer_goal(self.flow, goal["id"], answers)
        with self.assertRaises(ValueError):
            approve_goal(self.flow, goal["id"], "")


if __name__ == "__main__":
    unittest.main()
