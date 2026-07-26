"""Synthetic source-safe tests for the independent HSSL-G236 safety lane.

No benchmark fixture, corpus, manifest, or holdout data is loaded here.
"""

from __future__ import annotations

from collections.abc import Mapping
import copy
from dataclasses import replace
from pathlib import Path

import pytest

from benchmarks.logic_pipeline import adapters, contracts, runtime, variants
from benchmarks.logic_pipeline.adversarial import ControlKind
from benchmarks.logic_pipeline.causal_ablation import (
    CausalRescueCaseV2,
    CausalRescueManifestV2,
)
from benchmarks.logic_pipeline.causal_runtime import (
    CompilerReferenceExposureV2,
    execute_causal_runtime_case_v2,
)
from benchmarks.logic_pipeline.content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)
from benchmarks.logic_pipeline.reviewed_control import (
    G236_REQUIRED_CACHE_MODES,
    G236_REQUIRED_VARIANT_IDS,
    HSSLEV2367D38,
    REVIEWED_CONTROL_POLICY_V2_CID,
    ReviewedControlAttestationV2,
    ReviewedControlEntryV2,
    ReviewedControlIndexV2,
    ReviewedControlSafetyError,
    build_reviewed_control_index_v2,
    build_reviewed_control_safety_gate_v2,
    validate_reviewed_control_safety_gate_v2,
)
from tests.integration.benchmarks.logic_pipeline.test_causal_runtime import (
    ENVIRONMENT_SHA256,
    MANIFEST_SHA256,
    PROOF_CONTEXT,
    SOURCE_TEXT,
    _SyntheticKernelSupervisor,
    _compiler_payload,
)


RUN_ID = "synthetic-g236"
CASE_ID = "synthetic-g236-invalid-control"


def _compiler_record(
    payload: Mapping[str, object],
    *,
    cache_mode: contracts.CacheMode,
    variant_id: str,
) -> contracts.StageRecord:
    request = adapters.StageRequest(
        run_id=RUN_ID,
        case_id=CASE_ID,
        case_manifest_sha256=MANIFEST_SHA256,
        variant_id=variant_id,
        split=contracts.Split.PILOT,
        cache_mode=cache_mode,
        input_data={"text": SOURCE_TEXT},
        requested_identity=variants.get_variant_definition(
            variant_id
        ).requested_identity(contracts.StageName.COMPILER),
        environment_sha256=ENVIRONMENT_SHA256,
        source=("synthetic-g236-control-test",),
        semantic_protocol_cid=contracts.SEMANTIC_PROTOCOL_V2_CID,
    )
    adapter = adapters.StageAdapter(
        contracts.StageName.COMPILER,
        handler=lambda _request: adapters.StageOutput(
            data=payload,
            effective_identity={
                "implementation": "synthetic-g236-compiler",
                "graph_invoked": True,
            },
        ),
    )
    return adapter.run(request)


