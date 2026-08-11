"""Conformance: advisor, solver, Hammer, and proof-kernel authority boundaries (LFP-042).

Acceptance:

* Confidence never proves parse correctness
* Generic success never becomes proof
* Quota / unavailability never becomes logic evidence
* Only official kernel success under pinned imports establishes kernel authority

Interfaces: LogicAuthorityAudit@1
"""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.backends.results import ResultAuthority
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolchainAuthorityCeiling,
    ToolRole,
    can_satisfy_certified_authority_requirement,
    get_tool_role,
)
from ipfs_datasets_py.logic.conformance.authority_audit import (
    DEFAULT_AUTHORITY_AUDIT,
    GOAL_ID,
    LOGIC_AUTHORITY_AUDIT_INTERFACE,
    REASON_CONFIDENCE_NOT_PROOF,
    REASON_GENERIC_SUCCESS_NOT_PROOF,
    REASON_KERNEL_AUTHORITY_ESTABLISHED,
    REASON_KERNEL_REQUIRES_PINNED_IMPORTS,
    REASON_QUOTA_NOT_LOGIC_EVIDENCE,
    REQUIRED_EVIDENCE_SUBSET,
    TASK_ID,
    ActorKind,
    AuditDisposition,
    AuthorityClaim,
    AuthorityVerdict,
    ClaimedAuthority,
    LogicAuthorityAudit,
    audit_claim,
    build_adversarial_claim_corpus,
    classify_actor,
    confidence_never_proves_parse_correctness,
    establishes_kernel_authority,
    generic_success_never_becomes_proof,
    has_pinned_imports,
    is_generic_success_token,
    is_quota_or_unavailability_token,
    matrix_authority_ceiling,
    quota_unavailability_never_logic_evidence,
    run_authority_audit,
)
from ipfs_datasets_py.logic.conformance.matrix import AuthorityCeiling
from ipfs_datasets_py.logic.formalization.proposal_advisors import (
    UNVERIFIED_AUTHORITY,
    confidence_never_yields_proof,
)
from ipfs_datasets_py.logic.parsers.kernel_targets import (
    DEFAULT_ISABELLE_IMPORTS,
    DEFAULT_LEAN_IMPORTS,
    DEFAULT_ROCQ_IMPORTS,
    ProofAuthorityRole,
    RouteSurface,
    is_official_kernel,
    result_authority_for_surface,
    surface_authority_role,
)


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_identity() -> None:
    audit = LogicAuthorityAudit()
    assert audit.interface == LOGIC_AUTHORITY_AUDIT_INTERFACE
    assert audit.interface == "LogicAuthorityAudit@1"
    assert DEFAULT_AUTHORITY_AUDIT.interface == "LogicAuthorityAudit@1"
    assert audit.task_id == TASK_ID == "LFP-042"
    assert audit.goal_id == GOAL_ID == "LFP-G080"
    payload = audit.to_dict()
    assert payload["interface"] == "LogicAuthorityAudit@1"


def test_default_corpus_and_report_are_deterministic() -> None:
    first = run_authority_audit()
    second = LogicAuthorityAudit().audit()
    assert first.digest == second.digest
    assert first.to_json() == second.to_json()
    assert first.interface == LOGIC_AUTHORITY_AUDIT_INTERFACE
    assert first.all_boundaries_hold is True
    assert set(REQUIRED_EVIDENCE_SUBSET) <= set(first.evidence_subset)
    wire = json.loads(first.to_json())
    assert wire["task_id"] == "LFP-042"
    assert wire["summary"]["all_boundaries_hold"] is True


# ---------------------------------------------------------------------------
# Confidence never proves parse correctness
# ---------------------------------------------------------------------------


def test_confidence_never_proves_parse_correctness_invariant() -> None:
    assert (
        confidence_never_proves_parse_correctness(
            confidence=1.0,
            is_valid=True,
            similarity=1.0,
            parse_ok=True,
        )
        is False
    )
    assert confidence_never_yields_proof(confidence=0.99, is_valid=True) is False


