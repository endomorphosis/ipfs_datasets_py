"""Synthetic G210 causal accounting tests; no benchmark data is loaded."""

from __future__ import annotations

import copy
import hashlib

import pytest

from benchmarks.logic_pipeline import contracts, metrics, runtime, statistics
from benchmarks.logic_pipeline.content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
    sha256_digest_for_cid,
)


MANIFEST_SHA = "a" * 64
ENVIRONMENT_SHA = "b" * 64
INPUT_SHA = "c" * 64
COMPILER_ARTIFACT_SHA = "d" * 64
HAMMER_ARTIFACT_SHA = "e" * 64
RUN_ID = "g210-metrics"
CASE_ID = "synthetic-rescue"
VARIANT_ID = "A2"
SOURCE_TEXT = "Every source-bound synthetic rescue is independently checked."
SOURCE_CID = cid_for_bytes(SOURCE_TEXT.encode("utf-8"))


def _hammer_payload() -> dict[str, object]:
    body: dict[str, object] = {
        "schema": "ipfs-datasets.logic-pipeline-benchmark.hammer-evidence.v1",
        "request": {"request_id": "request-1"},
        "portfolio": {"request_id": "request-1"},
        "normalized_evidence": {},
        "proof_candidate": {
            "request_id": "request-1",
            "candidate_id": "candidate-1",
        },
        "reconstruction": {
            "request_id": "request-1",
            "candidate_id": "candidate-1",
            "environment_lock_id": "environment-1",
            "kernel_accepted": True,
        },
        "environment_lock": {"lock_id": "environment-1"},
        "reconstruction_kernel_accepted": True,
        "status": "verified",
    }
    return {
        "evidence_id": hashlib.sha256(
            contracts.canonical_json(body).encode("utf-8")
        ).hexdigest(),
        **body,
    }


def _native_receipt(
    source: str,
    artifact_sha256: str,
    *,
    accepted: bool,
) -> dict[str, object]:
    attempt_body: dict[str, object] = {
        "attempt_index": 0,
        "candidate_source": source,
        "candidate_artifact_sha256": artifact_sha256,
        "source_sha256": hashlib.sha256(SOURCE_TEXT.encode()).hexdigest(),
        "command_sha256": hashlib.sha256(
            f"lean:{source}".encode()
        ).hexdigest(),
        "stdout_sha256": hashlib.sha256(
            b"accepted" if accepted else b"rejected"
        ).hexdigest(),
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "returncode": 0 if accepted else 1,
        "timed_out": False,
        "cancelled": False,
        "resource_exhausted": False,
        "termination_reason": "completed",
        "process_group_reaped": True,
        "active_process_count": 0,
        "accepted": accepted,
    }
    attempt = {
        **attempt_body,
        "attempt_sha256": hashlib.sha256(
            contracts.canonical_json(attempt_body).encode("utf-8")
        ).hexdigest(),
    }
    body: dict[str, object] = {
        "schema": contracts.NATIVE_KERNEL_RECEIPT_SCHEMA,
        "protocol_sha256": contracts.DEFAULT_PROTOCOL_SHA256,
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "case_manifest_sha256": MANIFEST_SHA,
        "variant_id": VARIANT_ID,
        "split": contracts.Split.PILOT.value,
        "cache_mode": contracts.CacheMode.COLD.value,
        "input_sha256": INPUT_SHA,
        "environment_sha256": ENVIRONMENT_SHA,
        "independent": True,
        "accepted": accepted,
        "active_process_count": 0,
        "compiled_obligation_sha256": hashlib.sha256(b"compiled").hexdigest(),
        "obligation_sha256": hashlib.sha256(b"obligation").hexdigest(),
        "candidate_source": source,
        "candidate_artifact_sha256": artifact_sha256,
        "source_sha256": attempt["source_sha256"],
        "semantic_context_sha256": hashlib.sha256(
            b"semantic-context"
        ).hexdigest(),
        "semantic_artifact_sha256s": [artifact_sha256],
        "command_sha256": attempt["command_sha256"],
        "stdout_sha256": attempt["stdout_sha256"],
        "stderr_sha256": attempt["stderr_sha256"],
        "returncode": attempt["returncode"],
        "timed_out": False,
        "cancelled": False,
        "resource_exhausted": False,
        "termination_reason": "completed",
        "process_group_reaped": True,
        "candidate_attempts": [attempt],
        "candidate_attempts_sha256": hashlib.sha256(
            contracts.canonical_json([attempt]).encode("utf-8")
        ).hexdigest(),
        "selected_attempt": {
            key: attempt[key]
            for key in (
                "attempt_index",
                "candidate_source",
                "candidate_artifact_sha256",
                "attempt_sha256",
                "accepted",
            )
        },
    }
    return {
        **body,
        "receipt_sha256": hashlib.sha256(
            contracts.canonical_json(body).encode("utf-8")
        ).hexdigest(),
    }


