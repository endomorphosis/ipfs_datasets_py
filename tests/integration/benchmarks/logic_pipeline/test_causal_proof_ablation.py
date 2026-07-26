"""Synthetic G210 proof-graph tests; no corpus or holdout is loaded."""

from __future__ import annotations

import pytest

from benchmarks.logic_pipeline import capabilities, contracts, runtime, variants
from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json


def _candidate(source: str, proof: str) -> runtime.CausalProofCandidate:
    return runtime.CausalProofCandidate(
        source=source,
        certificate=proof,
        artifact_cid=cid_for_dag_json(
            {
                "schema": "synthetic-causal-artifact.v1",
                "source": source,
                "proof": proof,
            }
        ),
    )


def _controller(
    *,
    accepted_proofs: frozenset[bytes],
    calls: list[str],
    variant_id: str,
) -> runtime.CausalProofGraphController:
    def check(
        candidate: runtime.CausalProofCandidate,
    ) -> runtime.CausalKernelCheck:
        assert isinstance(candidate.certificate, bytes)
        calls.append(candidate.source)
        accepted = candidate.certificate in accepted_proofs
        return runtime.CausalKernelCheck(
            candidate_cid=str(candidate.candidate_cid),
            accepted=accepted,
            receipt={
                "schema": "synthetic-independent-kernel-receipt.v1",
                "run_id": "g210-synthetic",
                "case_id": "case-1",
                "variant_id": variant_id,
                "candidate_cid": candidate.candidate_cid,
                "independent": True,
                "accepted": accepted,
            },
            failure_code=(
                None
                if accepted
                else contracts.FailureCode.KERNEL_REJECTION
            ),
        )

    return runtime.CausalProofGraphController(
        kernel_checker=check,
        kernel_receipt_validator=lambda candidate, check: (
            check.receipt.get("schema")
            == "synthetic-independent-kernel-receipt.v1"
            and check.receipt.get("independent") is True
            and check.receipt.get("candidate_cid")
            == candidate.candidate_cid
        ),
    )


def _execute(
    controller: runtime.CausalProofGraphController,
    *,
    variant_id: str,
    compiler: runtime.CausalProofCandidate | None,
    producers: dict[
        str,
        object,
    ],
) -> runtime.CausalProofGraphResult:
    return controller.execute(
        run_id="g210-synthetic",
        case_id="case-1",
        variant_id=variant_id,
        source_text="Every synthetic obligation is source bound.",
        compiler_candidate=compiler,
        optional_producers=producers,  # type: ignore[arg-type]
    )


def test_protocol_is_additive_cid_bound_and_a0_gains_equal_kernel_exposure() -> None:
    assert contracts.HSSLEV2108F34() == (
        "equal compiler-kernel exposure and distinct optional-component "
        "rescue attribution"
    )
    assert contracts.DEFAULT_PROTOCOL_SHA256 == (
        "a12067c4239b9628fde065db3fe10e623148c95a55891a642306e0c90dee8fa3"
    )
    assert contracts.CAUSAL_PROOF_PROTOCOL_V2.parent_semantic_protocol_cid == (
        contracts.SEMANTIC_PROTOCOL_V2_CID
    )
    assert contracts.CAUSAL_PROOF_PROTOCOL_V2.holdout_permitted is False
    assert variants.get_variant_definition("A0").stages == (
        contracts.StageName.COMPILER,
    )
    assert variants.get_causal_proof_variant_profile(
        "A0"
    ).effective_stages == (
        contracts.StageName.COMPILER,
        contracts.StageName.KERNEL,
    )
    assert variants.effective_variant_stages(
        "A0",
        causal_proof_protocol_cid=contracts.CAUSAL_PROOF_PROTOCOL_V2_CID,
    )[-1] is contracts.StageName.KERNEL
    assert all(
        profile.effective_stages[-1] is contracts.StageName.KERNEL
        for profile in variants.CAUSAL_PROOF_VARIANT_PROFILES.values()
    )
    assert variants.get_causal_proof_variant_profile(
        "A12"
    ).optional_order == (
        contracts.StageName.LEANSTRAL,
        contracts.StageName.HAMMER,
    )