def test_symai_high_confidence_cannot_prove_parse_or_theorem() -> None:
    parse_claim = AuthorityClaim(
        claim_id="t.symai.parse",
        provider_id="symbolicai",
        claimed_authority=ClaimedAuthority.PARSE_CORRECT,
        confidence=0.999,
        is_valid=True,
        parse_ok=True,
    )
    theorem_claim = AuthorityClaim(
        claim_id="t.symai.theorem",
        provider_id="symai",
        claimed_authority=ClaimedAuthority.THEOREM,
        confidence=1.0,
        is_valid=True,
        status="success",
    )
    parse_verdict = audit_claim(parse_claim)
    theorem_verdict = audit_claim(theorem_claim)
    assert parse_verdict.disposition is AuditDisposition.REJECT
    assert parse_verdict.establishes_proof is False
    assert parse_verdict.is_logic_evidence is False
    assert REASON_CONFIDENCE_NOT_PROOF in parse_verdict.reason_codes
    assert theorem_verdict.establishes_kernel_authority is False
    assert theorem_verdict.establishes_proof is False
    assert theorem_verdict.max_result_authority is ResultAuthority.CANDIDATE


def test_ergoai_availability_never_kernel_authority() -> None:
    verdict = audit_claim(
        AuthorityClaim(
            claim_id="t.ergoai.avail",
            provider_id="ergoai",
            claimed_authority=ClaimedAuthority.KERNEL,
            available=True,
            present=True,
            status="ok",
        )
    )
    assert verdict.disposition is AuditDisposition.REJECT
    assert verdict.establishes_kernel_authority is False
    assert can_satisfy_certified_authority_requirement("ergoai") is False
    role = get_tool_role("ergoai")
    assert role.role is ToolRole.ADVISOR
    assert role.authority_ceiling is ToolchainAuthorityCeiling.ADVISORY


# ---------------------------------------------------------------------------
# Generic success never becomes proof
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    ["ok", "success", "passed", "complete", "true", "yes"],
)
def test_generic_success_tokens_never_become_proof(token: str) -> None:
    assert is_generic_success_token(token) is True
    assert generic_success_never_becomes_proof(status=token, success=True) is False


def test_z3_generic_success_is_not_kernel_proof() -> None:
    verdict = audit_claim(
        AuthorityClaim(
            claim_id="t.z3.success",
            provider_id="z3",
            claimed_authority=ClaimedAuthority.KERNEL,
            status="success",
            success=True,
        )
    )
    assert verdict.disposition is AuditDisposition.REJECT
    assert verdict.establishes_kernel_authority is False
    assert REASON_GENERIC_SUCCESS_NOT_PROOF in verdict.reason_codes
    assert verdict.max_result_authority is ResultAuthority.SATISFIABILITY


def test_hammer_solver_success_remains_candidate() -> None:
    verdict = audit_claim(
        AuthorityClaim(
            claim_id="t.hammer.proved",
            provider_id="hammer",
            claimed_authority=ClaimedAuthority.THEOREM,
            status="proved",
            success=True,
            attributes={"stage": "premise"},
        )
    )
    assert verdict.establishes_kernel_authority is False
    assert verdict.establishes_proof is False
    assert verdict.max_result_authority is ResultAuthority.CANDIDATE
    assert classify_actor("hammer") is ActorKind.HAMMER
    assert matrix_authority_ceiling("hammer") is AuthorityCeiling.ADVISORY


def test_vampire_proved_is_not_kernel() -> None:
    verdict = audit_claim(
        {
            "claim_id": "t.vampire.proved",
            "provider_id": "vampire",
            "claimed_authority": "kernel",
            "status": "proved",
            "success": True,
        }
    )
    assert verdict.establishes_kernel_authority is False
    assert verdict.disposition is AuditDisposition.REJECT


# ---------------------------------------------------------------------------
# Quota / unavailability never becomes logic evidence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    ["unavailable", "timeout", "quota_exceeded", "rate_limited", "resource_exhausted"],
)
def test_quota_unavailability_tokens_are_not_logic_evidence(status: str) -> None:
    assert is_quota_or_unavailability_token(status) is True
    assert (
        quota_unavailability_never_logic_evidence(status=status, available=False)
        is False
    )


