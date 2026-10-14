"""Full physical custody into detached candidate records; no reviewed law."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_source
from ipfs_datasets_py.logic.autoformal import legal_cache_parent_occurrences as occurrence_owner
from ipfs_datasets_py.logic.autoformal import legal_parent_sentence_candidates as sentence_owner
from ipfs_datasets_py.logic.autoformal.legal_statutory_context import DEPENDENCY_KINDS
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes, cid_for_bytes


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def raw_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode()


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def reseal(value):
    return contracts.seal_record(
        {
            key: deepcopy(item)
            for key, item in value.items()
            if key not in {"record_cid", "cid_scope"}
        }
    )


def incoming_fixture():
    """Load authored fixture helpers only; use actual package owners for all operations."""
    spec = importlib.util.spec_from_file_location(
        "authored_parent_fixture_for_corpus_adapter",
        Path(__file__).with_name("test_legal_cache_parent_occurrences.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def case(tmp_path, **options):
    provenance, lineage, views, old_arguments = incoming_fixture().fixture(tmp_path, **options)
    occurrences = occurrence_owner.prepare_cache_parent_occurrences(
        provenance, lineage, views, **old_arguments
    )
    sentences = sentence_owner.prepare_parent_sentence_candidates(
        views,
        expected_parent_text_views_report_sha256=old_arguments[
            "expected_parent_text_views_report_sha256"
        ],
        parent_text_views_inputs=old_arguments["parent_text_views_inputs"],
    )
    reports = {
        "parent_text_views": views,
        "cache_parent_occurrences": occurrences,
        "parent_sentence_candidates": sentences,
    }
    report_bytes = {name: raw_json(value) for name, value in reports.items()}
    pins = {
        name: {"raw_sha256": sha(report_bytes[name]), "canonical_sha256": sha(canonical(value))}
        for name, value in reports.items()
    }
    replay = {
        "provenance_reports": provenance,
        "lineage_report": lineage,
        "expected_lineage_report_sha256": old_arguments["expected_lineage_report_sha256"],
        "lineage_inputs": old_arguments["lineage_inputs"],
        "parent_text_views_inputs": old_arguments["parent_text_views_inputs"],
        "expected_record_sha256s": old_arguments["expected_record_sha256s"],
        "expected_provenance_report_sha256s": old_arguments["expected_provenance_report_sha256s"],
    }
    return {
        "reports": reports,
        "arguments": {
            "report_bytes": report_bytes,
            "expected_report_pins": pins,
            "replay_inputs": replay,
        },
    }


@pytest.fixture
def owner():
    from ipfs_datasets_py.logic.autoformal import corpus_parent_occurrence_adapter

    return corpus_parent_occurrence_adapter


def build(owner, data, **options):
    return owner.build_parent_occurrence_corpus(**data["arguments"], **options)


def validate(owner, bundle, data):
    return owner.validate_parent_occurrence_corpus(bundle, **data["arguments"])


def by_schema(bundle, schema):
    return [record for record in bundle["records"] if record["schema"] == schema]


def repin_report(data, key, mutate):
    report = json.loads(data["arguments"]["report_bytes"][key])
    mutate(report)
    raw = raw_json(report)
    data["arguments"]["report_bytes"][key] = raw
    data["arguments"]["expected_report_pins"][key] = {
        "raw_sha256": sha(raw),
        "canonical_sha256": sha(canonical(report)),
    }


@pytest.mark.parametrize(
    "report_key",
    [
        "parent_text_views",
        "cache_parent_occurrences",
        "parent_sentence_candidates",
    ],
)
@pytest.mark.parametrize("pin_kind", ["raw_sha256", "canonical_sha256"])
def test_each_complete_raw_and_canonical_report_has_an_independent_required_pin(
    owner, tmp_path, report_key, pin_kind
):
    data = case(tmp_path)
    data["arguments"]["expected_report_pins"][report_key][pin_kind] = "0" * 64
    with pytest.raises(ValueError):
        build(owner, data)


def test_pretty_raw_bytes_and_full_canonical_report_digest_are_distinct(owner, tmp_path):
    data = case(tmp_path)
    for key, pins in data["arguments"]["expected_report_pins"].items():
        assert pins["raw_sha256"] != pins["canonical_sha256"]
        assert pins["raw_sha256"] == sha(data["arguments"]["report_bytes"][key])
        assert pins["canonical_sha256"] == sha(canonical(data["reports"][key]))
    bundle = build(owner, data)
    assert set(bundle) == {"manifest", "records"}
    assert validate(owner, bundle, data) == bundle


@pytest.mark.parametrize(
    "damage",
    [
        "missing_report",
        "extra_report",
        "missing_pin",
        "extra_pin_field",
        "raw_buffer",
        "empty_bytes",
        "invalid_JSON",
        "missing_replay",
        "extra_replay",
        "callback",
    ],
)
def test_closed_complete_input_and_replay_shapes_refuse_partial_or_custom_intake(
    owner, tmp_path, damage
):
    data = case(tmp_path)
    inputs = data["arguments"]
    if damage == "missing_report":
        inputs["report_bytes"].pop("parent_sentence_candidates")
    elif damage == "extra_report":
        inputs["report_bytes"]["autoencoder"] = b"{}"
    elif damage == "missing_pin":
        inputs["expected_report_pins"].pop("cache_parent_occurrences")
    elif damage == "extra_pin_field":
        inputs["expected_report_pins"]["parent_text_views"]["verified"] = True
    elif damage == "raw_buffer":
        inputs["report_bytes"]["parent_text_views"] = bytearray(
            inputs["report_bytes"]["parent_text_views"]
        )
    elif damage == "empty_bytes":
        inputs["report_bytes"]["parent_text_views"] = b""
    elif damage == "invalid_JSON":
        raw = b'{"schema":'
        inputs["report_bytes"]["parent_text_views"] = raw
        inputs["expected_report_pins"]["parent_text_views"]["raw_sha256"] = sha(raw)
    elif damage == "missing_replay":
        inputs["replay_inputs"].pop("expected_lineage_report_sha256")
    elif damage == "extra_replay":
        inputs["replay_inputs"]["accepted"] = True
    else:
        inputs["replay_inputs"]["loader"] = lambda: pytest.fail("custom intake must never run")
    with pytest.raises(ValueError):
        build(owner, data)


@pytest.mark.parametrize(
    "damage",
    [
        "lineage_pin",
        "record_population",
        "provenance_population",
        "descriptor_pin",
        "preflight_pin",
        "physical_row_pin",
        "physical_row_order",
        "source_file_bytes",
    ],
)
def test_replay_requires_all_original_cache_producer_and_physical_parent_bindings(
    owner, tmp_path, damage
):
    data = case(tmp_path)
    replay = data["arguments"]["replay_inputs"]
    views = replay["parent_text_views_inputs"]
    if damage == "lineage_pin":
        replay["expected_lineage_report_sha256"] = "0" * 64
    elif damage == "record_population":
        replay["expected_record_sha256s"].reverse()
    elif damage == "provenance_population":
        replay["expected_provenance_report_sha256s"][0] = "0" * 64
    elif damage == "descriptor_pin":
        views["expected_parent_descriptor_sha256"] = "0" * 64
    elif damage == "preflight_pin":
        views["expected_preflight_sha256"] = "0" * 64
    elif damage == "physical_row_pin":
        views["expected_row_sha256s"][0] = "0" * 64
    elif damage == "physical_row_order":
        views["row_ordinals"].reverse()
        views["expected_row_sha256s"].reverse()
    else:
        path = Path(views["parent_descriptor"]["local_path"])
        path.write_bytes(path.read_bytes() + b"changed immutable fixture bytes")
    with pytest.raises(ValueError):
        build(owner, data)


@pytest.mark.parametrize(
    "damage",
    [
        "view_subset",
        "view_order",
        "text_normalization",
        "UTF8_geometry",
        "selected_match",
        "cache_subset",
        "cache_order",
        "zero_comparison",
        "partition_piece",
        "partition_order",
        "context_window",
        "dependency_target",
        "false_authority",
    ],
)
def test_repaired_raw_canonical_and_internal_seals_cannot_override_complete_fixed_owner_replay(
    owner, tmp_path, damage
):
    data = case(
        tmp_path,
        source_text="aa",
        parent_texts=[
            "§ Café aa aaaa under this section. Historical and Revision Notes aa. ",
            "Second without a match under paragraph (a)! ",
        ],
    )
    key = (
        "parent_text_views"
        if damage in {"view_subset", "view_order", "text_normalization"}
        else "cache_parent_occurrences"
    )
    if damage in {"partition_piece", "partition_order", "context_window", "dependency_target"}:
        key = "parent_sentence_candidates"

    def mutate(report):
        if damage == "view_subset":
            report["views"].pop()
        elif damage == "view_order":
            report["views"].reverse()
        elif damage == "text_normalization":
            report["views"][0]["text_view"]["coordinate_origin"]["normalization"] = "NFKC"
        elif damage == "UTF8_geometry":
            report["rows"][0]["comparison_views"][0]["occurrences"][0]["selector"][
                "utf8byte_start"
            ] += 1
        elif damage == "selected_match":
            report["rows"][0]["selected_occurrence"] = report["rows"][0]["comparison_views"][0][
                "occurrences"
            ][0]
        elif damage == "cache_subset":
            report["rows"].pop()
        elif damage == "cache_order":
            report["rows"].reverse()
        elif damage == "zero_comparison":
            report["rows"][0]["comparison_views"].pop()
        elif damage == "partition_piece":
            report["rows"][0]["segments"].pop()
        elif damage == "partition_order":
            report["rows"][0]["segments"].reverse()
        elif damage == "context_window":
            report["rows"][0]["segments"][0]["context"]["suffix"]["text"] += "invented context"
        elif damage == "dependency_target":
            report["rows"][0]["dependency_candidates"][0]["selected_target"] = "usc:us:10:invented"
        else:
            report["authority"]["admitted"] = True
        seal = {
            "parent_text_views": "text_views_sha256",
            "cache_parent_occurrences": "occurrences_sha256",
            "parent_sentence_candidates": "sentence_candidates_sha256",
        }[key]
        report[seal] = sha(
            canonical({field: value for field, value in report.items() if field != seal})
        )

    repin_report(data, key, mutate)
    with pytest.raises(ValueError):
        build(owner, data)


@pytest.mark.parametrize(
    "report_key",
    [
        "parent_text_views",
        "cache_parent_occurrences",
        "parent_sentence_candidates",
    ],
)
def test_internal_report_seal_is_not_the_full_external_canonical_pin(owner, tmp_path, report_key):
    data = case(tmp_path)
    seal = {
        "parent_text_views": "text_views_sha256",
        "cache_parent_occurrences": "occurrences_sha256",
        "parent_sentence_candidates": "sentence_candidates_sha256",
    }[report_key]
    data["arguments"]["expected_report_pins"][report_key]["canonical_sha256"] = data["reports"][
        report_key
    ][seal]
    with pytest.raises(ValueError):
        build(owner, data)


def original_value(data, record):
    binding = record["external_binding"]
    value = json.loads(data["arguments"]["report_bytes"][binding["report_key"]])
    pointer = binding["json_pointer"]
    assert pointer.startswith("/")
    for token in pointer.split("/")[1:]:
        key = token.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if type(value) is list else value[key]
    return value


def population_counts(data):
    views, occurrences, sentences = [
        data["reports"][name]
        for name in ("parent_text_views", "cache_parent_occurrences", "parent_sentence_candidates")
    ]
    roles = {
        "region": sum(
            len(row["text_view"]["regions"]) for row in views["views"] if row["text_view"]
        ),
        "marker": sum(
            len(row["text_view"]["marker_observations"])
            for row in views["views"]
            if row["text_view"]
        ),
        "segment": sum(len(row["segments"]) for row in sentences["rows"]),
        "dependency": sum(len(row["dependency_candidates"]) for row in sentences["rows"]),
        "boundary": sum(len(row["boundary_observations"]) for row in sentences["rows"]),
        "prefix": sum(
            segment["context"]["prefix"] is not None
            for row in sentences["rows"]
            for segment in row["segments"]
        ),
        "suffix": sum(
            segment["context"]["suffix"] is not None
            for row in sentences["rows"]
            for segment in row["segments"]
        ),
    }
    return {
        "parents": views["row_count"],
        "cache_rows": occurrences["row_count"],
        "cache_matches": occurrences["exact_occurrence_count"],
        "roles": roles,
    }


def assert_population(bundle, data):
    manifest, records = bundle["manifest"], bundle["records"]
    expected = population_counts(data)
    populations = manifest["populations"]
    assert set(populations) == {"parents", "cache_rows", "cache_matches", "roles"}
    for field in ("parents", "cache_rows", "cache_matches"):
        assert len(populations[field]) == expected[field]
    assert set(populations["roles"]) == set(expected["roles"])
    for role, count in expected["roles"].items():
        assert len(populations["roles"][role]) == count
    assert [row["record_cid"] for row in manifest["record_refs"]] == [
        row["record_cid"] for row in records
    ]
    assert len({row["record_cid"] for row in records}) == len(records)
    for record, reference in zip(records, manifest["record_refs"], strict=True):
        assert set(reference) == {"record_cid", "sha256"}
        assert reference["sha256"] == sha(canonical_dag_json_bytes(record))
        assert len(canonical_dag_json_bytes(record)) <= contracts.MAX_RECORD_BYTES
        assert reseal(record) == record
    assert len(canonical_dag_json_bytes(manifest)) <= contracts.MAX_RECORD_BYTES
    assert reseal(manifest) == manifest


def test_all_exact_origins_roles_partition_pieces_and_cache_comparisons_are_retained(
    owner, tmp_path
):
    data = case(
        tmp_path,
        source_text="aa",
        parent_texts=[
            " \tCafé aa aaaa under this section. Historical and Revision Notes aa. Tail",
            "Snow 雪 aa under paragraph (a)! \t",
        ],
    )
    bundle = build(owner, data)
    assert_population(bundle, data)
    assert all(
        len(bundle["manifest"]["populations"]["roles"][role])
        for role in ("region", "marker", "segment", "dependency", "boundary", "prefix", "suffix")
    )
    records = {record["record_cid"]: record for record in bundle["records"]}
    for parent_record in by_schema(bundle, "legal-corpus-parent-field/v1"):
        assert original_value(data, parent_record) is not None
    for role in by_schema(bundle, "legal-corpus-parent-source-role/v1"):
        value = original_value(data, role)
        assert role["external_binding"]["value_sha256"] == sha(canonical(value))
        assert role["source_occurrence_cid"] in records
        assert role["source_version_cid"] in records
        assert role["context_cid"] in records
        assert role["parent_record_cid"] in records
    assert validate(owner, bundle, data) == bundle


def test_original_report_bytes_full_canonical_hashes_and_json_pointer_values_are_losslessly_bound(
    owner, tmp_path
):
    data = case(tmp_path)
    bundle = build(owner, data)
    bindings = [row["external_binding"] for row in bundle["records"] if "external_binding" in row]
    assert bindings
    for row in bundle["records"]:
        if "external_binding" not in row:
            continue
        binding = row["external_binding"]
        raw = data["arguments"]["report_bytes"][binding["report_key"]]
        pins = data["arguments"]["expected_report_pins"][binding["report_key"]]
        assert binding["report_raw_cid"] == cid_for_bytes(raw)
        assert binding["report_raw_sha256"] == pins["raw_sha256"]
        assert binding["report_canonical_sha256"] == pins["canonical_sha256"]
        assert binding["value_sha256"] == sha(canonical(original_value(data, row)))
    assert {binding["report_key"] for binding in bindings} == set(data["arguments"]["report_bytes"])


def test_every_physical_occurrence_has_explicit_unavailable_context_without_governing_claims(
    owner, tmp_path
):
    data = case(tmp_path)
    bundle = build(owner, data)
    occurrences = by_schema(bundle, corpus_source.SOURCE_OCCURRENCE_SCHEMA)
    contexts = by_schema(bundle, corpus_source.CONTEXT_DECLARATION_SCHEMA)
    assert occurrences
    assert {row["source_occurrence_cid"] for row in contexts} == {
        row["record_cid"] for row in occurrences
    }
    for declaration in contexts:
        assert declaration["availability"] == "required_unavailable"
        assert len(declaration["context_references"]) == 1
        reference = declaration["context_references"][0]
        occurrence = next(
            row for row in occurrences if row["record_cid"] == declaration["source_occurrence_cid"]
        )
        assert reference["record_cid"] == occurrence["source_version_cid"]
        assert reference["record_kind"] == "source_version"
        assert declaration["missing_requirements"] == list(DEPENDENCY_KINDS)
        assert declaration["dependency_verification"] == "declaration_only"
    for occurrence in occurrences:
        assert occurrence["historical_aliases"] == []
        assert occurrence["coordinate_system"] == corpus_source.COORDINATE_SYSTEM
    for record in [bundle["manifest"], *bundle["records"]]:
        for flag in (
            "admitted",
            "formalized",
            "source_semantics_verified",
            "source_authenticity_verified",
            "context_closure_verified",
            "independently_reviewed",
            "proof_authority",
            "training_qualified",
        ):
            if flag in record:
                assert record[flag] is False


def test_literal_Unicode_and_UTF8_geometry_never_collapses_normalized_aliases(owner, tmp_path):
    data = case(tmp_path, source_text="é", parent_texts=["雪 é e\u0301 é. ", "e\u0301 only. "])
    bundle = build(owner, data)
    assert_population(bundle, data)
    matches = by_schema(bundle, "legal-corpus-parent-cache-match/v1")
    records = {record["record_cid"]: record for record in bundle["records"]}
    assert len(matches) == 4
    geometry = []
    for match in matches:
        occurrence = records[match["source_occurrence_cid"]]
        assert occurrence["span_text"] == "é"
        assert occurrence["start_utf8"] != occurrence["start_char"]
        geometry.append(
            (occurrence["source_version_cid"], occurrence["start_char"], occurrence["end_char"])
        )
    assert len(set(geometry)) == 2
    assert len({match["source_occurrence_cid"] for match in matches}) == 2
    versions = by_schema(bundle, corpus_source.SOURCE_VERSION_SCHEMA)
    assert len(versions) == 2
    for version in versions:
        assert version["extracted_view"]["normalization_profile"] == "identity/v1"
        assert "normalized-view" not in version["extracted_view"]["extraction_profile"]


def test_equal_raw_cache_rows_keep_distinct_binding_records_for_shared_physical_occurrences(
    owner, tmp_path
):
    data = case(tmp_path, cache_change=lambda rows: rows.__setitem__(1, deepcopy(rows[0])))
    original = data["reports"]["cache_parent_occurrences"]["rows"]
    assert original[0]["raw_row_sha256"] == original[1]["raw_row_sha256"]
    assert original[0]["record_sha256"] != original[1]["record_sha256"]
    bundle = build(owner, data)
    assert_population(bundle, data)
    cache_rows = by_schema(bundle, "legal-corpus-parent-cache-row/v1")
    matches = by_schema(bundle, "legal-corpus-parent-cache-match/v1")
    assert len(cache_rows) == 2 and cache_rows[0]["record_cid"] != cache_rows[1]["record_cid"]
    assert len(matches) == data["reports"]["cache_parent_occurrences"]["exact_occurrence_count"]
    assert len({match["source_occurrence_cid"] for match in matches}) * 2 == len(matches)
    assert len({match["record_cid"] for match in matches}) == len(matches)


def test_identical_parent_text_at_distinct_physical_rows_remains_distinct_source_versions(
    owner, tmp_path
):
    data = case(tmp_path, source_text="aa", parent_texts=["Café aa. ", "Café aa. "])
    bundle = build(owner, data)
    versions = by_schema(bundle, corpus_source.SOURCE_VERSION_SCHEMA)
    assert len(versions) == 2
    assert len({version["record_cid"] for version in versions}) == 2
    assert len({version["extracted_view"]["sha256"] for version in versions}) == 1
    assert_population(bundle, data)


@pytest.mark.parametrize(
    "limit",
    [
        "max_report_bytes",
        "max_replay_bytes",
        "max_total_input_bytes",
        "max_records",
        "max_collection_bytes",
    ],
)
def test_lowered_whole_batch_limits_refuse_without_selecting_an_easy_prefix(owner, tmp_path, limit):
    data = case(tmp_path)
    with pytest.raises(ValueError):
        build(owner, data, limits={limit: 1})


@pytest.mark.parametrize(
    "limits",
    [{"made_up_limit": 1}, {"max_records": True}, {"max_records": 0}, {"max_records": 10**12}],
)
def test_limit_profile_is_closed_integer_lower_only(owner, tmp_path, limits):
    with pytest.raises(ValueError):
        build(owner, case(tmp_path), limits=limits)


def test_detached_large_collection_exceeds_one_envelope_without_raising_common_record_limit(
    owner, tmp_path
):
    assert contracts.MAX_RECORD_BYTES == 1024 * 1024
    data = case(
        tmp_path,
        source_text="unmatched cache literal",
        parent_texts=["Café " + "z" * 60000 + ". \t"] * 8,
    )
    bundle = build(owner, data)
    assert_population(bundle, data)
    sizes = [len(canonical_dag_json_bytes(record)) for record in bundle["records"]]
    assert sum(sizes) > contracts.MAX_RECORD_BYTES
    assert max(sizes) <= contracts.MAX_RECORD_BYTES
    assert len(canonical_dag_json_bytes(bundle["manifest"])) <= contracts.MAX_RECORD_BYTES
    assert contracts.MAX_RECORD_BYTES == 1024 * 1024
    assert validate(owner, bundle, data) == bundle


def test_actual_public_module_import_is_inert():
    program = """
