"""FastAPI adapter for the canonical Python wallet service.

This module exposes a thin HTTP surface over ``ipfs_datasets_py.wallet`` so
browser clients can treat Python as the wallet implementation boundary.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import smtplib
import time
from typing import Any, Dict, List, Mapping, Optional
from email.message import EmailMessage
from email.utils import make_msgid
from urllib import request as urllib_request

from fastapi import APIRouter, File, Form, HTTPException, Header, Query, UploadFile
from pydantic import BaseModel, Field

from . import DataWalletError, WalletService
from .crypto import sha256_hex
from .manifest import canonical_bytes
from .models import AnalyticsTemplate, AccessRequest, ApprovalRequest, AuditEvent, GrantReceipt, ProofReceipt
from .storage import LocalEncryptedBlobStore
from .ucan import invocation_from_token, invocation_to_token, resource_for_export, resource_for_record

PORTLAND_POLICE_MISSING_EMAIL = "missing@police.portlandoregon.gov"


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


class SavedServicesResponse(BaseModel):
    saved_services: List[Dict[str, Any]]


class ServiceInteractionsResponse(BaseModel):
    interactions: List[Dict[str, Any]]


class ServicePlansResponse(BaseModel):
    plans: List[Dict[str, Any]]


class WalletApprovalsResponse(BaseModel):
    approvals: List[Dict[str, Any]]


class WalletRecoveryBundleRequest(BaseModel):
    actor_did: str
    encrypted_bundle: Dict[str, Any]
    wrapping_method: str = "passphrase"
    kdf: Dict[str, Any] = Field(default_factory=dict)
    recovery_hint: str = ""
    public_metadata: Dict[str, Any] = Field(default_factory=dict)


class AddTextDocumentRequest(BaseModel):
    actor_did: str
    text: str
    filename: str = "document.txt"
    title: str | None = None
    key_hex: str | None = None


class WalletRecordMetadataRequest(BaseModel):
    actor_did: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DeleteWalletRecordRequest(BaseModel):
    actor_did: str
    unpin_ipfs: bool = True


class LocationRegionProofRequest(BaseModel):
    actor_did: str
    region_id: str
    grant_id: str | None = None


class LocationDistanceProofRequest(BaseModel):
    actor_did: str
    target_id: str
    target_lat: float
    target_lon: float
    max_distance_km: float
    grant_id: str | None = None


class DocumentPrivacyProfileProofRequest(BaseModel):
    actor_did: str
    public_inputs: Dict[str, Any] = Field(default_factory=dict)


class WalletRecordMetadataGenerationRequest(BaseModel):
    actor_did: str
    actor_key_hex: str | None = None
    wallet_cid: str | None = None
    provider: str | None = "hf_inference_api"
    model_name: str | None = None
    kwargs: Dict[str, Any] = Field(default_factory=dict)
    grant_id: str | None = None
    invocation_token: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    max_chars_per_record: int = 20_000
    max_bytes_per_record: int = 200_000
    use_ocr: bool = True


class AnalyticsConsentFromTemplateRequest(BaseModel):
    actor_did: str
    template_id: str
    expires_at: str | None = None


class AnalyticsConsentRevokeRequest(BaseModel):
    actor_did: str


class MissingPersonDeadDropEmailRequest(BaseModel):
    actor_did: str
    to_email: str = PORTLAND_POLICE_MISSING_EMAIL
    subject: str = "Missing person report dead drop bundle"
    body: str
    bundle: Dict[str, Any]
    bundle_filename: str = "abby-missing-person-wallet-dead-drop.json"


class MissingPersonDeadDropConfigRequest(BaseModel):
    actor_did: str
    enabled: bool = False
    to_email: str = PORTLAND_POLICE_MISSING_EMAIL
    subject: str = "Missing person report dead drop bundle"
    body: str = ""
    bundle: Dict[str, Any] = Field(default_factory=dict)
    bundle_filename: str = "abby-missing-person-wallet-dead-drop.json"
    due_at: str = ""
    last_check_in_at: str = ""


class MissingPersonDeadDropDispatchRequest(BaseModel):
    actor_did: str


class SavedServiceRequest(BaseModel):
    actor_did: str
    service_doc_id: str
    source_content_cid: str
    source_page_cid: str = ""
    title: str = ""
    provider_name: str = ""
    program_name: str = ""
    source_url: str = ""
    label: str = ""
    reason: str = ""
    priority: str = "normal"
    status: str = "saved"
    private_notes_record_id: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ServiceInteractionRequest(BaseModel):
    actor_did: str
    service_doc_id: str
    source_content_cid: str = ""
    source_page_cid: str = ""
    provider_name: str = ""
    program_name: str = ""
    interaction_type: str
    channel: str = ""
    counterparty_name: str = ""
    counterparty_contact: str = ""
    timestamp: str = ""
    status: str = ""
    outcome: str = ""
    notes_record_id: str = ""
    next_action: str = ""
    next_follow_up_at: str = ""
    source_action_url: str = ""
    related_grant_ids: List[str] = Field(default_factory=list)
    related_record_ids: List[str] = Field(default_factory=list)
    privacy_level: str = "private"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ServicePlanRequest(BaseModel):
    actor_did: str
    service_doc_id: str
    source_content_cid: str = ""
    source_page_cid: str = ""
    service_title: str = ""
    provider_name: str = ""
    goal: str = ""
    steps: List[str] = Field(default_factory=list)
    documents_needed: List[str] = Field(default_factory=list)
    questions_to_ask: List[str] = Field(default_factory=list)
    appointment_at: str = ""
    reminder_at: str = ""
    travel_target: str = ""
    assigned_worker_recipient_id: str = ""
    status: str = "active"
    related_interaction_ids: List[str] = Field(default_factory=list)
    private_notes_record_id: str = ""


class ServicePlanUpdateRequest(BaseModel):
    actor_did: str
    source_content_cid: str | None = None
    source_page_cid: str | None = None
    service_title: str | None = None
    provider_name: str | None = None
    goal: str | None = None
    steps: List[str] | None = None
    documents_needed: List[str] | None = None
    questions_to_ask: List[str] | None = None
    appointment_at: str | None = None
    reminder_at: str | None = None
    travel_target: str | None = None
    assigned_worker_recipient_id: str | None = None
    status: str | None = None
    related_interaction_ids: List[str] | None = None
    private_notes_record_id: str | None = None


class ServicePlanShareGrantRequest(BaseModel):
    actor_did: str = ""
    issuer_did: str = ""
    audience_did: str = ""
    worker_did: str = ""
    scopes: List[str] = Field(default_factory=lambda: ["service_summary"])
    purpose: str = "service_plan_collaboration"
    worker_recipient_id: str = ""
    worker_name: str = ""
    expires_at: str | None = None
    approval_id: str | None = None
    issuer_key_hex: str | None = None
    audience_key_hex: str | None = None
    caveats: Dict[str, Any] = Field(default_factory=dict)


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


class RevokeGrantRequest(BaseModel):
    actor_did: str


class EmergencyRevokeRequest(BaseModel):
    actor_did: str
    actor_key_hex: str | None = None
    approval_id: str | None = None
    rotate_keys: bool = True
    reason: str | None = None


class WalletControllerRequest(BaseModel):
    actor_did: str
    controller_did: str
    controller_key_hex: str | None = None
    approval_id: str | None = None


class WalletDeviceRequest(BaseModel):
    actor_did: str
    device_did: str
    device_key_hex: str | None = None
    approval_id: str | None = None


class WalletRecoveryPolicyRequest(BaseModel):
    actor_did: str
    contact_dids: List[str] = Field(default_factory=list)
    threshold: int = 1
    approval_id: str | None = None


class WalletControllerRecoveryRequest(BaseModel):
    actor_did: str
    controller_did: str
    controller_key_hex: str | None = None
    approval_id: str | None = None


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

_MAGIC_UCAN_CONTEXT = "abby-magic-ucan-v1"


def default_wallet_dir() -> Path:
    return Path.home() / ".ipfs_datasets" / "wallet" / "manifests"


def default_blob_dir() -> Path:
    return Path.home() / ".ipfs_datasets" / "wallet" / "blobs"


def wallet_path(wallet_dir: Path, wallet_id: str) -> Path:
    return wallet_dir / f"{wallet_id}.json"


def _magic_login_secret() -> str:
    return str(os.getenv("WALLET_MAGIC_LOGIN_SECRET") or "").strip()


def _base64url_encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode_to_bytes(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _hmac_base64url(secret: str, value: str) -> str:
    return _base64url_encode_bytes(hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).digest())


def _extract_bearer_token(authorization: str | None) -> str:
    raw = str(authorization or "").strip()
    if not raw:
        return ""
    scheme, _, token = raw.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


def _verify_magic_ucan(token: str) -> Dict[str, Any]:
    secret = _magic_login_secret()
    if not secret:
        raise RuntimeError("WALLET_MAGIC_LOGIN_SECRET is required for passwordless login")
    parts = str(token or "").strip().split(".")
    if len(parts) != 3 or parts[0] != _MAGIC_UCAN_CONTEXT:
        raise ValueError("UCAN token is malformed")
    _, payload_encoded, signature = parts
    expected = _hmac_base64url(secret, f"{_MAGIC_UCAN_CONTEXT}.{payload_encoded}")
    if not hmac.compare_digest(signature, expected):
        raise ValueError("UCAN signature is invalid")
    try:
        payload = json.loads(_base64url_decode_to_bytes(payload_encoded).decode("utf-8"))
    except Exception as exc:
        raise ValueError("UCAN payload is malformed") from exc
    if not isinstance(payload, dict) or payload.get("profile") != _MAGIC_UCAN_CONTEXT:
        raise ValueError("UCAN payload is malformed")
    expires_at = int(payload.get("expiresAt") or 0)
    if not expires_at or expires_at <= int(time.time() * 1000):
        raise ValueError("UCAN token is expired")
    return payload


def _capability_resource_matches(pattern: str, resource: str) -> bool:
    if pattern == "*" or pattern == resource:
        return True
    if pattern.endswith("/*") and resource.startswith(pattern[:-1]):
        return True
    return False


def _require_magic_ucan(
    *,
    authorization: str | None,
    wallet_id: str,
    ability: str,
    resource: str,
) -> Dict[str, Any]:
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="recovery UCAN authorization required")
    try:
        payload = _verify_magic_ucan(token)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if str(payload.get("walletId") or "") != str(wallet_id):
        raise HTTPException(status_code=403, detail="UCAN wallet scope does not match")
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, list):
        raise HTTPException(status_code=403, detail="UCAN has no capabilities")
    for capability in capabilities:
        if not isinstance(capability, Mapping):
            continue
        if str(capability.get("can") or "") != ability:
            continue
        if _capability_resource_matches(str(capability.get("with") or ""), resource):
            return payload
    raise HTTPException(status_code=403, detail="UCAN does not allow this recovery action")


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


def _require_portland_police_missing_email(to_email: str) -> str:
    normalized = str(to_email or "").strip().lower()
    if normalized != PORTLAND_POLICE_MISSING_EMAIL:
        raise ValueError(
            f"missing-person dead drop recipient must be {PORTLAND_POLICE_MISSING_EMAIL}"
        )
    return PORTLAND_POLICE_MISSING_EMAIL


def _send_webhook_notification(
    *,
    env_prefix: str,
    required_key: str,
    required_value: str,
    extra_payload: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    webhook_url = str(os.getenv(f"{env_prefix}_WEBHOOK_URL") or "").strip()
    backend = str(os.getenv(f"{env_prefix}_BACKEND") or ("http" if webhook_url else "")).strip().lower()
    if not backend or not webhook_url:
        raise RuntimeError(
            f"{env_prefix}_WEBHOOK_URL environment variable is required for delivery but is not configured"
        )
    if backend != "http":
        raise RuntimeError(f"{env_prefix}_BACKEND must be http when delivery is enabled")

    extra_headers: Dict[str, str] = {}
    if bearer_token := str(os.getenv(f"{env_prefix}_BEARER_TOKEN") or "").strip():
        extra_headers["authorization"] = f"Bearer {bearer_token}"
    if header_name := str(os.getenv(f"{env_prefix}_HTTP_HEADER_NAME") or "").strip():
        header_value = str(os.getenv(f"{env_prefix}_HTTP_HEADER_VALUE") or "").strip()
        if not header_value:
            raise RuntimeError(f"{env_prefix}_HTTP_HEADER_VALUE is required when header name is set")
        extra_headers[header_name] = header_value

    timeout_seconds = float(str(os.getenv(f"{env_prefix}_TIMEOUT_SECONDS") or "15").strip())
    if timeout_seconds <= 0:
        raise RuntimeError(f"{env_prefix}_TIMEOUT_SECONDS must be positive")

    payload = {required_key: required_value, **dict(extra_payload or {})}
    request_headers = {"content-type": "application/json", **extra_headers}
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    req = urllib_request.Request(webhook_url, data=body, headers=request_headers, method="POST")
    with urllib_request.urlopen(req, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
        content_type = str(getattr(response, "headers", {}).get("content-type", ""))
        status = str(getattr(response, "status", getattr(response, "code", 200)))

    response_payload: Dict[str, Any] = {}
    if raw and ("json" in content_type.lower() or raw.lstrip().startswith("{")):
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("dead-drop delivery response must be a JSON object")
        response_payload = parsed

    provider_message_id = str(
        response_payload.get("provider_message_id")
        or response_payload.get("message_id")
        or response_payload.get("email_id")
        or response_payload.get("id")
        or ""
    )
    result = {
        "provider": str(response_payload.get("provider") or "http"),
        "provider_status": str(response_payload.get("status") or status),
    }
    if provider_message_id:
        result["provider_message_id"] = provider_message_id
    return result


def _send_dead_drop_email(
    *,
    to_email: str,
    subject: str,
    body: str,
    bundle: Dict[str, Any],
    bundle_filename: str,
) -> Dict[str, Any]:
    normalized_to_email = str(to_email or "").strip()
    normalized_subject = str(subject or "").strip()
    normalized_body = str(body or "")
    bundle_json = json.dumps(bundle, indent=2, sort_keys=True)
    sender = str(os.getenv("WALLET_DEAD_DROP_FROM_EMAIL") or "no-reply@211-ai.org").strip()

    webhook_url = str(os.getenv("WALLET_DEAD_DROP_WEBHOOK_URL") or "").strip()
    backend = str(os.getenv("WALLET_DEAD_DROP_BACKEND") or ("http" if webhook_url else "")).strip().lower()
    if backend or webhook_url:
        if backend != "http" or not webhook_url:
            raise RuntimeError(
                "WALLET_DEAD_DROP_WEBHOOK_URL environment variable is required for dead-drop delivery when WALLET_DEAD_DROP_BACKEND is enabled"
            )
        delivery = _send_webhook_notification(
            env_prefix="WALLET_DEAD_DROP",
            required_key="to_email",
            required_value=normalized_to_email,
            extra_payload={
                "subject": normalized_subject,
                "body": normalized_body,
                "from_email": sender,
                "attachment_base64": base64.b64encode(bundle_json.encode("utf-8")).decode("ascii"),
                "attachment_filename": str(bundle_filename or "abby-missing-person-wallet-dead-drop.json"),
                "attachment_mime_type": "application/json",
            },
        )
        return {"message_id": str(delivery.get("provider_message_id") or "")}

    smtp_host = str(os.getenv("WALLET_DEAD_DROP_SMTP_HOST") or "").strip()
    if not smtp_host:
        raise RuntimeError(
            "WALLET_DEAD_DROP_SMTP_HOST environment variable is required for dead-drop email delivery but is not configured"
        )
    smtp_port = int(str(os.getenv("WALLET_DEAD_DROP_SMTP_PORT") or "587").strip())
    smtp_use_ssl = str(os.getenv("WALLET_DEAD_DROP_SMTP_USE_SSL") or "").strip().lower() in {"1", "true", "yes", "on"}
    smtp_starttls = str(os.getenv("WALLET_DEAD_DROP_SMTP_STARTTLS") or "true").strip().lower() in {"1", "true", "yes", "on"}
    smtp_username = str(os.getenv("WALLET_DEAD_DROP_SMTP_USERNAME") or "").strip()
    smtp_password = str(os.getenv("WALLET_DEAD_DROP_SMTP_PASSWORD") or "")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = normalized_to_email
    message["Subject"] = normalized_subject
    sender_domain = sender.rsplit("@", 1)[-1].strip() if "@" in sender else ""
    message["Message-Id"] = make_msgid(domain=sender_domain or None)
    message.set_content(normalized_body)
    message.add_attachment(
        bundle_json.encode("utf-8"),
        maintype="application",
        subtype="json",
        filename=bundle_filename,
    )

    smtp_factory = smtplib.SMTP_SSL if smtp_use_ssl else smtplib.SMTP
    with smtp_factory(smtp_host, smtp_port, timeout=20) as smtp:
        if not smtp_use_ssl and smtp_starttls:
            smtp.starttls()
        if smtp_username:
            smtp.login(smtp_username, smtp_password)
        rejected = smtp.send_message(message)
    if rejected:
        raise RuntimeError(f"Dead-drop email delivery rejected recipients: {sorted(rejected)}")
    return {"message_id": str(message.get('Message-Id') or '')}


def _inject_shared_analytics_templates(service: WalletService, wallet_dir: Path) -> None:
    for wallet_snapshot_id in _list_wallet_snapshot_ids(wallet_dir):
        path = wallet_path(wallet_dir, wallet_snapshot_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for template_data in payload.get("analytics_templates", []):
            if not isinstance(template_data, Mapping):
                continue
            template_id = str(template_data.get("template_id") or "").strip()
            if not template_id or template_id in service.analytics_templates:
                continue
            try:
                service.analytics_templates[template_id] = AnalyticsTemplate(**dict(template_data))
            except Exception:
                continue


def _list_shared_analytics_templates(wallet_dir: Path) -> List[Dict[str, Any]]:
    templates: Dict[str, Dict[str, Any]] = {}
    for wallet_snapshot_id in _list_wallet_snapshot_ids(wallet_dir):
        path = wallet_path(wallet_dir, wallet_snapshot_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for template_data in payload.get("analytics_templates", []):
            if not isinstance(template_data, Mapping):
                continue
            template_id = str(template_data.get("template_id") or "").strip()
            if template_id:
                templates[template_id] = dict(template_data)
    return [templates[template_id] for template_id in sorted(templates)]


def _sorted_records(service: WalletService, wallet_id: str, data_type: str | None = None) -> List[Dict[str, Any]]:
    records = []
    for record in sorted(service.records.values(), key=lambda item: item.record_id):
        if record.wallet_id != wallet_id:
            continue
        if data_type and record.data_type != data_type:
            continue
        payload = record.to_dict()
        metadata_key = service._record_metadata_key(wallet_id, record.record_id)
        metadata_record = service.record_metadata.get(metadata_key)
        payload["metadata"] = dict(metadata_record.metadata) if metadata_record else {}
        version = service.versions.get(record.current_version_id)
        if version is not None:
            payload["storage_metadata"] = {
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


def _ops_health_shared_secret() -> str:
    return str(os.getenv("WALLET_OPS_HEALTH_SHARED_SECRET") or "").strip()


def _ops_health_report(*, verify_storage: bool = False) -> Dict[str, Any]:
    wallet_dir = default_wallet_dir()
    blob_dir = default_blob_dir()
    wallet_ids = _list_wallet_snapshot_ids(wallet_dir)
    services: List[WalletService] = []
    for wallet_id in wallet_ids:
        try:
            services.append(_load_wallet_service(wallet_id, wallet_dir=wallet_dir, blob_dir=blob_dir))
        except Exception:
            continue

    checks: List[Dict[str, Any]] = []

    def add_check(name: str, status: str, summary: str, **details: Any) -> None:
        checks.append({"name": name, "status": status, "summary": summary, "details": details})

    add_check(
        "repository",
        "ok",
        "Wallet snapshot repository is available." if wallet_dir.exists() else "Wallet snapshot repository directory does not exist yet.",
        configured=True,
        wallet_snapshot_count=len(wallet_ids),
        live_wallet_count=len(wallet_ids),
        missing_snapshot_wallet_ids=[],
    )

    active_record_count = sum(
        len([record for record in service.records.values() if record.status == "active"])
        for service in services
    )
    storage_failures: List[Dict[str, Any]] = []
    if verify_storage:
        for wallet_id, service in zip(wallet_ids, services):
            for record in service.records.values():
                if record.status != "active":
                    continue
                try:
                    report = service.verify_record_storage(wallet_id, record.record_id)
                except Exception as exc:
                    storage_failures.append(
                        {"wallet_id": wallet_id, "record_id": record.record_id, "error": str(exc)}
                    )
                    continue
                if not report.ok:
                    storage_failures.append(
                        {
                            "wallet_id": wallet_id,
                            "record_id": record.record_id,
                            "payload_failures": [status.to_dict() for status in report.payload if not status.ok],
                            "metadata_failures": [status.to_dict() for status in report.metadata if not status.ok],
                        }
                    )
    storage_backend_name = services[0].storage.__class__.__name__ if services else "LocalEncryptedBlobStore"
    add_check(
        "storage_availability",
        "error" if storage_failures else "ok",
        (
            f"{len(storage_failures)} active records failed encrypted storage verification."
            if storage_failures
            else "Encrypted storage backend is configured and no verified records failed."
        ),
        backend=storage_backend_name,
        active_record_count=active_record_count,
        verified=verify_storage,
        failures=storage_failures,
    )

    proof_backend = services[0].proof_backend if services else _new_service(blob_dir).proof_backend
    simulated_enabled = services[0].allow_simulated_proofs if services else True
    proof_status = "warning" if simulated_enabled else "ok"
    proof_summary = (
        "Simulated proof receipts are enabled; configure a production proof backend before launch."
        if simulated_enabled
        else "Production proof mode rejects simulated proof receipts."
    )
    add_check(
        "proof_registry",
        proof_status,
        proof_summary,
        backend=proof_backend.__class__.__name__,
        verifier_id=getattr(proof_backend, "verifier_id", None),
        proof_system=getattr(proof_backend, "proof_system", None),
        backend_mode=getattr(proof_backend, "mode", None),
        is_simulated_backend=bool(getattr(proof_backend, "is_simulated", False)),
        backend_health=None,
        allow_simulated_proofs=simulated_enabled,
        env_vars=["WALLET_PROOF_MODE", "WALLET_PROOF_BACKEND", "WALLET_ALLOW_SIMULATED_PROOFS"],
    )

    revoked_grant_ids = {
        grant.grant_id
        for service in services
        for grant in service.grants.values()
        if grant.status == "revoked"
    }
    dangling_key_wraps: List[Dict[str, Any]] = []
    for service in services:
        for version in service.versions.values():
            for key_wrap in version.key_wraps:
                if key_wrap.grant_id in revoked_grant_ids and key_wrap.status == "active":
                    dangling_key_wraps.append(
                        {
                            "record_id": key_wrap.record_id,
                            "version_id": key_wrap.version_id,
                            "recipient_did": key_wrap.recipient_did,
                            "grant_id": key_wrap.grant_id,
                        }
                    )
    add_check(
        "revocation_propagation",
        "error" if dangling_key_wraps else "ok",
        (
            f"{len(dangling_key_wraps)} active key wraps still reference revoked grants."
            if dangling_key_wraps
            else "Revoked grants do not have active delegated key wraps."
        ),
        revoked_grant_count=len(revoked_grant_ids),
        dangling_key_wraps=dangling_key_wraps,
    )

    budget_spent: Dict[str, float] = {}
    for service in services:
        for key, value in service.analytics_query_budget_spent.items():
            budget_spent[str(key)] = float(value)
    budget_spent = dict(sorted(budget_spent.items()))
    negative_budgets = {key: value for key, value in budget_spent.items() if value < 0}
    add_check(
        "privacy_budget",
        "error" if negative_budgets else "ok",
        (
            "Privacy budget ledger contains invalid negative spend values."
            if negative_budgets
            else "Privacy budget ledger is readable."
        ),
        budget_key_count=len(budget_spent),
        spent=budget_spent,
        invalid_negative_spend=negative_budgets,
    )

    if any(check["status"] == "error" for check in checks):
        status = "error"
    elif any(check["status"] == "warning" for check in checks):
        status = "warning"
    else:
        status = "ok"

    return {
        "status": status,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "wallet_count": len(wallet_ids),
        "check_count": len(checks),
        "checks": checks,
    }


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


def _derived_output(result: Mapping[str, Any]) -> Dict[str, Any]:
    output = result.get("output")
    return dict(output) if isinstance(output, Mapping) else {}


def _derived_artifact_id(result: Mapping[str, Any]) -> str:
    artifact = result.get("artifact")
    if hasattr(artifact, "artifact_id"):
        return str(getattr(artifact, "artifact_id") or "")
    if hasattr(artifact, "id"):
        return str(getattr(artifact, "id") or "")
    if isinstance(artifact, Mapping):
        return str(artifact.get("artifact_id") or artifact.get("id") or "")
    return ""


def _record_metadata_value(record: Mapping[str, Any], key: str) -> str:
    metadata = record.get("metadata")
    if isinstance(metadata, Mapping):
        value = metadata.get(key)
        if isinstance(value, str):
            return value
    return ""


def _safe_short_text(value: Any, *, limit: int = 240) -> str:
    text = str(value or "")
    text = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[email]", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}\b", "[phone]", text)
    text = re.sub(r"\b\d{4,}\b", "[number]", text)
    return text.strip()[:limit]


def _read_string_list(value: Any, *, limit: int = 12) -> List[str]:
    if not isinstance(value, list):
        return []
    return [_safe_short_text(item, limit=80) for item in value if _safe_short_text(item, limit=80)][:limit]


def _read_number(record: Mapping[str, Any] | None, key: str) -> int | float | None:
    if not isinstance(record, Mapping):
        return None
    value = record.get(key)
    return value if isinstance(value, (int, float)) else None


def _read_string(record: Mapping[str, Any] | None, key: str) -> str:
    if not isinstance(record, Mapping):
        return ""
    value = record.get(key)
    return str(value).strip() if isinstance(value, str) else ""


def _default_labels_for_mime_type(mime_type: str) -> List[str]:
    normalized = str(mime_type or "").lower()
    if normalized == "application/pdf":
        return ["pdf", "document"]
    if normalized.startswith("image/"):
        return ["image", "visual file"]
    if normalized.startswith("text/"):
        return ["text", "document"]
    if "json" in normalized:
        return ["json", "structured data"]
    if "spreadsheet" in normalized or "excel" in normalized or "csv" in normalized:
        return ["spreadsheet", "tabular data"]
    if "wordprocessing" in normalized or "msword" in normalized:
        return ["word document", "document"]
    if normalized.startswith("audio/"):
        return ["audio"]
    if normalized.startswith("video/"):
        return ["video"]
    return ["wallet file"]


def _display_mime_type(mime_type: str) -> str:
    normalized = str(mime_type or "").strip().lower()
    if not normalized:
        return "Unknown file"
    if normalized == "application/pdf":
        return "PDF document"
    if normalized.startswith("image/"):
        return f"{normalized.split('/', 1)[1].upper()} image"
    if normalized.startswith("text/"):
        return "Text document"
    if "json" in normalized:
        return "JSON data"
    if "spreadsheet" in normalized or "excel" in normalized or "csv" in normalized:
        return "Spreadsheet"
    if "wordprocessing" in normalized or "msword" in normalized:
        return "Word document"
    if normalized.startswith("audio/"):
        return "Audio file"
    if normalized.startswith("video/"):
        return "Video file"
    if normalized == "application/octet-stream":
        return "Encrypted/binary file"
    return normalized


def _fallback_document_profile_output(*, file_name: str, mime_type: str) -> Dict[str, Any]:
    return {
        "output_policy": "local_metadata_only",
        "profile": {"chunk_count": 0, "profile_type": "metadata fallback"},
        "summary": f"{_display_mime_type(mime_type)} wallet file queued for redacted profiling.",
        "upload_state": {"fileName": file_name, "mimeType": mime_type},
    }


def _build_document_profile_public_inputs(
    *,
    artifact_ids: Sequence[str],
    file_name: str,
    mime_type: str,
    outputs: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    graphs = [output.get("graph") for output in outputs]
    graph = next((item for item in graphs if isinstance(item, Mapping)), {})
    profiles = [output.get("profile") for output in outputs]
    profile = next((item for item in profiles if isinstance(item, Mapping)), {})
    redaction_count = 0
    for output in outputs:
        counts = output.get("redaction_counts")
        if isinstance(counts, Mapping):
            redaction_count += sum(value for value in counts.values() if isinstance(value, (int, float)))
    public_mime_type = mime_type or "application/octet-stream"
    labels = _default_labels_for_mime_type(public_mime_type)
    return {
        "artifact_ids": list(artifact_ids),
        "chunk_count": _read_number(profile, "chunk_count"),
        "edge_count": _read_number(graph, "edge_count"),
        "file_name_profile": file_name,
        "graph_type": _read_string(graph, "graph_type"),
        "mime_family": public_mime_type.split("/", 1)[0] or "application",
        "mime_type": public_mime_type,
        "node_count": _read_number(graph, "node_count"),
        "organizer_labels": labels,
        "organizer_summary": _display_mime_type(public_mime_type),
        "output_policies": sorted({str(output.get("output_policy")) for output in outputs if output.get("output_policy")}),
        "privacy_policy": "no_plaintext_public_inputs",
        "profile_methods": sorted({str(output.get("output_policy")) for output in outputs if output.get("output_policy")}),
        "redaction_count": redaction_count,
        "size_bucket": "server-side",
        "summary": "Redacted GraphRAG, vector metadata, and derived descriptors created inside the wallet boundary.",
    }


def _classify_document_profile(public_inputs: Mapping[str, Any]) -> str:
    summary = _read_string(public_inputs, "organizer_summary")
    if summary:
        return summary
    labels = _read_string_list(public_inputs.get("organizer_labels"), limit=3)
    if labels:
        return ", ".join(labels[:3])
    return _display_mime_type(str(public_inputs.get("mime_type") or ""))


def _summarize_document_profile(public_inputs: Mapping[str, Any]) -> str:
    mime_type = str(public_inputs.get("mime_type") or "document")
    graph_type = str(public_inputs.get("graph_type") or "redacted graph")
    nodes = public_inputs.get("node_count")
    chunks = public_inputs.get("chunk_count")
    nodes_text = f"{nodes} nodes" if isinstance(nodes, (int, float)) else "safe graph"
    chunks_text = f"{chunks} chunks" if isinstance(chunks, (int, float)) else "vector metadata"
    return f"{mime_type} · {graph_type} · {nodes_text} · {chunks_text}"


def _build_privacy_search_text(outputs: Sequence[Mapping[str, Any]], public_inputs: Mapping[str, Any]) -> str:
    parts: List[str] = [
        _classify_document_profile(public_inputs),
        _summarize_document_profile(public_inputs),
        " ".join(_read_string_list(public_inputs.get("organizer_labels"), limit=12)),
        " ".join(str(policy) for policy in public_inputs.get("output_policies", []) if isinstance(policy, str)),
    ]
    for output in outputs:
        parts.append(_safe_short_text(output.get("summary")))
        parts.append(_safe_short_text(output.get("text")))
    return " ".join(part for part in parts if part).strip()


def _build_privacy_vector_terms(outputs: Sequence[Mapping[str, Any]], public_inputs: Mapping[str, Any]) -> List[str]:
    terms: List[str] = []
    terms.extend(_read_string_list(public_inputs.get("organizer_labels"), limit=12))
    for key in ("mime_type", "mime_family", "graph_type", "organizer_summary"):
        value = public_inputs.get(key)
        if isinstance(value, str) and value.strip():
            terms.append(value.strip())
    for output in outputs:
        policy = output.get("output_policy")
        if isinstance(policy, str) and policy.strip():
            terms.append(policy.strip())
    normalized: List[str] = []
    seen = set()
    for term in terms:
        safe = _safe_short_text(term, limit=80).lower()
        if safe and safe not in seen:
            normalized.append(safe)
            seen.add(safe)
    return normalized[:24]


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


@router.post("/wallets/{wallet_id}/controllers")
def add_wallet_controller(wallet_id: str, request: WalletControllerRequest) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        wallet = service.add_controller(
            wallet_id,
            actor_did=request.actor_did,
            controller_did=request.controller_did,
            controller_secret=_optional_hex_key(request.controller_key_hex),
            approval_id=request.approval_id,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return wallet.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/controllers/remove")
def remove_wallet_controller(wallet_id: str, request: WalletControllerRequest) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        wallet = service.remove_controller(
            wallet_id,
            actor_did=request.actor_did,
            controller_did=request.controller_did,
            approval_id=request.approval_id,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return wallet.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/devices")
def add_wallet_device(wallet_id: str, request: WalletDeviceRequest) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        wallet = service.add_device(
            wallet_id,
            actor_did=request.actor_did,
            device_did=request.device_did,
            device_secret=_optional_hex_key(request.device_key_hex),
            approval_id=request.approval_id,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return wallet.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/devices/revoke")
def revoke_wallet_device(wallet_id: str, request: WalletDeviceRequest) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        wallet = service.revoke_device(
            wallet_id,
            actor_did=request.actor_did,
            device_did=request.device_did,
            approval_id=request.approval_id,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return wallet.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/recovery-policy")
def set_wallet_recovery_policy(wallet_id: str, request: WalletRecoveryPolicyRequest) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        wallet = service.set_recovery_policy(
            wallet_id,
            actor_did=request.actor_did,
            contact_dids=request.contact_dids,
            threshold=request.threshold,
            approval_id=request.approval_id,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return wallet.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/recovery-bundles")
def store_wallet_recovery_bundle(wallet_id: str, request: WalletRecoveryBundleRequest) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        bundle = service.store_recovery_bundle(
            wallet_id,
            actor_did=request.actor_did,
            encrypted_bundle=request.encrypted_bundle,
            wrapping_method=request.wrapping_method,
            kdf=request.kdf,
            recovery_hint=request.recovery_hint,
            public_metadata=request.public_metadata,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return {
            "bundle": bundle.to_dict(),
            "privacy": {
                "server_can_decrypt": False,
                "plaintext_wallet_key_received": False,
                "authorization_model": "wallet actor creates encrypted recovery material; magic-login UCAN can only read encrypted bundles",
            },
        }
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/wallets/{wallet_id}/recovery-bundles/latest")
def get_latest_wallet_recovery_bundle(
    wallet_id: str,
    authorization: str | None = Header(default=None),
) -> Dict[str, Any]:
    resource = f"wallet://{wallet_id}/recovery-bundles/latest"
    ucan = _require_magic_ucan(
        authorization=authorization,
        wallet_id=wallet_id,
        ability="wallet/recovery/read_encrypted",
        resource=resource,
    )
    service = _load_wallet_service(wallet_id)
    try:
        bundle = service.latest_recovery_bundle(wallet_id)
        return {
            "bundle": bundle.to_dict(),
            "ucan": {
                "profile": str(ucan.get("profile") or ""),
                "audience": str(ucan.get("aud") or ""),
                "capabilities": ucan.get("capabilities") or [],
                "expires_at": int(ucan.get("expiresAt") or 0),
            },
            "privacy": {
                "server_can_decrypt": False,
                "plaintext_wallet_key_returned": False,
            },
        }
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/wallets/{wallet_id}/recovery-bundles/{bundle_id}")
def get_wallet_recovery_bundle(
    wallet_id: str,
    bundle_id: str,
    authorization: str | None = Header(default=None),
) -> Dict[str, Any]:
    resource = f"wallet://{wallet_id}/recovery-bundles/{bundle_id}"
    ucan = _require_magic_ucan(
        authorization=authorization,
        wallet_id=wallet_id,
        ability="wallet/recovery/read_encrypted",
        resource=resource,
    )
    service = _load_wallet_service(wallet_id)
    try:
        bundle = service.get_recovery_bundle(wallet_id, bundle_id)
        return {
            "bundle": bundle.to_dict(),
            "ucan": {
                "profile": str(ucan.get("profile") or ""),
                "audience": str(ucan.get("aud") or ""),
                "capabilities": ucan.get("capabilities") or [],
                "expires_at": int(ucan.get("expiresAt") or 0),
            },
            "privacy": {
                "server_can_decrypt": False,
                "plaintext_wallet_key_returned": False,
            },
        }
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/controllers/recover")
def recover_wallet_controller(wallet_id: str, request: WalletControllerRecoveryRequest) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        wallet = service.recover_controller(
            wallet_id,
            actor_did=request.actor_did,
            controller_did=request.controller_did,
            controller_secret=_optional_hex_key(request.controller_key_hex),
            approval_id=request.approval_id,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return wallet.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.patch("/wallets/{wallet_id}/records/{record_id}/metadata")
def update_wallet_record_metadata(
    wallet_id: str,
    record_id: str,
    request: WalletRecordMetadataRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        record = service.update_record_metadata(
            wallet_id,
            record_id,
            actor_did=request.actor_did,
            metadata=request.metadata,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return record
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/wallets/{wallet_id}/records/{record_id}")
def delete_wallet_record(
    wallet_id: str,
    record_id: str,
    request: DeleteWalletRecordRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        result = service.delete_record(
            wallet_id,
            record_id,
            actor_did=request.actor_did,
            unpin_ipfs=request.unpin_ipfs,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return result
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/locations/{location_record_id}/region-proofs")
def create_location_region_proof(
    wallet_id: str,
    location_record_id: str,
    request: LocationRegionProofRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        proof = service.create_location_region_proof(
            wallet_id,
            location_record_id,
            actor_did=request.actor_did,
            region_id=request.region_id,
            grant_id=request.grant_id,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return proof.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/locations/{location_record_id}/distance-proofs")
def create_location_distance_proof(
    wallet_id: str,
    location_record_id: str,
    request: LocationDistanceProofRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        proof = service.create_location_distance_proof(
            wallet_id,
            location_record_id,
            actor_did=request.actor_did,
            target_id=request.target_id,
            target_lat=request.target_lat,
            target_lon=request.target_lon,
            max_distance_km=request.max_distance_km,
            grant_id=request.grant_id,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return proof.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/records/{record_id}/document-profile-proofs")
def create_document_profile_proof(
    wallet_id: str,
    record_id: str,
    request: DocumentPrivacyProfileProofRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        proof = service.create_document_profile_proof(
            wallet_id,
            record_id,
            actor_did=request.actor_did,
            public_inputs=request.public_inputs,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return proof.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/records/{record_id}/metadata/generate")
def generate_wallet_record_metadata(
    wallet_id: str,
    record_id: str,
    request: WalletRecordMetadataGenerationRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    actor_secret = _optional_hex_key(request.actor_key_hex)
    invocation = invocation_from_token(request.invocation_token) if request.invocation_token else None
    try:
        if invocation is not None:
            service.verify_invocation(
                wallet_id,
                invocation,
                actor_did=request.actor_did,
                resource=resource_for_record(wallet_id, record_id),
                ability="record/analyze",
                actor_secret=actor_secret,
            )

        metadata_status = service.update_record_metadata(
            wallet_id,
            record_id,
            actor_did=request.actor_did,
            metadata={
                "privacyProfileMessage": "Creating redacted GraphRAG, vector metadata, and wallet router labels.",
                "privacyProfileStatus": "profiling",
                **({"privacyProfileMimeType": request.mime_type} if request.mime_type else {}),
            },
        )

        derived_results: List[Dict[str, Any]] = []
        result_errors: List[str] = []
        shared_kwargs = {
            "wallet_id": wallet_id,
            "record_id": record_id,
            "actor_did": request.actor_did,
            "grant_id": invocation.grant_id if invocation is not None else request.grant_id,
            "actor_secret": actor_secret,
        }
        for create_result in (
            lambda: service.analyze_document_with_redaction(
                **shared_kwargs,
                max_chars=500,
                **({"invocation_caveats": invocation.caveats} if invocation is not None else {}),
            ),
            lambda: service.create_document_vector_profile(
                **shared_kwargs,
                chunk_size_words=80,
                **({"invocation_caveats": invocation.caveats} if invocation is not None else {}),
            ),
            lambda: service.create_redacted_graphrag(
                wallet_id,
                [record_id],
                actor_did=request.actor_did,
                grant_id=invocation.grant_id if invocation is not None else request.grant_id,
                actor_secret=actor_secret,
                max_chars_per_record=request.max_chars_per_record,
                max_bytes_per_record=request.max_bytes_per_record,
                use_ocr=request.use_ocr,
                **({"invocation_caveats": invocation.caveats} if invocation is not None else {}),
            ),
            lambda: service.extract_document_text_with_redaction(
                **shared_kwargs,
                max_chars=12_000,
                max_bytes=request.max_bytes_per_record,
                use_ocr=request.use_ocr,
                **({"invocation_caveats": invocation.caveats} if invocation is not None else {}),
            ),
            lambda: service.analyze_document_form_with_redaction(
                **shared_kwargs,
                max_fields=100,
                use_ocr=request.use_ocr,
                **({"invocation_caveats": invocation.caveats} if invocation is not None else {}),
            ),
        ):
            try:
                derived_results.append(create_result())
            except Exception as exc:
                result_errors.append(str(exc))

        outputs = [_derived_output(result) for result in derived_results if _derived_output(result)]
        if not outputs:
            outputs.append(
                _fallback_document_profile_output(
                    file_name=request.file_name or record_id,
                    mime_type=request.mime_type or _record_metadata_value(metadata_status, "privacyProfileMimeType") or "application/octet-stream",
                )
            )
        artifact_ids = [_derived_artifact_id(result) for result in derived_results]
        artifact_ids = [artifact_id for artifact_id in artifact_ids if artifact_id]
        public_inputs = _build_document_profile_public_inputs(
            artifact_ids=artifact_ids,
            file_name=request.file_name or _record_metadata_value(metadata_status, "fileName") or record_id,
            mime_type=request.mime_type or _record_metadata_value(metadata_status, "privacyProfileMimeType") or "application/octet-stream",
            outputs=outputs,
        )
        proof = service.create_document_profile_proof(
            wallet_id,
            record_id,
            actor_did=request.actor_did,
            public_inputs=public_inputs,
        )
        metadata_patch: Dict[str, Any] = {
            "privacyProfileArtifactIds": artifact_ids,
            "privacyProfileClassification": _classify_document_profile(public_inputs),
            "privacyProfileLabels": _read_string_list(public_inputs.get("organizer_labels")) or _default_labels_for_mime_type(str(public_inputs.get("mime_type") or "")),
            "privacyProfileMessage": "Safe document profile and proof are attached to this wallet record.",
            "privacyProfileMimeType": public_inputs.get("mime_type"),
            "privacyProfileNeedsRefresh": False,
            "privacyProfileProofId": proof.proof_id,
            "privacyProfilePublicInputs": public_inputs,
            "privacyProfileSearchText": _build_privacy_search_text(outputs, public_inputs),
            "privacyProfileStatus": "profiled",
            "privacyProfileSummary": _summarize_document_profile(public_inputs),
            "privacyProfileVectorTerms": _build_privacy_vector_terms(outputs, public_inputs),
        }
        if result_errors:
            metadata_patch["privacyProfileWarnings"] = result_errors[:5]
        record = service.update_record_metadata(
            wallet_id,
            record_id,
            actor_did=request.actor_did,
            metadata=metadata_patch,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return {
            "record": record,
            "metadata": record.get("metadata", {}),
            "proof": proof.to_dict(),
            "router": {
                "wallet_id": wallet_id,
                "wallet_cid": request.wallet_cid,
                "provider": request.provider,
                "model_name": request.model_name,
            },
        }
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


@router.get("/analytics/templates")
def list_analytics_templates(include_inactive: bool = False) -> Dict[str, Any]:
    templates = _list_shared_analytics_templates(default_wallet_dir())
    if not include_inactive:
        templates = [
            template
            for template in templates
            if str(template.get("status") or "approved") == "approved"
        ]
    return {"templates": templates}


@router.get("/wallets/{wallet_id}/analytics/consents")
def list_wallet_analytics_consents(wallet_id: str, status: str = "all") -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    normalized_status = str(status or "all").strip().lower() or "all"
    consents = [
        consent.to_dict()
        for consent in sorted(service.analytics_consents.values(), key=lambda item: item.created_at)
        if consent.wallet_id == wallet_id and (normalized_status == "all" or consent.status == normalized_status)
    ]
    return {"consents": consents}


@router.post("/wallets/{wallet_id}/analytics/consents/from-template")
def create_wallet_analytics_consent_from_template(
    wallet_id: str,
    request: AnalyticsConsentFromTemplateRequest,
) -> Dict[str, Any]:
    wallet_dir = default_wallet_dir()
    service = _load_wallet_service(wallet_id, wallet_dir=wallet_dir)
    _inject_shared_analytics_templates(service, wallet_dir)
    try:
        template = service._analytics_template(request.template_id)
        consent = service.create_analytics_consent(
            wallet_id,
            actor_did=request.actor_did,
            template_id=template.template_id,
            allowed_record_types=list(template.allowed_record_types),
            allowed_derived_fields=list(template.allowed_derived_fields),
            aggregation_policy=dict(template.aggregation_policy),
            expires_at=request.expires_at,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return consent.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/analytics/consents/{consent_id}/revoke")
def revoke_wallet_analytics_consent(
    wallet_id: str,
    consent_id: str,
    request: AnalyticsConsentRevokeRequest,
) -> Dict[str, Any]:
    wallet_dir = default_wallet_dir()
    service = _load_wallet_service(wallet_id, wallet_dir=wallet_dir)
    try:
        consent = service.revoke_analytics_consent(wallet_id, consent_id, actor_did=request.actor_did)
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return consent.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/wallets/{wallet_id}/audit", response_model=WalletAuditEventsResponse)
def list_wallet_audit(wallet_id: str) -> WalletAuditEventsResponse:
    service = _load_wallet_service(wallet_id)
    return WalletAuditEventsResponse(events=_serialize_many(service.get_audit_log(wallet_id)))


@router.post("/wallets/{wallet_id}/dead-drops/missing-person")
def send_missing_person_dead_drop_email(
    wallet_id: str,
    request: MissingPersonDeadDropEmailRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    actor = str(request.actor_did or "").strip()
    if not actor:
        raise HTTPException(status_code=400, detail="actor_did is required")
    if actor not in service._wallet_principals(wallet_id):
        raise HTTPException(status_code=400, detail="actor_did is not authorized for this wallet")
    try:
        to_email = _require_portland_police_missing_email(request.to_email)
        envelope = _send_dead_drop_email(
            to_email=to_email,
            subject=request.subject,
            body=request.body,
            bundle=request.bundle,
            bundle_filename=request.bundle_filename,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "wallet_id": wallet_id,
        "status": "sent",
        "to_email": to_email,
        "subject": request.subject,
        "bundle_filename": request.bundle_filename,
        **envelope,
    }


@router.get("/wallets/{wallet_id}/dead-drops/missing-person")
def get_missing_person_dead_drop(wallet_id: str) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    return service.get_missing_person_dead_drop(wallet_id).to_dict()


@router.put("/wallets/{wallet_id}/dead-drops/missing-person")
def save_missing_person_dead_drop(
    wallet_id: str,
    request: MissingPersonDeadDropConfigRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        record = service.save_missing_person_dead_drop(
            wallet_id,
            actor_did=request.actor_did,
            enabled=request.enabled,
            to_email=_require_portland_police_missing_email(request.to_email),
            subject=request.subject,
            body=request.body,
            bundle=request.bundle,
            bundle_filename=request.bundle_filename,
            due_at=request.due_at,
            last_check_in_at=request.last_check_in_at,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return record.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/dead-drops/missing-person/dispatch")
def dispatch_missing_person_dead_drop(
    wallet_id: str,
    request: MissingPersonDeadDropDispatchRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        record = service.get_missing_person_dead_drop_for_dispatch(wallet_id, actor_did=request.actor_did)
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        envelope = _send_dead_drop_email(
            to_email=_require_portland_police_missing_email(record.to_email),
            subject=record.subject,
            body=record.body,
            bundle=record.bundle,
            bundle_filename=record.bundle_filename,
        )
        updated = service.mark_missing_person_dead_drop_sent(
            wallet_id,
            actor_did=request.actor_did,
            message_id=str(envelope.get("message_id") or ""),
            dispatched_reason="manual",
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return {
            "wallet_id": wallet_id,
            "status": "sent",
            "to_email": updated.to_email,
            "subject": updated.subject,
            "bundle_filename": updated.bundle_filename,
            **envelope,
        }
    except Exception as exc:
        service.mark_missing_person_dead_drop_failed(
            wallet_id,
            actor_did=request.actor_did,
            error=str(exc),
            dispatched_reason="manual",
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/wallets/{wallet_id}/portal/saved-services", response_model=SavedServicesResponse)
def list_saved_services(wallet_id: str, status: str | None = None) -> SavedServicesResponse:
    try:
        service = _load_wallet_service(wallet_id)
        return SavedServicesResponse(
            saved_services=[record.to_dict() for record in service.list_saved_services(wallet_id, status=status)]
        )
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/portal/saved-services")
def save_service(wallet_id: str, request: SavedServiceRequest) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        record = service.save_service_for_wallet(
            wallet_id,
            actor_did=request.actor_did,
            service_doc_id=request.service_doc_id,
            source_content_cid=request.source_content_cid,
            source_page_cid=request.source_page_cid,
            title=request.title,
            provider_name=request.provider_name,
            program_name=request.program_name,
            source_url=request.source_url,
            label=request.label,
            reason=request.reason,
            priority=request.priority,
            status=request.status,
            private_notes_record_id=request.private_notes_record_id,
            metadata=request.metadata,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return record.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/wallets/{wallet_id}/portal/interactions", response_model=ServiceInteractionsResponse)
def list_service_interactions(
    wallet_id: str,
    service_doc_id: str | None = None,
    interaction_type: str | None = None,
    status: str | None = None,
) -> ServiceInteractionsResponse:
    try:
        service = _load_wallet_service(wallet_id)
        return ServiceInteractionsResponse(
            interactions=[
                record.to_dict()
                for record in service.list_service_interactions(
                    wallet_id,
                    service_doc_id=service_doc_id,
                    interaction_type=interaction_type,
                    status=status,
                )
            ]
        )
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/portal/interactions")
def create_service_interaction(wallet_id: str, request: ServiceInteractionRequest) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        record = service.create_service_interaction(
            wallet_id,
            actor_did=request.actor_did,
            service_doc_id=request.service_doc_id,
            source_content_cid=request.source_content_cid,
            source_page_cid=request.source_page_cid,
            provider_name=request.provider_name,
            program_name=request.program_name,
            interaction_type=request.interaction_type,
            channel=request.channel,
            counterparty_name=request.counterparty_name,
            counterparty_contact=request.counterparty_contact,
            timestamp=request.timestamp,
            status=request.status,
            outcome=request.outcome,
            notes_record_id=request.notes_record_id,
            next_action=request.next_action,
            next_follow_up_at=request.next_follow_up_at,
            source_action_url=request.source_action_url,
            related_grant_ids=request.related_grant_ids,
            related_record_ids=request.related_record_ids,
            privacy_level=request.privacy_level,
            metadata=request.metadata,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return record.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/wallets/{wallet_id}/portal/plans", response_model=ServicePlansResponse)
def list_service_plans(
    wallet_id: str,
    service_doc_id: str | None = None,
    status: str | None = None,
) -> ServicePlansResponse:
    try:
        service = _load_wallet_service(wallet_id)
        return ServicePlansResponse(
            plans=[
                record.to_dict()
                for record in service.list_service_plans(
                    wallet_id,
                    service_doc_id=service_doc_id,
                    status=status,
                )
            ]
        )
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/portal/plans")
def create_service_plan(wallet_id: str, request: ServicePlanRequest) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        record = service.create_service_plan(
            wallet_id,
            actor_did=request.actor_did,
            service_doc_id=request.service_doc_id,
            source_content_cid=request.source_content_cid,
            source_page_cid=request.source_page_cid,
            service_title=request.service_title,
            provider_name=request.provider_name,
            goal=request.goal,
            steps=request.steps,
            documents_needed=request.documents_needed,
            questions_to_ask=request.questions_to_ask,
            appointment_at=request.appointment_at,
            reminder_at=request.reminder_at,
            travel_target=request.travel_target,
            assigned_worker_recipient_id=request.assigned_worker_recipient_id,
            status=request.status,
            related_interaction_ids=request.related_interaction_ids,
            private_notes_record_id=request.private_notes_record_id,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return record.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/wallets/{wallet_id}/portal/plans/{plan_id}")
def update_service_plan(wallet_id: str, plan_id: str, request: ServicePlanUpdateRequest) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        record = service.update_service_plan(
            wallet_id,
            plan_id,
            actor_did=request.actor_did,
            source_content_cid=request.source_content_cid,
            source_page_cid=request.source_page_cid,
            service_title=request.service_title,
            provider_name=request.provider_name,
            goal=request.goal,
            steps=request.steps,
            documents_needed=request.documents_needed,
            questions_to_ask=request.questions_to_ask,
            appointment_at=request.appointment_at,
            reminder_at=request.reminder_at,
            travel_target=request.travel_target,
            assigned_worker_recipient_id=request.assigned_worker_recipient_id,
            status=request.status,
            related_interaction_ids=request.related_interaction_ids,
            private_notes_record_id=request.private_notes_record_id,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return record.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/portal/plans/{plan_id}/share-grants")
def create_service_plan_share_grant(
    wallet_id: str,
    plan_id: str,
    request: ServicePlanShareGrantRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        result = service.create_service_plan_share_grant(
            wallet_id,
            plan_id,
            issuer_did=request.actor_did or request.issuer_did,
            audience_did=request.audience_did or request.worker_did,
            scopes=request.scopes,
            purpose=request.purpose,
            worker_recipient_id=request.worker_recipient_id,
            worker_name=request.worker_name,
            expires_at=request.expires_at,
            approval_id=request.approval_id,
            issuer_secret=_optional_hex_key(request.issuer_key_hex),
            audience_secret=_optional_hex_key(request.audience_key_hex),
            extra_caveats=request.caveats,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return result.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ops/health")
def ops_health(
    verify_storage: bool = False,
    authorization: str | None = Header(default=None),
    x_wallet_ops_shared_secret: str | None = Header(default=None),
) -> Dict[str, Any]:
    expected_secret = _ops_health_shared_secret()
    if expected_secret:
        supplied_secret = _extract_bearer_token(authorization) or str(x_wallet_ops_shared_secret or "").strip()
        if supplied_secret != expected_secret:
            raise HTTPException(status_code=401, detail="ops health authorization required")
    try:
        return _ops_health_report(verify_storage=verify_storage)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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


@router.post("/wallets/{wallet_id}/grants/{grant_id}/revoke")
def revoke_wallet_grant(
    wallet_id: str,
    grant_id: str,
    request: RevokeGrantRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        grant = service.revoke_grant(wallet_id, grant_id, actor_did=request.actor_did)
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return grant.to_dict()
    except (DataWalletError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wallets/{wallet_id}/emergency-revoke")
def emergency_revoke_wallet(
    wallet_id: str,
    request: EmergencyRevokeRequest,
) -> Dict[str, Any]:
    service = _load_wallet_service(wallet_id)
    wallet_dir = default_wallet_dir()
    try:
        report = service.emergency_revoke(
            wallet_id,
            actor_did=request.actor_did,
            actor_secret=_optional_hex_key(request.actor_key_hex),
            approval_id=request.approval_id,
            rotate_keys=request.rotate_keys,
            reason=request.reason,
        )
        _save_wallet_snapshot(service, wallet_dir, wallet_id)
        return report
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