def test_solver_quota_is_inconclusive_not_evidence() -> None:
    verdict = audit_claim(
        AuthorityClaim(
            claim_id="t.cvc5.quota",
            provider_id="cvc5",
            claimed_authority=ClaimedAuthority.SATISFIABILITY,
            status="quota_exceeded",
        )
    )
    assert verdict.disposition is AuditDisposition.INCONCLUSIVE
    assert verdict.is_logic_evidence is False
    assert verdict.establishes_proof is False
    assert REASON_QUOTA_NOT_LOGIC_EVIDENCE in verdict.reason_codes


def test_kernel_unavailability_is_not_logic_evidence() -> None:
    verdict = audit_claim(
        AuthorityClaim(
            claim_id="t.lean.unavail",
            provider_id="lean",
            claimed_authority=ClaimedAuthority.KERNEL,
            status="unavailable",
            available=False,
        )
    )
    assert verdict.disposition is AuditDisposition.INCONCLUSIVE
    assert verdict.is_logic_evidence is False
    assert verdict.establishes_kernel_authority is False


# ---------------------------------------------------------------------------
# Only official kernel success under pinned imports
# ---------------------------------------------------------------------------


def test_official_kernels_are_enumerated() -> None:
    assert is_official_kernel("lean")
    assert is_official_kernel("rocq")
    assert is_official_kernel("isabelle")
    assert classify_actor("lean") is ActorKind.KERNEL
    assert classify_actor("rocq") is ActorKind.KERNEL
    assert classify_actor("isabelle") is ActorKind.KERNEL
    assert surface_authority_role(RouteSurface.KERNEL_NATIVE) is (
        ProofAuthorityRole.OFFICIAL_KERNEL
    )
    assert result_authority_for_surface(RouteSurface.KERNEL_NATIVE) is (
        ResultAuthority.THEOREM
    )
    for surface in (
        RouteSurface.HAMMER_STRATEGY,
        RouteSurface.ATP_CANDIDATE,
        RouteSurface.PROGRAM_SMT,
        RouteSurface.PROTOCOL_PROVERIF,
    ):
        assert surface_authority_role(surface) is not ProofAuthorityRole.OFFICIAL_KERNEL
        assert result_authority_for_surface(surface) is not ResultAuthority.THEOREM


def test_kernel_acceptance_without_pinned_imports_fails() -> None:
    assert has_pinned_imports((), kernel_target="lean") is False
    verdict = audit_claim(
        AuthorityClaim(
            claim_id="t.lean.noimports",
            provider_id="lean",
            claimed_authority=ClaimedAuthority.KERNEL,
            kernel_accepted=True,
            environment_pinned=True,
            environment_id="env:lean:x",
            imports=(),
        )
    )
    assert verdict.disposition is AuditDisposition.REJECT
    assert verdict.establishes_kernel_authority is False
    assert REASON_KERNEL_REQUIRES_PINNED_IMPORTS in verdict.reason_codes
    assert (
        establishes_kernel_authority(
            provider_id="lean",
            kernel_accepted=True,
            imports=(),
            environment_pinned=True,
            environment_id="env:lean:x",
        )
        is False
    )


def test_kernel_acceptance_without_environment_fails() -> None:
    verdict = audit_claim(
        AuthorityClaim(
            claim_id="t.rocq.noenv",
            provider_id="rocq",
            claimed_authority=ClaimedAuthority.THEOREM,
            kernel_accepted=True,
            imports=DEFAULT_ROCQ_IMPORTS,
            environment_pinned=False,
            environment_id="",
        )
    )
    assert verdict.disposition is AuditDisposition.REJECT
    assert verdict.establishes_kernel_authority is False


