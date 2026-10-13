"""Candidate-only physical joins use independently pinned fictional inputs."""

import copy
import hashlib
import json

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_legacy_source_join as joins
from ipfs_datasets_py.logic.autoformal.corpus_contracts import CorpusContractError, seal_record
from ipfs_datasets_py.logic.autoformal.corpus_span_adapter import adapt_paired_span_bytes
from ipfs_datasets_py.utils.cid_utils import cid_for_bytes


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def fixture(text="§ Café Clerk; Clerk.", span="Clerk"):
    provenance = {
        "repository_id": "justicedao/ipfs_uscode",
        "revision": "a" * 40,
        "path_in_repo": "uscode_parquet/laws.parquet",
        "artifact_sha256": "b" * 64,
        "artifact_bytes": 1000,
        "release_id": "historical-release",
        "parquet_row_index": 17,
        "entry_cid": cid_for_bytes(b"declared row"),
        "legal_id": "usc:us:5:1",
        "text_sha256": sha(text.encode()),
    }
    producer = {
        "source_span_id": "historical-span",
        "source_sha256": sha(span.encode()),
        "text": span,
        "legal_id": provenance["legal_id"],
        "entry_cid": provenance["entry_cid"],
        "source_section_offset": provenance["parquet_row_index"],
        "historical_span_ordinal": 999,
        "historical_document_batch_index": 3,
        "historical_document_batch_size": 64,
        "source_parent": {
            "repository_id": provenance["repository_id"],
            "revision": provenance["revision"],
            "path_in_repo": provenance["path_in_repo"],
            "sha256": provenance["artifact_sha256"],
            "bytes": provenance["artifact_bytes"],
            "release_id": provenance["release_id"],
            "path": "/historical/producer/machine/laws.parquet",
        },
        "logic_target_observation": {},
        "admitted": True,
        "formalized": True,
    }
    receipt = wire({"schema_version": "fictional-producer/v1", "rows": [producer]})
    row = {
        "schema_version": "uscode-paired-span-census/v1",
        "observation_id": "historical-observation",
        "source": {
            "span_id": producer["source_span_id"],
            "revision": provenance["release_id"],
            "legal_id": provenance["legal_id"],
            "text": span,
            "text_sha256": sha(span.encode()),
        },
        "source_target_artifact_sha256": sha(receipt),
        "source_target_artifact_pointer": "/rows/0/logic_target_observation",
        "autoencoder": {"formal_outputs": []},
        "compiler": {"formal_outputs": [], "canonical_formal_outputs": []},
        "admitted": True,
        "formalized": True,
    }
    raw = wire(row)
    inputs = {
        "expected_population": [
            {
                "row_sha256": sha(raw),
                "source_span_id": producer["source_span_id"],
                "text_sha256": sha(span.encode()),
                "source_revision": provenance["release_id"],
            }
        ],
        "producer_receipt_bytes": receipt,
        "expected_producer_receipt_sha256": sha(receipt),
        "source_sections": [{**provenance, "text": text}],
        "expected_source_sections": [provenance],
    }
    return [raw], inputs


def result(text="§ Café Clerk; Clerk.", span="Clerk"):
    raw, inputs = fixture(text, span)
    return joins.build_legacy_source_join(raw, **inputs), raw, inputs


def reseal(value):
    return seal_record(
        {
            key: copy.deepcopy(item)
            for key, item in value.items()
            if key not in {"record_cid", "cid_scope"}
        }
    )


def replace_receipt(raw, inputs, mutate):
    receipt = json.loads(inputs["producer_receipt_bytes"])
    mutate(receipt)
    encoded = wire(receipt)
    inputs["producer_receipt_bytes"] = encoded
    inputs["expected_producer_receipt_sha256"] = sha(encoded)
    row = json.loads(raw[0])
    row["source_target_artifact_sha256"] = sha(encoded)
    raw[0] = wire(row)
    inputs["expected_population"][0]["row_sha256"] = sha(raw[0])