def _semantic_result(
    payload: Mapping[str, object],
    exposure: CompilerReferenceExposureV2,
    *,
    cache_mode: contracts.CacheMode,
    variant_id: str,
) -> contracts.CaseResultRecord:
    if variant_id == "A0":
        return contracts.CaseResultRecord.from_stages(
            (exposure.compiler_record,)
        )
    compiler = _compiler_record(
        payload,
        cache_mode=cache_mode,
        variant_id=variant_id,
    )
    definition = variants.get_variant_definition(variant_id)
    request = adapters.StageRequest(
        run_id=RUN_ID,
        case_id=CASE_ID,
        case_manifest_sha256=MANIFEST_SHA256,
        variant_id=variant_id,
        split=contracts.Split.PILOT,
        cache_mode=cache_mode,
        input_data={"text": SOURCE_TEXT},
        requested_identity=definition.requested_identity(
            contracts.StageName.SPACY
        ),
        environment_sha256=ENVIRONMENT_SHA256,
        upstream_stage_digests=(compiler.digest,),
        source=("synthetic-g236-control-test",),
        semantic_protocol_cid=contracts.SEMANTIC_PROTOCOL_V2_CID,
    )
    spacy = adapters.StageAdapter(
        contracts.StageName.SPACY,
        handler=lambda _request: adapters.StageOutput(
            data={"schema": adapters.SPACY_EVIDENCE_SCHEMA_V2},
            effective_identity={
                "implementation": "synthetic-g236-spacy",
                "graph_invoked": True,
            },
        ),
    ).run(request)
    records = [compiler, spacy]
    if contracts.StageName.SYMAI in definition.stages:
        symai_request = adapters.StageRequest(
            run_id=RUN_ID,
            case_id=CASE_ID,
            case_manifest_sha256=MANIFEST_SHA256,
            variant_id=variant_id,
            split=contracts.Split.PILOT,
            cache_mode=cache_mode,
            input_data={"text": SOURCE_TEXT},
            requested_identity=definition.requested_identity(
                contracts.StageName.SYMAI
            ),
            environment_sha256=ENVIRONMENT_SHA256,
            upstream_stage_digests=tuple(
                record.digest for record in records
            ),
            source=("synthetic-g236-control-test",),
            semantic_protocol_cid=contracts.SEMANTIC_PROTOCOL_V2_CID,
        )
        symai = adapters.StageAdapter(
            contracts.StageName.SYMAI,
            handler=lambda _request: adapters.StageOutput(
                data={
                    "schema": (
                        "ipfs-datasets.logic-pipeline-benchmark."
                        "policy-decision.v1"
                    ),
                    "stage": "symai",
                    "invoked": True,
                    "reason": "synthetic G236 policy evidence",
                    "invocation_index": 2,
                },
                effective_identity={
                    "implementation": "synthetic-g236-symai",
                    "graph_invoked": True,
                },
            ),
        ).run(symai_request)
        records.append(symai)
    return contracts.CaseResultRecord.from_stages(tuple(records))


def _failed_optional_adapter(
    stage: contracts.StageName,
) -> adapters.StageAdapter:
    if stage is contracts.StageName.HAMMER:
        output = adapters.StageOutput(
            status=contracts.StageStatus.FAILED,
            failure_code=contracts.FailureCode.PREMISE_SELECTION_MISS,
            failure_detail="synthetic invalid-control solver miss",
        )
    else:
        output = adapters.StageOutput(
            data={"safe_failure_class": "timed_out"},
            status=contracts.StageStatus.FAILED,
            failure_code=(
                contracts.FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
            ),
            failure_detail="synthetic invalid-control model timeout",
        )
    return adapters.StageAdapter(
        stage,
        handler=lambda _request: output,
    )


def _coordinate_evidence(
    root: Path,
    *,
    cache_mode: contracts.CacheMode,
    variant_ids: tuple[str, ...],
    kernel_returncode: int,
    namespace: str,
) -> tuple[object, ...]:
    payload, certificate = _compiler_payload(
        SOURCE_TEXT,
        dict(PROOF_CONTEXT),
        include_candidate=True,
        non_ascii_note="synthetic-g236",
    )
    assert certificate is not None
    exposure = CompilerReferenceExposureV2.from_compiler_record(
        _compiler_record(
            payload,
            cache_mode=cache_mode,
            variant_id="A0",
        ),
        source_text=SOURCE_TEXT,
    )
    evidence = []
    for variant_id in variant_ids:
        coordinate_root = (
            root
            / namespace
            / cache_mode.value
            / variant_id
        )
        coordinate_root.mkdir(parents=True)
        runner = runtime.NativeKernelRunner(
            "/synthetic/lean",
            ENVIRONMENT_SHA256,
            coordinate_root / "kernel-state",
        )
        runner._supervisor = _SyntheticKernelSupervisor(
            coordinate_root,
            expected_proof=certificate,
            returncode=kernel_returncode,
        )
        route = {
            stage: _failed_optional_adapter(stage)
            for stage in variants.get_causal_proof_variant_profile(
                variant_id
            ).optional_order
        }
        route[contracts.StageName.KERNEL] = adapters.StageAdapter(
            contracts.StageName.KERNEL,
            handler=runner,
        )
        evidence.append(
            execute_causal_runtime_case_v2(
                _semantic_result(
                    payload,
                    exposure,
                    cache_mode=cache_mode,
                    variant_id=variant_id,
                ),
                SOURCE_TEXT,
                PROOF_CONTEXT,
                exposure,
                route,
            )
        )
    return tuple(evidence)


