"""Property-style adversarial tests for the source-only semantic-v2 boundary.

All examples in this module are constructed in memory.  In particular, these
tests do not load the combined benchmark corpus or any sealed holdout data.
"""

from __future__ import annotations

from dataclasses import replace
from itertools import permutations
import string

import pytest

from benchmarks.logic_pipeline import ablation, adapters, contracts
from benchmarks.logic_pipeline.content_addressing import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)


_FROZEN_V1_PROTOCOL_SHA256 = (
    "a12067c4239b9628fde065db3fe10e623148c95a55891a642306e0c90dee8fa3"
)
_SOURCE = "Every licensed agency shall retain each record."
_MODAL_IR = {
    "formulas": [
        {
            "operator": {"family": "deontic"},
            "predicate": {
                "name": "retain_record",
                "arguments": ["agency:licensed", "record"],
            },
        }
    ]
}
_FROZEN_LOGIC_ALIASES = {
    "first_order": "fol",
    "first_order_logic": "fol",
    "fol": "fol",
    "deontic": "deontic",
    "deontic_logic": "deontic",
    "temporal": "temporal",
    "temporal_logic": "temporal",
}


def _request(
    *,
    input_data: object = None,
    semantic_v2: bool = False,
    proof_context: object = None,
) -> adapters.StageRequest:
    kwargs: dict[str, object] = {
        "run_id": "g200-properties",
        "case_id": "synthetic-case",
        "case_manifest_sha256": "a" * 64,
        "variant_id": "A0",
        "split": contracts.Split.PILOT,
        "cache_mode": contracts.CacheMode.COLD,
        "input_data": (
            {"text": _SOURCE} if input_data is None else input_data
        ),
    }
    if semantic_v2:
        kwargs["semantic_protocol_cid"] = (
            contracts.SEMANTIC_PROTOCOL_V2_CID
        )
    if proof_context is not None:
        kwargs["proof_context"] = proof_context
    return adapters.StageRequest(**kwargs)  # type: ignore[arg-type]


def _projection(
    producer_id: str,
    *,
    source_text: str = _SOURCE,
    evidence_marker: str | None = None,
) -> contracts.SemanticProjection:
    return contracts.SemanticProjection.create(
        producer_id=producer_id,
        source_text=source_text,
        logic_family="deontic",
        target="retain_record",
        semantic_class="proved",
        predicates=("licensed_agency", "retain_record"),
        entities=("agency", "record"),
        evidence_cid=cid_for_dag_json(
            {"producer_evidence": evidence_marker or producer_id}
        ),
    )


def test_frozen_v1_protocol_digest_remains_byte_for_byte_unchanged() -> None:
    assert contracts.DEFAULT_PROTOCOL_SHA256 == _FROZEN_V1_PROTOCOL_SHA256
    assert (
        contracts.SEMANTIC_PROTOCOL_V2.parent_protocol_sha256
        == _FROZEN_V1_PROTOCOL_SHA256
    )


def test_calibration_routes_are_cid_bound_integrated_prefix_measurements() -> None:
    routes = contracts.semantic_calibration_route_manifest_v2()
    metrics = contracts.semantic_calibration_metric_spec_v2()

    assert (
        cid_for_dag_json(routes)
        == contracts.SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID
    )
    assert (
        cid_for_dag_json(metrics)
        == contracts.SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID
    )
    assert routes["measurement_unit"] == "integrated_frontend_stage_prefix"
    assert routes["cost_attribution"] == "complete_selected_stage_prefix"
    assert routes["standalone_producer_claims_permitted"] is False
    assert (
        metrics["selection"][
            "standalone_producer_delegation_claims_permitted"
        ]
        is False
    )
    assert metrics["cases_per_producer"] == 20
    assert metrics["primary_quality"]["minimum_successes"] == 15
    assert (
        metrics["primary_quality"]["minimum_rate_millionths"]
        == 750_000
    )
    assert metrics["uncertainty"] == {
        "method": "wilson_score_interval",
        "confidence_millionths": 950_000,
        "minimum_lower_bound_millionths": 500_000,
    }
    assert (
        contracts.SEMANTIC_PROTOCOL_V2.calibration_route_manifest_cid
        == contracts.SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID
    )
    assert (
        contracts.SEMANTIC_PROTOCOL_V2.calibration_metric_spec_cid
        == contracts.SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID
    )


