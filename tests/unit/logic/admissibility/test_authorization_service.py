"""Unit tests for IntentAuthorizationService@1 (LIG-035).

Evidence subset:

* offline source-to-decision service
* deterministic replay
* cancellation
* exception
* no-side-effect receipt

Acceptance:

* Validate all inputs/roots/budgets; normalize or accept a canonical envelope;
  lower Intent; hard-filter/select/verify evidence; compose/run native proof
  jobs; select/map decision; build receipt; preserve trace/diagnostics;
  support injected offline dependencies, cancellation and replay; never
  execute content/tools, install backends, mutate corpus, authorize simulated
  evidence in production, derive capability for non-allow, or convert
  exceptions into allow.
"""

from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.logic.admissibility.compose import (
    ActionScope,
    InternalDecisionStatus,
    JobVerdict,
    ProofJob,
)
from ipfs_datasets_py.logic.admissibility.portfolio import (
    PortfolioAttemptRecord,
)
from ipfs_datasets_py.logic.admissibility.reasons import AdmissibilityStatus
from ipfs_datasets_py.logic.admissibility.receipt import (
    CapabilityDerivationError,
    derive_capability,
)
from ipfs_datasets_py.logic.admissibility.service import (
    AUTHORIZATION_BUDGET_SCHEMA_VERSION,
    INTENT_AUTHORIZATION_SERVICE_INTERFACE,
    AuthorizationBudget,
    AuthorizationBudgetError,
    AuthorizationCancelled,
    AuthorizationServiceError,
    AuthorizationServiceResult,
    AuthorizationStage,
    CancellationToken,
    EvidenceSelectionResult,
    IntentAuthorizationService,
    IntentLowerResult,
    OfflineAuthorizationDependencies,
    action_scopes_from_envelope,
    bound_context_from_envelope,
    evaluate_authorization,
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


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_FIXED_CLOCK = "2026-07-28T12:00:00Z"
_LEGAL_CID = "bafylegalgrant01"
_SECURITY_CID = "bafysecurityinv01"
_SIM_CID = "bafysimulatedzkp01"


def _envelope(**overrides: Any) -> InvocationIntentEnvelope:
    base: dict[str, Any] = {
        "envelope_id": "env:auth-svc-1",
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
        "nonce": "nonce-svc-001",
        "created_at": "2026-07-28T12:00:00Z",
        "deadline": "2026-07-28T12:05:00Z",
        "invocation_kind": InvocationKind.SKILLCENTER,
        "policy": PolicyRequirements(
            policy_profile="legal-strict",
            policy_root="policy:root-v1",
            corpus_roots=("corpus:legal-v1", "corpus:security-v1"),
            revocation_root="revocation:root-v1",
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


def _views() -> tuple[NativeViewBinding, ...]:
    return (
        NativeViewBinding(
            view_id="view:fol",
            logic_family="first_order",
            formula_ids=("formula:grant", "formula:forbid"),
            statement_ids=("stmt:grant", "stmt:forbid"),
            capabilities=("capability:write",),
        ),
        NativeViewBinding(
            view_id="view:modal",
            logic_family="modal",
            formula_ids=("formula:modal-grant",),
            statement_ids=("stmt:modal-grant",),
            capabilities=("capability:write",),
        ),
    )


def _cross_links() -> tuple[CrossViewLink, ...]:
    return (
        CrossViewLink(
            link_id="link:fol-modal-grant",
            source_formula_id="formula:grant",
            target_formula_id="formula:modal-grant",
            relation=CrossViewRelation.CORRESPONDS_TO,
            preserved_properties=("permission",),
        ),
    )


def _lower_result(envelope: InvocationIntentEnvelope) -> IntentLowerResult:
    return IntentLowerResult(
        intent_cid="bafyintentformal01",
        intent_document_id=envelope.source.intent_document_id,
        formalization_artifact_id=envelope.source.formalization_artifact_id,
        actions=action_scopes_from_envelope(envelope),
        native_views=_views(),
        cross_view_links=_cross_links(),
        assumptions=("assumption:source-reviewed",),
        diagnostics=("test.lower.ok",),
    )


def _evidence(
    *,
    include_sim: bool = False,
    verification_passed: bool = True,
    gaps: tuple[str, ...] = (),
) -> EvidenceSelectionResult:
    legal = (_LEGAL_CID,)
    security = (_SECURITY_CID,)
    selected = (_LEGAL_CID, _SECURITY_CID)
    simulated: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()
    if include_sim:
        simulated = (_SIM_CID,)
        rejected = (_SIM_CID,)
    return EvidenceSelectionResult(
        legal_evidence_cids=legal,
        security_evidence_cids=security,
        selected_evidence_cids=selected,
        rejected_cids=rejected,
        simulated_rejected=simulated,
        gaps=gaps,
        verification_passed=verification_passed,
        audit_digest="d" * 64,
        diagnostics=("test.evidence.ok",),
    )


def _attempt(
    job: ProofJob,
    backend_id: str,
    verdict: JobVerdict,
    *,
    authority: str = "theorem_proof",
) -> PortfolioAttemptRecord:
    return PortfolioAttemptRecord(
        attempt_id=f"attempt:{job.job_id}:{backend_id}:{verdict.value}",
        job_id=job.job_id,
        backend_id=backend_id,
        status=AttemptStatus.SUCCEEDED,
        verdict=verdict,
        authority_path=authority,
        elapsed_ms=5,
        reason=f"{backend_id}:{verdict.value}",
    )


def _proved_attempts_solver(
    job: ProofJob, backend_id: str, probe: Any
) -> PortfolioAttemptRecord:
    return _attempt(job, backend_id, JobVerdict.PROVED)


def _offline_deps(
    *,
    allow: bool = True,
    include_sim: bool = False,
    raise_in_lower: bool = False,
    evidence_fail: bool = False,
) -> OfflineAuthorizationDependencies:
    def lowerer(envelope: InvocationIntentEnvelope) -> IntentLowerResult:
        if raise_in_lower:
            raise RuntimeError("injected lowerer boom")
        return _lower_result(envelope)

    def selector(
        envelope: InvocationIntentEnvelope,
        *,
        roots: Any,
        budget: Any,
        profile: Any,
        intent: Any,
    ) -> EvidenceSelectionResult:
        if evidence_fail:
            return _evidence(verification_passed=False, gaps=("verify_fail",))
        return _evidence(include_sim=include_sim)

    def which(_name: str) -> str | None:
        # Pretend backends available without installation.
        return f"/fake/bin/{_name}"

    deps = OfflineAuthorizationDependencies(
        intent_lowerer=lowerer,
        evidence_selector=selector,
        which=which,
        clock=lambda: _FIXED_CLOCK,
        portfolio_solver=_proved_attempts_solver if allow else None,
        precomputed_attempts=None if allow else (),
    )
    if not allow:
        # Empty precomputed attempts → unavailable → non-allow.
        deps.precomputed_attempts = ()
        deps.portfolio_solver = None
    return deps


def _run(
    envelope: InvocationIntentEnvelope | None = None,
    *,
    deps: OfflineAuthorizationDependencies | None = None,
    **kwargs: Any,
) -> AuthorizationServiceResult:
    service = IntentAuthorizationService()
    return service.evaluate(
        envelope or _envelope(),
        deps=deps or _offline_deps(),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Budget / roots / inputs
# ---------------------------------------------------------------------------


class TestBudgetAndRoots:
    def test_budget_rejects_side_effect_flags(self) -> None:
        for flag in (
            "allow_network",
            "allow_install",
            "allow_corpus_mutation",
            "allow_tool_execution",
        ):
            budget = AuthorizationBudget(**{flag: True})  # type: ignore[arg-type]
            with pytest.raises(AuthorizationBudgetError, match=flag.split("_")[1]):
                budget.validate_side_effect_flags()

    def test_budget_schema_and_dict_roundtrip(self) -> None:
        budget = AuthorizationBudget(max_candidates=8, selection_budget=2)
        assert budget.schema_version == AUTHORIZATION_BUDGET_SCHEMA_VERSION
        rebuilt = AuthorizationBudget.from_dict(budget.to_dict())
        assert rebuilt.max_candidates == 8
        assert rebuilt.selection_budget == 2
        assert rebuilt.production_mode is True

    def test_missing_policy_root_fails_closed(self) -> None:
        env = _envelope(
            policy=PolicyRequirements(
                policy_profile="legal-strict",
                policy_root="",
                corpus_roots=("corpus:legal-v1",),
                revocation_root="revocation:root-v1",
            )
        )
        result = _run(env, policy_ref="")
        assert result.status is not InternalDecisionStatus.ALLOW
        assert result.wire_status is not AdmissibilityStatus.ALLOW
        assert result.capability is None
        assert any(
            "policy_root" in r or "policy" in r.lower() for r in result.reasons
        ) or any(
            "Root" in result.trace.exception_type
            or "root" in result.trace.exception_message
            for _ in [0]
        )

    def test_missing_corpus_roots_fails_closed(self) -> None:
        env = _envelope(
            policy=PolicyRequirements(
                policy_profile="legal-strict",
                policy_root="policy:root-v1",
                corpus_roots=(),
                revocation_root="revocation:root-v1",
            )
        )
        result = _run(env)
        assert result.status is not InternalDecisionStatus.ALLOW
        assert result.capability is None

    def test_unknown_profile_fails_closed(self) -> None:
        result = _run(profile="not-a-real-profile")
        assert result.status is InternalDecisionStatus.ERROR
        assert result.wire_status is AdmissibilityStatus.ABSTAIN
        assert result.capability is None


# ---------------------------------------------------------------------------
# Envelope normalize / accept / lower / actions
# ---------------------------------------------------------------------------


class TestEnvelopeAndLower:
    def test_accepts_canonical_envelope(self) -> None:
        result = _run()
        assert result.envelope is not None
        assert result.envelope.envelope_id == "env:auth-svc-1"
        assert AuthorizationStage.NORMALIZE.value in result.trace.stages
        assert AuthorizationStage.LOWER.value in result.trace.stages

    def test_normalizer_for_raw_source(self) -> None:
        captured: list[Any] = []

        def normalizer(source: Any) -> InvocationIntentEnvelope:
            captured.append(source)
            return _envelope()

        deps = _offline_deps()
        deps.normalizer = normalizer
        result = IntentAuthorizationService().evaluate(
            {"raw": "hostile skill text that must not execute"},
            deps=deps,
        )
        assert captured == [{"raw": "hostile skill text that must not execute"}]
        assert result.envelope is not None
        # Source text never executed — only passed to normalizer as data.
        assert "auth.service.normalize.accepted" in result.trace.diagnostics

    def test_raw_source_without_normalizer_fails(self) -> None:
        result = IntentAuthorizationService().evaluate(
            object(),
            deps=_offline_deps(),
        )
        assert result.status is InternalDecisionStatus.ERROR
        assert result.is_allow is False

    def test_action_scopes_from_envelope(self) -> None:
        scopes = action_scopes_from_envelope(_envelope())
        assert len(scopes) == 1
        assert scopes[0].action_id == "action:transfer"
        assert scopes[0].effect_id == "effect:ledger-write"
        assert "resource:ledger" in scopes[0].resource_ids

    def test_bound_context_from_envelope(self) -> None:
        env = _envelope()
        ctx = bound_context_from_envelope(env)
        assert ctx.actor_id == "actor:alice"
        assert ctx.audience_id == "audience:dispatcher-1"
        assert ctx.tool_id == "tool:ledger.transfer"
        assert ctx.nonce == "nonce-svc-001"
        assert len(ctx.request_digest) == 64
        assert len(ctx.arguments_digest) == 64


# ---------------------------------------------------------------------------
# Offline source-to-decision (allow / deny paths)
# ---------------------------------------------------------------------------


class TestOfflineSourceToDecision:
    def test_full_offline_allow_path_with_receipt(self) -> None:
        # Portfolio needs proved attempts for every job on each backend.
        # Use a solver that returns PROVED for all.
        deps = _offline_deps(allow=True)
        result = _run(deps=deps)
        assert result.interface == INTENT_AUTHORIZATION_SERVICE_INTERFACE
        assert result.status is InternalDecisionStatus.ALLOW
        assert result.wire_status is AdmissibilityStatus.ALLOW
        assert result.compatibility_status is AdmissibilityStatus.ALLOW
        assert result.decision is not None and result.decision.is_allow
        assert result.receipt is not None
        assert result.receipt.is_allow
        assert result.receipt.producer_id == result.producer_id
        assert result.receipt.roots.policy_root == "policy:root-v1"
        assert "corpus:legal-v1" in result.receipt.roots.corpus_roots
        assert result.receipt.roots.revocation_root == "revocation:root-v1"
        assert result.receipt.actor_id == "actor:alice"
        assert result.receipt.audience_id == "audience:dispatcher-1"
        assert result.receipt.nonce == "nonce-svc-001"
        assert _LEGAL_CID in result.receipt.selected_evidence_cids
        assert result.bundle is not None
        assert result.portfolio_run is not None
        assert result.intent_lower is not None
        assert result.evidence is not None
        # Trace preserves pipeline stages.
        for stage in (
            AuthorizationStage.VALIDATE,
            AuthorizationStage.NORMALIZE,
            AuthorizationStage.LOWER,
            AuthorizationStage.EVIDENCE,
            AuthorizationStage.COMPOSE,
            AuthorizationStage.PORTFOLIO,
            AuthorizationStage.DECIDE,
            AuthorizationStage.RECEIPT,
            AuthorizationStage.COMPLETE,
        ):
            assert stage.value in result.trace.stages

    def test_unavailable_portfolio_cannot_allow(self) -> None:
        deps = _offline_deps(allow=False)
        result = _run(deps=deps)
        assert result.status is not InternalDecisionStatus.ALLOW
        assert result.wire_status is not AdmissibilityStatus.ALLOW
        assert result.capability is None
        if result.receipt is not None:
            assert not result.receipt.permits_capability_derivation

    def test_evidence_verification_failure_indeterminate(self) -> None:
        deps = _offline_deps(evidence_fail=True)
        result = _run(deps=deps)
        assert result.status is InternalDecisionStatus.INDETERMINATE
        assert result.wire_status is AdmissibilityStatus.ABSTAIN
        assert result.capability is None
        assert any("evidence" in r for r in result.reasons)

    def test_explicit_roots_override_envelope(self) -> None:
        result = _run(
            policy_ref="policy:override",
            legal_corpus_ref="corpus:legal-override",
            security_corpus_ref="corpus:security-override",
            intent_corpus_ref="corpus:intent-override",
            revocation_root="revocation:override",
        )
        assert result.roots is not None
        assert result.roots.policy_root == "policy:override"
        assert "corpus:legal-override" in result.roots.corpus_roots
        assert result.roots.revocation_root == "revocation:override"

    def test_module_level_helper(self) -> None:
        result = evaluate_authorization(_envelope(), deps=_offline_deps())
        assert isinstance(result, AuthorizationServiceResult)
        assert result.status is InternalDecisionStatus.ALLOW


# ---------------------------------------------------------------------------
# Simulated evidence / production mode
# ---------------------------------------------------------------------------


class TestSimulatedEvidenceProduction:
    def test_simulated_evidence_not_authoritative_in_production(self) -> None:
        # Provide only simulated evidence as "selected" that gets stripped.
        def selector(*_a: Any, **_k: Any) -> EvidenceSelectionResult:
            return EvidenceSelectionResult(
                legal_evidence_cids=(_SIM_CID,),
                security_evidence_cids=(),
                selected_evidence_cids=(_SIM_CID,),
                simulated_rejected=(_SIM_CID,),
                gaps=("only_simulated",),
                verification_passed=True,
                diagnostics=("sim-only",),
            )

        deps = _offline_deps()
        deps.evidence_selector = selector
        result = IntentAuthorizationService().evaluate(
            _envelope(),
            deps=deps,
            budget=AuthorizationBudget(production_mode=True),
        )
        # After stripping simulated CIDs, selection is empty → coverage gap.
        assert result.status is not InternalDecisionStatus.ALLOW
        assert result.capability is None
        if result.evidence is not None:
            assert _SIM_CID in result.evidence.simulated_rejected
            assert _SIM_CID not in result.evidence.selected_evidence_cids


# ---------------------------------------------------------------------------
# Capability derivation rules
# ---------------------------------------------------------------------------


class TestCapabilityDerivation:
    def test_derive_capability_only_on_allow(self) -> None:
        result = _run(deps=_offline_deps(allow=True), derive_capability_on_allow=True)
        assert result.is_allow
        assert result.capability is not None
        assert result.capability.audience_id == "audience:dispatcher-1"
        result.capability.verify_integrity()

    def test_no_capability_on_non_allow(self) -> None:
        result = _run(
            deps=_offline_deps(allow=False), derive_capability_on_allow=True
        )
        assert not result.is_allow
        assert result.capability is None
        # Manual derivation from non-allow receipt must also fail.
        if result.receipt is not None:
            with pytest.raises(CapabilityDerivationError):
                derive_capability(
                    result.receipt,
                    capability_id="capability:should-fail",
                )

    def test_exception_path_never_derives_capability(self) -> None:
        deps = _offline_deps(raise_in_lower=True)
        result = _run(deps=deps, derive_capability_on_allow=True)
        assert result.status is InternalDecisionStatus.ERROR
        assert result.capability is None
        assert result.is_allow is False


# ---------------------------------------------------------------------------
# Cancellation and exception fail-closed
# ---------------------------------------------------------------------------


class TestCancellationAndExceptions:
    def test_cancellation_never_allows(self) -> None:
        token = CancellationToken()
        token.cancel("test-cancel")
        result = IntentAuthorizationService().evaluate(
            _envelope(),
            deps=_offline_deps(),
            cancellation=token,
        )
        assert result.status is not InternalDecisionStatus.ALLOW
        assert result.wire_status is not AdmissibilityStatus.ALLOW
        assert result.capability is None
        assert result.trace.cancelled is True
        assert any("cancel" in r.lower() for r in result.reasons)

    def test_mid_pipeline_cancellation(self) -> None:
        token = CancellationToken()

        def lowerer(envelope: InvocationIntentEnvelope) -> IntentLowerResult:
            token.cancel("mid-lower")
            token.check("lower")
            return _lower_result(envelope)

        deps = _offline_deps()
        deps.intent_lowerer = lowerer
        result = IntentAuthorizationService().evaluate(
            _envelope(),
            deps=deps,
            cancellation=token,
        )
        assert result.status is InternalDecisionStatus.INDETERMINATE
        assert result.is_allow is False
        assert result.capability is None
        assert result.trace.cancelled is True

    def test_exception_never_converts_to_allow(self) -> None:
        deps = _offline_deps(raise_in_lower=True)
        result = _run(deps=deps)
        assert result.status is InternalDecisionStatus.ERROR
        assert result.wire_status is AdmissibilityStatus.ABSTAIN
        assert result.is_allow is False
        assert result.capability is None
        assert result.trace.exception_type == "RuntimeError"
        assert "boom" in result.trace.exception_message

    def test_cancellation_token_check_raises(self) -> None:
        token = CancellationToken()
        token.cancel("x")
        with pytest.raises(AuthorizationCancelled, match="cancelled"):
            token.check("portfolio")


# ---------------------------------------------------------------------------
# Deterministic replay
# ---------------------------------------------------------------------------


class TestDeterministicReplay:
    def test_replay_same_inputs_same_receipt_identity(self) -> None:
        deps_a = _offline_deps()
        deps_b = _offline_deps()
        env = _envelope()
        a = IntentAuthorizationService().evaluate(env, deps=deps_a)
        b = IntentAuthorizationService().evaluate(env, deps=deps_b)
        assert a.status is InternalDecisionStatus.ALLOW
        assert b.status is InternalDecisionStatus.ALLOW
        assert a.receipt is not None and b.receipt is not None
        assert a.receipt.content_digest == b.receipt.content_digest
        assert a.receipt.content_cid == b.receipt.content_cid
        assert a.context is not None and b.context is not None
        assert a.context.digest == b.context.digest
        assert a.decision is not None and b.decision is not None
        assert a.decision.digest == b.decision.digest

    def test_context_mutation_changes_receipt(self) -> None:
        env_a = _envelope()
        env_b = _envelope(actor=ActorBinding(actor_id="actor:eve"))
        a = _run(env_a)
        b = _run(env_b)
        assert a.receipt is not None and b.receipt is not None
        assert a.receipt.content_digest != b.receipt.content_digest


# ---------------------------------------------------------------------------
# No side effects
# ---------------------------------------------------------------------------


class TestNoSideEffects:
    def test_service_never_requests_install_or_mutation(self) -> None:
        deps = _offline_deps()
        # Side-effect log starts empty; service must not append install/mutate.
        result = _run(deps=deps)
        assert result.is_allow
        forbidden = {
            "install",
            "mutate_corpus",
            "execute_tool",
            "network_fetch",
        }
        for entry in deps.side_effect_log:
            assert entry not in forbidden

    def test_budget_with_install_flag_fails_before_decision(self) -> None:
        result = IntentAuthorizationService().evaluate(
            _envelope(),
            deps=_offline_deps(),
            budget=AuthorizationBudget(allow_install=True),
        )
        assert result.status is InternalDecisionStatus.ERROR
        assert result.is_allow is False
        assert result.capability is None

    def test_budget_with_tool_execution_flag_fails(self) -> None:
        result = IntentAuthorizationService().evaluate(
            _envelope(),
            deps=_offline_deps(),
            budget=AuthorizationBudget(allow_tool_execution=True),
        )
        assert result.is_allow is False
        assert result.status is InternalDecisionStatus.ERROR

    def test_result_to_dict_is_json_ready(self) -> None:
        result = _run()
        payload = result.to_dict()
        assert payload["interface"] == INTENT_AUTHORIZATION_SERVICE_INTERFACE
        assert payload["status"] == "allow"
        assert payload["wire_status"] == "allow"
        assert "receipt" in payload and payload["receipt"] is not None
        assert "trace" in payload


# ---------------------------------------------------------------------------
# Trace / diagnostics preservation
# ---------------------------------------------------------------------------


class TestTraceAndDiagnostics:
    def test_trace_records_diagnostics(self) -> None:
        result = _run()
        assert result.trace.diagnostics
        assert any(
            d.startswith("auth.service.") for d in result.trace.diagnostics
        )
        assert result.trace.elapsed_ms >= 0
        assert result.trace.schema_version

    def test_fail_closed_result_still_has_trace(self) -> None:
        result = _run(deps=_offline_deps(raise_in_lower=True))
        assert AuthorizationStage.ERROR.value in result.trace.stages
        assert result.trace.exception_type
        assert result.receipt is not None or result.decision is not None
        # Even on error we may have a fail-closed receipt with roots/context
        # when those stages completed; lower fails before roots? Actually
        # lower is after roots, so receipt should exist.
        assert result.roots is not None
        assert result.context is not None
        assert result.receipt is not None
        assert result.receipt.outcome is InternalDecisionStatus.ERROR