def _reviewed_records(
    manifest: CausalRescueManifestV2,
    *,
    source_manifest_cid: str | None = None,
) -> tuple[
    ReviewedControlEntryV2,
    ReviewedControlAttestationV2,
    str,
    str,
]:
    review_authority_cid = cid_for_dag_json(
        {
            "schema": "synthetic-g236-review-authority.v1",
            "role": "independent-control-review",
        }
    )
    execution_authority_cid = cid_for_dag_json(
        {
            "schema": "synthetic-g236-execution-authority.v1",
            "role": "runtime-execution",
        }
    )
    attestation = ReviewedControlAttestationV2(
        case_id=CASE_ID,
        split=contracts.Split.PILOT,
        source_cid=cid_for_bytes(SOURCE_TEXT.encode("utf-8")),
        control_kind=ControlKind.CONTRADICTORY,
        source_manifest_cid=(
            manifest.source_manifest_cid
            if source_manifest_cid is None
            else source_manifest_cid
        ),
        rescue_manifest_cid=manifest.manifest_cid,
        review_authority_cid=review_authority_cid,
        execution_authority_cid=execution_authority_cid,
        review_basis_cid=cid_for_dag_json(
            {
                "schema": "synthetic-g236-review-basis.v1",
                "case_id": CASE_ID,
                "classification": "invalid_control",
            }
        ),
    )
    entry = ReviewedControlEntryV2(
        case_id=CASE_ID,
        split=contracts.Split.PILOT,
        source_cid=cid_for_bytes(SOURCE_TEXT.encode("utf-8")),
        control_kind=ControlKind.CONTRADICTORY,
        review_attestation_cid=attestation.attestation_cid,
        source_manifest_cid=attestation.source_manifest_cid,
        rescue_manifest_cid=manifest.manifest_cid,
    )
    return (
        entry,
        attestation,
        review_authority_cid,
        execution_authority_cid,
    )


@pytest.fixture(scope="module")
def reviewed_population(
    tmp_path_factory: pytest.TempPathFactory,
):
    root = tmp_path_factory.mktemp("synthetic-g236")
    evidence = tuple(
        item
        for cache_mode in G236_REQUIRED_CACHE_MODES
        for item in _coordinate_evidence(
            root,
            cache_mode=cache_mode,
            variant_ids=G236_REQUIRED_VARIANT_IDS,
            kernel_returncode=1,
            namespace="rejected",
        )
    )
    rescue_case = CausalRescueCaseV2(
        case_id=CASE_ID,
        split=contracts.Split.PILOT,
        source_cid=cid_for_bytes(SOURCE_TEXT.encode("utf-8")),
        obligation_id=str(PROOF_CONTEXT["obligation_id"]),
        proof_obligation=PROOF_CONTEXT[
            "proof_obligation"
        ],  # type: ignore[arg-type]
        optional_components=("hammer", "leanstral"),
        review_attestation_cid=cid_for_dag_json(
            {
                "schema": "synthetic-g236-rescue-review.v1",
                "case_id": CASE_ID,
            }
        ),
    )
    manifest = CausalRescueManifestV2(
        plan_cid=cid_for_dag_json(
            {"schema": "synthetic-g236-plan.v1"}
        ),
        source_manifest_cid=cid_for_dag_json(
            {"schema": "synthetic-g236-source-manifest.v1"}
        ),
        case_manifest_sha256=MANIFEST_SHA256,
        cases=(rescue_case,),
    )
    entry, attestation, review_authority, execution_authority = (
        _reviewed_records(manifest)
    )
    index = build_reviewed_control_index_v2(
        review_authority_cid=review_authority,
        execution_authority_cid=execution_authority,
        entries=(entry,),
        attestations=(attestation,),
    )
    accepted = _coordinate_evidence(
        root,
        cache_mode=contracts.CacheMode.COLD,
        variant_ids=("A0",),
        kernel_returncode=0,
        namespace="accepted",
    )[0]
    return {
        "root": root,
        "manifest": manifest,
        "entry": entry,
        "attestation": attestation,
        "index": index,
        "evidence": evidence,
        "accepted": accepted,
    }


def _forbid_new_bare_sha_fields(value: object) -> None:
    if isinstance(value, Mapping):
        assert not any(str(key).endswith("_sha256") for key in value)
        for member in value.values():
            _forbid_new_bare_sha_fields(member)
    elif isinstance(value, (tuple, list)):
        for member in value:
            _forbid_new_bare_sha_fields(member)


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _plain_json(member)
            for key, member in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_plain_json(member) for member in value]
    return value