def test_dag_json_cid_is_deterministic_for_every_top_level_key_order() -> None:
    items = (
        ("unicode", "café"),
        ("nested", {"z": 2, "a": [3, 1]}),
        ("enabled", True),
        ("count", 7),
    )
    expected_bytes = canonical_dag_json_bytes(dict(items))
    expected_cid = cid_for_dag_json(dict(items))

    for ordering in permutations(items):
        candidate = dict(ordering)
        assert canonical_dag_json_bytes(candidate) == expected_bytes
        assert cid_for_dag_json(candidate) == expected_cid


def test_cid_recomputation_detects_content_tamper_and_projection_tamper() -> None:
    original = {"logic": "deontic", "target": "retain_record"}
    tampered = {"logic": "deontic", "target": "destroy_record"}
    assert cid_for_dag_json(original) != cid_for_dag_json(tampered)

    projection = _projection("compiler")
    record = projection.to_dict()
    record["evidence_cid"] = cid_for_dag_json(tampered)
    with pytest.raises(
        contracts.ProtocolContractError,
        match="provenance identity changed",
    ):
        contracts.SemanticProjection.from_dict(record)


def test_codec_substitution_cannot_cross_raw_and_dag_json_boundaries() -> None:
    value = {"logic": "deontic", "target": "retain_record"}
    encoded = canonical_dag_json_bytes(value)
    raw_cid = cid_for_bytes(encoded, codec="raw")
    dag_json_cid = cid_for_dag_json(value)

    assert raw_cid != dag_json_cid
    assert validate_cid(raw_cid, codecs=("raw",)) == raw_cid
    assert validate_cid(dag_json_cid, codecs=("dag-json",)) == dag_json_cid
    with pytest.raises(ValueError, match="codec"):
        validate_cid(raw_cid, codecs=("dag-json",))
    with pytest.raises(ValueError, match="codec"):
        validate_cid(dag_json_cid, codecs=("raw",))

    projection = _projection("compiler")
    substituted = projection.to_dict()
    substituted["source_cid"] = cid_for_dag_json(
        {"text": _SOURCE}
    )
    with pytest.raises(
        contracts.ProtocolContractError,
        match="source_cid is not a canonical CID",
    ):
        contracts.SemanticProjection.from_dict(substituted)


def test_logic_alias_implementation_exactly_matches_frozen_spec() -> None:
    normalization_spec = contracts.semantic_normalization_spec_v2()

    assert normalization_spec["logic_aliases"] == _FROZEN_LOGIC_ALIASES
    assert adapters._SEMANTIC_LOGIC_ALIASES_V2 == _FROZEN_LOGIC_ALIASES
    assert (
        cid_for_dag_json(normalization_spec)
        == contracts.SEMANTIC_NORMALIZATION_V2_CID
    )

    for alias, expected in _FROZEN_LOGIC_ALIASES.items():
        modal_ir = {
            "formulas": [
                {
                    "operator": {"family": alias},
                    "predicate": {
                        "name": "retain_record",
                        "arguments": [],
                    },
                }
            ]
        }
        projection = adapters.build_modal_semantic_projection_v2(
            producer_id="compiler",
            source_text=_SOURCE,
            modal_ir=modal_ir,
        )
        assert projection.logic_family == expected


