#!/usr/bin/env python3
"""Build and validate Xaman vendor-evidence packets for external evidence review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_vendor_evidence import (  # noqa: E402
    VendorEvidenceError,
    MANIFEST_PATH,
    REVIEW_PATH,
    REVIEW_TEMPLATE_PATH,
    REVIEW_VERIFICATION_PATH,
    REVIEW_REQUIRED_KEYS,
    build_vendor_evidence_placeholder_manifest,
    build_vendor_evidence_review_template,
    load_json,
    validate_vendor_evidence_manifest,
    validate_vendor_evidence_review,
)


DEFAULT_TEMPLATE_PATH = Path(MANIFEST_PATH).parent / 'vendor-evidence-intake-template.json'
DEFAULT_MANIFEST_OUT = Path(MANIFEST_PATH)
DEFAULT_REVIEW_TEMPLATE_OUT = Path(REVIEW_TEMPLATE_PATH)
DEFAULT_REVIEW_OUT = Path(REVIEW_PATH)
DEFAULT_VERIFICATION_OUT = Path(REVIEW_VERIFICATION_PATH)


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n', encoding='utf-8')


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding='utf-8')


def _label(path: Path, root: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def generate(
    repo_root: Path,
    *,
    intake_template: Path,
    manifest_in: Path | None,
    manifest_out: Path,
    write_template: bool = False,
    review_template_out: Path | None = None,
    review_path: Path | None = None,
    verification_out: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    """Build or validate a vendor-evidence manifest and optional review verification."""

    manifest: dict[str, Any]
    if manifest_in is not None:
        manifest = validate_vendor_evidence_manifest(load_json(manifest_in))
    else:
        template = load_json(_resolve(repo_root, intake_template))
        manifest = build_vendor_evidence_placeholder_manifest(template=template)
    _write_json(manifest_out, manifest)

    review_template: dict[str, Any] | None = None
    review_verification: dict[str, Any] | None = None
    if write_template:
        review_template = build_vendor_evidence_review_template(manifest)
        if review_template_out is None:
            raise VendorEvidenceError('review template output path must be set when --write-review-template is used')
        _write_json(review_template_out, review_template)

    if review_path is not None:
        if verification_out is None:
            raise VendorEvidenceError('verification output path must be set when --review is used')
        review_payload = load_json(review_path)
        if set(review_payload.keys()) >= REVIEW_REQUIRED_KEYS:
            review_verification = validate_vendor_evidence_review(review_payload, manifest=manifest)
        else:
            raise VendorEvidenceError('review payload is missing required reviewer keys')
        _write_json(verification_out, review_verification)

    return manifest, review_template, review_verification


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR), help='Repository root containing security_artifacts')
    parser.add_argument(
        '--intake-template',
        default=str(DEFAULT_TEMPLATE_PATH),
        help='Input vendor-evidence-intake template path.',
    )
    parser.add_argument('--manifest-in', default=None, help='Existing manifest to validate and refresh from.')
    parser.add_argument(
        '--manifest-out',
        default=str(DEFAULT_MANIFEST_OUT),
        help='Output path for validated or placeholder vendor-evidence manifest.',
    )
    parser.add_argument('--write-review-template', action='store_true', help='Emit a non-evidence review template.')
    parser.add_argument(
        '--review-template-out',
        default=str(DEFAULT_REVIEW_TEMPLATE_OUT),
        help='Output path for review template JSON.',
    )
    parser.add_argument('--review', default=None, help='Vendor review JSON to validate.')
    parser.add_argument(
        '--verification-out',
        default=str(DEFAULT_VERIFICATION_OUT),
        help='Output path for validated review verification payload.',
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    try:
        manifest, review_template, review_verification = generate(
            repo_root=repo_root,
            intake_template=Path(args.intake_template),
            manifest_in=Path(args.manifest_in) if args.manifest_in else None,
            manifest_out=_resolve(repo_root, args.manifest_out),
            write_template=args.write_review_template,
            review_template_out=_resolve(repo_root, args.review_template_out),
            review_path=_resolve(repo_root, args.review) if args.review else None,
            verification_out=_resolve(repo_root, args.verification_out) if args.review else None,
        )
        payload = {
            'manifest_path': _label(_resolve(repo_root, args.manifest_out), repo_root),
            'manifest_cid': manifest['artifact_cid'],
            'manifest_status': manifest['manifest_status'],
            'verification_path': _label(_resolve(repo_root, args.verification_out), repo_root) if args.review else None,
            'verification_status': review_verification['decision'] if review_verification else None,
            'review_template_path': _label(_resolve(repo_root, args.review_template_out), repo_root)
            if review_template
            else None,
            'review_template_status': review_template['template_status'] if review_template else None,
        }
        print(json.dumps({key: value for key, value in payload.items() if value is not None}, sort_keys=True))
    except VendorEvidenceError as exc:
        parser.error(str(exc))
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
