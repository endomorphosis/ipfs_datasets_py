"""Genuine coordinate/source-metadata joins over authored, unreviewed inputs.

The real existing source, manifest, payload and coordinate owners run here.
These controls supply no statutory source, entity semantics or graph admission.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_entity_index_intake as entity
from ipfs_datasets_py.logic.autoformal import legal_paired_manifest_inventory_v1 as inventory
from ipfs_datasets_py.logic.autoformal import legal_paired_payload_intake_v1 as payload
from ipfs_datasets_py.logic.autoformal import legal_source_package_intake_v1 as source
from ipfs_datasets_py.logic.autoformal import legal_source_span_entity_join_v1 as join
from ipfs_datasets_py.logic.autoformal import paired_span_census as paired
from tests.unit.logic.autoformal.test_legal_paired_coordinate_intake_v2 import (
    MARKER, build_coordinate_payload,
)
from tests.unit.logic.autoformal.test_legal_source_package_intake_v1 import inputs as source_inputs


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def coordinate_join(tmp_path, request):
    coordinate = build_coordinate_payload(tmp_path, **getattr(request, "param", {}))
    source_request, metadata = source_inputs(advertised=15, readme_mismatch=True)
    source_raw = wire(source_request)
    location = coordinate["request"]
    path = location["manifest_path_in_repo"]
    manifest_raw = (Path(location["repository_root"]) / path).read_bytes()
    selected = {"path_in_repo": path, "bytes": len(manifest_raw), "sha256": sha(manifest_raw),
                "source_coordinate_report_sha256": coordinate["pin"]}
    paired_request = {"schema": inventory.REQUEST_SCHEMA_V2, "repository_id": inventory.REPOSITORY,
        "revision": location["revision"], "selection_scope": inventory.SELECTION_SCOPE,
        "manifests": [selected]}
    info_raw = wire({"partial": False, "dataset_info": {
        "dataset_name": "uscode-autoformal-entity-cache", "config_name": "autoformal_uscode",
        "features": {field: {"_type": "Value",
            "dtype": "bool" if field in entity.BOOLEAN_FIELDS else "string"} for field in entity.FIELDS},
        "splits": {"train": {"num_examples": 1960876}}}})
    request = {"schema": join.REQUEST_SCHEMA_V2, "source_request_sha256": sha(source_raw),
        "paired_inventory_request_sha256": sha(wire(paired_request)),
        "paired_bundles": [{"manifest_path_in_repo": path,
                            "repository_root": str(location["repository_root"])}],
        "legacy_joins": {}, "entity": {
            "repository_id": "justicedao/uscode-autoformal-entity-cache", "revision": "c" * 40,
            "configuration": "autoformal_uscode", "info_sha256": sha(info_raw)}}
    return {"coordinate": coordinate, "request": request, "source_raw": source_raw,
        "metadata": metadata, "paired_request": paired_request, "manifests": {path: manifest_raw},
        "info_raw": info_raw}


def prepare(case):
    raw = wire(case["request"])
    return join.prepare_source_span_entity_join_manifest_v2(raw, case["source_raw"], case["metadata"],
        wire(case["paired_request"]), case["manifests"], case["info_raw"],
        expected_request_sha256=sha(raw))


def validate(case, report, *, expected=None):
    raw = wire(case["request"])
    pin = join.source_span_entity_join_manifest_sha256(report) if expected is None else expected
    return join.validate_source_span_entity_join_manifest_v2(report, raw, case["source_raw"],
        case["metadata"], wire(case["paired_request"]), case["manifests"], case["info_raw"],
        expected_report_sha256=pin, expected_request_sha256=sha(raw))


def set_manifest(case, value):
    """Reseal actual manifest metadata without creating any new table bytes."""
    value = deepcopy(value)
    value.pop("fingerprint", None)
    value.pop("path_in_repo", None)
    fingerprint = sha(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode())
    value["fingerprint"] = fingerprint
    path = f"autoformal/uscode/paired-v3/manifests/{value['agent_id']}/manifest-{fingerprint}.json"
    value["path_in_repo"] = path
    raw = wire(value)
    case["manifests"] = {path: raw}
    selected = case["paired_request"]["manifests"][0]
    selected.update(path_in_repo=path, bytes=len(raw), sha256=sha(raw))
    case["request"]["paired_inventory_request_sha256"] = sha(wire(case["paired_request"]))
    case["request"]["paired_bundles"][0]["manifest_path_in_repo"] = path


def test_real_coordinate_join_replays_complete_report_once_and_original_global_occurrences(coordinate_join):
    case = coordinate_join
    result = prepare(case)
    assert validate(case, result) == result
    assert validate(case, wire(result),
        expected=join.source_span_entity_join_manifest_sha256(result)) == result
    assert result["schema"] == join.SCHEMA_V2
    assert result["span_inventory"]["schema"] == inventory.SCHEMA_V2
    nested = result["paired_bundles"][0]["payload_intake"]
    assert nested["schema"] == payload.SCHEMA_V2
    carrier = nested["source_coordinates"]
    original = next(row for row in case["coordinate"]["bundle"]["artifacts"]
                    if row["kind"] == "source_coordinate_report")
    raw = paired.decode_artifact(original)
    assert carrier["report_raw_utf8"].encode() == raw
    assert carrier["report_sha256"] == case["coordinate"]["pin"]
    assert carrier["report_artifact_sha256"] == sha(raw) != carrier["report_sha256"]
    assert raw.index(b'z_metadata') < raw.index(b'a_metadata')
    assert MARKER not in carrier["report_raw_utf8"]
    assert len(json.loads(carrier["report_raw_utf8"])["spans"]) == 4
    assert json.loads(wire(result))["paired_bundles"][0]["payload_intake"]["source_coordinates"] == carrier
    def carrier_count(value):
        if isinstance(value, dict):
            return ("report_raw_utf8" in value) + sum(carrier_count(v) for v in value.values())
        return sum(carrier_count(v) for v in value) if isinstance(value, list) else 0
    assert carrier_count(result) == 1
    refs = result["row_references"]
    assert [row["source_coordinate_span_index"] for row in refs] == [1, 3]
    assert [row["source_provenance_json"] for row in refs] == case["coordinate"]["references"]
    assert all(row["source_coordinate_report_sha256"] == carrier["report_sha256"] for row in refs)
    assert all("report_raw_utf8" not in row for row in refs)


def test_equal_text_never_collapses_distinct_original_occurrences_or_physical_rows(coordinate_join):
    result = prepare(coordinate_join)
    rows = result["paired_bundles"][0]["payload_intake"]["rows"]
    sources = [json.loads(row["derived_row_json"])["source"] for row in rows]
    assert sources[0]["text"] == sources[1]["text"]
    assert sources[0]["span_id"] != sources[1]["span_id"]
    assert result["counts"]["physical_paired_rows"] == result["counts"]["selected_row_references"] == 2
    assert len({row["physical_identity_sha256"] for row in result["row_references"]}) == 2
    assert [row["physical_identity"]["row_ordinal"] for row in result["row_references"]] == [0, 1]
    assert all(row["selected_occurrence"] is None for row in result["row_references"])
    assert result["counts"]["candidate_occurrence_references"] == 0


def test_source_metadata_entity_schema_and_coordinates_supply_no_semantic_crosswalk(coordinate_join):
    result = prepare(coordinate_join)
    metadata = result["source_metadata_intake"]
    assert metadata["source_identity"]["hub_revision"] == "a" * 40
    assert metadata["source_identity"]["producer_source_revision"] == "b" * 40
    assert metadata["metadata_validation"]["table_bodies_read"] is False
    assert metadata["status"] == "selected_metadata_verified_with_discrepancies"
    assert result["entity_metadata"]["declared_rows"] == 1960876
    assert result["entity_metadata"]["verified_file_rows"] == result["counts"]["entity_file_rows_verified"] == 0
    assert result["paired_bundles"][0]["legacy_candidate_join"] is None
    for row in result["row_references"]:
        assert row["current_source_release_correspondence"] == "unverified_no_independent_crosswalk"
        assert row["entity_binding"] == "unavailable_semantic_companions_not_supplied"
        assert row["source_candidate_record"] is None
        assert row["training_mask"] == row["evaluation_gold_mask"] == 0
        assert type(row["training_mask"]) is type(row["evaluation_gold_mask"]) is int
    assert result["training_mask"] == result["evaluation_gold_mask"] == 0
    assert all(value is False for value in result["authority"].values())


@pytest.mark.parametrize("damage", ["missing", "uppercase", "boolean", "different"])
def test_coordinate_pin_refuses_before_source_or_payload_preparation(coordinate_join, monkeypatch, damage):
    case = coordinate_join
    selected = case["paired_request"]["manifests"][0]
    if damage == "missing": selected.pop("source_coordinate_report_sha256")
    else: selected["source_coordinate_report_sha256"] = {
        "uppercase": "A" * 64, "boolean": True, "different": "0" * 64}[damage]
    case["request"]["paired_inventory_request_sha256"] = sha(wire(case["paired_request"]))
    def unreachable(*args, **kwargs):
        pytest.fail("invalid coordinate pin reached source or payload preparation")
    monkeypatch.setattr(source, "prepare_source_package_intake", unreachable)
    monkeypatch.setattr(payload, "prepare_paired_payload_intake_v2", unreachable)
    with pytest.raises(ValueError): prepare(case)


@pytest.mark.parametrize("count", [0, 2])
def test_coordinate_profile_requires_exactly_one_manifest_before_owners(coordinate_join, monkeypatch, count):
    case = coordinate_join
    case["request"]["paired_bundles"] *= count
    monkeypatch.setattr(join, "_owners", lambda: pytest.fail("invalid bundle count reached owners"))
    with pytest.raises(ValueError): prepare(case)


@pytest.mark.parametrize("count", [0, 65])
def test_coordinate_physical_row_bounds_refuse_before_payload_loading(coordinate_join, monkeypatch, count):
    case = coordinate_join
    manifest = json.loads(next(iter(case["manifests"].values())))
    manifest["tables"]["paired_spans"]["row_count"] = count
    set_manifest(case, manifest)
    monkeypatch.setattr(payload, "prepare_paired_payload_intake_v2",
        lambda *args, **kwargs: pytest.fail("out-of-profile row count reached payload loader"))
    with pytest.raises(ValueError): prepare(case)


def test_legacy_candidate_namespace_cannot_be_mixed_into_coordinate_profile(coordinate_join, monkeypatch):
    case = coordinate_join
    path = case["request"]["paired_bundles"][0]["manifest_path_in_repo"]
    case["request"]["legacy_joins"][path] = "0" * 64
    monkeypatch.setattr(join, "_owners", lambda: pytest.fail("mixed profile reached owners"))
    with pytest.raises(ValueError): prepare(case)


@pytest.mark.parametrize("damage", ["schema", "manifest_pin", "source_pin", "entity_pin"])
def test_nested_input_contracts_are_not_replaced_by_outer_resealing(coordinate_join, damage):
    case = coordinate_join
    if damage == "schema": case["request"]["schema"] = join.REQUEST_SCHEMA
    elif damage == "source_pin": case["request"]["source_request_sha256"] = "0" * 64
    elif damage == "entity_pin": case["request"]["entity"]["info_sha256"] = "0" * 64
    else:
        case["paired_request"]["manifests"][0]["sha256"] = "0" * 64
        case["request"]["paired_inventory_request_sha256"] = sha(wire(case["paired_request"]))
    with pytest.raises(ValueError): prepare(case)


def test_legacy_join_entrypoint_does_not_silently_accept_coordinate_transport(coordinate_join):
    case = coordinate_join
    request = deepcopy(case["request"])
    request["schema"] = join.REQUEST_SCHEMA
    raw = wire(request)
    with pytest.raises(ValueError):
        join.prepare_source_span_entity_join_manifest(raw, case["source_raw"], case["metadata"],
            wire(case["paired_request"]), case["manifests"], case["info_raw"], expected_request_sha256=sha(raw))


@pytest.mark.parametrize("damage", ["index", "reference", "report_pin", "report_text", "omit_row",
    "reorder_rows", "authority", "mask", "crosswalk", "entity_binding"])
def test_rehashed_join_forgery_still_requires_genuine_full_original_replay(coordinate_join, damage):
    result = prepare(coordinate_join)
    assert validate(coordinate_join, result) == result
    row = result["row_references"][0]
    if damage == "index": row["source_coordinate_span_index"] = 0
    elif damage == "reference": row["source_provenance_json"] = result["row_references"][1]["source_provenance_json"]
    elif damage == "report_pin": row["source_coordinate_report_sha256"] = "0" * 64
    elif damage == "report_text":
        result["paired_bundles"][0]["payload_intake"]["source_coordinates"]["report_raw_utf8"] += " "
    elif damage == "omit_row": result["row_references"].pop()
    elif damage == "reorder_rows": result["row_references"].reverse()
    elif damage == "authority": result["authority"]["graph_admitted"] = True
    elif damage == "mask": row["training_mask"] = True
    elif damage == "crosswalk": row["current_source_release_correspondence"] = "verified"
    else: row["entity_binding"] = {"inferred_from_equal_legal_id": True}
    with pytest.raises(ValueError, match="full replay"):
        validate(coordinate_join, result)


def test_wrong_report_pin_refuses_before_delegated_replay(coordinate_join, monkeypatch):
    result = prepare(coordinate_join)
    monkeypatch.setattr(join, "_owners", lambda: pytest.fail("wrong report pin reached owners"))
    with pytest.raises(ValueError): validate(coordinate_join, result, expected="0" * 64)


@pytest.mark.parametrize("table", ["paired_spans", "artifacts"])
def test_changed_retained_tables_invalidate_original_join_without_partial_output(coordinate_join, table):
    case = coordinate_join
    result = prepare(case)
    descriptor = case["coordinate"]["written"][table]
    path = Path(case["coordinate"]["request"]["repository_root"]) / descriptor["path_in_repo"]
    path.write_bytes(path.read_bytes() + b"changed after original join")
    with pytest.raises(ValueError): validate(case, result)


def test_join_output_and_carrier_are_detached_from_inputs(coordinate_join):
    case = coordinate_join
    original = deepcopy(case["coordinate"]["report"])
    result = prepare(case)
    expected_reference = case["coordinate"]["references"][0]
    result["row_references"][0]["source_provenance_json"] = "changed"
    result["paired_bundles"][0]["payload_intake"]["source_coordinates"]["report_raw_utf8"] = "changed"
    assert case["coordinate"]["report"] == original
    fresh = prepare(case)
    assert fresh["row_references"][0]["source_provenance_json"] == expected_reference
    assert json.loads(fresh["paired_bundles"][0]["payload_intake"]["source_coordinates"]["report_raw_utf8"]) == original


def test_late_offered_metadata_mutation_refuses_after_genuine_source_preparation(coordinate_join, monkeypatch):
    case = coordinate_join
    genuine = source.prepare_source_package_intake
    observed = []

    def mutate_after_real_source(*args, **kwargs):
        result = genuine(*args, **kwargs)
        observed.append(result["schema"])
        case["metadata"]["README.md"] += b"late offered mapping mutation"
        return result

    monkeypatch.setattr(source, "prepare_source_package_intake", mutate_after_real_source)
    with pytest.raises(ValueError, match="original coordinate metadata mapping changed"):
        prepare(case)
    assert observed == [source.SCHEMA]


def test_late_table_mutation_refuses_after_genuine_payload_preparation(coordinate_join, monkeypatch):
    case = coordinate_join
    genuine = payload.prepare_paired_payload_intake_v2
    observed = []

    def mutate_after_real_payload(*args, **kwargs):
        result = genuine(*args, **kwargs)
        observed.append(result["schema"])
        entry = case["coordinate"]["written"]["artifacts"]
        path = Path(case["coordinate"]["request"]["repository_root"]) / entry["path_in_repo"]
        path.write_bytes(path.read_bytes() + b"late table mutation")
        return result

    monkeypatch.setattr(payload, "prepare_paired_payload_intake_v2", mutate_after_real_payload)
    with pytest.raises(ValueError, match="complete regular coordinate bundle file"):
        prepare(case)
    assert observed == [payload.SCHEMA_V2]


def test_primary_payload_failure_retains_all_closing_custody_failures(coordinate_join, monkeypatch):
    """Explicit negative fault injection follows a genuine complete payload replay."""
    case = coordinate_join
    genuine_payload = payload.prepare_paired_payload_intake_v2
    genuine_pins = join._coordinate_owner_pins
    pin_calls, payload_calls = [], []
    sentinel = RuntimeError("authored negative payload boundary failure")

    def changed_closing_pin_map(owners):
        pins = genuine_pins(owners)
        pin_calls.append(dict(pins))
        if len(pin_calls) > 1:
            # No source file is changed; only this negative observed result is injected.
            pins = {**pins, "negative-test:closing-source-observation": "0" * 64}
        return pins

    def fail_after_real_payload(*args, **kwargs):
        result = genuine_payload(*args, **kwargs)
        payload_calls.append(result["schema"])
        case["metadata"]["README.md"] += b"negative closing input mutation"
        entry = case["coordinate"]["written"]["artifacts"]
        path = Path(case["coordinate"]["request"]["repository_root"]) / entry["path_in_repo"]
        path.write_bytes(path.read_bytes() + b"negative closing file mutation")
        raise sentinel

    monkeypatch.setattr(join, "_coordinate_owner_pins", changed_closing_pin_map)
    monkeypatch.setattr(payload, "prepare_paired_payload_intake_v2", fail_after_real_payload)
    with pytest.raises(RuntimeError, match="authored negative payload boundary failure") as caught:
        prepare(case)
    assert caught.value is sentinel
    assert payload_calls == [payload.SCHEMA_V2] and len(pin_calls) == 2
    notes = getattr(caught.value, "__notes__", [])
    for label in ("original inputs", "owner sources", "retained files"):
        assert any("secondary coordinate join custody failure (" + label + ")" in note for note in notes)


def test_late_offered_report_mutation_refuses_after_genuine_validator_replay(coordinate_join, monkeypatch):
    case = coordinate_join
    result = prepare(case)
    genuine = payload.prepare_paired_payload_intake_v2
    observed = []

    def mutate_after_real_payload(*args, **kwargs):
        prepared = genuine(*args, **kwargs)
        observed.append(prepared["schema"])
        result["row_references"][0]["training_mask"] = True
        return prepared

    monkeypatch.setattr(payload, "prepare_paired_payload_intake_v2", mutate_after_real_payload)
    with pytest.raises(ValueError, match="offered coordinate join report changed during validation"):
        validate(case, result)
    assert observed == [payload.SCHEMA_V2]
