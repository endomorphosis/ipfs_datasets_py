"""FastAPI adapter for the canonical Python wallet service.

This module exposes a thin HTTP surface over ``ipfs_datasets_py.wallet`` so
browser clients can treat Python as the wallet implementation boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import DataWalletError, WalletService
from .models import AccessRequest, AuditEvent, GrantReceipt, ProofReceipt
from .storage import LocalEncryptedBlobStore


class CreateWalletRequest(BaseModel):
    owner_did: str
    controller_dids: List[str] | None = None
    approval_threshold: int | None = Field(default=None, ge=1)


class WalletAccessRequestsResponse(BaseModel):
    requests: List[Dict[str, Any]]


class WalletGrantReceiptsResponse(BaseModel):
    receipts: List[Dict[str, Any]]


class WalletAuditEventsResponse(BaseModel):
    events: List[Dict[str, Any]]


class WalletRecordsResponse(BaseModel):
    records: List[Dict[str, Any]]


class WalletProofsResponse(BaseModel):
    proofs: List[Dict[str, Any]]


router = APIRouter(tags=["wallet"])


def default_wallet_dir() -> Path:
    return Path.home() / ".ipfs_datasets" / "wallet" / "manifests"


def default_blob_dir() -> Path:
    return Path.home() / ".ipfs_datasets" / "wallet" / "blobs"


def wallet_path(wallet_dir: Path, wallet_id: str) -> Path:
    return wallet_dir / f"{wallet_id}.json"


def _new_service(blob_dir: Path) -> WalletService:
    return WalletService(storage_backend=LocalEncryptedBlobStore(blob_dir))


def _save_wallet_snapshot(service: WalletService, wallet_dir: Path, wallet_id: str) -> None:
    wallet_dir.mkdir(parents=True, exist_ok=True)
    wallet_path(wallet_dir, wallet_id).write_text(
        json.dumps(service.export_wallet_snapshot(wallet_id), sort_keys=True),
        encoding="utf-8",
    )


def _load_wallet_service(wallet_id: str, wallet_dir: Path | None = None, blob_dir: Path | None = None) -> WalletService:
    manifest_dir = wallet_dir or default_wallet_dir()
    blob_root = blob_dir or default_blob_dir()
    path = wallet_path(manifest_dir, wallet_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Wallet not found: {wallet_id}")
    service = _new_service(blob_root)
    service.import_wallet_snapshot(json.loads(path.read_text(encoding="utf-8")))
    return service


def _sorted_records(service: WalletService, wallet_id: str, data_type: str | None = None) -> List[Dict[str, Any]]:
    records = []
    for record in sorted(service.records.values(), key=lambda item: item.record_id):
        if record.wallet_id != wallet_id:
            continue
        if data_type and record.data_type != data_type:
            continue
        payload = record.to_dict()
        version = service.versions.get(record.current_version_id)
        if version is not None:
            payload["metadata"] = {
                "encrypted_payload_ref": version.encrypted_payload_ref.to_dict(),
                "encrypted_metadata_ref": (
                    version.encrypted_metadata_ref.to_dict() if version.encrypted_metadata_ref else None
                ),
                "created_at": version.created_at,
            }
        records.append(payload)
    return records


def _wallet_proofs(service: WalletService, wallet_id: str) -> List[Dict[str, Any]]:
    return [
        proof.to_dict()
        for proof in sorted(service.proofs.values(), key=lambda item: item.created_at, reverse=True)
        if proof.wallet_id == wallet_id
    ]


def _serialize_many(values: List[AccessRequest] | List[GrantReceipt] | List[AuditEvent] | List[ProofReceipt]) -> List[Dict[str, Any]]:
    return [item.to_dict() for item in values]


@router.post("/wallets")
def create_wallet(request: CreateWalletRequest) -> Dict[str, Any]:
    wallet_dir = default_wallet_dir()
    blob_dir = default_blob_dir()
    service = _new_service(blob_dir)
    controllers = list(request.controller_dids or [request.owner_did])
    if request.owner_did not in controllers:
        controllers = [request.owner_did, *controllers]
    governance_policy: Dict[str, Any] = {}
    if request.approval_threshold is not None:
        governance_policy = {
            "threshold": request.approval_threshold,
            "approver_dids": controllers,
        }
    try:
        wallet = service.create_wallet(
            owner_did=request.owner_did,
            controller_dids=controllers,
            governance_policy=governance_policy,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet.wallet_id)
        return wallet.to_dict()
    except DataWalletError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/wallets/{wallet_id}")
def get_wallet(wallet_id: str) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    return service.get_wallet(wallet_id).to_dict()


@router.get("/wallets/{wallet_id}/records", response_model=WalletRecordsResponse)
def list_wallet_records(wallet_id: str, data_type: Optional[str] = Query(default=None)) -> WalletRecordsResponse:
    service = _load_wallet_service(wallet_id)
    return WalletRecordsResponse(records=_sorted_records(service, wallet_id, data_type))


@router.get("/wallets/{wallet_id}/proofs", response_model=WalletProofsResponse)
def list_wallet_proofs(wallet_id: str) -> WalletProofsResponse:
    service = _load_wallet_service(wallet_id)
    return WalletProofsResponse(proofs=_wallet_proofs(service, wallet_id))


@router.get("/wallets/{wallet_id}/audit", response_model=WalletAuditEventsResponse)
def list_wallet_audit(wallet_id: str) -> WalletAuditEventsResponse:
    service = _load_wallet_service(wallet_id)
    return WalletAuditEventsResponse(events=_serialize_many(service.get_audit_log(wallet_id)))


@router.get("/wallets/{wallet_id}/access-requests", response_model=WalletAccessRequestsResponse)
def list_wallet_access_requests(
    wallet_id: str,
    status: Optional[str] = Query(default=None),
    requester_did: Optional[str] = Query(default=None),
    audience_did: Optional[str] = Query(default=None),
) -> WalletAccessRequestsResponse:
    service = _load_wallet_service(wallet_id)
    requests = service.list_access_requests(
        wallet_id,
        status=None if status in (None, "all") else status,
        requester_did=requester_did,
        audience_did=audience_did,
    )
    return WalletAccessRequestsResponse(requests=_serialize_many(requests))


@router.get("/wallets/{wallet_id}/grant-receipts", response_model=WalletGrantReceiptsResponse)
def list_wallet_grant_receipts(
    wallet_id: str,
    status: Optional[str] = Query(default=None),
    audience_did: Optional[str] = Query(default=None),
) -> WalletGrantReceiptsResponse:
    service = _load_wallet_service(wallet_id)
    receipts = service.list_grant_receipts(
        wallet_id,
        audience_did=audience_did,
        status=None if status in (None, "all") else status,
    )
    return WalletGrantReceiptsResponse(receipts=_serialize_many(receipts))