import json,sys
from ipfs_datasets_py.logic.autoformal import corpus_parent_occurrence_adapter
blocked=[name for name in sys.modules if name in {"torch","transformers","pyarrow"}
  or name.endswith("canonical_compiler") or name.endswith("legal_source_definition_norm_bridge")
  or name.endswith("backends.process")]
assert not blocked,blocked
print(json.dumps(corpus_parent_occurrence_adapter.__file__))
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        env=dict(os.environ, IPFS_DATASETS_PY_MINIMAL_IMPORTS="1"),
        capture_output=True,
        text=True,
        check=True,
    )
    expected = (
        Path(__file__).resolve().parents[4]
        / "ipfs_datasets_py/logic/autoformal/corpus_parent_occurrence_adapter.py"
    )
    assert Path(json.loads(result.stdout)).resolve() == expected


@pytest.mark.parametrize(
    "damage", ["wrong_source_hash", "missing_legal_id", "missing_source_text", "missing_span_id"]
)
def test_unsupported_or_conflicting_cache_declarations_remain_complete_observations(
    owner, tmp_path, damage
):
    def change(rows):
        if damage == "wrong_source_hash":
            rows[0]["source"]["text_sha256"] = "0" * 64
        elif damage == "missing_legal_id":
            rows[0]["source"]["legal_id"] = None
        elif damage == "missing_source_text":
            rows[0]["source"]["text"] = None
        else:
            rows[0]["source"]["span_id"] = None

    data = case(tmp_path, cache_change=change)
    bundle = build(owner, data)
    assert_population(bundle, data)
    rows = by_schema(bundle, "legal-corpus-parent-cache-row/v1")
    assert len(rows) == 2
    assert [original_value(data, row) for row in rows] == data["reports"][
        "cache_parent_occurrences"
    ]["rows"]
    if damage == "missing_source_text":
        assert data["reports"]["cache_parent_occurrences"]["rows"][0]["exact_occurrence_count"] == 0
    else:
        assert data["reports"]["cache_parent_occurrences"]["rows"][0]["exact_occurrence_count"] > 0
    assert validate(owner, bundle, data) == bundle


