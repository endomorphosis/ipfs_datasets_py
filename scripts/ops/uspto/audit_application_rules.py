#!/usr/bin/env python3
"""Audit an application against USPTO filing rules + document format heuristics.

Fills diligence gaps by combining:

* Filing-obligation pack inventory (claims/spec/drawings/ADS/oath/fees)
* IFW export completeness
* Claim / abstract / specification format checks (OCR-assisted)
* Status / priority / grant signals
* Latest prior-art compliance warnings when available

Examples
--------
python3 scripts/ops/uspto/audit_application_rules.py --application-number 18654466

python3 scripts/ops/uspto/audit_application_rules.py --all-seed

Review only — not legal advice. Never Sign/Pay/Submit.
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


def main(argv: list[str] | None = None) -> int:
    from ipfs_datasets_py.processors.domains.uspto.application_rules_audit import (
        audit_application_rules,
    )
    from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
        default_state_root,
        load_portfolio_seed,
    )

    p = argparse.ArgumentParser(
        description=(
            "Audit application package against filing rules and format heuristics"
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
    p.add_argument("--package-dir", default="")
    p.add_argument("--application-type", default="utility")
    p.add_argument("--scenario", default="")
    p.add_argument("--no-filing-pack", action="store_true")
    p.add_argument("--no-prior-art", action="store_true")
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

    results = []
    exit_code = 0
    for app in apps:
        report = audit_application_rules(
            app,
            state_root=state,
            package_dir=str(args.package_dir or "") or None,
            application_type=str(args.application_type or "utility"),
            scenario=str(args.scenario or "") or None,
            run_filing_pack=not bool(args.no_filing_pack),
            include_prior_art=not bool(args.no_prior_art),
            persist=not bool(args.no_persist),
        )
        if not report.get("ok") or report.get("overall_status") == "not_ready":
            exit_code = 1
        if args.verbose:
            results.append(report)
        else:
            # Compact: errors/warnings + passes count + paths
            findings = report.get("findings") or []
            results.append(
                {
                    "application_number": report.get("application_number"),
                    "ok": report.get("ok"),
                    "overall_status": report.get("overall_status"),
                    "scenario": report.get("scenario"),
                    "filing_pack_status": report.get("filing_pack_status"),
                    "prior_art_status": report.get("prior_art_status"),
                    "severity_counts": report.get("severity_counts"),
                    "claims": report.get("claims"),
                    "errors": [
                        f
                        for f in findings
                        if f.get("severity") == "error"
                    ],
                    "warnings": [
                        f
                        for f in findings
                        if f.get("severity") == "warning"
                    ],
                    "human_only": [
                        f
                        for f in findings
                        if f.get("severity") == "human_only"
                    ],
                    "action_plan": report.get("action_plan"),
                    "paths": report.get("paths"),
                    "disclaimer": report.get("disclaimer"),
                }
            )

    payload = {
        "schema": "patlaw-audit-application-rules-cli-v1",
        "ok": exit_code == 0,
        "state_root": str(state),
        "results": results,
    }
    try:
        receipt = state / "exports" / "application_rules_format_receipt.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(payload, indent=2, default=str) + "\n")
        os.chmod(receipt, 0o600)
        payload["receipt"] = str(receipt)
    except Exception:
        pass
    print(json.dumps(payload, indent=2, default=str))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