def test_all_unicode_matches_preserved_without_selecting_or_attesting():
    ledger, raw, inputs = result()
    assert joins.validate_legacy_source_join(ledger, raw, **inputs) == ledger
    row = ledger["rows"][0]
    assert row["disposition"] == "ambiguous_exact_candidates"
    assert row["occurrence_count"] == 2
    occurrences = [item["source_occurrence"] for item in row["candidates"]]
    assert [item["start_char"] for item in occurrences] == [7, 14]
    assert [item["start_utf8"] for item in occurrences] == [9, 16]
    assert occurrences[0]["record_cid"] != occurrences[1]["record_cid"]
    assert all(item["historical_aliases"][0]["status"] == "unresolved" for item in occurrences)
    assert row["selected_occurrence"] is None
    assert (
        row["producer_link"]["producer_record"]["historical_metadata"]["historical_span_ordinal"]
        == 999
    )
    assert row["producer_link"]["producer_record"]["source_section_offset"] == 17
    assert not row["original_producer_occurrence_attested"]
    assert not any(
        ledger[key]
        for key in (
            "admitted",
            "formalized",
            "proof_authority",
            "source_authenticity_verified",
            "source_semantics_verified",
            "official_html_view_mapping_verified",
            "context_closure_verified",
        )
    )
    version = ledger["source_sections"][0]["source_version"]
    assert version["edition"] == joins.UNDECLARED_EDITION
    assert version["raw_artifact"]["media_type"] == "text/plain"
    assert version["raw_artifact"]["sha256"] == inputs["expected_source_sections"][0]["text_sha256"]
    assert ledger["expected_source_sections"][0]["artifact_sha256"] == "b" * 64


def test_unique_candidate_remains_unselected_with_all_governing_context_open():
    ledger, _, _ = result("§ Clerk shall file.", "Clerk shall file.")
    row = ledger["rows"][0]
    assert row["disposition"] == "unique_exact_candidate" and row["selected_occurrence"] is None
    context = row["candidates"][0]["context_declaration"]
    assert context["availability"] == "required_unavailable"
    assert context["missing_requirements"] == list(joins.DEPENDENCY_KINDS)
    assert context["dependency_verification"] == "declaration_only"


def test_candidate_binding_integrates_existing_paired_adapter_without_geometry_conversion():
    ledger, raw, inputs = result("§ Clerk shall file.", "Clerk shall file.")
    section = ledger["source_sections"][0]
    candidate = ledger["rows"][0]["candidates"][0]
    adapted = adapt_paired_span_bytes(
        raw[0],
        expected_row_sha256=sha(raw[0]),
        source_binding={
            "source_version": section["source_version"],
            "source_occurrence": candidate["source_occurrence"],
            "context_declaration": candidate["context_declaration"],
            "expected_raw_sha256": section["provenance"]["text_sha256"],
            "extracted_text": section["extracted_text"],
            "expected_extracted_sha256": section["provenance"]["text_sha256"],
        },
    )
    assert adapted["source_binding"]["source_occurrence"] == candidate["source_occurrence"]
    assert adapted["source_binding"]["source_authenticity_verified"] is False
    assert adapted["admitted"] is adapted["formalized"] is False
    assert inputs["source_sections"][0]["text"] == "§ Clerk shall file."


def test_overlapping_matches_and_zero_matches_are_distinct():
    ledger, _, _ = result("aaaa", "aa")
    assert [c["source_occurrence"]["start_char"] for c in ledger["rows"][0]["candidates"]] == [
        0,
        1,
        2,
    ]
    ledger, _, _ = result("Clerk  shall", "Clerk shall")
    assert ledger["rows"][0]["disposition"] == "no_exact_occurrence"
    assert ledger["counts"]["candidate_occurrences"] == 0