def test_normalization_cid_binds_every_runtime_projection_rule_family() -> None:
    spec = contracts.semantic_normalization_spec_v2()

    assert adapters._SEMANTIC_NORMALIZATION_SPEC_V2 == spec
    assert cid_for_dag_json(spec) == contracts.SEMANTIC_NORMALIZATION_V2_CID
    assert spec["term_normalization"] == {
        "accepted_input_type": "string",
        "non_string_result": "",
        "unicode": "NFKC",
        "case": "casefold",
        "token_separator": "_",
        "preserved_punctuation": [".", ":", "-"],
        "other_characters": "replace_with_space",
        "whitespace": "split_collapse",
        "maximum_length": 256,
        "alphanumeric_profile": "python_str_isalnum_unicode",
        "persisted_term_schema_pattern": r"^[^\W_][\w.:-]{0,255}$",
        "authoritative_validation": (
            "exact_normalization_fixed_point_and_leading_and_body_"
            "characters_checked_with_unicode_isalnum"
        ),
        "noncanonical_persisted_terms": "reject_projection",
    }
    modal_ir = spec["modal_ir"]
    assert modal_ir["document"]["formulas_field"] == "formulas"
    assert modal_ir["formulas"] == {
        "accepted_container": (
            "sequence_excluding_string_bytes_bytearray"
        ),
        "accepted_item_shape": "mapping",
        "invalid_container_result": "empty",
        "invalid_items": "ignore",
        "collection_order": "input_sequence",
    }
    assert modal_ir["operator"]["accepted_shapes"] == [
        "mapping",
        "string",
    ]
    assert modal_ir["predicate"]["accepted_shapes"] == [
        "mapping",
        "string",
    ]
    assert modal_ir["arguments"]["entity_values"] == [
        "exact_argument",
        "suffix_after_final_:",
    ]
    selection = modal_ir["primary_formula_selection"]
    assert selection["preferred_role"]["normalized_value"] == "clause"
    assert [
        rule["path"] for rule in selection["ordered_tiebreakers"]
    ] == [
        ["provenance", "start_char"],
        ["provenance", "end_char"],
        ["formula_id"],
        ["array_index"],
    ]

    class_rules = spec["class_inference"]
    assert class_rules["proved_signals"] == []
    assert class_rules["default"] == {
        "class": "unsupported",
        "reason": "no_explicit_source_derived_class_evidence",
        "confidence_millionths": 0,
    }
    assert [
        rule["class"] for rule in class_rules["ordered_explicit_signals"]
    ] == ["ambiguous", "disproved"]
    assert spec["validation"]["validation_error_class"] == "unsupported"
    assert (
        spec["validation"]["validation_error_confidence_millionths"]
        == 0
    )
    assert spec["completeness"] == {
        "logic_family": "validation_presence.logic_family",
        "target": "validation_presence.target",
        "class": "assigned_enum_including_unsupported",
        "predicates": "validation_presence.predicates",
        "entities": "observed_collection_empty_is_complete",
    }
    assert spec["scoreability"]["minimum_confidence_millionths"] is None
    assert (
        spec["scoreability"][
            "unsupported_class_is_a_scoreable_observation"
        ]
        is True
    )


@pytest.mark.parametrize(
    ("spelling", "expected"),
    [
        ("First Order", "fol"),
        ("FIRST-ORDER", "first-order"),
        ("First Order Logic", "fol"),
        ("ＤＥＯＮＴＩＣ　ＬＯＧＩＣ", "deontic"),
        ("Temporal Logic", "temporal"),
    ],
)
def test_logic_aliases_follow_nfkc_casefold_and_separator_rules(
    spelling: str,
    expected: str,
) -> None:
    modal_ir = {
        "formulas": [
            {
                "operator": {"family": spelling},
                "predicate": {
                    "name": "retain_record",
                    "arguments": [],
                },
            }
        ]
    }
    projection = adapters.build_modal_semantic_projection_v2(
        producer_id="compiler",
        source_text=_SOURCE,
        modal_ir=modal_ir,
    )

    assert projection.logic_family == expected


def test_primary_clause_beats_a_later_condition_formula() -> None:
    modal_ir = {
        "formulas": [
            {
                "formula_id": "clause-1",
                "operator": {"family": "deontic"},
                "predicate": {
                    "name": "retain_record",
                    "role": "clause",
                    "arguments": ["agency:licensed", "record"],
                },
                "provenance": {"start_char": 0, "end_char": 48},
            },
            {
                "formula_id": "condition-1",
                "operator": {"family": "fol"},
                "predicate": {
                    "name": "license_active",
                    "role": "condition",
                    "arguments": ["agency:licensed"],
                },
                "provenance": {"start_char": 6, "end_char": 21},
            },
        ]
    }

    projection = adapters.build_modal_semantic_projection_v2(
        producer_id="compiler",
        source_text=_SOURCE,
        modal_ir=modal_ir,
    )

    assert projection.logic_family == "deontic"
    assert projection.target == "retain_record"
    assert projection.predicates == ("license_active", "retain_record")


