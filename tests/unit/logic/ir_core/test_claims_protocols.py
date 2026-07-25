"""Contracts for solver-neutral claims and exact, non-transferable authority."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from ipfs_datasets_py.logic.ir_core.claims import (
    Assumption,
    ClaimValidationError,
    FrozenMap,
    IRClaim,
    ProofObligation,
    stable_digest,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    AttemptStatus,
    AuthorityKind,
    AuthorityMismatchError,
    BackendAttempt,
    BackendCapabilities,
    BackendRequest,
    BoundedResult,
    EvidenceGateResult,
    ExecutionBounds,
    MonitorResult,
    PolicyDecision,
    ProofBackend,
    ProofReceipt,
    ProofResult,
    ProtocolValidationError,
    QueryKind,
    ResourceUsage,
    ResultAuthority,
    ResultReceipt,
    ResultStatus,
    SatisfiabilityResult,
)


def _claim() -> IRClaim:
    return IRClaim(
        claim_id="claim:no-unauthorized-withdrawal",
        declaration_id="security-ir:exchange-v1",
        statement="Every broadcast withdrawal has a prior authorization.",
        assumptions=(
            Assumption(
                assumption_id="assumption:event-log-complete",
                statement="The bounded event log is complete for the run.",
                source_refs=("artifact:event-log",),
                metadata={"review": {"status": "accepted"}},
            ),
        ),
        obligations=(
            ProofObligation(
                obligation_id="obligation:authorization",
                statement=(
                    "For every broadcast in the bounded model, an authorization "
                    "precedes it."
                ),
                assumption_ids=("assumption:event-log-complete",),
                logic_family="first_order_temporal",
                source_refs=("source:withdrawal-policy",),
            ),
        ),
        domain="security",
        metadata={"labels": ["blocking", "withdrawal"]},
    )


def _bounds() -> ExecutionBounds:
    return ExecutionBounds(
        timeout_ms=1_000,
        max_steps=1_000,
        max_memory_bytes=1_000_000,
        max_output_bytes=4_096,
    )


def _request(query_kind: QueryKind = QueryKind.THEOREM_PROOF) -> BackendRequest:
    return BackendRequest.for_claim(
        _claim(),
        "obligation:authorization",
        request_id=f"request:{query_kind.value}",
        query_kind=query_kind,
        bounds=_bounds(),
        payload={"encoding": "neutral-ast/v1"},
        requested_backend_id="fake-backend",
    )


def _output_digest(query_kind: QueryKind) -> str:
    return stable_digest({"backend-output": query_kind.value})


def _attempt(request: BackendRequest) -> BackendAttempt:
    return BackendAttempt(
        attempt_id=f"attempt:{request.query_kind.value}",
        request_digest=request.digest,
        backend_id="fake-backend",
        backend_version="1.0",
        status=AttemptStatus.SUCCEEDED,
        bounds=request.bounds,
        usage=ResourceUsage(
            elapsed_ms=10,
            steps=12,
            peak_memory_bytes=1_024,
            output_bytes=40,
        ),
        output_digest=_output_digest(request.query_kind),
    )


_RESULT_CLASS = {
    QueryKind.THEOREM_PROOF: ProofResult,
    QueryKind.SATISFIABILITY: SatisfiabilityResult,
    QueryKind.RUNTIME_MONITOR: MonitorResult,
    QueryKind.EVIDENCE_READINESS: EvidenceGateResult,
    QueryKind.POLICY_APPROVAL: PolicyDecision,
}


def _result(
    query_kind: QueryKind,
    status: ResultStatus,
) -> tuple[BackendRequest, BackendAttempt, BoundedResult]:
    request = _request(query_kind)
    attempt = _attempt(request)
    authority = ResultAuthority(
        kind=query_kind.authority_kind,
        issuer="fake-verifier",
        method=f"{query_kind.value}/v1",
        scope_digest=request.digest,
        configuration_digest=stable_digest({"policy": query_kind.value}),
    )
    result_class = _RESULT_CLASS[query_kind]
    result = result_class.for_attempt(
        request,
        attempt,
        result_id=f"result:{query_kind.value}",
        authority=authority,
        status=status,
        payload={"bounded": True},
    )
    return request, attempt, result


def test_claim_is_recursively_immutable_and_identity_excludes_runtime_state() -> None:
    caller_metadata = {"labels": ["blocking"], "review": {"status": "accepted"}}
    claim = replace(_claim(), metadata=caller_metadata)
    equivalent = IRClaim.from_dict(claim.to_dict())

    caller_metadata["labels"].append("mutated")
    caller_metadata["review"]["status"] = "rejected"
    assert equivalent == claim
    assert equivalent.digest == claim.digest
    assert claim.metadata["labels"] == ("blocking",)
    assert isinstance(claim.metadata["review"], FrozenMap)

    with pytest.raises(FrozenInstanceError):
        claim.statement = "mutated"  # type: ignore[misc]
    with pytest.raises(TypeError):
        claim.metadata["new"] = "value"  # type: ignore[index]
    detached = claim.to_dict()
    detached["metadata"]["labels"].append("mutated")
    assert claim.metadata["labels"] == ("blocking",)


def test_claim_rejects_unknown_assumptions_duplicate_ids_and_unknown_fields() -> None:
    with pytest.raises(ClaimValidationError, match="unknown assumptions"):
        IRClaim(
            claim_id="claim:bad",
            statement="Bad claim.",
            assumptions=(),
            obligations=(
                ProofObligation(
                    obligation_id="obligation:bad",
                    statement="Bad target.",
                    assumption_ids=("assumption:missing",),
                ),
            ),
        )

    assumption = Assumption("assumption:duplicate", "Premise.")
    with pytest.raises(ClaimValidationError, match="assumption IDs must be unique"):
        IRClaim(
            claim_id="claim:duplicate",
            statement="Duplicate premise IDs.",
            assumptions=(assumption, assumption),
            obligations=(ProofObligation("obligation:target", "Target."),),
        )

    payload = _claim().to_dict()
    payload["runtime_verdict"] = "PROVED"
    with pytest.raises(ClaimValidationError, match="unknown claim field"):
        IRClaim.from_dict(payload)


def test_backend_request_and_attempt_bind_declaration_obligation_and_bounds() -> None:
    claim = _claim()
    request = _request()
    attempt = _attempt(request)

    assert request.claim_digest == claim.digest
    assert request.declaration_id == claim.declaration_id
    assert request.obligation_digest == claim.obligations[0].digest
    assert request.assumption_ids == ("assumption:event-log-complete",)
    assert attempt.request_digest == request.digest
    assert BackendRequest.from_dict(request.to_dict()) == request
    assert BackendAttempt.from_dict(attempt.to_dict()) == attempt

    with pytest.raises(ProtocolValidationError, match="cannot exceed bounds"):
        replace(
            attempt,
            usage=replace(attempt.usage, elapsed_ms=request.bounds.timeout_ms + 1),
        )

    with pytest.raises(ProtocolValidationError, match="output_digest"):
        replace(attempt, output_digest="")


def test_failed_and_unavailable_attempts_are_still_complete_records() -> None:
    request = _request()
    failed = BackendAttempt(
        attempt_id="attempt:failed",
        request_digest=request.digest,
        backend_id="fake-backend",
        backend_version="1.0",
        status=AttemptStatus.UNAVAILABLE,
        bounds=request.bounds,
        diagnostics=("backend is not installed",),
    )
    authority = ResultAuthority(
        kind=AuthorityKind.THEOREM_PROOF,
        issuer="fake-verifier",
        method="unavailable/v1",
        scope_digest=request.digest,
    )
    result = ProofResult.for_attempt(
        request,
        failed,
        result_id="result:unavailable",
        authority=authority,
        status=ResultStatus.UNKNOWN,
        diagnostics=("no theorem verdict",),
    )

    receipt = ResultReceipt.issue(
        _claim(),
        request,
        failed,
        result,
        receipt_id="receipt:unavailable",
        issuer="test-recorder",
    )
    assert receipt.authority_kind is AuthorityKind.THEOREM_PROOF
    assert receipt.output_digest == result.output_digest
    assert ResultReceipt.from_dict(receipt.to_dict()) == receipt
    with pytest.raises(AuthorityMismatchError, match="not an affirmative theorem proof"):
        ProofReceipt.issue(
            _claim(),
            request,
            failed,
            result,
            receipt_id="proof-receipt:unavailable",
            verifier="kernel/v1",
        )


def test_result_status_and_concrete_type_must_match_authority() -> None:
    request = _request(QueryKind.SATISFIABILITY)
    attempt = _attempt(request)
    authority = ResultAuthority(
        kind=AuthorityKind.SATISFIABILITY,
        issuer="fake-smt",
        method="check-sat",
        scope_digest=request.digest,
    )

    with pytest.raises(AuthorityMismatchError, match="not a valid satisfiability"):
        SatisfiabilityResult.for_attempt(
            request,
            attempt,
            result_id="result:forged-proof-label",
            authority=authority,
            status=ResultStatus.PROVED,
        )

    with pytest.raises(AuthorityMismatchError, match="ProofResult requires theorem_proof"):
        ProofResult.for_attempt(
            request,
            attempt,
            result_id="result:sat-as-proof",
            authority=authority,
            status=ResultStatus.SATISFIABLE,
        )


@pytest.mark.parametrize(
    ("query_kind", "status"),
    (
        (QueryKind.SATISFIABILITY, ResultStatus.SATISFIABLE),
        (QueryKind.SATISFIABILITY, ResultStatus.UNSATISFIABLE),
        (QueryKind.RUNTIME_MONITOR, ResultStatus.MONITOR_SATISFIED),
        (QueryKind.EVIDENCE_READINESS, ResultStatus.READY),
        (QueryKind.POLICY_APPROVAL, ResultStatus.APPROVED),
    ),
)
def test_non_proof_result_families_cannot_issue_theorem_receipt(
    query_kind: QueryKind,
    status: ResultStatus,
) -> None:
    claim = _claim()
    request, attempt, result = _result(query_kind, status)

    receipt = ResultReceipt.issue(
        claim,
        request,
        attempt,
        result,
        receipt_id=f"receipt:{query_kind.value}",
        issuer="test-verifier",
    )
    assert receipt.authority_kind is query_kind.authority_kind
    assert receipt.result_type == type(result).result_type

    with pytest.raises(
        AuthorityMismatchError,
        match=rf"{type(result).__name__} cannot be used as theorem proof",
    ):
        ProofReceipt.issue(
            claim,
            request,
            attempt,
            result,
            receipt_id=f"proof-receipt:{query_kind.value}",
            verifier="test-verifier",
        )


def test_generic_result_with_forged_theorem_labels_cannot_issue_proof_receipt() -> None:
    claim = _claim()
    request, attempt, proof = _result(QueryKind.THEOREM_PROOF, ResultStatus.PROVED)
    forged = BoundedResult(
        result_id="result:generic-forgery",
        request_digest=proof.request_digest,
        attempt_digest=proof.attempt_digest,
        claim_digest=proof.claim_digest,
        declaration_id=proof.declaration_id,
        obligation_id=proof.obligation_id,
        obligation_digest=proof.obligation_digest,
        backend_id=proof.backend_id,
        backend_version=proof.backend_version,
        assumption_ids=proof.assumption_ids,
        authority=proof.authority,
        status=proof.status,
        bounds=proof.bounds,
        usage=proof.usage,
        output_digest=proof.output_digest,
        payload=proof.payload,
    )

    assert not forged.is_theorem_proof
    with pytest.raises(AuthorityMismatchError, match="BoundedResult cannot"):
        ProofReceipt.issue(
            claim,
            request,
            attempt,
            forged,
            receipt_id="proof-receipt:generic-forgery",
            verifier="kernel/v1",
        )


def test_only_affirmative_theorem_result_can_issue_proof_receipt() -> None:
    claim = _claim()
    request, attempt, result = _result(
        QueryKind.THEOREM_PROOF,
        ResultStatus.PROVED,
    )

    receipt = ProofReceipt.issue(
        claim,
        request,
        attempt,
        result,
        receipt_id="proof-receipt:authorization",
        verifier="kernel-checker/v1",
    )

    assert result.is_theorem_proof
    assert receipt.proof_authority is AuthorityKind.THEOREM_PROOF
    assert receipt.result_type == ProofResult.result_type
    assert receipt.claim_digest == claim.digest
    assert receipt.assumption_ids == result.assumption_ids
    assert receipt.backend_id == result.backend_id
    assert receipt.bounds_digest == result.bounds.digest
    assert receipt.output_digest == result.output_digest
    assert ProofReceipt.from_dict(receipt.to_dict()) == receipt

    unknown = replace(result, result_id="result:unknown", status=ResultStatus.UNKNOWN)
    with pytest.raises(AuthorityMismatchError, match="not an affirmative theorem proof"):
        ProofReceipt.issue(
            claim,
            request,
            attempt,
            unknown,
            receipt_id="proof-receipt:unknown",
            verifier="kernel-checker/v1",
        )


def test_receipt_rejects_cross_attempt_cross_claim_and_changed_output() -> None:
    claim = _claim()
    request, attempt, result = _result(
        QueryKind.THEOREM_PROOF,
        ResultStatus.PROVED,
    )
    other_attempt = replace(attempt, attempt_id="attempt:other")

    with pytest.raises(ProtocolValidationError, match="bindings are inconsistent"):
        ResultReceipt.issue(
            claim,
            request,
            other_attempt,
            result,
            receipt_id="receipt:cross-run",
            issuer="test-verifier",
        )

    other_claim = replace(claim, claim_id="claim:other")
    with pytest.raises(ProtocolValidationError, match="bindings are inconsistent"):
        ProofReceipt.issue(
            other_claim,
            request,
            attempt,
            result,
            receipt_id="proof-receipt:cross-claim",
            verifier="kernel-checker/v1",
        )

    changed_output = replace(result, output_digest=stable_digest({"changed": True}))
    with pytest.raises(ProtocolValidationError, match="bindings are inconsistent"):
        ResultReceipt.issue(
            claim,
            request,
            attempt,
            changed_output,
            receipt_id="receipt:changed-output",
            issuer="test-verifier",
        )


def test_result_round_trip_preserves_specific_family_and_recursive_immutability() -> None:
    _, _, monitor = _result(
        QueryKind.RUNTIME_MONITOR,
        ResultStatus.MONITOR_SATISFIED,
    )
    decoded = BoundedResult.from_dict(monitor.to_dict())

    assert isinstance(decoded, MonitorResult)
    assert decoded == monitor
    with pytest.raises(TypeError):
        decoded.payload["new"] = "value"  # type: ignore[index]

    payload = monitor.to_dict()
    payload["result_type"] = "proof"
    with pytest.raises(AuthorityMismatchError, match="ProofResult requires theorem_proof"):
        BoundedResult.from_dict(payload)


def test_bounded_result_rejects_oversize_payload_and_usage() -> None:
    request = BackendRequest.for_claim(
        _claim(),
        "obligation:authorization",
        request_id="request:tiny-output",
        bounds=ExecutionBounds(
            timeout_ms=100,
            max_steps=100,
            max_memory_bytes=10_000,
            max_output_bytes=8,
        ),
        requested_backend_id="fake-backend",
    )
    output_digest = stable_digest({"tiny": "output"})
    attempt = BackendAttempt(
        attempt_id="attempt:tiny-output",
        request_digest=request.digest,
        backend_id="fake-backend",
        backend_version="1",
        status=AttemptStatus.SUCCEEDED,
        bounds=request.bounds,
        output_digest=output_digest,
    )
    authority = ResultAuthority(
        kind=AuthorityKind.THEOREM_PROOF,
        issuer="fake-backend",
        method="kernel-reconstruction",
        scope_digest=request.digest,
    )

    with pytest.raises(ProtocolValidationError, match="payload exceeds"):
        ProofResult.for_attempt(
            request,
            attempt,
            result_id="result:oversize",
            authority=authority,
            status=ResultStatus.PROVED,
            payload={"too-large": "payload"},
        )

    valid = ProofResult.for_attempt(
        request,
        attempt,
        result_id="result:valid",
        authority=authority,
        status=ResultStatus.PROVED,
    )
    with pytest.raises(ProtocolValidationError, match="usage exceeds"):
        replace(valid, usage=ResourceUsage(elapsed_ms=101))


def test_proof_backend_is_solver_neutral_structural_protocol() -> None:
    class FakeBackend:
        backend_id = "fake-backend"
        backend_version = "1"
        capabilities = BackendCapabilities(
            logic_families=("first_order_temporal",),
            query_kinds=(QueryKind.THEOREM_PROOF,),
            deterministic=True,
        )

        def supports(self, request: BackendRequest) -> bool:
            return self.capabilities.supports(request.logic_family, request.query_kind)

        def run(
            self, request: BackendRequest
        ) -> tuple[BackendAttempt, BoundedResult]:
            attempt = _attempt(request)
            authority = ResultAuthority(
                kind=request.query_kind.authority_kind,
                issuer=self.backend_id,
                method="fake-kernel/v1",
                scope_digest=request.digest,
            )
            result = ProofResult.for_attempt(
                request,
                attempt,
                result_id="result:fake",
                authority=authority,
                status=ResultStatus.PROVED,
            )
            return attempt, result

    backend = FakeBackend()
    assert isinstance(backend, ProofBackend)
    assert backend.supports(_request())
