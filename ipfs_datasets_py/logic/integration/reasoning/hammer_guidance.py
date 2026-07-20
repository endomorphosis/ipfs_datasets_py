"""Trusted guidance artifacts produced by Legal IR hammer runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .hammer import HammerBackendResult, HammerResult, HammerStatus


HAMMER_GUIDANCE_SCHEMA_VERSION = "legal-ir-hammer-guidance-v1"
_SOURCE_TEXT_KEYS = {
    "copied_text",
    "draft_text",
    "full_text",
    "raw_source",
    "source_span",
    "source_text",
    "text",
}


def _stable_json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _sanitize_metadata(value: Any) -> Any:
    """Return metadata without raw legal text payloads.

    Leanstral and decompiler artifacts may contain long source spans. Guidance
    artifacts should identify those spans by hash/provenance fields, not train on
    copied source text.
    """

    if isinstance(value, Mapping):
        sanitized: Dict[str, Any] = {}
        for key, child in sorted(value.items(), key=lambda item: str(item[0])):
            key_text = str(key)
            lowered = key_text.lower()
            if lowered in _SOURCE_TEXT_KEYS or lowered.endswith("_source_text"):
                text = str(child or "")
                sanitized[f"{key_text}_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
                sanitized[f"{key_text}_omitted"] = True
                continue
            sanitized[key_text] = _sanitize_metadata(child)
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [_sanitize_metadata(item) for item in value]
    return value


def _backend_statuses(results: Sequence[HammerBackendResult]) -> Dict[str, str]:
    return {
        str(result.backend): str(getattr(result.status, "value", result.status))
        for result in results
    }


@dataclass(frozen=True)
class HammerGuidanceArtifact:
    """Machine-readable bridge signal for autoencoder and Codex consumers."""

    guidance_id: str
    obligation_id: str
    trusted: bool
    legal_ir_view: str
    logic_family: str
    target_component: str
    goal_name: str
    goal_statement_hash: str
    proved: bool
    proof_checked: bool
    backend_statuses: Dict[str, str] = field(default_factory=dict)
    selected_premises: List[str] = field(default_factory=list)
    premise_views: List[str] = field(default_factory=list)
    reconstruction_status: str = ""
    winner_backend: str = ""
    failure_reason: str = ""
    rejection_reasons: List[str] = field(default_factory=list)
    proof_obligation_ids: List[str] = field(default_factory=list)
    target_metrics: List[str] = field(default_factory=list)
    drafted_logic_candidates: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = HAMMER_GUIDANCE_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend_statuses": dict(sorted(self.backend_statuses.items())),
            "drafted_logic_candidates": [
                dict(sorted(candidate.items())) for candidate in self.drafted_logic_candidates
            ],
            "failure_reason": self.failure_reason,
            "goal_name": self.goal_name,
            "goal_statement_hash": self.goal_statement_hash,
            "guidance_id": self.guidance_id,
            "legal_ir_view": self.legal_ir_view,
            "logic_family": self.logic_family,
            "metadata": dict(sorted(self.metadata.items())),
            "obligation_id": self.obligation_id,
            "premise_views": list(self.premise_views),
            "proof_checked": bool(self.proof_checked),
            "proof_obligation_ids": list(self.proof_obligation_ids),
            "proved": bool(self.proved),
            "reconstruction_status": self.reconstruction_status,
            "rejection_reasons": list(self.rejection_reasons),
            "schema_version": self.schema_version,
            "selected_premises": list(self.selected_premises),
            "target_component": self.target_component,
            "target_metrics": list(self.target_metrics),
            "trusted": bool(self.trusted),
            "winner_backend": self.winner_backend,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HammerGuidanceArtifact":
        return cls(
            guidance_id=str(data.get("guidance_id") or ""),
            obligation_id=str(data.get("obligation_id") or ""),
            trusted=bool(data.get("trusted")),
            legal_ir_view=str(data.get("legal_ir_view") or ""),
            logic_family=str(data.get("logic_family") or ""),
            target_component=str(data.get("target_component") or ""),
            goal_name=str(data.get("goal_name") or ""),
            goal_statement_hash=str(data.get("goal_statement_hash") or ""),
            proved=bool(data.get("proved")),
            proof_checked=bool(data.get("proof_checked")),
            backend_statuses={
                str(key): str(value)
                for key, value in dict(data.get("backend_statuses") or {}).items()
            },
            selected_premises=_string_list(data.get("selected_premises")),
            premise_views=_string_list(data.get("premise_views")),
            reconstruction_status=str(data.get("reconstruction_status") or ""),
            winner_backend=str(data.get("winner_backend") or ""),
            failure_reason=str(data.get("failure_reason") or ""),
            rejection_reasons=_string_list(data.get("rejection_reasons")),
            proof_obligation_ids=_string_list(data.get("proof_obligation_ids")),
            target_metrics=_string_list(data.get("target_metrics")),
            drafted_logic_candidates=[
                dict(item)
                for item in data.get("drafted_logic_candidates", []) or []
                if isinstance(item, Mapping)
            ],
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version") or HAMMER_GUIDANCE_SCHEMA_VERSION),
        )

    @classmethod
    def from_hammer_result(
        cls,
        result: HammerResult,
        *,
        candidate_metadata: Optional[Mapping[str, Any]] = None,
        trusted_requires_reconstruction: bool = False,
    ) -> "HammerGuidanceArtifact":
        metadata = _sanitize_metadata(candidate_metadata or result.goal.metadata or {})
        obligation_id = str(
            metadata.get("obligation_id")
            or metadata.get("proof_obligation_id")
            or result.goal.metadata.get("obligation_id")
            or result.goal.name
        )
        legal_ir_view = str(
            metadata.get("legal_ir_view")
            or metadata.get("target_component")
            or result.goal.metadata.get("legal_ir_view")
            or ""
        )
        logic_family = str(
            metadata.get("logic_family")
            or result.goal.metadata.get("logic_family")
            or ""
        )
        target_component = str(
            metadata.get("target_component")
            or legal_ir_view
            or result.goal.metadata.get("target_component")
            or ""
        )
        reconstruction = result.reconstruction
        reconstruction_status = str(getattr(reconstruction, "status", "") or "")
        proof_checked = bool(getattr(reconstruction, "verified", False))
        proved = result.status == HammerStatus.PROVED
        trusted = proved and (proof_checked or not trusted_requires_reconstruction)
        rejection_reasons: List[str] = []
        if not proved:
            rejection_reasons.append(str(getattr(result.status, "value", result.status)))
        if trusted_requires_reconstruction and not proof_checked:
            rejection_reasons.append("native_reconstruction_not_verified")
        if metadata.get("copy_source_span_rejected") or metadata.get("copied_source_span_rejected"):
            trusted = False
            rejection_reasons.append("source_copy_rejected")

        selected_premises = [premise.name for premise in result.premise_selection.selected]
        premise_views = sorted(
            {
                str(premise.metadata.get("legal_ir_view") or premise.metadata.get("target_component") or "")
                for premise in result.premise_selection.selected
                if str(premise.metadata.get("legal_ir_view") or premise.metadata.get("target_component") or "")
            }
        )
        drafted_candidates = [
            dict(_sanitize_metadata(item))
            for item in (metadata.get("drafted_logic_candidates") or [])
            if isinstance(item, Mapping)
        ]
        payload_for_id = {
            "backend_statuses": _backend_statuses(result.backend_results),
            "goal": result.goal.name,
            "obligation_id": obligation_id,
            "proved": proved,
            "selected_premises": selected_premises,
        }
        return cls(
            guidance_id=str(metadata.get("guidance_id") or f"hammer-guidance-{_stable_hash(payload_for_id)[:16]}"),
            obligation_id=obligation_id,
            trusted=trusted,
            legal_ir_view=legal_ir_view,
            logic_family=logic_family,
            target_component=target_component,
            goal_name=result.goal.name,
            goal_statement_hash=hashlib.sha256(result.goal.statement.encode("utf-8")).hexdigest(),
            proved=proved,
            proof_checked=proof_checked,
            backend_statuses=_backend_statuses(result.backend_results),
            selected_premises=selected_premises,
            premise_views=premise_views,
            reconstruction_status=reconstruction_status,
            winner_backend=str(result.metadata.get("winner_backend") or ""),
            failure_reason="" if proved else str(getattr(result.status, "value", result.status)),
            rejection_reasons=sorted(set(rejection_reasons)),
            proof_obligation_ids=_string_list(metadata.get("proof_obligation_ids") or obligation_id),
            target_metrics=_string_list(metadata.get("target_metrics")),
            drafted_logic_candidates=drafted_candidates,
            metadata=dict(metadata),
        )

    def to_leanstral_guidance_item(self) -> Dict[str, Any]:
        """Return the shape consumed by existing Leanstral autoencoder guidance."""

        payload = self.to_dict()
        payload.update(
            {
                "accepted": bool(self.trusted),
                "proof_checked": bool(self.proof_checked),
                "source": "hammer_verified_guidance",
                "target_component": self.target_component or self.legal_ir_view,
            }
        )
        return payload


def hammer_guidance_artifact_from_result(
    result: HammerResult,
    *,
    candidate_metadata: Optional[Mapping[str, Any]] = None,
    trusted_requires_reconstruction: bool = False,
) -> HammerGuidanceArtifact:
    return HammerGuidanceArtifact.from_hammer_result(
        result,
        candidate_metadata=candidate_metadata,
        trusted_requires_reconstruction=trusted_requires_reconstruction,
    )


__all__ = [
    "HAMMER_GUIDANCE_SCHEMA_VERSION",
    "HammerGuidanceArtifact",
    "hammer_guidance_artifact_from_result",
]