def test_unavailable_source_and_producer_preserve_denominator():
    raw, inputs = fixture()
    inputs.update(source_sections=[], expected_source_sections=[])
    ledger = joins.build_legacy_source_join(raw, **inputs)
    assert ledger["rows"][0]["disposition"] == "source_section_unavailable"
    inputs.update(producer_receipt_bytes=None, expected_producer_receipt_sha256=None)
    ledger = joins.build_legacy_source_join(raw, **inputs)
    assert ledger["rows"][0]["disposition"] == "producer_source_unavailable"
    assert ledger["counts"]["paired_rows"] == 1 and ledger["population_complete"] is True


def test_legal_alias_does_not_join_another_physical_row():
    raw, inputs = fixture()
    for key in ("source_sections", "expected_source_sections"):
        inputs[key][0]["parquet_row_index"] = 18
    ledger = joins.build_legacy_source_join(raw, **inputs)
    assert ledger["rows"][0]["disposition"] == "source_section_unavailable"
    assert not ledger["rows"][0]["candidates"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("entry_cid", cid_for_bytes(b"wrong entry")),
        ("legal_id", "usc:us:5:2"),
        ("artifact_bytes", 1001),
        ("release_id", "another-release"),
    ],
)
def test_same_physical_row_with_conflicting_provenance_is_not_joined(field, value):
    raw, inputs = fixture()
    for key in ("source_sections", "expected_source_sections"):
        inputs[key][0][field] = value
    ledger = joins.build_legacy_source_join(raw, **inputs)
    assert ledger["rows"][0]["disposition"] == "producer_parent_mismatch"
    assert ledger["rows"][0]["occurrence_count"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("parquet_row_index", True),
        ("artifact_bytes", True),
        ("revision", "main"),
        ("path_in_repo", "../laws.parquet"),
        ("entry_cid", "arbitrary-label"),
    ],
)
def test_malformed_trusted_source_descriptors_refused(field, value):
    raw, inputs = fixture()
    for key in ("source_sections", "expected_source_sections"):
        inputs[key][0][field] = value
    with pytest.raises(CorpusContractError):
        joins.build_legacy_source_join(raw, **inputs)


@pytest.mark.parametrize(
    "damage",
    [
        "paired_hash",
        "source_hash",
        "receipt_hash",
        "source_omission",
        "paired_omission",
        "source_order",
        "duplicate_physical",
        "duplicate_paired",
    ],
)
def test_external_hashes_and_ordered_populations_are_required(damage):
    raw, inputs = fixture()
    if damage == "paired_hash":
        raw[0] += b" "
    elif damage == "source_hash":
        inputs["source_sections"][0]["text"] += " extra"
    elif damage == "receipt_hash":
        inputs["producer_receipt_bytes"] += b" "
    elif damage == "source_omission":
        inputs["source_sections"] = []
    elif damage == "paired_omission":
        raw = []
    elif damage == "source_order":
        inputs["expected_source_sections"][0]["parquet_row_index"] = 18
    elif damage == "duplicate_physical":
        inputs["source_sections"] *= 2
        inputs["expected_source_sections"] *= 2
    else:
        raw *= 2
        inputs["expected_population"] *= 2
    with pytest.raises(CorpusContractError):
        joins.build_legacy_source_join(raw, **inputs)


@pytest.mark.parametrize(
    "pointer",
    [
        "/rows/1/logic_target_observation",
        "/rows/00/logic_target_observation",
        "/rows/-1/logic_target_observation",
        "/rows/0/text",
        None,
    ],
)
def test_only_exact_bound_producer_pointer_can_constrain_physical_row(pointer):
    raw, inputs = fixture()
    row = json.loads(raw[0])
    row["source_target_artifact_pointer"] = pointer
    raw[0] = wire(row)
    inputs["expected_population"][0]["row_sha256"] = sha(raw[0])
    with pytest.raises(CorpusContractError):
        joins.build_legacy_source_join(raw, **inputs)


@pytest.mark.parametrize(
    "field,value",
    [
        ("text", "different"),
        ("source_sha256", "0" * 64),
        ("source_span_id", "other"),
        ("legal_id", "usc:us:5:2"),
    ],
)
def test_hash_bound_but_contradictory_producer_row_refused(field, value):
    raw, inputs = fixture()
    replace_receipt(raw, inputs, lambda r: r["rows"][0].update({field: value}))
    with pytest.raises(CorpusContractError, match="producer row differs"):
        joins.build_legacy_source_join(raw, **inputs)


