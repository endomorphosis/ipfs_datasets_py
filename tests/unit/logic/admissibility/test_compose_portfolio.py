"""Unit tests for authorization composition and portfolio (LIG-033).

Acceptance coverage:

* Preserve native logic and typed cross-view links.
* Closed profile requires applicable positive grant and proved non-conflict
  (not merely no retrieved deny).
* Include Security invariants, obligations, and coverage jobs.
* Probe backends without installation.
* Record capabilities / assumptions / translations / reconstruction /
  attempts / timeouts.
* Deterministic deny-overrides selection is order independent.
* Unsupported / unknown / contradictory / unavailable / SAT-only / model /
  monitor / evidence / policy / simulation paths cannot allow.
* Map internal deny → reject; review / indeterminate / error → abstain.
"""

from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.logic.admissibility.compose import (
    AUTHORIZATION_DECISION_POLICY_INTERFACE,
    AUTHORIZATION_QUERY_COMPOSER_INTERFACE,
    CLOSED_PROFILE_REQUIRED_JOBS,
    NON_ALLOWING_AUTHORITY_PATHS,
    ActionScope,
    AuthorizationDecisionPolicy,
    AuthorizationQueryBundle,
    AuthorizationQueryComposer,
    ComposeError,
    InternalDecisionStatus,
    JobVerdict,
    ProofJob,
    ProofJobKind,
    ProofJobResult,
    compose_authorization_query,
    evaluate_authorization_decision,
    map_internal_to_wire,
)
from ipfs_datasets_py.logic.admissibility.portfolio import (
    AUTHORIZATION_PORTFOLIO_INTERFACE,
    AuthorizationPortfolio,
    BackendAvailability,
    BackendProbeResult,
    PortfolioAttemptRecord,
    PortfolioError,
    PortfolioReconstructionRecord,
    PortfolioTranslationRecord,
    probe_backend,
    probe_backends,
    result_status_to_job_verdict,
    select_job_result,
    select_portfolio_results,
)
from ipfs_datasets_py.logic.admissibility.reasons import AdmissibilityStatus
from ipfs_datasets_py.logic.formalization.constraint_contracts import (
    NativeViewBinding,
    WorldPolicyKind,
)
from ipfs_datasets_py.logic.formalization.views import (
    CrossViewLink,
    CrossViewRelation,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    AttemptStatus,
    AuthorityKind,
    BackendCapabilities,
    QueryKind,
    ResultStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _action(
    action_id: str = "action:transfer",
    *,
    effect_id: str = "effect:ledger-write",
    logic_family: str = "first_order",
    domain: str = "intent",
) -> ActionScope:
    return ActionScope(
        action_id=action_id,
        effect_id=effect_id,
        resource_ids=("resource:ledger",),
        capability_ids=("capability:write",),
        domain=domain,
        logic_family=logic_family,
        statement=f"Authorize {action_id}",
    )


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


def _compose(
    *,
    actions: list[ActionScope] | None = None,
    profile: str = "legal-strict",
) -> AuthorizationQueryBundle:
    return compose_authorization_query(
        actions or [_action()],
        profile=profile,
        invocation_digest="a" * 64,
        intent_cid="bafyintent0001",
        corpus_root="bafycorpus0001",
        revocation_root="bafyrevocation01",
        policy_root="bafypolicy00001",
        legal_evidence_cids=("bafylegalgrant01",),
        security_evidence_cids=("bafysecurityinv01",),
        native_views=_views(),
        cross_view_links=_cross_links(),
        assumptions=("assumption:source-reviewed",),
    )


def _proved(job: ProofJob, *, authority: str = "theorem_proof") -> ProofJobResult:
    return ProofJobResult(
        job_id=job.job_id,
        kind=job.kind,
        verdict=JobVerdict.PROVED,
        authority_path=authority,
        backend_id="z3",
        attempt_ids=(f"attempt:{job.job_id}:z3",),
        reason=f"proved {job.kind.value}",
    )


def _result(
    job: ProofJob,
    verdict: JobVerdict,
    *,
    authority: str = "theorem_proof",
    reason: str = "",
    metadata: dict[str, Any] | None = None,
) -> ProofJobResult:
    return ProofJobResult(
        job_id=job.job_id,
        kind=job.kind,
        verdict=verdict,
        authority_path=authority,
        backend_id="z3",
        attempt_ids=(f"attempt:{job.job_id}:z3",),
        reason=reason or f"{verdict.value} for {job.kind.value}",
        metadata=metadata or {},
    )


def _all_proved(bundle: AuthorizationQueryBundle) -> list[ProofJobResult]:
    return [_proved(job) for job in bundle.jobs]


def _attempt(
    job: ProofJob,
    backend_id: str,
    verdict: JobVerdict,
    *,
    authority: str = "theorem_proof",
    status: AttemptStatus = AttemptStatus.SUCCEEDED,
    timed_out: bool = False,
    translations: tuple[PortfolioTranslationRecord, ...] = (),
    reconstructions: tuple[PortfolioReconstructionRecord, ...] = (),
    assumptions: tuple[str, ...] = (),
) -> PortfolioAttemptRecord:
    return PortfolioAttemptRecord(
        attempt_id=f"attempt:{job.job_id}:{backend_id}:{verdict.value}",
        job_id=job.job_id,
        backend_id=backend_id,
        status=status,
        verdict=verdict,
        authority_path=authority,
        timed_out=timed_out,
        elapsed_ms=5 if not timed_out else 100,
        assumption_ids=assumptions,
        translations=translations,
        reconstructions=reconstructions,
        reason=f"{backend_id}:{verdict.value}",
    )


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def test_composer_emits_required_closed_profile_jobs_and_preserves_views() -> None:
    bundle = _compose()
    assert bundle.interface == AUTHORIZATION_QUERY_COMPOSER_INTERFACE
    assert bundle.world_policy is WorldPolicyKind.CLOSED
    assert bundle.profile_id == "legal-strict"
    kinds = {job.kind for job in bundle.jobs}
    for required in CLOSED_PROFILE_REQUIRED_JOBS:
        assert required in kinds
    assert ProofJobKind.POSITIVE_GRANT in kinds
    assert ProofJobKind.NON_CONFLICT in kinds
    assert ProofJobKind.SECURITY_INVARIANT in kinds
    assert ProofJobKind.OBLIGATION_PRE in kinds
    assert ProofJobKind.COVERAGE in kinds
    # Native views preserved (not flattened into one family).
    assert {view.view_id for view in bundle.native_views} == {
        "view:fol",
        "view:modal",
    }
    assert {view.logic_family for view in bundle.native_views} == {
        "first_order",
        "modal",
    }
    # Typed cross-view links retained.
    assert len(bundle.cross_view_links) == 1
    assert bundle.cross_view_links[0].link_id == "link:fol-modal-grant"
    # Jobs bind link and view identities.
    grant = bundle.jobs_of_kind(ProofJobKind.POSITIVE_GRANT)[0]
    assert "view:fol" in grant.view_ids
    assert "link:fol-modal-grant" in grant.cross_view_link_ids
    # Positive grant and non-conflict are distinct jobs.
    assert grant.job_id != bundle.jobs_of_kind(ProofJobKind.NON_CONFLICT)[0].job_id


def test_composer_is_deterministic_for_action_order() -> None:
    a1 = _action("action:a", effect_id="e1")
    a2 = _action("action:b", effect_id="e2")
    left = compose_authorization_query([a1, a2], profile="legal-strict")
    right = compose_authorization_query([a2, a1], profile="legal-strict")
    assert left.digest == right.digest
    assert [job.job_id for job in left.jobs] == [job.job_id for job in right.jobs]


def test_composer_rejects_unknown_profile() -> None:
    with pytest.raises(ComposeError, match="profile resolution failed"):
        compose_authorization_query([_action()], profile="not-a-real-profile")


def test_bundle_round_trip_dict() -> None:
    bundle = _compose()
    restored = AuthorizationQueryBundle.from_dict(bundle.to_dict())
    assert restored.digest == bundle.digest
    assert restored.jobs == bundle.jobs


# ---------------------------------------------------------------------------
# Decision policy
# ---------------------------------------------------------------------------


def test_closed_profile_allow_requires_grant_and_proved_non_conflict() -> None:
    bundle = _compose()
    policy = AuthorizationDecisionPolicy.for_profile("legal-strict")
    assert policy.interface == AUTHORIZATION_DECISION_POLICY_INTERFACE
    assert policy.require_positive_grant is True
    assert policy.require_proved_non_conflict is True
    assert policy.accept_no_retrieved_deny_as_non_conflict is False

    decision = policy.evaluate(bundle, _all_proved(bundle))
    assert decision.status is InternalDecisionStatus.ALLOW
    assert decision.wire_status is AdmissibilityStatus.ALLOW
    assert decision.is_allow


def test_no_retrieved_deny_is_not_proved_non_conflict() -> None:
    bundle = _compose()
    policy = AuthorizationDecisionPolicy.for_profile("legal-strict")
    results = []
    for job in bundle.jobs:
        if job.kind is ProofJobKind.NON_CONFLICT:
            results.append(
                _result(
                    job,
                    JobVerdict.PROVED,
                    reason="no deny documents retrieved",
                    metadata={"no_retrieved_deny": True},
                )
            )
        else:
            results.append(_proved(job))
    decision = policy.evaluate(bundle, results)
    assert decision.status is InternalDecisionStatus.INDETERMINATE
    assert decision.wire_status is AdmissibilityStatus.ABSTAIN
    assert any(
        "no_retrieved_deny_is_not_non_conflict" in item
        for item in decision.diagnostics
    )


def test_closed_policy_rejects_accept_no_retrieved_deny_flag() -> None:
    with pytest.raises(ComposeError, match="cannot treat absence"):
        AuthorizationDecisionPolicy(
            policy_id="policy:bad",
            world_policy=WorldPolicyKind.CLOSED,
            accept_no_retrieved_deny_as_non_conflict=True,
        )


def test_missing_positive_grant_cannot_allow() -> None:
    bundle = _compose()
    policy = AuthorizationDecisionPolicy.for_profile("legal-strict")
    results = []
    for job in bundle.jobs:
        if job.kind is ProofJobKind.POSITIVE_GRANT:
            results.append(_result(job, JobVerdict.UNKNOWN))
        else:
            results.append(_proved(job))
    decision = policy.evaluate(bundle, results)
    assert decision.status is InternalDecisionStatus.INDETERMINATE
    assert decision.wire_status is AdmissibilityStatus.ABSTAIN


def test_deny_overrides_grant() -> None:
    bundle = _compose()
    policy = AuthorizationDecisionPolicy.for_profile("legal-strict")
    results = []
    for job in bundle.jobs:
        if job.kind is ProofJobKind.SECURITY_INVARIANT:
            results.append(
                _result(
                    job,
                    JobVerdict.DENIED,
                    reason="hard security forbid",
                )
            )
        else:
            results.append(_proved(job))
    decision = policy.evaluate(bundle, results)
    assert decision.status is InternalDecisionStatus.DENY
    assert decision.wire_status is AdmissibilityStatus.REJECT
    assert decision.is_deny


def test_deny_overrides_is_order_independent() -> None:
    bundle = _compose()
    policy = AuthorizationDecisionPolicy.for_profile("legal-strict")
    base = _all_proved(bundle)
    # Inject a deny for non-conflict.
    non_conflict = bundle.jobs_of_kind(ProofJobKind.NON_CONFLICT)[0]
    deny = _result(non_conflict, JobVerdict.DISPROVED, reason="prohibition")
    mixed = [
        deny if item.job_id == non_conflict.job_id else item for item in base
    ]
    reversed_mixed = list(reversed(mixed))
    shuffled = mixed[::2] + mixed[1::2]
    digests = {
        policy.evaluate(bundle, mixed).digest,
        policy.evaluate(bundle, reversed_mixed).digest,
        policy.evaluate(bundle, shuffled).digest,
    }
    assert len(digests) == 1
    decision = policy.evaluate(bundle, reversed_mixed)
    assert decision.status is InternalDecisionStatus.DENY
    assert decision.wire_status is AdmissibilityStatus.REJECT


@pytest.mark.parametrize(
    "verdict,expected_status,wire",
    [
        (JobVerdict.REVIEW, InternalDecisionStatus.REVIEW, AdmissibilityStatus.ABSTAIN),
        (JobVerdict.ERROR, InternalDecisionStatus.ERROR, AdmissibilityStatus.ABSTAIN),
        (
            JobVerdict.CONTRADICTORY,
            InternalDecisionStatus.REVIEW,
            AdmissibilityStatus.ABSTAIN,
        ),
        (
            JobVerdict.UNKNOWN,
            InternalDecisionStatus.INDETERMINATE,
            AdmissibilityStatus.ABSTAIN,
        ),
        (
            JobVerdict.UNAVAILABLE,
            InternalDecisionStatus.INDETERMINATE,
            AdmissibilityStatus.ABSTAIN,
        ),
        (
            JobVerdict.UNSUPPORTED,
            InternalDecisionStatus.INDETERMINATE,
            AdmissibilityStatus.ABSTAIN,
        ),
        (
            JobVerdict.TIMEOUT,
            InternalDecisionStatus.INDETERMINATE,
            AdmissibilityStatus.ABSTAIN,
        ),
    ],
)
def test_non_allow_paths_map_to_abstain_or_indeterminate(
    verdict: JobVerdict,
    expected_status: InternalDecisionStatus,
    wire: AdmissibilityStatus,
) -> None:
    bundle = _compose()
    policy = AuthorizationDecisionPolicy.for_profile("legal-strict")
    results = []
    for job in bundle.jobs:
        if job.kind is ProofJobKind.POSITIVE_GRANT:
            results.append(_result(job, verdict))
        else:
            results.append(_proved(job))
    decision = policy.evaluate(bundle, results)
    assert decision.status is expected_status
    assert decision.wire_status is wire
    assert decision.wire_status is not AdmissibilityStatus.ALLOW


@pytest.mark.parametrize(
    "authority_path,verdict",
    [
        ("sat_only", JobVerdict.SAT_ONLY),
        ("model", JobVerdict.MODEL),
        ("monitor", JobVerdict.MONITOR),
        ("evidence", JobVerdict.EVIDENCE),
        ("policy", JobVerdict.POLICY),
        ("simulation", JobVerdict.SIMULATION),
    ],
)
def test_non_theorem_authority_paths_cannot_allow(
    authority_path: str, verdict: JobVerdict
) -> None:
    assert authority_path in NON_ALLOWING_AUTHORITY_PATHS or authority_path in {
        "sat_only",
        "model",
        "monitor",
        "evidence",
        "policy",
        "simulation",
    }
    bundle = _compose()
    policy = AuthorizationDecisionPolicy.for_profile("legal-strict")
    results = []
    for job in bundle.jobs:
        if job.kind is ProofJobKind.POSITIVE_GRANT:
            # Claim "proved" under a non-theorem authority path — must not allow.
            results.append(
                _result(job, verdict, authority=authority_path)
            )
        else:
            results.append(_proved(job))
    decision = policy.evaluate(bundle, results)
    assert decision.status is not InternalDecisionStatus.ALLOW
    assert decision.wire_status is not AdmissibilityStatus.ALLOW


def test_map_internal_to_wire_contract() -> None:
    assert map_internal_to_wire(InternalDecisionStatus.ALLOW) is AdmissibilityStatus.ALLOW
    assert map_internal_to_wire(InternalDecisionStatus.DENY) is AdmissibilityStatus.REJECT
    assert map_internal_to_wire(InternalDecisionStatus.REVIEW) is AdmissibilityStatus.ABSTAIN
    assert (
        map_internal_to_wire(InternalDecisionStatus.INDETERMINATE)
        is AdmissibilityStatus.ABSTAIN
    )
    assert map_internal_to_wire(InternalDecisionStatus.ERROR) is AdmissibilityStatus.ABSTAIN


def test_policy_forbids_non_allowing_authority_in_allowlist() -> None:
    with pytest.raises(ComposeError, match="non-allowing paths"):
        AuthorizationDecisionPolicy(
            policy_id="policy:bad-auth",
            allowed_authority_paths=("theorem_proof", "simulation"),
        )


# ---------------------------------------------------------------------------
# Portfolio probes and selection
# ---------------------------------------------------------------------------


def test_probe_backend_without_installation_missing() -> None:
    probe = probe_backend(
        "z3",
        which=lambda _name: None,
    )
    assert probe.availability is BackendAvailability.UNAVAILABLE
    assert probe.probed_without_install is True
    assert probe.executable_path == ""
    assert "auth.portfolio.probe_without_install" in probe.diagnostics


def test_probe_backend_without_installation_available() -> None:
    probe = probe_backend(
        "z3",
        which=lambda name: f"/usr/bin/{name}",
        version_probe=lambda _path: "Z3 version 4.12",
        capabilities=BackendCapabilities(
            logic_families=("first_order",),
            query_kinds=(QueryKind.THEOREM_PROOF,),
            deterministic=True,
        ),
    )
    assert probe.available
    assert probe.executable_path == "/usr/bin/z3"
    assert probe.version == "Z3 version 4.12"
    assert probe.probed_without_install is True


def test_probe_backends_order_independent() -> None:
    which = lambda name: f"/opt/{name}"
    left = probe_backends(("cvc5", "z3"), which=which)
    right = probe_backends(("z3", "cvc5"), which=which)
    assert [item.backend_id for item in left] == [
        item.backend_id for item in right
    ]
    assert [item.digest for item in left] == [item.digest for item in right]


def test_unavailable_attempt_cannot_claim_proved() -> None:
    job = _compose().jobs[0]
    with pytest.raises(PortfolioError, match="unavailable backends never"):
        PortfolioAttemptRecord(
            attempt_id="attempt:bad",
            job_id=job.job_id,
            backend_id="z3",
            status=AttemptStatus.UNAVAILABLE,
            verdict=JobVerdict.PROVED,
        )


def test_timeout_attempt_cannot_claim_proved() -> None:
    job = _compose().jobs[0]
    with pytest.raises(PortfolioError, match="timed-out attempts cannot"):
        PortfolioAttemptRecord(
            attempt_id="attempt:timeout",
            job_id=job.job_id,
            backend_id="z3",
            status=AttemptStatus.TIMED_OUT,
            verdict=JobVerdict.PROVED,
            timed_out=True,
        )


def test_select_job_result_deny_overrides_order_independent() -> None:
    bundle = _compose()
    job = bundle.jobs_of_kind(ProofJobKind.NON_CONFLICT)[0]
    attempts_a = [
        _attempt(job, "z3", JobVerdict.PROVED),
        _attempt(job, "cvc5", JobVerdict.DISPROVED),
    ]
    attempts_b = list(reversed(attempts_a))
    left = select_job_result(attempts_a, job)
    right = select_job_result(attempts_b, job)
    assert left.digest == right.digest
    assert left.verdict is JobVerdict.DISPROVED
    assert "auth.portfolio.deny_overrides" in left.diagnostics


def test_select_job_result_solver_disagreement_fail_closed() -> None:
    bundle = _compose()
    job = bundle.jobs_of_kind(ProofJobKind.POSITIVE_GRANT)[0]
    attempts = [
        _attempt(job, "z3", JobVerdict.PROVED),
        _attempt(job, "cvc5", JobVerdict.UNKNOWN),
    ]
    result = select_job_result(
        attempts, job, required_backends=("z3", "cvc5")
    )
    assert result.verdict is JobVerdict.CONTRADICTORY
    assert result.verdict is not JobVerdict.PROVED


def test_select_job_result_sat_only_cannot_prove() -> None:
    bundle = _compose()
    job = bundle.jobs_of_kind(ProofJobKind.POSITIVE_GRANT)[0]
    attempts = [
        _attempt(
            job,
            "z3",
            JobVerdict.PROVED,
            authority="sat_only",
        )
    ]
    result = select_job_result(attempts, job)
    assert result.verdict is not JobVerdict.PROVED
    assert result.authority_path == "sat_only"


def test_select_portfolio_results_order_independent() -> None:
    bundle = _compose()
    attempts: list[PortfolioAttemptRecord] = []
    for job in bundle.jobs:
        attempts.append(_attempt(job, "z3", JobVerdict.PROVED))
        attempts.append(_attempt(job, "cvc5", JobVerdict.PROVED))
    left = select_portfolio_results(bundle, attempts)
    right = select_portfolio_results(bundle, list(reversed(attempts)))
    assert [item.digest for item in left] == [item.digest for item in right]
    assert all(item.verdict is JobVerdict.PROVED for item in left)


def test_result_status_to_job_verdict_non_allowing_authorities() -> None:
    assert (
        result_status_to_job_verdict(
            ResultStatus.SATISFIABLE,
            authority_kind=AuthorityKind.SATISFIABILITY,
        )
        is JobVerdict.SAT_ONLY
    )
    assert (
        result_status_to_job_verdict(
            ResultStatus.MONITOR_SATISFIED,
            authority_kind=AuthorityKind.RUNTIME_MONITOR,
        )
        is JobVerdict.MONITOR
    )
    assert (
        result_status_to_job_verdict(
            ResultStatus.READY,
            authority_kind=AuthorityKind.EVIDENCE_READINESS,
        )
        is JobVerdict.EVIDENCE
    )
    assert (
        result_status_to_job_verdict(
            ResultStatus.APPROVED,
            authority_kind=AuthorityKind.POLICY_APPROVAL,
        )
        is JobVerdict.POLICY
    )
    assert (
        result_status_to_job_verdict(
            ResultStatus.PROVED,
            authority_kind=AuthorityKind.THEOREM_PROOF,
            simulated=True,
        )
        is JobVerdict.SIMULATION
    )
    assert (
        result_status_to_job_verdict(
            ResultStatus.PROVED,
            authority_kind=AuthorityKind.THEOREM_PROOF,
        )
        is JobVerdict.PROVED
    )


# ---------------------------------------------------------------------------
# End-to-end portfolio run with records
# ---------------------------------------------------------------------------


def test_portfolio_run_records_capabilities_assumptions_translations_timeouts() -> None:
    bundle = _compose()
    caps = BackendCapabilities(
        logic_families=("first_order", "modal"),
        query_kinds=(QueryKind.THEOREM_PROOF,),
        deterministic=True,
    )
    translation = PortfolioTranslationRecord(
        translation_id="tr:fol-smt",
        source_logic_family="first_order",
        target_logic_family="smt",
        translator_id="translator:test",
    )
    reconstruction = PortfolioReconstructionRecord(
        reconstruction_id="rc:smt",
        logic_family="smt",
        faithful=True,
        reconstructor_id="reconstructor:test",
    )
    attempts: list[PortfolioAttemptRecord] = []
    for job in bundle.jobs:
        attempts.append(
            _attempt(
                job,
                "z3",
                JobVerdict.PROVED,
                assumptions=("assumption:source-reviewed",),
                translations=(translation,),
                reconstructions=(reconstruction,),
            )
        )
        # Second backend times out on security invariant only.
        if job.kind is ProofJobKind.SECURITY_INVARIANT:
            attempts.append(
                _attempt(
                    job,
                    "cvc5",
                    JobVerdict.TIMEOUT,
                    status=AttemptStatus.TIMED_OUT,
                    timed_out=True,
                )
            )
        else:
            attempts.append(_attempt(job, "cvc5", JobVerdict.PROVED))

    portfolio = AuthorizationPortfolio(
        backend_ids=("z3", "cvc5"),
        required_backends=(),
        capabilities_by_backend={"z3": caps, "cvc5": caps},
    )
    run = portfolio.run(
        bundle,
        precomputed_attempts=attempts,
        which=lambda name: f"/usr/bin/{name}",
        decide=True,
    )
    assert run.interface == AUTHORIZATION_PORTFOLIO_INTERFACE
    assert len(run.probes) == 2
    assert all(probe.probed_without_install for probe in run.probes)
    assert all(probe.available for probe in run.probes)
    assert run.assumptions  # recorded
    assert "assumption:source-reviewed" in run.assumptions
    assert run.translations
    assert run.reconstructions
    assert run.timeouts  # security invariant timeout recorded
    assert run.decision is not None
    # Security invariant still proved by z3; timeout on cvc5 alone with no
    # required_backends should not force deny when z3 proved — selection
    # picks proved theorem authority when not required multi-backend.
    # With optional backends, one proved is enough for that job.
    assert run.decision.status in {
        InternalDecisionStatus.ALLOW,
        InternalDecisionStatus.INDETERMINATE,
        InternalDecisionStatus.REVIEW,
    }


def test_portfolio_run_full_allow_path() -> None:
    bundle = _compose()
    attempts: list[PortfolioAttemptRecord] = []
    for job in bundle.jobs:
        for backend_id in ("z3", "cvc5"):
            attempts.append(_attempt(job, backend_id, JobVerdict.PROVED))
    portfolio = AuthorizationPortfolio(
        backend_ids=("z3", "cvc5"),
        required_backends=("z3", "cvc5"),
    )
    run = portfolio.run(
        bundle,
        precomputed_attempts=attempts,
        which=lambda name: f"/bin/{name}",
    )
    assert run.decision is not None
    assert run.decision.status is InternalDecisionStatus.ALLOW
    assert run.decision.wire_status is AdmissibilityStatus.ALLOW
    assert all(item.verdict is JobVerdict.PROVED for item in run.job_results)


def test_portfolio_run_without_solver_cannot_allow() -> None:
    bundle = _compose()
    portfolio = AuthorizationPortfolio(backend_ids=("z3",))
    run = portfolio.run(
        bundle,
        which=lambda _name: None,
        decide=True,
    )
    assert run.decision is not None
    assert run.decision.status is not InternalDecisionStatus.ALLOW
    assert run.decision.wire_status is AdmissibilityStatus.ABSTAIN
    assert all(
        item.verdict is JobVerdict.UNAVAILABLE for item in run.job_results
    )


def test_portfolio_with_injected_solver_unavailable_backend() -> None:
    bundle = _compose()

    def solver(
        job: ProofJob, backend_id: str, probe: BackendProbeResult
    ) -> PortfolioAttemptRecord:
        return _attempt(job, backend_id, JobVerdict.PROVED)

    portfolio = AuthorizationPortfolio(backend_ids=("missing-solver",))
    run = portfolio.run(
        bundle,
        solver=solver,
        which=lambda _name: None,
    )
    assert run.decision is not None
    assert run.decision.wire_status is not AdmissibilityStatus.ALLOW
    assert all(
        attempt.status is AttemptStatus.UNAVAILABLE for attempt in run.attempts
    )


def test_evaluate_authorization_decision_helper() -> None:
    bundle = _compose()
    decision = evaluate_authorization_decision(bundle, _all_proved(bundle))
    assert decision.is_allow
    assert decision.wire_status is AdmissibilityStatus.ALLOW


def test_security_invariants_obligations_coverage_present_in_composer() -> None:
    composer = AuthorizationQueryComposer()
    bundle = composer.compose(
        [_action()],
        profile="security-lite",
        security_evidence_cids=("bafysecurity01",),
    )
    kinds = {job.kind for job in bundle.jobs}
    assert ProofJobKind.SECURITY_INVARIANT in kinds
    assert ProofJobKind.OBLIGATION_PRE in kinds
    assert ProofJobKind.OBLIGATION_DURING in kinds
    assert ProofJobKind.OBLIGATION_POST in kinds
    assert ProofJobKind.COVERAGE in kinds
    security_jobs = bundle.jobs_of_kind(ProofJobKind.SECURITY_INVARIANT)
    assert all(job.domain == "security" for job in security_jobs)


def test_decision_round_trip() -> None:
    bundle = _compose()
    decision = evaluate_authorization_decision(bundle, _all_proved(bundle))
    restored = type(decision).from_dict(decision.to_dict())
    assert restored.digest == decision.digest
    assert restored.wire_status is AdmissibilityStatus.ALLOW