def _candidate(source: str, certificate: str) -> runtime.CausalProofCandidate:
    return runtime.CausalProofCandidate(
        source=source,
        certificate=certificate,
        artifact_cid=cid_for_dag_json(
            {
                "schema": "synthetic-causal-artifact.v1",
                "source": source,
                "certificate": certificate,
            }
        ),
    )


def _selection() -> dict[str, object]:
    compiler = _candidate("compiler", "compiler candidate")
    hammer = _candidate("hammer", "distinct hammer candidate")
    compiler_artifact_sha = sha256_digest_for_cid(compiler.artifact_cid)
    hammer_artifact_sha = sha256_digest_for_cid(hammer.artifact_cid)
    receipts = {
        "compiler": _native_receipt(
            "compiler", compiler_artifact_sha, accepted=False
        ),
        "hammer": _native_receipt(
            "hammer", hammer_artifact_sha, accepted=True
        ),
    }
    artifacts = {
        "compiler": compiler_artifact_sha,
        "hammer": hammer_artifact_sha,
    }

    def check(
        candidate: runtime.CausalProofCandidate,
    ) -> runtime.CausalKernelCheck:
        accepted = candidate.source == "hammer"
        return runtime.CausalKernelCheck(
            candidate_cid=str(candidate.candidate_cid),
            accepted=accepted,
            receipt=receipts[candidate.source],
            stage_status=(
                contracts.StageStatus.SUCCESS
                if accepted
                else contracts.StageStatus.FAILED
            ),
            failure_code=(
                None
                if accepted
                else contracts.FailureCode.KERNEL_REJECTION
            ),
            consumed_artifact_sha256s=(artifacts[candidate.source],),
        )

    controller = runtime.CausalProofGraphController(
        kernel_checker=check,
        kernel_receipt_validator=lambda candidate, result: (
            result.candidate_cid == candidate.candidate_cid
            and result.receipt.get("independent") is True
        ),
    )
    result = controller.execute(
        run_id=RUN_ID,
        case_id=CASE_ID,
        variant_id=VARIANT_ID,
        source_text=SOURCE_TEXT,
        compiler_candidate=compiler,
        optional_producers={"hammer": lambda: hammer},
    )
    return contracts.validate_causal_proof_selection_receipt(result.receipt)


