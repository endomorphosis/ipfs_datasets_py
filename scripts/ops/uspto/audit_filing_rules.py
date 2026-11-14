#!/usr/bin/env python3
"""Audit a Patent Center export or response package against filing rules.

Thin operator wrapper around ``portfolio_cli audit-submission`` that defaults
to your local Patent Center / messages export for the given application.

Examples
--------
# As-filed completeness review of exported IFW (auto package + scenario)
python3 scripts/ops/uspto/audit_filing_rules.py --application-number 18654466

# Explicit OA-response package
python3 scripts/ops/uspto/audit_filing_rules.py \\
  --application-number 18654466 \\
  --package-dir ~/drafts/oa_response \\
  --scenario office_action_response

# List / show prior audits
python3 scripts/ops/uspto/audit_filing_rules.py --list --application-number 18654466
python3 scripts/ops/uspto/audit_filing_rules.py --show --application-number 18654466

Review only — not legal advice. Never signs, pays, or submits.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CLI = Path(__file__).resolve().parent / "portfolio_cli.py"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit Patent Center exports / submission packages against "
            "USPTO filing-obligation rule packs (MPEP/CFR). Review only."
        )
    )
    parser.add_argument("--state-root", default="")
    parser.add_argument("--application-number", default="")
    parser.add_argument("--revision-id", default="")
    parser.add_argument(
        "--package-dir",
        default="",
        help="Override package dir (default: auto from exports/<app>/…)",
    )
    parser.add_argument(
        "--scenario",
        default="",
        help=(
            "new_application | office_action_response | amendment | "
            "information_disclosure | … (default: auto)"
        ),
    )
    parser.add_argument(
        "--application-type",
        default="utility",
        help="utility|design|plant (default utility)",
    )
    parser.add_argument("--prior-art-run-id", default="")
    parser.add_argument("--prior-art-run-dir", default="")
    parser.add_argument("--delta-from", default="")
    parser.add_argument("--with-law-index", action="store_true")
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--no-ids-queue", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--audit-path", default="")
    parser.add_argument("--audit-dir", default="")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    cmd = [sys.executable, str(_CLI)]
    if args.state_root:
        cmd.extend(["--state-root", args.state_root])
    cmd.append("audit-submission")

    if args.list:
        cmd.append("--list")
    if args.show:
        cmd.append("--show")
    if args.application_number:
        cmd.extend(["--application-number", args.application_number])
    if args.revision_id:
        cmd.extend(["--revision-id", args.revision_id])
    if args.package_dir:
        cmd.extend(["--package-dir", args.package_dir])
    else:
        # Prefer export package when no explicit dir (and not list/show-only)
        if not args.list and not args.show:
            cmd.append("--from-exports")
    if args.scenario:
        cmd.extend(["--scenario", args.scenario])
    if args.application_type:
        cmd.extend(["--application-type", args.application_type])
    if args.prior_art_run_id:
        cmd.extend(["--prior-art-run-id", args.prior_art_run_id])
    if args.prior_art_run_dir:
        cmd.extend(["--prior-art-run-dir", args.prior_art_run_dir])
    if args.delta_from:
        cmd.extend(["--delta-from", args.delta_from])
    if args.with_law_index:
        cmd.append("--with-law-index")
    if args.no_persist:
        cmd.append("--no-persist")
    if args.no_ids_queue:
        cmd.append("--no-ids-queue")
    if args.audit_path:
        cmd.extend(["--audit-path", args.audit_path])
    if args.audit_dir:
        cmd.extend(["--audit-dir", args.audit_dir])
    if args.verbose:
        cmd.append("--verbose")

    env = os.environ.copy()
    # Ensure repo root is importable
    pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT) if not pp else f"{_REPO_ROOT}{os.pathsep}{pp}"
    )
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
