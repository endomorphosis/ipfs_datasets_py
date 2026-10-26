"""Original-bound coordinate custody stays separate from context permission.

Authored source inventory and real coordinate/Arrow owners supply the fixtures.
No model, database, source-occurrence search or Lean execution is performed.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_compact_source_context_cache_intake_v1 as subject
from ipfs_datasets_py.logic.autoformal import legal_compact_source_context_inventory_v1 as inventory
from ipfs_datasets_py.logic.autoformal import legal_paired_payload_intake_v1 as payload
from ipfs_datasets_py.logic.autoformal import paired_span_census as paired
from tests.unit.logic.autoformal.test_legal_compact_source_context_cache_intake_v1 import no_authority
from tests.unit.logic.autoformal.test_legal_compact_source_context_inventory_v1 import (
    case as inventory_case, originals, resolver,
)
from tests.unit.logic.autoformal.test_legal_paired_coordinate_intake_v2 import (
    MARKER, build_coordinate_payload, sha,
)


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


@pytest.fixture
def coordinate_context(inventory_case, tmp_path):
    raw, options = originals(inventory_case)
    parent = inventory.prepare_source_context_inventory_v1(*raw, **options,
        source_resolver=resolver(inventory_case))
    inventory_originals = {**dict(zip(("population_raw", "occurrences_raw", "catalog_raw", "access_raw"), raw)),
        **options, "source_resolver": resolver(inventory_case), "expected_report_sha256": sha(wire(parent))}
    text = inventory_case["inputs"]["same-left"]["text"]
    documents = [
        {"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:10:900",
         "text": "Unselected governing Ω context."},
        {"legal_id": "usc:us:10:1", "text": text},
        {"legal_id": "usc:us:10:2", "text": text},
        {"legal_id": "usc:us:10:901", "text": "Other unselected context."},
    ]
    cache = build_coordinate_payload(tmp_path, documents=documents, selected_indices=(1, 2))
    entry = cache["written"]["manifest"]
    request = {"schema": "legal-paired-manifest-inventory-request/v2", "repository_id": paired.REPOSITORY,
        "revision": cache["request"]["revision"], "selection_scope": "explicit_paired_manifest_selection",
        "manifests": [{"path_in_repo": entry["path_in_repo"], "bytes": entry["bytes"],
            "sha256": entry["sha256"], "source_coordinate_report_sha256": cache["pin"]}]}
    bindings = {"schema": subject.BINDINGS_SCHEMA_V2, "cache_request_sha256": sha(wire(request)),
        "inventory_report_sha256": sha(wire(parent)), "rows": [
            {"manifest_path_in_repo": entry["path_in_repo"], "row_ordinal": index,
             "row_sha256": None, "occurrence_ids": ids}
            for index, ids in enumerate((["same-left"], ["same-left", "same-right"]))]}
    path = cache["request"]["repository_root"] / entry["path_in_repo"]
    return dict(cache=cache, request=request, bindings=bindings, manifest_bytes={entry["path_in_repo"]: path.read_bytes()},
        root=cache["request"]["repository_root"], inventory_report=parent, inventory_originals=inventory_originals)


def arguments(case):
    request, bindings = wire(case["request"]), wire(case["bindings"])
    return (request, bindings), dict(expected_cache_request_sha256=sha(request),
        expected_cache_bindings_sha256=sha(bindings), manifest_bytes=case["manifest_bytes"],
        repository_root=case["root"], inventory_report=case["inventory_report"],
        inventory_originals=case["inventory_originals"])


def prepare(case, **changes):
    args, options = arguments(case)
    return subject.prepare_source_context_cache_intake_v2(*args, **{**options, **changes})


def replay(case, report, **changes):
    args, options = arguments(case)
    return subject.validate_source_context_cache_intake_v2(report, *args,
        **{**options, "expected_report_sha256": sha(wire(report)), **changes})


def repin_request(case):
    case["bindings"]["cache_request_sha256"] = sha(wire(case["request"]))


def test_complete_coordinate_context_retains_originals_once_without_binding_authority(coordinate_context):
    case = coordinate_context
    report = prepare(case)
    assert replay(case, report) == report
    assert subject.source_context_cache_intake_sha256(report) == sha(wire(report))
    assert report["schema"] == subject.SCHEMA_V2 and report["profile"] == subject.PROFILE_V2
    assert report["inventory_report"] == case["inventory_report"]
    assert report["coverage"]["declared_reference_rows"] == report["coverage"]["coordinate_occurrence_replayed_rows"] == 2
    assert report["coverage"]["inventory_occurrences"] == 5
    carrier = report["bundles"][0]["payload_report"]["source_coordinates"]
    artifact = next(row for row in case["cache"]["bundle"]["artifacts"] if row["kind"] == "source_coordinate_report")
    assert carrier["report_raw_utf8"].encode() == paired.decode_artifact(artifact)
    assert json.loads(wire(report))["bundles"][0]["payload_report"]["source_coordinates"] == carrier
    assert carrier["report_raw_utf8"].index('"z_metadata"') < carrier["report_raw_utf8"].index('"a_metadata"')
    assert "Unselected governing Ω context." in carrier["report_raw_utf8"]
    assert len(json.loads(carrier["report_raw_utf8"])["spans"]) == 4
    assert wire(report).count(b'"report_raw_utf8":') == 1
    assert [row["source_coordinate_span_index"] for row in report["records"]] == [1, 2]
    assert [row["source_provenance_json"] for row in report["records"]] == case["cache"]["references"]
    assert [row["association_status"] for row in report["records"]] == ["declared_single_association", "ambiguous_source_occurrences"]
    assert report["records"][0]["physical_record_id"] != report["records"][1]["physical_record_id"]
    assert all(not item["source_correspondence_verified"] for row in report["records"] for item in row["association_results"])
    assert MARKER in report["records"][0]["derived_row_json"]
    assert MARKER not in carrier["report_raw_utf8"] and MARKER not in wire(report["inventory_report"]).decode()
    no_authority(report)


def test_coordinate_references_do_not_fill_undeclared_inventory_associations(coordinate_context):
    case = coordinate_context
    for row in case["bindings"]["rows"]:
        row["occurrence_ids"] = []
    report = prepare(case)
    assert report["coverage"]["associated_inventory_occurrences"] == 0
    assert report["coverage"]["coordinate_occurrence_replayed_rows"] == 2
    assert all(row["association_status"] == "unresolved_source_occurrence" for row in report["records"])
    no_authority(report)


def test_independent_coordinate_pin_is_checked_before_source_resolver(coordinate_context):
    case, calls = coordinate_context, []
    case["request"]["manifests"][0]["source_coordinate_report_sha256"] = "0" * 64
    repin_request(case)
    original = case["inventory_originals"]["source_resolver"]
    def resolve(reference):
        calls.append(reference)
        return original(reference)
    case["inventory_originals"]["source_resolver"] = resolve
    with pytest.raises(ValueError, match="coordinate.*pin|coordinate.*SHA|report"):
        prepare(case)
    assert calls == []


@pytest.mark.parametrize("damage", ["schema", "unknown_inventory_id", "row_order"])
def test_coordinate_binding_originals_remain_closed_and_explicit(coordinate_context, damage):
    case = coordinate_context
    if damage == "schema": case["bindings"]["schema"] = subject.BINDINGS_SCHEMA
    elif damage == "unknown_inventory_id": case["bindings"]["rows"][0]["occurrence_ids"] = ["invented-origin"]
    else: case["bindings"]["rows"].reverse()
    with pytest.raises(subject.SourceContextCacheIntakeError):
        prepare(case)


@pytest.mark.parametrize("kind", ["missing", "corrupt"])
def test_unreadable_coordinate_bundle_preserves_every_declared_slot_and_expected_pin(coordinate_context, kind):
    case = coordinate_context
    path = case["root"] / case["cache"]["written"]["artifacts"]["path_in_repo"]
    if kind == "missing": path.unlink()
    else: path.write_bytes(b"corrupt retained artifact table")
    report = prepare(case)
    assert report["coverage"]["declared_reference_rows"] == 2
    assert report["coverage"]["coordinate_occurrence_replayed_rows"] == 0
    assert report["bundles"][0]["payload_report"] is None
    for row in report["records"]:
        assert row["record_status"] == ("bundle_unavailable" if kind == "missing" else "bundle_corrupt")
        assert row["expected_source_coordinate_report_sha256"] == case["cache"]["pin"]
        assert row["source_provenance_json"] is row["source_coordinate_span_index"] is row["source_coordinate_report_sha256"] is None
        assert row["coordinate_transport_status"] == "cache_record_unavailable"
    no_authority(report)


@pytest.mark.parametrize("damage", ["report_bytes", "index", "reference", "pin", "drop_record", "association", "authority", "inference"])
def test_rehashed_context_report_cannot_replace_original_coordinate_and_inventory_replay(coordinate_context, damage):
    case = coordinate_context
    report = prepare(case)
    if damage == "report_bytes": report["bundles"][0]["payload_report"]["source_coordinates"]["report_raw_utf8"] += " "
    elif damage == "index": report["records"][0]["source_coordinate_span_index"] = 0
    elif damage == "reference": report["records"][0]["source_provenance_json"] = report["records"][1]["source_provenance_json"]
    elif damage == "pin": report["records"][0]["source_coordinate_report_sha256"] = "0" * 64
    elif damage == "drop_record": report["records"].pop()
    elif damage == "association": report["records"][0]["occurrence_ids"] = ["same-right"]
    elif damage == "authority": report["authority"]["source_correspondence_verified"] = True
    else: report["records"][0]["inference_view"] = {"target": MARKER}
    with pytest.raises(subject.SourceContextCacheIntakeError, match="original-bound replay"):
        replay(case, report)


def test_expected_physical_row_pin_is_not_replaced_by_coordinate_integrity(coordinate_context):
    case = coordinate_context
    case["bindings"]["rows"][0]["row_sha256"] = "0" * 64
    with pytest.raises(subject.SourceContextCacheIntakeError, match="physical cache row SHA256"):
        prepare(case)


def test_initial_coordinate_profile_refuses_two_manifests_before_file_scan(coordinate_context, tmp_path, monkeypatch):
    case = coordinate_context
    documents = deepcopy(case["cache"]["documents"])
    documents[0]["z_metadata"] = "separate complete source context"
    other = build_coordinate_payload(tmp_path / "other", documents=documents, selected_indices=(1, 2))
    entry = other["written"]["manifest"]
    case["request"]["manifests"].append({"path_in_repo": entry["path_in_repo"], "bytes": entry["bytes"],
        "sha256": entry["sha256"], "source_coordinate_report_sha256": other["pin"]})
    case["manifest_bytes"][entry["path_in_repo"]] = Path(entry["path"]).read_bytes()
    repin_request(case)
    monkeypatch.setattr(subject, "_files", lambda *a, **k: pytest.fail("multiple manifests reached file scan"))
    with pytest.raises(subject.SourceContextCacheIntakeError, match="one coordinate manifest"):
        prepare(case)


def test_declared_coordinate_row_bound_precedes_file_scan(coordinate_context, monkeypatch):
    case = coordinate_context
    old = case["request"]["manifests"][0]
    manifest = json.loads(case["manifest_bytes"][old["path_in_repo"]])
    manifest["tables"]["paired_spans"]["row_count"] = 65
    body = {key: value for key, value in manifest.items() if key not in {"fingerprint", "path_in_repo"}}
    fingerprint = sha(paired._json(body))
    path = str(Path(old["path_in_repo"]).parent / ("manifest-" + fingerprint + ".json"))
    manifest.update(fingerprint=fingerprint, path_in_repo=path)
    raw = paired._json(manifest)
    case["request"]["manifests"] = [dict(old, path_in_repo=path, bytes=len(raw), sha256=sha(raw))]
    case["manifest_bytes"] = {path: raw}
    repin_request(case)
    monkeypatch.setattr(subject, "_files", lambda *a, **k: pytest.fail("oversized declaration reached file scan"))
    with pytest.raises(subject.SourceContextCacheIntakeError, match="bounded complete declared"):
        prepare(case)


def test_retained_file_changes_after_real_decode_refuse_the_operation(coordinate_context, monkeypatch):
    case = coordinate_context
    original = payload.prepare_paired_payload_intake_v2
    path = case["root"] / case["request"]["manifests"][0]["path_in_repo"]
    def changed(**kwargs):
        report = original(**kwargs)
        path.write_bytes(path.read_bytes() + b" ")
        return report
    monkeypatch.setattr(payload, "prepare_paired_payload_intake_v2", changed)
    with pytest.raises(subject.SourceContextCacheIntakeError, match="file witnesses changed"):
        prepare(case)


def test_arbitrary_coordinate_payload_failure_is_not_an_unsupported_bundle(coordinate_context, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("authored unexpected failure")
    monkeypatch.setattr(payload, "prepare_paired_payload_intake_v2", fail)
    with pytest.raises(RuntimeError, match="authored unexpected failure"):
        prepare(coordinate_context)


def test_coordinate_cache_does_not_authorize_a_rehashed_parent_inventory(coordinate_context):
    case = coordinate_context
    forged = deepcopy(case["inventory_report"])
    forged["authority"]["source_authority_authenticated"] = True
    case["inventory_report"] = forged
    case["inventory_originals"]["expected_report_sha256"] = sha(wire(forged))
    case["bindings"]["inventory_report_sha256"] = sha(wire(forged))
    with pytest.raises(ValueError, match="replay|original"):
        prepare(case)


def test_coordinate_request_does_not_silently_enter_legacy_context_profile(coordinate_context):
    args, options = arguments(coordinate_context)
    with pytest.raises(ValueError, match="paired selection|paired manifest"):
        subject.prepare_source_context_cache_intake_v1(*args, **options)


@pytest.mark.parametrize("unsupported_pin", [
    "0c25ad7ea4008a90b2bb64627c863b1f880b41421ec9bffa862d0483f9ce62bd",
    "442d96a5f442a5f471a7cad923bfb2f73fd97a370acd4acd03415586f23259de",
], ids=["historical-cache", "different-primary-cache"])
def test_coordinate_source_fence_rejects_other_generations_before_delegates(
        coordinate_context, monkeypatch, unsupported_pin):
    """Historical and primary pins are no alternate public compatibility list."""
    case = coordinate_context
    calls = {"resolver": 0, "payload": 0}

    def forbidden_resolver(*args, **kwargs):
        calls["resolver"] += 1
        raise AssertionError("source resolver ran before the producer source fence")

    def forbidden_payload(*args, **kwargs):
        calls["payload"] += 1
        raise AssertionError("payload intake ran before the producer source fence")

    case["inventory_originals"]["source_resolver"] = forbidden_resolver
    monkeypatch.setattr(payload, "prepare_paired_payload_intake_v2", forbidden_payload)
    monkeypatch.setitem(subject._COORDINATE_SOURCE_PINS, "span_cache", unsupported_pin)
    with pytest.raises(subject.SourceContextCacheIntakeError,
                       match="producer source changed or fixed pin differs"):
        prepare(case)
    assert calls == {"resolver": 0, "payload": 0}


def test_coordinate_closing_source_fence_refuses_injected_read_drift_after_real_payload(
        coordinate_context, monkeypatch):
    """Inject read bytes only; keep actual source files and fence logic intact."""
    producer_path = subject._SELF_PATH.with_name("span_cache.py")
    real_read = Path.read_bytes
    original_bytes = real_read(producer_path)
    real_payload = payload.prepare_paired_payload_intake_v2
    observed = {"payload_completed": 0, "injected_source_reads": 0}

    def real_payload_then_arm(*args, **kwargs):
        result = real_payload(*args, **kwargs)
        observed["payload_completed"] += 1
        return result

    def injected_read(path):
        raw = real_read(path)
        if path == producer_path and observed["payload_completed"]:
            observed["injected_source_reads"] += 1
            return raw + b"\n# authored closing-source-read drift\n"
        return raw

    monkeypatch.setattr(payload, "prepare_paired_payload_intake_v2", real_payload_then_arm)
    monkeypatch.setattr(Path, "read_bytes", injected_read)
    with pytest.raises(subject.SourceContextCacheIntakeError,
                       match="producer source changed or fixed pin differs"):
        prepare(coordinate_context)
    assert observed["payload_completed"] == 1
    assert observed["injected_source_reads"] >= 1
    assert real_read(producer_path) == original_bytes