def _overlap_selection() -> dict[str, object]:
    compiler = _candidate("compiler", "byte-identical candidate")
    hammer = _candidate("hammer", "byte-identical candidate")
    compiler_artifact_sha = sha256_digest_for_cid(compiler.artifact_cid)
    compiler_receipt = _native_receipt(
        "compiler", compiler_artifact_sha, accepted=False
    )

    def check(
        candidate: runtime.CausalProofCandidate,
    ) -> runtime.CausalKernelCheck:
        assert candidate.source == "compiler"
        return runtime.CausalKernelCheck(
            candidate_cid=str(candidate.candidate_cid),
            accepted=False,
            receipt=compiler_receipt,
            stage_status=contracts.StageStatus.FAILED,
            failure_code=contracts.FailureCode.KERNEL_REJECTION,
            consumed_artifact_sha256s=(compiler_artifact_sha,),
        )

    controller = runtime.CausalProofGraphController(
        kernel_checker=check,
        kernel_receipt_validator=lambda candidate, result: (
            result.candidate_cid == candidate.candidate_cid
            and result.receipt.get("independent") is True
        ),
    )
    result = controller.execute(
        run_id=RUN_ID,
        case_id=CASE_ID,
        variant_id=VARIANT_ID,
        source_text=SOURCE_TEXT,
        compiler_candidate=compiler,
        optional_producers={"hammer": lambda: hammer},
    )
    return contracts.validate_causal_proof_selection_receipt(result.receipt)


def _compiler_accepts_selection() -> dict[str, object]:
    compiler = _candidate("compiler", "accepted compiler candidate")
    compiler_artifact_sha = sha256_digest_for_cid(compiler.artifact_cid)
    compiler_receipt = _native_receipt(
        "compiler", compiler_artifact_sha, accepted=True
    )

    def check(
        candidate: runtime.CausalProofCandidate,
    ) -> runtime.CausalKernelCheck:
        assert candidate.source == "compiler"
        return runtime.CausalKernelCheck(
            candidate_cid=str(candidate.candidate_cid),
            accepted=True,
            receipt=compiler_receipt,
            stage_status=contracts.StageStatus.SUCCESS,
            consumed_artifact_sha256s=(compiler_artifact_sha,),
        )

    def forbidden_hammer() -> runtime.CausalProofCandidate:
        raise AssertionError("suppressed optional producer was invoked")

    controller = runtime.CausalProofGraphController(
        kernel_checker=check,
        kernel_receipt_validator=lambda candidate, result: (
            result.candidate_cid == candidate.candidate_cid
            and result.receipt.get("independent") is True
        ),
    )
    result = controller.execute(
        run_id=RUN_ID,
        case_id=CASE_ID,
        variant_id=VARIANT_ID,
        source_text=SOURCE_TEXT,
        compiler_candidate=compiler,
        optional_producers={"hammer": forbidden_hammer},
    )
    return contracts.validate_causal_proof_selection_receipt(result.receipt)


