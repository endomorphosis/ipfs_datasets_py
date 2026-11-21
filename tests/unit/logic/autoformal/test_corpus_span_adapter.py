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


def country_record():
    text = "§ Café 😀 e\u0301 — 同意 / 同意"
    return {"jurisdiction": "JP", "language": "ja", "text": text,
            "content_sha256": digest(text.encode()), "source_repo": "fixture:world",
            "source_revision": "dataset-revision-not-legal-edition", "effective_date": None,
            "provenance": {"document_role": "legislation_or_regulation"}}


def country_adapt(value, **kwargs):
    raw = encode(value)
    return a.adapt_country_law_record_bytes(raw, expected_record_sha256=digest(raw), **kwargs)


def country_binding(value):
    text = value["text"]
    raw = ("<p>" + text + "</p>").encode()
    return dict(source_id="fixture:country-source", release_id="fixture:release",
                edition="fixture:declared-edition", provision_id="fixture:article-1",
                raw_bytes=raw, expected_raw_sha256=digest(raw),
                expected_extracted_sha256=digest(text.encode()),
                extraction_profile="fixture:extracted-text/v1", normalization_profile="identity/v1",
                media_type="text/html")


def test_country_pending_preserves_exact_custody_and_unknown_edition():
    value = country_record()
    result = country_adapt(value)
    assert result["input_record"]["row_json"].encode() == encode(value)
    assert result["source_version"] is None
    assert result["source_occurrences"] == []
    assert result["admitted"] is result["formalized"] is result["source_semantics_verified"] is False
    binding = country_binding(value)
    binding["edition"] = None
    pending = country_adapt(value, source_binding=binding)
    assert pending["source_version"] is None
    assert {i.get("field") for i in pending["issues"]} >= {"edition"}
    assert value["effective_date"] is None


def test_country_multilingual_geometry_distinguishes_repeated_occurrences():
    value = country_record()
    text = value["text"]
    starts = [text.index("同意"), text.rindex("同意")]
    selectors = [{"start_char": start, "end_char": start + 2} for start in starts]
    result = country_adapt(value, source_binding=country_binding(value), occurrence_selectors=selectors)
    one, two = result["source_occurrences"]
    assert one["span_text"] == two["span_text"] == "同意"
    assert one["record_cid"] != two["record_cid"]
    assert one["start_utf8"] == len(text[:starts[0]].encode()) != starts[0]
    assert result["context_declarations"] == [None, None]
    assert "jurisdiction" not in result["source_version"]
    assert result["source_authenticity_verified"] is False


def test_country_duplicate_selectors_remain_explicit_in_order():
    value = country_record()
    selector = {"start_char": 0, "end_char": 1}
    result = country_adapt(value, source_binding=country_binding(value),
                           occurrence_selectors=[selector, selector])
    assert len(result["source_occurrences"]) == 2
    assert result["source_occurrences"][0] == result["source_occurrences"][1]
    assert result["occurrence_selectors"] == [selector, selector]


@pytest.mark.parametrize("change", ["content", "expected_view", "raw", "whitespace"])
def test_country_binding_hash_mismatch_refuses(change):
    value = country_record()
    binding = country_binding(value)
    if change == "content":
        value["content_sha256"] = "0" * 64
    elif change == "expected_view":
        binding["expected_extracted_sha256"] = "0" * 64
    elif change == "raw":
        binding["raw_bytes"] += b"!"
    else:
        value["text"] = " " + value["text"]
        value["content_sha256"] = digest(value["text"].encode())
    with pytest.raises(c.CorpusContractError):
        country_adapt(value, source_binding=binding)


@pytest.mark.parametrize("selector", [
    {"start_char": True, "end_char": 1}, {"start_char": 1, "end_char": 1},
    {"start_char": 2, "end_char": 1}, {"start_char": 0, "end_char": 999},
])
def test_country_invalid_geometry_refuses(selector):
    value = country_record()
    with pytest.raises(c.CorpusContractError):
        country_adapt(value, source_binding=country_binding(value), occurrence_selectors=[selector])


def test_country_missing_text_never_uses_html_or_guesses_edition():
    value = country_record()
    value.update(text=None, content_sha256=None)
    result = country_adapt(value)
    assert result["source_version"] is None
    assert "complete_projected_text" in {i.get("field") for i in result["issues"]}
    value["html"] = "<p>not used as source text</p>"
    pending = country_adapt(value)
    assert pending["source_version"] is None
    assert json.loads(pending["input_record"]["row_json"])["html"] == value["html"]


