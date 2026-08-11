#!/usr/bin/env python3
"""Fail-closed LCR-082 source-rights audit and deterministic fixture builder.

The validation modes accept no catalog, schema, registry, clock, freshness, or
output-path override.  ``--emit-deterministic-fixture`` only prints the exact
checked-in fixture candidate to stdout; it never writes repository or remote
state.  Normal ``--fixture-only --check`` compares the committed catalog with
that deterministic candidate before evaluation.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.legal_source_rights_policy import (
    ADMISSIBLE_CONTENT_SCOPES,
    CATALOG_PRODUCER,
    CATALOG_SCHEMA_VERSION,
    CONDITION_EVIDENCE_SCHEMA_VERSION,
    CURRENTNESS_DISCLAIMER,
    EVIDENCE_SCHEMA_VERSION,
    EXPECTED_FRONTIER_SIZE,
    FIXTURE_GOAL_ID,
    FIXTURE_TASK_ID,
    PROGRAM_ID,
    SCHEMA_VERSION,
    VERIFIER_ID,
    CatalogSchemaError,
    ContentScope,
    LegalSourceRightsPolicyError,
    audit_fixture_catalog,
    compute_artifact_digests,
    derive_expected_scope_frontier,
    frontier_digest_sha256,
    load_catalog_snapshot,
    load_spdx_registry,
    require_live_source_evidence,
    sha256_json,
)


REPORT_SCHEMA = "ipfs_datasets_py/legal-source-rights-compliance@2"
CODE_VERSION = "2"


class AuditError(RuntimeError):
    pass


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _base64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _identity_fields(mode: str) -> dict[str, str]:
    if mode != "fixture":
        raise ValueError("the checked-in deterministic builder only emits fixture evidence")
    return {
        "producer": CATALOG_PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": FIXTURE_TASK_ID,
        "goal_id": FIXTURE_GOAL_ID,
        "evidence_mode": "fixture",
    }


def _evidence(
    *,
    kind: str,
    source_id: str,
    content_scope: str,
    url: str,
    observed_at: str,
    content: bytes,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_kind": kind,
        **_identity_fields("fixture"),
        "verifier_id": VERIFIER_ID,
        "source_id": source_id,
        "content_scope": content_scope,
        "url": url,
        "verifier_observed_at": observed_at,
        "content_bytes_base64": _base64(content),
        "content_sha256": _sha256(content),
    }
    body["evidence_digest_sha256"] = sha256_json(body)
    return body


def _condition_receipt(
    *,
    condition_id: str,
    source_id: str,
    content_scope: str,
    observed_at: str,
    request: bytes,
    response: bytes,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": CONDITION_EVIDENCE_SCHEMA_VERSION,
        **_identity_fields("fixture"),
        "verifier_id": VERIFIER_ID,
        "condition_id": condition_id,
        "source_id": source_id,
        "content_scope": content_scope,
        "verifier_observed_at": observed_at,
        "request_bytes_base64": _base64(request),
        "request_sha256": _sha256(request),
        "response_bytes_base64": _base64(response),
        "response_sha256": _sha256(response),
    }
    body["receipt_digest_sha256"] = sha256_json(body)
    return body


def _license_binding(scope: ContentScope) -> tuple[str, str, str]:
    if scope is ContentScope.STATUTORY_TEXT:
        return (
            "LicenseRef-US-State-Statutory-Text",
            "government_edicts_doctrine",
            "d48cb14da98ecaa1f06e2ba498b17cadd9f0adaea38ceb28d71759ed049c8508",
        )
    if scope is ContentScope.FEDERAL_GOVERNMENT_TEXT:
        return (
            "LicenseRef-US-Federal-Government-Work",
            "us_government_work",
            "46cbe5c99f7016f4f9ced6344bb297581c2a78dbc2bdd91e93b188a025484e1d",
        )
    if scope is ContentScope.ANNOTATIONS:
        return (
            "LicenseRef-Annotations-Reserved",
            "proprietary",
            "af79ff861db14427b987ea16dab361da37194d8eee69fc7e00ecb78073bcd610",
        )
    if scope is ContentScope.DATABASE_CONTENT:
        return (
            "LicenseRef-Database-Content-Reserved",
            "proprietary",
            "b6d3f8abf435c9ea6cc789adab780b03e88cb57169fee2a9e16a21aad9580bb9",
        )
    return (
        "LicenseRef-Site-Presentation-Reserved",
        "proprietary",
        "e445a14ae5519d72e26458c8ba81e080bb403fb2d45bd41bd2485fe6126b0da6",
    )


def build_fixture_catalog_payload() -> dict[str, Any]:
    """Build the deterministic, immutable 57-record fixture from canonical evidence."""

    registry = load_spdx_registry()
    if registry.active_license_count != 465 or registry.deprecated_license_count != 25:
        raise AuditError("complete SPDX source snapshot counts changed")
    frontier = derive_expected_scope_frontier()
    if len(frontier) != EXPECTED_FRONTIER_SIZE:
        raise AuditError("derived frontier is incomplete")

    records: list[dict[str, Any]] = []
    admitted_ids: list[str] = []
    for entry in frontier:
        scope = ContentScope(entry.content_scope)
        in_scope = scope in ADMISSIBLE_CONTENT_SCOPES
        conditional = entry.source_id == "ak-akleg-basis" and scope is ContentScope.STATUTORY_TEXT
        license_id, legal_basis, license_ref_digest = _license_binding(scope)
        if registry.license_ref(license_id) is None:
            raise AuditError(f"fixture LicenseRef is not registered: {license_id}")

        record_id = f"{entry.source_id}-{entry.content_scope}"
        terms_bytes = (
            f"LCR-082 fixture terms bytes for {entry.source_id}/{entry.content_scope}; "
            "the source URL and content scope are independently bound."
        ).encode("utf-8")
        robots_bytes = (
            f"User-agent: lcr-082-fixture\nAllow: /\n"
            f"# source={entry.source_id} scope={entry.content_scope}\n"
        ).encode("utf-8")
        terms = _evidence(
            kind="terms",
            source_id=entry.source_id,
            content_scope=entry.content_scope,
            url=entry.source_url,
            observed_at="2026-08-01T10:00:00Z",
            content=terms_bytes,
        )
        robots = _evidence(
            kind="robots",
            source_id=entry.source_id,
            content_scope=entry.content_scope,
            url=entry.source_url,
            observed_at="2026-08-01T10:05:00Z",
            content=robots_bytes,
        )
        conditions: list[str] = []
        receipts: list[dict[str, Any]] = []
        robots_disposition = "allowed"
        rights_disposition = "allowed" if in_scope else "prohibited"
        if scope is ContentScope.DATABASE_CONTENT:
            rights_disposition = "quarantined"
        if conditional:
            condition_id = "respect-crawl-delay-10-seconds"
            conditions = [condition_id]
            robots_disposition = "conditional"
            rights_disposition = "conditional"
            receipts = [
                _condition_receipt(
                    condition_id=condition_id,
                    source_id=entry.source_id,
                    content_scope=entry.content_scope,
                    observed_at="2026-08-01T10:10:00Z",
                    request=(
                        b"GET /basis/statutes.asp HTTP/1.1\r\n"
                        b"Host: www.akleg.gov\r\n"
                        b"User-Agent: lcr-082-fixture\r\n\r\n"
                    ),
                    response=(
                        b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                        b"X-Fixture-Crawl-Delay: 10\r\n\r\n"
                    ),
                )
            ]
        permissions = {
            "redistribution": in_scope,
            "derivatives": in_scope,
            "archive": in_scope,
        }
        record = {
            "record_id": record_id,
            "source_id": entry.source_id,
            "corpus_family": entry.corpus_family,
            "dataset_repo_id": entry.dataset_repo_id,
            "content_scope": entry.content_scope,
            "rights_disposition": rights_disposition,
            "license_spdx": license_id,
            "license_ref_digest_sha256": license_ref_digest,
            "legal_basis": legal_basis,
            "terms": terms,
            "robots": robots,
            "robots_access_disposition": robots_disposition,
            "access_conditions": conditions,
            "condition_evidence": receipts,
            "permissions": permissions,
            "attribution_notice": (
                f"Source {entry.source_id} ({entry.jurisdiction_or_authority}); "
                f"scope {entry.content_scope}. Not a substitute for the official source."
            ),
            "review_status": "reviewed",
            "reviewed_at": "2026-08-05T12:00:00Z",
            "sealed_at": "2026-08-08T12:00:00Z",
            "source_url": entry.source_url,
            "jurisdiction_or_authority": entry.jurisdiction_or_authority,
            "card_label_is_not_authority": True,
            "dataset_card_label": "other" if scope is ContentScope.FEDERAL_GOVERNMENT_TEXT else None,
            "notes": f"Deterministic {entry.origin} fixture projection; fixture-only and non-authorizing.",
        }
        records.append(record)
        if in_scope:
            admitted_ids.append(record_id)

    payload: dict[str, Any] = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "producer": CATALOG_PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": FIXTURE_TASK_ID,
        "goal_id": FIXTURE_GOAL_ID,
        "evidence_mode": "fixture",
        "policy_schema_version": SCHEMA_VERSION,
        "sealed_at": "2026-08-09T12:00:00Z",
        "authorizing_for_publication": False,
        "target_dataset_repo_ids": [
            "justicedao/ipfs_state_laws",
            "justicedao/ipfs_federal_register",
        ],
        "artifact_digests": compute_artifact_digests(),
        "expected_scope_frontier_sha256": frontier_digest_sha256(),
        "admitted_record_ids": admitted_ids,
        "description": (
            "Immutable LCR-082 fixture covering all 51 LCR-002 state sources and "
            "the content-scope projection of the exact pinned LCR-048 Federal baseline."
        ),
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "records": records,
    }
    payload["catalog_digest_sha256"] = sha256_json(payload)
    return payload


def run_fixture_check() -> dict[str, Any]:
    committed_bytes, committed = load_catalog_snapshot()
    generated = build_fixture_catalog_payload()
    generated_bytes = (
        json.dumps(generated, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    if committed_bytes != generated_bytes:
        raise AuditError(
            "committed fixture bytes differ from the deterministic canonical build; "
            "fixture bytes/digests must be deliberately regenerated and committed"
        )
    try:
        report = audit_fixture_catalog(committed)
    except LegalSourceRightsPolicyError as exc:
        raise AuditError(str(exc)) from exc
    result = dict(report)
    result.update(
        {
            "report_schema": REPORT_SCHEMA,
            "code_version": CODE_VERSION,
            "audit_producer": CATALOG_PRODUCER,
            "mode": "fixture_only",
            "status": "passed",
            "authorizing_for_publication": False,
            "fixture_only_non_authorizing": True,
        }
    )
    result["report_digest_sha256"] = sha256_json(result)
    return result


def run_live_check() -> dict[str, Any]:
    try:
        report = require_live_source_evidence()
    except LegalSourceRightsPolicyError as exc:
        raise AuditError(str(exc)) from exc
    result = dict(report)
    result.update(
        {
            "report_schema": REPORT_SCHEMA,
            "code_version": CODE_VERSION,
            "audit_producer": CATALOG_PRODUCER,
            "mode": "live",
            "status": "passed",
        }
    )
    result["report_digest_sha256"] = sha256_json(result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit LCR-082 source-rights authority")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture-only", action="store_true")
    mode.add_argument("--require-live-source-evidence", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--emit-deterministic-fixture",
        action="store_true",
        help="Print the canonical fixture to stdout without writing any path.",
    )
    return parser


def _print_json(value: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.emit_deterministic_fixture:
        if not args.fixture_only or args.require_live_source_evidence or args.check:
            sys.stderr.write(
                "audit_legal_source_rights: FAILED: fixture emission requires "
                "--fixture-only without --check\n"
            )
            return 2
        try:
            _print_json(build_fixture_catalog_payload())
        except Exception as exc:  # noqa: BLE001 - fail closed
            sys.stderr.write(f"audit_legal_source_rights: FAILED: {exc}\n")
            return 1
        return 0
    if not args.check:
        sys.stderr.write("audit_legal_source_rights: FAILED: --check is required\n")
        return 2
    try:
        report = run_fixture_check() if args.fixture_only else run_live_check()
    except (AuditError, CatalogSchemaError) as exc:
        if args.json:
            _print_json(
                {
                    "status": "failed",
                    "producer": CATALOG_PRODUCER,
                    "program_id": PROGRAM_ID,
                    "authorizing_for_publication": False,
                    "error": str(exc),
                }
            )
        else:
            sys.stderr.write(f"audit_legal_source_rights: FAILED: {exc}\n")
        return 1
    if args.json:
        _print_json(report)
    else:
        sys.stdout.write(
            f"audit_legal_source_rights: PASSED ({report['mode']})\n"
            f"  records={report['record_count']} admitted={report['admitted_count']} "
            f"denied={report['denied_count']}\n"
            f"  authorizing_for_publication={report['authorizing_for_publication']}\n"
            f"  catalog_digest={report['catalog_digest_sha256']}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
