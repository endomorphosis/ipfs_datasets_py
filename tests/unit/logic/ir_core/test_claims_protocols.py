"""Contract tests for solver-neutral claims and exact result authority."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from ipfs_datasets_py.logic.ir_core.claims import (
    Assumption,
    ClaimValidationError,
    FrozenMap,
    IRClaim,
    ProofObligation,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    AttemptStatus,
    AuthorityKind,
    AuthorityMismatchError,
    BackendAttempt,
    BackendRequest,
    BoundedResult,
    ExecutionBounds,
    ProofBackend,
    ProofReceipt,
    ProtocolValidationError,
    QueryKind,
    ResourceUsage,
    ResultAuthority,
    ResultReceipt,
    ResultStatus,
)


def _claim() -> IRClaim:
    return IRClaim(
        claim_id="claim:no-unauthorized-withdrawal",
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


def _request(
    query_kind: QueryKind = QueryKind.THEOREM_PROOF,
) -> BackendRequest:
    return BackendRequest.for_claim(
        _claim(),
        "obligation:authorization",
        request_id=f"request:{query_kind.value}",
        query_kind=query_kind,
        bounds=ExecutionBounds(
            timeout_ms=1_000,
            max_steps=1_000,
            max_memory_bytes=1_000_000,
            max_output_bytes=4_096,
        ),
        payload={"encoding": "neutral-ast/v1"},
    )


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
    )


def _result(
    query_kind: QueryKind,
    status: ResultStatus,
) -> tuple[BackendRequest, BackendAttempt, BoundedResult]:
    request = _request(query_kind)
    attempt = _attempt(request)
    authority = ResultAuthority(
        kind=query_kind.authority_kind,
        issuer="fake-backend",
        method=f"{query_kind.value}/v1",
        scope_digest=request.digest,
    )
    result = BoundedResult.for_attempt(
        request,
        attempt,
        result_id=f"result:{query_kind.value}",
        authority=authority,
        status=status,
        payload={"bounded": True},
    )
    return request, attempt, result


def test_claim_is_recursively_immutable_and_has_stable_identity() -> None:
    claim = _claim()
    equivalent = IRClaim.from_dict(claim.to_dict())

    assert equivalent == claim
    assert equivalent.digest == claim.digest
    assert claim.metadata["labels"] == ("blocking", "withdrawal")
    assert isinstance(claim.assumptions[0].metadata["review"], FrozenMap)

    with pytest.raises(FrozenInstanceError):
        claim.statement = "mutated"  # type: ignore[misc]
    with pytest.raises(TypeError):
        claim.metadata["new"] = "value"  # type: ignore[index]
    detached = claim.to_dict()
    detached["metadata"]["labels"].append("mutated")
    assert claim.metadata["labels"] == ("blocking", "withdrawal")


def test_claim_rejects_unknown_assumption_and_duplicate_ids() -> None:
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


def test_backend_request_is_derived_from_claim_and_attempt_is_bounded() -> None:
    claim = _claim()
    request = _request()
    attempt = _attempt(request)

    assert request.claim_digest == claim.digest
    assert request.assumption_ids == ("assumption:event-log-complete",)
    assert request.logic_family == "first_order_temporal"
    assert attempt.request_digest == request.digest

    with pytest.raises(ProtocolValidationError, match="cannot exceed bounds"):
        replace(
            attempt,
            status=AttemptStatus.SUCCEEDED,
            usage=replace(attempt.usage, elapsed_ms=request.bounds.timeout_ms + 1),
        )


def test_result_status_must_belong_to_its_authority_family() -> None:
    request = _request(QueryKind.SATISFIABILITY)
    attempt = _attempt(request)
    authority = ResultAuthority(
        kind=AuthorityKind.SATISFIABILITY,
        issuer="fake-smt",
        method="check-sat",
        scope_digest=request.digest,
    )

    with pytest.raises(AuthorityMismatchError, match="not a valid satisfiability"):
        BoundedResult.for_attempt(
            request,
            attempt,
            result_id="result:forged-proof-label",
            authority=authority,
            status=ResultStatus.PROVED,
        )

    with pytest.raises(AuthorityMismatchError, match="request asks for satisfiability"):
        BoundedResult.for_attempt(
            request,
            attempt,
            result_id="result:forged-proof-authority",
            authority=replace(authority, kind=AuthorityKind.THEOREM_PROOF),
            status=ResultStatus.PROVED,
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
def test_non_proof_authority_cannot_issue_theorem_receipt(
    query_kind: QueryKind,
    status: ResultStatus,
) -> None:
    claim = _claim()
    request, attempt, result = _result(query_kind, status)

    # The result remains receiptable under its actual, narrow authority.
    result_receipt = ResultReceipt.issue(
        claim,
        request,
        attempt,
        result,
        receipt_id=f"receipt:{query_kind.value}",
        issuer="test-verifier",
    )
    assert result_receipt.authority_kind is query_kind.authority_kind

    # Neither SAT nor UNSAT, a passing monitor, evidence readiness, nor policy
    # approval can be relabeled as theorem proof.
    with pytest.raises(
        AuthorityMismatchError,
        match=rf"{query_kind.authority_kind.value} authority cannot be used as theorem_proof",
    ):
        ProofReceipt.issue(
            claim,
            request,
            attempt,
            result,
            receipt_id=f"proof-receipt:{query_kind.value}",
            verifier="test-verifier",
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
    assert receipt.claim_digest == claim.digest
    assert receipt.result_digest == result.digest

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


def test_receipt_issuance_rejects_cross_run_and_cross_claim_binding() -> None:
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
    )
    attempt = BackendAttempt(
        attempt_id="attempt:tiny-output",
        request_digest=request.digest,
        backend_id="fake-backend",
        backend_version="1",
        status=AttemptStatus.SUCCEEDED,
        bounds=request.bounds,
    )
    authority = ResultAuthority(
        kind=AuthorityKind.THEOREM_PROOF,
        issuer="fake-backend",
        method="kernel-reconstruction",
        scope_digest=request.digest,
    )

    with pytest.raises(ProtocolValidationError, match="payload exceeds"):
        BoundedResult.for_attempt(
            request,
            attempt,
            result_id="result:oversize",
            authority=authority,
            status=ResultStatus.PROVED,
            payload={"too-large": "payload"},
        )

    with pytest.raises(ProtocolValidationError, match="usage exceeds"):
        BoundedResult(
            result_id="result:over-budget",
            request_digest=request.digest,
            attempt_digest=attempt.digest,
            claim_digest=request.claim_digest,
            obligation_id=request.obligation_id,
            authority=authority,
            status=ResultStatus.PROVED,
            bounds=request.bounds,
            usage=ResourceUsage(elapsed_ms=101),
        )


def test_proof_backend_is_a_solver_neutral_structural_protocol() -> None:
    class FakeBackend:
        backend_id = "fake"
        backend_version = "1"

        def supports(self, request: BackendRequest) -> bool:
            return request.logic_family == "first_order_temporal"

        def run(
            self, request: BackendRequest
        ) -> tuple[BackendAttempt, BoundedResult]:
            attempt = _attempt(request)
            authority = ResultAuthority(
                kind=request.query_kind.authority_kind,
                issuer=self.backend_id,
                method="fake",
                scope_digest=request.digest,
            )
            result = BoundedResult.for_attempt(
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
