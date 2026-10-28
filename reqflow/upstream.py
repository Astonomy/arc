"""Reuse the pinned ARC data/interaction contract resolver without loading its compiler."""
import importlib.util
from pathlib import Path

REVISION = "5a02a173d33ebd9251b28d97c70f6a0cb5b20deb"
URL = "https://github.com/code-philia/agentic-requirement-compiler.git"
UPSTREAM = Path(__file__).resolve().parent.parent / "upstream"


def resolve_contracts(tree):
    path = UPSTREAM / "src/arcbench_agent_runtime/requirement_contracts.py"
    if not path.is_file():
        raise ValueError("ARC source missing: run scripts/setup-upstream.ps1 (see README)")
    spec = importlib.util.spec_from_file_location("reqflow_arc_contracts", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # This is the actual MIT upstream implementation; no copied contract logic.
    return module.resolve_requirement_contracts(tree)


def compatibility_report(repository):
    """Conservative evidence-based suitability of the full upstream compiler."""
    repository = Path(repository).resolve()
    conventional = all((repository / part / "package.json").exists() for part in ("backend", "frontend"))
    return {
        "upstream": URL, "revision": REVISION, "license": "MIT",
        "repository": str(repository),
        "full_compiler": "unverified" if conventional else "incompatible_layout",
        "reused": ["FOLDER/ATOMIC requirement format", "data lifecycle and interaction contract resolver"],
        "adapted": ["atomic dependency planning", "requirement/test/code evidence mapping", "Codex execution"],
        "not_enabled": ["global SQLite preparation", "template scaffolding", "upstream application compilation"],
        "reasons": [
            "Upstream web handler expects backend/ and frontend/ with npm/Vitest/Playwright conventions.",
            "Upstream database preparation targets SQLite; existing PostgreSQL architecture is not a migration input.",
            "Evolution mode exists but does not prove compatibility with an arbitrary existing application.",
        ],
    }
