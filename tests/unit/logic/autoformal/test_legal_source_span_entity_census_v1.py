"""Actual retained join/census custody, plus bounded refusal controls.

The positive fixture uses both original paired bundles and genuine retained
producer receipts. No positive delegate is stubbed. The entity population is
the already-recorded complete v2 census; this suite forbids a fresh entity row
scan. Existing tiny entity-index regressions cover endpoint classification.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.autoformal import legal_entity_index_intake as entity
from ipfs_datasets_py.logic.autoformal import legal_source_span_entity_join_v1 as join
from ipfs_datasets_py.logic.autoformal import legal_source_span_entity_census_v1 as subject


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def reference(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def read(ref):
    assert reference(ref["path"]) == {key: ref[key] for key in ("path", "bytes", "sha256")}
    return Path(ref["path"]).read_bytes()


def save(directory, name, value):
    path = directory / name
    with path.open("xb") as stream:
        stream.write(wire(value) + b"\n")
    return reference(path)


def prepare(case, *, request=None, joined=None, census_raw=None, originals=None, entity_path=None):
    raw = wire(case.request if request is None else request)
    return subject.prepare_source_span_entity_census_v1(
        raw, case.joined if joined is None else joined,
        case.census_raw if census_raw is None else census_raw,
        case.entity_path if entity_path is None else entity_path,
        expected_request_sha256=sha(raw),
        join_originals=case.originals if originals is None else originals)


def validate(case, report, *, expected=None):
    return subject.validate_source_span_entity_census_v1(
        report, wire(case.request), case.joined, case.census_raw, case.entity_path,
        expected_report_sha256=case.report_sha256 if expected is None else expected,
        expected_request_sha256=sha(wire(case.request)), join_originals=case.originals)


@pytest.fixture(scope="module")
def retained(tmp_path_factory):
    packet_path = Path(os.environ["LEGAL_SOURCE_SPAN_ENTITY_CENSUS_FIXTURE"])
    packet_raw = packet_path.read_bytes()
    assert sha(packet_raw) == os.environ["LEGAL_SOURCE_SPAN_ENTITY_CENSUS_FIXTURE_SHA256"]
    packet = json.loads(packet_raw)
    assert packet["schema"] == "legal-source-span-entity-census-fixture/v1"
    external = [*packet["pin_files"], *packet["large_files"]]
    for descriptor in external:
        assert reference(descriptor["path"]) == descriptor
    refs = packet["refs"]
    inputs = json.loads(read(refs["join_frozen_inputs"]))
    joined_raw = read(refs["join_report"])
    joined = json.loads(joined_raw)
    compatibility = json.loads(read(refs["compatibility"]))
    census_raw = read(refs["census"])
    census = json.loads(census_raw)
    custody = json.loads(read(refs["entity_custody"]))
    execution = json.loads(read(refs["entity_execution"]))
    prior_comparison = json.loads(read(refs["entity_comparison"]))
    selected = compatibility["entity_cache"]
    assert selected["census"]["sha256"] == refs["census"]["sha256"]
    assert selected["artifact"]["sha256"] == refs["entity_file"]["sha256"]
    assert selected["canonical_census_sha256"] == packet["expected"]["prior_census_sha256"]
    assert compatibility["validation"]["receipt"]["sha256"] == refs["entity_execution"]["sha256"]
    assert execution["resource_owner_admitted"] is True and execution["lease_released"] is True
    assert custody["source_path"] == refs["entity_file"]["path"]
    assert custody["sha256"] == selected["artifact"]["sha256"]
    assert prior_comparison["new_census_sha256"] == selected["canonical_census_sha256"]
    legacy_config = json.loads(read(inputs["legacy_inputs"]))
    legacy = {}
    for path, entry in legacy_config.items():
        legacy[path] = {key: entry[key] for key in (
            "expected_population", "expected_producer_receipt_sha256", "source_sections", "expected_source_sections")}
        legacy[path]["producer_receipt_bytes"] = read(entry["producer_receipt"])
    originals = {
        "request_raw": read(inputs["join_request"]),
        "source_request_raw": read(inputs["source_request"]),
        "source_metadata_bytes": {name: read(ref) for name, ref in inputs["source_metadata"].items()},
        "paired_inventory_request_raw": read(inputs["paired_request"]),
        "paired_manifest_bytes": {ref["path_in_repo"]: read(ref) for ref in inputs["paired_manifests"]},
        "entity_info_raw": read(inputs["entity_info"]),
        "expected_request_sha256": inputs["join_request"]["sha256"],
        "legacy_join_inputs": legacy,
    }
    request = {"schema": subject.REQUEST_SCHEMA,
        "join_report_sha256": join.source_span_entity_join_manifest_sha256(joined),
        "census_raw_sha256": selected["census"]["sha256"],
        "census_sha256": selected["canonical_census_sha256"],
        "entity": {"repository_id": selected["repository"], "revision": selected["revision"],
                   "configuration": "autoformal_uscode", "file_sha256": selected["artifact"]["sha256"],
                   "file_bytes": selected["artifact"]["bytes"], "rows": selected["physical_rows"]},
        "census_limits": deepcopy(census["limits"])}
    case = SimpleNamespace(packet=packet, refs=refs, originals=originals, joined=joined,
        census=census, census_raw=census_raw, request=request, entity_path=Path(custody["source_path"]))
    directory = tmp_path_factory.getbasetemp() / "source-span-entity-census-v1"
    directory.mkdir()
    observed = {"public_join_replays": 0, "public_entity_binding_checks": 0,
                "fresh_entity_row_scans": 0, "model_calls": 0, "encoder_calls": 0,
                "optimizer_steps": 0, "entity_binding_arguments": []}
    public_join = join.validate_source_span_entity_join_manifest
    public_bindings = entity.validate_census_bindings

    def join_replay(*args, **kwargs):
        observed["public_join_replays"] += 1
        return public_join(*args, **kwargs)

    def bindings(report, path, **kwargs):
        observed["public_entity_binding_checks"] += 1
        observed["entity_binding_arguments"].append({"path": str(path), **kwargs})
        return public_bindings(report, path, **kwargs)

    def no_scan(*args, **kwargs):
        observed["fresh_entity_row_scans"] += 1
        pytest.fail("This companion must verify prior census custody without an entity row scan")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(join, "validate_source_span_entity_join_manifest", join_replay)
        patch.setattr(entity, "validate_census_bindings", bindings)
        patch.setattr(entity, "census_parquet", no_scan)
        patch.setattr(entity, "validate_census", no_scan)
        patch.setattr(entity, "iter_observed_rows", no_scan)
        case.report = prepare(case)
        case.report_sha256 = subject.source_span_entity_census_sha256(case.report)
        # The public validator also accepts serialized output and original join bytes.
        validated = subject.validate_source_span_entity_census_v1(wire(case.report), wire(request),
            joined_raw, census_raw, case.entity_path, expected_report_sha256=case.report_sha256,
            expected_request_sha256=sha(wire(request)), join_originals=originals)
        assert validated == case.report
        assert observed["public_join_replays"] == observed["public_entity_binding_checks"] == 2
        assert observed["fresh_entity_row_scans"] == 0
        assert wire(case.report["join_report"]) == wire(joined)
        main_observed = deepcopy(observed)
        artifacts = {
            "positive-report.json": save(directory, "positive-report.json", case.report),
            "validation.json": save(directory, "validation.json", validated),
            "source-custody.json": save(directory, "source-custody.json", {
                "packet": reference(packet_path), "refs": refs,
                "independent_prior_census_pin_origin": refs["compatibility"],
                "legacy_join_canonical_equal": True,
                "prior_native_execution_admitted": execution["resource_owner_admitted"],
                "prior_native_lease_released": execution["lease_released"],
                "prior_native_status_is_saved_evidence_not_live_observation": True}),
            "observed-calls.json": save(directory, "observed-calls.json", {
                "scope": "actual_positive_prepare_and_outer_validation_only", **main_observed}),
            "scope.json": save(directory, "scope.json", {
                "actual_retained_paired_rows": 16, "actual_retained_candidate_occurrences": 150,
                "prior_entity_census_rows": 1960876, "fresh_entity_rows_decoded": 0,
                "positive_delegates_stubbed": False, "model_calls": 0, "encoder_calls": 0,
                "optimizer_steps": 0, "network_calls": 0, "new_training": False,
                "semantic_admission": False, "training_mask": 0, "evaluation_gold_mask": 0})}
        manifest = {"schema": "legal-source-span-entity-census-fixture-evidence/v1", "artifacts": artifacts}
        case.manifest_ref = save(directory, "fixture-manifest.json", manifest)
        case.observed = observed
        yield case
        for descriptor in external:
            assert reference(descriptor["path"]) == descriptor
        assert observed["fresh_entity_row_scans"] == 0


def test_real_originals_and_independent_prior_census_replay(retained, record_property):
    record_property("source_span_entity_census_fixture_manifest", json.dumps(retained.manifest_ref, sort_keys=True))
    report = retained.report
    assert report["schema"] == "legal-source-span-entity-census/v1"
    assert report["census_binding_validation"]["status"] == "pinned_prior_census_custody_verified"
    assert report["census_binding_validation"]["fresh_row_replay_performed"] is False
    assert report["evidence"]["source_span_join_replayed"] is True
    assert report["evidence"]["fresh_entity_file_and_footer_verified"] is True
    assert report["evidence"]["fresh_entity_row_replay_performed"] is False
    assert report["evidence"]["verification_order"] == ["entity_prior_census_binding", "source_span_join_replay"]
    assert report["evidence"]["atomic_multi_file_snapshot_verified"] is False


def test_distinct_populations_do_not_promote_the_legacy_join(retained):
    report = retained.report
    assert report["counts"] == {"selected_paired_row_references": 16,
        "selected_physical_paired_rows": 16, "prior_entity_census_rows": 1960876,
        "fresh_entity_rows_decoded": 0, "entity_semantic_bindings": None}
    old = report["join_report"]
    assert old == retained.joined
    assert old["counts"]["entity_file_rows_verified"] == old["entity_metadata"]["verified_file_rows"] == 0
    assert old["counts"]["source_dispositions"] == {"unique_exact_candidate": 11, "ambiguous_exact_candidates": 5}
    assert old["counts"]["candidate_occurrence_references"] == 150
    assert len({row["physical_identity_sha256"] for row in report["row_references"]}) == 16
    assert [row["reference_ordinal"] for row in report["row_references"]] == list(range(16))
    for new, prior in zip(report["row_references"], old["row_references"]):
        assert new["physical_identity_sha256"] == prior["physical_identity_sha256"]
        assert new["row_sha256"] == prior["row_sha256"]
        assert new["entity_semantic_binding"] is None and prior["selected_occurrence"] is None
        assert new["reason"] == "semantic_companions_not_supplied"
        assert type(new["training_mask"]) is type(new["evaluation_gold_mask"]) is int
        assert new["training_mask"] == new["evaluation_gold_mask"] == 0


def test_endpoint_defects_remain_complete_recorded_observations(retained):
    census = retained.report["census"]["report"]
    detail = census["endpoint_integrity"]
    assert census == retained.census
    assert census["rows"] == sum(census["disposition_counts"].values()) == 1960876
    assert detail["edge_rows"] == detail["missing_endpoint_values"]["both"] == 1722395
    assert detail["exclusive_edge_dispositions"] == {"missing_endpoint_value": 1722395,
        "nonempty_dangling_endpoint": 0, "ambiguous_declared_endpoint": 0, "unique_declared_endpoints": 0}
    assert census["disposition_counts"]["node_observation_missing_identity"] == 119134
    assert census["source"]["raw_row_file_byte_mapping_verified"] is False
    assert all(value is False for value in retained.report["authority"].values())
    assert all(value is False for value in census["authority"].values())


def test_exact_census_bytes_and_original_request_are_retained(retained):
    report = retained.report
    assert report["census"]["raw_utf8"].encode("utf-8") == retained.census_raw
    assert report["census"]["raw_sha256"] == retained.refs["census"]["sha256"]
    assert report["census"]["census_sha256"] == retained.packet["expected"]["prior_census_sha256"]
    assert report["census"]["raw_sha256"] != report["census"]["census_sha256"]
    assert report["request_raw_utf8"].encode("utf-8") == wire(retained.request)
    assert report["entity_file"]["path"] == str(retained.entity_path)


def test_returned_report_is_detached_from_original_objects(retained):
    report = retained.report
    before = subject.source_span_entity_census_sha256(report)
    saved_count = report["join_report"]["counts"]["entity_file_rows_verified"]
    saved_revision = report["request"]["entity"]["revision"]
    saved_rows = report["census"]["report"]["rows"]
    try:
        report["join_report"]["counts"]["entity_file_rows_verified"] = -1
        report["request"]["entity"]["revision"] = "0" * 40
        report["census"]["report"]["rows"] = -1
        assert retained.joined["counts"]["entity_file_rows_verified"] == 0
        assert retained.request["entity"]["revision"] == retained.packet["expected"]["entity_revision"]
        assert retained.census["rows"] == 1960876
    finally:
        report["join_report"]["counts"]["entity_file_rows_verified"] = saved_count
        report["request"]["entity"]["revision"] = saved_revision
        report["census"]["report"]["rows"] = saved_rows
    assert subject.source_span_entity_census_sha256(report) == before


@pytest.mark.parametrize("damage", ["schema", "extra", "missing", "raw_pin", "canonical_pin",
    "join_pin", "revision", "row_count", "file_size", "file_hash", "configuration", "limit", "boolean_count"])
def test_request_and_population_mismatches_refuse_before_owners(retained, monkeypatch, damage):
    request = deepcopy(retained.request)
    if damage == "schema": request["schema"] += "-unknown"
    elif damage == "extra": request["forged_admission"] = True
    elif damage == "missing": request.pop("census_limits")
    elif damage == "raw_pin": request["census_raw_sha256"] = "0" * 64
    elif damage == "canonical_pin": request["census_sha256"] = "0" * 64
    elif damage == "join_pin": request["join_report_sha256"] = "0" * 64
    elif damage == "revision": request["entity"]["revision"] = "0" * 40
    elif damage == "row_count": request["entity"]["rows"] = 16
    elif damage == "file_size": request["entity"]["file_bytes"] -= 1
    elif damage == "file_hash": request["entity"]["file_sha256"] = "0" * 64
    elif damage == "configuration": request["entity"]["configuration"] = "unrelated"
    elif damage == "limit": request["census_limits"]["batch_size"] = 1
    elif damage == "boolean_count": request["entity"]["rows"] = True
    monkeypatch.setattr(subject, "_owners", lambda: pytest.fail("owner loaded before request refusal"))
    with pytest.raises(ValueError):
        prepare(retained, request=request)


@pytest.mark.parametrize("damage", ["authority", "partial", "missing_endpoint_details", "bad_endpoint_sum", "v1"])
def test_resealed_census_cannot_bypass_public_owner_contract(retained, damage):
    census = deepcopy(retained.census)
    if damage == "authority": census["authority"]["admitted"] = True
    elif damage == "partial": census["population_complete"] = False
    elif damage == "missing_endpoint_details": census.pop("endpoint_integrity")
    elif damage == "bad_endpoint_sum": census["endpoint_integrity"]["exclusive_edge_dispositions"]["unique_declared_endpoints"] = 1
    elif damage == "v1": census = json.loads(read(retained.refs["legacy_v1_census"]))
    census["census_sha256"] = sha(wire({key: value for key, value in census.items() if key != "census_sha256"}))
    raw = wire(census)
    request = deepcopy(retained.request)
    request["census_raw_sha256"], request["census_sha256"] = sha(raw), census["census_sha256"]
    with pytest.raises(ValueError):
        prepare(retained, request=request, census_raw=raw)


@pytest.mark.parametrize("damage", ["missing_argument", "source_request", "entity_info", "source_metadata", "receipt"])
def test_original_inputs_cannot_be_omitted_or_replaced(retained, damage):
    original = deepcopy(retained.originals)
    if damage == "missing_argument": original.pop("legacy_join_inputs")
    elif damage == "source_request": original["source_request_raw"] += b"\n"
    elif damage == "entity_info": original["entity_info_raw"] += b"\n"
    elif damage == "source_metadata": original["source_metadata_bytes"]["README.md"] += b"\n"
    elif damage == "receipt":
        first = next(iter(original["legacy_join_inputs"].values()))
        first["producer_receipt_bytes"] += b"\n"
    with pytest.raises(ValueError):
        prepare(retained, originals=original)


def mutate_output(report, damage):
    if damage == "authority": report["authority"]["admitted"] = True
    elif damage == "prior_rows": report["counts"]["prior_entity_census_rows"] = 16
    elif damage == "legacy_rows": report["join_report"]["counts"]["entity_file_rows_verified"] = 1960876
    elif damage == "omitted": report["row_references"].pop()
    elif damage == "reordered": report["row_references"].reverse()
    elif damage == "merged": report["row_references"][-1] = deepcopy(report["row_references"][0])
    elif damage == "binding": report["row_references"][0]["entity_semantic_binding"] = {"invented": "officer"}
    elif damage == "fresh_replay": report["evidence"]["fresh_entity_row_replay_performed"] = True


@pytest.mark.parametrize("damage", ["authority", "prior_rows", "legacy_rows", "omitted", "reordered", "merged", "binding", "fresh_replay"])
def test_output_mutations_fail_independent_report_pin_before_replay(retained, monkeypatch, damage):
    changed = deepcopy(retained.report)
    mutate_output(changed, damage)
    monkeypatch.setattr(subject, "prepare_source_span_entity_census_v1",
                        lambda *args, **kwargs: pytest.fail("replay started before stale output pin refusal"))
    with pytest.raises(ValueError):
        validate(retained, changed)


@pytest.mark.parametrize("damage_group", ["physical_population", "semantic_and_execution_claims"])
def test_resealed_output_forgery_is_rejected_by_actual_original_replay(retained, damage_group):
    changed = deepcopy(retained.report)
    if damage_group == "physical_population":
        mutate_output(changed, "omitted")
        mutate_output(changed, "reordered")
        mutate_output(changed, "merged")
    else:
        for damage in ("authority", "legacy_rows", "binding", "fresh_replay"):
            mutate_output(changed, damage)
    with pytest.raises(ValueError, match="differs from full original-input replay"):
        validate(retained, changed, expected=subject.source_span_entity_census_sha256(changed))


def test_stale_request_bytes_refuse_without_loading_owners(retained, monkeypatch):
    monkeypatch.setattr(subject, "_owners", lambda: pytest.fail("owner loaded for stale request"))
    with pytest.raises(ValueError):
        subject.prepare_source_span_entity_census_v1(wire(retained.request) + b"\n", retained.joined,
            retained.census_raw, retained.entity_path, expected_request_sha256=sha(wire(retained.request)),
            join_originals=retained.originals)


def test_original_aggregate_byte_bound_is_checked_before_owners(retained, monkeypatch):
    monkeypatch.setattr(subject, "MAX_ORIGINAL_BYTES", 1024)
    monkeypatch.setattr(subject, "_owners", lambda: pytest.fail("owner loaded before original byte bound"))
    with pytest.raises(ValueError, match="aggregate original"):
        prepare(retained)


def test_validator_output_bound_refuses_before_replay(retained, monkeypatch):
    monkeypatch.setattr(subject, "MAX_REPORT_BYTES", 1024)
    monkeypatch.setattr(subject, "prepare_source_span_entity_census_v1",
                        lambda *args, **kwargs: pytest.fail("replay started before output byte bound"))
    with pytest.raises(ValueError):
        validate(retained, retained.report)


def test_alternate_entity_path_cannot_rewrite_prior_custody(retained, tmp_path, monkeypatch):
    # No file copy or symlink is needed: a changed path alone must be refused.
    monkeypatch.setattr(subject, "_owners", lambda: pytest.fail("owner loaded before path refusal"))
    with pytest.raises(ValueError):
        prepare(retained, entity_path=tmp_path / "foreign.parquet")


def test_negative_delegate_failure_preserves_primary_and_checks_all_closing_custody(retained, monkeypatch):
    """A deliberately failing delegate tests error fences, not positive evidence."""
    original = deepcopy(retained.originals)
    offered_join = deepcopy(retained.joined)
    primary = RuntimeError("deliberate negative delegate failure")
    real_owners = subject._owners
    calls = []

    def owners():
        calls.append("owners")
        return real_owners()

    def fail_binding(*args, **kwargs):
        original["source_metadata_bytes"]["README.md"] += b"\n"
        offered_join["counts"]["entity_file_rows_verified"] = -1
        raise primary

    monkeypatch.setattr(subject, "_owners", owners)
    monkeypatch.setattr(entity, "validate_census_bindings", fail_binding)
    with pytest.raises(RuntimeError) as captured:
        prepare(retained, originals=original, joined=offered_join)
    assert captured.value is primary
    notes = getattr(captured.value, "__notes__", [])
    assert any("original join arguments" in note for note in notes)
    assert any("offered join report" in note for note in notes)
    assert calls == ["owners", "owners"]  # Closing producer check still runs after both earlier failures.


def test_negative_outer_failure_preserves_primary_and_offered_report_note(retained, monkeypatch):
    """A deliberately failed prepare call cannot hide concurrent output mutation."""
    offered = deepcopy(retained.report)
    primary = RuntimeError("deliberate negative outer failure")

    def fail_prepare(*args, **kwargs):
        offered["authority"]["admitted"] = True
        raise primary

    monkeypatch.setattr(subject, "prepare_source_span_entity_census_v1", fail_prepare)
    with pytest.raises(RuntimeError) as captured:
        validate(retained, offered)
    assert captured.value is primary
    assert any("offered companion report" in note for note in getattr(primary, "__notes__", []))


# Coordinate coverage uses one tiny genuine detailed census, not the retained
# 1,960,876-row fixture above. A guard forbids new row scans during each
# companion operation; separate small entity-owner regressions keep their scope.
from tests.unit.logic.autoformal.test_legal_entity_index_intake import (
    rows as coordinate_entity_rows, write as write_coordinate_entity,
)
from tests.unit.logic.autoformal.test_legal_source_span_entity_coordinate_join_v2 import (
    coordinate_join as coordinate_join_fixture, prepare as prepare_coordinate_join,
)


@pytest.fixture(scope="module")
def coordinate_prior_census(tmp_path_factory):
    directory = tmp_path_factory.mktemp("coordinate-prior-entity-census", numbered=False)
    path = directory / "sixteen-authored-entities.parquet"
    inputs = write_coordinate_entity(path, coordinate_entity_rows())
    inputs["revision"] = "c" * 40
    census = entity.census_parquet(path, endpoint_details=True, **inputs)
    assert census["rows"] == sum(census["disposition_counts"].values()) == 16
    assert census["schema"] == "legal-materialized-entity-index-census/v2"
    original = path.read_bytes()
    yield {"path": path, "census": census, "raw": wire(census) + b"\n", "bytes": original}
    assert path.read_bytes() == original


@pytest.fixture
def coordinate_census(coordinate_prior_census, tmp_path, monkeypatch):
    prior = coordinate_prior_census
    calls = {"bindings": [], "joins": [], "forbidden_scans": 0}

    def no_scan(*args, **kwargs):
        calls["forbidden_scans"] += 1
        pytest.fail("coordinate companion decoded entity rows instead of checking prior custody")

    for name in ("census_parquet", "validate_census", "iter_observed_rows", "_rows"):
        monkeypatch.setattr(entity, name, no_scan)
    source = coordinate_join_fixture.__wrapped__(tmp_path, SimpleNamespace(param={}))
    info = json.loads(source["info_raw"])
    info["dataset_info"]["splits"]["train"]["num_examples"] = 16
    source["info_raw"] = wire(info)
    source["request"]["entity"]["info_sha256"] = sha(source["info_raw"])
    joined = prepare_coordinate_join(source)
    original_request = wire(source["request"])
    originals = {"request_raw": original_request, "source_request_raw": source["source_raw"],
        "source_metadata_bytes": source["metadata"],
        "paired_inventory_request_raw": wire(source["paired_request"]),
        "paired_manifest_bytes": source["manifests"], "entity_info_raw": source["info_raw"],
        "expected_request_sha256": sha(original_request), "legacy_join_inputs": None}
    census = deepcopy(prior["census"])
    request = {"schema": subject.REQUEST_SCHEMA_V2,
        "join_report_sha256": join.source_span_entity_join_manifest_sha256(joined),
        "census_raw_sha256": sha(prior["raw"]), "census_sha256": census["census_sha256"],
        "join_originals_sha256": subject.source_span_entity_census_join_originals_sha256(originals),
        "source_coordinate_report_sha256": source["coordinate"]["pin"],
        "entity": {"repository_id": "justicedao/uscode-autoformal-entity-cache", "revision": "c" * 40,
            "configuration": "autoformal_uscode", "file_sha256": sha(prior["bytes"]),
            "file_bytes": len(prior["bytes"]), "rows": 16},
        "census_limits": deepcopy(census["limits"])}
    genuine_binding, genuine_join = entity.validate_census_bindings, join.validate_source_span_entity_join_manifest_v2

    def bindings(*args, **kwargs):
        entry = {"endpoint_details": kwargs.get("endpoint_details"), "passed": False}
        calls["bindings"].append(entry)
        result = genuine_binding(*args, **kwargs)
        entry["passed"] = True
        return result

    def replay(*args, **kwargs):
        entry = {"passed": False}
        calls["joins"].append(entry)
        result = genuine_join(*args, **kwargs)
        entry["passed"] = True
        return result

    monkeypatch.setattr(entity, "validate_census_bindings", bindings)
    monkeypatch.setattr(join, "validate_source_span_entity_join_manifest_v2", replay)
    case = SimpleNamespace(source=source, joined=joined, originals=originals, census=census,
        census_raw=prior["raw"], entity_path=prior["path"], entity_bytes=prior["bytes"],
        request=request, calls=calls)
    yield case
    assert calls["forbidden_scans"] == 0
    assert case.entity_path.read_bytes() == case.entity_bytes


def prepare_coordinate_census(case, *, request=None, joined=None, census_raw=None, originals=None,
                             entity_path=None):
    raw = wire(case.request if request is None else request)
    return subject.prepare_source_span_entity_census_v2(raw,
        case.joined if joined is None else joined, case.census_raw if census_raw is None else census_raw,
        case.entity_path if entity_path is None else entity_path, expected_request_sha256=sha(raw),
        join_originals=case.originals if originals is None else originals)


def validate_coordinate_census(case, report):
    offered = json.loads(report) if type(report) is bytes else report
    request = wire(case.request)
    return subject.validate_source_span_entity_census_v2(report, request, case.joined,
        case.census_raw, case.entity_path, expected_request_sha256=sha(request),
        expected_report_sha256=subject.source_span_entity_census_sha256(offered),
        join_originals=case.originals)


def assert_coordinate_census_unqualified(report):
    assert all(type(value) is bool and value is False for value in report["authority"].values())
    for row in [report, *report["row_references"]]:
        assert type(row["training_mask"]) is type(row["evaluation_gold_mask"]) is int
        assert row["training_mask"] == row["evaluation_gold_mask"] == 0
    assert all(row["entity_semantic_binding"] is None for row in report["row_references"])
    assert report["counts"]["fresh_entity_rows_decoded"] == 0
    assert report["counts"]["entity_semantic_bindings"] is None
    assert report["evidence"]["atomic_multi_file_snapshot_verified"] is False
    assert report["evidence"]["fresh_entity_row_replay_performed"] is False


@pytest.mark.parametrize("transport", ["object", "bytes"], ids=["object", "bytes"])
def test_coordinate_census_genuine_binding_and_original_join_replay_without_rescan(coordinate_census, transport):
    case = coordinate_census
    original_join, original_inputs = wire(case.joined), deepcopy(case.originals)
    report = prepare_coordinate_census(case)
    offered = wire(report) if transport == "bytes" else report
    assert validate_coordinate_census(case, offered) == report
    assert len(case.calls["bindings"]) == 4 and len(case.calls["joins"]) == 2
    assert all(row == {"endpoint_details": True, "passed": True} for row in case.calls["bindings"])
    assert all(row["passed"] for row in case.calls["joins"])
    assert report["schema"] == subject.SCHEMA_V2
    assert report["join_report"] == case.joined and wire(report["join_report"]) == original_join
    assert case.originals == original_inputs
    assert report["census"]["raw_utf8"].encode() == case.census_raw
    assert report["census"]["report"] == case.census
    assert report["census_binding_validation"]["status"] == "pinned_prior_census_custody_verified"
    assert report["counts"]["prior_entity_census_rows"] == 16
    assert report["counts"]["selected_physical_paired_rows"] == 2
    assert report["counts"]["selected_paired_row_references"] == 2
    assert report["join_report"]["entity_metadata"]["verified_file_rows"] == 0
    assert report["join_report"]["entity_metadata"]["declared_rows"] == 16
    detail = report["census"]["report"]["endpoint_integrity"]
    assert detail["edge_rows"] == 6
    assert detail["exclusive_edge_dispositions"] == {"missing_endpoint_value": 2,
        "nonempty_dangling_endpoint": 1, "ambiguous_declared_endpoint": 2, "unique_declared_endpoints": 1}
    carrier = report["join_report"]["paired_bundles"][0]["payload_intake"]["source_coordinates"]
    assert carrier == case.joined["paired_bundles"][0]["payload_intake"]["source_coordinates"]
    assert len(json.loads(carrier["report_raw_utf8"])["spans"]) == 4
    assert [row["reference_ordinal"] for row in report["row_references"]] == [0, 1]
    assert [row["source_coordinate_span_index"] for row in report["row_references"]] == [1, 3]
    assert [row["physical_identity_sha256"] for row in report["row_references"]] == [
        row["physical_identity_sha256"] for row in case.joined["row_references"]]
    for fresh, old in zip(report["row_references"], case.joined["row_references"], strict=True):
        for key in ("source_provenance_json", "source_coordinate_report_sha256", "source_coordinate_span_index"):
            assert fresh[key] == old[key]
        assert "report_raw_utf8" not in fresh and fresh["reason"] == "semantic_companions_not_supplied"
    assert wire(report).count(wire(carrier["report_raw_utf8"])) == 1
    assert_coordinate_census_unqualified(report)


@pytest.mark.parametrize("damage", ["missing", "join-pin", "originals-pin", "coordinate-pin", "boolean-rows",
    "row-count", "file-bytes", "limits"], ids=["missing", "join-pin", "originals-pin", "coordinate-pin",
    "boolean-rows", "row-count", "file-bytes", "limits"])
def test_coordinate_census_independent_request_and_lineage_refusals(coordinate_census, damage):
    case = coordinate_census
    request = deepcopy(case.request)
    if damage == "missing": request.pop("join_originals_sha256")
    elif damage == "join-pin": request["join_report_sha256"] = "0" * 64
    elif damage == "originals-pin": request["join_originals_sha256"] = "0" * 64
    elif damage == "coordinate-pin": request["source_coordinate_report_sha256"] = "0" * 64
    elif damage == "boolean-rows": request["entity"]["rows"] = True
    elif damage == "row-count": request["entity"]["rows"] -= 1
    elif damage == "file-bytes": request["entity"]["file_bytes"] -= 1
    else: request["census_limits"]["batch_size"] += 1
    with pytest.raises(ValueError): prepare_coordinate_census(case, request=request)


@pytest.mark.parametrize("damage", ["index", "order", "carrier", "mask", "entity-binding"],
    ids=["index", "order", "carrier", "mask", "entity-binding"])
def test_coordinate_census_resealed_join_requires_genuine_original_replay(coordinate_census, damage):
    case = coordinate_census
    joined, request = deepcopy(case.joined), deepcopy(case.request)
    if damage == "index": joined["row_references"][0]["source_coordinate_span_index"] = 0
    elif damage == "order": joined["row_references"].reverse()
    elif damage == "carrier": joined["paired_bundles"][0]["payload_intake"]["source_coordinates"]["report_raw_utf8"] += " "
    elif damage == "mask": joined["row_references"][0]["training_mask"] = True
    else: joined["row_references"][0]["entity_binding"] = "forged_semantic_binding"
    request["join_report_sha256"] = join.source_span_entity_join_manifest_sha256(joined)
    with pytest.raises(ValueError): prepare_coordinate_census(case, request=request, joined=joined)


@pytest.mark.parametrize("damage", ["v1", "authority", "partial", "endpoint-sum", "source-path"],
    ids=["v1", "authority", "partial", "endpoint-sum", "source-path"])
def test_coordinate_census_resealed_prior_census_still_obeys_entity_owner(coordinate_census, damage):
    case = coordinate_census
    census, request = deepcopy(case.census), deepcopy(case.request)
    if damage == "v1":
        census["schema"] = "legal-materialized-entity-index-census/v1"
        census.pop("endpoint_integrity")
    elif damage == "authority": census["authority"]["admitted"] = True
    elif damage == "partial": census["population_complete"] = False
    elif damage == "endpoint-sum": census["endpoint_integrity"]["exclusive_edge_dispositions"]["unique_declared_endpoints"] += 1
    else: census["source"]["path"] += ".forged"
    census["census_sha256"] = sha(wire({key: value for key, value in census.items() if key != "census_sha256"}))
    raw = wire(census)
    request.update(census_raw_sha256=sha(raw), census_sha256=census["census_sha256"])
    with pytest.raises(ValueError): prepare_coordinate_census(case, request=request, census_raw=raw)


@pytest.mark.parametrize("profile", ["v1-entrypoint", "v1-join"], ids=["v1-entrypoint", "v1-join"])
def test_coordinate_census_version_domains_do_not_alias(coordinate_census, profile):
    case = coordinate_census
    request = deepcopy(case.request)
    if profile == "v1-entrypoint":
        request["schema"] = subject.REQUEST_SCHEMA
        request.pop("join_originals_sha256"); request.pop("source_coordinate_report_sha256")
        raw = wire(request)
        with pytest.raises(ValueError):
            subject.prepare_source_span_entity_census_v1(raw, case.joined, case.census_raw,
                case.entity_path, expected_request_sha256=sha(raw), join_originals=case.originals)
    else:
        joined = deepcopy(case.joined)
        joined["schema"] = join.SCHEMA
        request["join_report_sha256"] = join.source_span_entity_join_manifest_sha256(joined)
        with pytest.raises(ValueError): prepare_coordinate_census(case, request=request, joined=joined)


@pytest.mark.parametrize("damage", ["index", "index-bool", "order", "binding", "mask"],
    ids=["index", "index-bool", "order", "binding", "mask"])
def test_coordinate_census_resealed_output_refuses_exact_regeneration(coordinate_census, damage):
    case = coordinate_census
    report = prepare_coordinate_census(case)
    if damage == "index": report["row_references"][0]["source_coordinate_span_index"] = 0
    elif damage == "index-bool": report["row_references"][0]["source_coordinate_span_index"] = True
    elif damage == "order": report["row_references"].reverse()
    elif damage == "binding": report["row_references"][0]["entity_semantic_binding"] = {"invented": "A"}
    else: report["training_mask"] = 1
    with pytest.raises(ValueError): validate_coordinate_census(case, report)


@pytest.mark.parametrize("source", ["entity", "paired"], ids=["entity", "paired"])
def test_coordinate_census_closing_checks_refuse_physical_drift(coordinate_census, monkeypatch, source):
    case = coordinate_census
    if source == "entity": target = case.entity_path
    else:
        selected = case.joined["span_inventory"]["manifests"][0]["manifest"]["tables"]["paired_spans"]
        target = Path(case.source["request"]["paired_bundles"][0]["repository_root"]) / selected["path_in_repo"]
    original = target.read_bytes()
    genuine = join.validate_source_span_entity_join_manifest_v2
    changed = []
    def drift(*args, **kwargs):
        result = genuine(*args, **kwargs)
        if not changed:
            target.write_bytes(original + b"closing physical mutation")
            changed.append(True)
        return result
    monkeypatch.setattr(join, "validate_source_span_entity_join_manifest_v2", drift)
    try:
        with pytest.raises(ValueError): prepare_coordinate_census(case)
        assert changed == [True]
        assert len(case.calls["bindings"]) == 2
        assert case.calls["bindings"][0]["passed"] is True
        if source == "entity": assert case.calls["bindings"][1]["passed"] is False
    finally: target.write_bytes(original)


def test_coordinate_census_closing_original_input_fence(coordinate_census, monkeypatch):
    case = coordinate_census
    genuine = join.validate_source_span_entity_join_manifest_v2
    def mutate(*args, **kwargs):
        result = genuine(*args, **kwargs)
        case.originals["source_metadata_bytes"]["README.md"] += b"late original mutation"
        return result
    monkeypatch.setattr(join, "validate_source_span_entity_join_manifest_v2", mutate)
    with pytest.raises(ValueError): prepare_coordinate_census(case)
    assert len(case.calls["bindings"]) == 2


def test_coordinate_census_primary_failure_preserves_secondary_custody(coordinate_census, monkeypatch):
    case = coordinate_census
    genuine = join.validate_source_span_entity_join_manifest_v2
    primary = RuntimeError("authored failure after genuine coordinate join")
    def fail(*args, **kwargs):
        genuine(*args, **kwargs)
        case.originals["source_metadata_bytes"]["README.md"] += b"secondary original mutation"
        raise primary
    monkeypatch.setattr(join, "validate_source_span_entity_join_manifest_v2", fail)
    with pytest.raises(RuntimeError) as caught: prepare_coordinate_census(case)
    assert caught.value is primary
    assert any("original" in note for note in getattr(primary, "__notes__", []))
    assert len(case.calls["bindings"]) == 2 and all(row["passed"] for row in case.calls["bindings"])


@pytest.mark.parametrize("producer", ["companion", "join"], ids=["companion", "join"])
def test_coordinate_census_stale_source_refuses(coordinate_census, monkeypatch, producer):
    module = subject if producer == "companion" else join
    monkeypatch.setattr(module, "_SELF_PIN", "0" * 64)
    with pytest.raises(ValueError): prepare_coordinate_census(coordinate_census)


def test_coordinate_census_validator_preserves_offered_report_fence(coordinate_census, monkeypatch):
    case = coordinate_census
    report = prepare_coordinate_census(case)
    genuine = join.validate_source_span_entity_join_manifest_v2
    def mutate(*args, **kwargs):
        result = genuine(*args, **kwargs)
        report["authority"]["admitted"] = True
        return result
    monkeypatch.setattr(join, "validate_source_span_entity_join_manifest_v2", mutate)
    with pytest.raises(ValueError): validate_coordinate_census(case, report)


def test_coordinate_census_alternate_entity_locator_cannot_rewrite_prior_identity(coordinate_census, tmp_path):
    with pytest.raises(ValueError):
        prepare_coordinate_census(coordinate_census, entity_path=tmp_path / "foreign.parquet")


def test_coordinate_census_actual_footer_refuses_resealed_false_population(coordinate_census):
    case = coordinate_census
    census, request = deepcopy(case.census), deepcopy(case.request)
    census["rows"] = census["source"]["expected_rows"] = request["entity"]["rows"] = 15
    census["disposition_counts"]["unknown_record_kind_observation"] -= 1
    census["census_sha256"] = sha(wire({key: value for key, value in census.items() if key != "census_sha256"}))
    raw = wire(census)
    request.update(census_raw_sha256=sha(raw), census_sha256=census["census_sha256"])
    with pytest.raises(entity.EntityIndexIntakeError, match="footer row count"):
        prepare_coordinate_census(case, request=request, census_raw=raw)
    assert case.calls["joins"] == []
    assert len(case.calls["bindings"]) == 2 and not any(row["passed"] for row in case.calls["bindings"])


def test_coordinate_census_closing_producer_fence_after_real_join(coordinate_census, monkeypatch):
    case = coordinate_census
    genuine = join.validate_source_span_entity_join_manifest_v2
    def drift(*args, **kwargs):
        result = genuine(*args, **kwargs)
        monkeypatch.setattr(subject, "_SELF_PIN", "0" * 64)
        return result
    monkeypatch.setattr(join, "validate_source_span_entity_join_manifest_v2", drift)
    with pytest.raises(ValueError, match="changed since import"):
        prepare_coordinate_census(case)
    assert len(case.calls["joins"]) == 1 and case.calls["joins"][0]["passed"] is True
    assert len(case.calls["bindings"]) == 2 and all(row["passed"] for row in case.calls["bindings"])


# The wire companion reuses the tiny genuine prior census and the existing
# original coordinate/metadata fixtures. No retained environmental population
# or fresh entity rescan is needed by these selected controls.
from ipfs_datasets_py.logic.autoformal import legal_source_package_intake_v1 as wire_source
from tests.unit.logic.autoformal.test_legal_source_package_intake_v1 import wire_intake_inputs
from tests.unit.logic.autoformal.test_legal_source_span_entity_coordinate_join_v2 import prepare_wire_join


def materialize_wire_census(directory, prior, *, selected_indices=(1, 3)):
    source = coordinate_join_fixture.__wrapped__(directory,
        SimpleNamespace(param={"selected_indices": selected_indices}))
    source_request, metadata = wire_intake_inputs()
    source["source_raw"], source["metadata"] = wire(source_request), metadata
    source["request"]["schema"] = join.REQUEST_SCHEMA_V3
    source["request"]["source_request_sha256"] = sha(source["source_raw"])
    info = json.loads(source["info_raw"])
    info["dataset_info"]["splits"]["train"]["num_examples"] = 16
    source["info_raw"] = wire(info)
    source["request"]["entity"]["info_sha256"] = sha(source["info_raw"])
    joined = prepare_wire_join(source)
    original_request = wire(source["request"])
    originals = {"request_raw": original_request, "source_request_raw": source["source_raw"],
        "source_metadata_bytes": source["metadata"],
        "paired_inventory_request_raw": wire(source["paired_request"]),
        "paired_manifest_bytes": source["manifests"], "entity_info_raw": source["info_raw"],
        "expected_request_sha256": sha(original_request), "legacy_join_inputs": None}
    census = deepcopy(prior["census"])
    request = {"schema": "legal-source-span-entity-census-request/v3",
        "join_report_sha256": join.source_span_entity_join_manifest_sha256(joined),
        "census_raw_sha256": sha(prior["raw"]), "census_sha256": census["census_sha256"],
        "join_originals_sha256": subject.source_span_entity_census_join_originals_sha256(originals),
        "source_coordinate_report_sha256": source["coordinate"]["pin"],
        "metadata_profile": "hf-default-parquet-envelope/v1",
        "source_metadata_intake_sha256": joined["source_metadata_intake_sha256"],
        "entity": {"repository_id": "justicedao/uscode-autoformal-entity-cache", "revision": "c" * 40,
            "configuration": "autoformal_uscode", "file_sha256": sha(prior["bytes"]),
            "file_bytes": len(prior["bytes"]), "rows": 16},
        "census_limits": deepcopy(census["limits"])}
    return SimpleNamespace(source=source, joined=joined, originals=originals, census=census,
        census_raw=prior["raw"], entity_path=prior["path"], entity_bytes=prior["bytes"], request=request)


@pytest.fixture(scope="module")
def wire_census_base(tmp_path_factory, coordinate_prior_census):
    directory = tmp_path_factory.mktemp("wire-coordinate-census", numbered=False)
    return materialize_wire_census(directory, coordinate_prior_census)


@pytest.fixture
def wire_census(wire_census_base, monkeypatch):
    case = deepcopy(wire_census_base)
    case.calls = {"bindings": [], "joins": [], "intakes": [], "intake_validations": [], "forbidden_scans": 0}
    genuine_binding = entity.validate_census_bindings
    genuine_join = join.validate_source_span_entity_join_manifest_v3
    genuine_intake = wire_source.prepare_source_package_intake_v2
    genuine_intake_validation = wire_source.validate_source_package_intake_v2
    depth = {"join": 0}

    def no_scan(*args, **kwargs):
        case.calls["forbidden_scans"] += 1
        pytest.fail("wire census must retain prior entity-row observations without rescanning")

    def no_legacy(*args, **kwargs):
        pytest.fail("explicit wire census entered a legacy source or coordinate delegate")

    def binding(*args, **kwargs):
        result = genuine_binding(*args, **kwargs)
        case.calls["bindings"].append(result)
        return result

    def replay(*args, **kwargs):
        depth["join"] += 1
        try:
            result = genuine_join(*args, **kwargs)
        finally:
            depth["join"] -= 1
        case.calls["joins"].append(result)
        return result

    def intake(*args, **kwargs):
        result = genuine_intake(*args, **kwargs)
        case.calls["intakes"].append(result)
        return result

    def validate_intake(*args, **kwargs):
        result = genuine_intake_validation(*args, **kwargs)
        if depth["join"] == 0:
            case.calls["intake_validations"].append(result)
        return result

    for name in ("census_parquet", "validate_census", "iter_observed_rows", "_rows"):
        monkeypatch.setattr(entity, name, no_scan)
    for name in ("prepare_source_span_entity_join_manifest", "validate_source_span_entity_join_manifest",
                 "prepare_source_span_entity_join_manifest_v2", "validate_source_span_entity_join_manifest_v2"):
        monkeypatch.setattr(join, name, no_legacy)
    for name in ("prepare_source_package_intake", "validate_source_package_intake"):
        monkeypatch.setattr(wire_source, name, no_legacy)
    monkeypatch.setattr(entity, "validate_census_bindings", binding)
    monkeypatch.setattr(join, "validate_source_span_entity_join_manifest_v3", replay)
    monkeypatch.setattr(wire_source, "prepare_source_package_intake_v2", intake)
    monkeypatch.setattr(wire_source, "validate_source_package_intake_v2", validate_intake)
    yield case
    assert case.calls["forbidden_scans"] == 0
    assert case.entity_path.read_bytes() == case.entity_bytes


def prepare_wire_census(case, *, request=None, joined=None, census_raw=None, originals=None,
                        entity_path=None, expected=None):
    raw = wire(case.request if request is None else request)
    return subject.prepare_source_span_entity_census_v3(raw,
        case.joined if joined is None else joined, case.census_raw if census_raw is None else census_raw,
        case.entity_path if entity_path is None else entity_path,
        expected_request_sha256=sha(raw) if expected is None else expected,
        join_originals=case.originals if originals is None else originals)


def validate_wire_census(case, report, *, expected=None):
    offered = json.loads(report) if type(report) is bytes else report
    request = wire(case.request)
    return subject.validate_source_span_entity_census_v3(report, request, case.joined,
        case.census_raw, case.entity_path, expected_request_sha256=sha(request),
        expected_report_sha256=subject.source_span_entity_census_sha256(offered) if expected is None else expected,
        join_originals=case.originals)


def wire_census_recommit(case, joined, originals=None):
    request = deepcopy(case.request)
    request["join_report_sha256"] = join.source_span_entity_join_manifest_sha256(joined)
    request["source_metadata_intake_sha256"] = joined["source_metadata_intake_sha256"]
    if originals is not None:
        request["join_originals_sha256"] = subject.source_span_entity_census_join_originals_sha256(originals)
    return request


@pytest.mark.parametrize("transport", ["object", "bytes"], ids=["object", "bytes"])
def test_wire_census_genuine_roundtrip_retains_originals_and_prior_census_without_rescan(wire_census, transport):
    case = wire_census
    original_join, original_inputs = wire(case.joined), deepcopy(case.originals)
    report = prepare_wire_census(case)
    assert validate_wire_census(case, wire(report) if transport == "bytes" else report) == report
    assert report["schema"] == "legal-source-span-entity-census/v3"
    assert report["source_compatibility_profile"] == "paired-coordinate-hf-wire-entity-census/v1"
    assert report["metadata_profile"] == "hf-default-parquet-envelope/v1"
    assert report["source_metadata_request_schema"] == wire_source.REQUEST_SCHEMA_V2
    assert report["source_metadata_intake_sha256"] == case.joined["source_metadata_intake_sha256"]
    assert wire(report["join_report"]) == original_join and case.originals == original_inputs
    assert report["join_report"]["schema"] == join.SCHEMA_V3
    assert report["join_report"]["entity_metadata"]["verified_file_rows"] == 0
    intake = report["join_report"]["source_metadata_intake"]
    assert len(intake["files"]) == 5
    assert intake["metadata_validation"]["table_bodies_read"] is False
    assert intake["metadata_validation"]["Arrow_loaded"] is False
    assert report["join_report"]["paired_bundles"][0]["payload_intake"]["schema"] == "legal-paired-payload-intake/v2"
    assert report["census"]["raw_utf8"].encode() == case.census_raw
    assert report["census_binding_validation"]["fresh_row_replay_performed"] is False
    assert report["counts"]["prior_entity_census_rows"] == 16
    assert report["counts"]["selected_physical_paired_rows"] == 2
    assert report["counts"]["selected_paired_row_references"] == 2
    assert len(case.calls["joins"]) >= 2 and len(case.calls["bindings"]) >= 4
    assert case.calls["intakes"]
    assert case.calls["intake_validations"]
    assert all(row["schema"] == wire_source.SCHEMA_V2 for row in case.calls["intakes"])
    assert all(row["schema"] == wire_source.SCHEMA_V2 for row in case.calls["intake_validations"])
    carrier = report["join_report"]["paired_bundles"][0]["payload_intake"]["source_coordinates"]
    assert wire(report).count(wire(carrier["report_raw_utf8"])) == 1
    assert [row["source_coordinate_span_index"] for row in report["row_references"]] == [1, 3]
    assert [row["physical_identity_sha256"] for row in report["row_references"]] == [
        row["physical_identity_sha256"] for row in case.joined["row_references"]]
    assert_coordinate_census_unqualified(report)


def test_wire_census_duplicate_global_indices_preserve_distinct_physical_order(
        wire_census, coordinate_prior_census, tmp_path):
    case = materialize_wire_census(tmp_path, coordinate_prior_census, selected_indices=(3, 1))
    report = prepare_wire_census(case)
    assert validate_wire_census(case, report) == report
    rows = report["row_references"]
    assert [row["reference_ordinal"] for row in rows] == [0, 1]
    assert [row["source_coordinate_span_index"] for row in rows] == [3, 1]
    assert [row["physical_identity"]["row_ordinal"] for row in case.joined["row_references"]] == [0, 1]
    assert len({row["physical_identity_sha256"] for row in rows}) == 2
    assert report["counts"]["selected_paired_row_references"] == 2
    assert_coordinate_census_unqualified(report)
    # The batch producer rejects duplicate source-span IDs. Exercise repeated
    # index preservation separately at the shared pure projection boundary;
    # this synthetic projection is explicitly not a genuine joined artifact.
    projection = deepcopy(case.joined)
    for key in ("source_provenance_json", "source_coordinate_report_sha256", "source_coordinate_span_index"):
        value = projection["row_references"][0][key]
        projection["row_references"][1][key] = value
        projection["paired_bundles"][0]["payload_intake"]["rows"][1][key] = value
    projected = subject._coordinate_references(projection, case.request)
    assert [row["source_coordinate_span_index"] for row in projected] == [3, 3]
    assert [row["reference_ordinal"] for row in projected] == [0, 1]
    assert len({row["physical_identity_sha256"] for row in projected}) == 2
    request = wire_census_recommit(case, projection)
    with pytest.raises(ValueError): prepare_wire_census(case, request=request, joined=projection)


@pytest.mark.parametrize("damage", ["schema", "join_report_sha256", "census_raw_sha256", "census_sha256",
    "entity", "census_limits", "join_originals_sha256", "source_coordinate_report_sha256",
    "metadata_profile", "source_metadata_intake_sha256", "unknown"],
    ids=["schema", "join_report_sha256", "census_raw_sha256", "census_sha256", "entity", "census_limits",
         "join_originals_sha256", "source_coordinate_report_sha256", "metadata_profile",
         "source_metadata_intake_sha256", "unknown"])
def test_wire_census_requires_the_complete_closed_ten_field_request_before_owners(wire_census, monkeypatch, damage):
    request = deepcopy(wire_census.request)
    if damage == "unknown": request["unknown_wire_option"] = True
    else: request.pop(damage)
    monkeypatch.setattr(subject, "_owners", lambda: pytest.fail("incomplete wire request reached owners"))
    with pytest.raises(ValueError): prepare_wire_census(wire_census, request=request)


@pytest.mark.parametrize("pin", ["request", "join_report_sha256", "census_raw_sha256", "census_sha256",
    "join_originals_sha256", "source_coordinate_report_sha256", "source_metadata_intake_sha256"],
    ids=["request", "join", "census-raw", "census-canonical", "originals", "coordinate", "wire-intake"])
def test_wire_census_independent_complete_pins_are_required(wire_census, pin):
    request = deepcopy(wire_census.request)
    if pin == "request":
        with pytest.raises(ValueError): prepare_wire_census(wire_census, expected="0" * 64)
    else:
        request[pin] = "0" * 64
        with pytest.raises(ValueError): prepare_wire_census(wire_census, request=request)


@pytest.mark.parametrize("damage", ["request-schema", "metadata-profile", "join-schema", "join-profile",
    "intake-schema", "intake-profile", "nested-request-schema"],
    ids=["request-schema", "metadata-profile", "join-schema", "join-profile", "intake-schema",
         "intake-profile", "nested-request-schema"])
def test_wire_census_rehashed_profile_changes_do_not_alias_older_contracts(wire_census, damage):
    case = wire_census
    joined = deepcopy(case.joined)
    if damage == "join-schema": joined["schema"] = join.SCHEMA_V2
    elif damage == "join-profile": joined["source_compatibility_profile"] = join.COORDINATE_PROFILE
    elif damage == "intake-schema": joined["source_metadata_intake"]["schema"] = wire_source.SCHEMA
    elif damage == "intake-profile": joined["source_metadata_intake"]["metadata_profile"] = "legacy-info/v1"
    elif damage == "nested-request-schema": joined["source_metadata_request_schema"] = wire_source.REQUEST_SCHEMA
    if damage in ("intake-schema", "intake-profile"):
        joined["source_metadata_intake_sha256"] = wire_source.source_package_intake_sha256(joined["source_metadata_intake"])
    request = wire_census_recommit(case, joined)
    if damage == "request-schema": request["schema"] = subject.REQUEST_SCHEMA_V2
    elif damage == "metadata-profile": request["metadata_profile"] = "legacy-info/v1"
    with pytest.raises(ValueError): prepare_wire_census(case, request=request, joined=joined)


def test_wire_census_nested_original_source_request_must_remain_explicit_wire_v2(wire_census):
    case = wire_census
    originals = deepcopy(case.originals)
    source_request = json.loads(originals["source_request_raw"])
    source_request["schema"] = wire_source.REQUEST_SCHEMA
    originals["source_request_raw"] = wire(source_request)
    outer = json.loads(originals["request_raw"])
    outer["source_request_sha256"] = sha(originals["source_request_raw"])
    originals["request_raw"] = wire(outer)
    originals["expected_request_sha256"] = sha(originals["request_raw"])
    request = wire_census_recommit(case, case.joined, originals)
    with pytest.raises(ValueError): prepare_wire_census(case, request=request, originals=originals)


@pytest.mark.parametrize("damage", ["schema", "profile", "source-request-schema", "intake-pin",
    "coordinate-index", "row-order", "mask", "semantic-binding"],
    ids=["schema", "profile", "source-request-schema", "intake-pin", "coordinate-index", "row-order",
         "mask", "semantic-binding"])
def test_wire_census_rehashed_output_requires_complete_original_regeneration(wire_census, damage):
    case = wire_census
    report = prepare_wire_census(case)
    if damage == "schema": report["schema"] = subject.SCHEMA_V2
    elif damage == "profile": report["metadata_profile"] = "legacy-info/v1"
    elif damage == "source-request-schema": report["source_metadata_request_schema"] = wire_source.REQUEST_SCHEMA
    elif damage == "intake-pin": report["source_metadata_intake_sha256"] = "0" * 64
    elif damage == "coordinate-index": report["row_references"][0]["source_coordinate_span_index"] = 0
    elif damage == "row-order": report["row_references"].reverse()
    elif damage == "mask": report["training_mask"] = True
    else: report["row_references"][0]["entity_semantic_binding"] = {"inferred_from_matching_label": True}
    with pytest.raises(ValueError): validate_wire_census(case, report)


def test_wire_census_wrong_independent_output_pin_refuses_before_replay(wire_census, monkeypatch):
    report = prepare_wire_census(wire_census)
    counts = {key: len(wire_census.calls[key]) for key in ("bindings", "joins", "intake_validations")}
    monkeypatch.setattr(subject, "_wire_census_owners",
        lambda *a, **k: pytest.fail("wrong output pin reached actual wire owners"))
    with pytest.raises(ValueError): validate_wire_census(wire_census, report, expected="0" * 64)
    assert {key: len(wire_census.calls[key]) for key in counts} == counts


@pytest.mark.parametrize("target", ["original", "detached", "offered-join"],
    ids=["original", "detached", "offered-join"])
def test_wire_census_genuine_join_cannot_mutate_original_detached_or_offered_inputs(wire_census, monkeypatch, target):
    case = wire_census
    genuine = join.validate_source_span_entity_join_manifest_v3
    observed = []

    def mutate(*args, **kwargs):
        result = genuine(*args, **kwargs)
        if not observed:
            if target == "original": case.originals["source_metadata_bytes"]["README.md"] += b" late original wire metadata"
            elif target == "detached":
                metadata = kwargs.get("source_metadata_bytes") if "source_metadata_bytes" in kwargs else args[3]
                metadata["README.md"] += b" late detached wire metadata"
            else: case.joined["source_metadata_profile"] = "late-offered-profile/v9"
            observed.append(result["schema"])
        return result

    monkeypatch.setattr(join, "validate_source_span_entity_join_manifest_v3", mutate)
    with pytest.raises(ValueError): prepare_wire_census(case)
    assert observed == [join.SCHEMA_V3]


@pytest.mark.parametrize("target", ["binding", "join", "intake"], ids=["binding", "join", "intake"])
def test_wire_census_retained_real_returns_remain_fenced_after_final_entity_callback(wire_census, monkeypatch, target):
    case = wire_census
    genuine = entity.validate_census_bindings
    observed = []

    def mutate_after_closing_binding(*args, **kwargs):
        result = genuine(*args, **kwargs)
        if len(case.calls["bindings"]) >= 2 and not observed:
            if target == "binding": case.calls["bindings"][0]["fresh_row_replay_performed"] = True
            elif target == "join": case.calls["joins"][0]["authority"]["admitted"] = True
            else: case.calls["intake_validations"][0]["metadata_profile"] = "late-retained-intake/v9"
            observed.append(True)
        return result

    monkeypatch.setattr(entity, "validate_census_bindings", mutate_after_closing_binding)
    with pytest.raises(ValueError): prepare_wire_census(case)
    assert observed == [True]


@pytest.mark.parametrize("target", ["output", "original", "binding", "join", "intake", "producer"],
    ids=["output", "original", "binding", "join", "intake", "producer"])
def test_wire_census_final_encoder_cannot_mutate_any_retained_custody(wire_census, monkeypatch, target):
    case = wire_census
    genuine = subject._wire
    observed = []

    def mutate_after_encoding(value, *args, **kwargs):
        raw = genuine(value, *args, **kwargs)
        if type(value) is dict and value.get("schema") == "legal-source-span-entity-census/v3" \
                and len(case.calls["bindings"]) >= 2 and not observed:
            if target == "output": value["training_mask"] = True
            elif target == "original": case.originals["source_metadata_bytes"]["README.md"] += b" final encoder mutation"
            elif target == "binding": case.calls["bindings"][0]["fresh_row_replay_performed"] = True
            elif target == "join": case.calls["joins"][0]["authority"]["admitted"] = True
            elif target == "intake": case.calls["intake_validations"][0]["metadata_profile"] = "encoder-intake/v9"
            else: monkeypatch.setattr(subject, "_SELF_PIN", "0" * 64)
            observed.append(True)
        return raw

    monkeypatch.setattr(subject, "_wire", mutate_after_encoding)
    with pytest.raises(ValueError): prepare_wire_census(case)
    assert observed == [True]


@pytest.mark.parametrize("source", ["entity", "paired"], ids=["entity", "paired"])
def test_wire_census_final_original_replay_refuses_physical_file_drift(
        wire_census, coordinate_prior_census, tmp_path, monkeypatch, source):
    # Paired witnesses include inode/mtime/ctime. Restoring bytes cannot restore
    # those identities; a mutation must never poison the shared module bundle.
    case = materialize_wire_census(tmp_path, coordinate_prior_census)
    if source == "entity": target = case.entity_path
    else:
        selected = case.joined["span_inventory"]["manifests"][0]["manifest"]["tables"]["paired_spans"]
        target = Path(case.source["request"]["paired_bundles"][0]["repository_root"]) / selected["path_in_repo"]
    original = target.read_bytes()
    genuine = join.validate_source_span_entity_join_manifest_v3
    observed = []

    def drift(*args, **kwargs):
        result = genuine(*args, **kwargs)
        if not observed:
            target.write_bytes(original + b" closing wire-census drift")
            observed.append(True)
        return result

    monkeypatch.setattr(join, "validate_source_span_entity_join_manifest_v3", drift)
    try:
        with pytest.raises(ValueError): prepare_wire_census(case)
        assert observed == [True]
    finally: target.write_bytes(original)


def test_wire_census_base_exception_primary_survives_secondary_physical_and_input_failures(wire_census, monkeypatch):
    case = wire_census
    class DeliberateWirePrimary(BaseException):
        pass
    primary = DeliberateWirePrimary("genuine wire replay followed by authored primary failure")
    genuine = join.validate_source_span_entity_join_manifest_v3
    original = case.entity_path.read_bytes()
    observed = []

    def fail(*args, **kwargs):
        result = genuine(*args, **kwargs)
        observed.append(result["schema"])
        case.entity_path.write_bytes(original + b" secondary entity drift")
        case.originals["source_metadata_bytes"]["README.md"] += b" secondary original drift"
        raise primary

    monkeypatch.setattr(join, "validate_source_span_entity_join_manifest_v3", fail)
    try:
        with pytest.raises(DeliberateWirePrimary) as caught: prepare_wire_census(case)
        assert caught.value is primary and observed
        notes = getattr(primary, "__notes__", [])
        assert any("entity" in note for note in notes)
        assert any("original" in note or "input" in note for note in notes)
    finally: case.entity_path.write_bytes(original)


@pytest.mark.parametrize("version", [1, 2], ids=["v1", "v2"])
def test_wire_census_request_is_refused_by_unchanged_older_public_profiles(wire_census, version):
    case = wire_census
    api = subject.prepare_source_span_entity_census_v1 if version == 1 else subject.prepare_source_span_entity_census_v2
    raw = wire(case.request)
    with pytest.raises(ValueError):
        api(raw, case.joined, case.census_raw, case.entity_path,
            expected_request_sha256=sha(raw), join_originals=case.originals)


def test_wire_census_complete_result_is_detached_from_original_inputs_and_returns(wire_census):
    case = wire_census
    before = wire(case.joined), deepcopy(case.originals), deepcopy(case.census)
    report = prepare_wire_census(case)
    report["join_report"]["source_metadata_intake"]["metadata_profile"] = "caller-mutated-report/v9"
    report["row_references"][0]["entity_semantic_binding"] = {"caller_mutation": True}
    report["census_binding_validation"]["fresh_row_replay_performed"] = True
    assert before == (wire(case.joined), case.originals, case.census)
    assert all(row["fresh_row_replay_performed"] is False for row in case.calls["bindings"])
    assert all(row["source_metadata_intake"]["metadata_profile"] == "hf-default-parquet-envelope/v1"
        for row in case.calls["joins"])
    assert all(row["metadata_profile"] == "hf-default-parquet-envelope/v1"
        for row in case.calls["intake_validations"])
    assert_coordinate_census_unqualified(prepare_wire_census(case))


def test_wire_census_parsed_offered_report_cannot_replace_independently_pinned_caller_bytes(wire_census, monkeypatch):
    case = wire_census
    correct = prepare_wire_census(case)
    offered = deepcopy(correct)
    offered["counts"]["selected_paired_row_references"] = 999
    bad_pin = subject.source_span_entity_census_sha256(offered)
    assert bad_pin != subject.source_span_entity_census_sha256(correct)
    genuine_read = subject._read_json
    genuine_join = join.validate_source_span_entity_join_manifest_v3
    parsed, changed = [], []

    def capture_actual_offered_parse(raw, maximum, label):
        result = genuine_read(raw, maximum, label)
        if label == "wire census companion report":
            assert result is not offered and result["schema"] == "legal-source-span-entity-census/v3"
            assert result["counts"]["selected_paired_row_references"] == 999
            parsed.append(result)
        return result

    def correct_only_detached_offered_after_real_join(*args, **kwargs):
        result = genuine_join(*args, **kwargs)
        if not changed:
            assert len(parsed) == 1 and parsed[0] is not offered
            parsed[0].clear()
            parsed[0].update(deepcopy(correct))
            changed.append(True)
        return result

    monkeypatch.setattr(subject, "_read_json", capture_actual_offered_parse)
    monkeypatch.setattr(join, "validate_source_span_entity_join_manifest_v3", correct_only_detached_offered_after_real_join)
    with pytest.raises(ValueError): validate_wire_census(case, offered, expected=bad_pin)
    assert changed == [True] and len(parsed) == 1
    assert offered["counts"]["selected_paired_row_references"] == 999
    assert subject.source_span_entity_census_sha256(offered) == bad_pin
    assert parsed[0] == correct


def test_wire_census_first_preflight_encoder_cannot_rewrite_original_join_before_capture(wire_census, monkeypatch):
    case = wire_census
    genuine = subject._wire
    changed = []

    def mutate_after_original_join_encoding(value, *args, **kwargs):
        raw = genuine(value, *args, **kwargs)
        if value is case.joined and not changed:
            case.joined["counts"]["physical_paired_rows"] += 7
            changed.append(True)
        return raw

    monkeypatch.setattr(subject, "_wire", mutate_after_original_join_encoding)
    with pytest.raises(ValueError): prepare_wire_census(case)
    assert changed == [True]


@pytest.mark.parametrize("damage", ["authority", "census-pin", "extra-field"],
    ids=["authority", "census-pin", "extra-field"])
def test_wire_census_consistently_corrupted_real_entity_bindings_cannot_define_a_new_baseline(
        wire_census, monkeypatch, damage):
    case = wire_census
    genuine = entity.validate_census_bindings
    observed = []

    def corrupt_every_genuine_binding(*args, **kwargs):
        result = genuine(*args, **kwargs)
        if damage == "authority":
            key = next(iter(result["authority"]))
            result["authority"][key] = True
        elif damage == "census-pin": result["census_sha256"] = "0" * 64
        else: result["accepted_semantic_binding"] = True
        observed.append(result)
        return result

    monkeypatch.setattr(entity, "validate_census_bindings", corrupt_every_genuine_binding)
    with pytest.raises(ValueError): prepare_wire_census(case)
    assert observed
    for result in observed:
        if damage == "authority": assert any(value is True for value in result["authority"].values())
        elif damage == "census-pin": assert result["census_sha256"] == "0" * 64
        else: assert result["accepted_semantic_binding"] is True


def test_wire_census_held_finalizer_refuses_callback_replacement_after_genuine_join(wire_census, monkeypatch):
    case = wire_census
    genuine_join = join.validate_source_span_entity_join_manifest_v3
    genuine_witness = join._coordinate_file_witnesses
    changed, closing_physical = [], []

    def observe_real_physical_checks(*args, **kwargs):
        result = genuine_witness(*args, **kwargs)
        if changed: closing_physical.append(result)
        return result

    def replace_finalizer_after_real_join(*args, **kwargs):
        result = genuine_join(*args, **kwargs)
        if not changed:
            monkeypatch.setattr(subject, "_finish_coordinate_custody", lambda *a, **k: None)
            changed.append(True)
        return result

    monkeypatch.setattr(join, "_coordinate_file_witnesses", observe_real_physical_checks)
    monkeypatch.setattr(join, "validate_source_span_entity_join_manifest_v3", replace_finalizer_after_real_join)
    with pytest.raises(ValueError): prepare_wire_census(case)
    assert changed == [True]
    assert len(case.calls["bindings"]) >= 2
    assert closing_physical