@pytest.mark.parametrize("missing", [None, ""])
def test_unavailable_parent_fields_and_all_zero_comparison_cells_stay_in_the_population(
    owner, tmp_path, missing
):
    data = case(tmp_path, parent_texts=[missing, "Second aa body. "])
    bundle = build(owner, data)
    assert_population(bundle, data)
    assert len(by_schema(bundle, "legal-corpus-parent-field/v1")) == 2
    assert len(by_schema(bundle, corpus_source.SOURCE_VERSION_SCHEMA)) == 1
    for row in by_schema(bundle, "legal-corpus-parent-cache-row/v1"):
        original = original_value(data, row)
        assert len(original["comparison_views"]) == 2
        assert original["comparison_views"][0]["occurrence_count"] == 0
        assert original["comparison_views"][0]["view_available"] is False
        assert original["status"] == "comparison_parent_view_unavailable"
    assert validate(owner, bundle, data) == bundle


def test_lossless_sentence_roles_reconstruct_every_original_character_and_gap(owner, tmp_path):
    data = case(
        tmp_path,
        source_text="Café",
        parent_texts=[
            " \tCafé acts under this section.\n雪 waits!\u00a0Last fragment  ",
            "Second Café under paragraph (a). ",
        ],
    )
    bundle = build(owner, data)
    records = {record["record_cid"]: record for record in bundle["records"]}
    by_parent = {}
    for identity in bundle["manifest"]["populations"]["roles"]["segment"]:
        role = records[identity]
        original = original_value(data, role)
        occurrence = records[role["source_occurrence_cid"]]
        assert occurrence["span_text"] == original["selector"]["text"]
        by_parent.setdefault(role["parent_record_cid"], []).append(occurrence)
    for parent in by_schema(bundle, "legal-corpus-parent-field/v1"):
        original = original_value(data, parent)
        pieces = by_parent[parent["record_cid"]]
        text = "".join(piece["span_text"] for piece in pieces)
        view = original.get("text_view", original.get("raw_row", original))
        assert text == view["text"]
        assert pieces[0]["start_char"] == 0 and pieces[-1]["end_char"] == len(text)
        for left, right in zip(pieces, pieces[1:], strict=False):
            assert left["end_char"] == right["start_char"]
            assert left["end_utf8"] == right["start_utf8"]


