"""Live-shape regression tests for semantic scorer calibration.

The tests load only the explicitly unsealed pilot/development corpus boundary.
Producer requests contain source material only; reviewed labels are never
read or supplied to an adapter.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from benchmarks.logic_pipeline import adapters
from benchmarks.logic_pipeline import runtime
from benchmarks.logic_pipeline.cases import (
    FROZEN_CORPUS_MANIFEST_SHA256,
    BenchmarkCase,
    load_unsealed_pilot_development,
)
from benchmarks.logic_pipeline.contracts import (
    StageName,
    StageStatus,
    canonical_json,
)
from benchmarks.logic_pipeline.semantic_reassessment import (
    SemanticReassessmentError,
    validate_label_blind_semantic_input_binding,
    validate_normalized_semantic_stage_contract,
)


_RUN_ID = "semantic-contract-calibration"
_ENVIRONMENT_SHA256 = "e" * 64


def _unsealed_case() -> BenchmarkCase:
    _manifest, cases = load_unsealed_pilot_development()
    assert cases
    return cases[0]


def _source_only_request(
    case: BenchmarkCase,
    *,
    variant_id: str = "A0",
) -> adapters.StageRequest:
    return adapters.StageRequest(
        run_id=_RUN_ID,
        case_id=case.case_id,
        case_manifest_sha256=FROZEN_CORPUS_MANIFEST_SHA256,
        variant_id=variant_id,
        split=case.split,
        input_data={"text": case.source_text},
        requested_identity={"graph_invoked": True},
        environment_sha256=_ENVIRONMENT_SHA256,
    )


def test_live_compiler_shape_fails_closed_without_normalized_contract() -> None:
    case = _unsealed_case()
    request = _source_only_request(case)
    record = adapters.CompilerAdapter(
        runtime._current_compiler_handler
    ).run(request)

    assert record.status is StageStatus.SUCCESS
    assert record.stage is StageName.COMPILER
    assert record.provenance.input_sha256 == request.input_sha256
    assert record.data["compiled_obligation"] is None
    assert set(record.data["modal_ir"]) >= {
        "document_id",
        "formulas",
        "normalized_text",
    }
    assert (
        validate_label_blind_semantic_input_binding(record, case)
        == request.input_sha256
    )

    with pytest.raises(
        SemanticReassessmentError,
        match=(
            r"uncalibrated for compiler:.*observed_logics, "
            r"observed_targets; semantic-quality receipt cannot be minted"
        ),
    ):
        validate_normalized_semantic_stage_contract(record)


def test_live_regex_spacy_shape_fails_closed_without_normalized_contract() -> None:
    case = _unsealed_case()
    request = _source_only_request(case)
    record = adapters.SpacyAdapter(
        config=adapters.SpacyAdapterConfig(
            mode=adapters.SpacyAdapterMode.REGEX_LEGAL
        )
    ).run(request)

    assert record.status is StageStatus.SUCCESS
    assert record.stage is StageName.SPACY
    assert record.provenance.input_sha256 == request.input_sha256
    assert record.data["schema"] == adapters.SPACY_EVIDENCE_SCHEMA
    assert set(record.data["modal_ir"]) >= {
        "document_id",
        "formulas",
        "normalized_text",
    }
    assert (
        validate_label_blind_semantic_input_binding(record, case)
        == request.input_sha256
    )

    with pytest.raises(
        SemanticReassessmentError,
        match=(
            r"uncalibrated for spacy:.*observed_logics, "
            r"observed_targets; semantic-quality receipt cannot be minted"
        ),
    ):
        validate_normalized_semantic_stage_contract(record)


class _PropositionsOnlyEngine:
    """Return the exact candidate shape allowed by the strict response schema."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def forward(self, argument: object):
        prompt = argument.prop.prepared_input
        assert isinstance(prompt, str)
        self.prompts.append(prompt)
        raw = json.dumps(
            {
                "candidate_ir": {
                    "propositions": ["an agency has a legal obligation"]
                },
                "normalized_predicates": ["has_legal_obligation"],
                "quantifiers": [],
                "entities": ["agency"],
                "ambiguity_flags": [],
                "confidence": 0.75,
                "validation_errors": [],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return [raw], {
            "backend": "test_existing_router",
            "effective_provider_name": "ipfs_accelerate_py",
            "effective_model_name": "leanstral-calibration-test",
        }


def test_strict_symai_live_shape_is_label_blind_but_not_score_calibrated() -> None:
    case = _unsealed_case()
    engine = _PropositionsOnlyEngine()
    request = _source_only_request(case, variant_id="A4")
    record = adapters.SymaiAdapter(
        config=adapters.SymaiAdapterConfig(
            provider="ipfs_accelerate_py",
            model="leanstral-calibration-test",
            max_retries=0,
            cache_enabled=False,
        ),
        engine_factory=lambda _config, _namespace: engine,
        trace_getter=lambda: {},
    ).run(request)

    assert record.status is StageStatus.SUCCESS
    assert record.stage is StageName.SYMAI
    assert record.provenance.input_sha256 == request.input_sha256
    assert record.to_dict()["data"]["candidate_ir"] == {
        "propositions": ["an agency has a legal obligation"]
    }
    assert (
        validate_label_blind_semantic_input_binding(record, case)
        == request.input_sha256
    )
    assert len(engine.prompts) == 1
    assert case.source_text in engine.prompts[0]
    for forbidden in (
        "expected_class",
        "expected_ir",
        "proof_obligation",
        "negative_controls",
        "required_predicates",
        "required_entities",
    ):
        assert forbidden not in engine.prompts[0]

    with pytest.raises(
        SemanticReassessmentError,
        match=(
            r"uncalibrated for symai:.*observed_logics, "
            r"observed_targets; semantic-quality receipt cannot be minted"
        ),
    ):
        validate_normalized_semantic_stage_contract(record)


def test_reviewed_fields_in_producer_digest_fail_label_isolation() -> None:
    case = _unsealed_case()
    source_record = adapters.CompilerAdapter(
        runtime._current_compiler_handler
    ).run(_source_only_request(case))
    unsafe_input_sha256 = hashlib.sha256(
        canonical_json(
            {
                "text": case.source_text,
                "expected_class": "fabricated-test-label",
                "expected_ir": {
                    "logic": "fabricated-test-logic",
                    "target": "fabricated-test-target",
                },
                "proof_obligation": {
                    "goal": "fabricated-test-obligation"
                },
            }
        ).encode("utf-8")
    ).hexdigest()
    unsafe_record = replace(
        source_record,
        provenance=replace(
            source_record.provenance,
            input_sha256=unsafe_input_sha256,
        ),
    )

    with pytest.raises(
        SemanticReassessmentError,
        match=(
            r"not bound to the canonical label-blind source-only envelope "
            r"for compiler"
        ),
    ):
        validate_label_blind_semantic_input_binding(unsafe_record, case)


def test_explicit_normalized_logic_and_target_are_score_calibrated() -> None:
    case = _unsealed_case()
    modal_ir = {
        "logic_family": "deontic",
        "semantic_target": "source_derived_obligation",
        "predicates": ["has_legal_obligation"],
        "entities": ["agency"],
    }
    record = adapters.CompilerAdapter(
        lambda _request: adapters.StageOutput(
            data={
                "schema": (
                    "ipfs-datasets.logic-pipeline-benchmark."
                    "compiler-output.v1"
                ),
                "modal_ir": modal_ir,
                "modal_ir_sha256": hashlib.sha256(
                    canonical_json(modal_ir).encode("utf-8")
                ).hexdigest(),
            },
            effective_identity={"graph_invoked": True},
        )
    ).run(_source_only_request(case))

    validate_label_blind_semantic_input_binding(record, case)
    projection = validate_normalized_semantic_stage_contract(record)

    assert projection["observed_logics"] == ["deontic"]
    assert projection["observed_targets"] == [
        "source_derived_obligation"
    ]
