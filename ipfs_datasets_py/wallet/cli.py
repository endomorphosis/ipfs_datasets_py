"""CLI for the unified generic wallet."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from ipfs_datasets_py.wallet import WalletService
from ipfs_datasets_py.wallet.crypto import random_key
from ipfs_datasets_py.wallet.storage import LocalEncryptedBlobStore
from ipfs_datasets_py.wallet.ucan import (
    invocation_from_token,
    invocation_to_token,
    resource_for_export,
    resource_for_record,
)


def _default_wallet_dir() -> Path:
    return Path.home() / ".ipfs_datasets" / "wallet" / "manifests"


def _default_blob_dir() -> Path:
    return Path.home() / ".ipfs_datasets" / "wallet" / "blobs"


def _key_from_arg(value: str) -> bytes:
    if value.startswith("env:"):
        env_name = value.removeprefix("env:")
        value = os.environ.get(env_name, "")
        if not value:
            raise ValueError(f"environment variable is empty or unset: {env_name}")
    key = bytes.fromhex(value)
    if len(key) != 32:
        raise ValueError("wallet key must decode to 32 bytes")
    return key


def _wallet_path(wallet_dir: Path, wallet_id: str) -> Path:
    return wallet_dir / f"{wallet_id}.json"


def _service(blob_dir: Path) -> WalletService:
    return WalletService(storage_backend=LocalEncryptedBlobStore(blob_dir))


def _save(service: WalletService, wallet_dir: Path, wallet_id: str) -> Path:
    wallet_dir.mkdir(parents=True, exist_ok=True)
    path = _wallet_path(wallet_dir, wallet_id)
    path.write_text(json.dumps(service.export_wallet_snapshot(wallet_id), sort_keys=True, indent=2), encoding="utf-8")
    return path


def _load(wallet_dir: Path, blob_dir: Path, wallet_id: str) -> WalletService:
    service = _service(blob_dir)
    snapshot = json.loads(_wallet_path(wallet_dir, wallet_id).read_text(encoding="utf-8"))
    service.import_wallet_snapshot(snapshot)
    return service


def _load_all(wallet_dir: Path, blob_dir: Path) -> WalletService:
    service = _service(blob_dir)
    if not wallet_dir.exists():
        return service
    for path in sorted(wallet_dir.glob("wallet-*.json")):
        service.import_wallet_snapshot(json.loads(path.read_text(encoding="utf-8")))
    return service


def _save_all(service: WalletService, wallet_dir: Path, wallet_ids: Iterable[str]) -> None:
    for wallet_id in sorted(set(wallet_ids)):
        _save(service, wallet_dir, wallet_id)


def _parse_key_value_items(items: list[str] | None) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"expected KEY=VALUE field, got: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("field key cannot be empty")
        parsed[key] = value
    return parsed


def _aggregate_result_summary(result) -> Dict[str, Any]:
    return {
        "result_id": result.result_id,
        "template_id": result.template_id,
        "metric": result.metric,
        "released": result.released,
        "suppressed": result.suppressed,
        "count": result.count if result.exact_count_released else None,
        "noisy_count": result.noisy_count if result.released else None,
        "min_cohort_size": result.min_cohort_size,
        "epsilon": result.epsilon,
        "privacy_budget_key": result.privacy_budget_key,
        "privacy_budget_spent": result.privacy_budget_spent,
        "privacy_notes": list(result.privacy_notes),
    }


def _emit(result: Dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(result, sort_keys=True, indent=2))
        return
    status = result.get("status", "ok")
    print(f"status: {status}")
    for key, value in result.items():
        if key != "status":
            print(f"{key}: {value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ipfs-datasets wallet")
    parser.add_argument("--wallet-dir", type=Path, default=_default_wallet_dir())
    parser.add_argument("--blob-dir", type=Path, default=_default_blob_dir())
    parser.add_argument("--json", action="store_true", dest="json_output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("generate-key", help="Generate a local 256-bit wallet key")

    create = subparsers.add_parser("create", help="Create a wallet manifest")
    create.add_argument("--owner-did", required=True)
    create.add_argument("--controller-did", action="append", default=[])
    create.add_argument("--approval-threshold", type=int)

    add = subparsers.add_parser("add", help="Encrypt and add a document record")
    add.add_argument("--wallet-id", required=True)
    add.add_argument("--actor-did", required=True)
    add.add_argument("--key-hex", required=True)
    add.add_argument("--path", type=Path, required=True)
    add.add_argument("--title")
    add.add_argument("--category")

    list_records = subparsers.add_parser("list", help="List wallet records")
    list_records.add_argument("--wallet-id", required=True)
    list_records.add_argument("--actor-did", required=True)

    decrypt = subparsers.add_parser("decrypt", help="Decrypt a record to a local file")
    decrypt.add_argument("--wallet-id", required=True)
    decrypt.add_argument("--document-id", "--record-id", dest="record_id", required=True)
    decrypt.add_argument("--actor-did", required=True)
    decrypt.add_argument("--key-hex", required=True)
    decrypt.add_argument("--out", type=Path, required=True)
    decrypt.add_argument("--grant-id")

    analyze = subparsers.add_parser("analyze", help="Run a permitted derived analysis")
    analyze.add_argument("--wallet-id", required=True)
    analyze.add_argument("--document-id", "--record-id", dest="record_id", required=True)
    analyze.add_argument("--actor-did", required=True)
    analyze.add_argument("--key-hex", required=True)
    analyze.add_argument("--grant-id")
    analyze.add_argument("--output-type", default="summary")

    issue_invocation = subparsers.add_parser("issue-invocation", help="Issue a signed invocation token for a grant")
    issue_invocation.add_argument("--wallet-id", required=True)
    issue_invocation.add_argument("--document-id", "--record-id", dest="record_id", required=True)
    issue_invocation.add_argument("--grant-id", required=True)
    issue_invocation.add_argument("--actor-did", required=True)
    issue_invocation.add_argument("--key-hex", required=True)
    issue_invocation.add_argument("--ability", required=True)
    issue_invocation.add_argument("--caveat", action="append", default=[], help="Invocation caveat as KEY=VALUE")
    issue_invocation.add_argument("--expires-at")

    analyze_invocation = subparsers.add_parser("analyze-invocation", help="Run derived analysis using an invocation token")
    analyze_invocation.add_argument("--wallet-id", required=True)
    analyze_invocation.add_argument("--document-id", "--record-id", dest="record_id", required=True)
    analyze_invocation.add_argument("--actor-did", required=True)
    analyze_invocation.add_argument("--key-hex", required=True)
    analyze_invocation.add_argument("--invocation-token", required=True)

    decrypt_invocation = subparsers.add_parser("decrypt-invocation", help="Decrypt a record using an invocation token")
    decrypt_invocation.add_argument("--wallet-id", required=True)
    decrypt_invocation.add_argument("--document-id", "--record-id", dest="record_id", required=True)
    decrypt_invocation.add_argument("--actor-did", required=True)
    decrypt_invocation.add_argument("--key-hex", required=True)
    decrypt_invocation.add_argument("--invocation-token", required=True)
    decrypt_invocation.add_argument("--out", type=Path, required=True)

    share = subparsers.add_parser("share", help="Share a record with a delegate")
    share.add_argument("--wallet-id", required=True)
    share.add_argument("--document-id", "--record-id", dest="record_id", required=True)
    share.add_argument("--issuer-did", required=True)
    share.add_argument("--audience-did", required=True)
    share.add_argument("--issuer-key-hex", required=True)
    share.add_argument("--recipient-key-hex", required=True)
    share.add_argument("--can", dest="ability", choices=["record/analyze", "record/decrypt"], required=True)
    share.add_argument("--output-type", action="append", default=[])
    share.add_argument("--purpose", default="service_matching")
    share.add_argument("--expires-at")
    share.add_argument("--approval-ref")
    share.add_argument("--issue-invocation", action="store_true")
    share.add_argument("--invocation-expires-at")

    export_grant = subparsers.add_parser("export-grant", help="Grant a delegate bounded encrypted export access")
    export_grant.add_argument("--wallet-id", required=True)
    export_grant.add_argument("--record-id", action="append", required=True)
    export_grant.add_argument("--issuer-did", required=True)
    export_grant.add_argument("--audience-did", required=True)
    export_grant.add_argument("--issuer-key-hex", required=True)
    export_grant.add_argument("--recipient-key-hex", required=True)
    export_grant.add_argument("--purpose", default="user_export")
    export_grant.add_argument("--expires-at")
    export_grant.add_argument("--approval-ref")
    export_grant.add_argument("--issue-invocation", action="store_true")
    export_grant.add_argument("--invocation-expires-at")

    export_invocation = subparsers.add_parser("export-invocation", help="Issue a signed export invocation token")
    export_invocation.add_argument("--wallet-id", required=True)
    export_invocation.add_argument("--grant-id", required=True)
    export_invocation.add_argument("--actor-did", required=True)
    export_invocation.add_argument("--key-hex", required=True)
    export_invocation.add_argument("--record-id", action="append", default=[])
    export_invocation.add_argument("--expires-at")

    export_bundle = subparsers.add_parser("export-bundle", help="Create a bounded encrypted wallet export bundle")
    export_bundle.add_argument("--wallet-id", required=True)
    export_bundle.add_argument("--actor-did", required=True)
    export_bundle.add_argument("--key-hex")
    export_bundle.add_argument("--grant-id")
    export_bundle.add_argument("--invocation-token")
    export_bundle.add_argument("--record-id", action="append", default=[])
    export_bundle.add_argument("--out", type=Path, required=True)
    export_bundle.add_argument("--exclude-proofs", action="store_true")
    export_bundle.add_argument("--exclude-derived-artifacts", action="store_true")

    verify_export_bundle = subparsers.add_parser("verify-export-bundle", help="Verify an encrypted export bundle receipt")
    verify_export_bundle.add_argument("--path", type=Path, required=True)

    access_requests = subparsers.add_parser("access-requests", help="List access requests")
    access_requests.add_argument("--wallet-id", required=True)
    access_requests.add_argument("--status", choices=["pending", "approved", "rejected", "revoked", "all"], default="pending")
    access_requests.add_argument("--requester-did")
    access_requests.add_argument("--audience-did")

    request_access = subparsers.add_parser("request-access", help="Request access to a wallet record")
    request_access.add_argument("--wallet-id", required=True)
    request_access.add_argument("--document-id", "--record-id", dest="record_id", required=True)
    request_access.add_argument("--requester-did", required=True)
    request_access.add_argument("--audience-did")
    request_access.add_argument("--ability", action="append", required=True)
    request_access.add_argument("--purpose", required=True)
    request_access.add_argument("--expires-at")

    approve_access = subparsers.add_parser("approve-access", help="Approve an access request")
    approve_access.add_argument("--wallet-id", required=True)
    approve_access.add_argument("--request-id", required=True)
    approve_access.add_argument("--actor-did", required=True)
    approve_access.add_argument("--issuer-key-hex", required=True)
    approve_access.add_argument("--recipient-key-hex", required=True)
    approve_access.add_argument("--approval-ref")
    approve_access.add_argument("--issue-invocation", action="store_true")
    approve_access.add_argument("--invocation-expires-at")

    reject_access = subparsers.add_parser("reject-access", help="Reject an access request")
    reject_access.add_argument("--wallet-id", required=True)
    reject_access.add_argument("--request-id", required=True)
    reject_access.add_argument("--actor-did", required=True)
    reject_access.add_argument("--reason")

    revoke_access = subparsers.add_parser("revoke-access", help="Revoke an approved access request")
    revoke_access.add_argument("--wallet-id", required=True)
    revoke_access.add_argument("--request-id", required=True)
    revoke_access.add_argument("--actor-did", required=True)
    revoke_access.add_argument("--reason")

    grant = subparsers.add_parser("grant", help="Grant record access")
    grant.add_argument("--wallet-id", required=True)
    grant.add_argument("--document-id", "--record-id", dest="record_id", required=True)
    grant.add_argument("--issuer-did", required=True)
    grant.add_argument("--audience-did", required=True)
    grant.add_argument("--issuer-key-hex", required=True)
    grant.add_argument("--recipient-key-hex", required=True)
    grant.add_argument("--ability", action="append", required=True)
    grant.add_argument("--output-type", action="append", default=[])
    grant.add_argument("--purpose", choices=["decrypt", "analyze"], default="analyze")
    grant.add_argument("--expires-at")
    grant.add_argument("--approval-ref")

    request_approval = subparsers.add_parser("request-approval", help="Request threshold approval")
    request_approval.add_argument("--wallet-id", required=True)
    request_approval.add_argument("--requested-by", required=True)
    request_approval.add_argument("--operation", default="grant/create")
    request_approval.add_argument("--resource", action="append", required=True)
    request_approval.add_argument("--ability", action="append", required=True)
    request_approval.add_argument("--expires-at")

    approve_approval = subparsers.add_parser("approve-approval", help="Approve a threshold request")
    approve_approval.add_argument("--wallet-id", required=True)
    approve_approval.add_argument("--approval-id", required=True)
    approve_approval.add_argument("--approver-did", required=True)

    revoke = subparsers.add_parser("revoke", help="Revoke a grant")
    revoke.add_argument("--wallet-id", required=True)
    revoke.add_argument("--actor-did", required=True)
    revoke.add_argument("--grant-id", required=True)

    verify_storage = subparsers.add_parser("verify-storage", help="Verify encrypted record storage replicas")
    verify_storage.add_argument("--wallet-id", required=True)
    verify_storage.add_argument("--document-id", "--record-id", dest="record_id", required=True)
    verify_storage.add_argument("--skip-metadata", action="store_true")

    repair_storage = subparsers.add_parser("repair-storage", help="Repair encrypted record storage replicas")
    repair_storage.add_argument("--wallet-id", required=True)
    repair_storage.add_argument("--document-id", "--record-id", dest="record_id", required=True)
    repair_storage.add_argument("--actor-did", required=True)
    repair_storage.add_argument("--skip-metadata", action="store_true")

    analytics_template = subparsers.add_parser("analytics-template", help="Register an aggregate analytics template")
    analytics_template.add_argument("--wallet-id", required=True)
    analytics_template.add_argument("--template-id", required=True)
    analytics_template.add_argument("--title", required=True)
    analytics_template.add_argument("--purpose", required=True)
    analytics_template.add_argument("--record-type", action="append", required=True)
    analytics_template.add_argument("--derived-field", action="append", required=True)
    analytics_template.add_argument("--min-cohort-size", type=int, default=10)
    analytics_template.add_argument("--epsilon-budget", type=float, default=1.0)
    analytics_template.add_argument("--created-by", required=True)
    analytics_template.add_argument("--expires-at")

    analytics_templates = subparsers.add_parser("analytics-templates", help="List active analytics templates")
    analytics_templates.add_argument("--wallet-id", required=True)
    analytics_templates.add_argument("--include-inactive", action="store_true")

    analytics_consent = subparsers.add_parser("analytics-consent", help="Create consent from an analytics template")
    analytics_consent.add_argument("--wallet-id", required=True)
    analytics_consent.add_argument("--actor-did", required=True)
    analytics_consent.add_argument("--template-id", required=True)
    analytics_consent.add_argument("--expires-at")

    analytics_contribute = subparsers.add_parser("analytics-contribute", help="Submit derived analytics fields")
    analytics_contribute.add_argument("--wallet-id", required=True)
    analytics_contribute.add_argument("--actor-did", required=True)
    analytics_contribute.add_argument("--consent-id", required=True)
    analytics_contribute.add_argument("--template-id", required=True)
    analytics_contribute.add_argument("--field", action="append", required=True, help="Derived field as KEY=VALUE")

    analytics_count = subparsers.add_parser("analytics-count", help="Run a private aggregate count")
    analytics_count.add_argument("--wallet-id", required=True)
    analytics_count.add_argument("--template-id", required=True)
    analytics_count.add_argument("--epsilon", type=float)
    analytics_count.add_argument("--min-cohort-size", type=int)
    analytics_count.add_argument("--budget-key")
    analytics_count.add_argument("--budget-limit", type=float)
    analytics_count.add_argument("--actor-did", default="did:service:ipfs-datasets-cli")

    audit = subparsers.add_parser("audit", help="Show wallet audit event count and head")
    audit.add_argument("--wallet-id", required=True)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "generate-key":
            _emit({"status": "ok", "key_hex": random_key().hex()}, json_output=args.json_output)
            return 0

        if args.command == "verify-export-bundle":
            service = _service(args.blob_dir)
            bundle = json.loads(args.path.read_text(encoding="utf-8"))
            computed_hash = service.export_bundle_hash(bundle)
            _emit(
                {
                    "status": "ok",
                    "valid": service.verify_export_bundle(bundle),
                    "bundle_id": bundle.get("bundle_id"),
                    "bundle_hash": bundle.get("bundle_hash"),
                    "computed_hash": computed_hash,
                },
                json_output=args.json_output,
            )
            return 0

        if args.command == "create":
            controllers = args.controller_did or [args.owner_did]
            if args.owner_did not in controllers:
                controllers = [args.owner_did, *controllers]
            governance_policy: Dict[str, Any] = {}
            if args.approval_threshold is not None:
                governance_policy["threshold"] = args.approval_threshold
                governance_policy["approver_dids"] = controllers
            service = _service(args.blob_dir)
            wallet = service.create_wallet(
                owner_did=args.owner_did,
                controller_dids=controllers,
                governance_policy=governance_policy,
            )
            path = _save(service, args.wallet_dir, wallet.wallet_id)
            _emit({"status": "ok", "wallet_id": wallet.wallet_id, "manifest_head": wallet.manifest_head, "path": str(path)}, json_output=args.json_output)
            return 0

        analytics_commands = {
            "analytics-template",
            "analytics-templates",
            "analytics-consent",
            "analytics-contribute",
            "analytics-count",
        }
        service = (
            _load_all(args.wallet_dir, args.blob_dir)
            if args.command in analytics_commands
            else _load(args.wallet_dir, args.blob_dir, args.wallet_id)
        )

        if args.command == "analytics-template":
            service._wallet(args.wallet_id)
            template = service.create_analytics_template(
                template_id=args.template_id,
                title=args.title,
                purpose=args.purpose,
                allowed_record_types=args.record_type,
                allowed_derived_fields=args.derived_field,
                aggregation_policy={
                    "min_cohort_size": args.min_cohort_size,
                    "epsilon_budget": args.epsilon_budget,
                    "duplicate_policy": "reject_by_nullifier",
                },
                created_by=args.created_by,
                expires_at=args.expires_at,
            )
            _save(service, args.wallet_dir, args.wallet_id)
            _emit({"status": "ok", **template.to_dict()}, json_output=args.json_output)
            return 0

        if args.command == "analytics-templates":
            service._wallet(args.wallet_id)
            templates = [
                template.to_dict()
                for template in service.list_analytics_templates(include_inactive=args.include_inactive)
            ]
            _emit({"status": "ok", "templates": templates}, json_output=args.json_output)
            return 0

        if args.command == "analytics-consent":
            wallet = service._wallet(args.wallet_id)
            template = service.analytics_templates[args.template_id]
            consent = service.create_analytics_consent(
                args.wallet_id,
                actor_did=args.actor_did,
                template_id=args.template_id,
                allowed_record_types=list(template.allowed_record_types),
                allowed_derived_fields=list(template.allowed_derived_fields),
                expires_at=args.expires_at,
            )
            _save(service, args.wallet_dir, wallet.wallet_id)
            _emit({"status": "ok", **consent.to_dict()}, json_output=args.json_output)
            return 0

        if args.command == "analytics-contribute":
            contribution = service.create_analytics_contribution(
                args.wallet_id,
                actor_did=args.actor_did,
                consent_id=args.consent_id,
                template_id=args.template_id,
                fields=_parse_key_value_items(args.field),
            )
            _save(service, args.wallet_dir, args.wallet_id)
            _emit({"status": "ok", **contribution.to_dict()}, json_output=args.json_output)
            return 0

        if args.command == "analytics-count":
            result = service.run_aggregate_count(
                args.template_id,
                min_cohort_size=args.min_cohort_size,
                epsilon=args.epsilon,
                budget_key=args.budget_key,
                budget_limit=args.budget_limit,
                actor_did=args.actor_did,
            )
            participating_wallet_ids = [
                consent.wallet_id
                for consent in service.analytics_consents.values()
                if consent.template_id == args.template_id
            ]
            _save_all(service, args.wallet_dir, participating_wallet_ids or [args.wallet_id])
            _emit({"status": "ok", **_aggregate_result_summary(result)}, json_output=args.json_output)
            return 0

        if args.command == "add":
            metadata: Dict[str, Any] = {"filename": args.path.name}
            if args.title:
                metadata["title"] = args.title
            if args.category:
                metadata["category"] = args.category
            record = service.add_record(
                args.wallet_id,
                data_type="document",
                plaintext=args.path.read_bytes(),
                actor_did=args.actor_did,
                actor_secret=_key_from_arg(args.key_hex),
                private_metadata=metadata,
                sensitivity="restricted",
                public_descriptor="document",
            )
            _save(service, args.wallet_dir, args.wallet_id)
            _emit(
                {
                    "status": "ok",
                    "wallet_id": args.wallet_id,
                    "document_id": record.record_id,
                    "record_id": record.record_id,
                    "version_id": record.current_version_id,
                    "payload_ref": service.versions[record.current_version_id].encrypted_payload_ref.uri,
                },
                json_output=args.json_output,
            )
            return 0

        if args.command == "list":
            records = [
                record.to_dict()
                for record in sorted(service.records.values(), key=lambda item: item.record_id)
                if record.wallet_id == args.wallet_id
            ]
            _emit({"status": "ok", "wallet_id": args.wallet_id, "records": records}, json_output=args.json_output)
            return 0

        if args.command == "decrypt":
            plaintext = service.decrypt_record(
                args.wallet_id,
                args.record_id,
                actor_did=args.actor_did,
                grant_id=args.grant_id,
                actor_secret=_key_from_arg(args.key_hex),
            )
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_bytes(plaintext)
            _save(service, args.wallet_dir, args.wallet_id)
            _emit({"status": "ok", "out": str(args.out), "size_bytes": len(plaintext)}, json_output=args.json_output)
            return 0

        if args.command == "analyze":
            artifact = service.analyze_record_summary(
                args.wallet_id,
                args.record_id,
                actor_did=args.actor_did,
                grant_id=args.grant_id,
                actor_secret=_key_from_arg(args.key_hex),
            )
            _save(service, args.wallet_dir, args.wallet_id)
            _emit({"status": "ok", **artifact.to_dict()}, json_output=args.json_output)
            return 0

        if args.command == "issue-invocation":
            invocation = service.issue_invocation(
                args.wallet_id,
                grant_id=args.grant_id,
                actor_did=args.actor_did,
                resource=resource_for_record(args.wallet_id, args.record_id),
                ability=args.ability,
                actor_secret=_key_from_arg(args.key_hex),
                caveats=_parse_key_value_items(args.caveat),
                expires_at=args.expires_at,
            )
            _save(service, args.wallet_dir, args.wallet_id)
            _emit(
                {
                    "status": "ok",
                    "invocation_id": invocation.invocation_id,
                    "grant_id": invocation.grant_id,
                    "ability": invocation.ability,
                    "resource": invocation.resource,
                    "invocation_token": invocation_to_token(invocation),
                },
                json_output=args.json_output,
            )
            return 0

        if args.command == "analyze-invocation":
            artifact = service.analyze_record_summary_with_invocation(
                args.wallet_id,
                args.record_id,
                actor_did=args.actor_did,
                invocation=invocation_from_token(args.invocation_token),
                actor_secret=_key_from_arg(args.key_hex),
            )
            _save(service, args.wallet_dir, args.wallet_id)
            _emit({"status": "ok", **artifact.to_dict()}, json_output=args.json_output)
            return 0

        if args.command == "decrypt-invocation":
            plaintext = service.decrypt_record_with_invocation(
                args.wallet_id,
                args.record_id,
                actor_did=args.actor_did,
                invocation=invocation_from_token(args.invocation_token),
                actor_secret=_key_from_arg(args.key_hex),
            )
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_bytes(plaintext)
            _save(service, args.wallet_dir, args.wallet_id)
            _emit({"status": "ok", "out": str(args.out), "size_bytes": len(plaintext)}, json_output=args.json_output)
            return 0

        if args.command == "share":
            caveats: Dict[str, Any] = {"purpose": args.purpose}
            if args.output_type:
                caveats["output_types"] = args.output_type
            if args.expires_at is not None:
                caveats["expires_at"] = args.expires_at
            if args.approval_ref:
                caveats["approval_ref"] = args.approval_ref
            grant = service.create_grant(
                wallet_id=args.wallet_id,
                issuer_did=args.issuer_did,
                audience_did=args.audience_did,
                resources=[resource_for_record(args.wallet_id, args.record_id)],
                abilities=[args.ability],
                caveats=caveats,
                expires_at=args.expires_at,
                approval_id=args.approval_ref,
                issuer_secret=_key_from_arg(args.issuer_key_hex),
                audience_secret=_key_from_arg(args.recipient_key_hex),
            )
            result: Dict[str, Any] = {
                "status": "ok",
                "grant_id": grant.grant_id,
                "audience_did": grant.audience_did,
                "ability": args.ability,
                "resource": resource_for_record(args.wallet_id, args.record_id),
            }
            if args.issue_invocation:
                invocation = service.issue_invocation(
                    args.wallet_id,
                    grant_id=grant.grant_id,
                    actor_did=args.audience_did,
                    resource=resource_for_record(args.wallet_id, args.record_id),
                    ability=args.ability,
                    actor_secret=_key_from_arg(args.recipient_key_hex),
                    caveats={"purpose": args.purpose},
                    expires_at=args.invocation_expires_at,
                )
                result.update(
                    {
                        "invocation_id": invocation.invocation_id,
                        "invocation_token": invocation_to_token(invocation),
                    }
                )
            _save(service, args.wallet_dir, args.wallet_id)
            _emit(result, json_output=args.json_output)
            return 0

        if args.command == "export-grant":
            grant = service.create_grant(
                wallet_id=args.wallet_id,
                issuer_did=args.issuer_did,
                audience_did=args.audience_did,
                resources=[resource_for_export(args.wallet_id)],
                abilities=["export/create"],
                caveats={"purpose": args.purpose, "record_ids": list(args.record_id)},
                expires_at=args.expires_at,
                approval_id=args.approval_ref,
                issuer_secret=_key_from_arg(args.issuer_key_hex),
                audience_secret=_key_from_arg(args.recipient_key_hex),
            )
            result: Dict[str, Any] = {
                "status": "ok",
                "grant_id": grant.grant_id,
                "audience_did": grant.audience_did,
                "ability": "export/create",
                "resource": resource_for_export(args.wallet_id),
                "record_ids": list(args.record_id),
            }
            if args.issue_invocation:
                invocation = service.issue_invocation(
                    args.wallet_id,
                    grant_id=grant.grant_id,
                    actor_did=args.audience_did,
                    resource=resource_for_export(args.wallet_id),
                    ability="export/create",
                    actor_secret=_key_from_arg(args.recipient_key_hex),
                    caveats={"purpose": args.purpose, "record_ids": list(args.record_id)},
                    expires_at=args.invocation_expires_at,
                )
                result.update(
                    {
                        "invocation_id": invocation.invocation_id,
                        "invocation_token": invocation_to_token(invocation),
                    }
                )
            _save(service, args.wallet_dir, args.wallet_id)
            _emit(result, json_output=args.json_output)
            return 0

        if args.command == "export-invocation":
            caveats: Dict[str, Any] = {"purpose": "user_export"}
            if args.record_id:
                caveats["record_ids"] = list(args.record_id)
            invocation = service.issue_invocation(
                args.wallet_id,
                grant_id=args.grant_id,
                actor_did=args.actor_did,
                resource=resource_for_export(args.wallet_id),
                ability="export/create",
                actor_secret=_key_from_arg(args.key_hex),
                caveats=caveats,
                expires_at=args.expires_at,
            )
            _save(service, args.wallet_dir, args.wallet_id)
            _emit(
                {
                    "status": "ok",
                    "invocation_id": invocation.invocation_id,
                    "grant_id": invocation.grant_id,
                    "ability": invocation.ability,
                    "resource": invocation.resource,
                    "invocation_token": invocation_to_token(invocation),
                },
                json_output=args.json_output,
            )
            return 0

        if args.command == "export-bundle":
            record_ids = list(args.record_id) if args.record_id else None
            if args.invocation_token:
                bundle = service.create_export_bundle_with_invocation(
                    args.wallet_id,
                    actor_did=args.actor_did,
                    invocation=invocation_from_token(args.invocation_token),
                    actor_secret=_key_from_arg(args.key_hex) if args.key_hex else None,
                    record_ids=record_ids,
                    include_proofs=not args.exclude_proofs,
                    include_derived_artifacts=not args.exclude_derived_artifacts,
                )
            else:
                bundle = service.create_export_bundle(
                    args.wallet_id,
                    actor_did=args.actor_did,
                    grant_id=args.grant_id,
                    record_ids=record_ids,
                    include_proofs=not args.exclude_proofs,
                    include_derived_artifacts=not args.exclude_derived_artifacts,
                )
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(bundle, sort_keys=True, indent=2), encoding="utf-8")
            _save(service, args.wallet_dir, args.wallet_id)
            _emit(
                {
                    "status": "ok",
                    "out": str(args.out),
                    "wallet_id": args.wallet_id,
                    "bundle_id": bundle["bundle_id"],
                    "bundle_hash": bundle["bundle_hash"],
                    "record_count": len(bundle["records"]),
                    "proof_count": len(bundle["proofs"]),
                    "derived_artifact_count": len(bundle["derived_artifacts"]),
                },
                json_output=args.json_output,
            )
            return 0

        if args.command == "access-requests":
            status = None if args.status == "all" else args.status
            requests = [
                request.to_dict()
                for request in service.list_access_requests(
                    args.wallet_id,
                    status=status,
                    requester_did=args.requester_did,
                    audience_did=args.audience_did,
                )
            ]
            _emit({"status": "ok", "wallet_id": args.wallet_id, "requests": requests}, json_output=args.json_output)
            return 0

        if args.command == "request-access":
            request = service.request_access(
                args.wallet_id,
                requester_did=args.requester_did,
                audience_did=args.audience_did,
                resources=[resource_for_record(args.wallet_id, args.record_id)],
                abilities=args.ability,
                purpose=args.purpose,
                expires_at=args.expires_at,
            )
            _save(service, args.wallet_dir, args.wallet_id)
            _emit({"status": "ok", **request.to_dict()}, json_output=args.json_output)
            return 0

        if args.command == "approve-access":
            request = service.approve_access_request(
                args.wallet_id,
                request_id=args.request_id,
                actor_did=args.actor_did,
                issuer_secret=_key_from_arg(args.issuer_key_hex),
                audience_secret=_key_from_arg(args.recipient_key_hex),
                approval_id=args.approval_ref,
                issue_invocation=args.issue_invocation,
                invocation_expires_at=args.invocation_expires_at,
            )
            result: Dict[str, Any] = {"status": "ok", **request.to_dict()}
            if request.invocation_id:
                result["invocation_token"] = invocation_to_token(service.invocations[request.invocation_id])
            _save(service, args.wallet_dir, args.wallet_id)
            _emit(result, json_output=args.json_output)
            return 0

        if args.command == "reject-access":
            request = service.reject_access_request(
                args.wallet_id,
                request_id=args.request_id,
                actor_did=args.actor_did,
                reason=args.reason,
            )
            _save(service, args.wallet_dir, args.wallet_id)
            _emit({"status": "ok", **request.to_dict()}, json_output=args.json_output)
            return 0

        if args.command == "revoke-access":
            request = service.revoke_access_request(
                args.wallet_id,
                request_id=args.request_id,
                actor_did=args.actor_did,
                reason=args.reason,
            )
            _save(service, args.wallet_dir, args.wallet_id)
            _emit({"status": "ok", **request.to_dict()}, json_output=args.json_output)
            return 0

        if args.command == "grant":
            caveats: Dict[str, Any] = {}
            if args.output_type:
                caveats["output_types"] = args.output_type
            if args.expires_at is not None:
                caveats["expires_at"] = args.expires_at
            if args.approval_ref:
                caveats["approval_ref"] = args.approval_ref
            grant = service.create_grant(
                wallet_id=args.wallet_id,
                issuer_did=args.issuer_did,
                audience_did=args.audience_did,
                resources=[resource_for_record(args.wallet_id, args.record_id)],
                abilities=args.ability,
                caveats=caveats,
                expires_at=args.expires_at,
                approval_id=args.approval_ref,
                issuer_secret=_key_from_arg(args.issuer_key_hex),
                audience_secret=_key_from_arg(args.recipient_key_hex),
            )
            _save(service, args.wallet_dir, args.wallet_id)
            _emit({"status": "ok", "grant_id": grant.grant_id, "audience_did": grant.audience_did}, json_output=args.json_output)
            return 0

        if args.command == "request-approval":
            request = service.request_approval(
                args.wallet_id,
                requested_by=args.requested_by,
                operation=args.operation,
                resources=args.resource,
                abilities=args.ability,
                expires_at=args.expires_at,
            )
            _save(service, args.wallet_dir, args.wallet_id)
            _emit({"status": "ok", "approval_id": request.approval_id, "approval_status": request.status, "threshold": request.threshold}, json_output=args.json_output)
            return 0

        if args.command == "approve-approval":
            request = service.approve_approval(args.wallet_id, approval_id=args.approval_id, approver_did=args.approver_did)
            _save(service, args.wallet_dir, args.wallet_id)
            _emit({"status": "ok", "approval_id": request.approval_id, "approval_status": request.status, "approved_count": request.approved_count}, json_output=args.json_output)
            return 0

        if args.command == "revoke":
            grant = service.revoke_grant(args.wallet_id, actor_did=args.actor_did, grant_id=args.grant_id)
            _save(service, args.wallet_dir, args.wallet_id)
            _emit({"status": "ok", "grant_id": grant.grant_id, "grant_status": grant.status}, json_output=args.json_output)
            return 0

        if args.command == "verify-storage":
            report = service.verify_record_storage(
                args.wallet_id,
                args.record_id,
                include_metadata=not args.skip_metadata,
            )
            _save(service, args.wallet_dir, args.wallet_id)
            _emit({"status": "ok", **report.to_dict()}, json_output=args.json_output)
            return 0

        if args.command == "repair-storage":
            report = service.repair_record_storage(
                args.wallet_id,
                args.record_id,
                actor_did=args.actor_did,
                include_metadata=not args.skip_metadata,
            )
            _save(service, args.wallet_dir, args.wallet_id)
            _emit({"status": "ok", **report.to_dict()}, json_output=args.json_output)
            return 0

        if args.command == "audit":
            events = service.get_audit_log(args.wallet_id)
            _emit({"status": "ok", "wallet_id": args.wallet_id, "event_count": len(events), "audit_head": events[-1].hash_self if events else None}, json_output=args.json_output)
            return 0

        raise ValueError(f"unsupported command: {args.command}")
    except Exception as exc:
        _emit({"status": "error", "error": str(exc)}, json_output=args.json_output)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
