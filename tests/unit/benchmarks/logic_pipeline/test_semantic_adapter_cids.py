"""Focused CID invariants at the semantic-v2 adapter boundary."""

from __future__ import annotations

from collections.abc import Mapping
import json

import pytest

from benchmarks.logic_pipeline.adapters import (
    _SEMANTIC_LOGIC_ALIASES_V2,
    _with_semantic_failure_receipt,
    build_modal_semantic_projection_v2,
    StageRequest,
    StageOutput,
    SymaiAdapter,
    SymaiAdapterConfig,
)
from benchmarks.logic_pipeline.content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
)
from benchmarks.logic_pipeline.contracts import (
    FailureCode,
    SEMANTIC_NORMALIZATION_V2_CID,
    SEMANTIC_PROTOCOL_V2_CID,
    SemanticProjection,
    StageName,
    StageStatus,
    semantic_normalization_spec_v2,
)


class _ExactResponseEngine:
    def __init__(self, response: str) -> None:
        self.response = response

    def forward(self, _argument: object) -> tuple[list[str], dict[str, str]]:
        return [self.response], {
            "effective_provider_name": "test_provider",
            "effective_model_name": "test_model",
        }


def test_runtime_logic_aliases_match_the_cid_bound_normalization_spec() -> None:
    normalization_spec = semantic_normalization_spec_v2()

    assert cid_for_dag_json(
        normalization_spec
    ) == SEMANTIC_NORMALIZATION_V2_CID
    assert _SEMANTIC_LOGIC_ALIASES_V2 == normalization_spec["logic_aliases"]
    for source_family, expected_family in (
        normalization_spec["logic_aliases"]
    ).items():
        projection = build_modal_semantic_projection_v2(
            producer_id="compiler",
            source_text="A source-derived target exists.",
            modal_ir={
                "formulas": [
                    {
                        "operator": {"family": source_family},
                        "predicate": {
                            "name": "target",
                            "arguments": [],
                        },
                    }
                ]
            },
        )
        assert projection.logic_family == expected_family


def test_symai_v2_binds_exact_source_and_raw_response_bytes() -> None:
    source_text = "  A permit holder must file.  "
    raw_response = (
        "  "
        + json.dumps(
            {
                "logic_family": "deontic",
                "target": "file",
                "class": "proved",
                "predicates": ["file"],
                "entities": ["permit_holder"],
                "completeness": {
                    "logic_family": True,
                    "target": True,
                    "class": True,
                    "predicates": True,
                    "entities": True,
                },
                "ambiguity_flags": [],
                "confidence_millionths": 900_000,
                "validation_errors": [],
            },
            separators=(",", ":"),
        )
        + "\n"
    )
    request = StageRequest(
        run_id="semantic-cid-test",
        case_id="source-whitespace",
        case_manifest_sha256="0" * 64,
        input_data={"text": source_text},
        semantic_protocol_cid=SEMANTIC_PROTOCOL_V2_CID,
    )
    adapter = SymaiAdapter(
        config=SymaiAdapterConfig(
            provider="test_provider",
            model="test_model",
            max_retries=0,
            semantic_protocol_cid=SEMANTIC_PROTOCOL_V2_CID,
        ),
        engine_factory=lambda _config, _namespace: _ExactResponseEngine(
            raw_response
        ),
        trace_getter=lambda: {},
        cache={},
    )

    record = adapter.run(request)

    assert record.status is StageStatus.SUCCESS
    assert isinstance(record.data, Mapping)
    persisted_data = record.to_dict()["data"]
    assert isinstance(persisted_data, dict)
    projection = SemanticProjection.from_dict(
        persisted_data["semantic_projection"]
    )
    assert projection.source_cid == request.source_cid
    assert projection.source_cid == cid_for_bytes(
        source_text.encode("utf-8")
    )
    assert persisted_data["raw_output"] == raw_response
    assert persisted_data["raw_output_cid"] == cid_for_bytes(
        raw_response.encode("utf-8")
    )


def test_symai_v2_oversized_failure_retains_full_cid_not_oversized_text() -> None:
    raw_response = "x" * 129
    request = StageRequest(
        run_id="semantic-cid-test",
        case_id="oversized-response",
        case_manifest_sha256="0" * 64,
        input_data={"text": "A permit holder must file."},
        semantic_protocol_cid=SEMANTIC_PROTOCOL_V2_CID,
    )
    adapter = SymaiAdapter(
        config=SymaiAdapterConfig(
            provider="test_provider",
            model="test_model",
            max_retries=0,
            max_raw_output_bytes=128,
            semantic_protocol_cid=SEMANTIC_PROTOCOL_V2_CID,
        ),
        engine_factory=lambda _config, _namespace: _ExactResponseEngine(
            raw_response
        ),
        trace_getter=lambda: {},
        cache={},
    )

    record = adapter.run(request)

    assert record.status is StageStatus.FAILED
    persisted_data = record.to_dict()["data"]
    assert isinstance(persisted_data, dict)
    assert persisted_data["raw_output"] is None
    assert persisted_data["raw_output_bytes"] == 129
    assert persisted_data["raw_output_retained_exactly"] is False
    assert persisted_data["raw_output_cid"] == cid_for_bytes(
        raw_response.encode("utf-8")
    )


@pytest.mark.parametrize(
    ("candidate_cid", "candidate_bytes", "expected_cid"),
    [
        (
            cid_for_bytes(b"unretained-response"),
            len(b"unretained-response"),
            cid_for_bytes(b"unretained-response"),
        ),
        ("not-a-canonical-cid", 19, None),
        (cid_for_dag_json({"raw": "response"}), 19, None),
        (cid_for_bytes(b"empty-count-is-invalid"), 0, None),
        (cid_for_bytes(b"missing-count"), None, None),
        (None, 19, None),
    ],
)
def test_unretained_symai_failure_copies_only_paired_canonical_raw_cid(
    candidate_cid: object,
    candidate_bytes: object,
    expected_cid: str | None,
) -> None:
    request = StageRequest(
        run_id="semantic-cid-test",
        case_id="unretained-failure",
        case_manifest_sha256="0" * 64,
        input_data={"text": "A permit holder must file."},
        semantic_protocol_cid=SEMANTIC_PROTOCOL_V2_CID,
    )
    wrapped = _with_semantic_failure_receipt(
        request,
        StageName.SYMAI,
        StageOutput(
            data={
                "raw_output": None,
                "raw_output_cid": candidate_cid,
                "raw_output_bytes": candidate_bytes,
            },
            status=StageStatus.FAILED,
            failure_code=FailureCode.SYMAI_CONTRACT_OR_JSON_FAILURE,
        ),
    )

    assert isinstance(wrapped.data, Mapping)
    expected_bytes = (
        candidate_bytes if expected_cid is not None else None
    )
    assert wrapped.data["raw_output_cid"] == expected_cid
    assert wrapped.data["raw_output_bytes"] == expected_bytes
    receipt = wrapped.data["semantic_failure"]
    assert isinstance(receipt, Mapping)
    evidence = receipt["evidence"]
    assert isinstance(evidence, Mapping)
    assert evidence["raw_output_cid"] == expected_cid
    assert evidence["raw_output_bytes"] == expected_bytes
