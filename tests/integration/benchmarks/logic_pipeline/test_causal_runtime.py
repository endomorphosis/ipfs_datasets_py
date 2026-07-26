"""Synthetic integration tests for the receipt-bearing G210 runtime bridge.

No benchmark fixture, corpus, or holdout data is loaded by this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
import copy
from dataclasses import replace
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmarks.logic_pipeline import (
    adapters,
    capabilities,
    contracts,
    runtime,
    variants,
)
from benchmarks.logic_pipeline import causal_runtime
from benchmarks.logic_pipeline.causal_runtime import (
    CausalRuntimeBridgeError,
    CompilerReferenceExposureV2,
    execute_causal_runtime_case_v2,
    validate_causal_runtime_evidence_v2,
)
from benchmarks.logic_pipeline.content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
    sha256_digest_for_cid,
)


RUN_ID = "synthetic-causal-runtime"
CASE_ID = "synthetic-case"
MANIFEST_SHA256 = "a" * 64
ENVIRONMENT_SHA256 = "b" * 64
SOURCE_TEXT = (
    "Every archivist is trained. Ada is an archivist. "
    "Therefore Ada is trained."
)
PROOF_CONTEXT: dict[str, object] = {
    "obligation_id": "synthetic-reviewed-obligation",
    "proof_obligation": {
        "kind": "theorem",
        "logic": "fol",
        "target": "trained",
    },
}


class _SyntheticKernelSupervisor:
    """In-process process-owner double that retains exact rendered sources."""

    def __init__(
        self,
        root: Path,
        *,
        expected_proof: str | tuple[str, ...],
        returncode: int | tuple[int, ...] = 0,
    ) -> None:
        self.root = root
        self.expected_proofs = (
            (expected_proof,)
            if isinstance(expected_proof, str)
            else expected_proof
        )
        self.returncodes = (
            (returncode,) * len(self.expected_proofs)
            if isinstance(returncode, int)
            else returncode
        )
        if len(self.expected_proofs) != len(self.returncodes):
            raise ValueError("synthetic kernel outcomes must align")
        self.active_process_count = 0
        self.sources: list[str] = []
        self.closed = False

    @contextmanager
    def temporary_directory(self, **_kwargs: object):
        directory = self.root / f"native-check-{len(self.sources)}"
        directory.mkdir()
        yield str(directory)

    def run(self, command: object, **kwargs: object) -> object:
        index = len(self.sources)
        source = Path(str(kwargs["cwd"])) / "Main.lean"
        rendered = source.read_text(encoding="utf-8")
        assert f"by\n  {self.expected_proofs[index]}" in rendered
        assert tuple(command)[1:3] == ("-j", "1")
        self.sources.append(rendered)
        returncode = self.returncodes[index]
        return SimpleNamespace(
            returncode=returncode,
            stdout="accepted" if returncode == 0 else "",
            stderr="" if returncode == 0 else "rejected",
            timed_out=False,
            cancelled=False,
            resource_exhausted=False,
            error=None,
            termination_reason="completed",
            process_group_reaped=True,
            wall_time_seconds=0.001,
        )

    def close(self) -> None:
        self.closed = True


def _compiler_payload(
    source_text: str,
    proof_context: dict[str, object],
    *,
    include_candidate: bool,
    non_ascii_note: str = "synthetic",
) -> tuple[dict[str, object], str | None]:
    proof_input = {"text": source_text, **proof_context}
    compiled = runtime.compile_reviewed_obligation(proof_input)
    assert compiled is not None
    translation = runtime._entailment_translation(
        proof_input,
        theorem_name=compiled.theorem_name,
        obligation_sha256=compiled.obligation_sha256,
        kind=compiled.kind,
        logic=compiled.logic,
        semantic_target=compiled.semantic_target,
    )
    certificate = (
        None
        if not include_candidate
        or translation is None
        or translation.native_proof_text is None
        else translation.native_proof_text
    )
    native_candidate = (
        None
        if certificate is None or translation is None
        else {
            "schema": runtime.NATIVE_PROOF_CANDIDATE_SCHEMA,
            "translation_sha256": translation.digest,
            "obligation_sha256": compiled.obligation_sha256,
            "source_sha256": translation.source_sha256,
            "derivation": translation.shape,
            "certificate": certificate,
            "authoritative": False,
            "requires_independent_kernel": True,
        }
    )
    return (
        {
            "compiled_obligation": compiled.to_dict(),
            "compiled_obligation_sha256": compiled.digest,
            "entailment_translation": (
                None if translation is None else translation.to_dict()
            ),
            "entailment_translation_sha256": (
                None if translation is None else translation.digest
            ),
            "native_proof_candidate": native_candidate,
            "synthetic_note": non_ascii_note,
        },
        certificate,
    )


def _semantic_compiler_record(
    payload: dict[str, object],
    *,
    source_text: str = SOURCE_TEXT,
    variant_id: str = "A0",
) -> contracts.StageRecord:
    request = adapters.StageRequest(
        run_id=RUN_ID,
        case_id=CASE_ID,
        case_manifest_sha256=MANIFEST_SHA256,
        variant_id=variant_id,
        split=contracts.Split.PILOT,
        cache_mode=contracts.CacheMode.COLD,
        input_data={"text": source_text},
        requested_identity=variants.get_variant_definition(
            variant_id
        ).requested_identity(contracts.StageName.COMPILER),
        environment_sha256=ENVIRONMENT_SHA256,
        source=("synthetic-causal-runtime-test",),
        semantic_protocol_cid=contracts.SEMANTIC_PROTOCOL_V2_CID,
    )
    adapter = adapters.StageAdapter(
        contracts.StageName.COMPILER,
        handler=lambda _request: adapters.StageOutput(
            data=payload,
            effective_identity={
                "implementation": "synthetic-compiler",
                "graph_invoked": True,
            },
        ),
    )
    invocation = adapter.invoke(request)
    return adapter.record(request, invocation)


def _compiler_exposure(
    payload: dict[str, object],
    certificate: str | None,
) -> CompilerReferenceExposureV2:
    record = _semantic_compiler_record(payload)
    exposure = CompilerReferenceExposureV2.from_compiler_record(
        record,
        source_text=SOURCE_TEXT,
    )
    assert (exposure.compiler_candidate is None) is (certificate is None)
    return exposure


def _semantic_result(
    exposure: CompilerReferenceExposureV2,
) -> contracts.CaseResultRecord:
    return contracts.CaseResultRecord.from_stages(
        (exposure.compiler_record,)
    )


def _semantic_frontend_result(
    payload: dict[str, object],
    *,
    source_text: str,
    variant_id: str = "A2",
) -> contracts.CaseResultRecord:
    compiler = _semantic_compiler_record(
        payload,
        source_text=source_text,
        variant_id=variant_id,
    )
    request = adapters.StageRequest(
        run_id=RUN_ID,
        case_id=CASE_ID,
        case_manifest_sha256=MANIFEST_SHA256,
        variant_id=variant_id,
        split=contracts.Split.PILOT,
        cache_mode=contracts.CacheMode.COLD,
        input_data={"text": source_text},
        requested_identity=variants.get_variant_definition(
            variant_id
        ).requested_identity(contracts.StageName.SPACY),
        environment_sha256=ENVIRONMENT_SHA256,
        upstream_stage_digests=(compiler.digest,),
        source=("synthetic-causal-runtime-test",),
        semantic_protocol_cid=contracts.SEMANTIC_PROTOCOL_V2_CID,
    )
    adapter = adapters.StageAdapter(
        contracts.StageName.SPACY,
        handler=lambda _request: adapters.StageOutput(
            data={"schema": adapters.SPACY_EVIDENCE_SCHEMA_V2},
            effective_identity={
                "implementation": "synthetic-spacy",
                "graph_invoked": True,
            },
        ),
    )
    spacy = adapter.run(request)
    records = [compiler, spacy]
    if (
        contracts.StageName.SYMAI
        in variants.get_variant_definition(variant_id).stages
    ):
        symai_request = replace(
            request,
            requested_identity=variants.get_variant_definition(
                variant_id
            ).requested_identity(contracts.StageName.SYMAI),
            upstream_stage_digests=tuple(
                record.digest for record in records
            ),
        )
        symai_adapter = adapters.StageAdapter(
            contracts.StageName.SYMAI,
            handler=lambda _request: adapters.StageOutput(
                data={
                    "schema": (
                        "ipfs-datasets.logic-pipeline-benchmark."
                        "policy-decision.v1"
                    ),
                    "stage": "symai",
                    "invoked": True,
                    "reason": "synthetic semantic policy evidence",
                    "invocation_index": 2,
                },
                effective_identity={
                    "implementation": "synthetic-symai",
                    "graph_invoked": True,
                },
            ),
        )
        records.append(symai_adapter.run(symai_request))
    return contracts.CaseResultRecord.from_stages(tuple(records))


def _execute_compiler_path(
    tmp_path: Path,
) -> tuple[object, _SyntheticKernelSupervisor]:
    payload, certificate = _compiler_payload(
        SOURCE_TEXT,
        PROOF_CONTEXT,
        include_candidate=True,
        non_ascii_note="café ∀",
    )
    assert certificate is not None
    exposure = _compiler_exposure(payload, certificate)
    runner = runtime.NativeKernelRunner(
        "/synthetic/lean",
        ENVIRONMENT_SHA256,
        tmp_path / "kernel-state",
    )
    supervisor = _SyntheticKernelSupervisor(
        tmp_path,
        expected_proof=certificate,
    )
    runner._supervisor = supervisor
    evidence = execute_causal_runtime_case_v2(
        _semantic_result(exposure),
        SOURCE_TEXT,
        PROOF_CONTEXT,
        exposure,
        {
            # Passing the exact full A0 live route is supported; the semantic
            # compiler adapter is deliberately not re-invoked by G210.
            contracts.StageName.COMPILER: adapters.StageAdapter(
                contracts.StageName.COMPILER,
                handler=None,
            ),
            contracts.StageName.KERNEL: adapters.StageAdapter(
                contracts.StageName.KERNEL,
                handler=runner,
            )
        },
    )
    return evidence, supervisor


def _rebase_case_result_and_evidence(
    persisted: dict[str, object],
) -> None:
    case_value = persisted["case_result"]
    assert isinstance(case_value, dict)
    case_value["receipt"] = None
    rebuilt = contracts.CaseResultRecord.from_dict(case_value)
    plain_case = causal_runtime._plain(rebuilt.to_dict())
    assert isinstance(plain_case, dict)
    persisted["case_result"] = plain_case
    persisted["case_result_cid"] = cid_for_dag_json(plain_case)
    selection = persisted["selection_receipt"]
    assert isinstance(selection, dict)
    persisted["causal_case_receipt"] = causal_runtime._plain(
        causal_runtime.build_causal_rescue_case_receipt(
            rebuilt,
            selection,
        )
    )
    persisted["receipt_cid"] = cid_for_dag_json(
        {
            key: value
            for key, value in persisted.items()
            if key != "receipt_cid"
        }
    )


def test_compiler_candidate_is_checked_once_and_persistently_replays(
    tmp_path: Path,
) -> None:
    evidence, supervisor = _execute_compiler_path(tmp_path)

    assert len(supervisor.sources) == 1
    assert evidence.selection_result.receipt["selected_source"] == "compiler"
    sidecars = evidence.selection_result.receipt["kernel_receipts"]
    assert len(sidecars) == 1
    assert len(sidecars[0]["receipt"]["candidate_attempts"]) == 1
    assert evidence.case_result.kernel_accepted is True
    assert (
        validate_causal_runtime_evidence_v2(evidence.to_dict()).receipt_cid
        == evidence.receipt_cid
    )


def test_live_hammer_overlap_uses_semantic_v2_cids_and_no_duplicate_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload, compiler_certificate = _compiler_payload(
        SOURCE_TEXT,
        PROOF_CONTEXT,
        include_candidate=True,
    )
    assert compiler_certificate is not None
    exposure = CompilerReferenceExposureV2.from_compiler_record(
        _semantic_compiler_record(payload),
        source_text=SOURCE_TEXT,
    )
    hammer_capability = capabilities.CapabilityRecord(
        capabilities.CapabilityKind.HAMMER,
        capabilities.CapabilityStatus.AVAILABLE,
        {
            "implementation": "synthetic-hammer",
            "solver": "cvc5",
            "solver_path": "/synthetic/cvc5",
        },
        ("synthetic-causal-runtime-test",),
    )

    def solver(
        _arguments: object,
        **_kwargs: object,
    ) -> capabilities.BoundedProcessResult:
        return capabilities.BoundedProcessResult(
            arguments=("/synthetic/cvc5", "--lang=smt2"),
            returncode=0,
            stdout="unsat\n",
            stderr="",
            timed_out=False,
            process_group_reaped=True,
        )

    monkeypatch.setattr(runtime, "run_bounded_process_group", solver)
    runner = runtime.NativeKernelRunner(
        "/synthetic/lean",
        ENVIRONMENT_SHA256,
        tmp_path / "kernel-state",
        expected_hammer_identity=hammer_capability.identity,
    )
    supervisor = _SyntheticKernelSupervisor(
        tmp_path,
        expected_proof=compiler_certificate,
        returncode=1,
    )
    runner._supervisor = supervisor
    evidence = execute_causal_runtime_case_v2(
        _semantic_frontend_result(payload, source_text=SOURCE_TEXT),
        SOURCE_TEXT,
        PROOF_CONTEXT,
        exposure,
        {
            contracts.StageName.HAMMER: adapters.StageAdapter(
                contracts.StageName.HAMMER,
                handler=runtime._hammer_live_handler(
                    hammer_capability
                ),
            ),
            contracts.StageName.KERNEL: adapters.StageAdapter(
                contracts.StageName.KERNEL,
                handler=runner,
            ),
        },
    )

    assert len(supervisor.sources) == 1
    assert evidence.selection_result.selected_source is None
    optional = evidence.selection_result.receipt[
        "optional_candidates"
    ][0]
    assert optional["overlap"] is True
    assert optional["causal_rescue"] is False
    assert optional["zero_credit_reason"] == "duplicate_certificate"
    sidecars = evidence.selection_result.receipt["kernel_receipts"]
    assert [len(item["receipt"]["candidate_attempts"]) for item in sidecars] == [1]
    hammer_record = next(
        stage
        for stage in evidence.case_result.stages
        if stage.stage is contracts.StageName.HAMMER
    )
    semantic_context_cid = hammer_record.provenance.effective_identity[
        "semantic_context_cid"
    ]
    assert semantic_context_cid.startswith("b")
    assert "semantic_context_sha256" not in (
        hammer_record.provenance.effective_identity
    )
    validate_causal_runtime_evidence_v2(evidence.to_dict())


def test_distinct_hammer_rescue_replays_its_later_semantic_context(
    tmp_path: Path,
) -> None:
    payload, compiler_certificate = _compiler_payload(
        SOURCE_TEXT,
        PROOF_CONTEXT,
        include_candidate=True,
    )
    assert compiler_certificate is not None
    exposure = CompilerReferenceExposureV2.from_compiler_record(
        _semantic_compiler_record(payload),
        source_text=SOURCE_TEXT,
    )
    hammer_certificate = "aesop"

    class _DistinctHammerKernelRunner(runtime.NativeKernelRunner):
        def _validated_hammer_candidate(
            self,
            request: adapters.StageRequest,
            _translation: runtime.ReviewedEntailmentTranslation | None,
        ) -> tuple[str, str] | None:
            artifact = request.artifact(contracts.StageName.HAMMER)
            if artifact is None:
                return None
            return hammer_certificate, artifact.digest

    runner = _DistinctHammerKernelRunner(
        "/synthetic/lean",
        ENVIRONMENT_SHA256,
        tmp_path / "kernel-state",
    )
    supervisor = _SyntheticKernelSupervisor(
        tmp_path,
        expected_proof=(compiler_certificate, hammer_certificate),
        returncode=(1, 0),
    )
    runner._supervisor = supervisor

    evidence = execute_causal_runtime_case_v2(
        _semantic_frontend_result(payload, source_text=SOURCE_TEXT),
        SOURCE_TEXT,
        PROOF_CONTEXT,
        exposure,
        {
            contracts.StageName.HAMMER: adapters.StageAdapter(
                contracts.StageName.HAMMER,
                handler=lambda _request: adapters.StageOutput(
                    data={"proof_text": hammer_certificate},
                    effective_identity={
                        "implementation": "synthetic-hammer",
                    },
                ),
            ),
            contracts.StageName.KERNEL: adapters.StageAdapter(
                contracts.StageName.KERNEL,
                handler=runner,
            ),
        },
    )

    assert len(supervisor.sources) == 2
    assert evidence.selection_result.selected_source == "hammer"
    assert evidence.case_result.kernel_accepted is True
    validate_causal_runtime_evidence_v2(evidence.to_dict())


def test_hammer_failure_then_distinct_leanstral_rescue_replays(
    tmp_path: Path,
) -> None:
    payload, compiler_certificate = _compiler_payload(
        SOURCE_TEXT,
        PROOF_CONTEXT,
        include_candidate=True,
    )
    assert compiler_certificate is not None
    exposure = CompilerReferenceExposureV2.from_compiler_record(
        _semantic_compiler_record(payload),
        source_text=SOURCE_TEXT,
    )
    leanstral_certificate = "aesop"

    class _DistinctLeanstralKernelRunner(runtime.NativeKernelRunner):
        def _validated_leanstral_candidate(
            self,
            request: adapters.StageRequest,
            _compiled: runtime.CompiledObligation,
        ) -> tuple[str, str] | None:
            artifact = request.artifact(contracts.StageName.LEANSTRAL)
            if artifact is None:
                return None
            return leanstral_certificate, artifact.digest

    runner = _DistinctLeanstralKernelRunner(
        "/synthetic/lean",
        ENVIRONMENT_SHA256,
        tmp_path / "kernel-state",
    )
    supervisor = _SyntheticKernelSupervisor(
        tmp_path,
        expected_proof=(compiler_certificate, leanstral_certificate),
        returncode=(1, 0),
    )
    runner._supervisor = supervisor
    evidence = execute_causal_runtime_case_v2(
        _semantic_frontend_result(
            payload,
            source_text=SOURCE_TEXT,
            variant_id="A3",
        ),
        SOURCE_TEXT,
        PROOF_CONTEXT,
        exposure,
        {
            contracts.StageName.HAMMER: adapters.StageAdapter(
                contracts.StageName.HAMMER,
                handler=lambda _request: adapters.StageOutput(
                    status=contracts.StageStatus.FAILED,
                    failure_code=(
                        contracts.FailureCode.PREMISE_SELECTION_MISS
                    ),
                    failure_detail="synthetic premise miss",
                ),
            ),
            contracts.StageName.LEANSTRAL: adapters.StageAdapter(
                contracts.StageName.LEANSTRAL,
                handler=lambda _request: adapters.StageOutput(
                    data={
                        "draft": {
                            "proof_text": leanstral_certificate,
                        }
                    },
                    effective_identity={
                        "implementation": "synthetic-leanstral",
                    },
                ),
            ),
            contracts.StageName.KERNEL: adapters.StageAdapter(
                contracts.StageName.KERNEL,
                handler=runner,
            ),
        },
    )

    assert len(supervisor.sources) == 2
    assert evidence.selection_result.selected_source == "leanstral"
    optional = evidence.selection_result.receipt["optional_candidates"]
    assert tuple(item["source"] for item in optional) == (
        "hammer",
        "leanstral",
    )
    assert optional[0]["failure_code"] == (
        "hammer_premise_selection_miss"
    )
    assert optional[1]["causal_rescue"] is True
    assert evidence.case_result.kernel_accepted is True
    validate_causal_runtime_evidence_v2(evidence.to_dict())


def test_leanstral_failure_then_hammer_acceptance_gets_zero_rescue_credit(
    tmp_path: Path,
) -> None:
    payload, compiler_certificate = _compiler_payload(
        SOURCE_TEXT,
        PROOF_CONTEXT,
        include_candidate=True,
    )
    assert compiler_certificate is not None
    exposure = CompilerReferenceExposureV2.from_compiler_record(
        _semantic_compiler_record(payload),
        source_text=SOURCE_TEXT,
    )
    hammer_certificate = "aesop"

    class _PostModelHammerKernelRunner(runtime.NativeKernelRunner):
        def _validated_hammer_candidate(
            self,
            request: adapters.StageRequest,
            _translation: runtime.ReviewedEntailmentTranslation | None,
        ) -> tuple[str, str] | None:
            artifact = request.artifact(contracts.StageName.HAMMER)
            if artifact is None:
                return None
            return hammer_certificate, artifact.digest

    runner = _PostModelHammerKernelRunner(
        "/synthetic/lean",
        ENVIRONMENT_SHA256,
        tmp_path / "kernel-state",
    )
    supervisor = _SyntheticKernelSupervisor(
        tmp_path,
        expected_proof=(compiler_certificate, hammer_certificate),
        returncode=(1, 0),
    )
    runner._supervisor = supervisor
    evidence = execute_causal_runtime_case_v2(
        _semantic_frontend_result(
            payload,
            source_text=SOURCE_TEXT,
            variant_id="A6",
        ),
        SOURCE_TEXT,
        PROOF_CONTEXT,
        exposure,
        {
            contracts.StageName.LEANSTRAL: adapters.StageAdapter(
                contracts.StageName.LEANSTRAL,
                handler=lambda _request: adapters.StageOutput(
                    data={"safe_failure_class": "timed_out"},
                    status=contracts.StageStatus.FAILED,
                    failure_code=(
                        contracts.FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
                    ),
                    failure_detail="synthetic model timeout",
                ),
            ),
            contracts.StageName.HAMMER: adapters.StageAdapter(
                contracts.StageName.HAMMER,
                handler=lambda _request: adapters.StageOutput(
                    data={"proof_text": hammer_certificate},
                    effective_identity={
                        "implementation": "synthetic-hammer",
                    },
                ),
            ),
            contracts.StageName.KERNEL: adapters.StageAdapter(
                contracts.StageName.KERNEL,
                handler=runner,
            ),
        },
    )

    assert len(supervisor.sources) == 2
    assert evidence.selection_result.selected_source == "hammer"
    optional = evidence.selection_result.receipt["optional_candidates"]
    assert tuple(item["source"] for item in optional) == (
        "leanstral",
        "hammer",
    )
    assert optional[0]["failure_code"] == "leanstral_timeout"
    assert optional[1]["accepted"] is True
    assert optional[1]["causal_rescue"] is False
    assert optional[1]["zero_credit_reason"] == (
        "post_model_failure_continuation"
    )
    assert evidence.case_result.kernel_accepted is True
    validate_causal_runtime_evidence_v2(evidence.to_dict())


def test_compiler_exposure_rejects_contradictory_legacy_input_digest() -> None:
    payload, _certificate = _compiler_payload(
        SOURCE_TEXT,
        PROOF_CONTEXT,
        include_candidate=True,
    )
    record = _semantic_compiler_record(payload)
    bad_record = replace(
        record,
        provenance=replace(
            record.provenance,
            input_sha256="0" * 64,
        ),
    )

    with pytest.raises(
        CausalRuntimeBridgeError,
        match="legacy input digest",
    ):
        CompilerReferenceExposureV2.from_compiler_record(
            bad_record,
            source_text=SOURCE_TEXT,
        )


def test_compiler_exposure_rejects_requested_identity_substitution() -> None:
    payload, _certificate = _compiler_payload(
        SOURCE_TEXT,
        PROOF_CONTEXT,
        include_candidate=True,
    )
    record = _semantic_compiler_record(payload)
    requested = dict(record.provenance.requested_identity)
    requested["configuration_sha256"] = "0" * 64
    substituted = replace(
        record,
        provenance=replace(
            record.provenance,
            requested_identity=requested,
        ),
    )

    with pytest.raises(
        CausalRuntimeBridgeError,
        match="frozen A0 compiler treatment",
    ):
        CompilerReferenceExposureV2.from_compiler_record(
            substituted,
            source_text=SOURCE_TEXT,
        )


def test_semantic_frontend_rejects_requested_policy_substitution() -> None:
    payload, _certificate = _compiler_payload(
        SOURCE_TEXT,
        PROOF_CONTEXT,
        include_candidate=False,
    )
    result = _semantic_frontend_result(
        payload,
        source_text=SOURCE_TEXT,
        variant_id="A4",
    )
    records = list(result.stages)
    assert records[-1].stage is contracts.StageName.SYMAI
    requested = dict(records[-1].provenance.requested_identity)
    requested["policy"] = "substituted-provider-route"
    records[-1] = replace(
        records[-1],
        provenance=replace(
            records[-1].provenance,
            requested_identity=requested,
        ),
    )
    substituted = contracts.CaseResultRecord.from_stages(tuple(records))

    with pytest.raises(
        CausalRuntimeBridgeError,
        match="frozen semantic treatment",
    ):
        causal_runtime._semantic_frontend(
            substituted,
            source_text=SOURCE_TEXT,
        )


def test_failed_compiler_record_cannot_claim_candidate_absence() -> None:
    payload, _certificate = _compiler_payload(
        SOURCE_TEXT,
        PROOF_CONTEXT,
        include_candidate=False,
    )
    record = _semantic_compiler_record(payload)
    failed_record = replace(
        record,
        status=contracts.StageStatus.FAILED,
        output_sha256=None,
        failure_code=contracts.FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
        failure_detail="synthetic compiler failure",
    )

    with pytest.raises(
        CausalRuntimeBridgeError,
        match="invoked A0 compiler",
    ):
        CompilerReferenceExposureV2.from_compiler_record(
            failed_record,
            source_text=SOURCE_TEXT,
        )


def test_invalid_coordinate_or_null_obligation_fails_before_adapter_call(
    tmp_path: Path,
) -> None:
    payload, certificate = _compiler_payload(
        SOURCE_TEXT,
        PROOF_CONTEXT,
        include_candidate=True,
    )
    exposure = _compiler_exposure(payload, certificate)
    calls: list[str] = []
    kernel = adapters.StageAdapter(
        contracts.StageName.KERNEL,
        handler=lambda _request: calls.append("kernel"),
    )
    mismatched_record = replace(
        exposure.compiler_record,
        case_manifest_sha256="c" * 64,
    )

    with pytest.raises(
        CausalRuntimeBridgeError,
        match="case/cache coordinate",
    ):
        execute_causal_runtime_case_v2(
            contracts.CaseResultRecord.from_stages(
                (mismatched_record,)
            ),
            SOURCE_TEXT,
            PROOF_CONTEXT,
            exposure,
            {contracts.StageName.KERNEL: kernel},
        )
    with pytest.raises(
        CausalRuntimeBridgeError,
        match="no reviewed obligation",
    ):
        execute_causal_runtime_case_v2(
            _semantic_result(exposure),
            SOURCE_TEXT,
            {
                "obligation_id": None,
                "proof_obligation": None,
            },
            exposure,
            {contracts.StageName.KERNEL: kernel},
        )
    assert calls == []


def test_compiler_artifact_raw_cid_covers_exact_legacy_non_ascii_bytes() -> None:
    payload, certificate = _compiler_payload(
        SOURCE_TEXT,
        PROOF_CONTEXT,
        include_candidate=True,
        non_ascii_note="café ∀",
    )
    exposure = _compiler_exposure(payload, certificate)
    artifact = exposure.artifact
    exact_bytes = contracts.canonical_json(artifact.to_dict()).encode("utf-8")
    artifact_cid = exposure.to_dict()["compiler_artifact_cid"]

    assert b"caf\\u00e9" in exact_bytes
    assert b"\\u2200" in exact_bytes
    assert artifact_cid == cid_for_bytes(exact_bytes)
    assert sha256_digest_for_cid(
        artifact_cid, codecs=("raw",)
    ) == hashlib.sha256(exact_bytes).hexdigest()
    assert exposure.compiler_candidate is not None
    assert exposure.compiler_candidate.artifact_cid == artifact_cid


def test_candidate_absence_is_measured_by_one_negative_kernel_check(
    tmp_path: Path,
) -> None:
    source_text = "A synthetic policy statement has no translatable rule."
    proof_context = {
        "obligation_id": "synthetic-untranslated-obligation",
        "proof_obligation": {
            "kind": "theorem",
            "logic": "fol",
            "target": "untranslated",
        },
    }
    payload, certificate = _compiler_payload(
        source_text,
        proof_context,
        include_candidate=False,
    )
    assert certificate is None
    record = _semantic_compiler_record(payload, source_text=source_text)
    exposure = CompilerReferenceExposureV2.from_compiler_record(
        record,
        source_text=source_text,
    )
    runner = runtime.NativeKernelRunner(
        "/synthetic/lean",
        ENVIRONMENT_SHA256,
        tmp_path / "kernel-state",
    )
    supervisor = _SyntheticKernelSupervisor(
        tmp_path,
        expected_proof="must not execute",
    )
    runner._supervisor = supervisor

    evidence = execute_causal_runtime_case_v2(
        contracts.CaseResultRecord.from_stages((record,)),
        source_text,
        proof_context,
        exposure,
        {
            contracts.StageName.KERNEL: adapters.StageAdapter(
                contracts.StageName.KERNEL,
                handler=runner,
            )
        },
    )

    assert supervisor.sources == []
    assert evidence.selection_result.receipt["selected_source"] is None
    assert not evidence.selection_result.receipt["kernel_receipts"]
    assert len(evidence.kernel_check_telemetry) == 1
    assert evidence.kernel_check_telemetry[0]["candidate_cid"] is None
    assert evidence.case_result.kernel_accepted is False
    validate_causal_runtime_evidence_v2(evidence.to_dict())


def test_optional_failure_is_bound_to_its_typed_stage_record(
    tmp_path: Path,
) -> None:
    source_text = "A synthetic statement has no usable solver premise."
    proof_context = {
        "obligation_id": "synthetic-hammer-failure",
        "proof_obligation": {
            "kind": "theorem",
            "logic": "fol",
            "target": "unprovable",
        },
    }
    payload, certificate = _compiler_payload(
        source_text,
        proof_context,
        include_candidate=False,
    )
    assert certificate is None
    exposure = CompilerReferenceExposureV2.from_compiler_record(
        _semantic_compiler_record(payload, source_text=source_text),
        source_text=source_text,
    )
    runner = runtime.NativeKernelRunner(
        "/synthetic/lean",
        ENVIRONMENT_SHA256,
        tmp_path / "kernel-state",
    )
    supervisor = _SyntheticKernelSupervisor(
        tmp_path,
        expected_proof="must not execute",
    )
    runner._supervisor = supervisor
    evidence = execute_causal_runtime_case_v2(
        _semantic_frontend_result(payload, source_text=source_text),
        source_text,
        proof_context,
        exposure,
        {
            contracts.StageName.HAMMER: adapters.StageAdapter(
                contracts.StageName.HAMMER,
                handler=lambda _request: adapters.StageOutput(
                    status=contracts.StageStatus.FAILED,
                    failure_code=(
                        contracts.FailureCode.PREMISE_SELECTION_MISS
                    ),
                    failure_detail="synthetic premise miss",
                ),
            ),
            contracts.StageName.KERNEL: adapters.StageAdapter(
                contracts.StageName.KERNEL,
                handler=runner,
            ),
        },
    )

    assert supervisor.sources == []
    optional = evidence.selection_result.receipt[
        "optional_candidates"
    ][0]
    assert optional["failure_code"] == "hammer_premise_selection_miss"
    assert optional["candidate_cid"] is None
    assert optional["artifact_cid"] is None
    restored = validate_causal_runtime_evidence_v2(evidence.to_dict())
    hammer_record = next(
        stage
        for stage in restored.case_result.stages
        if stage.stage is contracts.StageName.HAMMER
    )
    tampered = dict(optional)
    tampered["failure_code"] = "hammer_timeout"
    with pytest.raises(
        CausalRuntimeBridgeError,
        match="typed failure StageRecord",
    ):
        causal_runtime._proof_artifact_binding(
            stage=contracts.StageName.HAMMER,
            record=hammer_record,
            selection_record=tampered,
        )


@pytest.mark.parametrize(
    "tamper",
    (
        "proof_context",
        "compiler_provenance",
        "kernel_telemetry",
        "native_semantic_context",
        "multiple_candidate_attempts",
    ),
)
def test_persisted_evidence_rejects_bound_evidence_tampering(
    tmp_path: Path,
    tamper: str,
) -> None:
    evidence, _supervisor = _execute_compiler_path(tmp_path)
    persisted = copy.deepcopy(evidence.to_dict())

    if tamper == "proof_context":
        persisted["proof_context"]["obligation_id"] = "substituted"
    elif tamper == "compiler_provenance":
        persisted["compiler_reference_exposure"]["compiler_record"][
            "provenance"
        ]["effective_identity"]["source_cid"] = cid_for_bytes(b"substituted")
    elif tamper == "kernel_telemetry":
        persisted["kernel_check_telemetry"][0]["telemetry"][
            "bytes_in"
        ] += 1
    elif tamper == "native_semantic_context":
        persisted["selection_receipt"]["kernel_receipts"][0]["receipt"][
            "semantic_context_sha256"
        ] = "0" * 64
    else:
        sidecar = persisted["selection_receipt"]["kernel_receipts"][0]
        attempts = sidecar["receipt"]["candidate_attempts"]
        attempts.append(copy.deepcopy(attempts[0]))

    with pytest.raises(
        (CausalRuntimeBridgeError, contracts.ProtocolContractError, ValueError)
    ):
        validate_causal_runtime_evidence_v2(persisted)


@pytest.mark.parametrize(
    "tamper",
    (
        "compiler_reference_exposure_cid",
        "kernel_check_count",
        "configuration_sha256",
    ),
)
def test_rebased_terminal_provenance_tampering_is_rejected(
    tmp_path: Path,
    tamper: str,
) -> None:
    evidence, _supervisor = _execute_compiler_path(tmp_path)
    persisted = copy.deepcopy(evidence.to_dict())
    case_value = persisted["case_result"]
    assert isinstance(case_value, dict)
    stages = case_value["stages"]
    assert isinstance(stages, list)
    terminal = stages[-1]
    requested = terminal["provenance"]["requested_identity"]
    effective = terminal["provenance"]["effective_identity"]

    if tamper == "compiler_reference_exposure_cid":
        substituted = cid_for_dag_json({"substituted": "exposure"})
        requested[tamper] = substituted
        effective[tamper] = substituted
    elif tamper == "kernel_check_count":
        effective[tamper] += 1
    else:
        requested[tamper] = "0" * 64
    _rebase_case_result_and_evidence(persisted)

    with pytest.raises(
        CausalRuntimeBridgeError,
        match=(
            "semantic/proof boundary|terminal kernel identity|"
            "frozen causal treatment"
        ),
    ):
        validate_causal_runtime_evidence_v2(persisted)


def test_cid_bearing_runtime_evidence_is_deeply_immutable(
    tmp_path: Path,
) -> None:
    evidence, _supervisor = _execute_compiler_path(tmp_path)
    proof_obligation = evidence.proof_context["proof_obligation"]
    assert isinstance(proof_obligation, Mapping)
    with pytest.raises(TypeError):
        proof_obligation["target"] = "substituted"  # type: ignore[index]

    telemetry = evidence.kernel_check_telemetry[0]["telemetry"]
    assert isinstance(telemetry, Mapping)
    with pytest.raises(TypeError):
        telemetry["bytes_in"] = 999  # type: ignore[index]

    sidecars = evidence.selection_result.receipt["kernel_receipts"]
    assert isinstance(sidecars, tuple)
    assert isinstance(sidecars[0], Mapping)
    assert isinstance(sidecars[0]["receipt"], Mapping)
    attempts = sidecars[0]["receipt"]["candidate_attempts"]
    assert isinstance(attempts, tuple)
    with pytest.raises(AttributeError):
        attempts.append(attempts[0])