def test_all_source_producer_pins_and_record_inventory_bind_actual_current_bytes(owner, tmp_path):
    from ipfs_datasets_py.logic.autoformal import legal_span_section_bridge

    data = case(tmp_path)
    bundle = build(owner, data)
    pins = bundle["manifest"]["producer_pins"]
    assert pins
    for path, digest in pins.items():
        assert Path(path).is_absolute()
        assert sha(Path(path).read_bytes()) == digest
    assert str(Path(owner.__file__).resolve()) in pins
    assert str(Path(contracts.__file__).resolve()) in pins
    assert str(Path(occurrence_owner.__file__).resolve()) in pins
    assert str(Path(sentence_owner.__file__).resolve()) in pins
    assert str(Path(legal_span_section_bridge.__file__).resolve()) in pins
    assert_population(bundle, data)


@pytest.mark.parametrize(
    "damage", ["manifest_authority", "producer_pin", "record_order", "binding_value"]
)
def test_repaired_bundle_seals_inventory_hashes_and_owner_pins_require_original_full_replay(
    owner, tmp_path, damage
):
    data = case(tmp_path)
    bundle = build(owner, data)
    if damage == "manifest_authority":
        bundle["manifest"]["admitted"] = True
    elif damage == "producer_pin":
        first = next(iter(bundle["manifest"]["producer_pins"]))
        bundle["manifest"]["producer_pins"][first] = "0" * 64
    elif damage == "record_order":
        bundle["records"].reverse()
        bundle["manifest"]["record_refs"].reverse()
    else:
        at = next(i for i, record in enumerate(bundle["records"]) if "external_binding" in record)
        old = bundle["records"][at]["record_cid"]
        bundle["records"][at]["external_binding"]["value_sha256"] = "0" * 64
        changed = reseal(bundle["records"][at])
        bundle["records"][at] = changed
        bundle["manifest"]["record_refs"][at] = {
            "record_cid": changed["record_cid"],
            "sha256": sha(canonical_dag_json_bytes(changed)),
        }

        def replace(value):
            if type(value) is dict:
                return {key: replace(item) for key, item in value.items()}
            if type(value) is list:
                return [replace(item) for item in value]
            return changed["record_cid"] if value == old else value

        bundle["manifest"]["populations"] = replace(bundle["manifest"]["populations"])
    bundle["manifest"] = reseal(bundle["manifest"])
    with pytest.raises(ValueError):
        validate(owner, bundle, data)


