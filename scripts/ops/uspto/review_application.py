#!/usr/bin/env python3
"""Unified application review CLI (PAAR-090).

Runs claim model → search → conflict risk → conformance → optional diligence
and emits UnifiedApplicationReview@1.

Exit codes
----------
0  ready (review support complete; human still owns filing)
1  review_required
2  not_ready / error

Examples
--------
python3 scripts/ops/uspto/review_application.py \\
  --application-number 16990002 \\
  --package-dir tests/fixtures/uspto/paar_review/clean_package \\
  --state-root /tmp/paar-review-state --no-persist

python3 scripts/ops/uspto/review_application.py \\
  --fixture-dir tests/fixtures/uspto/paar_review/planted_conflict \\
  --state-root /tmp/paar-review-state

Review only — not legal advice. Never Sign/Pay/Submit. Never patentability
conclusions. auto_file_blocked always true.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    from ipfs_datasets_py.processors.domains.uspto.application_review_orchestrator import (
        ApplicationReviewOrchestratorError,
        REVIEW_ONLY_UNIFIED_DISCLAIMER,
        run_unified_application_review,
    )
    from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
        default_state_root,
    )

    p = argparse.ArgumentParser(
        description=(
            "Unified PAAR application review (claim → search → conflict → "
            "conformance → diligence). Review only — not legal advice. "
            "Never Sign/Pay/Submit. Never patentability conclusions."
        ),
        epilog=REVIEW_ONLY_UNIFIED_DISCLAIMER[:240] + "…",
    )
    p.add_argument(
        "--application-number",
        default="",
        help="USPTO application number (digits; optional if fixture/package provides it)",
    )
    p.add_argument(
        "--state-root",
        default="",
        help="Operator state root (default: portfolio default_state_root)",
    )
    p.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not write under state-root/compliance_audits/<app>/review_<stamp>/",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print full UnifiedApplicationReview JSON (default: compact summary)",
    )
    p.add_argument(
        "--package-dir",
        default="",
        help="Optional package / export directory (or fixture variant dir)",
    )
    p.add_argument(
        "--prior-art-run",
        default="",
        help="Optional prior-art run directory (hits/journal JSON)",
    )
    p.add_argument(
        "--fixture-dir",
        default="",
        help="Hermetic paar_review fixture directory (loads claims/hits/inventory)",
    )
    p.add_argument(
        "--claims-file",
        default="",
        help="Optional claims text file (overrides fixture claims when set)",
    )
    p.add_argument(
        "--claims-text",
        default="",
        help="Optional inline claims text (prefer --claims-file for large sets)",
    )
    p.add_argument(
        "--authority-corpus-present",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Override authority corpus binding (default: from inventory/fixture)",
    )
    p.add_argument(
        "--application-type",
        default="utility",
        help="Application type for obligation catalog (default: utility)",
    )
    p.add_argument(
        "--scenario",
        default="new_application",
        help="Filing scenario for obligation catalog (default: new_application)",
    )
    p.add_argument(
        "--no-diligence",
        action="store_true",
        help="Skip optional application_gap_closure diligence packs",
    )
    p.add_argument(
        "--no-conflict-review",
        action="store_true",
        help="Skip optional conflict_review_report (stub path)",
    )
    p.add_argument(
        "--no-search",
        action="store_true",
        help="Skip review_search_orchestrator composition",
    )
    args = p.parse_args(argv)

    state = (
        Path(args.state_root).expanduser().resolve()
        if args.state_root
        else default_state_root()
    )

    kwargs: dict = {
        "application_number": str(args.application_number or "").strip(),
        "state_root": state,
        "persist": not bool(args.no_persist),
        "include_diligence": not bool(args.no_diligence),
        "include_conflict_review": not bool(args.no_conflict_review),
        "include_search": not bool(args.no_search),
        "application_type": args.application_type,
        "scenario": args.scenario,
    }
    if args.package_dir:
        kwargs["package_dir"] = Path(args.package_dir).expanduser().resolve()
    if args.prior_art_run:
        kwargs["prior_art_run"] = Path(args.prior_art_run).expanduser().resolve()
    if args.fixture_dir:
        kwargs["fixture_dir"] = Path(args.fixture_dir).expanduser().resolve()
    if args.claims_file:
        kwargs["claims_file"] = Path(args.claims_file).expanduser().resolve()
    if args.claims_text:
        kwargs["claims_text"] = args.claims_text
    if args.authority_corpus_present is not None:
        kwargs["authority_corpus_present"] = bool(args.authority_corpus_present)

    try:
        report = run_unified_application_review(**kwargs)
    except ApplicationReviewOrchestratorError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": exc.code,
                    "message": str(exc)[:256],
                    "exit_code_hint": 2,
                    "disposition": "not_ready",
                    "auto_file_blocked": True,
                    "disclaimer": REVIEW_ONLY_UNIFIED_DISCLAIMER,
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2
    except Exception as exc:  # noqa: BLE001 — operator CLI fail closed
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": type(exc).__name__,
                    "message": str(exc)[:256],
                    "exit_code_hint": 2,
                    "disposition": "not_ready",
                    "auto_file_blocked": True,
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    if args.verbose:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True, default=str))
    else:
        print(
            json.dumps(
                report.compact_summary(), indent=2, sort_keys=True, default=str
            )
        )

    return int(report.exit_code_hint)


if __name__ == "__main__":
    raise SystemExit(main())