def test_primary_selection_uses_span_then_formula_id_then_array_index() -> None:
    modal_ir = {
        "formulas": [
            {
                "formula_id": "z",
                "operator": {"family": "temporal"},
                "predicate": {"name": "later", "arguments": []},
                "provenance": {"start_char": 8, "end_char": 12},
            },
            {
                "formula_id": "b",
                "operator": {"family": "deontic"},
                "predicate": {"name": "second", "arguments": []},
                "provenance": {"start_char": 1, "end_char": 5},
            },
            {
                "formula_id": "a",
                "operator": {"family": "fol"},
                "predicate": {"name": "first", "arguments": []},
                "provenance": {"start_char": 1, "end_char": 5},
            },
            {
                "formula_id": "a",
                "operator": {"family": "deontic"},
                "predicate": {"name": "same_key_later", "arguments": []},
                "provenance": {"start_char": 1, "end_char": 5},
            },
        ]
    }

    projection = adapters.build_modal_semantic_projection_v2(
        producer_id="compiler",
        source_text="A source contains several formula candidates.",
        modal_ir=modal_ir,
    )

    assert projection.logic_family == "fol"
    assert projection.target == "first"
    assert projection.predicates == (
        "first",
        "later",
        "same_key_later",
        "second",
    )


def test_scalar_modal_ir_shapes_and_invalid_members_follow_frozen_rules() -> None:
    projection = adapters.build_modal_semantic_projection_v2(
        producer_id="compiler",
        source_text="A source-derived target exists.",
        modal_ir={
            "formulas": [
                None,
                "not-a-formula",
                {
                    "operator": "Temporal Logic",
                    "predicate": "Café_Target",
                },
            ]
        },
    )

    assert projection.logic_family == "temporal"
    assert projection.target == "café_target"
    assert projection.predicates == ("café_target",)
    assert projection.entities == ()
    assert projection.semantic_class == "unsupported"
    assert projection.confidence_millionths == 0
    assert projection.validation_errors == ()
    assert projection.scoreable is True


def test_predicate_entities_preserve_unicode_and_expand_final_qualifier() -> None:
    projection = adapters.build_modal_semantic_projection_v2(
        producer_id="compiler",
        source_text="Élodie must file a 東京 notice.",
        modal_ir={
            "formulas": [
                {
                    "operator": {"family": "deontic"},
                    "predicate": {
                        "name": "Déposer_通知",
                        "arguments": [
                            "actor:Élodie",
                            "東京",
                            "scope:a:b",
                            7,
                            None,
                        ],
                    },
                }
            ]
        },
    )

    assert projection.target == "déposer_通知"
    assert projection.predicates == ("déposer_通知",)
    assert set(projection.entities) == {
        "actor:élodie",
        "élodie",
        "東京",
        "scope:a:b",
        "b",
    }
    assert contracts.SemanticProjection.from_dict(
        projection.to_dict()
    ) == projection


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ＣＡＦÉ / 東京", "café_東京"),
        ("ΔΙΚΑΙΩΜΑ", "δικαιωμα"),
        ("Право № ７", "право_no_7"),
        ("  Élodie::通知  ", "élodie::通知"),
    ],
)
def test_term_normalization_uses_frozen_unicode_profile(
    raw: str,
    expected: str,
) -> None:
    assert contracts.normalize_semantic_term(raw) == expected


@pytest.mark.parametrize(
    "noncanonical_target",
    [
        "Retain_Record",
        "cafe\u0301",
        "retain__record",
        "Ｒｅｔａｉｎ",
    ],
)
def test_persisted_terms_must_be_exact_normalization_fixed_points(
    noncanonical_target: str,
) -> None:
    record = _projection("compiler").to_dict()
    record["target"] = noncanonical_target

    with pytest.raises(
        contracts.ProtocolContractError,
        match="target is not normalized",
    ):
        contracts.SemanticProjection.from_dict(record)


def test_semantic_content_cid_is_independent_of_every_producer_identity() -> None:
    projections = [
        _projection(producer_id)
        for producer_id in contracts.SEMANTIC_PRODUCER_IDS_V2
    ]

    assert len(
        {projection.semantic_content_cid for projection in projections}
    ) == 1
    assert len({projection.projection_cid for projection in projections}) == (
        len(contracts.SEMANTIC_PRODUCER_IDS_V2)
    )


