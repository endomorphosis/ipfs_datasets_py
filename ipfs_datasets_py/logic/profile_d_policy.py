"""Canonical Profile-D policy evaluator export.

This module is the stable import used by MCP++ transports:
``ipfs_datasets_py.logic.profile_d_policy.evaluate_execution_policy``.
It delegates policy semantics to the datasets MCP temporal policy engine and
adds the transport-facing artifacts expected by ipfs_accelerate_py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject, artifact_cid
from ipfs_datasets_py.mcp_server.temporal_policy import PolicyClause, PolicyEvaluator, PolicyObject


def _parse_iso8601(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_clauses(policy: Dict[str, Any] | None, policy_text: str | List[str] | None) -> list[dict[str, Any]]:
    if isinstance(policy, dict):
        raw_clauses = policy.get("clauses")
        if isinstance(raw_clauses, list):
            return [dict(item) for item in raw_clauses if isinstance(item, dict)]

    # Minimal deterministic fallback for text-only callers. Natural-language
    # compilation can be layered here, but the transport contract should remain
    # usable when only policy text is present.
    if policy_text:
        return [{"clause_type": "permission", "actor": "*", "action": "*"}]
    return []


def _policy_object(clauses: Iterable[dict[str, Any]]) -> PolicyObject:
    parsed: list[PolicyClause] = []
    for item in clauses:
        parsed.append(
            PolicyClause(
                clause_type=str(item.get("clause_type") or "").strip().lower(),
                actor=str(item.get("actor") or "*").strip() or "*",
                action=str(item.get("action") or "*").strip() or "*",
                resource=(str(item.get("resource") or "").strip() or None)
                if item.get("resource") is not None
                else None,
                valid_from=str(item.get("valid_from") or "").strip() or None,
                valid_until=str(item.get("valid_until") or "").strip() or None,
                obligation_deadline=str(item.get("obligation_deadline") or "").strip() or None,
                metadata=dict(item.get("metadata") or {}) if isinstance(item.get("metadata"), dict) else {},
            )
        )
    return PolicyObject(policy_id="profile-d-policy", clauses=parsed, version="v1")


def _formal_logic_record(
    *,
    clauses: list[dict[str, Any]],
    actor: str,
    action: str,
    resource: str | None,
    decision: str,
) -> dict[str, Any]:
    formulas: list[dict[str, Any]] = []
    for index, clause in enumerate(clauses):
        clause_type = str(clause.get("clause_type") or "").strip().lower()
        formulas.append(
            {
                "formula_id": f"profile_d_clause_{index + 1}",
                "logic": "temporal_deontic",
                "operator": clause_type,
                "actor": str(clause.get("actor") or "*"),
                "action": str(clause.get("action") or "*"),
                "resource": clause.get("resource"),
                "valid_from": clause.get("valid_from"),
                "valid_until": clause.get("valid_until"),
                "obligation_deadline": clause.get("obligation_deadline"),
            }
        )
    return {
        "profile": "mcp++/deontic-policy",
        "logic_system": "temporal_deontic_policy",
        "query": {
            "actor": actor,
            "action": action,
            "resource": resource,
        },
        "decision": decision,
        "formulas": formulas,
    }


def _zkp_statement(
    *,
    decision_cid: str,
    policy_cid: str,
    formal_logic_cid: str,
    requested: bool,
) -> dict[str, Any]:
    return {
        "status": "statement_ready" if requested else "not_requested",
        "zero_knowledge": False,
        "statement": {
            "decision_cid": decision_cid,
            "policy_cid": policy_cid,
            "formal_logic_cid": formal_logic_cid,
        },
    }


def _normalize_obligations(obligations: Iterable[Any], *, now: datetime | None) -> list[dict[str, Any]]:
    eval_time = now or datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for item in obligations:
        if isinstance(item, dict):
            row = dict(item)
        else:
            row = {
                "type": str(getattr(item, "type", "") or ""),
                "deadline": getattr(item, "deadline", None),
                "details": getattr(item, "details", None),
            }
        if not row.get("status"):
            deadline = _parse_iso8601(str(row.get("deadline") or ""))
            row["status"] = "overdue" if deadline is not None and eval_time > deadline else "pending"
        out.append(row)
    return out


def evaluate_execution_policy(
    *,
    actor: str,
    action: str,
    resource: str | None = None,
    policy: Dict[str, Any] | None = None,
    policy_text: str | List[str] | None = None,
    evaluated_at: str | None = None,
    intent_cid: str | None = None,
    request_zkp_certificate: bool = False,
) -> Dict[str, Any]:
    """Evaluate a Profile-D policy and return transport-ready artifacts."""

    actor_text = str(actor or "")
    action_text = str(action or "")
    resource_text = str(resource).strip() if resource is not None else None
    clauses = _normalize_clauses(policy, policy_text)
    policy_obj = _policy_object(clauses)

    intent = IntentObject(
        tool=action_text,
        input_cid=artifact_cid({"actor": actor_text, "action": action_text, "resource": resource_text}),
        constraints_policy_cid=policy_obj.policy_cid,
    )
    if intent_cid:
        intent._cid = str(intent_cid)
    else:
        intent_cid = intent.cid
    eval_time = _parse_iso8601(evaluated_at)

    decision = PolicyEvaluator().evaluate(
        intent,
        policy_obj,
        actor=actor_text,
        resource=resource_text,
        now=eval_time,
        proofs_checked=[policy_obj.policy_cid],
        evaluator_did="did:ipfs-datasets:profile-d",
    )
    out = decision.to_dict()
    out["intent_cid"] = str(intent_cid)
    out["policy_cid"] = policy_obj.policy_cid
    out["policy"] = policy_obj.to_dict()
    out["obligations"] = _normalize_obligations(decision.obligations, now=eval_time)

    formal_logic = _formal_logic_record(
        clauses=clauses,
        actor=actor_text,
        action=action_text,
        resource=resource_text,
        decision=str(out.get("decision") or ""),
    )
    formal_logic_cid = artifact_cid(formal_logic)
    out["formal_logic"] = formal_logic
    out["formal_logic_cid"] = formal_logic_cid
    out["zkp_certificate"] = _zkp_statement(
        decision_cid=str(out.get("decision_cid") or ""),
        policy_cid=str(out.get("policy_cid") or ""),
        formal_logic_cid=str(formal_logic_cid),
        requested=bool(request_zkp_certificate),
    )
    return out


__all__ = ["evaluate_execution_policy"]
