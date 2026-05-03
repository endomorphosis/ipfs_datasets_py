"""CLI for the unified generic wallet."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from ipfs_datasets_py.wallet import WalletService
from ipfs_datasets_py.wallet.crypto import random_key
from ipfs_datasets_py.wallet.storage import LocalEncryptedBlobStore
from ipfs_datasets_py.wallet.ucan import resource_for_record


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

        service = _load(args.wallet_dir, args.blob_dir, args.wallet_id)

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