def test_cid_bearing_causal_routes_are_deeply_immutable() -> None:
    profile = variants.get_causal_proof_variant_profile("A3")
    original_cid = profile.cid
    route = profile.optional_routes[0]
    predecessors = route["allowed_predecessor_states"]

    assert isinstance(predecessors, tuple)
    with pytest.raises(TypeError):
        route["source"] = "substituted"  # type: ignore[index]
    with pytest.raises(AttributeError):
        predecessors.append("substituted")
    assert profile.cid == original_cid


def test_compiler_acceptance_suppresses_all_optional_producers() -> None:
    calls: list[str] = []
    compiler = _candidate("compiler", "exact compiler certificate")
    controller = _controller(
        accepted_proofs=frozenset({b"exact compiler certificate"}),
        calls=calls,
        variant_id="A3",
    )
    producer_calls: list[str] = []

    def forbidden(source: str):
        def invoke() -> runtime.CausalProofCandidate:
            producer_calls.append(source)
            return _candidate(source, f"{source} must not run")

        return invoke

    result = _execute(
        controller,
        variant_id="A3",
        compiler=compiler,
        producers={
            "hammer": forbidden("hammer"),
            "leanstral": forbidden("leanstral"),
        },
    )

    receipt = contracts.validate_causal_proof_selection_receipt(
        result.receipt
    )
    assert calls == ["compiler"]
    assert producer_calls == []
    assert receipt["selected_source"] == "compiler"
    assert all(
        item["invoked"] is False
        and item["trigger_eligible"] is False
        and item["causal_rescue"] is False
        for item in receipt["optional_candidates"]
    )
    assert receipt["denominators"] == {
        "compiler_reference": True,
        "compiler_candidate_present": True,
        "hammer_optional_route": True,
        "leanstral_optional_route": True,
        "hammer_escalation": False,
        "leanstral_escalation": False,
        "hammer_suppression": True,
        "leanstral_suppression": True,
        "hammer_unique_rescue": False,
        "leanstral_unique_rescue": False,
        "overlap": False,
        "unnecessary_work": False,
    }


def test_duplicate_hammer_gets_zero_credit_then_distinct_leanstral_rescues() -> None:
    calls: list[str] = []
    compiler = _candidate("compiler", "duplicate certificate")
    controller = _controller(
        accepted_proofs=frozenset({b"distinct leanstral certificate"}),
        calls=calls,
        variant_id="A3",
    )

    result = _execute(
        controller,
        variant_id="A3",
        compiler=compiler,
        producers={
            "hammer": lambda: _candidate(
                "hammer", "duplicate certificate"
            ),
            "leanstral": lambda: _candidate(
                "leanstral", "distinct leanstral certificate"
            ),
        },
    )
    receipt = contracts.validate_causal_proof_selection_receipt(
        result.receipt
    )
    hammer, leanstral = receipt["optional_candidates"]

    assert calls == ["compiler", "leanstral"]
    assert hammer["overlap"] is True
    assert hammer["kernel_checked"] is False
    assert hammer["marginal_credit_millionths"] == 0
    assert hammer["zero_credit_reason"] == "duplicate_certificate"
    assert leanstral["causal_rescue"] is True
    assert leanstral["marginal_credit_millionths"] == 1_000_000
    assert receipt["selected_source"] == "leanstral"
    assert len(receipt["kernel_receipts"]) == 2
    assert receipt["denominators"]["overlap"] is True
    assert receipt["denominators"]["unnecessary_work"] is True


def test_post_model_failure_is_continuation_not_recovery() -> None:
    calls: list[str] = []
    controller = _controller(
        accepted_proofs=frozenset({b"distinct hammer rescue"}),
        calls=calls,
        variant_id="A6",
    )

    result = _execute(
        controller,
        variant_id="A6",
        compiler=None,
        producers={
            "leanstral": lambda: runtime.CausalProofFailure(
                "leanstral",
                "leanstral_output_limit",
                "bounded output was truncated",
            ),
            "hammer": lambda: _candidate(
                "hammer", "distinct hammer rescue"
            ),
        },
    )
    receipt = contracts.validate_causal_proof_selection_receipt(
        result.receipt
    )
    leanstral, hammer = receipt["optional_candidates"]

    assert leanstral["continuation_kind"] == (
        "post_model_failure_continuation"
    )
    assert leanstral["causal_rescue"] is False
    assert leanstral["failure_code"] == "leanstral_output_limit"
    assert hammer["continuation_kind"] == (
        "selected_post_model_failure_continuation"
    )
    assert hammer["causal_credit_eligible"] is False
    assert hammer["causal_rescue"] is False
    assert hammer["marginal_credit_millionths"] == 0
    assert (
        hammer["zero_credit_reason"] == "post_model_failure_continuation"
    )
    assert receipt["selected_source"] == "hammer"
    assert receipt["denominators"]["hammer_unique_rescue"] is False
    assert calls == ["hammer"]


