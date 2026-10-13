"""Paired-cache custody and physical joins without semantic promotion."""
import copy
import hashlib
import json

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as c
from ipfs_datasets_py.logic.autoformal import corpus_span_adapter as a
from ipfs_datasets_py.logic.autoformal.corpus_source import (
    build_context_declaration,
    build_source_occurrence,
    build_source_version,
)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def formal(payload=None, **overrides):
    if payload is None:
        payload = {"modality": "Obligation", "actor": "agency", "action": "retain",
                   "object": "record", "temporal": {"kind": "minimum_duration", "quantity": 20, "unit": "days"}}
    raw = json.dumps(payload, indent=2, ensure_ascii=False).encode()
    return {"family": "typed_deontic", "format": "typed-deontic-rule/v1", "payload_json": raw.decode(),
            "sha256": digest(raw), "origin": "deterministic_compiler", "independent": True,
            "target_conditioned": False, "syntax_status": "compiler_accepted", **overrides}


def row(**overrides):
    text = "The agency shall retain the record for at least 20 days."
    output = formal()
    return {"schema_version": "uscode-paired-span-census/v1", "repository_id": "fixture",
            "source": {"span_id": "historical-span", "text": text, "text_sha256": digest(text.encode()),
                       "legal_id": "usc:5:1", "revision": "historical-release-alias", "constitution": False},
            "autoencoder": {"formal_outputs": [], "raw_vector": [0.1, 0.2], "status": "unsupported_symbolic_decoder"},
            "compiler": {"formal_outputs": [output], "canonical_formal_outputs": [copy.deepcopy(output)]},
            "comparison": {"status": "autoencoder_unavailable"}, "observation_id": "historical-id-preserved",
            "admitted": True, "formalized": True, "unknown_future_metadata": {"retained": "§ café"}, **overrides}


