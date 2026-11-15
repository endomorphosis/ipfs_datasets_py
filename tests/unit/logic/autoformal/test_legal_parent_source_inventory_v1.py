"""Source-only selected-parent inventory checks against genuine physical bytes.

Arrow writes independent engineering fixtures. The existing public bounded
page owner replays them and the exact retained historical parent. No cache,
candidate, formal target, vector, model or current-release inventory is an
input to source metadata construction.
"""
from copy import deepcopy
import hashlib
import inspect
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import legal_parent_parquet_pages as pages
from ipfs_datasets_py.logic.autoformal import legal_parent_source_inventory_v1 as inventory
from tests.unit.logic.autoformal.test_legal_parent_parquet_pages import fixture, reader_inputs


EVIDENCE_NAME = "source-parent-inventory-engineering-evidence.json"
REAL_ORDINALS = [2720, 2721, 2722, 2724, 2726, 2727, 3345, 3352, 3353,
    3354, 3355, 3357, 3358]
REAL_ORIGINALS = {
    "row_pins": ("LEGAL_PARENT_ROW_PINS", 3439,
        "1400269e4a664d431dd79649c9014ee200e6466ca87c1fbe423127288271e2e1"),
    "retained_sections": ("LEGAL_PARENT_EXPECTED_SECTIONS", 123063,
        "14305627bc8148ea409d97acbb7c78610f3f5e37cd5d6ca63f1bcfd69e96db5e"),
}


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def prepare(descriptor, row_report, row_arguments):
    return inventory.prepare_selected_parent_source_inventory_v1(descriptor, row_report,
        expected_row_report_sha256=pages.parent_row_report_sha256(row_report), **row_arguments)


def validate(report, descriptor, row_report, row_arguments):
    return inventory.validate_selected_parent_source_inventory_v1(report, descriptor, row_report,
        expected_report_sha256=inventory.selected_parent_source_inventory_sha256(report),
        expected_row_report_sha256=pages.parent_row_report_sha256(row_report), **row_arguments)


def fixture_report(tmp_path, *, dictionary=True, ordinals=None):
    _, descriptor, expected = fixture(tmp_path, dictionary=dictionary)
    ordinals = [0, 3, 6, 7, 18, 30] if ordinals is None else ordinals
    arguments = reader_inputs(descriptor, expected, ordinals)
    rows = pages.read_selected_parent_rows(descriptor, **arguments)
    return descriptor, expected, arguments, rows


