"""Profile D execution-policy evaluation and proof-statement preparation.

This is the canonical package-export path for MCP++ Profile D callers.  It
accepts either explicit temporal-deontic clauses or natural-language policy
text, delegates text compilation to the existing NL -> DCEC pipeline when it
is available, and returns deterministic policy and decision identifiers.

The returned ``zkp_certificate`` is intentionally a *statement request*, not a
claimed proof.  The current Groth16 circuits do not prove Profile D evaluation,
so callers can hand the public statement to a dedicated circuit without
misrepresenting a digest as zero-knowledge evidence.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import re
from typing import Any, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.ipld_cid import canonical_dag_json, dag_json_cid


PROFILE_D_POLICY_SCHEMA = "mcp++/profile-d-policy@1"
PROFILE_D_ZKP_STATEMENT_SCHEMA = "mcp++/profile-d-policy-zkp-statement@1"
_CLAUSE_TYPES = frozenset({"permission", "prohibition", "obligation"})


class ProfileDPolicyError(ValueError):
    """Raised when a Profile D policy cannot be safely compiled or evaluated."""


@dataclass(frozen=True)
class PolicyClause:
    """Minimal, dependency-free Profile D clause representation.

    This intentionally lives in ``logic`` rather than importing ``mcp_server``:
    importing the server package initializes optional MCP++ integrations and can
    transitively import model runtimes. Policy validation must remain a small,
    hermetic package-export operation for HTTP and libp2p policy gates.
    """

    clause_type: str
    actor: str = "*"
    action: str = "*"
    resource: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    obligation_deadline: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "clause_type": self.clause_type,
            "actor": self.actor,
            "action": self.action,
            "resource": self.resource,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "obligation_deadline": self.obligation_deadline,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PolicyObject:
    """Canonical Profile D policy model used for DAG-JSON addressing."""

    policy_id: str
    clauses: Sequence[PolicyClause]
    version: str = "v1"
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "clauses": [clause.to_dict() for clause in self.clauses],
            "version": self.version,
            "description": self.description,
        }


def evaluate_execution_policy(
    *,
    actor: str,
    action: str,
    resource: str | None = None,
    policy: Mapping[str, Any] | None = None,
    policy_text: str | Sequence[str] | None = None,
    evaluated_at: str | None = None,
    intent_cid: str | None = None,
    request_zkp_certificate: bool = False,
) -> dict[str, Any]:
    """Evaluate whether an execution is permitted by a Profile D policy.

    Exactly one of ``policy`` or ``policy_text`` must be supplied.  Explicit
    policy objects are the portable wire form.  Plain text is compiled through
    the existing DCEC pipeline before the same deterministic evaluator runs.
    """
    if not isinstance(actor, str) or not actor.strip():
        raise ProfileDPolicyError("actor must be a non-empty string")
    if not isinstance(action, str) or not action.strip():
        raise ProfileDPolicyError("action must be a non-empty string")
    if (policy is None) == (policy_text is None):
        raise ProfileDPolicyError("provide exactly one of policy or policy_text")

    if policy is not None:
        policy_object, formal_logic, source = _compile_explicit_policy(policy)
    else:
        policy_object, formal_logic, source = _compile_plain_text_policy(policy_text, actor=actor)

    evaluated = _parse_evaluated_at(evaluated_at)
    policy_artifact = {
        "schema": PROFILE_D_POLICY_SCHEMA,
        "policy": policy_object.to_dict(),
        "formal_logic": formal_logic,
    }
    policy_cid = _cid(policy_artifact)
    decision, normalized_obligations, justification = _evaluate_policy(
        clauses=policy_object.clauses,
        actor=actor.strip(),
        action=action.strip(),
        resource=resource,
        evaluated_at=evaluated,
    )
    allowed = decision != "deny"
    formal_logic_artifact = {"formal_logic": formal_logic}
    formal_logic_cid = _cid(formal_logic_artifact)
    evaluated_at_canonical = evaluated.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    intent_artifact = {
        "schema": "mcp++/profile-d-intent@1",
        "actor": actor.strip(),
        "action": action.strip(),
        "resource": resource,
        "input_cid": intent_cid,
        "policy_cid": policy_cid,
    }
    profile_intent_cid = _cid(intent_artifact)
    decision_artifact = {
        "schema": "mcp++/profile-d-decision@1",
        "decision": decision,
        "allowed": allowed,
        "policy_cid": policy_cid,
        "intent_cid": profile_intent_cid,
        "obligations": normalized_obligations,
        "justification": justification,
        "policy_version": policy_object.version,
        "formal_logic_cid": formal_logic_cid,
        "evaluated_at": evaluated_at_canonical,
    }
    decision_cid = _cid(decision_artifact)
    result = {
        "decision": decision,
        "allowed": allowed,
        "policy_cid": policy_cid,
        "decision_cid": decision_cid,
        "intent_cid": profile_intent_cid,
        "obligations": normalized_obligations,
        "justification": justification,
        "policy_version": policy_object.version,
        "formal_logic": formal_logic,
        "formal_logic_cid": formal_logic_cid,
        "policy_source": source,
        "witness": {
            "schema": PROFILE_D_POLICY_SCHEMA,
            "actor": actor.strip(),
            "action": action.strip(),
            "resource": resource,
            "evaluated_at": evaluated_at_canonical,
        },
    }
    if request_zkp_certificate:
        result["zkp_certificate"] = _zkp_statement(result)
    if _include_artifact_blocks():
        blocks = {
            "policy": _artifact_block(policy_cid, policy_artifact),
            "intent": _artifact_block(profile_intent_cid, intent_artifact),
            "decision": _artifact_block(decision_cid, decision_artifact),
            "formal_logic": _artifact_block(formal_logic_cid, formal_logic_artifact),
        }
        if request_zkp_certificate:
            certificate = result["zkp_certificate"]
            blocks["statement"] = _artifact_block(
                certificate["statement_cid"],
                certificate["public_inputs"],
            )
        # The managed compatibility adapters remove this implementation detail
        # before replying, then persist these exact bytes through Helia.
        result["_artifact_blocks"] = blocks
    return result


def _compile_explicit_policy(policy: Mapping[str, Any]) -> tuple[PolicyObject, list[str], str]:
    raw_clauses = policy.get("clauses")
    if not isinstance(raw_clauses, list) or not raw_clauses:
        raise ProfileDPolicyError("policy.clauses must be a non-empty list")
    clauses = [_normalize_clause(item) for item in raw_clauses]
    policy_id = str(policy.get("policy_id") or "")
    policy_object = PolicyObject(
        policy_id=policy_id,
        clauses=clauses,
        version=str(policy.get("version") or "v1"),
        description=str(policy.get("description") or ""),
    )
    supplied_logic = policy.get("formal_logic")
    if isinstance(supplied_logic, list) and all(isinstance(item, str) for item in supplied_logic):
        formal_logic = list(supplied_logic)
    else:
        formal_logic = [_clause_to_formula(item) for item in clauses]
    return policy_object, formal_logic, "explicit"


def _evaluate_policy(
    *,
    clauses: Sequence[PolicyClause],
    actor: str,
    action: str,
    resource: str | None,
    evaluated_at: datetime,
) -> tuple[str, list[dict[str, Any]], str]:
    """Evaluate Profile D clauses with prohibition precedence, fail-closed."""

    permissions: list[PolicyClause] = []
    prohibitions: list[PolicyClause] = []
    obligations: list[dict[str, Any]] = []
    for clause in clauses:
        if not _clause_applies(clause, actor, action, resource, evaluated_at):
            continue
        if clause.clause_type == "prohibition":
            prohibitions.append(clause)
        elif clause.clause_type == "permission":
            permissions.append(clause)
        elif clause.clause_type == "obligation":
            obligations.append({
                "type": "obligation",
                "action": clause.action,
                "deadline": clause.obligation_deadline or "",
                "metadata": dict(clause.metadata),
            })

    if prohibitions:
        return "deny", [], "; ".join(
            f"Prohibited: actor={actor} action={action}" for _clause in prohibitions
        )
    if permissions and obligations:
        return "allow_with_obligations", obligations, f"Permitted with {len(obligations)} obligation(s)"
    if permissions:
        return "allow", [], f"Explicit permission for actor={actor} action={action}"
    return "deny", [], f"No matching permission for actor={actor} action={action}"


def _clause_applies(
    clause: PolicyClause,
    actor: str,
    action: str,
    resource: str | None,
    evaluated_at: datetime,
) -> bool:
    if not _matches(clause.actor, actor) or not _matches(clause.action, action):
        return False
    if clause.resource is not None and not _matches(clause.resource, resource or ""):
        return False
    valid_from = _parse_timestamp(clause.valid_from)
    valid_until = _parse_timestamp(clause.valid_until)
    return (valid_from is None or evaluated_at >= valid_from) and (
        valid_until is None or evaluated_at <= valid_until
    )


def _matches(pattern: str, value: str) -> bool:
    return pattern == "*" or pattern == value or (
        pattern.endswith("/*") and value.startswith(pattern[:-1])
    )


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProfileDPolicyError("temporal bounds must be ISO-8601 timestamps") from error
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _compile_plain_text_policy(
    policy_text: str | Sequence[str] | None,
    *,
    actor: str,
) -> tuple[PolicyObject, list[str], str]:
    sentences = _sentences(policy_text)
    if not sentences:
        raise ProfileDPolicyError("policy_text must contain at least one non-empty sentence")
    policy_id = _cid({"policy_text": sentences})[:24]
    try:
        from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import compile_nl_to_ucan_policy

        compiled = compile_nl_to_ucan_policy(
            sentences,
            policy_id=policy_id,
            default_actor=actor,
        )
        raw_clauses = list(getattr(compiled.policy_result, "clauses", []) or [])
        clauses = [
            _normalize_clause(
                {
                    "clause_type": getattr(item, "clause_type", None),
                    "actor": getattr(item, "actor", None),
                    "action": getattr(item, "action", None),
                    "resource": getattr(item, "resource", None),
                    "valid_from": getattr(item, "valid_from", None),
                    "valid_until": getattr(item, "valid_until", None),
                    "obligation_deadline": getattr(item, "obligation_deadline", None),
                }
            )
            for item in raw_clauses
        ]
        formulas = [str(item) for item in list(getattr(compiled.policy_result, "dcec_formulas", []) or [])]
        if clauses:
            return PolicyObject(policy_id=policy_id, clauses=clauses), formulas or [_clause_to_formula(item) for item in clauses], "plain_text_dcec"
    except Exception:
        # The fallback remains deterministic and fail-closed when no modal
        # clause can be recognized. It is only a narrow transport fallback.
        pass

    clauses = _fallback_text_clauses(sentences, default_actor=actor)
    if not clauses:
        raise ProfileDPolicyError("plain-text policy did not produce any recognized deontic clauses")
    return PolicyObject(policy_id=policy_id, clauses=clauses), [_clause_to_formula(item) for item in clauses], "plain_text_fallback"


def _normalize_clause(value: Any) -> PolicyClause:
    if not isinstance(value, Mapping):
        raise ProfileDPolicyError("each policy clause must be an object")
    clause_type = str(value.get("clause_type") or value.get("type") or "").strip().lower()
    if clause_type not in _CLAUSE_TYPES:
        raise ProfileDPolicyError(f"unsupported policy clause type: {clause_type or 'missing'}")
    actor = str(value.get("actor") or "*").strip() or "*"
    action = str(value.get("action") or "*").strip() or "*"
    resource = value.get("resource")
    return PolicyClause(
        clause_type=clause_type,
        actor=actor,
        action=action,
        resource=str(resource).strip() if resource is not None and str(resource).strip() else None,
        valid_from=_optional_string(value.get("valid_from") or value.get("not_before")),
        valid_until=_optional_string(value.get("valid_until") or value.get("not_after")),
        obligation_deadline=_optional_string(value.get("obligation_deadline") or value.get("deadline")),
        metadata=dict(value.get("metadata") or {}) if isinstance(value.get("metadata"), Mapping) else {},
    )


def _fallback_text_clauses(sentences: Iterable[str], *, default_actor: str) -> list[PolicyClause]:
    clauses: list[PolicyClause] = []
    for sentence in sentences:
        normalized = sentence.strip().rstrip(".")
        lower = normalized.lower()
        if re.search(r"\b(must not|shall not|may not|forbidden|prohibited)\b", lower):
            clause_type = "prohibition"
        elif re.search(r"\b(must|shall|required to|is required)\b", lower):
            clause_type = "obligation"
        elif re.search(r"\b(may|permitted|allowed|authorized)\b", lower):
            clause_type = "permission"
        else:
            continue
        words = normalized.split()
        clause_actor = words[0].lower() if len(words) > 1 else default_actor
        action_match = re.search(r"\b(?:must not|shall not|may not|must|shall|may|permitted to|allowed to|authorized to|required to)\s+(.+)$", lower)
        action = action_match.group(1).strip() if action_match else "*"
        clauses.append(PolicyClause(clause_type=clause_type, actor=clause_actor, action=action))
    return clauses


def _clause_to_formula(clause: PolicyClause) -> str:
    operator = {"permission": "P", "prohibition": "F", "obligation": "O"}[clause.clause_type]
    resource = clause.resource or "*"
    formula = f"{operator}({clause.actor},{clause.action},{resource})"
    if clause.valid_from or clause.valid_until:
        return f"G[{clause.valid_from or '-inf'},{clause.valid_until or '+inf'}]({formula})"
    if clause.obligation_deadline:
        return f"O_before({formula},{clause.obligation_deadline})"
    return formula


def _parse_evaluated_at(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProfileDPolicyError("evaluated_at must be an ISO-8601 timestamp") from error
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _sentences(value: str | Sequence[str] | None) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[\n.!?]+", value) if item.strip()]
    if isinstance(value, Sequence):
        return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _optional_string(value: Any) -> str | None:
    return str(value).strip() if value is not None and str(value).strip() else None


def _normalize_obligation(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {"type": str(getattr(value, "type", "obligation")), "deadline": getattr(value, "deadline", None)}


def _cid(value: Mapping[str, Any]) -> str:
    return dag_json_cid(value)


def _include_artifact_blocks() -> bool:
    return os.environ.get("MCPPLUSPLUS_PROFILE_D_INCLUDE_ARTIFACT_BLOCKS", "").lower() in {
        "1", "true", "yes", "on"
    }


def _artifact_block(cid: str, value: Mapping[str, Any]) -> dict[str, str]:
    return {
        "cid": cid,
        "bytes_base64": base64.b64encode(canonical_dag_json(value)).decode("ascii"),
    }


def _zkp_statement(result: Mapping[str, Any]) -> dict[str, Any]:
    public_inputs = {
        "policy_cid": result["policy_cid"],
        "decision_cid": result["decision_cid"],
        "intent_cid": result["intent_cid"],
        "formal_logic_cid": result["formal_logic_cid"],
        "decision": result["decision"],
        "allowed": result["allowed"],
    }
    return {
        "schema": PROFILE_D_ZKP_STATEMENT_SCHEMA,
        "status": "statement_ready",
        "zero_knowledge": False,
        "proof": None,
        "reason": "No dedicated Profile D policy-evaluation circuit is registered.",
        "public_inputs": public_inputs,
        "statement_cid": _cid(public_inputs),
    }


__all__ = [
    "PROFILE_D_POLICY_SCHEMA",
    "PROFILE_D_ZKP_STATEMENT_SCHEMA",
    "ProfileDPolicyError",
    "evaluate_execution_policy",
]
