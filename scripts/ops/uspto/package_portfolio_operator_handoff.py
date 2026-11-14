#!/usr/bin/env python3
"""Build personal portfolio operator handoff inventory (PATLAW-214)."""
from __future__ import annotations

import argparse
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

SCHEMA: Final = "patlaw-portfolio-operator-handoff.v1"

HANDOFF_DOCS = [
    "docs/operations/USPTO_PORTFOLIO_AUTOMATION.md",
    "docs/operations/USPTO_PORTFOLIO_PRIOR_ART_COMPLIANCE_RUNBOOK.md",
    "docs/operations/PATENT_LEGAL_PORTFOLIO_NON_GOALS.md",
    "docs/operations/PATENT_LEGAL_PORTFOLIO_MATTER_STATUS.md",
    "docs/operations/PATENT_LEGAL_PORTFOLIO_PILOT_RECEIPT.md",
    "docs/operations/PATENT_LEGAL_PUBLIC_PATENT_SEARCH_SOURCES.md",
    "docs/operations/PATENT_LEGAL_EPO_OPS.md",
]

CLI = "scripts/ops/uspto/portfolio_cli.py"
SMOKE = "scripts/ops/uspto/smoke_prior_art_compliance_loop.sh"


def _digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def build_handoff_package(repo_root: Path) -> dict[str, Any]:
    docs = []
    for rel in HANDOFF_DOCS:
        p = repo_root / rel
        docs.append({"path": rel, "present": p.is_file(), "sha256": _digest(p)})
    return {
        "schema": SCHEMA,
        "task_id": "PATLAW-214",
        "goal_id": "PATLAW-G235",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "content_free": True,
        "cli_entrypoint": CLI,
        "cli_present": (repo_root / CLI).is_file(),
        "smoke_script": SMOKE,
        "smoke_present": (repo_root / SMOKE).is_file(),
        "documents": docs,
        "hard_barriers": ["Sign", "Pay", "Submit"],
        "auto_file_blocked": True,
        "forbidden": [
            "google_patents_scrape",
            "pps_automation",
            "patentability_conclusions",
            "auto_sign_pay_submit",
            "auto_ids_file",
        ],
        "notes": "Inventory only — never embeds credentials or private PDF bodies.",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, default=Path.cwd())
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    pkg = build_handoff_package(args.repo_root.resolve())
    text = json.dumps(pkg, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