def test_official_lean_success_under_pinned_imports_establishes_kernel() -> None:
    claim = AuthorityClaim(
        claim_id="t.lean.ok",
        provider_id="lean",
        claimed_authority=ClaimedAuthority.KERNEL,
        kernel_accepted=True,
        imports=DEFAULT_LEAN_IMPORTS,
        environment_pinned=True,
        environment_id="env:lean:pinned",
        trust_escapes_rejected=True,
        status="accepted",
        axioms=("classical",),
    )
    verdict = audit_claim(claim)
    assert verdict.disposition is AuditDisposition.KERNEL
    assert verdict.establishes_kernel_authority is True
    assert verdict.establishes_proof is True
    assert verdict.is_logic_evidence is True
    assert verdict.max_result_authority is ResultAuthority.THEOREM
    assert REASON_KERNEL_AUTHORITY_ESTABLISHED in verdict.reason_codes
    assert (
        establishes_kernel_authority(
            provider_id="lean",
            kernel_accepted=True,
            imports=DEFAULT_LEAN_IMPORTS,
            environment_pinned=True,
            environment_id="env:lean:pinned",
            trust_escapes_rejected=True,
            status="accepted",
            claimed=ClaimedAuthority.KERNEL,
        )
        is True
    )


@pytest.mark.parametrize(
    ("provider_id", "imports"),
    [
        ("lean", DEFAULT_LEAN_IMPORTS),
        ("rocq", DEFAULT_ROCQ_IMPORTS),
        ("isabelle", DEFAULT_ISABELLE_IMPORTS),
    ],
)
def test_each_official_kernel_establishes_authority_when_pinned(
    provider_id: str,
    imports: tuple[str, ...],
) -> None:
    verdict = audit_claim(
        AuthorityClaim(
            claim_id=f"t.{provider_id}.ok",
            provider_id=provider_id,
            claimed_authority=ClaimedAuthority.KERNEL,
            kernel_accepted=True,
            imports=imports,
            environment_id=f"env:{provider_id}:1",
            environment_pinned=True,
            trust_escapes_rejected=True,
            status="accepted",
        )
    )
    assert verdict.establishes_kernel_authority is True
    assert verdict.disposition is AuditDisposition.KERNEL


# ---------------------------------------------------------------------------
# Scoped non-kernel authorities
# ---------------------------------------------------------------------------


def test_solver_satisfiability_is_scoped_not_kernel() -> None:
    verdict = audit_claim(
        AuthorityClaim(
            claim_id="t.z3.sat",
            provider_id="z3",
            claimed_authority=ClaimedAuthority.SATISFIABILITY,
            status="unsat",
        )
    )
    assert verdict.disposition is AuditDisposition.SCOPED
    assert verdict.establishes_kernel_authority is False
    assert verdict.is_logic_evidence is True
    assert verdict.max_result_authority is ResultAuthority.SATISFIABILITY


def test_model_checker_bounded_is_scoped() -> None:
    verdict = audit_claim(
        AuthorityClaim(
            claim_id="t.apalache.bounded",
            provider_id="apalache",
            claimed_authority=ClaimedAuthority.BOUNDED,
            status="satisfied",
        )
    )
    assert verdict.disposition is AuditDisposition.SCOPED
    assert verdict.establishes_kernel_authority is False
    assert verdict.max_result_authority is ResultAuthority.MODEL_CHECK


def test_protocol_and_monitor_are_scoped() -> None:
    protocol = audit_claim(
        AuthorityClaim(
            claim_id="t.tamarin.protocol",
            provider_id="tamarin",
            claimed_authority=ClaimedAuthority.PROTOCOL,
            status="secure",
        )
    )
    monitor = audit_claim(
        AuthorityClaim(
            claim_id="t.mtl.monitor",
            provider_id="runtime_mtl",
            claimed_authority=ClaimedAuthority.MONITOR,
            status="satisfied",
        )
    )
    assert protocol.disposition is AuditDisposition.SCOPED
    assert protocol.max_result_authority is ResultAuthority.PROTOCOL
    assert monitor.disposition is AuditDisposition.SCOPED
    assert monitor.max_result_authority is ResultAuthority.MONITOR
    assert protocol.establishes_kernel_authority is False
    assert monitor.establishes_kernel_authority is False


