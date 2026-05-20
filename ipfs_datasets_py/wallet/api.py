"""FastAPI adapter for the canonical Python wallet service.

This module exposes a thin HTTP surface over ``ipfs_datasets_py.wallet`` so
browser clients can treat Python as the wallet implementation boundary.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from . import DataWalletError, WalletService
from .crypto import sha256_hex
from .manifest import canonical_bytes
from .models import AccessRequest, ApprovalRequest, AuditEvent, GrantReceipt, ProofReceipt
from .storage import LocalEncryptedBlobStore
from .ucan import invocation_from_token, invocation_to_token, resource_for_export, resource_for_record


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


class WalletApprovalsResponse(BaseModel):
    approvals: List[Dict[str, Any]]


class AddTextDocumentRequest(BaseModel):
    actor_did: str
    text: str
    filename: str = "document.txt"
    title: str | None = None
    key_hex: str | None = None


class RecordGrantRequest(BaseModel):
    issuer_did: str
    audience_did: str
    abilities: List[str] = Field(default_factory=lambda: ["record/analyze"])
    purpose: str = "service_matching"
    output_types: List[str] = Field(default_factory=list)
    user_presence_required: bool = False
    caveats: Dict[str, Any] = Field(default_factory=dict)
    issuer_key_hex: str | None = None
    audience_key_hex: str | None = None
    approval_id: str | None = None
    expires_at: str | None = None
    max_delegation_depth: int | None = None


class DelegateGrantRequest(BaseModel):
    issuer_did: str
    audience_did: str
    resources: List[str] = Field(default_factory=list)
    abilities: List[str] = Field(default_factory=list)
    caveats: Dict[str, Any] = Field(default_factory=dict)
    expires_at: str | None = None
    issuer_key_hex: str | None = None
    audience_key_hex: str | None = None


class AccessRequestCreateRequest(BaseModel):
    record_id: str
    requester_did: str
    ability: str = "record/analyze"
    audience_did: str | None = None
    purpose: str = "service_matching"
    expires_at: str | None = None


class AccessRequestDecisionRequest(BaseModel):
    actor_did: str
    issuer_key_hex: str | None = None
    audience_key_hex: str | None = None
    approval_id: str | None = None
    issue_invocation: bool = False
    invocation_expires_at: str | None = None
    reason: str | None = None


class ThresholdApprovalCreateRequest(BaseModel):
    requested_by: str
    operation: str = "grant/create"
    resources: List[str] = Field(default_factory=list)
    abilities: List[str] = Field(default_factory=list)
    expires_at: str | None = None


class ThresholdApprovalDecisionRequest(BaseModel):
    approver_did: str


class RotateRecordKeyRequest(BaseModel):
    actor_did: str
    actor_key_hex: str | None = None


class RepairStorageRequest(BaseModel):
    actor_did: str


class AnalysisInvocationRequest(BaseModel):
    grant_id: str
    actor_did: str
    actor_key_hex: str | None = None
    expires_at: str | None = None
    purpose: str | None = None
    output_types: List[str] = Field(default_factory=list)
    user_present: bool = False


class AnalyzeRecordRequest(BaseModel):
    actor_did: str
    actor_key_hex: str | None = None
    grant_id: str | None = None
    invocation_token: str | None = None
    max_chars: int = 200


class DecryptRecordRequest(BaseModel):
    actor_did: str
    actor_key_hex: str | None = None
    grant_id: str | None = None
    invocation_token: str | None = None


class RedactedAnalyzeRecordRequest(BaseModel):
    actor_did: str
    actor_key_hex: str | None = None
    grant_id: str | None = None
    invocation_token: str | None = None
    max_chars: int = 500


class VectorProfileRequest(BaseModel):
    actor_did: str
    actor_key_hex: str | None = None
    grant_id: str | None = None
    invocation_token: str | None = None
    chunk_size_words: int = 80


class RedactedTextExtractionRequest(BaseModel):
    actor_did: str
    actor_key_hex: str | None = None
    grant_id: str | None = None
    invocation_token: str | None = None
    max_chars: int = 20_000
    max_bytes: int = 200_000
    use_ocr: bool = True


class RedactedFormAnalysisRequest(BaseModel):
    actor_did: str
    actor_key_hex: str | None = None
    grant_id: str | None = None
    invocation_token: str | None = None
    max_fields: int = 100
    use_ocr: bool = False


class RedactedGraphRAGRequest(BaseModel):
    actor_did: str
    actor_key_hex: str | None = None
    grant_id: str | None = None
    invocation_token: str | None = None
    record_ids: List[str] = Field(default_factory=list)
    max_chars_per_record: int = 20_000
    max_bytes_per_record: int = 200_000
    use_ocr: bool = True


class ExportGrantRequest(BaseModel):
    issuer_did: str
    audience_did: str
    record_ids: List[str] = Field(default_factory=list)
    issuer_key_hex: str | None = None
    audience_key_hex: str | None = None
    purpose: str = "user_export"
    expires_at: str | None = None
    approval_id: str | None = None
    output_types: List[str] = Field(default_factory=list)


class ExportInvocationRequest(BaseModel):
    grant_id: str
    actor_did: str
    actor_key_hex: str | None = None
    record_ids: List[str] = Field(default_factory=list)
    expires_at: str | None = None
    purpose: str | None = None
    output_types: List[str] = Field(default_factory=list)
    user_present: bool = False


class ExportBundleRequest(BaseModel):
    actor_did: str
    actor_key_hex: str | None = None
    grant_id: str | None = None
    invocation_token: str | None = None
    record_ids: List[str] = Field(default_factory=list)
    include_proofs: bool = True
    include_derived_artifacts: bool = True


class ExportBundleVerifyRequest(BaseModel):
    bundle: Dict[str, Any]


class ExportBundleImportRequest(BaseModel):
    bundle: Dict[str, Any]


class ExportBundleStorageRequest(BaseModel):
    bundle: Dict[str, Any]


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


def _serialize_approvals(values: List[ApprovalRequest]) -> List[Dict[str, Any]]:
    return [item.to_dict() for item in values]


def _optional_hex_key(value: str | None) -> bytes | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return bytes.fromhex(raw)


def _list_wallet_snapshot_ids(wallet_dir: Path) -> List[str]:
    if not wallet_dir.exists():
        return []
    return sorted(path.stem for path in wallet_dir.glob("*.json") if path.is_file())


def _verify_wallet_snapshot_file(wallet_id: str, wallet_dir: Path) -> Dict[str, Any]:
    path = wallet_path(wallet_dir, wallet_id)
    report: Dict[str, Any] = {
        "wallet_id": wallet_id,
        "path": str(path),
        "exists": path.exists(),
        "valid": False,
    }
    if not path.exists():
        report["error"] = "Wallet snapshot not found"
        return report
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report["error"] = f"Invalid JSON: {exc.msg}"
        return report
    if not isinstance(payload, dict):
        report["format"] = "unknown"
        report["error"] = "Snapshot payload is not an object"
        return report
    report.update(
        {
            "format": "legacy",
            "computed_hash": sha256_hex(canonical_bytes(payload)),
            "valid": True,
        }
    )
    return report


def _analysis_result_to_dict(result: Dict[str, Any]) -> Dict[str, Any]:
    artifact = result["artifact"]
    artifact_data = artifact.to_dict() if hasattr(artifact, "to_dict") else dict(artifact)
    return {
        "artifact": artifact_data,
        "output": result["output"],
    }


def _invocation_caveats(
    service: WalletService,
    grant_id: str,
    *,
    fallback_purpose: str,
    default_output_types: List[str] | None = None,
    purpose: str | None = None,
    output_types: List[str] | None = None,
    user_present: bool = False,
) -> Dict[str, Any]:
    grant = service.grants.get(grant_id)
    caveats: Dict[str, Any] = {}
    grant_purpose = grant.caveats.get("purpose") if grant is not None else None
    caveats["purpose"] = purpose or (str(grant_purpose) if grant_purpose else fallback_purpose)
    resolved_output_types = list(output_types) if output_types else list(default_output_types or [])
    if resolved_output_types:
        caveats["output_types"] = resolved_output_types
    if user_present:
        caveats["user_present"] = True
    return caveats


def _normalize_record_grant_caveats(request: RecordGrantRequest) -> tuple[List[str], Dict[str, Any]]:
    allowed_abilities = {"record/analyze", "record/decrypt", "record/share"}
    normalized_abilities: List[str] = []
    for ability in request.abilities:
        if ability not in allowed_abilities:
            raise ValueError(f"record grants do not support ability: {ability}")
        if ability not in normalized_abilities:
            normalized_abilities.append(ability)
    if not normalized_abilities:
        raise ValueError("record grants require at least one ability")
    if normalized_abilities == ["record/share"]:
        raise ValueError("record/share must be paired with analyze or decrypt access")

    caveats: Dict[str, Any] = dict(request.caveats)
    caveats["purpose"] = request.purpose or caveats.get("purpose") or "service_matching"
    if request.output_types:
        caveats["output_types"] = list(request.output_types)
    elif "output_types" not in caveats and "allowed_output_types" not in caveats:
        default_output_types: List[str] = []
        if "record/analyze" in normalized_abilities:
            default_output_types.append("summary")
        if "record/decrypt" in normalized_abilities:
            default_output_types.append("plaintext")
        if default_output_types:
            caveats["output_types"] = default_output_types
    if request.user_presence_required:
        caveats["user_presence_required"] = True
    if request.max_delegation_depth is not None:
        caveats["max_delegation_depth"] = max(0, int(request.max_delegation_depth))
    return normalized_abilities, caveats


def _normalize_export_grant_caveats(request: ExportGrantRequest) -> Dict[str, Any]:
    if not request.record_ids:
        raise ValueError("export grants require at least one record_id")
    caveats: Dict[str, Any] = {
        "purpose": request.purpose or "user_export",
        "record_ids": list(request.record_ids),
        "output_types": list(request.output_types) if request.output_types else ["encrypted_export_bundle"],
    }
    return caveats


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


@router.get("/wallets/snapshots")
def list_wallet_snapshots() -> Dict[str, Any]:
    return {"wallet_ids": _list_wallet_snapshot_ids(default_wallet_dir())}


@router.get("/wallets/{wallet_id}")
def get_wallet(wallet_id: str) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    return service.get_wallet(wallet_id).to_dict()


@router.get("/wallets/{wallet_id}/records", response_model=WalletRecordsResponse)
def list_wallet_records(wallet_id: str, data_type: Optional[str] = Query(default=None)) -> WalletRecordsResponse:
    service = _load_wallet_service(wallet_id)
    return WalletRecordsResponse(records=_sorted_records(service, wallet_id, data_type))


@router.post("/wallets/{wallet_id}/records/{record_id}/rotate-key")
def rotate_wallet_record_key(
    wallet_id: str,
    record_id: str,
    request: RotateRecordKeyRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        version = service.rotate_record_key(
            wallet_id,
            record_id,
            actor_did=request.actor_did,
            actor_secret=_optional_hex_key(request.actor_key_hex),
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return version.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/wallets/{wallet_id}/records/{record_id}/storage")
def verify_wallet_record_storage(wallet_id: str, record_id: str) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    try:
        return service.verify_record_storage(wallet_id, record_id).to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/wallets/{wallet_id}/storage")
def verify_wallet_storage(wallet_id: str) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    try:
        return service.verify_wallet_storage(wallet_id).to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/storage/repair")
def repair_wallet_storage(
    wallet_id: str,
    request: RepairStorageRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        report = service.repair_wallet_storage(wallet_id, actor_did=request.actor_did)
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return report.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/records/{record_id}/storage/repair")
def repair_wallet_record_storage(
    wallet_id: str,
    record_id: str,
    request: RepairStorageRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        report = service.repair_record_storage(wallet_id, record_id, actor_did=request.actor_did)
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return report.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/documents/text")
def add_text_document(wallet_id: str, request: AddTextDocumentRequest) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    metadata = {"title": request.title} if request.title else {}
    try:
        record = service.add_record(
            wallet_id,
            data_type="document",
            plaintext=request.text.encode("utf-8"),
            actor_did=request.actor_did,
            actor_secret=_optional_hex_key(request.key_hex),
            private_metadata={"filename": request.filename, **metadata},
            sensitivity="restricted",
            public_descriptor="document",
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return record.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/documents")
async def add_binary_document(
    wallet_id: str,
    actor_did: str = Form(...),
    key_hex: str | None = Form(default=None),
    title: str | None = Form(default=None),
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    metadata: Dict[str, Any] = {
        "filename": file.filename or "document.bin",
        "content_type": file.content_type or "application/octet-stream",
    }
    if title:
        metadata["title"] = title
    try:
        record = service.add_record(
            wallet_id,
            data_type="document",
            plaintext=await file.read(),
            actor_did=actor_did,
            actor_secret=_optional_hex_key(key_hex),
            private_metadata=metadata,
            sensitivity="restricted",
            public_descriptor="document",
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return record.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/snapshot")
def save_wallet_snapshot(wallet_id: str) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return {"wallet_id": wallet_id, "path": str(wallet_path(wallet_dir, wallet_id))}
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/wallets/{wallet_id}/snapshot")
def verify_wallet_snapshot(wallet_id: str) -> Dict[str, Any]:
    return _verify_wallet_snapshot_file(wallet_id, default_wallet_dir())


@router.post("/wallets/{wallet_id}/snapshot/load")
def load_wallet_snapshot(wallet_id: str) -> Dict[str, Any]:
    try:
        _load_wallet_service(wallet_id)
        return {"wallet_id": wallet_id, "loaded": True}
    except HTTPException as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc


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
    requests = service.access_request_review_items(
        wallet_id,
        status=None if status in (None, "all") else status,
        requester_did=requester_did,
        audience_did=audience_did,
    )
    return WalletAccessRequestsResponse(requests=requests)


@router.post("/wallets/{wallet_id}/access-requests")
def create_wallet_access_request(wallet_id: str, request: AccessRequestCreateRequest) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        access_request = service.request_access(
            wallet_id,
            requester_did=request.requester_did,
            audience_did=request.audience_did,
            resources=[resource_for_record(wallet_id, request.record_id)],
            abilities=[request.ability],
            purpose=request.purpose,
            expires_at=request.expires_at,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return access_request.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/access-requests/{request_id}/approve")
def approve_wallet_access_request(
    wallet_id: str,
    request_id: str,
    request: AccessRequestDecisionRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        access_request = service.approve_access_request(
            wallet_id,
            request_id=request_id,
            actor_did=request.actor_did,
            issuer_secret=_optional_hex_key(request.issuer_key_hex),
            audience_secret=_optional_hex_key(request.audience_key_hex),
            approval_id=request.approval_id,
            issue_invocation=request.issue_invocation,
            invocation_expires_at=request.invocation_expires_at,
        )
        response = access_request.to_dict()
        if access_request.invocation_id:
            response["invocation_token"] = invocation_to_token(service.invocations[access_request.invocation_id])
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return response
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/access-requests/{request_id}/reject")
def reject_wallet_access_request(
    wallet_id: str,
    request_id: str,
    request: AccessRequestDecisionRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        access_request = service.reject_access_request(
            wallet_id,
            request_id=request_id,
            actor_did=request.actor_did,
            reason=request.reason,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return access_request.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/access-requests/{request_id}/revoke")
def revoke_wallet_access_request(
    wallet_id: str,
    request_id: str,
    request: AccessRequestDecisionRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        access_request = service.revoke_access_request(
            wallet_id,
            request_id=request_id,
            actor_did=request.actor_did,
            reason=request.reason,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return access_request.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.post("/wallets/{wallet_id}/records/{record_id}/grants")
def create_wallet_record_grant(
    wallet_id: str,
    record_id: str,
    request: RecordGrantRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        abilities, caveats = _normalize_record_grant_caveats(request)
        grant = service.create_grant(
            wallet_id=wallet_id,
            issuer_did=request.issuer_did,
            audience_did=request.audience_did,
            resources=[resource_for_record(wallet_id, record_id)],
            abilities=abilities,
            caveats=caveats,
            expires_at=request.expires_at,
            approval_id=request.approval_id,
            issuer_secret=_optional_hex_key(request.issuer_key_hex),
            audience_secret=_optional_hex_key(request.audience_key_hex),
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return grant.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/grants/{parent_grant_id}/delegate")
def delegate_wallet_grant(
    wallet_id: str,
    parent_grant_id: str,
    request: DelegateGrantRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        grant = service.create_grant(
            wallet_id=wallet_id,
            issuer_did=request.issuer_did,
            audience_did=request.audience_did,
            resources=request.resources,
            abilities=request.abilities,
            caveats=dict(request.caveats),
            expires_at=request.expires_at,
            issuer_secret=_optional_hex_key(request.issuer_key_hex),
            audience_secret=_optional_hex_key(request.audience_key_hex),
            parent_grant_id=parent_grant_id,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return grant.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/exports/grants")
def create_wallet_export_grant(wallet_id: str, request: ExportGrantRequest) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        grant = service.create_grant(
            wallet_id=wallet_id,
            issuer_did=request.issuer_did,
            audience_did=request.audience_did,
            resources=[resource_for_export(wallet_id)],
            abilities=["export/create"],
            caveats=_normalize_export_grant_caveats(request),
            issuer_secret=_optional_hex_key(request.issuer_key_hex),
            audience_secret=_optional_hex_key(request.audience_key_hex),
            expires_at=request.expires_at,
            approval_id=request.approval_id,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return grant.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/exports/invocations")
def issue_wallet_export_invocation(wallet_id: str, request: ExportInvocationRequest) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        caveats = _invocation_caveats(
            service,
            request.grant_id,
            fallback_purpose="user_export",
            default_output_types=["encrypted_export_bundle"],
            purpose=request.purpose,
            output_types=request.output_types,
            user_present=request.user_present,
        )
        if request.record_ids:
            caveats["record_ids"] = list(request.record_ids)
        invocation = service.issue_invocation(
            wallet_id,
            grant_id=request.grant_id,
            actor_did=request.actor_did,
            resource=resource_for_export(wallet_id),
            ability="export/create",
            actor_secret=_optional_hex_key(request.actor_key_hex),
            caveats=caveats,
            expires_at=request.expires_at,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return {
            **invocation.to_dict(),
            "actor_did": request.actor_did,
            "created_at": invocation.issued_at,
            "invocation_token": invocation_to_token(invocation),
        }
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/exports")
def create_wallet_export_bundle(wallet_id: str, request: ExportBundleRequest) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        if request.invocation_token:
            bundle = service.create_export_bundle_with_invocation(
                wallet_id,
                actor_did=request.actor_did,
                invocation=invocation_from_token(request.invocation_token),
                actor_secret=_optional_hex_key(request.actor_key_hex),
                record_ids=request.record_ids or None,
                include_proofs=request.include_proofs,
                include_derived_artifacts=request.include_derived_artifacts,
            )
        else:
            bundle = service.create_export_bundle(
                wallet_id,
                actor_did=request.actor_did,
                grant_id=request.grant_id,
                record_ids=request.record_ids or None,
                include_proofs=request.include_proofs,
                include_derived_artifacts=request.include_derived_artifacts,
            )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return bundle
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/exports/verify")
def verify_wallet_export_bundle(request: ExportBundleVerifyRequest) -> Dict[str, Any]:
    service = _new_service(default_blob_dir())
    computed_hash = service.export_bundle_hash(request.bundle)
    try:
        service.validate_export_bundle_schema(request.bundle)
        schema_valid = True
        schema_error = None
    except (KeyError, TypeError, ValueError) as exc:
        schema_valid = False
        schema_error = str(exc)
    hash_valid = service.verify_export_bundle(request.bundle)
    return {
        "valid": bool(hash_valid and schema_valid),
        "hash_valid": bool(hash_valid),
        "schema_valid": schema_valid,
        "schema_error": schema_error,
        "bundle_id": request.bundle.get("bundle_id"),
        "bundle_hash": request.bundle.get("bundle_hash"),
        "computed_hash": computed_hash,
    }


@router.post("/exports/import")
def import_wallet_export_bundle(request: ExportBundleImportRequest) -> Dict[str, Any]:
    service = _new_service(default_blob_dir())
    wallet_dir = default_wallet_dir()
    try:
        result = service.import_export_bundle(request.bundle)
        _save_wallet_snapshot(service, wallet_dir, result["wallet_id"])
        return result
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/exports/storage")
def verify_wallet_export_bundle_storage(request: ExportBundleStorageRequest) -> Dict[str, Any]:
    wallet_id = str((request.bundle.get("wallet") or {}).get("wallet_id") or "")
    if wallet_id:
        try:
            service = _load_wallet_service(wallet_id)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            service = _new_service(default_blob_dir())
    else:
        service = _new_service(default_blob_dir())
    try:
        return service.verify_export_bundle_storage(request.bundle)
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/records/{record_id}/analysis-invocations")
def issue_record_analysis_invocation(
    wallet_id: str,
    record_id: str,
    request: AnalysisInvocationRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        invocation = service.issue_invocation(
            wallet_id,
            grant_id=request.grant_id,
            actor_did=request.actor_did,
            resource=resource_for_record(wallet_id, record_id),
            ability="record/analyze",
            actor_secret=_optional_hex_key(request.actor_key_hex),
            caveats=_invocation_caveats(
                service,
                request.grant_id,
                fallback_purpose="service_matching",
                default_output_types=["summary"],
                purpose=request.purpose,
                output_types=request.output_types,
                user_present=request.user_present,
            ),
            expires_at=request.expires_at,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return {"invocation": invocation.to_dict(), "token": invocation_to_token(invocation)}
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/records/{record_id}/decrypt-invocations")
def issue_record_decrypt_invocation(
    wallet_id: str,
    record_id: str,
    request: AnalysisInvocationRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        invocation = service.issue_invocation(
            wallet_id,
            grant_id=request.grant_id,
            actor_did=request.actor_did,
            resource=resource_for_record(wallet_id, record_id),
            ability="record/decrypt",
            actor_secret=_optional_hex_key(request.actor_key_hex),
            caveats=_invocation_caveats(
                service,
                request.grant_id,
                fallback_purpose="document_view",
                default_output_types=["plaintext"],
                purpose=request.purpose,
                output_types=request.output_types,
                user_present=request.user_present,
            ),
            expires_at=request.expires_at,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return {"invocation": invocation.to_dict(), "token": invocation_to_token(invocation)}
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/records/{record_id}/decrypt")
def decrypt_wallet_record(
    wallet_id: str,
    record_id: str,
    request: DecryptRecordRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    actor_secret = _optional_hex_key(request.actor_key_hex)
    try:
        if request.invocation_token:
            plaintext = service.decrypt_record_with_invocation(
                wallet_id,
                record_id,
                actor_did=request.actor_did,
                invocation=invocation_from_token(request.invocation_token),
                actor_secret=actor_secret,
            )
        else:
            plaintext = service.decrypt_record(
                wallet_id,
                record_id,
                actor_did=request.actor_did,
                grant_id=request.grant_id,
                actor_secret=actor_secret,
            )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return {
            "record_id": record_id,
            "size_bytes": len(plaintext),
            "text": plaintext.decode("utf-8", errors="replace"),
            "base64": base64.b64encode(plaintext).decode("ascii"),
        }
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/records/{record_id}/analyze")
def analyze_wallet_record(
    wallet_id: str,
    record_id: str,
    request: AnalyzeRecordRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    actor_secret = _optional_hex_key(request.actor_key_hex)
    try:
        if request.invocation_token:
            artifact = service.analyze_record_summary_with_invocation(
                wallet_id,
                record_id,
                actor_did=request.actor_did,
                invocation=invocation_from_token(request.invocation_token),
                actor_secret=actor_secret,
                max_chars=request.max_chars,
            )
        else:
            artifact = service.analyze_record_summary(
                wallet_id,
                record_id,
                actor_did=request.actor_did,
                grant_id=request.grant_id or "",
                actor_secret=actor_secret,
                max_chars=request.max_chars,
            )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return artifact.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/records/{record_id}/analyze/redacted")
def analyze_wallet_record_redacted(
    wallet_id: str,
    record_id: str,
    request: RedactedAnalyzeRecordRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    actor_secret = _optional_hex_key(request.actor_key_hex)
    try:
        if request.invocation_token:
            invocation = invocation_from_token(request.invocation_token)
            service.verify_invocation(
                wallet_id,
                invocation,
                actor_did=request.actor_did,
                resource=resource_for_record(wallet_id, record_id),
                ability="record/analyze",
                actor_secret=actor_secret,
            )
            result = service.analyze_document_with_redaction(
                wallet_id,
                record_id,
                actor_did=request.actor_did,
                grant_id=invocation.grant_id,
                actor_secret=actor_secret,
                max_chars=request.max_chars,
                invocation_caveats=invocation.caveats,
            )
        else:
            result = service.analyze_document_with_redaction(
                wallet_id,
                record_id,
                actor_did=request.actor_did,
                grant_id=request.grant_id,
                actor_secret=actor_secret,
                max_chars=request.max_chars,
            )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return _analysis_result_to_dict(result)
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/records/{record_id}/vector-profile")
def create_wallet_record_vector_profile(
    wallet_id: str,
    record_id: str,
    request: VectorProfileRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    actor_secret = _optional_hex_key(request.actor_key_hex)
    try:
        if request.invocation_token:
            invocation = invocation_from_token(request.invocation_token)
            service.verify_invocation(
                wallet_id,
                invocation,
                actor_did=request.actor_did,
                resource=resource_for_record(wallet_id, record_id),
                ability="record/analyze",
                actor_secret=actor_secret,
            )
            result = service.create_document_vector_profile(
                wallet_id,
                record_id,
                actor_did=request.actor_did,
                grant_id=invocation.grant_id,
                actor_secret=actor_secret,
                chunk_size_words=request.chunk_size_words,
                invocation_caveats=invocation.caveats,
            )
        else:
            result = service.create_document_vector_profile(
                wallet_id,
                record_id,
                actor_did=request.actor_did,
                grant_id=request.grant_id,
                actor_secret=actor_secret,
                chunk_size_words=request.chunk_size_words,
            )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return _analysis_result_to_dict(result)
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/records/{record_id}/extract-text/redacted")
def extract_wallet_record_text_redacted(
    wallet_id: str,
    record_id: str,
    request: RedactedTextExtractionRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    actor_secret = _optional_hex_key(request.actor_key_hex)
    try:
        if request.invocation_token:
            invocation = invocation_from_token(request.invocation_token)
            service.verify_invocation(
                wallet_id,
                invocation,
                actor_did=request.actor_did,
                resource=resource_for_record(wallet_id, record_id),
                ability="record/analyze",
                actor_secret=actor_secret,
            )
            result = service.extract_document_text_with_redaction(
                wallet_id,
                record_id,
                actor_did=request.actor_did,
                grant_id=invocation.grant_id,
                actor_secret=actor_secret,
                max_chars=request.max_chars,
                max_bytes=request.max_bytes,
                use_ocr=request.use_ocr,
                invocation_caveats=invocation.caveats,
            )
        else:
            result = service.extract_document_text_with_redaction(
                wallet_id,
                record_id,
                actor_did=request.actor_did,
                grant_id=request.grant_id,
                actor_secret=actor_secret,
                max_chars=request.max_chars,
                max_bytes=request.max_bytes,
                use_ocr=request.use_ocr,
            )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return _analysis_result_to_dict(result)
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/records/{record_id}/forms/analyze/redacted")
def analyze_wallet_record_form_redacted(
    wallet_id: str,
    record_id: str,
    request: RedactedFormAnalysisRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    actor_secret = _optional_hex_key(request.actor_key_hex)
    try:
        if request.invocation_token:
            invocation = invocation_from_token(request.invocation_token)
            service.verify_invocation(
                wallet_id,
                invocation,
                actor_did=request.actor_did,
                resource=resource_for_record(wallet_id, record_id),
                ability="record/analyze",
                actor_secret=actor_secret,
            )
            result = service.analyze_document_form_with_redaction(
                wallet_id,
                record_id,
                actor_did=request.actor_did,
                grant_id=invocation.grant_id,
                actor_secret=actor_secret,
                max_fields=request.max_fields,
                use_ocr=request.use_ocr,
                invocation_caveats=invocation.caveats,
            )
        else:
            result = service.analyze_document_form_with_redaction(
                wallet_id,
                record_id,
                actor_did=request.actor_did,
                grant_id=request.grant_id,
                actor_secret=actor_secret,
                max_fields=request.max_fields,
                use_ocr=request.use_ocr,
            )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return _analysis_result_to_dict(result)
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/records/graphrag/redacted")
def create_wallet_redacted_graphrag(
    wallet_id: str,
    request: RedactedGraphRAGRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    actor_secret = _optional_hex_key(request.actor_key_hex)
    try:
        if not request.record_ids:
            raise ValueError("redacted GraphRAG creation requires at least one record_id")
        if request.invocation_token:
            invocation = invocation_from_token(request.invocation_token)
            for record_id in request.record_ids:
                service.verify_invocation(
                    wallet_id,
                    invocation,
                    actor_did=request.actor_did,
                    resource=resource_for_record(wallet_id, record_id),
                    ability="record/analyze",
                    actor_secret=actor_secret,
                )
            result = service.create_redacted_graphrag(
                wallet_id,
                request.record_ids,
                actor_did=request.actor_did,
                grant_id=invocation.grant_id,
                actor_secret=actor_secret,
                max_chars_per_record=request.max_chars_per_record,
                max_bytes_per_record=request.max_bytes_per_record,
                use_ocr=request.use_ocr,
                invocation_caveats=invocation.caveats,
            )
        else:
            result = service.create_redacted_graphrag(
                wallet_id,
                request.record_ids,
                actor_did=request.actor_did,
                grant_id=request.grant_id,
                actor_secret=actor_secret,
                max_chars_per_record=request.max_chars_per_record,
                max_bytes_per_record=request.max_bytes_per_record,
                use_ocr=request.use_ocr,
            )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return _analysis_result_to_dict(result)
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/approvals")
def request_wallet_threshold_approval(
    wallet_id: str,
    request: ThresholdApprovalCreateRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        approval = service.request_approval(
            wallet_id,
            requested_by=request.requested_by,
            operation=request.operation,
            resources=request.resources,
            abilities=request.abilities,
            expires_at=request.expires_at,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return approval.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/wallets/{wallet_id}/approvals", response_model=WalletApprovalsResponse)
def list_wallet_threshold_approvals(
    wallet_id: str,
    status: str = Query(default="all"),
) -> WalletApprovalsResponse:
    service = _load_wallet_service(wallet_id)
    approvals = [
        approval
        for approval in service.approval_requests.values()
        if approval.wallet_id == wallet_id
    ]
    if status != "all":
        approvals = [approval for approval in approvals if approval.status == status]
    approvals = sorted(approvals, key=lambda item: item.created_at)
    return WalletApprovalsResponse(approvals=_serialize_approvals(approvals))


@router.post("/wallets/{wallet_id}/approvals/{approval_id}/approve")
def approve_wallet_threshold_approval(
    wallet_id: str,
    approval_id: str,
    request: ThresholdApprovalDecisionRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        approval = service.approve_approval(
            wallet_id,
            approval_id=approval_id,
            approver_did=request.approver_did,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return approval.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
