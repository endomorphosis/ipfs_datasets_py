"""Portable authored source observations; no model, compiler or Lean runs."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import zlib

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import paired_span_census as paired
from ipfs_datasets_py.logic.autoformal import uscode_ingest as ingest
from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache


def encoded(value, *, ordered=False):
    return json.dumps(value, ensure_ascii=False, sort_keys=not ordered,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def retained(tmp_path):
    # Duplicate physical documents retain distinct global occurrence ordinals.
    documents = [{"legal_id": "usc:us:5:550", "entry_cid": "fixture:unverified",
                  "title": "5", "section": "550",
                  "text": " \tΩ agency shall\r\nkeep records.  Café may file!  "} for _ in range(2)]
    report = ingest.inventory_uscode_source_coordinates(documents,
        query="fixture:portable-coordinate", release_id="fixture:release")
    pin = ingest.uscode_source_coordinates_sha256(report)
    selected = [report["spans"][index]["source_span_id"] for index in (1, 2)]
    cache = SpanCache(tmp_path / "source.duckdb")
    cache._db.execute("SET threads=1")
    try:
        cache.enqueue_source_coordinates(report, documents, expected_report_sha256=pin,
            query=report["query"], release_id=report["release_id"])
        exported = cache.export_source_coordinates(pin, source_span_ids=selected)
    finally:
        cache.close()
    observations = [{**row, "compiler_result": {"compiler_status": "abstain", "rules": [],
        "compilation_complete": False, "reason": "authored transport fixture"}}
        for row in exported["rows"]]
    return exported, observations


def build(retained, *, coordinate=True, **kwargs):
    exported, observations = retained
    kwargs.setdefault("release_id", exported["report"]["release_id"])
    if coordinate:
        kwargs.update(source_coordinate_report=exported["report"],
                      expected_source_coordinate_report_sha256=exported["report_sha256"])
    return paired.build_paired_census(observations, agent_id="coordinate-fixture",
        code_identity="fixture:source-transport", model_identity="fixture:no-model", **kwargs)


def replace_artifact(bundle, name, value):
    transport = bundle["coordinate_transport"]
    key = name + "_artifact_sha256"
    old = transport[key]
    row = next(row for row in bundle["artifacts"] if row["artifact_sha256"] == old)
    raw = encoded(value, ordered=name == "report")
    row.update(artifact_sha256=digest(raw), decoded_bytes=len(raw), payload=zlib.compress(raw))
    transport[key] = row["artifact_sha256"]


def artifact_value(bundle, name):
    reference = bundle["coordinate_transport"][name + "_artifact_sha256"]
    row = next(row for row in bundle["artifacts"] if row["artifact_sha256"] == reference)
    return json.loads(paired.decode_artifact(row))


def write_resealed_tables(written, bundle):
    """Adversarial bytes have coherent outer hashes, not trusted source replay."""
    path = Path(written["manifest"]["path"])
    manifest = json.loads(path.read_bytes())
    for kind in paired.TABLE_NAMES:
        entry = manifest["tables"][kind]
        sink = pa.BufferOutputStream()
        pq.write_table(pa.Table.from_pylist(bundle[kind],
            schema=paired.arrow_schemas()[kind]), sink, compression="zstd")
        raw = sink.getvalue().to_pybytes()
        filename = entry["filename"].rsplit("-", 1)[0] + "-" + digest(raw) + ".parquet"
        (path.parent / filename).write_bytes(raw)
        entry.update(filename=filename, path_in_repo=str(Path(entry["path_in_repo"]).parent / filename),
                     sha256=digest(raw), bytes=len(raw))
    manifest["coordinate_transport"] = bundle["coordinate_transport"]
    body = {k: v for k, v in manifest.items() if k not in {"fingerprint", "path_in_repo"}}
    fingerprint = paired._sha(paired._json(body))
    filename = "manifest-" + fingerprint + ".json"
    manifest.update(fingerprint=fingerprint,
                    path_in_repo=str(Path(manifest["path_in_repo"]).parent / filename))
    target = path.parent / filename
    target.write_bytes(paired._json(manifest))
    return target


def test_opt_in_preserves_v2_rows_ids_goals_and_default_schema(retained, tmp_path):
    legacy, portable = build(retained, coordinate=False), build(retained)
    assert legacy["schema_version"] == portable["schema_version"] == paired.SCHEMA
    assert legacy["paired_spans"] == portable["paired_spans"]
    assert legacy["goals"] == portable["goals"]
    assert "coordinate_transport" not in legacy
    assert paired.validate_paired_source_coordinates(legacy) is None
    with pytest.raises(paired.PairedCensusError, match="explicit coordinate"):
        paired.validate_paired_source_coordinates(legacy, expected_report_sha256=retained[0]["report_sha256"])
    written = paired.write_paired_census_bundle(legacy, tmp_path / "v2")
    assert json.loads(Path(written["manifest"]["path"]).read_bytes())["schema"] == paired.MANIFEST_SCHEMA
    assert written["manifest"]["path_in_repo"].startswith(paired.REPO_PREFIX + "/")


def test_one_complete_report_and_exact_original_subset_references(retained):
    bundle = build(retained)
    decoded = paired.validate_paired_source_coordinates(bundle,
        expected_report_sha256=retained[0]["report_sha256"])
    assert decoded == retained[0]
    assert [json.loads(row["source_provenance_json"])["span_index"] for row in decoded["rows"]] == [1, 2]
    assert len(decoded["report"]["spans"]) == 4
    assert sum(row["kind"] == "source_coordinate_report" for row in bundle["artifacts"]) == 1
    report = next(row for row in bundle["artifacts"] if row["kind"] == "source_coordinate_report")
    raw = paired.decode_artifact(report)
    assert raw == encoded(retained[0]["report"], ordered=True)
    assert digest(raw) == bundle["coordinate_transport"]["report_artifact_sha256"]
    assert bundle["coordinate_transport"]["report_sha256"] == retained[0]["report_sha256"]
    assert list(json.loads(raw)["documents"][0]["source_metadata"]) == list(
        retained[0]["report"]["documents"][0]["source_metadata"])


def test_versioned_manifest_roundtrip_exposes_replayed_coordinates(retained, tmp_path):
    bundle = build(retained)
    written = paired.write_paired_census_bundle(bundle, tmp_path / "v3")
    manifest = json.loads(Path(written["manifest"]["path"]).read_bytes())
    assert manifest["schema"] == paired.COORDINATE_MANIFEST_SCHEMA
    assert set(manifest["tables"]) == set(paired.TABLE_NAMES)
    assert all(written[k]["path_in_repo"].startswith(paired.COORDINATE_REPO_PREFIX + "/")
               for k in (*paired.TABLE_NAMES, "manifest"))
    loaded = paired.load_paired_census_bundle(written["manifest"]["path"])
    assert loaded["schema_version"] == paired.SCHEMA
    assert loaded["paired_spans"] == bundle["paired_spans"]
    assert loaded["source_coordinates"] == retained[0]
    assert paired.validate_paired_source_coordinates(loaded,
        expected_report_sha256=retained[0]["report_sha256"]) == retained[0]
    assert loaded["admitted"] is loaded["formalized"] is loaded["enqueued"] is False
    with pytest.raises(paired.PairedCensusError, match="independent"):
        paired.validate_paired_source_coordinates(loaded, expected_report_sha256="0" * 64)


@pytest.mark.parametrize("missing", ["report", "pin"])
def test_opt_in_requires_both_original_report_and_independent_pin(retained, missing):
    kwargs = {"source_coordinate_report": retained[0]["report"],
              "expected_source_coordinate_report_sha256": retained[0]["report_sha256"]}
    kwargs.pop("source_coordinate_report" if missing == "report" else "expected_source_coordinate_report_sha256")
    with pytest.raises(paired.PairedCensusError, match="both required"):
        paired.build_paired_census(retained[1], **kwargs)


@pytest.mark.parametrize("missing", ["one", "all"])
def test_legacy_rows_cannot_acquire_inferred_coordinate_references(retained, missing):
    exported, observations = deepcopy(retained)
    for row in observations[:1] if missing == "one" else observations:
        row.pop("source_provenance_json")
    with pytest.raises(paired.PairedCensusError, match="existing source provenance"):
        build((exported, observations))


def test_coordinate_profile_refuses_empty_observation_population(retained):
    with pytest.raises(paired.PairedCensusError, match="one to 128"):
        build((retained[0], []))


@pytest.mark.parametrize("mismatch", ["default", "explicit", "row", "campaign"])
def test_source_revision_must_match_the_complete_report_release(retained, mismatch):
    exported, observations = deepcopy(retained)
    kwargs = {"source_coordinate_report": exported["report"],
              "expected_source_coordinate_report_sha256": exported["report_sha256"]}
    if mismatch != "default":
        kwargs["release_id"] = "wrong" if mismatch == "explicit" else exported["report"]["release_id"]
    if mismatch == "row":
        observations[0]["release_id"] = "wrong"
    elif mismatch == "campaign":
        observations[0]["batch_observation"] = {"campaign": {"source_revision": "wrong"}}
    with pytest.raises(paired.PairedCensusError, match="revision.*report release"):
        paired.build_paired_census(observations, **kwargs)


@pytest.mark.parametrize("mutation", ["report_pin", "missing_report", "missing_index", "report_kind",
    "index_kind", "duplicate_report", "index_schema", "index_missing_observation", "index_extra_observation",
    "reference_text", "reference_index", "reference_authority"])
def test_invalid_transport_refuses_before_creating_destination(retained, tmp_path, mutation):
    bundle = build(retained)
    transport = bundle["coordinate_transport"]
    if mutation == "report_pin":
        transport["report_sha256"] = "0" * 64
    elif mutation in {"missing_report", "missing_index"}:
        reference = transport[mutation.split("_")[1] + "_artifact_sha256"]
        bundle["artifacts"] = [row for row in bundle["artifacts"] if row["artifact_sha256"] != reference]
    elif mutation in {"report_kind", "index_kind", "duplicate_report"}:
        name = "index" if mutation == "index_kind" else "report"
        row = next(row for row in bundle["artifacts"] if row["artifact_sha256"] == transport[name + "_artifact_sha256"])
        if mutation == "duplicate_report":
            bundle["artifacts"].append(deepcopy(row))
        else:
            row["kind"] = "unrelated"
    else:
        index = artifact_value(bundle, "index")
        identity = next(iter(index["observations"]))
        if mutation == "index_schema":
            index["schema"] = "unknown/v99"
        elif mutation == "index_missing_observation":
            index["observations"].pop(identity)
        elif mutation == "index_extra_observation":
            index["observations"]["0" * 64] = index["observations"][identity]
        else:
            ref = json.loads(index["observations"][identity])
            if mutation == "reference_text":
                ref["source_sha256"] = "0" * 64
            elif mutation == "reference_index":
                ref["span_index"] = 0
            else:
                ref["authority"]["qualified"] = True
            index["observations"][identity] = encoded(ref).decode()
        replace_artifact(bundle, "index", index)
    target = tmp_path / "must-not-exist"
    with pytest.raises(paired.PairedCensusError):
        paired.write_paired_census_bundle(bundle, target)
    assert not target.exists()


@pytest.mark.parametrize("mutation", ["index", "unselected_report_occurrence"])
def test_resealed_tables_and_manifest_cannot_replace_complete_source_replay(retained, tmp_path, mutation):
    bundle = build(retained)
    written = paired.write_paired_census_bundle(bundle, tmp_path / "published")
    index = artifact_value(bundle, "index")
    if mutation == "index":
        index["observations"].pop(next(iter(index["observations"])))
    else:
        report = artifact_value(bundle, "report")
        report["spans"][0]["source_char_end"] += 1  # Not one of the exported occurrences.
        report.pop("source_coordinates_sha256")
        report["source_coordinates_sha256"] = digest(encoded(report))
        pin = ingest.uscode_source_coordinates_sha256(report)
        bundle["coordinate_transport"]["report_sha256"] = pin
        replace_artifact(bundle, "report", report)
        for identity, raw in index["observations"].items():
            reference = json.loads(raw)
            reference["report_sha256"] = pin
            index["observations"][identity] = encoded(reference).decode()
    replace_artifact(bundle, "index", index)
    forged = write_resealed_tables(written, bundle)
    with pytest.raises(paired.PairedCensusError):
        paired.load_paired_census_bundle(forged)


def test_rehashed_source_revision_cannot_inherit_coordinate_transport(retained, tmp_path):
    bundle = build(retained)
    # A valid no-goal bundle isolates the coordinate release guard from the
    # independent repair packet's capture of the original observation ID.
    bundle["goals"] = []
    for span in bundle["paired_spans"]:
        span["goal_ids"] = []
    written = paired.write_paired_census_bundle(bundle, tmp_path / "published")
    assert paired.load_paired_census_bundle(written["manifest"]["path"])["source_coordinates"] == retained[0]
    row = bundle["paired_spans"][0]
    previous = row["observation_id"]
    row["source"]["revision"] = "another-release"
    body = {key: value for key, value in row.items() if key != "observation_id"}
    body["goal_ids"] = []
    row["observation_id"] = paired._sha(paired._json(body))
    index = artifact_value(bundle, "index")
    index["observations"][row["observation_id"]] = index["observations"].pop(previous)
    replace_artifact(bundle, "index", index)
    forged = write_resealed_tables(written, bundle)
    with pytest.raises(paired.PairedCensusError, match="revision.*report release"):
        paired.load_paired_census_bundle(forged)


def test_coordinate_artifact_bound_refuses_without_truncating_source(retained, monkeypatch):
    before = deepcopy(retained[0]["report"])
    monkeypatch.setattr(paired, "MAX_ARTIFACT_BYTES", 64)
    with pytest.raises(paired.PairedCensusError, match="bound"):
        build(retained)
    assert retained[0]["report"] == before
