import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

from reqflow.importer import scan_project, write_import


class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()

    def put(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_inventory_does_not_modify_business_files_or_promote_inferences(self):
        self.put("package.json", json.dumps({"scripts": {"test": "vitest run"}, "dependencies": {"next": "1", "pg": "1"}, "engines": {"node": ">=24"}}))
        self.put("apps/web/package.json", json.dumps({"dependencies": {"vue": "1"}}))
        self.put("tests/account.test.ts", "// TODO confirm behavior")
        self.put("docs/API.md", "A candidate description")
        self.put(".github/workflows/test.yml", "name: Tests")
        self.put("packages/db/migrations/001.sql", "select 1;")
        self.put("apps/api/route.ts", "export {};")
        before = {path.relative_to(self.repo).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.repo.rglob("*") if path.is_file()}
        baseline = write_import(self.repo, self.root / "output")
        after = {path.relative_to(self.repo).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.repo.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(baseline["test_execution"], "not_run")
        self.assertTrue({"nextjs", "vue", "postgresql", "node >=24"}.issubset(baseline["stack"]))
        self.assertFalse(baseline["commands"][0]["confirmed"])
        self.assertIn("apps/api/route.ts", baseline["discovery"]["api"])
        self.assertIn("packages/db/migrations/001.sql", baseline["discovery"]["database"])
        self.assertEqual({item["classification"] for item in baseline["candidate_requirements"]}, {"observed", "inferred", "unknown"})
        output = self.root / "output/.reqflow"
        self.assertFalse((output / "requirements.yaml").exists())
        self.assertEqual(yaml.safe_load((output / "import-baseline.yaml").read_text(encoding="utf-8")), baseline)

    def test_secrets_and_vendor_paths_are_not_exported(self):
        self.put(".env", "API_KEY=secret")
        self.put(".env.example", "API_KEY=example")
        self.put("credentials.json", '{"password":"secret"}')
        self.put("node_modules/private/package.json", "{}")
        self.put(".git/config", "hidden")
        self.put("cert.pem", "private-key")
        baseline = scan_project(self.repo)
        serialized = json.dumps(baseline)
        self.assertNotIn("API_KEY", serialized)
        self.assertNotIn("credentials.json", serialized)
        self.assertNotIn("node_modules/private", serialized)
        self.assertNotIn("cert.pem", serialized)
        self.assertNotIn(".env", serialized)

    def test_default_import_stays_in_project_arc_and_excludes_generated_artifacts(self):
        business = self.put('app.py', 'answer = 42\n')
        write_import(self.repo)
        self.assertEqual(business.read_text(), 'answer = 42\n')
        self.assertTrue((self.repo / '.arc/project.yaml').is_file())
        self.put('.arc/private-test.py', 'generated')
        baseline = scan_project(self.repo)
        self.assertNotIn('.arc', baseline['directories'])
        self.assertNotIn('private-test.py', json.dumps(baseline))

    def test_historical_failures_preserved_and_malformed_report_is_unknown(self):
        self.put("test-results/.last-run.json", json.dumps({"status": "failed", "failedTests": ["case-123"]}))
        self.put("junit.xml", '<testsuite><testcase name="broken" classname="account"><failure message="old failure"/></testcase></testsuite>')
        self.put("vitest-results.json", json.dumps({"numFailedTests": 1, "testResults": [{"assertionResults": [{"fullName": "login rejects bad password", "status": "failed"}]}]}))
        self.put("playwright-report/results.json", "not json")
        baseline = scan_project(self.repo)
        reports = {item["path"]: item for item in baseline["existing_test_reports"]}
        self.assertEqual(reports["test-results/.last-run.json"]["failures"][0]["name"], "case-123")
        self.assertEqual(reports["junit.xml"]["failures"][0]["name"], "account.broken")
        self.assertEqual(reports["vitest-results.json"]["failures"][0]["status"], "failed")
        self.assertIn("error", reports["playwright-report/results.json"])
        self.assertTrue(all(item["evidence"] == "historical_report" for item in reports.values()))
        self.assertEqual(baseline["test_execution"], "not_run")

    def test_source_output_rejected(self):
        with self.assertRaises(ValueError):
            write_import(self.repo, self.repo)
        with self.assertRaises(ValueError):
            write_import(self.repo, self.repo / "reports")
        self.assertFalse((self.repo / ".reqflow").exists())

    def test_git_status_includes_dirty_but_does_not_disclose_secret_names(self):
        subprocess.run(["git", "init", "--quiet", str(self.repo)], check=True)
        self.put("README.md", "project")
        self.put(".env", "API_KEY=secret")
        baseline = scan_project(self.repo)
        self.assertTrue(baseline["git"]["available"])
        self.assertTrue(baseline["git"]["dirty"])
        self.assertEqual(baseline["git"]["status"], [{"code": "??", "path": "README.md"}])
        self.assertIsNone(baseline["git"]["head"])

    def test_symlink_source_is_not_followed(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "README.md").write_text("private")
        try:
            (self.repo / "linked").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable")
        baseline = scan_project(self.repo)
        self.assertNotIn("linked", baseline["directories"])
        self.assertFalse(baseline["discovery"]["documents"])


if __name__ == "__main__":
    unittest.main()