@pytest.mark.parametrize(
    "damage", ["drop_record", "extra_record", "unknown_root_field", "nonlist_records"]
)
def test_closed_detached_collection_never_accepts_missing_extra_or_custom_records(
    owner, tmp_path, damage
):
    data = case(tmp_path)
    bundle = build(owner, data)
    if damage == "drop_record":
        bundle["records"].pop()
    elif damage == "extra_record":
        bundle["records"].append(
            contracts.seal_record({"schema": "unlisted-record/v1", "value": "unknown"})
        )
    elif damage == "unknown_root_field":
        bundle["independently_reviewed"] = True
    else:
        bundle["records"] = tuple(bundle["records"])
    with pytest.raises(ValueError):
        validate(owner, bundle, data)


def test_original_inputs_are_still_required_when_consuming_valid_sealed_records(owner, tmp_path):
    data = case(tmp_path)
    bundle = build(owner, data)
    path = Path(
        data["arguments"]["replay_inputs"]["parent_text_views_inputs"]["parent_descriptor"][
            "local_path"
        ]
    )
    path.write_bytes(path.read_bytes() + b"stale independently pinned parent")
    with pytest.raises(ValueError):
        validate(owner, bundle, data)


def test_bundle_records_are_detached_from_all_mutable_caller_reports_pins_and_replay(
    owner, tmp_path
):
    data = case(tmp_path)
    bundle = build(owner, data)
    saved = deepcopy(bundle)
    data["arguments"]["expected_report_pins"].clear()
    data["arguments"]["report_bytes"].clear()
    data["arguments"]["replay_inputs"]["provenance_reports"].clear()
    data["reports"]["parent_text_views"]["views"].clear()
    assert bundle == saved


