#!/usr/bin/env python3
"""Re-audit historical Leanstral rule-gap reports with current trust policy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.leanstral_rule_gap_reaudit import (  # noqa: E402,E501
    CANONICAL_HISTORICAL_REPORT_COUNT,
    CANONICAL_UNIQUE_GAP_COUNT,
    LeanstralRuleGapReauditError,
    LeanstralRuleGapReauditPolicy,
    reaudit_leanstral_rule_gaps,
    write_reaudit_report_atomic,
)


DEFAULT_HISTORICAL_ROOT = REPO_ROOT / "workspace" / "leanstral-smoke"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "reports",
        metavar="REPORT",
        type=Path,
        nargs="*",
        help=(
            "Historical rule-gaps.json files. When omitted, discover one report "
            "below each immediate child of --reports-root."
        ),
    )
    parser.add_argument(
        "--report",
        "--historical-report",
        dest="extra_reports",
        action="append",
        type=Path,
        default=[],
        help="Additional historical report; repeat as needed.",
    )
    parser.add_argument(
        "--reports-root",
        "--historical-root",
        type=Path,
        default=DEFAULT_HISTORICAL_ROOT,
        help=(
            "Discovery root used only when no REPORT or --report is supplied "
            f"(default: {DEFAULT_HISTORICAL_ROOT})."
        ),
    )
    parser.add_argument(
        "--fresh-evidence",
        type=Path,
        help=(
            "Optional current-evidence JSON produced from the strict sanitizer "
            "and current deterministic/Hammer/reconstruction verifiers."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination for the content-addressed, source-free re-audit report.",
    )
    parser.add_argument(
        "--expected-reports",
        type=int,
        default=CANONICAL_HISTORICAL_REPORT_COUNT,
        help="Required historical report count (default: 9).",
    )
    parser.add_argument(
        "--expected-unique-gaps",
        type=int,
        default=CANONICAL_UNIQUE_GAP_COUNT,
        help="Required deduplicated structural gap count (default: 1).",
    )
    parser.add_argument(
        "--max-guidance-influence",
        type=float,
        default=0.1,
        help="Hard upper bound for freshly verified guidance (default: 0.1).",
    )
    parser.add_argument(
        "--allow-unconflicted-history",
        action="store_true",
        help="Do not require both accepted and non-accepted historical decisions.",
    )
    parser.add_argument(
        "--allow-backend-proof-without-native-reconstruction",
        action="store_true",
        help=(
            "Apply a policy that permits a trusted backend proof without native "
            "reconstruction. The default canonical policy requires reconstruction."
        ),
    )
    parser.add_argument(
        "--require-accepted-guidance",
        action="store_true",
        help="Return exit status 2 when the fresh candidate is rejected or absent.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing output atomically.",
    )
    return parser


def _load_strict_json(path: Path) -> object:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ValueError(f"non-finite JSON number: {value}")

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise LeanstralRuleGapReauditError(
            f"cannot parse fresh evidence: {path}"
        ) from exc


def _historical_paths(args: argparse.Namespace) -> list[Path]:
    explicit = [*args.reports, *args.extra_reports]
    if explicit:
        paths = explicit
    else:
        paths = sorted(args.reports_root.glob("*/rule-gaps.json"))
    resolved = [path.resolve() for path in paths]
    if not resolved:
        raise LeanstralRuleGapReauditError("no historical rule-gap reports found")
    if len(set(resolved)) != len(resolved):
        raise LeanstralRuleGapReauditError("duplicate historical report path")
    return resolved


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.output.resolve()
    if output.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite output: {output}")
    try:
        paths = _historical_paths(args)
        fresh_evidence = (
            _load_strict_json(args.fresh_evidence.resolve())
            if args.fresh_evidence is not None
            else None
        )
        policy = LeanstralRuleGapReauditPolicy(
            expected_historical_reports=args.expected_reports,
            expected_unique_gaps=args.expected_unique_gaps,
            max_guidance_influence=args.max_guidance_influence,
            require_native_reconstruction=(
                not args.allow_backend_proof_without_native_reconstruction
            ),
            require_historical_conflict=not args.allow_unconflicted_history,
        )
        report = reaudit_leanstral_rule_gaps(
            paths,
            fresh_evidence=fresh_evidence,
            policy=policy,
        )
        write_reaudit_report_atomic(output, report)
    except LeanstralRuleGapReauditError as exc:
        raise SystemExit(f"Leanstral rule-gap re-audit failed: {exc}") from exc

    print(
        f"decision={report['decision']} "
        f"historical_reports={report['historical_report_count']} "
        f"unique_gaps={report['historical_unique_gap_count']} "
        f"guidance_influence={report['selected_guidance']['influence']} "
        f"report_sha256={report['report_sha256']} "
        f"output={output}"
    )
    if args.require_accepted_guidance and report["decision"] != "accepted":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
