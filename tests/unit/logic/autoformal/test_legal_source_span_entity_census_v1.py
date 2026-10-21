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