@pytest.mark.parametrize(
    "source_text",
    [
        _SOURCE,
        f" {_SOURCE}",
        f"{_SOURCE} ",
        f"{_SOURCE}\n",
        "Every  licensed agency shall retain each record.",
        "Every\tlicensed agency shall retain each record.",
    ],
)
def test_semantic_v2_source_cid_preserves_every_exact_whitespace_byte(
    source_text: str,
) -> None:
    request = _request(
        input_data={"text": source_text},
        semantic_v2=True,
    )
    config = adapters.SymaiAdapterConfig(
        semantic_protocol_cid=contracts.SEMANTIC_PROTOCOL_V2_CID
    )
    projection = _projection("compiler", source_text=source_text)

    assert request.source_cid == cid_for_bytes(source_text.encode("utf-8"))
    assert projection.source_cid == request.source_cid
    assert adapters._symai_request_text(request, config) == source_text


def test_whitespace_variants_never_alias_to_one_source_or_cache_identity() -> None:
    sources = (
        _SOURCE,
        f" {_SOURCE}",
        f"{_SOURCE} ",
        f"{_SOURCE}\n",
        "Every  licensed agency shall retain each record.",
        "Every\tlicensed agency shall retain each record.",
    )
    config = adapters.SymaiAdapterConfig(
        semantic_protocol_cid=contracts.SEMANTIC_PROTOCOL_V2_CID
    )
    requests = tuple(
        _request(input_data={"text": source}, semantic_v2=True)
        for source in sources
    )

    assert len({request.source_cid for request in requests}) == len(sources)
    assert len(
        {
            adapters._symai_cache_key(
                request,
                config,
                adapters._symai_cache_namespace(request),
            )
            for request in requests
        }
    ) == len(sources)


def test_semantic_ablation_plan_keeps_the_exact_source_only_envelope() -> None:
    source_text = f" \t{_SOURCE}\n"
    case = ablation.AblationCase.create(
        "synthetic-whitespace",
        {"text": source_text},
        split=contracts.Split.PILOT,
    )

    plan = ablation.build_semantic_ablation_plan(
        "g200-source-plan",
        (case,),
        case_manifest_sha256="b" * 64,
        split=contracts.Split.PILOT,
        seed=23,
        variant_ids=("A0",),
        cache_modes=(contracts.CacheMode.COLD,),
    )

    assert len(plan.jobs) == 1
    assert plan.jobs[0].case.input_data == {"text": source_text}


def test_semantic_ablation_plan_rejects_a_rich_scheduled_case() -> None:
    case = ablation.AblationCase.create(
        "synthetic-rich",
        {
            "text": _SOURCE,
            "expected_class": "proved",
        },
        split=contracts.Split.PILOT,
    )

    with pytest.raises(
        ablation.AblationValidationError,
        match="canonical",
    ):
        ablation.build_semantic_ablation_plan(
            "g200-rich-plan",
            (case,),
            case_manifest_sha256="b" * 64,
            split=contracts.Split.PILOT,
            seed=23,
            variant_ids=("A0",),
            cache_modes=(contracts.CacheMode.COLD,),
        )


def test_nested_evaluator_field_is_rejected_before_symai_prompt() -> None:
    artifact = adapters.StageArtifact(
        stage=contracts.StageName.SPACY,
        status=contracts.StageStatus.SUCCESS,
        data={
            "schema": adapters.SPACY_EVIDENCE_SCHEMA_V2,
            "document": {
                "source_cid": cid_for_bytes(_SOURCE.encode("utf-8")),
                "normalized_text": _SOURCE,
            },
            "modal_ir": {
                "formulas": [
                    {
                        "operator": {"family": "deontic"},
                        "predicate": {
                            "name": "retain_record",
                            "arguments": ["agency"],
                            "expected_class": "disproved",
                        },
                    }
                ]
            },
        },
        output_sha256=None,
        effective_identity={"graph_invoked": True},
        invocation_index=0,
    )
    request = replace(
        _request(semantic_v2=True),
        upstream_artifacts=(artifact,),
    )

    with pytest.raises(
        contracts.ProtocolContractError,
        match="evaluator or proof field",
    ):
        context = adapters._symai_input_semantic_context(request)
        adapters._symai_prompt(
            _SOURCE,
            adapters._symai_cache_namespace(request),
            context,
            semantic_protocol_cid=contracts.SEMANTIC_PROTOCOL_V2_CID,
        )


@pytest.mark.parametrize(
    "rich_field",
    (
        *contracts.SEMANTIC_FORBIDDEN_PRODUCER_INPUT_FIELDS_V2,
        "document_id",
        "source_text",
    ),
)
def test_semantic_stage_request_rejects_every_rich_input_field(
    rich_field: str,
) -> None:
    rich_input = {"text": _SOURCE, rich_field: "forged-evaluator-value"}

    with pytest.raises(
        contracts.ProtocolContractError,
        match="canonical source-only",
    ):
        _request(input_data=rich_input, semantic_v2=True)


