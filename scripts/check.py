"""Capture the cross-project local verification in reviewable files."""
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
output = root / "docs/verification"
output.mkdir(parents=True, exist_ok=True)
system = platform.system().lower()
results = []
for name, folder in (("scheduler", root.parent / "scheduler"), ("arc", root)):
    command = [sys.executable, "-W", "error::ResourceWarning", "-m", "unittest", "discover", "-s", "tests", "-v"]
    run = subprocess.run(command, cwd=folder, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log = output / f"{name}-{system}.log"
    log.write_text(run.stdout + run.stderr, encoding="utf-8")
    results.append({"project": name, "command": command, "exit_code": run.returncode, "log": log.name})
summary = {"checked_at": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(), "python": sys.version,
           "results": results}
(output / f"{system}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
raise SystemExit(int(any(result["exit_code"] for result in results)))
