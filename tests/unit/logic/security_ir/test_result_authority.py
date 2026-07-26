"""Adversarial contracts for Security verification-result authority."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.ir_core.claims import (
    Assumption,
    IRClaim,
    ProofObligation,
    stable_digest,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    AttemptStatus,
    AuthorityKind,
    AuthorityMismatchError,
    BackendAttempt,
    BackendRequest,
    ExecutionBounds,
    QueryKind,
    ResourceUsage,
    ResultAuthority,
    ResultStatus,
    ProofResult as CoreProofResult,
)
from ipfs_datasets_py.logic.security_ir.result_policy import (
    ResultSelectionPolicy,
    SecurityResultAuthority,
    select_portfolio_result,
)
from ipfs_datasets_py.logic.security_ir.results import (
    DisproofResult,
    EvidenceGateResult,
    MonitorResult,
    PolicyDecision,
    ProofResult,
    SatisfiabilityResult,
    SecurityResultFamily,
    SecurityResultValidationError,
    issue_proof_receipt,
    map_legacy_result,
    map_xaman_blocker_satisfiability,
)


def _claim() -> IRClaim:
    return IRClaim(
        claim_id="claim:xaman-signature-authorized",
        declaration_id="security-ir:xaman-testnet",
        statement="Every accepted payload carries an authorized signature.",
        assumptions=(
            Assumption(
                assumption_id="assumption:source-reviewed",
                statement="The tested Xaman source revision was reviewed.",
                source_refs=("source:xaman",),
            ),
        ),
        obligations=(
            ProofObligation(
                obligation_id="obligation:signature",
                statement="An accepted payload implies an authorized signature.",
                assumption_ids=("assumption:source-reviewed",),
                logic_family="first_order",
                source_refs=("source:xaman",),
            ),
        ),
        domain="security",
    )


def _bounds() -> ExecutionBounds:
    return ExecutionBounds(
        timeout_ms=1_000,
        max_steps=10_000,
        max_memory_bytes=2_000_000,
        max_output_bytes=16_384,
    )


def _request(kind: QueryKind, *, backend_id: str = "") -> BackendRequest:
    return BackendRequest.for_claim(
        _claim(),
        "obligation:signature",
        request_id=f"request:{kind.value}",
        query_kind=kind,
        bounds=_bounds(),
        payload={"encoding": "neutral-ast/v1"},
        requested_backend_id=backend_id,
    )


def _attempt(
    request: BackendRequest,
    backend_id: str,
    *,
    output: str = "accepted",
) -> BackendAttempt:
    return BackendAttempt(
        attempt_id=f"attempt:{backend_id}:{output}",
        request_digest=request.digest,
        backend_id=backend_id,
        backend_version="1.0",
        status=AttemptStatus.SUCCEEDED,
        bounds=request.bounds,
        usage=ResourceUsage(
            elapsed_ms=10,
            steps=20,
            peak_memory_bytes=1_024,
            output_bytes=32,
        ),
        output_digest=stable_digest(
            {"backend": backend_id, "output": output, "request": request.digest}
        ),
    )


_RESULT_CLASS = {
    QueryKind.THEOREM_PROOF: ProofResult,
    QueryKind.SATISFIABILITY: SatisfiabilityResult,
    QueryKind.RUNTIME_MONITOR: MonitorResult,
    QueryKind.EVIDENCE_READINESS: EvidenceGateResult,
    QueryKind.POLICY_APPROVAL: PolicyDecision,
}


def _result(
    request: BackendRequest,
    backend_id: str,
    status: ResultStatus,
) -> tuple[BackendAttempt, object]:
    attempt = _attempt(request, backend_id, output=status.value)
    authority = ResultAuthority(
        kind=request.query_kind.authority_kind,
        issuer=f"verifier:{backend_id}",
        method=f"{request.query_kind.value}/v1",
        scope_digest=request.digest,
        configuration_digest=stable_digest({"policy": "test"}),
    )
    result = _RESULT_CLASS[request.query_kind].for_attempt(
        request,
        attempt,
        result_id=f"result:{backend_id}:{status.value}",
        authority=authority,
        status=status,
        payload={"backend_conclusion": status.value},
    )
    return attempt, result


def test_legacy_proof_output_maps_with_explicit_diagnostics() -> None:
    request = _request(QueryKind.THEOREM_PROOF, backend_id="z3")
    attempt = _attempt(request, "z3")
    legacy = {
        "schema_version": "proof-report/v1",
        "claim_id": _claim().claim_id,
        "status": "PROVED",
        "solver_result": "unsat",
    }

    mapping = map_legacy_result(legacy, request=request, attempt=attempt)

    assert mapping.family is SecurityResultFamily.PROOF
    assert isinstance(mapping.result, ProofResult)
    assert mapping.result.status is ResultStatus.PROVED
    assert mapping.diagnostics
    assert mapping.diagnostics[0].code == "security.result.legacy_proof_mapped"
    assert mapping.result.diagnostics == tuple(
        diagnostic.code for diagnostic in mapping.diagnostics
    )
    assert mapping.source_digest == stable_digest(legacy)
    assert type(mapping).from_dict(mapping.to_dict()) == mapping


def test_ambiguous_legacy_output_fails_instead_of_guessing() -> None:
    request = _request(QueryKind.THEOREM_PROOF, backend_id="z3")
    attempt = _attempt(request, "z3")

    with pytest.raises(SecurityResultValidationError, match="ambiguous"):
        map_legacy_result(
            {"schema_version": "unknown-report/v9", "message": "done"},
            request=request,
            attempt=attempt,
        )


def test_contradictory_legacy_proof_signals_fail_closed() -> None:
    request = _request(QueryKind.THEOREM_PROOF, backend_id="z3")
    attempt = _attempt(request, "z3")

    with pytest.raises(SecurityResultValidationError, match="conflicts"):
        map_legacy_result(
            {
                "schema_version": "proof-report/v1",
                "claim_id": _claim().claim_id,
                "status": "PROVED",
                "solver_result": "sat",
            },
            request=request,
            attempt=attempt,
        )


def test_legacy_disproof_is_distinct_and_requires_counterexample() -> None:
    request = _request(QueryKind.THEOREM_PROOF, backend_id="z3")
    attempt = _attempt(request, "z3")
    mapping = map_legacy_result(
        {
            "schema_version": "proof-report/v1",
            "status": "DISPROVED",
            "solver_result": "sat",
            "counterexample": {"payload_id": "forged"},
        },
        request=request,
        attempt=attempt,
    )

    assert mapping.family is SecurityResultFamily.DISPROOF
    assert isinstance(mapping.result, DisproofResult)
    assert not isinstance(mapping.result, ProofResult)
    assert mapping.result.status is ResultStatus.DISPROVED
    with pytest.raises(AuthorityMismatchError, match="cannot construct"):
        issue_proof_receipt(
            _claim(),
            request,
            attempt,
            mapping.result,
            receipt_id="receipt:forged",
            verifier="security-test",
        )

    with pytest.raises(SecurityResultValidationError, match="counterexample"):
        map_legacy_result(
            {
                "schema_version": "proof-report/v1",
                "status": "DISPROVED",
                "solver_result": "sat",
            },
            request=request,
            attempt=attempt,
        )


def test_xaman_blocker_satisfiability_is_an_evidence_gate() -> None:
    request = _request(QueryKind.EVIDENCE_READINESS, backend_id="z3")
    attempt = _attempt(request, "z3", output="sat")
    mapping = map_xaman_blocker_satisfiability(
        {
            "schema_version": "xaman-production-blocker-query/v1",
            "kind": "xaman_blocker_satisfiability",
            "solver_result": "sat",
            "blockers": [{"code": "VENDOR_RUNTIME_EVIDENCE_MISSING"}],
        },
        request=request,
        attempt=attempt,
    )

    assert mapping.family is SecurityResultFamily.EVIDENCE_GATE
    assert isinstance(mapping.result, EvidenceGateResult)
    assert mapping.result.status is ResultStatus.NOT_READY
    assert mapping.result.authority.kind is AuthorityKind.EVIDENCE_READINESS
    assert any(
        item.code == "security.result.xaman_blocker_is_evidence_gate"
        for item in mapping.diagnostics
    )

    proof_request = _request(QueryKind.THEOREM_PROOF, backend_id="z3")
    with pytest.raises(AuthorityMismatchError, match="evidence_readiness request"):
        map_xaman_blocker_satisfiability(
            {
                "kind": "xaman_blocker_satisfiability",
                "solver_result": "unsat",
            },
            request=proof_request,
            attempt=_attempt(proof_request, "z3", output="unsat"),
        )


@pytest.mark.parametrize(
    ("kind", "legacy", "expected_type", "expected_status"),
    [
        (
            QueryKind.RUNTIME_MONITOR,
            {
                "schema_version": "xaman-runtime-trace-report/v1",
                "status": "passed",
            },
            MonitorResult,
            ResultStatus.MONITOR_SATISFIED,
        ),
        (
            QueryKind.POLICY_APPROVAL,
            {
                "schema_version": "security-release-verdict/v1",
                "release_ready": False,
            },
            PolicyDecision,
            ResultStatus.REJECTED,
        ),
        (
            QueryKind.SATISFIABILITY,
            {
                "schema_version": "legacy-solver-output/v1",
                "kind": "satisfiability",
                "solver_result": "sat",
            },
            SatisfiabilityResult,
            ResultStatus.SATISFIABLE,
        ),
    ],
)
def test_other_legacy_families_keep_their_narrow_authority(
    kind: QueryKind,
    legacy: dict[str, object],
    expected_type: type[object],
    expected_status: ResultStatus,
) -> None:
    request = _request(kind, backend_id="legacy-checker")
    mapping = map_legacy_result(
        legacy,
        request=request,
        attempt=_attempt(request, "legacy-checker"),
    )

    assert isinstance(mapping.result, expected_type)
    assert mapping.result.status is expected_status
    assert mapping.result.authority.kind is kind.authority_kind
    assert mapping.diagnostics


@pytest.mark.parametrize(
    ("kind", "status"),
    [
        (QueryKind.SATISFIABILITY, ResultStatus.UNSATISFIABLE),
        (QueryKind.RUNTIME_MONITOR, ResultStatus.MONITOR_SATISFIED),
        (QueryKind.EVIDENCE_READINESS, ResultStatus.READY),
        (QueryKind.POLICY_APPROVAL, ResultStatus.APPROVED),
    ],
)
def test_no_non_proof_result_can_construct_a_proof_receipt(
    kind: QueryKind,
    status: ResultStatus,
) -> None:
    request = _request(kind)
    attempt, result = _result(request, "security-checker", status)

    with pytest.raises(AuthorityMismatchError, match="cannot construct"):
        issue_proof_receipt(
            _claim(),
            request,
            attempt,
            result,
            receipt_id=f"receipt:{kind.value}",
            verifier="security-test",
        )


def test_affirmative_security_proof_can_construct_bound_receipt() -> None:
    request = _request(QueryKind.THEOREM_PROOF, backend_id="z3")
    attempt, result = _result(request, "z3", ResultStatus.PROVED)

    receipt = issue_proof_receipt(
        _claim(),
        request,
        attempt,
        result,
        receipt_id="receipt:signature-proof",
        verifier="security-test",
    )

    assert receipt.status is ResultStatus.PROVED
    assert receipt.result_digest == result.digest
    assert receipt.proof_authority is AuthorityKind.THEOREM_PROOF


def test_backend_registry_core_proof_result_is_accepted_without_relabeling() -> None:
    request = _request(QueryKind.THEOREM_PROOF, backend_id="z3")
    attempt, security_result = _result(request, "z3", ResultStatus.PROVED)
    backend_result = CoreProofResult.from_dict(security_result.to_dict())
    policy = ResultSelectionPolicy(
        policy_id="policy:backend-proof",
        family=SecurityResultFamily.PROOF,
        required_backend_ids=("z3",),
    )

    verdict = select_portfolio_result((backend_result,), policy)
    receipt = issue_proof_receipt(
        _claim(),
        request,
        attempt,
        backend_result,
        receipt_id="receipt:backend-proof",
        verifier="security-test",
    )

    assert verdict.accepted
    assert verdict.status is ResultStatus.PROVED
    assert receipt.result_digest == backend_result.digest


def test_solver_order_cannot_change_consensus_verdict() -> None:
    request = _request(QueryKind.THEOREM_PROOF)
    _, z3 = _result(request, "z3", ResultStatus.PROVED)
    _, cvc5 = _result(request, "cvc5", ResultStatus.PROVED)
    policy = ResultSelectionPolicy(
        policy_id="policy:dual-solver-proof",
        family=SecurityResultFamily.PROOF,
        required_backend_ids=("z3", "cvc5"),
        allowed_backend_ids=("z3", "cvc5"),
    )

    forward = select_portfolio_result((z3, cvc5), policy)
    reverse = SecurityResultAuthority.select((cvc5, z3), policy)
    reversed_policy = ResultSelectionPolicy(
        policy_id="policy:dual-solver-proof",
        family=SecurityResultFamily.PROOF,
        required_backend_ids=("cvc5", "z3"),
        allowed_backend_ids=("cvc5", "z3"),
    )

    assert forward == reverse
    assert policy == reversed_policy
    assert ResultSelectionPolicy.from_dict(policy.to_dict()) == policy
    assert forward == select_portfolio_result((z3, cvc5), reversed_policy)
    assert forward.accepted
    assert forward.status is ResultStatus.PROVED
    assert forward.accepted_result.digest == min(z3.digest, cvc5.digest)
    assert forward.diagnostics == ("security.result.portfolio_consensus",)


def test_solver_disagreement_fails_closed_regardless_of_order() -> None:
    request = _request(QueryKind.THEOREM_PROOF)
    _, proved = _result(request, "z3", ResultStatus.PROVED)
    _, unknown = _result(request, "cvc5", ResultStatus.UNKNOWN)
    policy = ResultSelectionPolicy(
        policy_id="policy:dual-solver-proof",
        family=SecurityResultFamily.PROOF,
        required_backend_ids=("z3", "cvc5"),
    )

    first = select_portfolio_result((proved, unknown), policy)
    second = select_portfolio_result((unknown, proved), policy)

    assert first == second
    assert not first.accepted
    assert first.status is ResultStatus.ERROR
    assert "security.result.portfolio_rejected" in first.diagnostics
    assert any(
        item.startswith("security.result.solver_disagreement:")
        for item in first.diagnostics
    )


def test_duplicate_backend_outputs_cannot_win_by_position() -> None:
    request = _request(QueryKind.THEOREM_PROOF)
    _, proved = _result(request, "z3", ResultStatus.PROVED)
    conflicting = replace(
        proved,
        result_id="result:z3:unknown",
        status=ResultStatus.UNKNOWN,
        output_digest=stable_digest({"backend": "z3", "output": "other"}),
    )
    policy = ResultSelectionPolicy(
        policy_id="policy:one-solver",
        family=SecurityResultFamily.PROOF,
        required_backend_ids=("z3",),
    )

    verdict = select_portfolio_result((conflicting, proved), policy)

    assert not verdict.accepted
    assert verdict.status is ResultStatus.ERROR
    assert "security.result.ambiguous_backend_output:z3" in verdict.diagnostics
