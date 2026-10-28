"""Make the existing-project evidence/requirement boundary explicit."""
import json
from pathlib import Path

import yaml


def analyze_gaps(flow_dir, tree, *, save=True):
    from .core import atomic_plan

    flow_dir = Path(flow_dir)
    baseline_path = flow_dir / "import-baseline.yaml"
    baseline = yaml.safe_load(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else None
    mapping_path = flow_dir / "mappings.yaml"
    mappings = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) if mapping_path.exists() else {}
    if not isinstance(mappings, dict):
        raise ValueError("mappings.yaml must map REQ IDs to evidence decisions")
    previous_path = flow_dir / "requirements.yaml"
    previous = {}
    if previous_path.exists():
        old = yaml.safe_load(previous_path.read_text(encoding="utf-8"))
        previous = {item["id"]: item for item in atomic_plan(old)}
    entries, unresolved = [], []
    plan = atomic_plan(tree)
    for requirement in plan:
        identity = requirement["id"]
        mapping = mappings.get(identity, {})
        if not isinstance(mapping, dict):
            raise ValueError(f"invalid mapping: {identity}")
        status = mapping.get("status", "unknown")
        if status not in {"implemented", "missing", "change", "unknown"}:
            raise ValueError(f"invalid gap status: {identity}")
        evidence = mapping.get("evidence", [])
        if not isinstance(evidence, list) or any(not isinstance(path, str) for path in evidence):
            raise ValueError(f"evidence must be a path list: {identity}")
        valid_evidence = True
        if baseline:
            repo = Path(baseline["repository"]).resolve()
            for name in evidence:
                path = (repo / name).resolve()
                if not path.is_relative_to(repo) or not path.is_file():
                    valid_evidence = False
            confirmed = isinstance(mapping.get("confirmed_by"), str) and bool(mapping["confirmed_by"].strip())
            if status == "unknown" or not confirmed or not valid_evidence or (status in {"implemented", "change"} and not evidence):
                unresolved.append(identity + ": existing behavior is unknown or lacks confirmed evidence")
            if mapping.get("conflict") and not str(mapping.get("decision", "")).strip():
                unresolved.append(identity + ": implementation/test/document conflict has no decision")
        old = previous.get(identity)
        delta = "added" if old is None else "unchanged" if old == requirement else "changed"
        entries.append({"id": identity, "delta": delta, "status": status, "evidence": evidence,
                        "confirmed_by": mapping.get("confirmed_by"), "conflict": mapping.get("conflict"),
                        "decision": mapping.get("decision"), "evidence_exists": valid_evidence})
    report = {"version": 1, "existing_project": baseline is not None, "requirements": entries,
              "removed": sorted(set(previous) - {item["id"] for item in plan}),
              "unresolved": unresolved, "historical_test_reports": baseline.get("existing_test_reports", []) if baseline else [],
              "note": "Confirmed mappings are developer decisions; historical reports are not current test acceptance."}
    if save:
        flow_dir.mkdir(parents=True, exist_ok=True)
        (flow_dir / "gaps.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