def test_invalid_protocol_failure_taxonomy_and_tampering_fail_closed() -> None:
    with pytest.raises(
        runtime.RuntimeBindingError,
        match="unsupported causal proof protocol CID",
    ):
        runtime.CausalProofGraphController(
            kernel_checker=lambda _candidate: None,  # type: ignore[arg-type]
            kernel_receipt_validator=lambda _candidate, _check: True,
            protocol_cid=contracts.SEMANTIC_PROTOCOL_V2_CID,
        )
    with pytest.raises(
        runtime.RuntimeBindingError,
        match="failure code is not preregistered",
    ):
        runtime.CausalProofFailure("leanstral", "generic_model_failure")

    calls: list[str] = []
    controller = _controller(
        accepted_proofs=frozenset({b"accepted"}),
        calls=calls,
        variant_id="A2",
    )
    result = _execute(
        controller,
        variant_id="A2",
        compiler=None,
        producers={"hammer": lambda: _candidate("hammer", "accepted")},
    )
    tampered = result.to_dict()
    optional = [dict(item) for item in tampered["optional_candidates"]]
    optional[0]["marginal_credit_millionths"] = 0
    tampered["optional_candidates"] = optional
    with pytest.raises(
        contracts.ProtocolContractError,
        match="causal rescue or marginal credit",
    ):
        contracts.validate_causal_proof_selection_receipt(tampered)

    tampered_bytes = result.to_dict()
    sidecars = [dict(item) for item in tampered_bytes["kernel_receipts"]]
    sidecars[0]["candidate_bytes_utf8"] = "different accepted bytes"
    tampered_bytes["kernel_receipts"] = sidecars
    with pytest.raises(
        contracts.ProtocolContractError,
        match="raw candidate CID changed",
    ):
        contracts.validate_causal_proof_selection_receipt(tampered_bytes)

    relabeled = result.to_dict()
    optional = [dict(item) for item in relabeled["optional_candidates"]]
    optional[0]["continuation_kind"] = "recovery"
    relabeled["optional_candidates"] = optional
    body = {
        key: value for key, value in relabeled.items() if key != "receipt_cid"
    }
    relabeled["receipt_cid"] = cid_for_dag_json(body)
    with pytest.raises(
        contracts.ProtocolContractError,
        match="continuation or zero-credit reason",
    ):
        contracts.validate_causal_proof_selection_receipt(relabeled)


def test_live_runtime_additively_routes_a0_to_kernel_only_when_selected() -> None:
    records = tuple(
        capabilities.CapabilityRecord(
            kind,
            capabilities.CapabilityStatus.UNAVAILABLE,
            {"implementation": "synthetic-unavailable"},
            ("synthetic",),
            "not needed by structural route test",
        )
        for kind in capabilities.CapabilityKind
    )
    inventory = capabilities.CapabilityInventory.create(
        "g210-runtime-route",
        records,
        environment={"suite": "synthetic"},
    )
    compiler = lambda _request: None  # never invoked in this structural test

    legacy = runtime.build_live_runtime(
        inventory,
        runtime.RuntimeBackendHandlers(compiler=compiler),  # type: ignore[arg-type]
        variant_ids=("A0",),
    )
    causal = runtime.build_live_runtime(
        inventory,
        runtime.RuntimeBackendHandlers(compiler=compiler),  # type: ignore[arg-type]
        variant_ids=("A0",),
        causal_proof_protocol_cid=contracts.CAUSAL_PROOF_PROTOCOL_V2_CID,
    )

    assert tuple(legacy.adapters["A0"]) == (contracts.StageName.COMPILER,)
    assert tuple(causal.adapters["A0"]) == (
        contracts.StageName.COMPILER,
        contracts.StageName.KERNEL,
    )
    assert causal.causal_proof_protocol_cid == (
        contracts.CAUSAL_PROOF_PROTOCOL_V2_CID
    )