def small_report(tmp_path, values, *, text_type=None, omit_text=False):
    schema = pa.schema([("ipfs_cid", pa.string()), ("title_number", pa.string()),
        ("section_number", pa.string())] + ([] if omit_text else [("text", text_type or pa.string())]))
    expected = [{"ipfs_cid": "cid:" + str(i), "title_number": "10", "section_number": str(i + 1),
        **({} if omit_text else {"text": text})} for i, text in enumerate(values)]
    path = tmp_path / "source.parquet"
    pq.write_table(pa.Table.from_pylist(expected, schema=schema), path,
        compression="snappy", data_page_version="1.0")
    descriptor = {"repository": "fixture/parent", "revision": "a" * 40,
        "path_in_repo": path.name, "local_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size, "row_count": len(expected), "profile": pages.PARENT_PROFILE}
    arguments = reader_inputs(descriptor, expected, list(range(len(expected))))
    rows = pages.read_selected_parent_rows(descriptor, **arguments)
    return descriptor, expected, arguments, rows


def no_authority(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert type(report["training_mask"]) is type(report["evaluation_gold_mask"]) is int
    assert report["training_mask"] == report["evaluation_gold_mask"] == 0
    assert report["inference_view"] is None


@pytest.mark.parametrize("dictionary", [False, True])
def test_sparse_rows_retain_every_full_row_hash_and_physical_identity(tmp_path, dictionary):
    descriptor, expected, arguments, rows = fixture_report(tmp_path, dictionary=dictionary)
    report = prepare(descriptor, rows, arguments)
    assert inventory.selected_parent_source_inventory_sha256(report) == digest(report)
    assert len(report["rows"]) == 6
    assert [row["physical_key"]["parquet_row_index"] for row in report["rows"]] == arguments["row_ordinals"]
    for observed, ordinal in zip(report["rows"], arguments["row_ordinals"], strict=True):
        key = {"repository_id": descriptor["repository"], "revision": descriptor["revision"],
            "path_in_repo": descriptor["path_in_repo"], "artifact_sha256": descriptor["sha256"],
            "artifact_bytes": descriptor["bytes"], "parquet_row_index": ordinal}
        assert observed["physical_key"] == key
        assert observed["physical_section_id"] == "sha256:" + digest(key)
        assert observed["full_raw_row_sha256"] == digest(expected[ordinal])
        assert len(rows["rows"][arguments["row_ordinals"].index(ordinal)]["raw_row"]) == 45
        assert observed["group_id"] is observed["split"] is None
    no_authority(report)
    validate(report, descriptor, rows, arguments)


def test_equal_complete_rows_remain_distinct_physical_occurrences(tmp_path):
    path, descriptor, expected = fixture(tmp_path, rows=3)
    expected[1] = deepcopy(expected[0])
    pq.write_table(pa.Table.from_pylist(expected), path, compression="snappy", data_page_version="1.0")
    descriptor.update(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    arguments = reader_inputs(descriptor, expected, [0, 1])
    rows = pages.read_selected_parent_rows(descriptor, **arguments)
    report = prepare(descriptor, rows, arguments)
    first, second = report["rows"]
    assert first["full_raw_row_sha256"] == second["full_raw_row_sha256"]
    assert first["physical_section_id"] != second["physical_section_id"]
    assert first["physical_key"]["parquet_row_index"] == 0
    assert second["physical_key"]["parquet_row_index"] == 1


@pytest.mark.parametrize("damage", ["descriptor_pin", "row_report_pin", "preflight_pin", "row_hash", "row_order", "missing_pin", "bool_ordinal", "bool_row_count"])
def test_independent_physical_input_commitments_cannot_be_retargeted(tmp_path, damage):
    descriptor, _, arguments, rows = fixture_report(tmp_path, ordinals=[0, 7])
    kwargs = dict(arguments, expected_row_report_sha256=pages.parent_row_report_sha256(rows))
    if damage == "descriptor_pin": kwargs["expected_descriptor_sha256"] = "0" * 64
    elif damage == "row_report_pin": kwargs["expected_row_report_sha256"] = "0" * 64
    elif damage == "preflight_pin": kwargs["expected_preflight_sha256"] = "0" * 64
    elif damage == "row_hash": kwargs["expected_row_sha256s"][0] = "0" * 64
    elif damage == "row_order": kwargs["row_ordinals"] = [7, 0]
    elif damage == "missing_pin": kwargs["expected_row_sha256s"] = kwargs["expected_row_sha256s"][:-1]
    elif damage == "bool_ordinal": kwargs["row_ordinals"] = [False, 7]
    else:
        descriptor["row_count"] = True
        kwargs["expected_descriptor_sha256"] = digest(descriptor)
    with pytest.raises(ValueError):
        inventory.prepare_selected_parent_source_inventory_v1(descriptor, rows, **kwargs)


@pytest.mark.parametrize("mutation", ["append", "same_size_replacement"])
def test_saved_rows_cannot_replace_fresh_original_parent_replay(tmp_path, mutation):
    descriptor, _, arguments, rows = fixture_report(tmp_path, ordinals=[0, 7])
    path = Path(descriptor["local_path"])
    raw = path.read_bytes()
    path.write_bytes(raw + b"x" if mutation == "append" else raw[:8] + bytes([raw[8] ^ 1]) + raw[9:])
    with pytest.raises(ValueError):
        prepare(descriptor, rows, arguments)


def test_resealed_saved_row_report_does_not_bypass_original_row_commitments(tmp_path):
    descriptor, _, arguments, rows = fixture_report(tmp_path, ordinals=[0, 7])
    rows["rows"][0]["raw_row"]["extra_35"] = "source carrier modified after original decode"
    rows["rows"][0]["raw_row_sha256"] = digest(rows["rows"][0]["raw_row"])
    rows["row_report_sha256"] = digest({key: value for key, value in rows.items() if key != "row_report_sha256"})
    with pytest.raises(ValueError):
        prepare(descriptor, rows, arguments)


@pytest.mark.parametrize("mutated", ["caller_original", "delegated_snapshot"])
def test_original_or_delegated_snapshot_mutation_during_real_validation_is_refused(tmp_path, monkeypatch, mutated):
    descriptor, _, arguments, rows = fixture_report(tmp_path, ordinals=[0, 7])
    original = pages.validate_selected_parent_rows
    def mutate_after_genuine_validation(report, parent, **keywords):
        validation = original(report, parent, **keywords)
        target = rows if mutated == "caller_original" else report
        target["rows"][0]["raw_row"]["text"] = "caller changed while physical validation was in progress"
        return validation
    monkeypatch.setattr(pages, "validate_selected_parent_rows", mutate_after_genuine_validation)
    with pytest.raises(ValueError):
        prepare(descriptor, rows, arguments)


def test_cyclic_supplied_report_is_refused_before_any_parent_owner_call(tmp_path, monkeypatch):
    descriptor, _, arguments, rows = fixture_report(tmp_path, ordinals=[0, 7])
    rows["cycle"] = rows
    monkeypatch.setattr(pages, "validate_selected_parent_rows", lambda *args, **kwargs:
        pytest.fail("cyclic input reached the physical parent owner"))
    with pytest.raises(ValueError):
        inventory.prepare_selected_parent_source_inventory_v1(descriptor, rows,
            expected_row_report_sha256="0" * 64, **arguments)


def test_source_inventory_api_excludes_cache_candidates_model_and_partition_inputs():
    signature = inspect.signature(inventory.prepare_selected_parent_source_inventory_v1)
    assert set(signature.parameters) == {"descriptor", "row_report", "expected_descriptor_sha256",
        "expected_row_report_sha256", "preflight_report", "expected_preflight_sha256", "row_ordinals", "expected_row_sha256s"}
    assert not any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values())


@pytest.mark.parametrize("kind", ["missing", "null", "empty", "unsupported"])
def test_missing_empty_and_unsupported_text_keep_the_complete_selected_denominator(tmp_path, kind):
    text = None if kind == "null" else "" if kind == "empty" else 42 if kind == "unsupported" else "ignored"
    descriptor, expected, arguments, rows = small_report(tmp_path, [text],
        omit_text=kind == "missing", text_type=pa.int64() if kind == "unsupported" else pa.string())
    report = prepare(descriptor, rows, arguments)
    assert len(report["rows"]) == report["coverage"]["declared_selected_rows"] == report["coverage"]["replayed_selected_rows"] == 1
    row = report["rows"][0]
    assert row["full_raw_row_sha256"] == digest(expected[0])
    assert row["disposition"] == ("unsupported_text_type" if kind == "unsupported" else "empty_text" if kind == "empty" else "missing_text")
    assert row["text"] == ({"sha256": hashlib.sha256(b"").hexdigest(), "utf8_bytes": 0, "unicode_characters": 0} if kind == "empty" else None)
    assert row["normalized_content_sha256"] == (hashlib.sha256(b"").hexdigest() if kind == "empty" else None)
    no_authority(report)
    no_authority(row)


def test_unicode_lengths_and_normalized_keys_do_not_merge_distinct_physical_text(tmp_path):
    texts = ["  Café\n雪  STRAẞE\t", "café 雪 strasse", " \n\t "]
    descriptor, _, arguments, rows = small_report(tmp_path, texts)
    report = prepare(descriptor, rows, arguments)
    assert len({row["physical_section_id"] for row in report["rows"]}) == 3
    first, second, whitespace = report["rows"]
    assert first["normalized_content_sha256"] == second["normalized_content_sha256"]
    assert first["text"]["sha256"] != second["text"]["sha256"]
    for row, text in zip(report["rows"], texts, strict=True):
        assert row["text"] == {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "utf8_bytes": len(text.encode("utf-8")), "unicode_characters": len(text)}
        assert row["normalized_content_sha256"] == hashlib.sha256(" ".join(text.split()).casefold().encode()).hexdigest()
        assert row["disposition"] == "stored_text_available"
    assert whitespace["normalized_content_sha256"] == hashlib.sha256(b"").hexdigest()


def test_source_only_projection_omits_uninterpreted_raw_extras_and_detaches_inputs(tmp_path):
    descriptor, _, arguments, rows = fixture_report(tmp_path, ordinals=[0, 7])
    report = prepare(descriptor, rows, arguments)
    captured = wire(report)
    assert b"literal:35" not in captured
    assert b"Caf" not in captured
    assert all("raw_row" not in row for row in report["rows"])
    assert all(row["observed_identity"] == {key: rows["rows"][i]["raw_row"][key]
        for key in ("ipfs_cid", "title_number", "section_number")} for i, row in enumerate(report["rows"]))
    descriptor["revision"] = "b" * 40
    rows["rows"][0]["raw_row"]["text"] = "changed caller input"
    arguments["row_ordinals"][0] = 1
    assert wire(report) == captured


@pytest.mark.parametrize("damage", ["source_authority", "row_authority", "partition_group", "partition_split", "training_mask", "bool_mask", "inference_view", "missing_row", "physical_revision", "raw_row_hash", "text_hash"])
def test_rehashed_inventory_cannot_promote_or_retarget_regenerated_source(tmp_path, damage):
    descriptor, _, arguments, rows = fixture_report(tmp_path, ordinals=[0, 7])
    report = prepare(descriptor, rows, arguments)
    if damage == "source_authority": report["authority"][next(iter(report["authority"]))] = True
    elif damage == "row_authority": report["rows"][0]["authority"][next(iter(report["rows"][0]["authority"]))] = True
    elif damage == "partition_group": report["rows"][0]["group_id"] = "sha256:" + "a" * 64
    elif damage == "partition_split": report["rows"][0]["split"] = "train"
    elif damage == "training_mask": report["rows"][0]["training_mask"] = 1
    elif damage == "bool_mask": report["rows"][0]["training_mask"] = False
    elif damage == "inference_view": report["rows"][0]["inference_view"] = "source text admitted without access evidence"
    elif damage == "missing_row": report["rows"].pop()
    elif damage == "physical_revision": report["rows"][0]["physical_key"]["revision"] = "b" * 40
    elif damage == "raw_row_hash": report["rows"][0]["full_raw_row_sha256"] = "0" * 64
    else: report["rows"][0]["text"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        validate(report, descriptor, rows, arguments)


def _real_original(key):
    variable, expected_bytes, expected_sha256 = REAL_ORIGINALS[key]
    path = Path(os.environ[variable])
    assert path.is_absolute() and path.resolve(strict=True) == path
    raw = path.read_bytes()
    assert len(raw) == expected_bytes and hashlib.sha256(raw).hexdigest() == expected_sha256
    return json.loads(raw), {"path": str(path), "bytes": expected_bytes, "sha256": expected_sha256}


def persist(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"
    assert len(raw) <= 4 * 1024**2
    with path.open("xb") as stream:
        stream.write(raw)
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def test_real_thirteen_rows_project_source_only_metadata_from_fresh_parent_replay(tmp_path):
    pins, pins_ref = _real_original("row_pins")
    retained, retained_ref = _real_original("retained_sections")
    descriptor = pins["source_descriptor"]
    assert pins["row_ordinals"] == REAL_ORDINALS
    assert descriptor["revision"] == "5016b86a273ce5e4ffd066c5ae9f5fe494dd417e"
    assert descriptor["sha256"] == "4d26df1e3814279e4b4df3af0e454b4f64fc89a81879db926989862b6ad7d8b8"
    assert descriptor["bytes"] == 374277662 and descriptor["row_count"] == 60077
    assert digest(descriptor) == pins["descriptor_sha256"]
    preflight = pages.preflight_parent_pages(descriptor, expected_descriptor_sha256=pins["descriptor_sha256"])
    arguments = {"expected_descriptor_sha256": pins["descriptor_sha256"],
        "preflight_report": preflight, "expected_preflight_sha256": pages.parent_page_report_sha256(preflight),
        "row_ordinals": REAL_ORDINALS, "expected_row_sha256s": pins["expected_row_sha256s"]}
    rows = pages.read_selected_parent_rows(descriptor, **arguments)
    report = prepare(descriptor, rows, arguments)
    validation = validate(report, descriptor, rows, arguments)
    assert report["schema"] == "legal-parent-selected-source-inventory/v1"
    assert report["profile"] == "historical-parent-selected-source-metadata/v1"
    assert report["scope"] == "declared_physical_selection_only"
    assert report["coverage"] == {"declared_parent_rows": 60077, "declared_selected_rows": 13,
        "replayed_selected_rows": 13, "whole_parent_inventoried": False}
    assert report["content_normalization"] == "unicode-whitespace-casefold-v1"
    assert report["parent_descriptor_sha256"] == pins["descriptor_sha256"]
    assert report["row_report_sha256"] == pages.parent_row_report_sha256(rows)
    assert report["preflight_report_sha256"] == pages.parent_page_report_sha256(preflight)
    assert len(report["rows"]) == 13 and len(pins["all_columns"]) == 45
    for observed, original, section in zip(report["rows"], rows["rows"], retained["source_sections"], strict=True):
        text, raw = section["text"], original["raw_row"]
        assert set(raw) == set(pins["all_columns"])
        assert raw["text"] == text
        assert original["raw_row_sha256"] == observed["full_raw_row_sha256"] == digest(raw)
        assert observed["physical_key"]["parquet_row_index"] == section["parquet_row_index"] == original["row_ordinal"]
        assert observed["physical_section_id"] == "sha256:" + digest(observed["physical_key"])
        assert all(observed["physical_key"][key] == section[key] for key in observed["physical_key"])
        assert observed["text"] == {"sha256": section["text_sha256"],
            "utf8_bytes": len(text.encode()), "unicode_characters": len(text)}
        assert observed["observed_identity"] == {"ipfs_cid": section["entry_cid"],
            "title_number": raw["title_number"], "section_number": raw["section_number"]}
        assert observed["normalized_content_sha256"] == hashlib.sha256(" ".join(text.split()).casefold().encode()).hexdigest()
        assert observed["disposition"] == "stored_text_available"
        assert observed["group_id"] is observed["split"] is None
        no_authority(observed)
    no_authority(report)
    output = tmp_path / "real-parent-inventory"
    output.mkdir()
    refs = {"preflight": persist(output / "preflight-report.json", preflight),
        "selected_rows": persist(output / "selected-rows-report.json", rows),
        "inventory": persist(output / "source-inventory-report.json", report)}
    request = {"source_descriptor": descriptor, "expected_descriptor_sha256": pins["descriptor_sha256"],
        "expected_preflight_sha256": pages.parent_page_report_sha256(preflight),
        "expected_row_report_sha256": pages.parent_row_report_sha256(rows),
        "row_ordinals": REAL_ORDINALS, "expected_row_sha256s": pins["expected_row_sha256s"]}
    request_ref = persist(output / "selected-source-request.json", request)
    evidence = {"schema": "legal-parent-source-inventory-engineering-evidence/v1",
        "originals": {"row_pins": pins_ref, "retained_sections_assertion_only": retained_ref},
        "reports": refs, "request": request_ref,
        "inventory_full_canonical_sha256": inventory.selected_parent_source_inventory_sha256(report),
        "source_descriptor": descriptor, "source_descriptor_sha256": pins["descriptor_sha256"],
        "selected_physical_row_ordinals": REAL_ORDINALS, "selected_physical_rows": 13,
        "original_fields_per_row": 45, "declared_parent_rows": 60077,
        "selected_decoded_bytes": rows["selected_decoded_bytes"], "decoded_page_bytes": rows["decoded_page_bytes"],
        "public_original_bound_validation": validation,
        "all_selected_rows_retained": True, "large_parent_copied": False,
        "retained_source_sections_used_as_construction_inputs": False,
        "cache_candidates_targets_vectors_or_models_used_as_construction_inputs": False,
        "historical_row_reports_used_without_original_replay": False,
        "whole_parent_population_inventoried": False, "real_source_partitions_constructed": False,
        "group_or_split_assignments_inherited": False,
        "original_producer_occurrence_attested": False, "source_authority_authenticated": False,
        "source_semantics_verified": False, "training_qualified": False,
        "training_mask": 0, "evaluation_gold_mask": 0, "inference_view": None,
        "model_executed": False, "training_executed": False, "database_executed": False,
        "prover_or_Lean_executed": False, "convergence_proved": False,
        "scope": "Exactly13 source-only physical selections replayed through existing public parent byte owner. Independently pinned retained source sections supply assertions only. This distinct selected-parent inventory grants no whole-corpus, partition, source-meaning, model, training or Lean authority."}
    persist(tmp_path / EVIDENCE_NAME, evidence)