def encode(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode()


def adapt(value, **kwargs):
    raw = encode(value)
    return a.adapt_paired_span_bytes(raw, expected_row_sha256=digest(raw), **kwargs)


def source_binding(value, *, duplicate=False, second=False, availability="none_required"):
    span = value["source"]["text"]
    text = "§ Café. " + span + (" " + span if duplicate else "")
    raw = ("<p>" + text + "</p>").encode()
    args = {"expected_raw_sha256": digest(raw), "extracted_text": text,
            "expected_extracted_sha256": digest(text.encode())}
    version = build_source_version(source_id="usc-source", release_id="2024-01-01", edition="2024",
        provision_id="5 USC 1", raw_bytes=raw, extraction_profile="fixture/v1",
        normalization_profile="identity/v1", media_type="text/html", **args)
    start = text.rindex(span) if second else text.index(span)
    end = start + len(span)
    occurrence = build_source_occurrence(version, start_char=start, end_char=end,
        start_utf8=len(text[:start].encode()), end_utf8=len(text[:end].encode()), **args)
    context = build_context_declaration(occurrence, expected_occurrence_cid=occurrence["record_cid"],
        availability=availability, reason="fixture declaration",
        missing_requirements=["section definition"] if availability == "required_unavailable" else [])
    return {"source_version": version, "source_occurrence": occurrence, "context_declaration": context, **args}


def reseal(value):
    return c.seal_record({k: v for k, v in value.items() if k not in {"record_cid", "cid_scope"}})


def test_unresolved_rows_preserve_exact_bytes_opaque_payloads_and_legacy_flags():
    value = row()
    candidate = adapt(value)
    assert candidate["input_record"]["row_json"].encode() == encode(value)
    assert candidate["input_record"]["row_sha256"] == digest(encode(value))
    assert json.loads(candidate["input_record"]["row_json"])["admitted"] is True
    assert candidate["admitted"] is candidate["formalized"] is candidate["source_semantics_verified"] is False
    assert candidate["source_binding"] is None
    assert {issue["kind"] for issue in candidate["issues"]} >= {"source_occurrence_unresolved", "formal_outputs_unavailable"}
    assert {node["node_type"] for node in candidate["graph"]["nodes"]} == {"interpretation", "issue"}
    assert len(candidate["interpretations"]) == 2  # canonical and direct routes stay distinct
    assert candidate["interpretations"][0]["formal_output"] == value["compiler"]["formal_outputs"][0]
    assert all(item["projection_status"] == "opaque_preserved" for item in candidate["interpretations"])
    assert a.validate_span_candidate(candidate, expected_row_sha256=digest(encode(value))) == candidate


def test_explicit_unicode_geometry_join_builds_closed_source_links():
    value = row(schema_version="uscode-paired-span-census/v2")
    binding = source_binding(value)
    candidate = adapt(value, source_binding=binding)
    assert candidate["source_binding"]["source_integrity"] == "expected_hashes_and_extracted_geometry_checked"
    assert candidate["source_binding"]["source_authenticity_verified"] is False
    assert "extracted_text" not in candidate["source_binding"]
    assert {node["node_type"] for node in candidate["graph"]["nodes"]} >= {"source_version", "occurrence"}
    assert all(item["source_occurrence_cid"] == binding["source_occurrence"]["record_cid"]
               for item in candidate["interpretations"])
    assert a.validate_span_candidate(candidate, expected_row_sha256=digest(encode(value)), source_binding=binding) == candidate
    # Source geometry must be supplied again for validation of a bound record.
    with pytest.raises(c.CorpusContractError, match="recomputed"):
        a.validate_span_candidate(candidate, expected_row_sha256=digest(encode(value)))


def test_repeated_text_never_creates_an_implicit_physical_join():
    value = row()
    one = source_binding(value, duplicate=True)
    two = source_binding(value, duplicate=True, second=True)
    first, second = adapt(value, source_binding=one), adapt(value, source_binding=two)
    assert one["source_version"] == two["source_version"]
    assert one["source_occurrence"]["span_cid"] == two["source_occurrence"]["span_cid"]
    assert first["interpretations"][0]["record_cid"] != second["interpretations"][0]["record_cid"]
    assert first["graph"]["record_cid"] != second["graph"]["record_cid"]


def test_unavailable_context_is_retained_with_source_binding():
    value = row()
    candidate = adapt(value, source_binding=source_binding(value, availability="required_unavailable"))
    assert "context_required_unavailable" in {issue["kind"] for issue in candidate["issues"]}
    assert candidate["source_binding"]["context_declaration"]["missing_requirements"] == ["section definition"]


def test_every_route_order_duplicate_and_guided_provenance_survives():
    value = row()
    guided = formal(["opaque", "AST"], origin="autoencoder_guided_compiler", independent=False,
                    target_conditioned=True, syntax_status="not_checked", future_field="retained")
    value["autoencoder"]["formal_outputs"] = [guided, copy.deepcopy(guided)]
    value["compiler"]["formal_outputs"] = [formal("O(retain(record))", family="modal", format="opaque-modal/v3")]
    candidate = adapt(value)
    items = candidate["interpretations"]
    assert [(i["route"], i["ordinal"]) for i in items] == [
        ("autoencoder.formal_outputs", 0), ("autoencoder.formal_outputs", 1),
        ("compiler.formal_outputs", 0), ("compiler.canonical_formal_outputs", 0)]
    assert items[0]["formal_output"] == items[1]["formal_output"] == guided
    assert items[0]["record_cid"] != items[1]["record_cid"]
    assert all(n["node_type"] not in {"norm_assertion", "entity", "definition_assertion"}
               for n in candidate["graph"]["nodes"])


def test_missing_collection_and_abstention_are_explicit_not_dropped():
    value = row()
    del value["compiler"]["canonical_formal_outputs"]
    value["compiler"]["formal_outputs"] = []
    candidate = adapt(value)
    assert candidate["interpretations"] == []
    assert len(candidate["issues"]) == 4
    assert "formal_output_collection_missing" in {issue["kind"] for issue in candidate["issues"]}


@pytest.mark.parametrize("mutate", [
    lambda value: value.update(schema_version="future/v3"),
    lambda value: value.update(schema_version=[]),
    lambda value: value["source"].update(text_sha256="0" * 64),
    lambda value: value["compiler"]["formal_outputs"][0].update(sha256="0" * 64),
    lambda value: value["compiler"]["formal_outputs"][0].update(independent=1),
    lambda value: value["compiler"].update(formal_outputs="not-list"),
])
def test_malformed_schema_source_and_formal_evidence_refuse(mutate):
    value = row()
    mutate(value)
    with pytest.raises(c.CorpusContractError):
        adapt(value)


@pytest.mark.parametrize("payload", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', 'null', '42', '[]', '""'])
def test_invalid_or_empty_formal_json_refuses(payload):
    value = row()
    value["compiler"]["formal_outputs"][0].update(payload_json=payload, sha256=digest(payload.encode()))
    with pytest.raises(c.CorpusContractError):
        adapt(value)


@pytest.mark.parametrize("payload", [{"": 1}, {"opaque": "\x00"}, {"integer": 2**63}])
def test_common_json_subset_boundaries_fail_explicitly_without_partial_candidate(payload):
    value = row()
    value["compiler"]["formal_outputs"] = [formal(payload)]
    with pytest.raises(c.CorpusContractError):
        adapt(value)


def test_independent_commitment_and_source_view_mismatch_refuse():
    value = row()
    with pytest.raises(c.CorpusContractError, match="SHA256"):
        a.adapt_paired_span_bytes(encode(value), expected_row_sha256="0" * 64)
    binding = source_binding(value)
    binding["extracted_text"] += "changed"
    with pytest.raises(c.CorpusContractError):
        adapt(value, source_binding=binding)
    other = row()
    other["source"]["text"] = "Different span."
    other["source"]["text_sha256"] = digest(other["source"]["text"].encode())
    with pytest.raises(c.CorpusContractError, match="explicitly selected"):
        adapt(other, source_binding=source_binding(value))


@pytest.mark.parametrize("change", ["graph", "qualification", "interpretation"])
def test_resealing_cannot_forge_graph_provenance_or_qualification(change):
    value = row()
    candidate = adapt(value)
    if change == "graph":
        candidate["graph"]["edges"] = []
        candidate["graph"]["nodes"] = candidate["graph"]["nodes"][:1]
        candidate["graph"] = reseal(candidate["graph"])
    elif change == "qualification":
        candidate["admitted"] = True
    else:
        candidate["interpretations"][0]["formal_output"]["independent"] = False
        candidate["interpretations"][0] = reseal(candidate["interpretations"][0])
    with pytest.raises(c.CorpusContractError, match="recomputed"):
        a.validate_span_candidate(reseal(candidate), expected_row_sha256=digest(encode(value)))


def test_output_and_aggregate_bounds_fail_without_truncation(monkeypatch):
    value = row()
    monkeypatch.setattr(a, "MAX_OUTPUTS_PER_ROUTE", 1)
    value["compiler"]["formal_outputs"] *= 2
    with pytest.raises(c.CorpusContractError, match="bounded list"):
        adapt(value)
    value = row()
    monkeypatch.setattr(c, "MAX_RECORD_BYTES", len(encode(value)) + 200)
    with pytest.raises(c.CorpusContractError, match="byte bound"):
        adapt(value)


def test_input_is_not_mutated_or_shared():
    value = row()
    original = copy.deepcopy(value)
    candidate = adapt(value)
    candidate["interpretations"][0]["formal_output"]["origin"] = "changed"
    assert value == original


@pytest.mark.parametrize("has_rule", [False, True])
def test_real_paired_census_producer_rows_are_supported_without_semantic_projection(has_rule):
    from ipfs_datasets_py.logic.autoformal.paired_span_census import build_paired_census

    value = row()
    payload = json.loads(value["compiler"]["formal_outputs"][0]["payload_json"])
    bundle = build_paired_census([{
        "source_span_id": "actual-producer-span", "text": value["source"]["text"],
        "compiler_result": {"rules": [payload] if has_rule else [], "compilation_complete": True},
    }], repository_id="fixture", agent_id="fixture", code_identity="fixture-code", model_identity="fixture-model")
    produced = bundle["paired_spans"][0]
    candidate = adapt(produced)
    assert produced["schema_version"] == "uscode-paired-span-census/v2"
    assert candidate["input_record"]["row_json"].encode() == encode(produced)
    assert len(candidate["interpretations"]) == (2 if has_rule else 0)
    assert candidate["admitted"] is False