@pytest.mark.parametrize(
    "proof_context",
    [
        {"obligation_id": "synthetic-obligation"},
        {
            "obligation_id": "synthetic-obligation",
            "proof_obligation": None,
        },
        {
            "obligation_id": "synthetic-obligation",
            "proof_obligation": {
                "kind": "theorem",
                "logic": "deontic",
                "target": "retain_record",
            },
            "expected_class": "proved",
        },
        {
            "obligation_id": "synthetic-obligation",
            "proof_obligation": {
                "kind": "theorem",
                "logic": "deontic",
                "target": "retain_record",
                "kernel_outcome": "accepted",
            },
        },
    ],
)
def test_stage_request_rejects_malformed_or_rich_proof_context(
    proof_context: object,
) -> None:
    with pytest.raises(contracts.ProtocolContractError):
        _request(
            semantic_v2=True,
            proof_context=proof_context,
        )


def test_v1_stage_request_cannot_smuggle_separate_proof_context() -> None:
    proof_context = {
        "obligation_id": "synthetic-obligation",
        "proof_obligation": {
            "kind": "theorem",
            "logic": "deontic",
            "target": "retain_record",
        },
    }

    with pytest.raises(
        contracts.ProtocolContractError,
        match="requires semantic protocol v2",
    ):
        _request(proof_context=proof_context)


@pytest.mark.parametrize(
    "stage",
    (
        contracts.StageName.COMPILER,
        contracts.StageName.SPACY,
        contracts.StageName.SYMAI,
    ),
)
def test_source_only_producer_refuses_reviewed_proof_context_before_handler(
    stage: contracts.StageName,
) -> None:
    calls: list[adapters.StageRequest] = []
    proof_context = {
        "obligation_id": "synthetic-obligation",
        "proof_obligation": {
            "kind": "theorem",
            "logic": "deontic",
            "target": "retain_record",
        },
    }
    request = _request(
        semantic_v2=True,
        proof_context=proof_context,
    )
    adapter = adapters.StageAdapter(
        stage,
        handler=lambda value: calls.append(value) or {"unexpected": True},
    )

    invocation = adapter.invoke(request)

    assert calls == []
    assert invocation.output.status is contracts.StageStatus.FAILED
    assert (
        invocation.output.failure_code
        is contracts.FailureCode.SAFETY_CONTROL_FAILURE
    )
    assert invocation.output.data["failure_subcode"] == (
        "semantic_input_leakage"
    )


def test_unavailable_symai_has_complete_typed_semantic_failure() -> None:
    from benchmarks.logic_pipeline.semantic_reassessment import (
        validate_semantic_frontend_stage_v2,
    )

    request = _request(semantic_v2=True)
    adapter = adapters.SymaiAdapter(adapter_version="2")
    invocation = adapter.invoke(request)
    invocation = adapters.StageInvocation(
        replace(
            invocation.output,
            effective_identity={
                **dict(invocation.output.effective_identity),
                "graph_invoked": True,
                "graph_invocation_index": 0,
            },
        ),
        invocation.telemetry,
    )
    record = adapter.record(request, invocation)

    assert record.status is contracts.StageStatus.UNAVAILABLE
    assert record.data["raw_output"] is None
    assert record.data["raw_output_cid"] is None
    assert record.data["raw_output_bytes"] is None
    assert record.data["raw_output_retained_exactly"] is False
    assert validate_semantic_frontend_stage_v2(record, _SOURCE) is None