def test_country_context_requires_exact_parent_and_selector_population():
    value = country_record()
    selector = {"start_char": 0, "end_char": 1}
    kwargs = dict(source_binding=country_binding(value), occurrence_selectors=[selector])
    bound = country_adapt(value, **kwargs)
    occurrence = bound["source_occurrences"][0]
    context = build_context_declaration(occurrence, expected_occurrence_cid=occurrence["record_cid"],
        availability="required_unavailable", reason="fixture definition missing",
        missing_requirements=["governing definition"])
    result = country_adapt(value, context_declarations=[context], **kwargs)
    assert result["context_declarations"] == [context]
    assert {i["kind"] for i in result["issues"]} >= {"context_required_unavailable"}
    with pytest.raises(c.CorpusContractError):
        country_adapt(value, context_declarations=[context, context], **kwargs)
    with pytest.raises(c.CorpusContractError):
        country_adapt(value, context_declarations=[context])
    other = dict(kwargs, occurrence_selectors=[{"start_char": 1, "end_char": 2}])
    with pytest.raises(c.CorpusContractError):
        country_adapt(value, context_declarations=[context], **other)


def test_country_independent_input_commitment_and_strict_json_refuse():
    raw = encode(country_record())
    with pytest.raises(c.CorpusContractError):
        a.adapt_country_law_record_bytes(raw, expected_record_sha256="0" * 64)
    for raw in (b'{"text":1,"text":2}', b'{"text":NaN}', b'[]'):
        with pytest.raises(c.CorpusContractError):
            a.adapt_country_law_record_bytes(raw, expected_record_sha256=digest(raw))



def test_country_partial_binding_keys_refuse_but_explicit_unknowns_preserve_pending():
    value = country_record()
    value.update(jurisdiction=None, language=None)
    binding = country_binding(value)
    binding["edition"] = None
    selectors = [{"start_char": 0, "end_char": 1},
                 {"start_char": 2, "end_char": 6}]
    pending = country_adapt(value, source_binding=binding, occurrence_selectors=selectors)
    retained = json.loads(pending["input_record"]["row_json"])
    assert retained["jurisdiction"] is retained["language"] is None
    assert pending["occurrence_selectors"] == selectors
    assert pending["source_version"] is None
    assert pending["source_occurrences"] == []
    assert {i.get("field") for i in pending["issues"]} >= {"edition"}
    assert "edition" not in retained  # no invented legal-record field or edition
    assert pending["admitted"] is pending["formalized"] is False
    missing = dict(binding)
    del missing["edition"]
    with pytest.raises(c.CorpusContractError, match="closed country source binding"):
        country_adapt(value, source_binding=missing, occurrence_selectors=selectors)
    extra = dict(binding, guessed_edition="2026")
    with pytest.raises(c.CorpusContractError, match="closed country source binding"):
        country_adapt(value, source_binding=extra, occurrence_selectors=selectors)



def test_country_declared_view_preserves_unknown_metadata_without_schema_claim():
    value = country_record()
    value.update(future_field={"nested": [None, "保留", 7]}, language={"unreviewed": "as supplied"})
    value["provenance"]["future_provenance"] = {"declaration": False}
    result = country_adapt(value)
    assert result["input_record"]["input_label"] == "declared_world_law_source_view"
    assert "record_schema" not in result["input_record"]
    assert result["input_record"]["row_json"].encode() == encode(value)
    assert json.loads(result["input_record"]["row_json"]) == value
    assert result["source_version"] is None
    assert result["admitted"] is result["source_semantics_verified"] is False


@pytest.mark.parametrize("field", ["text", "content_sha256", "provenance"])
def test_country_declared_view_requires_only_its_consumed_fields(field):
    value = country_record()
    del value[field]
    with pytest.raises(c.CorpusContractError, match="fields required"):
        country_adapt(value)
    minimal = {"text": None, "content_sha256": None, "provenance": {}}
    assert country_adapt(minimal)["source_version"] is None


def test_country_declared_view_consumed_provenance_type_refuses():
    value = country_record()
    value["provenance"] = []
    with pytest.raises(c.CorpusContractError, match="provenance object"):
        country_adapt(value)