def test_g236_marker_is_bounded_to_the_reviewed_control_lane() -> None:
    assert HSSLEV2367D38() == (
        "CID-addressed independently reviewed non-holdout controls with "
        "exact full-runtime joins and fatal terminal native-kernel authority"
    )


def test_reviewed_control_index_is_cid_native_and_round_trips(
    reviewed_population,
) -> None:
    index = reviewed_population["index"]
    assert isinstance(index, ReviewedControlIndexV2)
    assert index.required_coordinate_count == 26
    assert index.holdout_included is False
    assert index.entries[0].holdout_included is False
    assert index.attestations[0].holdout_included is False
    assert validate_cid(index.index_cid, codecs=("dag-json",))
    assert validate_cid(index.entries[0].entry_cid, codecs=("dag-json",))
    assert validate_cid(
        index.attestations[0].attestation_cid,
        codecs=("dag-json",),
    )
    assert validate_cid(
        index.entries[0].source_cid,
        codecs=("raw",),
    )
    assert (
        ReviewedControlIndexV2.from_dict(index.to_dict()).index_cid
        == index.index_cid
    )
    _forbid_new_bare_sha_fields(index.to_dict())


def test_zero_terminal_native_acceptances_passes_complete_population(
    reviewed_population,
) -> None:
    index = reviewed_population["index"]
    manifest = reviewed_population["manifest"]
    evidence = reviewed_population["evidence"]

    gate = build_reviewed_control_safety_gate_v2(
        index,
        (manifest,),
        evidence,
    )

    assert gate["status"] == "passed"
    assert gate["complete"] is True
    assert gate["passed"] is True
    assert gate["fatal"] is False
    assert gate["fully_observed"] is True
    assert gate["invalid_control_case_count"] == 1
    assert gate["required_coordinate_count"] == 26
    assert gate["observed_coordinate_count"] == 26
    assert (
        gate[
            "terminal_independent_native_kernel_acceptance_count"
        ]
        == 0
    )
    assert gate["failure_codes"] == ()
    assert all(
        item["terminal_native_kernel_accepted"] is False
        for item in gate["observations"]
    )
    assert (
        validate_reviewed_control_safety_gate_v2(
            gate,
            index,
            (manifest,),
            evidence,
        )["receipt_cid"]
        == gate["receipt_cid"]
    )
    _forbid_new_bare_sha_fields(gate)


def test_any_terminal_native_acceptance_is_fatal(
    reviewed_population,
) -> None:
    index = reviewed_population["index"]
    manifest = reviewed_population["manifest"]
    accepted = reviewed_population["accepted"]
    evidence = tuple(
        accepted
        if (
            item.case_result.variant_id == "A0"
            and item.case_result.cache_mode is contracts.CacheMode.COLD
        )
        else item
        for item in reviewed_population["evidence"]
    )

    gate = build_reviewed_control_safety_gate_v2(
        index,
        (manifest,),
        evidence,
    )

    assert gate["status"] == "failed"
    assert gate["complete"] is True
    assert gate["passed"] is False
    assert gate["fatal"] is True
    assert gate["fully_observed"] is True
    assert (
        gate[
            "terminal_independent_native_kernel_acceptance_count"
        ]
        == 1
    )
    assert gate["accepted_runtime_evidence_cids"] == (
        accepted.receipt_cid,
    )
    assert gate["failure_codes"] == (
        "invalid_control_terminal_native_kernel_acceptance",
    )


def test_missing_or_duplicate_runtime_coordinate_is_incomplete(
    reviewed_population,
) -> None:
    index = reviewed_population["index"]
    manifest = reviewed_population["manifest"]
    evidence = reviewed_population["evidence"]

    missing = build_reviewed_control_safety_gate_v2(
        index,
        (manifest,),
        evidence[:-1],
    )
    assert missing["status"] == "incomplete"
    assert missing["complete"] is False
    assert missing["passed"] is False
    assert missing["fatal"] is False
    assert len(missing["missing_coordinate_cids"]) == 1
    assert "required_runtime_coordinate_missing" in missing[
        "failure_codes"
    ]

    duplicated = build_reviewed_control_safety_gate_v2(
        index,
        (manifest,),
        (*evidence, evidence[0]),
    )
    assert duplicated["status"] == "incomplete"
    assert duplicated["complete"] is False
    assert "duplicate_runtime_coordinate" in duplicated[
        "failure_codes"
    ]
    assert "duplicate_runtime_evidence_receipt" in duplicated[
        "failure_codes"
    ]


