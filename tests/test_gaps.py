from pathlib import Path
import tempfile
import unittest

import yaml

from reqflow import core, gaps
from test_core import tree


class GapTests(unittest.TestCase):
    def test_existing_project_unknowns_block_formal_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flow = root / ".reqflow"
            goal = core.create_goal(flow, "已明确增量目标", [])
            core.approve_goal(flow, goal["id"], "fixture")
            (flow / "import-baseline.yaml").write_text(yaml.safe_dump({"repository": str(root), "existing_test_reports": [{"failures": [{"name": "old failing test"}]}]}), encoding="utf-8")
            candidate = root / "candidate.yaml"
            candidate.write_text(yaml.safe_dump(tree()), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differences"):
                core.publish_requirements(flow, candidate, goal["id"], "fixture")
            self.assertFalse((flow / "requirements.yaml").exists())
            report = gaps.analyze_gaps(flow, tree())
            self.assertEqual(len(report["unresolved"]), 2)
            self.assertEqual(report["historical_test_reports"][0]["failures"][0]["name"], "old failing test")
            decisions = {identity: {"status": "missing", "confirmed_by": "fixture"} for identity in ("REQ-1", "REQ-2")}
            decisions["REQ-1"].update(conflict="test and document disagree")
            (flow / "mappings.yaml").write_text(yaml.safe_dump(decisions), encoding="utf-8")
            self.assertTrue(gaps.analyze_gaps(flow, tree())["unresolved"])
            decisions["REQ-1"]["decision"] = "Approved scenario defines the desired new behavior."
            (flow / "mappings.yaml").write_text(yaml.safe_dump(decisions), encoding="utf-8")
            self.assertFalse(gaps.analyze_gaps(flow, tree())["unresolved"])
            self.assertTrue(core.publish_requirements(flow, candidate, goal["id"], "fixture")["approved"])