def test_v1_and_v2_symai_cache_namespaces_and_keys_cannot_collide() -> None:
    v1_request = _request()
    v2_request = _request(semantic_v2=True)
    v1_config = adapters.SymaiAdapterConfig()
    v2_config = replace(
        v1_config,
        semantic_protocol_cid=contracts.SEMANTIC_PROTOCOL_V2_CID,
    )
    v1_namespace = adapters._symai_cache_namespace(v1_request)
    v2_namespace = adapters._symai_cache_namespace(v2_request)
    v1_key = adapters._symai_cache_key(
        v1_request,
        v1_config,
        v1_namespace,
    )
    v2_key = adapters._symai_cache_key(
        v2_request,
        v2_config,
        v2_namespace,
    )

    assert v2_namespace == (
        f"{v1_namespace}/semantic-protocol/"
        f"{contracts.SEMANTIC_PROTOCOL_V2_CID}"
    )
    assert v1_namespace != v2_namespace
    assert v1_key != v2_key

    v1_identity = v1_key.rsplit("/", 1)[-1]
    v2_identity = v2_key.rsplit("/", 1)[-1]
    assert len(v1_identity) == 64
    assert set(v1_identity) <= set(string.hexdigits.lower())
    assert validate_cid(v2_identity, codecs=("dag-json",)) == v2_identity

    # Even a caller-supplied common namespace cannot erase the schema and
    # content-addressing separation inside the key itself.
    assert adapters._symai_cache_key(
        v1_request,
        v1_config,
        v1_namespace,
    ) != adapters._symai_cache_key(
        v2_request,
        v2_config,
        v1_namespace,
    )


@pytest.mark.parametrize(
    "source_text",
    [
        "A licensee may retain the record.",
        "An unlicensed person cannot retain the record.",
        "A licensee shall retain the record unless the agency waives it.",
        "Every licensee except a temporary agent shall retain the record.",
    ],
)
def test_legal_lexical_cues_do_not_invent_ambiguity_or_disproof(
    source_text: str,
) -> None:
    projection = adapters.build_modal_semantic_projection_v2(
        producer_id="compiler",
        source_text=source_text,
        modal_ir=_MODAL_IR,
    )

    assert projection.semantic_class == "unsupported"
    assert projection.ambiguity_flags == ()
    assert projection.validation_errors == ()
    assert projection.confidence_millionths == 0
    assert projection.scoreable is True


def test_explicit_ambiguity_remains_an_allowed_source_derived_signal() -> None:
    projection = adapters.build_modal_semantic_projection_v2(
        producer_id="compiler",
        source_text="The agency states that this clause is ambiguous.",
        modal_ir=_MODAL_IR,
    )

    assert projection.semantic_class == "ambiguous"
    assert projection.ambiguity_flags == ("source_uncertainty",)
    assert projection.confidence_millionths == 1_000_000


def test_explicit_disproof_is_the_only_deterministic_negative_class_signal() -> None:
    projection = adapters.build_modal_semantic_projection_v2(
        producer_id="compiler",
        source_text="The claim that the permit is active is false.",
        modal_ir=_MODAL_IR,
    )

    assert projection.semantic_class == "disproved"
    assert projection.ambiguity_flags == ()
    assert projection.validation_errors == ()
    assert projection.confidence_millionths == 1_000_000


def test_conflicting_explicit_class_signals_fail_closed() -> None:
    projection = adapters.build_modal_semantic_projection_v2(
        producer_id="compiler",
        source_text=(
            "The clause is ambiguous and the asserted claim is false."
        ),
        modal_ir=_MODAL_IR,
    )

    assert projection.semantic_class == "unsupported"
    assert projection.ambiguity_flags == ("source_uncertainty",)
    assert projection.validation_errors == ("class_evidence_conflict",)
    assert projection.confidence_millionths == 0
    assert projection.scoreable is False


def test_missing_modal_fields_bind_validation_completeness_and_confidence() -> None:
    projection = adapters.build_modal_semantic_projection_v2(
        producer_id="compiler",
        source_text="No structured semantic fields were produced.",
        modal_ir={"formulas": [None, "invalid"]},
    )

    assert projection.logic_family == "unknown"
    assert projection.target == "unknown"
    assert projection.predicates == ()
    assert projection.entities == ()
    assert projection.semantic_class == "unsupported"
    assert projection.validation_errors == (
        "logic_family_missing",
        "predicates_missing",
        "target_missing",
    )
    assert dict(projection.completeness) == {
        "logic_family": False,
        "target": False,
        "class": True,
        "predicates": False,
        "entities": True,
    }
    assert projection.confidence_millionths == 0
    assert projection.scoreable is False


def test_negated_ambiguity_phrase_does_not_create_a_positive_signal() -> None:
    projection = adapters.build_modal_semantic_projection_v2(
        producer_id="compiler",
        source_text="The agency states that the clause is not ambiguous.",
        modal_ir=_MODAL_IR,
    )

    assert projection.semantic_class == "unsupported"
    assert projection.ambiguity_flags == ()