def _case_result(
    selection_cid: str,
    *,
    kernel_source: str = "hammer",
    kernel_accepted: bool = True,
    kernel_artifact_sha256: str | None = None,
    include_hammer: bool = True,
    omit_hammer_graph_invoked: bool = False,
) -> contracts.CaseResultRecord:
    route = (
        (
            contracts.StageName.COMPILER,
            contracts.StageName.SPACY,
            contracts.StageName.HAMMER,
            contracts.StageName.KERNEL,
        )
        if include_hammer
        else (
            contracts.StageName.COMPILER,
            contracts.StageName.SPACY,
            contracts.StageName.KERNEL,
        )
    )
    lanes = {
        contracts.StageName.COMPILER: contracts.ResourceLane.CPU,
        contracts.StageName.SPACY: contracts.ResourceLane.CPU,
        contracts.StageName.HAMMER: contracts.ResourceLane.SOLVER,
        contracts.StageName.KERNEL: contracts.ResourceLane.KERNEL,
    }
    stages: list[contracts.StageRecord] = []
    for index, stage_name in enumerate(route):
        effective_identity: dict[str, object] = {
            "implementation": stage_name.value,
            "source_cid": SOURCE_CID,
            "graph_invoked": True,
        }
        if (
            stage_name is contracts.StageName.HAMMER
            and omit_hammer_graph_invoked
        ):
            effective_identity.pop("graph_invoked")
        if stage_name is contracts.StageName.KERNEL:
            artifact_sha256 = (
                kernel_artifact_sha256
                if kernel_artifact_sha256 is not None
                else (
                    HAMMER_ARTIFACT_SHA
                    if kernel_source == "hammer"
                    else COMPILER_ARTIFACT_SHA
                )
            )
            effective_identity.update(
                {
                    "consumed_artifact_sha256": [artifact_sha256],
                    "causal_selection_receipt_cid": selection_cid,
                }
            )
        provenance = contracts.StageProvenance(
            schema=contracts.STAGE_PROVENANCE_SCHEMA,
            adapter_id=f"{stage_name.value}-adapter",
            adapter_version="2",
            source=("synthetic-g210-metrics",),
            requested_identity={
                "implementation": stage_name.value,
                "source_cid": SOURCE_CID,
            },
            effective_identity=effective_identity,
            input_sha256=INPUT_SHA,
            environment_sha256=ENVIRONMENT_SHA,
            upstream_stage_digests=tuple(item.digest for item in stages),
        )
        telemetry = contracts.TelemetryRecord(
            wall_time_ms=float(index + 1),
            cpu_time_ms=0.5,
            peak_memory_bytes=1024 * (index + 1),
            input_items=1,
            output_items=1,
            retries=2 if stage_name is contracts.StageName.HAMMER else 0,
            resource_lane=lanes[stage_name],
        )
        data: object = {"stage": stage_name.value}
        if stage_name is contracts.StageName.HAMMER:
            data = _hammer_payload()
        if stage_name is contracts.StageName.KERNEL:
            artifact_sha256 = (
                kernel_artifact_sha256
                if kernel_artifact_sha256 is not None
                else (
                    HAMMER_ARTIFACT_SHA
                    if kernel_source == "hammer"
                    else COMPILER_ARTIFACT_SHA
                )
            )
            data = _native_receipt(
                kernel_source,
                artifact_sha256,
                accepted=kernel_accepted,
            )
        stage_status = (
            contracts.StageStatus.FAILED
            if stage_name is contracts.StageName.KERNEL
            and not kernel_accepted
            else contracts.StageStatus.SUCCESS
        )
        stages.append(
            contracts.StageRecord.create(
                protocol_sha256=contracts.DEFAULT_PROTOCOL_SHA256,
                run_id=RUN_ID,
                case_id=CASE_ID,
                case_manifest_sha256=MANIFEST_SHA,
                variant_id=VARIANT_ID,
                split=contracts.Split.PILOT,
                cache_mode=contracts.CacheMode.COLD,
                stage=stage_name,
                adapter_version="2",
                status=stage_status,
                provenance=provenance,
                telemetry=telemetry,
                data=data,
                kernel_accepted=(
                    stage_name is contracts.StageName.KERNEL
                    and kernel_accepted
                ),
                kernel_receipt_sha256=(
                    str(data["receipt_sha256"])  # type: ignore[index]
                    if stage_name is contracts.StageName.KERNEL
                    and kernel_accepted
                    else None
                ),
                failure_code=(
                    contracts.FailureCode.KERNEL_REJECTION
                    if stage_name is contracts.StageName.KERNEL
                    and not kernel_accepted
                    else None
                ),
                failure_detail=(
                    "synthetic compiler reference rejected"
                    if stage_name is contracts.StageName.KERNEL
                    and not kernel_accepted
                    else None
                ),
            )
        )
    return contracts.CaseResultRecord.from_stages(stages)


def _artifact_sha_for_source(
    selection: dict[str, object],
    source: str,
) -> str:
    if source == "compiler":
        record = selection["compiler_reference"]
    else:
        record = next(
            item
            for item in selection["optional_candidates"]
            if item["source"] == source
        )
    return sha256_digest_for_cid(record["artifact_cid"])


