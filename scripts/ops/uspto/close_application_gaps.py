#!/usr/bin/env python3
"""Close remaining application diligence gaps with evidence packs.

Builds and persists:

* Foreign-patent **named-gap acceptance** (gap stays visible; never claims searched)
* Family / PCT / ISR diligence pack (continuity + IDS ISR/WO evidence + ODP)
* Human diligence packs: inventorship, new-matter, nonpublication, export
* Optional explicit human confirmations (requires --acknowledger)
* Re-run of ``audit_application_rules``

Examples
--------
# Document foreign gap acceptance + evidence packs + re-audit
python3 scripts/ops/uspto/close_application_gaps.py \\
  --application-number 18654466 --acknowledger operator:you

# Also record human confirmations for nonpublication + export (still review-only)
python3 scripts/ops/uspto/close_application_gaps.py \\
  --application-number 18654466 --acknowledger operator:you \\
  --confirm-human-items check:nonpublication,check:export,check:inventorship,check:new-matter

# Skip live ODP family enrichment (offline)
python3 scripts/ops/uspto/close_application_gaps.py \\
  --application-number 18654466 --no-fetch-odp --no-accept-foreign-gap

Review only — not legal advice. Never Sign/Pay/Submit. Never auto-file IDS.
Foreign acceptance never asserts foreign-patent coverage.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_uspto_env() -> Path | None:
    """Source USPTO ODP key from the operator env file when unset."""
    if os.environ.get("USPTO_ODP_API_KEY"):
        return None
    candidates = [
        Path.home() / ".config" / "ipfs_datasets_py" / "uspto.env",
    ]
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        candidates.insert(0, Path(xdg) / "ipfs_datasets_py" / "uspto.env")
    for path in candidates:
        if not path.is_file():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("'").strip('"')
                if key and key not in os.environ and val:
                    os.environ[key] = val
            if not os.environ.get("USPTO_ODP_API_KEY"):
                for alt in ("ODP_API_KEY", "USPTO_API_KEY"):
                    if os.environ.get(alt):
                        os.environ["USPTO_ODP_API_KEY"] = os.environ[alt]
                        break
            return path
        except OSError:
            continue
    return None


def main(argv: list[str] | None = None) -> int:
    _load_uspto_env()

    from ipfs_datasets_py.processors.domains.uspto.application_gap_closure import (
        close_application_gaps,
    )
    from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
        default_state_root,
        load_portfolio_seed,
    )

    p = argparse.ArgumentParser(
        description=(
            "Close residual application diligence gaps (foreign acceptance, "
            "family/PCT/ISR, human packs) — review only"
        )
    )
    p.add_argument("--state-root", default="")
    p.add_argument(
        "--application-number",
        action="append",
        default=[],
        help="Application number (repeatable)",
    )
    p.add_argument("--all-seed", action="store_true")
    p.add_argument(
        "--run-id",
        default="",
        help="Prior-art run id (default: latest run-*)",
    )
    p.add_argument(
        "--acknowledger",
        default="operator:local",
        help="Name recorded on foreign acceptance / human confirmations",
    )
    p.add_argument(
        "--accept-foreign-gap",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write formal foreign named-gap acceptance (default: true)",
    )
    p.add_argument(
        "--confirm-human-items",
        default="",
        help=(
            "Comma-separated checklist item ids to mark confirmed "
            "(e.g. check:nonpublication,check:export). Requires intentional use."
        ),
    )
    p.add_argument(
        "--fetch-odp",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fetch provisional/PCT titles via ODP (default: true when key set)",
    )
    p.add_argument(
        "--reaudit",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Re-run audit_application_rules after gap closure (default: true)",
    )
    p.add_argument("--no-persist", action="store_true")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    state = (
        Path(args.state_root).expanduser().resolve()
        if args.state_root
        else default_state_root()
    )
    apps = [str(a).strip() for a in (args.application_number or []) if str(a).strip()]
    if args.all_seed:
        seed_path = state / "portfolio_seed.json"
        if seed_path.is_file():
            seed = load_portfolio_seed(seed_path)
            apps = list(
                dict.fromkeys(
                    apps
                    + [
                        m.application_number
                        for m in seed.matters
                        if not str(m.ownership).startswith("candidate")
                    ]
                )
            )
    if not apps:
        print(
            json.dumps(
                {"ok": False, "error": "pass --application-number or --all-seed"},
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    confirm_items: list[str] = []
    if str(args.confirm_human_items or "").strip():
        confirm_items = [
            x.strip()
            for x in str(args.confirm_human_items).split(",")
            if x.strip()
        ]

    results = []
    exit_code = 0
    for app in apps:
        report = close_application_gaps(
            app,
            state_root=state,
            run_id=str(args.run_id or "") or None,
            acknowledger_name=str(args.acknowledger or "operator:local"),
            accept_foreign_gap_flag=bool(args.accept_foreign_gap),
            confirm_human_items=confirm_items or None,
            fetch_odp=bool(args.fetch_odp),
            reaudit=bool(args.reaudit),
            persist=not bool(args.no_persist),
        )
        if not report.get("ok"):
            exit_code = 1
        reaudit = (report.get("steps") or {}).get("reaudit") or {}
        if reaudit.get("overall_status") == "not_ready":
            exit_code = 1

        if args.verbose:
            results.append(report)
        else:
            results.append(
                {
                    "application_number": report.get("application_number"),
                    "ok": report.get("ok"),
                    "prior_art_run": report.get("prior_art_run"),
                    "steps": {
                        k: {
                            sk: sv
                            for sk, sv in (v or {}).items()
                            if sk
                            not in {
                                "acceptance",
                                "packs",
                                "provisionals",
                                "hits",
                            }
                        }
                        if isinstance(v, dict)
                        else v
                        for k, v in (report.get("steps") or {}).items()
                    },
                    "action_plan": report.get("action_plan"),
                    "paths": report.get("paths"),
                    "checklist_confirmed": [
                        i.get("item_id")
                        for i in (report.get("checklist") or {}).get("items") or []
                        if i.get("confirmed")
                    ],
                    "checklist_still_human": [
                        i.get("item_id")
                        for i in (report.get("checklist") or {}).get("items") or []
                        if not i.get("confirmed")
                    ],
                    "foreign_gap_accepted": bool(
                        (report.get("foreign_gap_acceptance") or {}).get(
                            "gap_remains_visible"
                        )
                        and (report.get("foreign_gap_acceptance") or {}).get(
                            "acknowledger_name"
                        )
                    ),
                    "family_finding_codes": [
                        f.get("code")
                        for f in (report.get("family_pct_isr") or {}).get("findings")
                        or []
                    ],
                    "disclaimer": report.get("disclaimer"),
                }
            )

    payload = {
        "schema": "patlaw-close-application-gaps-cli-v1",
        "ok": exit_code == 0,
        "state_root": str(state),
        "results": results,
        "disclaimer": (
            "Gap closure is review support only — not legal advice. Foreign "
            "acceptance never asserts foreign coverage. Sign/Pay/Submit human-only."
        ),
    }
    print(json.dumps(payload, indent=2, default=str))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