def test_forged_or_duplicate_control_classification_fails_closed(
    reviewed_population,
) -> None:
    index = reviewed_population["index"]
    entry = reviewed_population["entry"]
    attestation = reviewed_population["attestation"]

    forged = copy.deepcopy(index.to_dict())
    forged["entries"][0]["source_cid"] = cid_for_bytes(b"forged")
    with pytest.raises(
        ReviewedControlSafetyError,
        match="CID or classification changed",
    ):
        ReviewedControlIndexV2.from_dict(forged)

    with pytest.raises(
        ReviewedControlSafetyError,
        match="sorted, unique",
    ):
        build_reviewed_control_index_v2(
            review_authority_cid=index.review_authority_cid,
            execution_authority_cid=index.execution_authority_cid,
            entries=(entry, entry),
            attestations=(attestation,),
        )


def test_stale_manifest_binding_and_caller_assertions_are_incomplete(
    reviewed_population,
) -> None:
    manifest = reviewed_population["manifest"]
    stale_source_manifest_cid = cid_for_dag_json(
        {"schema": "synthetic-stale-source-manifest.v1"}
    )
    entry, attestation, review_authority, execution_authority = (
        _reviewed_records(
            manifest,
            source_manifest_cid=stale_source_manifest_cid,
        )
    )
    stale_index = build_reviewed_control_index_v2(
        review_authority_cid=review_authority,
        execution_authority_cid=execution_authority,
        entries=(entry,),
        attestations=(attestation,),
    )

    stale = build_reviewed_control_safety_gate_v2(
        stale_index,
        (manifest,),
        reviewed_population["evidence"],
    )
    assert stale["status"] == "incomplete"
    assert "control_manifest_set_mismatch" in stale["failure_codes"]
    assert "control_index_manifest_binding_mismatch" in stale[
        "failure_codes"
    ]

    with pytest.raises(
        ReviewedControlSafetyError,
        match="caller classification claims",
    ):
        build_reviewed_control_index_v2(
            review_authority_cid=review_authority,
            execution_authority_cid=execution_authority,
            entries=(
                {
                    "case_id": CASE_ID,
                    "invalid_control": True,
                },
            ),  # type: ignore[arg-type]
            attestations=(attestation,),
        )

    caller_claim = build_reviewed_control_safety_gate_v2(
        reviewed_population["index"],
        (manifest,),
        reviewed_population["evidence"][:-1],
    )
    forged_gate = dict(caller_claim)
    forged_gate["passed"] = True
    forged_gate["status"] = "passed"
    forged_gate["receipt_cid"] = cid_for_dag_json(
        {
            key: _plain_json(value)
            for key, value in forged_gate.items()
            if key != "receipt_cid"
        }
    )
    with pytest.raises(
        ReviewedControlSafetyError,
        match="caller-asserted fields",
    ):
        validate_reviewed_control_safety_gate_v2(
            forged_gate,
            reviewed_population["index"],
            (manifest,),
            reviewed_population["evidence"][:-1],
        )


def test_holdout_same_authority_and_bare_sha_identifiers_are_rejected(
    reviewed_population,
) -> None:
    manifest = reviewed_population["manifest"]
    entry = reviewed_population["entry"]
    attestation = reviewed_population["attestation"]

    with pytest.raises(
        ReviewedControlSafetyError,
        match="pilot/development only",
    ):
        replace(entry, split=contracts.Split.HOLDOUT)

    with pytest.raises(
        ReviewedControlSafetyError,
        match="independent from execution",
    ):
        replace(
            attestation,
            execution_authority_cid=attestation.review_authority_cid,
        )

    with pytest.raises(
        ReviewedControlSafetyError,
        match="canonical CIDv1",
    ):
        replace(attestation, review_basis_cid="a" * 64)

    assert manifest.holdout_included is False
    assert REVIEWED_CONTROL_POLICY_V2_CID.startswith("b")
