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


def case(tmp_path, *, source_profile=None, **options):
    provenance, lineage, views, old_arguments = incoming_fixture().fixture(tmp_path, **options)
    occurrences = occurrence_owner.prepare_cache_parent_occurrences(
        provenance, lineage, views, source_profile=source_profile, **old_arguments
    )
    sentences = sentence_owner.prepare_parent_sentence_candidates(
        views,
        expected_parent_text_views_report_sha256=old_arguments[
            "expected_parent_text_views_report_sha256"
        ],
        parent_text_views_inputs=old_arguments["parent_text_views_inputs"],
        source_profile=source_profile,
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
    if source_profile is not None:
        replay["source_profile"] = source_profile
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


def test_complete_parent_128k_corpus_replays_complete_unicode_field(owner, tmp_path):
    characters = 71_688
    text = "雪" + "a" * (characters - 3) + "é."
    data = case(tmp_path, parent_texts=[text], source_text="é", source_profile="complete-parent-128k/v1")
    bundle = build(owner, data)
    assert validate(owner, bundle, data) == bundle
    manifest = bundle["manifest"]
    assert manifest["profile"] == owner.COMPLETE_PARENT_128K_MANIFEST_PROFILE
    assert manifest["replay_bindings"]["source_profile"] == "complete-parent-128k/v1"
    assert manifest["counts"]["source_characters"] == characters
    assert manifest["counts"]["source_utf8_bytes"] == len(text.encode())
    assert manifest["limits"] == owner.DEFAULT_LIMITS
    assert manifest["counts"]["physical_parent_rows"] == manifest["counts"]["physical_cache_rows"] == 1
    occurrences = by_schema(bundle, corpus_source.SOURCE_OCCURRENCE_SCHEMA)
    whole = [row for row in occurrences if row["start_char"] == 0 and row["end_char"] == characters]
    assert len(whole) == 1 and whole[0]["span_text"] == text and whole[0]["end_utf8"] == len(text.encode())
    matched = [row for row in occurrences if row["span_text"] == "é"]
    assert len(matched) == 1 and matched[0]["start_utf8"] == len(text[:-2].encode())
    assert all(manifest[key] is False for key in owner.FALSE_FLAGS)
    assert all(manifest[key] is None for key in owner.UNSELECTED)


@pytest.mark.parametrize("damage", ["missing_selector", "unknown_selector", "boolean_selector",
    "legacy_occurrence_report", "legacy_sentence_report", "manifest_profile"])
def test_complete_parent_profile_cannot_be_transplanted_between_replay_and_reports(owner, tmp_path, damage):
    data = case(tmp_path, source_profile="complete-parent-128k/v1")
    replay = data["arguments"]["replay_inputs"]
    if damage == "manifest_profile":
        bundle = build(owner, data)
        bundle["manifest"]["profile"] = owner.PROFILE
        bundle["manifest"] = reseal(bundle["manifest"])
        with pytest.raises(ValueError, match="independent regeneration"):
            validate(owner, bundle, data)
        return
    if damage == "missing_selector":
        replay.pop("source_profile")
    elif damage == "unknown_selector":
        replay["source_profile"] = "unknown"
    elif damage == "boolean_selector":
        replay["source_profile"] = True
    else:
        key, seal = ("cache_parent_occurrences", "occurrences_sha256") if damage == "legacy_occurrence_report" else ("parent_sentence_candidates", "sentence_candidates_sha256")
        def downgrade(report):
            report.pop("source_profile")
            report["limits"]["max_source_characters"] = 65_536
            report.pop(seal)
            report[seal] = sha(canonical(report))
        repin_report(data, key, downgrade)
    with pytest.raises(ValueError, match="source profile"):
        build(owner, data)


def test_default_parent_profile_preserves_legacy_replay_and_manifest_shape(owner, tmp_path):
    data = case(tmp_path)
    assert set(data["arguments"]["replay_inputs"]) == owner.REPLAY_FIELDS
    assert all("source_profile" not in data["reports"][key]
        and data["reports"][key]["limits"]["max_source_characters"] == 65_536
        for key in ("cache_parent_occurrences", "parent_sentence_candidates"))
    bundle = build(owner, data)
    assert bundle["manifest"]["profile"] == owner.PROFILE
    assert "source_profile" not in bundle["manifest"]["replay_bindings"]
    assert validate(owner, bundle, data) == bundle


def paged_case(owner, tmp_path, *, duplicate_parent=False):
    texts = ["Café. \t" * 24] * (2 if duplicate_parent else 1)
    data = case(tmp_path, parent_texts=texts, source_text="unmatched cache literal")
    data["arguments"]["replay_inputs"]["inventory_profile"] = owner.PAGED_INVENTORY_PROFILE
    return data


def inventory_pages(owner, bundle):
    return by_schema(bundle, owner.INVENTORY_PAGE_SCHEMA)


def repair_inventory_page_seals(owner, bundle, *, repair_offsets=True):
    leaves = [row for row in bundle["records"] if row["schema"] != owner.INVENTORY_PAGE_SCHEMA]
    pages = inventory_pages(owner, bundle)
    repaired, refs, first = [], [], 0
    for number, page in enumerate(pages):
        if repair_offsets:
            page["page_ordinal"] = number
            page["first_record_ordinal"] = first
        page = reseal(page)
        repaired.append(page)
        entries = page["entries"]
        refs.append({"page_cid": page["record_cid"], "sha256": sha(canonical_dag_json_bytes(page)),
            "page_ordinal": page["page_ordinal"], "first_record_ordinal": page["first_record_ordinal"],
            "record_count": len(entries), "first_record_cid": entries[0]["record_cid"],
            "last_record_cid": entries[-1]["record_cid"]})
        first += len(entries)
    bundle["records"] = leaves + repaired
    bundle["manifest"]["page_refs"] = refs
    bundle["manifest"]["counts"]["records"] = len(bundle["records"])
    bundle["manifest"]["counts"]["record_kinds"]["inventory_page"] = len(repaired)
    bundle["manifest"] = reseal(bundle["manifest"])


def test_paged_record_refs_keep_complete_leaf_records_reports_and_populations(owner, tmp_path):
    data = paged_case(owner, tmp_path, duplicate_parent=True)
    legacy_data = deepcopy(data)
    legacy_data["arguments"]["replay_inputs"].pop("inventory_profile")
    legacy = build(owner, legacy_data)
    before = deepcopy(data)
    bundle = build(owner, data)
    pages = inventory_pages(owner, bundle)
    assert set(bundle) == {"manifest", "records"}
    assert len(pages) >= 2
    assert bundle["records"][:-len(pages)] == legacy["records"]
    assert bundle["manifest"]["populations"] == legacy["manifest"]["populations"]
    assert [entry for page in pages for entry in page["entries"]] == legacy["manifest"]["record_refs"]
    assert bundle["manifest"]["profile"] == owner.PAGED_MANIFEST_PROFILE
    assert "record_refs" not in bundle["manifest"]
    assert bundle["manifest"]["replay_bindings"]["inventory_profile"] == owner.PAGED_INVENTORY_PROFILE
    assert bundle["manifest"]["counts"]["records"] == len(bundle["records"])
    assert bundle["manifest"]["counts"]["record_kinds"]["inventory_page"] == len(pages)
    versions = by_schema(bundle, corpus_source.SOURCE_VERSION_SCHEMA)
    assert len(versions) == len({version["record_cid"] for version in versions}) == 2
    assert len({version["extracted_view"]["sha256"] for version in versions}) == 1
    assert all(0 < len(page["entries"]) <= 256 for page in pages)
    assert all(len(canonical_dag_json_bytes(page)) <= contracts.MAX_RECORD_BYTES for page in pages)
    assert all(page[key] is False for page in pages for key in owner.FALSE_FLAGS)
    assert all(page[key] is None for page in pages for key in owner.UNSELECTED)
    assert validate(owner, bundle, data) == bundle
    assert data == before


def test_paged_record_refs_bind_genuine_parent_consumer_without_governing_selection(owner, tmp_path):
    from ipfs_datasets_py.logic.autoformal import legal_semantic_graph

    data = paged_case(owner, tmp_path)
    bundle = build(owner, data)
    companion = next(row for row in bundle["records"]
        if row["schema"] == owner.ROLE_SCHEMA and row["role"] == "segment")
    bound = legal_semantic_graph.bind_parent_source_occurrence(bundle,
        expected_manifest_cid=bundle["manifest"]["record_cid"],
        source_occurrence_cid=companion["source_occurrence_cid"],
        companion_record_cid=companion["record_cid"], **data["arguments"])
    assert bound["selector"]["record_cid"] == companion["source_occurrence_cid"]
    assert bound["companion_record"] == companion
    assert bound["context"]["availability"] == "required_unavailable"
    assert bound["context"]["missing_requirements"] == list(owner.MISSING_CONTEXT)
    assert bound["edition"] == owner.UNDECLARED_EDITION
    assert bound["parent_manifest_cid"] == bundle["manifest"]["record_cid"]


def test_paged_record_refs_combine_with_complete_parent_source_profile(owner, tmp_path):
    text = "雪" + "a" * 71_685 + "é."
    data = case(tmp_path, parent_texts=[text], source_text="é", source_profile="complete-parent-128k/v1")
    data["arguments"]["replay_inputs"]["inventory_profile"] = owner.PAGED_INVENTORY_PROFILE
    original_reports = deepcopy(data["arguments"]["report_bytes"])
    bundle = build(owner, data)
    assert len(data["arguments"]["replay_inputs"]) == 9
    assert bundle["manifest"]["profile"] == owner.PAGED_COMPLETE_PARENT_128K_MANIFEST_PROFILE
    assert bundle["manifest"]["replay_bindings"]["source_profile"] == "complete-parent-128k/v1"
    assert bundle["manifest"]["replay_bindings"]["inventory_profile"] == owner.PAGED_INVENTORY_PROFILE
    assert data["arguments"]["report_bytes"] == original_reports
    assert all("inventory_profile" not in report for report in data["reports"].values())
    assert validate(owner, bundle, data) == bundle


def test_omitted_and_none_inventory_profiles_keep_identical_current_legacy_bytes(owner, tmp_path):
    data = case(tmp_path)
    legacy = build(owner, data)
    explicit_none = deepcopy(data)
    explicit_none["arguments"]["replay_inputs"]["inventory_profile"] = None
    same = build(owner, explicit_none)
    assert canonical_dag_json_bytes(same) == canonical_dag_json_bytes(legacy)
    assert same["manifest"]["profile"] == owner.PROFILE
    assert set(same) == {"manifest", "records"}
    assert "record_refs" in same["manifest"] and "page_refs" not in same["manifest"]
    assert "inventory_profile" not in same["manifest"]["replay_bindings"]
    assert not inventory_pages(owner, same)
    assert set(owner.REPLAY_FIELDS) == {"provenance_reports", "lineage_report",
        "expected_lineage_report_sha256", "lineage_inputs", "parent_text_views_inputs",
        "expected_record_sha256s", "expected_provenance_report_sha256s"}
    assert validate(owner, same, explicit_none) == same
    assert explicit_none["arguments"]["replay_inputs"]["inventory_profile"] is None


@pytest.mark.parametrize("selector", ["unknown", True, 1, {}, []],
    ids=["unknown", "boolean", "integer", "object", "array"])
def test_inventory_profile_selector_refuses_before_operation_owner_import(owner, tmp_path, monkeypatch, selector):
    data = case(tmp_path)
    data["arguments"]["replay_inputs"]["inventory_profile"] = selector
    def forbidden():
        raise AssertionError("operation owners must not import for an invalid inventory selector")
    monkeypatch.setattr(owner, "_owners", forbidden)
    with pytest.raises(ValueError, match="inventory profile"):
        build(owner, data)


def test_paged_inventory_permission_is_never_inferred_from_offered_manifest(owner, tmp_path):
    data = paged_case(owner, tmp_path)
    bundle = build(owner, data)
    legacy_data = deepcopy(data)
    legacy_data["arguments"]["replay_inputs"].pop("inventory_profile")
    with pytest.raises(ValueError):
        validate(owner, bundle, legacy_data)
    legacy = build(owner, legacy_data)
    with pytest.raises(ValueError):
        validate(owner, legacy, data)
    bundle["manifest"]["profile"] = owner.PROFILE
    bundle["manifest"] = reseal(bundle["manifest"])
    with pytest.raises(ValueError, match="independent regeneration"):
        validate(owner, bundle, data)


@pytest.mark.parametrize("damage", ["missing_page", "page_order", "missing_entry", "entry_order",
    "forged_hash", "duplicate_entry", "wrong_offset", "page_authority", "root_ref_hash"])
def test_resealed_paged_inventory_cannot_replace_complete_original_population(owner, tmp_path, damage):
    data = paged_case(owner, tmp_path)
    bundle = build(owner, data)
    pages = inventory_pages(owner, bundle)
    assert len(pages) >= 2
    if damage == "missing_page":
        bundle["records"].remove(pages[-1])
    elif damage == "page_order":
        leaves = [row for row in bundle["records"] if row["schema"] != owner.INVENTORY_PAGE_SCHEMA]
        bundle["records"] = leaves + list(reversed(pages))
    elif damage == "missing_entry":
        pages[0]["entries"].pop()
    elif damage == "entry_order":
        pages[0]["entries"][0], pages[0]["entries"][1] = pages[0]["entries"][1], pages[0]["entries"][0]
    elif damage == "forged_hash":
        pages[0]["entries"][0]["sha256"] = "0" * 64
    elif damage == "duplicate_entry":
        pages[0]["entries"][1] = deepcopy(pages[0]["entries"][0])
    elif damage == "wrong_offset":
        pages[0]["first_record_ordinal"] = 1
    elif damage == "page_authority":
        pages[0]["admitted"] = True
    repair_inventory_page_seals(owner, bundle, repair_offsets=damage != "wrong_offset")
    if damage == "root_ref_hash":
        bundle["manifest"]["page_refs"][0]["sha256"] = "0" * 64
        bundle["manifest"] = reseal(bundle["manifest"])
    with pytest.raises(ValueError):
        validate(owner, bundle, data)


def test_inventory_page_256_and_257_reference_boundaries_use_existing_sealed_records(owner):
    references = []
    for number in range(257):
        record = contracts.seal_record({"schema": "authored-inventory-boundary-fixture/v1", "ordinal": number})
        references.append({"record_cid": record["record_cid"], "sha256": sha(canonical_dag_json_bytes(record))})
    at_limit = owner._inventory_pages(references[:256])
    after_limit = owner._inventory_pages(references)
    assert [len(page["entries"]) for page in at_limit] == [256]
    assert [len(page["entries"]) for page in after_limit] == [256, 1]
    assert [page["first_record_ordinal"] for page in after_limit] == [0, 256]
    assert [entry for page in after_limit for entry in page["entries"]] == references
    assert all(len(canonical_dag_json_bytes(page)) <= contracts.MAX_RECORD_BYTES for page in after_limit)


def test_inventory_pages_consume_existing_record_and_whole_collection_budgets(owner, tmp_path):
    data = paged_case(owner, tmp_path)
    legacy_data = deepcopy(data)
    legacy_data["arguments"]["replay_inputs"].pop("inventory_profile")
    legacy = build(owner, legacy_data)
    count_limit = {"max_records": len(legacy["records"])}
    assert build(owner, legacy_data, limits=count_limit)["manifest"]["counts"]["records"] == len(legacy["records"])
    with pytest.raises(ValueError, match="record population exceeds bound"):
        build(owner, data, limits=count_limit)
    # The representation is counted inside the same finite detached collection.
    paged = build(owner, data)
    assert len(canonical_dag_json_bytes(paged)) > len(canonical_dag_json_bytes(legacy))
    byte_limit = {"max_collection_bytes": len(canonical_dag_json_bytes(legacy))}
    with pytest.raises(ValueError, match="bound"):
        build(owner, data, limits=byte_limit)
    assert owner.DEFAULT_LIMITS["max_records"] == 8192
    assert owner.DEFAULT_LIMITS["max_collection_bytes"] == 16 * 1024**2
    assert contracts.MAX_RECORD_BYTES == 1024**2