def test_advisor_candidate_stays_unverified() -> None:
    verdict = audit_claim(
        AuthorityClaim(
            claim_id="t.ergoai.cand",
            provider_id="ergoai",
            claimed_authority=ClaimedAuthority.CANDIDATE,
            confidence=0.4,
        )
    )
    assert verdict.establishes_proof is False
    assert verdict.max_result_authority is ResultAuthority.CANDIDATE
    assert UNVERIFIED_AUTHORITY == "unverified_candidate_only"


# ---------------------------------------------------------------------------
# Full adversarial corpus
# ---------------------------------------------------------------------------


def test_adversarial_corpus_covers_required_actors_and_boundaries() -> None:
    corpus = build_adversarial_claim_corpus()
    providers = {item.provider_id for item in corpus}
    for required in (
        "symbolicai",
        "symai",
        "ergoai",
        "hammer",
        "z3",
        "cvc5",
        "vampire",
        "eprover",
        "tla_tlc",
        "apalache",
        "proverif",
        "tamarin",
        "runtime_mtl",
        "lean",
        "rocq",
        "isabelle",
    ):
        assert required in providers

    report = run_authority_audit(corpus)
    assert report.all_boundaries_hold is True
    summary = report.summary
    assert summary["confidence_never_proves_parse_correctness"] is True
    assert summary["generic_success_never_becomes_proof"] is True
    assert summary["quota_unavailability_never_logic_evidence"] is True
    assert summary["kernel_authority_only_official_under_pinned_imports"] is True
    assert summary["advisor_tools_blocked_from_certified_authority"] is True
    assert summary["kernel_authority_count"] >= 3
    assert summary["non_kernel_surfaces_block_theorem"] is True

    # No non-kernel actor may establish kernel authority in the corpus.
    for claim, verdict in zip(report.claims, report.verdicts):
        if claim.actor_kind is not ActorKind.KERNEL:
            assert verdict.establishes_kernel_authority is False
        if verdict.establishes_kernel_authority:
            assert has_pinned_imports(claim.imports, kernel_target=claim.provider_id)
            assert claim.kernel_accepted is True
            assert claim.environment_id or claim.environment_pinned


def test_verdict_roundtrip_dict_shape() -> None:
    verdict = audit_claim(
        AuthorityClaim(
            claim_id="t.roundtrip",
            provider_id="lean",
            claimed_authority=ClaimedAuthority.KERNEL,
            kernel_accepted=True,
            imports=DEFAULT_LEAN_IMPORTS,
            environment_id="env:lean:rt",
            environment_pinned=True,
            status="accepted",
        )
    )
    payload = verdict.to_dict()
    restored = AuthorityVerdict(
        claim_id=payload["claim_id"],
        provider_id=payload["provider_id"],
        actor_kind=payload["actor_kind"],
        claimed_authority=payload["claimed_authority"],
        disposition=payload["disposition"],
        establishes_kernel_authority=payload["establishes_kernel_authority"],
        establishes_proof=payload["establishes_proof"],
        is_logic_evidence=payload["is_logic_evidence"],
        reason_codes=tuple(payload["reason_codes"]),
        max_result_authority=payload["max_result_authority"],
        notes=payload["notes"],
    )
    assert restored.establishes_kernel_authority is True
    assert restored.to_dict()["disposition"] == "kernel"


def test_actor_classification_matrix() -> None:
    assert classify_actor("symbolicai") is ActorKind.ADVISOR
    assert classify_actor("symai") is ActorKind.ADVISOR
    assert classify_actor("hammer") is ActorKind.HAMMER
    assert classify_actor("z3") is ActorKind.SOLVER
    assert classify_actor("vampire") is ActorKind.ATP
    assert classify_actor("apalache") is ActorKind.MODEL_CHECKER
    assert classify_actor("proverif") is ActorKind.PROTOCOL
    assert classify_actor("runtime_mtl") is ActorKind.MONITOR
    assert matrix_authority_ceiling("symbolicai") is AuthorityCeiling.CANDIDATE
    assert matrix_authority_ceiling("lean") is AuthorityCeiling.KERNEL
    assert matrix_authority_ceiling("z3") is AuthorityCeiling.EXACT
