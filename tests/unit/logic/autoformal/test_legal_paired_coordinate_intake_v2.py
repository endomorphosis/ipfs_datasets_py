"""Real coordinate/Arrow codecs; authored sources and no DB or model execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_paired_payload_intake_v1 as intake
from ipfs_datasets_py.logic.autoformal import paired_span_census as paired
from ipfs_datasets_py.logic.autoformal import span_cache
from ipfs_datasets_py.logic.autoformal import uscode_ingest as ingest
from tests.unit.logic.autoformal.test_corpus_span_adapter import source_binding
from tests.unit.logic.autoformal.test_legal_paired_payload_intake_v1 import inputs as legacy_inputs
from tests.unit.logic.test_span_cache_paired_feed import source_row


MARKER = "OPAQUE_TARGET_IS_NOT_A_SOURCE_CONTEXT"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def build_coordinate_payload(tmp_path, documents=None, selected_indices=(1, 3), *, compiler_rule=None):
    """Use the existing inventory/reference/Arrow owners, without a source DB."""
    # Equal text at different original positions remains two physical sources.
    if documents is None:
        documents = [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551",
            "text": "  Ω agency shall retain records.\r\n Café may file!  "} for _ in range(2)]
    report = ingest.inventory_uscode_source_coordinates(documents,
        query="authored-coordinate-intake", release_id="authored-source-release")
    pin = ingest.uscode_source_coordinates_sha256(report)
    _, spans = span_cache._coordinate_replay(report, pin)
    observations, references = [], []
    for index in selected_indices:
        source = spans[index]
        reference = span_cache._coordinate_wire(span_cache._coordinate_reference(report, spans, pin, index),
            span_cache.MAX_SOURCE_COORDINATE_REFERENCE_BYTES).decode("utf-8")
        row = source_row(source["source_span_id"], text=source["text"],
                         release=report["release_id"], guided=False)
        row.update(legal_id=source["legal_id"], source_provenance_json=reference)
        if compiler_rule is None:
            row["compiler_result"]["rules"][0]["actor"] = MARKER
        else:
            # Configure the authored observation before the producer captures it.
            row["compiler_result"]["rules"] = [deepcopy(compiler_rule)]
        observations.append(row)
        references.append(reference)
    bundle = paired.build_paired_census(observations, agent_id="coordinate-intake",
        code_identity="authored:coordinate-intake", model_identity="diagnostic:test",
        release_id=report["release_id"], source_coordinate_report=report,
        expected_source_coordinate_report_sha256=pin)
    written = paired.write_paired_census_bundle(bundle, tmp_path / "producer")
    root = (tmp_path / "retained" / ("a" * 40)).absolute()
    for kind in (*paired.TABLE_NAMES, "manifest"):
        entry = written[kind]
        destination = root / entry["path_in_repo"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(Path(entry["path"]).read_bytes())
    request = {"repository_root": root, "repository_id": paired.REPOSITORY, "revision": "a" * 40,
        "manifest_path_in_repo": written["manifest"]["path_in_repo"],
        "expected_manifest_sha256": written["manifest"]["sha256"],
        "expected_source_coordinate_report_sha256": pin}
    return {"request": request, "bundle": bundle, "report": report, "pin": pin, "references": references,
            "documents": documents, "observations": observations, "written": written}


@pytest.fixture
def coordinate_payload(tmp_path):
    return build_coordinate_payload(tmp_path)


def replay(report, request, **kwargs):
    return intake.validate_paired_payload_intake_v2(report,
        expected_report_sha256=intake.paired_payload_report_sha256(report), **request, **kwargs)


def test_coordinate_payload_retains_complete_exact_report_once_and_original_indices(coordinate_payload):
    case = coordinate_payload
    report = intake.prepare_paired_payload_intake_v2(**case["request"])
    assert replay(report, case["request"]) == report
    assert report["schema"] == intake.SCHEMA_V2
    carrier = report["source_coordinates"]
    assert set(carrier) == {"report_raw_utf8", "report_bytes", "report_artifact_sha256", "report_sha256"}
    raw = carrier["report_raw_utf8"].encode("utf-8")
    artifact = next(row for row in case["bundle"]["artifacts"] if row["kind"] == "source_coordinate_report")
    assert raw == paired.decode_artifact(artifact)
    assert carrier["report_bytes"] == len(raw)
    assert carrier["report_artifact_sha256"] == sha(raw) == artifact["artifact_sha256"]
    assert carrier["report_sha256"] == case["pin"] != carrier["report_artifact_sha256"]
    # Outer report canonicalization must not reorder source metadata internally.
    restored = json.loads(intake._wire(report))
    assert restored["source_coordinates"]["report_raw_utf8"].encode("utf-8") == raw
    assert raw.index(b'z_metadata') < raw.index(b'a_metadata')
    assert MARKER not in carrier["report_raw_utf8"]
    assert [row["source_coordinate_span_index"] for row in report["rows"]] == [1, 3]
    assert [row["source_provenance_json"] for row in report["rows"]] == case["references"]
    assert len(report["rows"]) == 2 and len(case["report"]["spans"]) == 4
    assert all("report_raw_utf8" not in row for row in report["rows"])
    sources = [json.loads(row["derived_row_json"])["source"] for row in report["rows"]]
    assert sources[0]["text"] == sources[1]["text"]
    assert sources[0]["span_id"] != sources[1]["span_id"]
    rows = [{"source_span_id": source["span_id"], "text": source["text"], "legal_id": source["legal_id"],
             "source_provenance_json": row["source_provenance_json"]} for source, row in zip(sources, report["rows"])]
    assert span_cache.validate_source_coordinate_rows(json.loads(carrier["report_raw_utf8"]), rows,
        expected_report_sha256=carrier["report_sha256"]) == [1, 3]
    assert report["source_binding_population_supplied"] is False
    assert report["source_occurrence_search_performed"] is False
    assert all(row["candidate"]["source_binding"] is None for row in report["rows"])
    assert all(value is False for value in report["authority"].values())


def test_coordinate_payload_keeps_explicit_corpus_binding_separate(coordinate_payload):
    case = coordinate_payload
    binding = source_binding(case["bundle"]["paired_spans"][0])
    report = intake.prepare_paired_payload_intake_v2(**case["request"], source_bindings=[binding, None])
    assert replay(report, case["request"], source_bindings=[binding, None]) == report
    assert [row["disposition"] for row in report["rows"]] == ["candidate_bound", "candidate_unbound"]
    assert report["rows"][0]["candidate"]["source_binding"]["source_authenticity_verified"] is False
    assert [row["source_provenance_json"] for row in report["rows"]] == case["references"]
    with pytest.raises(ValueError, match="full input replay"):
        replay(report, case["request"])


def test_legacy_payload_refuses_v3_instead_of_dropping_coordinate_carrier(coordinate_payload):
    request = dict(coordinate_payload["request"])
    request.pop("expected_source_coordinate_report_sha256")
    with pytest.raises(ValueError, match="payload profile"):
        intake.prepare_paired_payload_intake(**request)


@pytest.mark.parametrize("version", [1, 2])
def test_coordinate_payload_refuses_legacy_bundles(tmp_path, version):
    request, _, _ = legacy_inputs(tmp_path, version=version)
    with pytest.raises(ValueError, match="payload profile"):
        intake.prepare_paired_payload_intake_v2(**request, expected_source_coordinate_report_sha256="a" * 64)


@pytest.mark.parametrize("pin", ["expected_manifest_sha256", "expected_source_coordinate_report_sha256"])
def test_coordinate_payload_requires_independent_original_pins(coordinate_payload, pin):
    request = dict(coordinate_payload["request"])
    request[pin] = "0" * 64
    with pytest.raises(ValueError):
        intake.prepare_paired_payload_intake_v2(**request)


@pytest.mark.parametrize("value", [None, True, "A" * 64, "a" * 63])
def test_coordinate_payload_pin_shape_refuses_before_loading(coordinate_payload, monkeypatch, value):
    from ipfs_datasets_py.logic.autoformal import span_cache_feed
    monkeypatch.setattr(span_cache_feed, "load_paired_payload", lambda *a, **k: pytest.fail("invalid pin reached loader"))
    request = dict(coordinate_payload["request"])
    request["expected_source_coordinate_report_sha256"] = value
    with pytest.raises(ValueError, match="source coordinate report SHA256"):
        intake.prepare_paired_payload_intake_v2(**request)


@pytest.mark.parametrize("damage", ["drop_report", "report_text", "artifact_hash", "report_pin", "index", "reference", "drop_row", "authority"])
def test_rehashed_coordinate_payload_cannot_replace_complete_replay(coordinate_payload, damage):
    case = coordinate_payload
    report = intake.prepare_paired_payload_intake_v2(**case["request"])
    if damage == "drop_report": report.pop("source_coordinates")
    elif damage == "report_text": report["source_coordinates"]["report_raw_utf8"] += " "
    elif damage == "artifact_hash": report["source_coordinates"]["report_artifact_sha256"] = "0" * 64
    elif damage == "report_pin": report["source_coordinates"]["report_sha256"] = "0" * 64
    elif damage == "index": report["rows"][0]["source_coordinate_span_index"] = 0
    elif damage == "reference": report["rows"][0]["source_provenance_json"] = report["rows"][1]["source_provenance_json"]
    elif damage == "drop_row": report["rows"].pop()
    else: report["authority"]["source_semantics_verified"] = True
    with pytest.raises(ValueError, match="full input replay"):
        replay(report, case["request"])


@pytest.mark.parametrize("limit", ["max_rows", "max_report_bytes"])
def test_coordinate_payload_bounds_refuse_complete_population(coordinate_payload, limit):
    with pytest.raises(ValueError):
        intake.prepare_paired_payload_intake_v2(**coordinate_payload["request"], limits={limit: 1})


def test_coordinate_payload_result_is_detached(coordinate_payload):
    case = coordinate_payload
    before = deepcopy(case["report"])
    result = intake.prepare_paired_payload_intake_v2(**case["request"])
    result["rows"][0]["source_provenance_json"] = "changed"
    result["source_coordinates"]["report_raw_utf8"] = "changed"
    assert case["report"] == before
    fresh = intake.prepare_paired_payload_intake_v2(**case["request"])
    assert fresh["rows"][0]["source_provenance_json"] == case["references"][0]
