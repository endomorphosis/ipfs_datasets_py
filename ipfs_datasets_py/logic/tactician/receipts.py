"""Content-addressed receipts for Logic Tactician plans.

A :class:`TacticianReceipt` bundles a validated :class:`TacticianPlan` with
planner/policy identity anchors. Receipts are advisory only
(``semantic_authority=False``) and never authorize proof, write, or network
side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from .models import (
    SCHEMA_VERSION,
    TacticianPlan,
    TacticianPolicy,
    TacticianValidationError,
    _require_bool,
    _require_nonempty_str,
    _require_schema_version,
    compute_content_digest,
)
from .policy import DETERMINISTIC_PLANNER_ID, policy_content_id


class ReceiptError(TacticianValidationError):
    """Raised when a Tactician receipt fails validation."""


@dataclass(frozen=True)
class TacticianReceipt:
    """Immutable, content-addressed plan receipt."""

    receipt_id: str
    plan: TacticianPlan
    policy_digest: str
    planner_id: str = DETERMINISTIC_PLANNER_ID
    semantic_authority: bool = False
    schema_version: str = SCHEMA_VERSION

    def validate(self) -> None:
        owner = "TacticianReceipt"
        _require_schema_version(self.schema_version, owner=owner)
        if not isinstance(self.plan, TacticianPlan):
            raise ReceiptError(f"{owner}.plan must be a TacticianPlan")
        self.plan.validate()
        object.__setattr__(
            self,
            "policy_digest",
            _require_nonempty_str(
                self.policy_digest,
                field_name="policy_digest",
                owner=owner,
                max_length=512,
            ),
        )
        object.__setattr__(
            self,
            "planner_id",
            _require_nonempty_str(
                self.planner_id, field_name="planner_id", owner=owner
            ),
        )
        _require_bool(
            self.semantic_authority, field_name="semantic_authority", owner=owner
        )
        if self.semantic_authority is True:
            raise ReceiptError(f"{owner}.semantic_authority must remain False")
        body = self._body_dict()
        expected = compute_content_digest(body)
        if self.receipt_id != expected:
            raise ReceiptError(
                f"{owner}.receipt_id must equal content digest of the receipt body"
            )

    def _body_dict(self) -> Dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "planner_id": self.planner_id,
            "policy_digest": self.policy_digest,
            "schema_version": self.schema_version,
            "semantic_authority": False,
        }

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        payload = self._body_dict()
        payload["receipt_id"] = self.receipt_id
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TacticianReceipt":
        receipt = cls(
            receipt_id=str(data.get("receipt_id", "")),
            plan=TacticianPlan.from_dict(dict(data.get("plan") or {})),
            policy_digest=str(data.get("policy_digest", "")),
            planner_id=str(data.get("planner_id", DETERMINISTIC_PLANNER_ID)),
            semantic_authority=bool(data.get("semantic_authority", False)),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        )
        receipt.validate()
        return receipt

    @classmethod
    def from_plan(
        cls,
        plan: TacticianPlan,
        policy: TacticianPolicy,
        *,
        planner_id: Optional[str] = None,
    ) -> "TacticianReceipt":
        """Build a receipt binding ``plan`` to the content digest of ``policy``."""

        plan.validate()
        policy.validate()
        if plan.policy_id != policy.policy_id:
            raise ReceiptError("plan.policy_id must match policy.policy_id")
        digest = policy_content_id(policy)
        active_planner = planner_id or plan.planner_id
        provisional = cls(
            receipt_id="pending",
            plan=plan,
            policy_digest=digest,
            planner_id=active_planner,
            semantic_authority=False,
        )
        receipt_id = compute_content_digest(provisional._body_dict())
        receipt = cls(
            receipt_id=receipt_id,
            plan=plan,
            policy_digest=digest,
            planner_id=active_planner,
            semantic_authority=False,
        )
        receipt.validate()
        return receipt


__all__ = [
    "ReceiptError",
    "TacticianReceipt",
]
