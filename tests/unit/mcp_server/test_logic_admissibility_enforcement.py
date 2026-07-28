"""Unit tests for MCPIntentAuthorization@1 (LIG-038).

Evidence subset:

* MCP schema
* redaction
* compatibility
* malformed input
* backend unavailable
* no-invocation receipt (handlers never execute / never issue or consume
  dispatch capabilities)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ipfs_datasets_py.logic.admissibility.compose import (
    InternalDecisionStatus,
    JobVerdict,
    ProofJob,
)
from ipfs_datasets_py.logic.admissibility.portfolio import PortfolioAttemptRecord
from ipfs_datasets_py.logic.admissibility.service import (
    EvidenceSelectionResult,
    IntentLowerResult,
    OfflineAuthorizationDependencies,
    action_scopes_from_envelope,
)
from ipfs_datasets_py.logic.formalization.constraint_contracts import (
    NativeViewBinding,
)
from ipfs_datasets_py.logic.formalization.views import (
    CrossViewLink,
    CrossViewRelation,
)
from ipfs_datasets_py.logic.intent_ir.invocation.model import (
    ActorBinding,
    ArgumentCommitment,
    AudienceBinding,
    EnvironmentBinding,
    InvocationIntentEnvelope,
    InvocationKind,
    InvocationScope,
    PolicyRequirements,
    ScopeEntry,
    ScopeKind,
    SourceBinding,
    ToolBinding,
)
from ipfs_datasets_py.logic.ir_core.protocols import AttemptStatus
from ipfs_datasets_py.mcp_server.tools import logic_admissibility_enforcement as tools


_FIXED_CLOCK = "2026-07-28T12:00:00Z"
_LEGAL_CID = "bafylegalgrant01"
_SECURITY_CID = "bafysecurityinv01"
_POLICY = "policy:root-v1"
_CORPUS_LEGAL = "corpus:legal-v1"
_CORPUS_SECURITY = "corpus:security-v1"
_REVOCATION = "revocation:root-v1"


def _envelope(**overrides: Any) -> InvocationIntentEnvelope:
    base: dict[str, Any] = {
        "envelope_id": "env:mcp-auth-1",
        "source": SourceBinding(
            kind=InvocationKind.SKILLCENTER,
            source_ref="skill:ledger-transfer",
            source_revision="rev-1",
            intent_document_id="intent-doc:ledger",
            formalization_artifact_id="formal:ledger-v1",
        ),
        "tenant_id": "tenant:acme",
        "actor": ActorBinding(actor_id="actor:alice"),
        "audience": AudienceBinding(audience_id="audience:dispatcher-1"),
        "tool": ToolBinding(
            tool_id="tool:ledger.transfer", tool_version="1.2.3"
        ),
        "arguments": ArgumentCommitment.from_redacted(
            {"amount": 10, "currency": "USD"}
        ),
        "nonce": "nonce-mcp-001",
        "created_at": "2026-07-28T12:00:00Z",
        "deadline": "2026-07-28T12:05:00Z",
        "invocation_kind": InvocationKind.SKILLCENTER,
        "policy": PolicyRequirements(
            policy_profile="legal-strict",
            policy_root=_POLICY,
            corpus_roots=(_CORPUS_LEGAL, _CORPUS_SECURITY),
            revocation_root=_REVOCATION,
        ),
        "scope": InvocationScope(
            actions=(
                ScopeEntry(
                    entry_id="scope-action-1",
                    kind=ScopeKind.ACTION,
                    value="action:transfer",
                    description="Transfer funds",
                ),
            ),
            effects=(
                ScopeEntry(
                    entry_id="scope-effect-1",
                    kind=ScopeKind.EFFECT,
                    value="effect:ledger-write",
                ),
            ),
            resources=(
                ScopeEntry(
                    entry_id="scope-res-1",
                    kind=ScopeKind.RESOURCE,
                    value="resource:ledger",
                ),
            ),
            capabilities=(
                ScopeEntry(
                    entry_id="scope-cap-1",
                    kind=ScopeKind.CAPABILITY,
                    value="capability:write",
                ),
            ),
        ),
        "environment": EnvironmentBinding(
            environment_id="env:prod-sandbox",
            snapshot_digest="sha256:" + "c" * 64,
        ),
    }
    base.update(overrides)
    return InvocationIntentEnvelope(**base)


def _offline_deps(*, allow: bool = False) -> OfflineAuthorizationDependencies:
    def lowerer(envelope: InvocationIntentEnvelope) -> IntentLowerResult:
        return IntentLowerResult(
            intent_cid="bafyintentformal01",
            intent_document_id=envelope.source.intent_document_id,
            formalization_artifact_id=envelope.source.formalization_artifact_id,
            actions=action_scopes_from_envelope(envelope),
            native_views=(
                NativeViewBinding(
                    view_id="view:fol",
                    logic_family="first_order",
                    formula_ids=("formula:grant",),
                    statement_ids=("stmt:grant",),
                    capabilities=("capability:write",),
                ),
            ),
            cross_view_links=(),
            diagnostics=("test.lower.ok",),
        )

    def selector(
        envelope: InvocationIntentEnvelope,
        *,
        roots: Any,
        budget: Any,
        profile: Any,
        intent: Any,
    ) -> EvidenceSelectionResult:
        return EvidenceSelectionResult(
            legal_evidence_cids=(_LEGAL_CID,),
            security_evidence_cids=(_SECURITY_CID,),
            selected_evidence_cids=(_LEGAL_CID, _SECURITY_CID),
            verification_passed=True,
            audit_digest="d" * 64,
        )

    def which(_name: str) -> str | None:
        return f"/fake/bin/{_name}"

    def solver(
        job: ProofJob, backend_id: str, probe: Any
    ) -> PortfolioAttemptRecord:
        return PortfolioAttemptRecord(
            attempt_id=f"attempt:{job.job_id}:{backend_id}",
            job_id=job.job_id,
            backend_id=backend_id,
            status=AttemptStatus.SUCCEEDED,
            verdict=JobVerdict.PROVED,
            authority_path="theorem_proof",
            elapsed_ms=5,
        )

    return OfflineAuthorizationDependencies(
        intent_lowerer=lowerer,
        evidence_selector=selector,
        which=which,
        clock=lambda: _FIXED_CLOCK,
        portfolio_solver=solver if allow else None,
        precomputed_attempts=() if not allow else None,
    )


def _assert_hardened_flags(payload: MappingLike) -> None:
    assert payload["executed"] is False
    assert payload["capability_issued"] is False
    assert payload["capability_consumed"] is False


def _assert_no_private_leak(payload: Any) -> None:
    text = json.dumps(payload, default=str).lower()
    for token in (
        "skill_md",
        "raw_prompt",
        "private_formula",
        "witness_data",
        "api_key",
        "password",
        "redacted_arguments",
    ):
        assert token not in text, f"leaked {token!r}"


# typing helper alias
MappingLike = dict[str, Any]


# ---------------------------------------------------------------------------
# Schema / discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_schemas_document_all_handlers() -> None:
    assert tools.TOOL_NAMES == (
        "authorize_invocation",
        "verify_authorization_receipt",
        "list_authorization_api_tools",
    )
    assert set(tools.TOOL_SCHEMAS) == set(tools.TOOL_NAMES)
    for name in tools.TOOL_NAMES:
        schema = tools.TOOL_SCHEMAS[name]
        assert schema["name"] == name
        assert schema["interface"] == tools.MCP_INTENT_AUTHORIZATION_INTERFACE


@pytest.mark.asyncio
async def test_forbidden_capability_tools_not_exposed() -> None:
    for banned in tools.FORBIDDEN_TOOL_NAMES:
        assert banned not in tools.TOOL_NAMES
        assert not hasattr(tools, banned) or not callable(
            getattr(tools, banned, None)
        )


@pytest.mark.asyncio
async def test_list_authorization_api_tools_no_execution() -> None:
    result = await tools.list_authorization_api_tools()
    _assert_hardened_flags(result)
    assert result["success"] is True
    assert set(result["tool_names"]) == set(tools.TOOL_NAMES)
    assert "consume_dispatch_capability" in result["forbidden_tool_names"]


@pytest.mark.asyncio
async def test_capabilities_alias() -> None:
    result = await tools.capabilities()
    _assert_hardened_flags(result)
    assert result["success"] is True


# ---------------------------------------------------------------------------
# authorize_invocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorize_missing_invocation_fails_closed() -> None:
    result = await tools.authorize_invocation(
        None,
        policy_ref=_POLICY,
        legal_corpus_ref=_CORPUS_LEGAL,
        revocation_root=_REVOCATION,
    )
    _assert_hardened_flags(result)
    assert result["success"] is False
    assert result["status"] != "allow"
    assert result["wire_status"] != "allow"


@pytest.mark.asyncio
async def test_authorize_missing_policy_fails_closed() -> None:
    result = await tools.authorize_invocation(
        _envelope().to_dict(),
        policy_ref="",
        legal_corpus_ref=_CORPUS_LEGAL,
        revocation_root=_REVOCATION,
    )
    _assert_hardened_flags(result)
    assert result["success"] is False
    assert result["status"] != "allow"
    assert result["error_type"] == "missing_roots"


@pytest.mark.asyncio
async def test_authorize_missing_corpus_fails_closed() -> None:
    result = await tools.authorize_invocation(
        _envelope().to_dict(),
        policy_ref=_POLICY,
        revocation_root=_REVOCATION,
    )
    _assert_hardened_flags(result)
    assert result["success"] is False
    assert result["error_type"] == "missing_roots"


@pytest.mark.asyncio
async def test_authorize_missing_revocation_fails_closed() -> None:
    result = await tools.authorize_invocation(
        _envelope().to_dict(),
        policy_ref=_POLICY,
        legal_corpus_ref=_CORPUS_LEGAL,
        revocation_root="",
    )
    _assert_hardened_flags(result)
    assert result["success"] is False


@pytest.mark.asyncio
async def test_authorize_unknown_fields_fail_closed() -> None:
    result = await tools.authorize_invocation(
        _envelope().to_dict(),
        policy_ref=_POLICY,
        legal_corpus_ref=_CORPUS_LEGAL,
        revocation_root=_REVOCATION,
        derive_capability=True,  # type: ignore[call-arg]
    )
    _assert_hardened_flags(result)
    assert result["success"] is False
    assert result["error_type"] == "malformed_input"
    assert "derive_capability" in result["error"]


@pytest.mark.asyncio
async def test_authorize_malformed_invocation_type_fails_closed() -> None:
    result = await tools.authorize_invocation(
        "not-a-mapping",  # type: ignore[arg-type]
        policy_ref=_POLICY,
        legal_corpus_ref=_CORPUS_LEGAL,
        revocation_root=_REVOCATION,
    )
    _assert_hardened_flags(result)
    assert result["success"] is False
    assert result["status"] != "allow"


@pytest.mark.asyncio
async def test_authorize_invocation_returns_compatibility_shape() -> None:
    """Handlers evaluate via API; offline service may abstain without deps.

    Patch IntentAuthorizationAPI.evaluate to a deterministic non-allow
    redacted result so the MCP contract is asserted without optional solvers.
    """
    from ipfs_datasets_py.logic.admissibility.api import (
        AuthorizationAPIResult,
        RedactedAuthorizationView,
        TypedDecisionRef,
        TypedReceiptRef,
    )
    from ipfs_datasets_py.logic.admissibility.reasons import AdmissibilityStatus

    fake = AuthorizationAPIResult(
        wire_status=AdmissibilityStatus.REJECT,
        internal_status=InternalDecisionStatus.DENY,
        reasons=("denied by fixture",),
        reason_codes=("auth.test.deny",),
        decision_ref=TypedDecisionRef(
            decision_digest="a" * 64,
            status="deny",
            wire_status="reject",
            profile_id="legal-strict",
        ),
        receipt_ref=TypedReceiptRef(
            receipt_id="receipt:fixture-1",
            content_digest="b" * 64,
            wire_status="reject",
            outcome="deny",
            audience_id="audience:dispatcher-1",
            request_digest="c" * 64,
        ),
        view=RedactedAuthorizationView(
            wire_status="reject",
            internal_status="deny",
            reasons=("denied by fixture",),
            reason_codes=("auth.test.deny",),
            profile_id="legal-strict",
        ),
        profile_id="legal-strict",
    )

    with patch.object(
        tools,
        "_load_api",
    ) as load_api:
        api_mod = MagicMock()
        api_mod.redact_mapping = lambda x: x
        instance = MagicMock()
        instance.evaluate.return_value = fake
        api_mod.IntentAuthorizationAPI.return_value = instance
        load_api.return_value = api_mod

        result = await tools.authorize_invocation(
            _envelope().to_dict(),
            policy_ref=_POLICY,
            legal_corpus_ref=_CORPUS_LEGAL,
            security_corpus_ref=_CORPUS_SECURITY,
            revocation_root=_REVOCATION,
        )

    _assert_hardened_flags(result)
    assert result["wire_status"] == "reject"
    assert result["status"] == "reject"
    assert result["success"] is False
    assert result["decision_ref"] is not None
    assert result["receipt_ref"] is not None
    assert result["decision_ref"]["wire_status"] == "reject"
    assert result["receipt_ref"]["receipt_id"] == "receipt:fixture-1"
    _assert_no_private_leak(result)
    # Ensure evaluate was called without capability derivation knobs.
    kwargs = instance.evaluate.call_args.kwargs
    assert "derive_capability_on_allow" not in kwargs


@pytest.mark.asyncio
async def test_authorize_allow_path_still_never_issues_capability() -> None:
    from ipfs_datasets_py.logic.admissibility.api import (
        AuthorizationAPIResult,
        RedactedAuthorizationView,
        TypedDecisionRef,
        TypedReceiptRef,
    )
    from ipfs_datasets_py.logic.admissibility.reasons import AdmissibilityStatus

    fake = AuthorizationAPIResult(
        wire_status=AdmissibilityStatus.ALLOW,
        internal_status=InternalDecisionStatus.ALLOW,
        reasons=("allowed by fixture",),
        decision_ref=TypedDecisionRef(
            decision_digest="a" * 64,
            status="allow",
            wire_status="allow",
        ),
        receipt_ref=TypedReceiptRef(
            receipt_id="receipt:allow-1",
            content_digest="b" * 64,
            wire_status="allow",
            outcome="allow",
        ),
        view=RedactedAuthorizationView(
            wire_status="allow",
            internal_status="allow",
            reasons=("allowed by fixture",),
        ),
    )

    with patch.object(tools, "_load_api") as load_api:
        api_mod = MagicMock()
        api_mod.redact_mapping = lambda x: {
            **x,
            "executed": False,
            "capability_issued": False,
            "capability_consumed": False,
        }
        instance = MagicMock()
        instance.evaluate.return_value = fake
        api_mod.IntentAuthorizationAPI.return_value = instance
        load_api.return_value = api_mod

        result = await tools.authorize_invocation(
            _envelope().to_dict(),
            policy_ref=_POLICY,
            corpus_roots=[_CORPUS_LEGAL],
            revocation_root=_REVOCATION,
        )

    _assert_hardened_flags(result)
    assert result["wire_status"] == "allow"
    assert result["success"] is True
    assert result["capability_issued"] is False
    assert result["capability_consumed"] is False


@pytest.mark.asyncio
async def test_authorize_backend_unavailable_fails_closed() -> None:
    with patch.object(
        tools,
        "_load_api",
        side_effect=RuntimeError("authorization API backend unavailable"),
    ):
        result = await tools.authorize_invocation(
            _envelope().to_dict(),
            policy_ref=_POLICY,
            legal_corpus_ref=_CORPUS_LEGAL,
            revocation_root=_REVOCATION,
        )
    _assert_hardened_flags(result)
    assert result["success"] is False
    assert result["status"] != "allow"
    assert result["error_type"] == "backend_unavailable"


@pytest.mark.asyncio
async def test_authorize_evaluate_exception_fails_closed() -> None:
    with patch.object(tools, "_load_api") as load_api:
        api_mod = MagicMock()
        instance = MagicMock()
        instance.evaluate.side_effect = RuntimeError("boom")
        api_mod.IntentAuthorizationAPI.return_value = instance
        load_api.return_value = api_mod

        result = await tools.authorize_invocation(
            _envelope().to_dict(),
            policy_ref=_POLICY,
            legal_corpus_ref=_CORPUS_LEGAL,
            revocation_root=_REVOCATION,
        )
    _assert_hardened_flags(result)
    assert result["success"] is False
    assert result["status"] != "allow"
    assert result["error_type"] == "backend_unavailable"


@pytest.mark.asyncio
async def test_authorize_never_executes_target() -> None:
    """Hostile source content must not be executed by the handler path."""

    executed = {"ran": False}

    def _boom(*_a: Any, **_k: Any) -> Any:
        executed["ran"] = True
        raise AssertionError("target must not execute")

    hostile = _envelope().to_dict()
    # Plant a lookalike "code" field; handler must ignore/redact, not exec.
    hostile["metadata"] = {"shell": "rm -rf /", "eval": "__import__('os').system"}

    with patch.object(tools, "_load_api") as load_api:
        api_mod = MagicMock()
        api_mod.redact_mapping = lambda x: x
        instance = MagicMock()
        from ipfs_datasets_py.logic.admissibility.api import AuthorizationAPIResult
        from ipfs_datasets_py.logic.admissibility.reasons import AdmissibilityStatus

        instance.evaluate.return_value = AuthorizationAPIResult(
            wire_status=AdmissibilityStatus.ABSTAIN,
            internal_status=InternalDecisionStatus.ERROR,
            reasons=("fixture"),
        )
        api_mod.IntentAuthorizationAPI.return_value = instance
        load_api.return_value = api_mod

        with patch("builtins.exec", _boom), patch("builtins.eval", _boom):
            result = await tools.authorize_invocation(
                hostile,
                policy_ref=_POLICY,
                legal_corpus_ref=_CORPUS_LEGAL,
                revocation_root=_REVOCATION,
            )

    assert executed["ran"] is False
    _assert_hardened_flags(result)
    assert result["executed"] is False


# ---------------------------------------------------------------------------
# verify_authorization_receipt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_missing_receipt_fails_closed() -> None:
    result = await tools.verify_authorization_receipt(None)
    _assert_hardened_flags(result)
    assert result["success"] is False
    assert result["status"] != "allow"


@pytest.mark.asyncio
async def test_verify_unknown_fields_fail_closed() -> None:
    result = await tools.verify_authorization_receipt(
        {"receipt_id": "x"},
        consume_capability=True,  # type: ignore[call-arg]
    )
    _assert_hardened_flags(result)
    assert result["success"] is False
    assert "consume_capability" in result["error"]


@pytest.mark.asyncio
async def test_verify_receipt_success_shape() -> None:
    from ipfs_datasets_py.logic.admissibility.api import (
        AuthorizationAPIResult,
        TypedReceiptRef,
    )
    from ipfs_datasets_py.logic.admissibility.reasons import AdmissibilityStatus

    fake = AuthorizationAPIResult(
        wire_status=AdmissibilityStatus.ALLOW,
        internal_status=InternalDecisionStatus.ALLOW,
        reasons=("verified",),
        receipt_ref=TypedReceiptRef(
            receipt_id="receipt:v1",
            content_digest="d" * 64,
            wire_status="allow",
            outcome="allow",
        ),
    )

    with patch.object(tools, "_load_api") as load_api:
        api_mod = MagicMock()
        api_mod.redact_mapping = lambda x: x
        instance = MagicMock()
        instance.verify_receipt.return_value = fake
        api_mod.IntentAuthorizationAPI.return_value = instance
        load_api.return_value = api_mod

        result = await tools.verify_authorization_receipt(
            {"receipt_id": "receipt:v1"},
            now="2026-07-28T12:01:00Z",
            expected_audience="audience:dispatcher-1",
        )

    _assert_hardened_flags(result)
    assert result["success"] is True
    assert result["wire_status"] == "allow"
    assert result["receipt_ref"]["receipt_id"] == "receipt:v1"
    # verify_receipt must not accept consumption parameters
    assert "consume" not in str(instance.verify_receipt.call_args).lower()


@pytest.mark.asyncio
async def test_verify_receipt_failure_fails_closed() -> None:
    from ipfs_datasets_py.logic.admissibility.api import AuthorizationAPIResult
    from ipfs_datasets_py.logic.admissibility.reasons import AdmissibilityStatus

    fake = AuthorizationAPIResult(
        wire_status=AdmissibilityStatus.ABSTAIN,
        internal_status=InternalDecisionStatus.ERROR,
        reasons=("receipt verification failed: audience mismatch",),
        reason_codes=("auth.api.receipt_verify_failed",),
        receipt_ref=None,
    )

    with patch.object(tools, "_load_api") as load_api:
        api_mod = MagicMock()
        api_mod.redact_mapping = lambda x: x
        instance = MagicMock()
        instance.verify_receipt.return_value = fake
        api_mod.IntentAuthorizationAPI.return_value = instance
        load_api.return_value = api_mod

        result = await tools.verify_authorization_receipt(
            {"receipt_id": "receipt:bad"},
            expected_actor="actor:eve",
        )

    _assert_hardened_flags(result)
    assert result["success"] is False
    assert result["status"] != "allow"
    assert result["error_type"] == "receipt_verify_failed"


@pytest.mark.asyncio
async def test_verify_backend_unavailable_fails_closed() -> None:
    with patch.object(
        tools,
        "_load_api",
        side_effect=RuntimeError("authorization API backend unavailable"),
    ):
        result = await tools.verify_authorization_receipt(
            {"receipt_id": "receipt:x"}
        )
    _assert_hardened_flags(result)
    assert result["success"] is False
    assert result["error_type"] == "backend_unavailable"


# ---------------------------------------------------------------------------
# Fail helper + executed flags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_helper_never_returns_allow() -> None:
    coerced = tools._fail(
        "authorize_invocation",
        status="allow",
        error="should not allow",
    )
    assert coerced["status"] != "allow"
    _assert_hardened_flags(coerced)


@pytest.mark.asyncio
async def test_all_handlers_set_executed_false() -> None:
    responses = [
        await tools.list_authorization_api_tools(),
        await tools.authorize_invocation(None),
        await tools.verify_authorization_receipt(None),
    ]
    for response in responses:
        _assert_hardened_flags(response)
        assert response["interface"] == tools.MCP_INTENT_AUTHORIZATION_INTERFACE
