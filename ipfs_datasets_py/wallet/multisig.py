"""Threshold approval helpers for the canonical data wallet."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterable, List, Optional

from .exceptions import AccessDeniedError, ApprovalRequiredError
from .models import ApprovalRequest, Wallet, utc_now
from .ucan import is_expired

SENSITIVE_ABILITIES = {
    "record/decrypt",
    "document/decrypt",
    "wallet/admin",
    "export/create",
}


def normalize_governance_policy(
    *,
    controller_dids: List[str],
    governance_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    policy = dict(governance_policy or {})
    approvers = list(policy.get("approver_dids") or controller_dids)
    threshold = int(policy.get("threshold") or 1)
    threshold = max(1, min(threshold, len(approvers) or 1))
    policy["approver_dids"] = approvers
    policy["threshold"] = threshold
    policy.setdefault("sensitive_abilities", sorted(SENSITIVE_ABILITIES))
    return policy


def operation_requires_approval(
    wallet: Wallet,
    *,
    operation: str,
    abilities: Iterable[str],
    resources: Iterable[str],
    caveats: Optional[Dict[str, Any]] = None,
) -> bool:
    policy = normalize_governance_policy(
        controller_dids=wallet.controller_dids,
        governance_policy=wallet.governance_policy,
    )
    if int(policy.get("threshold") or 1) <= 1:
        return False
    ability_set = set(abilities)
    sensitive_abilities = set(policy.get("sensitive_abilities") or SENSITIVE_ABILITIES)
    if ability_set.intersection(sensitive_abilities):
        return True
    if operation in set(policy.get("sensitive_operations") or []):
        return True
    if (caveats or {}).get("full_wallet") is True:
        return True
    return any(str(resource).endswith("/*") for resource in resources)


def create_approval_request(
    wallet: Wallet,
    *,
    requested_by: str,
    operation: str,
    resources: List[str],
    abilities: List[str],
    details: Optional[Dict[str, Any]] = None,
    expires_at: Optional[str] = None,
) -> ApprovalRequest:
    policy = normalize_governance_policy(
        controller_dids=wallet.controller_dids,
        governance_policy=wallet.governance_policy,
    )
    return ApprovalRequest(
        approval_id=f"approval-{uuid.uuid4().hex}",
        wallet_id=wallet.wallet_id,
        operation=operation,
        requested_by=requested_by,
        resources=list(resources),
        abilities=list(abilities),
        threshold=int(policy["threshold"]),
        approver_dids=list(policy["approver_dids"]),
        details=details or {},
        expires_at=expires_at,
    )


def approve_request(request: ApprovalRequest, *, approver_did: str) -> ApprovalRequest:
    if request.status not in {"pending", "approved"}:
        raise AccessDeniedError(f"Approval request is not approvable: {request.status}")
    if is_expired(request.expires_at):
        request.status = "expired"
        raise AccessDeniedError("Approval request is expired")
    if approver_did not in set(request.approver_dids):
        raise AccessDeniedError("Approver is not in wallet governance policy")
    request.approvals[approver_did] = utc_now()
    if request.approved_count >= request.threshold:
        request.status = "approved"
    return request


def verify_approval(
    approvals: Dict[str, ApprovalRequest],
    *,
    approval_id: Optional[str],
    operation: str,
    requested_by: str,
    resources: List[str],
    abilities: List[str],
) -> ApprovalRequest:
    if not approval_id:
        raise ApprovalRequiredError("approval_id is required for this operation")
    try:
        request = approvals[approval_id]
    except KeyError as exc:
        raise ApprovalRequiredError(f"Approval request not found: {approval_id}") from exc
    if request.status != "approved" or is_expired(request.expires_at):
        raise ApprovalRequiredError("Approval request is not approved")
    if request.operation != operation:
        raise ApprovalRequiredError("Approval operation does not match request")
    if request.requested_by != requested_by:
        raise ApprovalRequiredError("Approval requester does not match issuer")
    if set(request.resources) != set(resources):
        raise ApprovalRequiredError("Approval resources do not match request")
    if set(request.abilities) != set(abilities):
        raise ApprovalRequiredError("Approval abilities do not match request")
    return request

