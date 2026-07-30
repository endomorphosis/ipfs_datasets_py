"""Integration contract for canonical ATP and legacy prover adapters."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from ipfs_datasets_py.logic.backends.atp.adapters import (
    ATPAdapterError,
    ATPCountermodel,
    ATPProofObject,
    DCECBackend,
    EProverBackend,
    MalformedATPOutput,
    NativeProverResult,
    NativeProverStatus,
    SZSStatus,
    TDFOLBackend,
    VampireBackend,
    parse_szs_status,
)
from ipfs_datasets_py.logic.backends.process import (
    BoundedToolRunner,
    RawProcessResult,
)
from ipfs_datasets_py.logic.backends.results import (
    CandidateResult,
    ResultAuthority,
    ResultStatus,
    SatisfiabilityResult,
    TheoremResult,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendRequest,
    ExecutionBounds,
    QueryKind,
)


def _request(
    *,
    family: str = "fol",
    encoding: str = "tptp",
    source: str = "fof(goal, conjecture, p).",
    query_kind: QueryKind = QueryKind.THEOREM_PROOF,
    backend_id: str = "",
    bounds: ExecutionBounds | None = None,
) -> BackendRequest:
    return BackendRequest(
        request_id="request:atp:test",
        claim_id="claim:atp:test",
        declaration_id="declaration:atp:test",
        claim_digest="1" * 64,
        obligation_id="obligation:atp:test",
        obligation_digest="2" * 64,
        assumption_ids=("assumption:reviewed",),
        logic_family=family,
        query_kind=query_kind,
        bounds=bounds or ExecutionBounds(timeout_ms=250, max_steps=20),
        payload=FrozenMap({"encoding": encoding, "source": source}),
        requested_backend_id=backend_id,
    )


def _process_runner(
    stdout: str,
    *,
    returncode: int | None = 0,
    timed_out: bool = False,
    output_truncated: bool = False,
) -> tuple[BoundedToolRunner, list[object]]:
    invocations: list[object] = []

    def execute(invocation, _cancellation):
        invocations.append(invocation)
        assert (invocation.cwd / "problem.p").read_text() == (
            "fof(goal, conjecture, p)."
        )
        return RawProcessResult(
            returncode=returncode,
            stdout=stdout,
            elapsed_seconds=0.012,
            timed_out=timed_out,
            output_truncated=output_truncated,
            process_tree_terminated=timed_out,
        )

    return BoundedToolRunner(executor=execute), invocations


def test_vampire_is_bounded_source_bound_and_unreconstructed_proof_is_candidate():
    runner, invocations = _process_runner(
        "% SZS status Theorem for canonical\n"
        "% SZS output start Proof for canonical\n"
        "fof(step1, plain, p).\n"
    )
    request = _request(backend_id="vampire")

    outcome = VampireBackend(
        runner=runner, backend_version="4.9"
    ).run(request)

    assert isinstance(outcome.result, CandidateResult)
    assert outcome.result.authority is ResultAuthority.CANDIDATE
    assert outcome.result.status is ResultStatus.CANDIDATE
    assert outcome.result.witness["candidate_kind"] == "unreconstructed_atp_proof"
    assert outcome.proof_object is not None
    assert outcome.proof_object.verified is False
    assert outcome.proof_object.content_digest == (
        outcome.result.witness["proof_object"]["content_digest"]
    )
    assert outcome.source_binding.request_digest == request.digest
    assert (
        outcome.result.metadata["source_binding"]["source_digest"]
        == outcome.source_binding.source_digest
    )
    invocation = invocations[0]
    assert invocation.limits.timeout_seconds == 0.25
    assert invocation.limits.memory_bytes == request.bounds.max_memory_bytes
    assert invocation.limits.max_output_bytes == request.bounds.max_output_bytes
    assert "--output_mode=tptp" in invocation.argv


def test_exact_szs_status_replaces_legacy_substring_heuristics():
    runner, _ = _process_runner("Proof found! Theorem proved!\n")
    outcome = EProverBackend(runner=runner).run(_request())

    assert isinstance(outcome.result, TheoremResult)
    assert outcome.result.status is ResultStatus.MALFORMED
    assert "no SZS status" in outcome.result.reason

    with pytest.raises(MalformedATPOutput, match="conflicting"):
        parse_szs_status(
            "% SZS status Theorem for x\n% SZS status CounterSatisfiable for x"
        )
    assert parse_szs_status("% SZS status CounterSatisfiable for x") is (
        SZSStatus.COUNTER_SATISFIABLE
    )
    assert parse_szs_status("# SZS status Theorem") is SZSStatus.THEOREM


def test_verified_reconstruction_can_produce_typed_theorem_proof():
    runner, _ = _process_runner("% SZS status Theorem for canonical\nproof")

    def reconstruct(binding, process, status):
        assert status is SZSStatus.THEOREM
        return ATPProofObject(
            request_digest=binding.request_digest,
            source_digest=binding.source_digest,
            proof_format="tstp",
            content=process.stdout,
            verified=True,
            checker_id="tstp-checker:reviewed-v1",
        )

    outcome = VampireBackend(
        runner=runner,
        backend_version="4.9",
        proof_reconstructor=reconstruct,
    ).run(_request())

    assert isinstance(outcome.result, TheoremResult)
    assert outcome.result.status is ResultStatus.PROVED
    assert outcome.result.authority is ResultAuthority.THEOREM
    assert outcome.proof_object is not None
    assert outcome.proof_object.verified is True
    assert outcome.result.witness["content_digest"] == (
        outcome.proof_object.content_digest
    )


def test_validated_countermodel_is_typed_for_theorem_and_sat_queries():
    def parse_model(binding, _process, status):
        assert status is SZSStatus.COUNTER_SATISFIABLE
        return ATPCountermodel(
            request_digest=binding.request_digest,
            source_digest=binding.source_digest,
            model_format="tptp-model",
            model=FrozenMap({"p": False}),
            validated=True,
            validator_id="tptp-model-validator:v1",
        )

    theorem_runner, _ = _process_runner(
        "% SZS status CounterSatisfiable for canonical"
    )
    theorem = EProverBackend(
        runner=theorem_runner, countermodel_parser=parse_model
    ).run(_request())
    assert isinstance(theorem.result, TheoremResult)
    assert theorem.result.status is ResultStatus.DISPROVED
    assert theorem.countermodel is not None

    sat_runner, _ = _process_runner(
        "% SZS status CounterSatisfiable for canonical"
    )
    sat = EProverBackend(
        runner=sat_runner, countermodel_parser=parse_model
    ).run(_request(query_kind=QueryKind.SATISFIABILITY))
    assert isinstance(sat.result, SatisfiabilityResult)
    assert sat.result.status is ResultStatus.SATISFIABLE


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            RawProcessResult(
                returncode=None, timed_out=True, process_tree_terminated=True
            ),
            ResultStatus.TIMEOUT,
        ),
        (
            RawProcessResult(returncode=0, output_truncated=True),
            ResultStatus.ERROR,
        ),
    ],
)
def test_external_operational_failures_are_explicit(raw, expected):
    def execute(_invocation, _cancellation):
        return raw

    outcome = VampireBackend(
        runner=BoundedToolRunner(executor=execute)
    ).run(_request())
    assert isinstance(outcome.result, TheoremResult)
    assert outcome.result.status is expected


def _verified_native_proof(invocation):
    proof = ATPProofObject(
        request_digest=invocation.source_binding.request_digest,
        source_digest=invocation.source_binding.source_digest,
        proof_format="dcec-proof-tree",
        content="1. p [Axiom]",
        verified=True,
        checker_id="dcec-proof-tree-checker:v1",
    )
    return NativeProverResult(
        request_digest=invocation.source_binding.request_digest,
        source_digest=invocation.source_binding.source_digest,
        status=NativeProverStatus.PROVED,
        native_result_type="CEC.native.ProofAttempt",
        elapsed_ms=4,
        steps=1,
        proof_object=proof,
        metadata=FrozenMap({"legacy_method": "axiom_lookup"}),
    )


@pytest.mark.parametrize(
    ("backend_factory", "family", "encoding"),
    [
        (DCECBackend, "dcec", "dcec"),
        (TDFOLBackend, "tdfol", "tdfol"),
    ],
)
def test_native_dcec_tdfol_results_are_typed_bounded_and_compatible(
    backend_factory, family, encoding
):
    request = _request(
        family=family,
        encoding=encoding,
        source="p",
        backend_id=family,
    )
    outcome = backend_factory(
        _verified_native_proof, backend_version="legacy-reviewed-1"
    ).run(request)

    assert isinstance(outcome.result, TheoremResult)
    assert outcome.result.status is ResultStatus.PROVED
    assert outcome.result.usage.steps == 1
    assert outcome.compatibility_receipt is not None
    assert outcome.compatibility_receipt.reviewed_behavior is True
    assert outcome.compatibility_receipt.canonical_result_digest == (
        outcome.result.digest
    )
    assert outcome.compatibility_receipt.request_digest == request.digest
    assert outcome.compatibility_receipt.receipt_id.startswith(
        "legacy-compatibility:"
    )


@dataclass
class _DuckTypedLegacySuccess:
    is_valid: bool = True
    status: str = "proved"


def test_native_adapter_rejects_duck_typed_success():
    backend = DCECBackend(lambda _invocation: _DuckTypedLegacySuccess())

    with pytest.raises(ATPAdapterError, match="duck-typed"):
        backend.run(_request(family="dcec", encoding="dcec", source="p"))


def test_unverified_native_success_is_candidate_not_proof():
    def native(invocation):
        return NativeProverResult(
            request_digest=invocation.source_binding.request_digest,
            source_digest=invocation.source_binding.source_digest,
            status=NativeProverStatus.PROVED,
            native_result_type="TDFOL.ProofResult",
        )

    outcome = TDFOLBackend(native).run(
        _request(family="tdfol", encoding="tdfol", source="p")
    )
    assert isinstance(outcome.result, CandidateResult)
    assert outcome.result.status is ResultStatus.CANDIDATE
    assert outcome.compatibility_receipt is not None
    assert outcome.compatibility_receipt.reviewed_behavior is True


def test_unreviewed_legacy_success_cannot_gain_theorem_authority():
    outcome = DCECBackend(
        _verified_native_proof,
        reviewed_outcomes=(NativeProverStatus.UNKNOWN,),
    ).run(_request(family="dcec", encoding="dcec", source="p"))

    assert isinstance(outcome.result, CandidateResult)
    assert outcome.result.witness["candidate_kind"] == "unreviewed_legacy_behavior"
    assert outcome.compatibility_receipt is not None
    assert outcome.compatibility_receipt.reviewed_behavior is False


def test_native_result_cannot_cross_request_or_source_binding():
    def forged(_invocation):
        return NativeProverResult(
            request_digest="a" * 64,
            source_digest="b" * 64,
            status=NativeProverStatus.UNKNOWN,
            native_result_type="legacy.Unknown",
        )

    with pytest.raises(ATPAdapterError, match="not bound"):
        DCECBackend(forged).run(
            _request(family="dcec", encoding="dcec", source="p")
        )


def test_native_usage_overrun_cannot_be_promoted_to_proof():
    def overrun(invocation):
        proof = ATPProofObject(
            request_digest=invocation.source_binding.request_digest,
            source_digest=invocation.source_binding.source_digest,
            proof_format="dcec-proof-tree",
            content="proof",
            verified=True,
            checker_id="checker:v1",
        )
        return NativeProverResult(
            request_digest=invocation.source_binding.request_digest,
            source_digest=invocation.source_binding.source_digest,
            status=NativeProverStatus.PROVED,
            native_result_type="CEC.native.ProofAttempt",
            steps=21,
            proof_object=proof,
        )

    outcome = DCECBackend(overrun).run(
        _request(family="dcec", encoding="dcec", source="p")
    )
    assert isinstance(outcome.result, TheoremResult)
    assert outcome.result.status is ResultStatus.ERROR
    assert "max_steps" in outcome.result.reason


def test_wrong_encoding_and_wrong_artifact_binding_fail_closed():
    with pytest.raises(ATPAdapterError, match="encoding"):
        VampireBackend(
            runner=_process_runner("% SZS status Theorem for x")[0]
        ).run(_request(encoding="smtlib2"))

    runner, _ = _process_runner("% SZS status Theorem for x")

    def forged_proof(_binding, process, _status):
        return ATPProofObject(
            request_digest="a" * 64,
            source_digest="b" * 64,
            proof_format="tstp",
            content=process.stdout,
            verified=True,
            checker_id="checker:v1",
        )

    with pytest.raises(ATPAdapterError, match="another source"):
        VampireBackend(
            runner=runner, proof_reconstructor=forged_proof
        ).run(_request())