@pytest.mark.parametrize("phase", ["after_fixed_replay", "after_projection"])
def test_producer_source_drift_during_replay_or_projection_refuses_the_whole_batch(
    owner, tmp_path, monkeypatch, phase
):
    data = case(tmp_path)
    original = owner._pins
    calls = 0
    cutoff = 2 if phase == "after_fixed_replay" else 3

    def changed(owners):
        nonlocal calls
        calls += 1
        result = original(owners)
        if calls >= cutoff:
            result[str(Path(owner.__file__).resolve())] = "0" * 64
        return result

    monkeypatch.setattr(owner, "_pins", changed)
    with pytest.raises(contracts.CorpusContractError):
        build(owner, data)
    assert calls >= cutoff


@pytest.mark.parametrize("phase", ["after_fixed_replay", "after_projection"])
def test_direct_span_profile_owner_drift_cannot_escape_the_producer_closure(
    owner, tmp_path, monkeypatch, phase
):
    from ipfs_datasets_py.logic.autoformal import legal_span_section_bridge

    data = case(tmp_path)
    profile_path = str(Path(legal_span_section_bridge.__file__).resolve())
    original = owner._pins
    calls = 0
    cutoff = 2 if phase == "after_fixed_replay" else 3

    def changed(owners):
        nonlocal calls
        calls += 1
        result = original(owners)
        assert result[profile_path] == sha(Path(profile_path).read_bytes())
        if calls >= cutoff:
            result[profile_path] = "0" * 64
        return result

    monkeypatch.setattr(owner, "_pins", changed)
    with pytest.raises(contracts.CorpusContractError):
        build(owner, data)
    assert calls >= cutoff