def test_large_receipt_has_its_own_bound_without_changing_common_record_bound():
    raw, inputs = fixture()
    replace_receipt(raw, inputs, lambda r: r.update(diagnostic_padding="x" * (1024 * 1024)))
    ledger = joins.build_legacy_source_join(raw, **inputs)
    assert ledger["producer_receipt"]["bytes"] > 1024 * 1024
    assert len(wire(ledger)) < 32 * 1024
    assert "diagnostic_padding" not in wire(ledger).decode()


@pytest.mark.parametrize(
    "bad", [b'{"rows":[],"rows":[]}', b'{"rows":[],"x":NaN}', b'{"rows":[],"x":1e999}', b"{"]
)
def test_strict_receipt_json_refuses_duplicate_nonfinite_or_invalid_inputs(bad):
    raw, inputs = fixture()
    inputs.update(producer_receipt_bytes=bad, expected_producer_receipt_sha256=sha(bad))
    with pytest.raises(CorpusContractError):
        joins.build_legacy_source_join(raw, **inputs)


def test_occurrence_overflow_refuses_whole_inventory(monkeypatch):
    raw, inputs = fixture("aaaa", "aa")
    monkeypatch.setattr(joins, "MAX_OCCURRENCES_PER_ROW", 2)
    with pytest.raises(CorpusContractError, match="inventory incomplete"):
        joins.build_legacy_source_join(raw, **inputs)


def test_receipt_and_source_resource_bounds_refuse_without_truncation(monkeypatch):
    raw, inputs = fixture()
    monkeypatch.setattr(joins, "MAX_RECEIPT_BYTES", 10)
    with pytest.raises(CorpusContractError, match="bounded immutable"):
        joins.build_legacy_source_join(raw, **inputs)
    monkeypatch.setattr(joins, "MAX_RECEIPT_BYTES", 32 * 1024 * 1024)
    monkeypatch.setattr(joins, "MAX_SECTION_BYTES", 5)
    with pytest.raises(CorpusContractError, match="byte bound"):
        joins.build_legacy_source_join(raw, **inputs)


@pytest.mark.parametrize(
    "damage", ["seal", "resealed_authority", "resealed_drop", "resealed_select", "resealed_offset"]
)
def test_ledger_replay_rejects_tampering_even_if_resealed(damage):
    ledger, raw, inputs = result()
    changed = copy.deepcopy(ledger)
    if damage in {"seal", "resealed_authority"}:
        changed["admitted"] = True
    elif damage == "resealed_drop":
        changed["rows"][0]["candidates"].pop()
    elif damage == "resealed_select":
        changed["selected_occurrence"] = changed["rows"][0]["candidates"][0]["source_occurrence"][
            "record_cid"
        ]
    else:
        changed["rows"][0]["candidates"][0]["source_occurrence"]["start_char"] += 1
    if damage != "seal":
        changed = reseal(changed)
    with pytest.raises(CorpusContractError):
        joins.validate_legacy_source_join(changed, raw, **inputs)


def test_inputs_and_returned_records_are_detached():
    raw, inputs = fixture()
    before = copy.deepcopy(inputs)
    ledger = joins.build_legacy_source_join(raw, **inputs)
    assert inputs == before
    ledger["source_sections"][0]["provenance"]["legal_id"] = "changed"
    assert inputs == before


@pytest.mark.parametrize("schema", [[], {}, None, True, "unknown/v1"])
def test_malformed_or_unknown_paired_schema_refused_as_contract_error(schema):
    raw, inputs = fixture()
    row = json.loads(raw[0])
    row["schema_version"] = schema
    raw[0] = wire(row)
    inputs["expected_population"][0]["row_sha256"] = sha(raw[0])
    with pytest.raises(CorpusContractError):
        joins.build_legacy_source_join(raw, **inputs)
