"""Read-only project inventory. Discovery is evidence, never approved requirements."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

import yaml


EXCLUDED_DIRECTORIES = {".git", ".venv", "venv", "node_modules", "__pycache__", ".next", "dist", "build", "coverage", ".cache", ".reqflow", ".arc"}


def _excluded(path: str) -> bool:
    parts = Path(path).parts
    return any(part in EXCLUDED_DIRECTORIES or part.lower().startswith(".env")
               or re.search(r"(?:credential|secret|private.?key)", part, re.I)
               or part.lower().endswith((".pem", ".key", ".p12", ".pfx")) for part in parts)


def _git(repo: Path) -> dict:
    def run(*args):
        return subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(repo), *args],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)

    try:
        result = run("status", "--porcelain=v1", "-z", "--untracked-files=all")
        if result.returncode:
            return {"available": False, "head": None, "branch": None, "dirty": None, "status": [], "error": "not a readable Git worktree"}
        entries = result.stdout.split("\0")
        changes = []
        index = 0
        dirty = bool(result.stdout)
        while index < len(entries):
            entry = entries[index]
            index += 1
            if not entry:
                continue
            code, path = entry[:2], entry[3:]
            if not _excluded(path):
                changes.append({"code": code, "path": path})
            if "R" in code or "C" in code:
                index += 1  # porcelain -z rename includes a second, original path
        head = run("rev-parse", "HEAD")
        branch = run("branch", "--show-current")
        return {"available": True, "head": head.stdout.strip() if head.returncode == 0 else None,
                "branch": branch.stdout.strip() if branch.returncode == 0 else None,
                "dirty": dirty, "status": changes}
    except (OSError, subprocess.SubprocessError):
        return {"available": False, "head": None, "branch": None, "dirty": None, "status": [], "error": "Git inspection unavailable"}


def _files(repo: Path) -> list[Path]:
    files = []
    for current, dirs, names in os.walk(repo, followlinks=False):
        parent = Path(current)
        dirs[:] = sorted(name for name in dirs if not _excluded(str((parent / name).relative_to(repo)))
                         and not (parent / name).is_symlink())
        files.extend(parent / name for name in sorted(names)
                     if not _excluded(str((parent / name).relative_to(repo))) and not (parent / name).is_symlink())
    return files


def _test_report(path: Path, relative: str) -> dict | None:
    name = path.name.lower()
    if name == ".last-run.json":
        kind = "playwright-last-run"
    elif path.suffix.lower() == ".xml" and ("junit" in name or name in {"test-results.xml", "testresult.xml"}):
        kind = "junit"
    elif path.suffix.lower() == ".json" and name in {"results.json", "test-results.json", "vitest-results.json", "report.json"}:
        kind = "json-test-report"
    else:
        return None
    result = {"path": relative, "format": kind, "failures": [], "evidence": "historical_report"}
    try:
        if path.stat().st_size > 10_000_000:
            raise ValueError("report exceeds 10MB inspection limit")
        if kind == "junit":
            tree = ET.fromstring(path.read_bytes())
            cases = list(tree.iter("testcase"))
            result["summary"] = {"tests": len(cases)}
            for case in cases:
                status = "failed" if case.find("failure") is not None else "error" if case.find("error") is not None else None
                if status:
                    result["failures"].append({"name": ".".join(filter(None, [case.get("classname"), case.get("name")])), "status": status})
        else:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("report must be a JSON object")
            if kind == "playwright-last-run":
                result["summary"] = {"status": data.get("status", "unknown")}
                result["failures"] = [{"name": str(item), "status": "failed"} for item in data.get("failedTests", [])]
            else:
                result["summary"] = {key: data[key] for key in ("numTotalTests", "numPassedTests", "numFailedTests", "success") if key in data}
                for suite in data.get("testResults", []):
                    for case in suite.get("assertionResults", []):
                        if case.get("status") in {"failed", "error"}:
                            result["failures"].append({"name": case.get("fullName") or case.get("title", "unknown"), "status": case["status"]})
                def playwright(suite):
                    for spec in suite.get("specs", []):
                        for test in spec.get("tests", []):
                            if test.get("status") in {"unexpected", "flaky"}:
                                result["failures"].append({"name": spec.get("title", "unknown"), "status": test["status"]})
                    for child in suite.get("suites", []):
                        playwright(child)
                for suite in data.get("suites", []):
                    playwright(suite)
    except (OSError, ValueError, TypeError, AttributeError, ET.ParseError):
        result["error"] = "report could not be parsed; execution status remains unknown"
    return result


def scan_project(repo: Path) -> dict:
    repo = Path(repo).expanduser().resolve()
    if not repo.is_dir():
        raise ValueError("repository must be an existing directory")
    paths = _files(repo)
    manifests, commands, reports = [], [], []
    stack = set()
    discovery = {name: [] for name in ("tests", "ci", "api", "database", "documents")}
    unknowns = ["Current runnable state is unknown: no project commands or tests were executed.",
                "Historical reports may be stale and are not current acceptance evidence.",
                "Discovered scripts are candidates; their environment and safety are unconfirmed."]
    for path in paths:
        relative = path.relative_to(repo).as_posix()
        lower = relative.lower()
        name = path.name.lower()
        if name == "package.json":
            manifests.append({"path": relative, "kind": "node"})
            try:
                package = json.loads(path.read_text(encoding="utf-8-sig"))
                deps = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
                stack.add("node")
                for dependency, label in (("next", "nextjs"), ("vue", "vue"), ("react", "react"), ("@nestjs/core", "nestjs"),
                                          ("pg", "postgresql"), ("postgres", "postgresql"), ("@playwright/test", "playwright"), ("vitest", "vitest")):
                    if dependency in deps:
                        stack.add(label)
                engines = package.get("engines", {})
                if isinstance(engines, dict):
                    stack.update(f"{key} {value}" for key, value in engines.items() if key in {"node", "pnpm"})
                for script, command in package.get("scripts", {}).items():
                    if isinstance(command, str):
                        commands.append({"name": script, "command": command, "manifest": relative, "confirmed": False})
            except (OSError, ValueError, TypeError, AttributeError):
                unknowns.append(f"Cannot parse manifest: {relative}")
        elif name in {"pyproject.toml", "requirements.txt", "cargo.toml", "go.mod", "pom.xml"}:
            kind = {"pyproject.toml": "python", "requirements.txt": "python", "cargo.toml": "rust", "go.mod": "go", "pom.xml": "java"}[name]
            manifests.append({"path": relative, "kind": kind})
            stack.add(kind)
        if re.search(r"(^|/)(tests?|__tests__)(/|$)|\.(test|spec)\.[^/]+$|(^|/)test_[^/]+\.py$", lower):
            discovery["tests"].append(relative)
        if lower.startswith(".github/workflows/") or name in {".gitlab-ci.yml", "jenkinsfile"}:
            discovery["ci"].append(relative)
        if re.search(r"(^|/)(api|routes?|controllers?)(/|\.)|openapi|swagger", lower):
            discovery["api"].append(relative)
        if re.search(r"(^|/)(migrations?|prisma|database|db)(/|\.)|\.sql$|schema\.prisma$", lower):
            discovery["database"].append(relative)
        if path.suffix.lower() in {".md", ".rst"} or lower.startswith("docs/"):
            discovery["documents"].append(relative)
        report = _test_report(path, relative)
        if report:
            reports.append(report)
    candidates = [{"id": f"CAND-{index:03}", "classification": "observed", "source": path,
                   "statement": "Test asset exists; its behavior and current result have not been verified."}
                  for index, path in enumerate(discovery["tests"], 1)]
    candidates.extend({"id": f"DOC-{index:03}", "classification": "inferred", "source": path,
                       "statement": "Documentation may describe requirements; developer confirmation is required."}
                      for index, path in enumerate(discovery["documents"], 1))
    candidates.append({"id": "UNKNOWN-001", "classification": "unknown", "source": None,
                       "statement": "Implementation/documentation/test agreement has not been established."})
    return {"version": 1, "repository": str(repo), "scanned_at": datetime.now(timezone.utc).isoformat(),
            "git": _git(repo), "directories": sorted(item.name for item in repo.iterdir() if item.is_dir() and not item.is_symlink() and not _excluded(item.name)),
            "manifests": manifests, "stack": sorted(stack), "commands": commands, "discovery": discovery,
            "existing_test_reports": reports, "candidate_requirements": candidates,
            "test_execution": "not_run", "unknowns": unknowns}


def write_import(repo: Path, output_dir: Path | None = None) -> dict:
    repo = Path(repo).expanduser().resolve()
    local = output_dir is None
    output_dir = repo if local else Path(output_dir).expanduser().resolve()
    if not local and output_dir.is_relative_to(repo):
        raise ValueError("import output must be outside the scanned repository")
    baseline = scan_project(repo)
    folder = output_dir / (".arc" if local else ".reqflow")
    # Resolve again to reject a pre-existing .reqflow symlink into the source.
    if folder.is_symlink() or (not local and folder.resolve().is_relative_to(repo)):
        raise ValueError("import output resolves inside the scanned repository")
    folder.mkdir(parents=True, exist_ok=True)
    config = {"version": 1, "repository": str(repo), "environment": "wsl" if str(repo).startswith("/mnt/") else "native",
              "commands": baseline["commands"], "scope": [], "allowed_paths": [],
              "constraints": ["Commands are discovery candidates and need confirmation.", "No business files were modified by import."]}
    if local:
        config['execution_mode'] = 'in-place'
    for name, value in (("project.yaml", config), ("import-baseline.yaml", baseline)):
        target = folder / name
        if target.is_symlink():
            raise ValueError("import artifact must not be a symlink")
        target.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")
    report = ["# 项目只读盘点", "", f"仓库：`{repo}`", f"扫描时间：{baseline['scanned_at']}",
              f"Git HEAD：`{baseline['git']['head']}`；脏工作区：{baseline['git']['dirty']}",
              "", "未执行安装、测试或构建；已有测试报告仅作为历史记录。未生成正式需求。", "", "## 技术栈线索", "",
              ", ".join(baseline["stack"]) or "未知", "", "## 历史测试报告", ""]
    for item in baseline["existing_test_reports"]:
        report.append(f"- `{item['path']}`：{len(item['failures'])} 个失败记录" + ("；解析失败，状态未知" if item.get("error") else ""))
        report.extend(f"  - {failure['name']} ({failure['status']})" for failure in item["failures"])
    if not baseline["existing_test_reports"]:
        report.append("未发现可识别的报告；不代表测试通过。")
    report.extend(["", "## 待确认", "", *[f"- {value}" for value in baseline["unknowns"]]])
    target = folder / "import-report.md"
    if target.is_symlink():
        raise ValueError("import artifact must not be a symlink")
    target.write_text("\n".join(report) + "\n", encoding="utf-8")
    return baseline