@pytest.mark.parametrize("budget", ["replay", "aggregate_input"])
def test_wide_untrusted_replay_refuses_before_bulk_json_serialization(
    owner, tmp_path, monkeypatch, budget
):
    data = case(tmp_path)
    replay = data["arguments"]["replay_inputs"]
    replay["provenance_reports"][0]["rows"][0]["raw_row"]["unknown_cache"]["wide_candidate"] = {
        "field:" + str(index): "雪" * 128 for index in range(1000)
    }
    target = replay
    original_dumps = owner.json.dumps
    bulk_target_seen = False

    def sentinel(value, *args, **kwargs):
        nonlocal bulk_target_seen
        if value is target:
            bulk_target_seen = True
            pytest.fail("oversized replay reached bulk JSON serialization before refusal")
        return original_dumps(value, *args, **kwargs)

    monkeypatch.setattr(owner.json, "dumps", sentinel)
    limit = 64 * 1024
    limits = (
        {"max_replay_bytes": limit}
        if budget == "replay"
        else {
            "max_total_input_bytes": sum(map(len, data["arguments"]["report_bytes"].values()))
            + limit,
        }
    )
    with pytest.raises(contracts.CorpusContractError):
        build(owner, data, limits=limits)
    assert bulk_target_seen is False


@pytest.mark.parametrize("budget", ["replay", "aggregate_input"])
def test_JSON_escaping_counts_toward_replay_budget_before_bulk_serialization(
    owner, tmp_path, monkeypatch, budget
):
    data = case(tmp_path)
    replay = data["arguments"]["replay_inputs"]
    baseline = len(canonical(replay))
    replay["provenance_reports"][0]["rows"][0]["raw_row"]["unknown_cache"]["escaped_candidate"] = (
        "\n" * 10000
    )
    limit = baseline + 15000
    assert len(canonical(replay)) > limit
    original_dumps = owner.json.dumps
    bulk_target_seen = False

    def sentinel(value, *args, **kwargs):
        nonlocal bulk_target_seen
        if value is replay:
            bulk_target_seen = True
            pytest.fail("JSON escaping exceeded the replay budget before bulk serialization")
        return original_dumps(value, *args, **kwargs)

    monkeypatch.setattr(owner.json, "dumps", sentinel)
    limits = (
        {"max_replay_bytes": limit}
        if budget == "replay"
        else {
            "max_total_input_bytes": sum(map(len, data["arguments"]["report_bytes"].values()))
            + limit,
        }
    )
    with pytest.raises(contracts.CorpusContractError):
        build(owner, data, limits=limits)
    assert bulk_target_seen is False