def test_distinct_native_accepted_candidate_is_one_causal_unique_win() -> None:
    assert metrics.HSSLEV2108F34() == contracts.HSSLEV2108F34()
    selection = _selection()
    case_result = _case_result(
        str(selection["receipt_cid"]),
        kernel_artifact_sha256=_artifact_sha_for_source(
            selection, "hammer"
        ),
    )

    receipt = metrics.build_causal_rescue_case_receipt(
        case_result, selection
    )
    assert metrics.validate_causal_rescue_case_receipt(receipt) == receipt
    assert receipt["compiler_reference_state"] == "rejected"
    assert receipt["causal_rescue_source"] == "hammer"
    assert len(receipt["native_kernel_receipt_cids"]) == 2
    hammer = next(
        item
        for item in receipt["component_measurements"]
        if item["component_id"] == "hammer"
    )
    assert hammer == {
        "component_id": "hammer",
        "invoked": True,
        "component_calls": 1,
        "model_calls": 0,
        "retries": 2,
        "wall_time_ms": 3.0,
        "peak_memory_bytes": 3072,
        "kernel_checks": 1,
        "unique_wins": 1,
        "unnecessary_work": False,
        "unnecessary_component_calls": 0,
        "overlap_zero_marginal": False,
        "continuation_kind": "selected_causal_rescue",
        "leanstral_failure_class": "none",
    }

    aggregate = metrics.aggregate_causal_rescue_receipts((receipt,))
    assert metrics.validate_causal_rescue_aggregate(aggregate) == aggregate
    component = aggregate["components"]["hammer"]
    assert component["eligible_count"] == 1
    assert component["escalated_count"] == 1
    assert component["unique_win_count"] == 1
    assert component["unnecessary_work_count"] == 0

    rate_bundle = statistics.build_causal_rescue_rate_bundle(aggregate)
    assert (
        statistics.validate_causal_rescue_rate_bundle(rate_bundle)
        == rate_bundle
    )
    rates = {
        item["metric_id"]: item for item in rate_bundle["rates"]
    }
    assert rates["hammer_causal_rescue_rate"]["numerator"] == 1
    assert rates["hammer_causal_rescue_rate"]["denominator"] == 1
    assert rates["hammer_escalation_rate"]["numerator"] == 1
    assert rates["hammer_escalation_rate"]["denominator"] == 1
    assert rates["hammer_suppression_rate"]["numerator"] == 0
    assert rates["hammer_suppression_rate"]["denominator"] == 1
    assert rates["hammer_unnecessary_work_rate"]["numerator"] == 0
    assert rates["hammer_unnecessary_work_rate"]["denominator"] == 1


def test_suppressed_route_is_measured_over_scheduled_optional_routes() -> None:
    selection = _compiler_accepts_selection()
    receipt = metrics.build_causal_rescue_case_receipt(
        _case_result(
            str(selection["receipt_cid"]),
            kernel_source="compiler",
            kernel_artifact_sha256=_artifact_sha_for_source(
                selection, "compiler"
            ),
            include_hammer=False,
        ),
        selection,
    )
    aggregate = metrics.aggregate_causal_rescue_receipts((receipt,))
    component = aggregate["components"]["hammer"]
    assert component["eligible_count"] == 0
    assert component["invoked_count"] == 0
    assert component["suppressed_count"] == 1

    rate_bundle = statistics.build_causal_rescue_rate_bundle(aggregate)
    rates = {item["metric_id"]: item for item in rate_bundle["rates"]}
    suppression = rates["hammer_suppression_rate"]
    assert suppression["event_label"] == "scheduled_route_suppressed"
    assert (
        suppression["population_label"]
        == "hammer_scheduled_optional_route"
    )
    assert suppression["numerator"] == 1
    assert suppression["denominator"] == 1


def test_causal_receipt_tampering_cannot_create_marginal_efficacy() -> None:
    selection = _selection()
    receipt = metrics.build_causal_rescue_case_receipt(
        _case_result(
            str(selection["receipt_cid"]),
            kernel_artifact_sha256=_artifact_sha_for_source(
                selection, "hammer"
            ),
        ),
        selection,
    )
    tampered = copy.deepcopy(receipt)
    tampered["component_measurements"][1]["unique_wins"] = 0
    with pytest.raises(
        metrics.MetricsContractError,
        match="fields or CID changed",
    ):
        metrics.validate_causal_rescue_case_receipt(tampered)


