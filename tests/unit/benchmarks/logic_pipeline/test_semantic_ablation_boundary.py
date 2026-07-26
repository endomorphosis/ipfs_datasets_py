"""Synthetic tests for the G200 source-only ablation trust boundary.

These fixtures are constructed in memory.  The reviewed combined corpus and
the sealed holdout are intentionally never opened by this module.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.logic_pipeline import ablation, adapters, cases, contracts
from benchmarks.logic_pipeline.content_addressing import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_dag_json,
)


_SOURCE = "Every licensed person may enter. Alice is licensed."
_MODAL_IR = {
    "formulas": [
        {
            "operator": {"family": "deontic"},
            "predicate": {
                "name": "enter",
                "arguments": ["person:alice"],
            },
        }
    ]
}


def _review(*, notes: str = "synthetic review") -> cases.ReviewAttestation:
    return cases.ReviewAttestation(
        schema=cases.REVIEW_SCHEMA,
        status="approved",
        reviewer_ids=("semantic-reviewer", "proof-reviewer"),
        review_method="manual_deductive_review",
        semantic_target_approved=True,
        proof_obligation_approved=True,
        model_output_used=False,
        notes=notes,
    )


def _reviewed_case() -> cases.BenchmarkCase:
    return cases.BenchmarkCase(
        schema=cases.CASE_SCHEMA,
        case_id="synthetic-source-only",
        split=contracts.Split.PILOT,
        stratum="synthetic",
        difficulty=cases.Difficulty.EASY,
        source_text=_SOURCE,
        source_sha256=hashlib.sha256(_SOURCE.encode("utf-8")).hexdigest(),
        expected_class=cases.ExpectedClass.PROVED,
        expected_ir={"logic": "deontic", "target": "enter"},
        required_predicates=("enter",),
        required_entities=("alice",),
        proof_obligation={
            "kind": "theorem",
            "logic": "deontic",
            "target": "enter",
        },
        negative_controls=(),
        provenance={
            "source_kind": "synthetic",
            "source_ref": "unit-test",
            "license": "test-only",
            "ground_truth_method": "manual",
            "model_generated_ground_truth": False,
            "prompt_exposure": "none",
        },
        review=_review(),
    )


def _forged_reviewed_case() -> cases.BenchmarkCase:
    """Return the same source with every evaluator-side answer changed."""

    return replace(
        _reviewed_case(),
        expected_class=cases.ExpectedClass.DISPROVED,
        expected_ir={"logic": "temporal", "target": "forged_target"},
        required_predicates=("forged_target",),
        required_entities=("mallory",),
        proof_obligation={
            "kind": "countermodel",
            "logic": "temporal",
            "target": "forged_target",
        },
        negative_controls=("forged-control",),
        provenance={
            "source_kind": "synthetic",
            "source_ref": "forged-unit-test",
            "license": "test-only",
            "ground_truth_method": "manual-forgery",
            "model_generated_ground_truth": False,
            "prompt_exposure": "forged",
        },
        review=_review(notes="forged evaluator answers"),
    )


def _semantic_plan(case: cases.BenchmarkCase) -> ablation.AblationPlan:
    return ablation.build_semantic_ablation_plan(
        "synthetic-semantic-v2",
        (case,),
        case_manifest_sha256="a" * 64,
        split=contracts.Split.PILOT,
        seed=17,
        variant_ids=("A5",),
        cache_modes=(contracts.CacheMode.COLD,),
        environment_sha256="b" * 64,
    )


class _RequestRecorder:
    def __init__(self) -> None:
        self.requests: dict[
            contracts.StageName, list[adapters.StageRequest]
        ] = {stage: [] for stage in contracts.StageName}

    def mapping(
        self,
        *,
        adapter_version: str = "2",
    ) -> dict[contracts.StageName, adapters.StageAdapter]:
        return {
            stage: adapters.StageAdapter(
                stage,
                handler=self._handler(stage),
                adapter_version=adapter_version,
            )
            for stage in contracts.StageName
        }

    def _handler(self, stage: contracts.StageName):
        def handler(request: adapters.StageRequest) -> adapters.StageOutput:
            self.requests[stage].append(request)
            source_text = request.input_data["text"]
            assert isinstance(source_text, str)
            evidence_cid = cid_for_dag_json(_MODAL_IR)
            producer_id = {
                contracts.StageName.COMPILER: "compiler",
                contracts.StageName.SPACY: "spacy_full_model",
                contracts.StageName.SYMAI: "symai",
            }.get(stage)
            if producer_id is None:
                raise AssertionError("proof stages must remain suppressed")
            if stage is contracts.StageName.SYMAI:
                validated_response = {
                    "logic_family": "deontic",
                    "target": "enter",
                    "class": "proved",
                    "predicates": ["enter"],
                    "entities": ["alice"],
                    "completeness": {
                        field: True
                        for field in (
                            contracts.SEMANTIC_PROJECTION_COMPLETENESS_FIELDS_V2
                        )
                    },
                    "ambiguity_flags": [],
                    "confidence_millionths": 900_000,
                    "validation_errors": [],
                }
                evidence_cid = cid_for_dag_json(validated_response)
            projection = contracts.SemanticProjection.create(
                producer_id=producer_id,
                source_text=source_text,
                logic_family="deontic",
                target="enter",
                semantic_class="proved",
                predicates=("enter",),
                entities=("alice",),
                confidence_millionths=900_000,
                evidence_cid=evidence_cid,
            )
            if stage is contracts.StageName.COMPILER:
                data = {
                    "schema": (
                        "ipfs-datasets.logic-pipeline-benchmark."
                        "compiler-output.v2"
                    ),
                    "semantic_protocol_cid": (
                        contracts.SEMANTIC_PROTOCOL_V2_CID
                    ),
                    "source_cid": request.source_cid,
                    "modal_ir": _MODAL_IR,
                    "modal_ir_cid": evidence_cid,
                    "modal_ir_canonical_bytes": len(
                        canonical_dag_json_bytes(_MODAL_IR)
                    ),
                    "retained_modal_ir_cid": evidence_cid,
                    "retained_modal_ir_canonical_bytes": len(
                        canonical_dag_json_bytes(_MODAL_IR)
                    ),
                    "semantic_projection": projection.to_dict(),
                }
            elif stage is contracts.StageName.SPACY:
                data = {
                    "schema": adapters.SPACY_EVIDENCE_SCHEMA_V2,
                    "semantic_protocol_cid": (
                        contracts.SEMANTIC_PROTOCOL_V2_CID
                    ),
                    "document": {
                        "source_cid": request.source_cid,
                        "normalized_text": source_text,
                    },
                    "modal_ir": _MODAL_IR,
                    "modal_ir_cid": evidence_cid,
                    "semantic_projection": projection.to_dict(),
                }
            else:
                raw_output = json.dumps(
                    validated_response,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                data = {
                    "schema": adapters.SYMAI_EVIDENCE_SCHEMA_V2,
                    "semantic_protocol_cid": (
                        contracts.SEMANTIC_PROTOCOL_V2_CID
                    ),
                    "source_cid": request.source_cid,
                    "raw_output": raw_output,
                    "raw_output_cid": cid_for_bytes(
                        raw_output.encode("utf-8")
                    ),
                    "validated_response": validated_response,
                    "validated_response_cid": evidence_cid,
                    "semantic_projection": projection.to_dict(),
                }
            return adapters.StageOutput(
                data=data,
                effective_identity={
                    **dict(request.requested_identity),
                    **(
                        {"mode": "full_model"}
                        if stage is contracts.StageName.SPACY
                        else {}
                    ),
                },
            )

        return handler


def test_semantic_case_projection_never_stores_reviewed_fields() -> None:
    reviewed = _reviewed_case()
    forged = _forged_reviewed_case()

    projected = ablation.AblationCase.from_benchmark_case_semantic_v2(
        reviewed
    )
    forged_projected = (
        ablation.AblationCase.from_benchmark_case_semantic_v2(forged)
    )

    assert ablation._thaw(projected.input_data) == {"text": _SOURCE}
    assert projected == forged_projected
    assert _semantic_plan(reviewed) == _semantic_plan(forged)


def test_semantic_execution_is_source_only_and_suppresses_g210_proofs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ablation, "_unix_time_ms", lambda: 1_000)
    recorder = _RequestRecorder()
    plan = _semantic_plan(_reviewed_case())
    root = tmp_path / "semantic-v2"

    run = ablation.execute_semantic_ablation(
        plan,
        recorder.mapping(),
        output_root=root,
        resume=False,
    )

    for stage in (
        contracts.StageName.COMPILER,
        contracts.StageName.SPACY,
        contracts.StageName.SYMAI,
    ):
        assert len(recorder.requests[stage]) == 1
        request = recorder.requests[stage][0]
        assert request.input_data == {"text": _SOURCE}
        assert (
            request.semantic_protocol_cid
            == contracts.SEMANTIC_PROTOCOL_V2_CID
        )
        assert request.source_cid is not None
        assert request.proof_context is None
        assert request.proof_context_cid is None

    for stage in (
        contracts.StageName.HAMMER,
        contracts.StageName.LEANSTRAL,
        contracts.StageName.KERNEL,
    ):
        assert recorder.requests[stage] == []
        record = next(item for item in run.results[0].stages if item.stage is stage)
        assert record.provenance.effective_identity["graph_invoked"] is False
        assert (
            record.provenance.effective_identity["policy_reason"]
            == ablation.SEMANTIC_V2_PROOF_SUPPRESSION_REASON
        )
        assert record.data["reason"] == (
            ablation.SEMANTIC_V2_PROOF_SUPPRESSION_REASON
        )

    profile = json.loads(
        (root / "state" / "semantic-execution-profile.json").read_text(
            encoding="utf-8"
        )
    )
    assert (
        profile["semantic_protocol_cid"]
        == contracts.SEMANTIC_PROTOCOL_V2_CID
    )
    assert profile["producer_input_fields"] == ["text"]
    assert profile["profile_cid"].startswith("b")
    assert (
        ablation.validate_semantic_ablation_evidence(
            plan,
            output_root=root,
        ).results
        == run.results
    )
    with pytest.raises(
        ablation.AblationValidationError,
        match="cannot resume a semantic-v2 namespace",
    ):
        ablation.execute_ablation(
            plan,
            recorder.mapping(),
            output_root=root,
        )


def test_forged_evaluator_answers_cannot_change_model_facing_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ablation, "_unix_time_ms", lambda: 2_000)
    reviewed_recorder = _RequestRecorder()
    forged_recorder = _RequestRecorder()
    reviewed_plan = _semantic_plan(_reviewed_case())
    forged_plan = _semantic_plan(_forged_reviewed_case())

    ablation.execute_semantic_ablation(
        reviewed_plan,
        reviewed_recorder.mapping(),
        output_root=tmp_path / "reviewed",
        resume=False,
    )
    ablation.execute_semantic_ablation(
        forged_plan,
        forged_recorder.mapping(),
        output_root=tmp_path / "forged",
        resume=False,
    )

    for stage in (
        contracts.StageName.COMPILER,
        contracts.StageName.SPACY,
        contracts.StageName.SYMAI,
    ):
        assert reviewed_recorder.requests[stage] == forged_recorder.requests[
            stage
        ]

    reviewed_request = reviewed_recorder.requests[
        contracts.StageName.SYMAI
    ][0]
    forged_request = forged_recorder.requests[contracts.StageName.SYMAI][0]
    config = adapters.SymaiAdapterConfig(
        semantic_protocol_cid=contracts.SEMANTIC_PROTOCOL_V2_CID
    )
    reviewed_namespace = adapters._symai_cache_namespace(reviewed_request)
    forged_namespace = adapters._symai_cache_namespace(forged_request)
    reviewed_prompt = adapters._symai_prompt(
        _SOURCE,
        reviewed_namespace,
        semantic_protocol_cid=contracts.SEMANTIC_PROTOCOL_V2_CID,
    )
    forged_prompt = adapters._symai_prompt(
        _SOURCE,
        forged_namespace,
        semantic_protocol_cid=contracts.SEMANTIC_PROTOCOL_V2_CID,
    )

    assert reviewed_prompt == forged_prompt
    assert adapters._symai_cache_key(
        reviewed_request,
        config,
        reviewed_namespace,
    ) == adapters._symai_cache_key(
        forged_request,
        config,
        forged_namespace,
    )
    assert adapters.build_modal_semantic_projection_v2(
        producer_id="compiler",
        source_text=reviewed_request.input_data["text"],
        modal_ir=_MODAL_IR,
    ) == adapters.build_modal_semantic_projection_v2(
        producer_id="compiler",
        source_text=forged_request.input_data["text"],
        modal_ir=_MODAL_IR,
    )


def test_semantic_execution_rejects_rich_cases_before_backend_or_write(
    tmp_path: Path,
) -> None:
    rich_case = ablation.AblationCase.create(
        "synthetic-rich-case",
        {
            "text": _SOURCE,
            "expected_class": "proved",
            "expected_ir": {"logic": "deontic", "target": "enter"},
            "proof_obligation": {
                "kind": "theorem",
                "logic": "deontic",
                "target": "enter",
            },
        },
    )
    plan = ablation.build_ablation_plan(
        "synthetic-rich-v1",
        (rich_case,),
        case_manifest_sha256="a" * 64,
        split=contracts.Split.PILOT,
        seed=5,
        variant_ids=("A5",),
        cache_modes=(contracts.CacheMode.COLD,),
    )
    recorder = _RequestRecorder()
    root = tmp_path / "must-not-exist"

    with pytest.raises(
        ablation.AblationValidationError,
        match="must store only the canonical",
    ):
        ablation.execute_semantic_ablation(
            plan,
            recorder.mapping(),
            output_root=root,
            resume=False,
        )

    assert not root.exists()
    assert all(not requests for requests in recorder.requests.values())


def test_semantic_execution_rejects_revision_1_adapters_before_write(
    tmp_path: Path,
) -> None:
    recorder = _RequestRecorder()
    plan = _semantic_plan(_reviewed_case())
    root = tmp_path / "must-not-exist"

    with pytest.raises(
        ablation.AblationValidationError,
        match="requires adapter version 2",
    ):
        ablation.execute_semantic_ablation(
            plan,
            recorder.mapping(adapter_version="1"),
            output_root=root,
            resume=False,
        )

    assert not root.exists()
    assert all(not requests for requests in recorder.requests.values())
