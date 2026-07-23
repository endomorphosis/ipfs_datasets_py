#!/usr/bin/env python3
"""Build a self-hosted Xaman independent-review packet or validate a decision."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_self_hosted_review import (  # noqa: E402
    IndependentReviewError,
    build_review_packet,
    build_review_template,
    load_json,
    validate_review_decision,
)


ROOT = Path('security_ir_artifacts/corpora/xaman-app/self-hosted-testnet')
DEFAULT_CANDIDATE = ROOT / 'endpoint-rebound-candidate.json'
DEFAULT_HEALTH = ROOT / 'daemon-health.json'
DEFAULT_ISOLATION = ROOT / 'bridge-isolation-report.json'
DEFAULT_PACKET = ROOT / 'independent-review-packet.json'
DEFAULT_TEMPLATE = ROOT / 'independent-review-template.json'
DEFAULT_REVIEW = ROOT / 'endpoint-rebind-review.json'
DEFAULT_REPORT = ROOT / 'independent-review-verification-report.json'


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n', encoding='utf-8')


def _label(path: Path, root: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR))
    parser.add_argument('--candidate', default=str(DEFAULT_CANDIDATE))
    parser.add_argument('--health', default=str(DEFAULT_HEALTH))
    parser.add_argument('--isolation', default=str(DEFAULT_ISOLATION))
    parser.add_argument('--packet-out', default=str(DEFAULT_PACKET))
    parser.add_argument('--write-template', action='store_true')
    parser.add_argument('--template-out', default=str(DEFAULT_TEMPLATE))
    parser.add_argument('--review', default=None, help='Independently completed review decision to validate.')
    parser.add_argument('--verification-out', default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve()
    try:
        packet = build_review_packet(
            candidate=load_json(_resolve(root, args.candidate)),
            health=load_json(_resolve(root, args.health)),
            isolation=load_json(_resolve(root, args.isolation)),
        )
        packet_path = _resolve(root, args.packet_out)
        _write(packet_path, packet)
        if args.write_template:
            template_path = _resolve(root, args.template_out)
            _write(template_path, build_review_template(packet))
        if args.review is not None:
            report_path = _resolve(root, args.verification_out)
            report = validate_review_decision(load_json(_resolve(root, args.review)), packet=packet)
            _write(report_path, report)
            print(json.dumps({'packet_path': _label(packet_path, root), 'verification_path': _label(report_path, root), 'security_decision': report['security_decision']}, sort_keys=True))
        else:
            print(json.dumps({'packet_path': _label(packet_path, root), 'packet_status': packet['packet_status'], 'template_written': bool(args.write_template)}, sort_keys=True))
    except IndependentReviewError as exc:
        parser.error(str(exc))
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