def test_component_accounting_requires_exact_invocation_marker() -> None:
    selection = _selection()
    with pytest.raises(
        metrics.MetricsContractError,
        match="lacks an exact graph_invoked marker",
    ):
        metrics.build_causal_rescue_case_receipt(
            _case_result(
                str(selection["receipt_cid"]),
                kernel_artifact_sha256=_artifact_sha_for_source(
                    selection, "hammer"
                ),
                omit_hammer_graph_invoked=True,
            ),
            selection,
        )


def test_candidate_artifact_cid_must_match_native_kernel_input() -> None:
    selection = _selection()
    case_result = _case_result(
        str(selection["receipt_cid"]),
        kernel_artifact_sha256=_artifact_sha_for_source(
            selection, "hammer"
        ),
    )
    tampered = copy.deepcopy(selection)
    tampered["optional_candidates"][0]["artifact_cid"] = cid_for_dag_json(
        {"schema": "different-candidate-artifact.v1"}
    )
    body = {
        key: value
        for key, value in tampered.items()
        if key != "receipt_cid"
    }
    tampered["receipt_cid"] = cid_for_dag_json(body)

    with pytest.raises(
        metrics.MetricsContractError,
        match="candidate CID/artifact differs from native-kernel input",
    ):
        metrics.build_causal_rescue_case_receipt(case_result, tampered)


def test_byte_identical_overlap_has_zero_marginal_and_unnecessary_work() -> None:
    selection = _overlap_selection()
    receipt = metrics.build_causal_rescue_case_receipt(
        _case_result(
            str(selection["receipt_cid"]),
            kernel_source="compiler",
            kernel_accepted=False,
            kernel_artifact_sha256=_artifact_sha_for_source(
                selection, "compiler"
            ),
        ),
        selection,
    )
    assert receipt["causal_rescue_source"] is None
    assert receipt["overlap_sources"] == ["hammer"]
    hammer = next(
        item
        for item in receipt["component_measurements"]
        if item["component_id"] == "hammer"
    )
    assert hammer["kernel_checks"] == 0
    assert hammer["unique_wins"] == 0
    assert hammer["overlap_zero_marginal"] is True
    assert hammer["unnecessary_work"] is True

    rates = {
        item["metric_id"]: item
        for item in statistics.build_causal_rescue_rate_bundle(
            metrics.aggregate_causal_rescue_receipts((receipt,))
        )["rates"]
    }
    assert rates["hammer_overlap_rate"]["numerator"] == 1
    assert rates["hammer_overlap_rate"]["denominator"] == 1
    assert rates["hammer_causal_rescue_rate"]["numerator"] == 0
    assert rates["hammer_causal_rescue_rate"]["denominator"] == 1
    assert rates["hammer_unnecessary_work_rate"]["numerator"] == 1
    assert rates["hammer_unnecessary_work_rate"]["denominator"] == 1


@pytest.mark.parametrize(
    ("failure_code", "expected"),
    [
        ("leanstral_output_limit", "output_limit"),
        ("leanstral_schema_invalid", "schema"),
        ("leanstral_forbidden_construct", "forbidden_construct"),
        ("leanstral_provider_failure", "provider"),
        ("leanstral_timeout", "timeout"),
    ],
)
def test_leanstral_failure_codes_remain_separate(
    failure_code: str,
    expected: str,
) -> None:
    assert (
        metrics.classify_leanstral_failure_code(failure_code).value
        == expected
    )

    with pytest.raises(
        metrics.MetricsContractError,
        match="not split and preregistered",
    ):
        metrics.classify_leanstral_failure_code("generic_model_failure")
