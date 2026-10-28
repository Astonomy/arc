import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import yaml

from reqflow.cli import main
from reqflow.view import render_view
from test_core import tree


class CliViewTests(unittest.TestCase):
    def test_clarification_to_publish_through_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flow = root / ".reqflow"
            candidate = root / "candidate.yaml"
            candidate.write_text(yaml.safe_dump(tree(), allow_unicode=True), encoding="utf-8")
            prefix = ["--flow-dir", str(flow)]
            commands = [
                ["goal-add", "目标", "--question", "采用现有数据库？"],
                ["goal-answer", "GOAL-001", "Q-1", "采用现有 PostgreSQL"],
                ["goal-approve", "GOAL-001", "--by", "test-fixture"],
                ["publish", str(candidate), "--goal", "GOAL-001", "--by", "test-fixture"],
                ["plan"],
                ["view", "--output", str(root / "report.html")],
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                for command in commands:
                    self.assertEqual(main(prefix + command), 0, command)
            self.assertIn("REQ-1", (flow / "requirements.md").read_text(encoding="utf-8"))
            document = (root / "report.html").read_text(encoding="utf-8")
            self.assertIn("GOAL-001", document)
            self.assertIn("需求详情", document)

    def test_view_embedded_data_cannot_close_script_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            flow = Path(directory)
            payload = tree()
            payload["name"] = "</script><script>alert('unsafe')</script>"
            (flow / "requirements.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")
            output = render_view(flow, flow / "report.html")
            document = output.read_text(encoding="utf-8")
            self.assertNotIn(payload["name"], document)
            start = document.index('<script id="data" type="application/json">')
            data = document[start:].split(">", 1)[1].split("</script>", 1)[0]
            self.assertEqual(json.loads(data)["requirements"]["name"], payload["name"])


if __name__ == "__main__":
    unittest.main()
