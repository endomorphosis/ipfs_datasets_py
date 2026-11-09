"""Verified paired payloads retain candidates and explicit source-join limits."""
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_span_adapter as candidates
from ipfs_datasets_py.logic.autoformal import legal_paired_payload_intake_v1 as intake
from ipfs_datasets_py.logic.autoformal import paired_span_census as paired
from tests.unit.logic.autoformal.test_corpus_span_adapter import source_binding
from tests.unit.logic.test_span_cache_paired_feed import (
    build_fixture,
    serialize_fixture,
    source_row,
)


REVISION = "a" * 40


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inputs(tmp_path, *, version=2, rows=None):
    """Create actual typed tables under a pinned repository-shaped directory."""
    bundle = build_fixture(version, rows=rows)
    entry, files, manifest = serialize_fixture(tmp_path / "producer", bundle,
        version=version, one_digest=version == 1)
    repository_root = tmp_path / "retained" / REVISION
    for name, path in files.items():
        destination = repository_root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
    request = {
        "repository_root": repository_root,
        "repository_id": paired.REPOSITORY,
        "revision": REVISION,
        "manifest_path_in_repo": entry["path"],
        "expected_manifest_sha256": sha(files[entry["path"]].read_bytes()),
    }
    return request, bundle, manifest


def replay(report, request, **kwargs):
    return intake.validate_paired_payload_intake(report,
        expected_report_sha256=intake.paired_payload_report_sha256(report),
        **request, **kwargs)


@pytest.mark.parametrize("version", [1, 2])
def test_verified_tables_preserve_all_rows_and_opaque_output_routes(tmp_path, version):
    first = source_row("first")
    first["model_formal_outputs"] *= 2
    # Keep the producer comparison agreeing: the legacy fixture conversion does
    # not regenerate disagreement packets after changing observation identities.
    # These rules populate both direct and canonical compiler output routes.
    first["compiler_result"]["rules"] *= 2
    request, bundle, _ = inputs(tmp_path, version=version,
        rows=[first, source_row("second", guided=False)])
    report = intake.prepare_paired_payload_intake(**request)
    assert replay(report, request) == report
    assert report["counts"]["physical_rows"] == 2
    assert report["counts"]["candidate_unbound"] == 2
    assert report["counts"]["candidate_bound"] == report["counts"]["adapter_rejected"] == 0
    assert len(report["rows"]) == 2
    interpretation_count = 0
    for ordinal, (result, original) in enumerate(zip(report["rows"], bundle["paired_spans"])):
        raw = paired._json(original)
        assert result["row_ordinal"] == ordinal
        assert result["observation_id"] == original["observation_id"]
        assert result["derived_row_json"].encode("utf-8") == raw
        assert result["row_sha256"] == sha(raw)
        assert result["disposition"] == "candidate_unbound"
        assert result["error"] is None
        candidate = result["candidate"]
        assert candidate == candidates.adapt_paired_span_bytes(raw, expected_row_sha256=sha(raw))
        assert candidates.validate_span_candidate(candidate, expected_row_sha256=sha(raw)) == candidate
        assert candidate["source_binding"] is None
        assert "source_occurrence_unresolved" in {issue["kind"] for issue in candidate["issues"]}
        assert candidate["admitted"] is candidate["formalized"] is candidate["source_semantics_verified"] is False
        for route, key in candidates.ROUTES:
            retained = [item["formal_output"] for item in candidate["interpretations"]
                        if item["route"] == route + "." + key]
            assert retained == original[route][key]
        interpretation_count += len(candidate["interpretations"])
    assert report["counts"]["interpretations"] == interpretation_count
    assert report["source_pins"]
    assert report["authority"] and all(value is False for value in report["authority"].values())


def test_unicode_physical_source_binding_requires_complete_replay(tmp_path):
    request, bundle, _ = inputs(tmp_path)
    binding = source_binding(bundle["paired_spans"][0])
    bindings = [binding]
    original_bindings = deepcopy(bindings)
    report = intake.prepare_paired_payload_intake(**request, source_bindings=bindings)
    assert bindings == original_bindings
    assert replay(report, request, source_bindings=bindings) == report
    assert report["counts"]["candidate_bound"] == 1
    assert report["counts"]["candidate_unbound"] == report["counts"]["adapter_rejected"] == 0
    result = report["rows"][0]
    assert result["disposition"] == "candidate_bound"
    candidate = result["candidate"]
    assert candidates.validate_span_candidate(candidate,
        expected_row_sha256=result["row_sha256"], source_binding=binding) == candidate
    assert candidate["source_binding"]["source_occurrence"] == binding["source_occurrence"]
    assert candidate["source_binding"]["source_authenticity_verified"] is False
    assert "extracted_text" not in candidate["source_binding"]
    with pytest.raises(ValueError):
        replay(report, request)
    changed = deepcopy(bindings)
    changed[0]["extracted_text"] += "changed"
    with pytest.raises(ValueError):
        replay(report, request, source_bindings=changed)


def test_repeated_source_text_never_selects_an_occurrence_implicitly(tmp_path):
    request, bundle, _ = inputs(tmp_path)
    row = bundle["paired_spans"][0]
    first = source_binding(row, duplicate=True)
    second = source_binding(row, duplicate=True, second=True)
    unbound = intake.prepare_paired_payload_intake(**request)
    one = intake.prepare_paired_payload_intake(**request, source_bindings=[first])
    two = intake.prepare_paired_payload_intake(**request, source_bindings=[second])
    assert unbound["rows"][0]["candidate"]["source_binding"] is None
    assert first["source_version"] == second["source_version"]
    assert first["source_occurrence"]["span_cid"] == second["source_occurrence"]["span_cid"]
    assert one["rows"][0]["candidate"]["record_cid"] != two["rows"][0]["candidate"]["record_cid"]
    assert replay(one, request, source_bindings=[first]) == one
    assert replay(two, request, source_bindings=[second]) == two
    with pytest.raises(ValueError):
        replay(one, request, source_bindings=[second])


def test_missing_context_and_mixed_binding_population_are_retained(tmp_path):
    request, bundle, _ = inputs(tmp_path,
        rows=[source_row("first"), source_row("second")])
    bindings = [source_binding(bundle["paired_spans"][0], availability="required_unavailable"), None]
    report = intake.prepare_paired_payload_intake(**request, source_bindings=bindings)
    assert replay(report, request, source_bindings=bindings) == report
    assert [row["disposition"] for row in report["rows"]] == ["candidate_bound", "candidate_unbound"]
    assert "context_required_unavailable" in {
        issue["kind"] for issue in report["rows"][0]["candidate"]["issues"]}
    assert report["counts"]["physical_rows"] == 2
    assert report["counts"]["candidate_bound"] == report["counts"]["candidate_unbound"] == 1


def test_adapter_output_coverage_failure_preserves_row_and_later_candidates(tmp_path):
    too_many = source_row("too-many", guided=False)
    too_many["compiler_result"]["rules"] *= 129
    request, bundle, _ = inputs(tmp_path,
        rows=[too_many, source_row("supported", guided=False)])
    report = intake.prepare_paired_payload_intake(**request)
    assert replay(report, request) == report
    assert report["counts"]["physical_rows"] == 2
    assert report["counts"]["adapter_rejected"] == report["counts"]["candidate_unbound"] == 1
    assert [row["disposition"] for row in report["rows"]] == ["adapter_rejected", "candidate_unbound"]
    rejected = report["rows"][0]
    assert rejected["candidate"] is None and rejected["error"] is not None
    assert rejected["derived_row_json"].encode() == paired._json(bundle["paired_spans"][0])
    assert rejected["observation_id"] == bundle["paired_spans"][0]["observation_id"]
    assert len(json.loads(rejected["derived_row_json"])["compiler"]["formal_outputs"]) == 129
    assert report["counts"]["interpretations"] == len(report["rows"][1]["candidate"]["interpretations"])


@pytest.mark.parametrize("mutation", ["omit_row", "counts", "disposition", "candidate", "authority", "producer"])
def test_rehashing_report_changes_does_not_replace_full_replay(tmp_path, mutation):
    request, _, _ = inputs(tmp_path)
    report = intake.prepare_paired_payload_intake(**request)
    forged = deepcopy(report)
    if mutation == "omit_row":
        forged["rows"] = []
    elif mutation == "counts":
        forged["counts"]["physical_rows"] += 1
    elif mutation == "disposition":
        forged["rows"][0]["disposition"] = "candidate_bound"
    elif mutation == "candidate":
        forged["rows"][0]["candidate"]["admitted"] = True
    elif mutation == "authority":
        forged["authority"][next(iter(forged["authority"]))] = True
    else:
        forged["source_pins"][next(iter(forged["source_pins"]))] = "0" * 64
    with pytest.raises(ValueError):
        replay(forged, request)


def test_supplied_report_commitment_is_independent(tmp_path):
    request, _, _ = inputs(tmp_path)
    report = intake.prepare_paired_payload_intake(**request)
    with pytest.raises(ValueError):
        intake.validate_paired_payload_intake(report, expected_report_sha256="0" * 64, **request)


@pytest.mark.parametrize("kind", ["paired_spans", "goals", "artifacts"])
def test_changed_table_bytes_refuse_whole_bundle_before_candidate_use(tmp_path, kind):
    request, _, manifest = inputs(tmp_path)
    path = request["repository_root"] / manifest["tables"][kind]["path_in_repo"]
    raw = path.read_bytes()
    path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(ValueError):
        intake.prepare_paired_payload_intake(**request)


@pytest.mark.parametrize("bindings", [[], [None, None], {}])
def test_binding_population_shape_is_explicit(tmp_path, bindings):
    request, _, _ = inputs(tmp_path)
    with pytest.raises(ValueError):
        intake.prepare_paired_payload_intake(**request, source_bindings=bindings)


def test_rejected_binding_identity_is_retained_when_error_messages_match(tmp_path):
    request, _, _ = inputs(tmp_path)
    first_bindings, second_bindings = [{}], [{"other": 1}]
    first = intake.prepare_paired_payload_intake(**request, source_bindings=first_bindings)
    second = intake.prepare_paired_payload_intake(**request, source_bindings=second_bindings)
    assert first["rows"][0]["disposition"] == second["rows"][0]["disposition"] == "adapter_rejected"
    assert first["rows"][0]["error"] == second["rows"][0]["error"]
    assert first["rows"][0]["candidate"] is second["rows"][0]["candidate"] is None
    assert first["source_bindings_sha256"] != second["source_bindings_sha256"]
    assert intake.paired_payload_report_sha256(first) != intake.paired_payload_report_sha256(second)
    assert replay(first, request, source_bindings=first_bindings) == first
    assert replay(second, request, source_bindings=second_bindings) == second
    with pytest.raises(ValueError):
        replay(first, request, source_bindings=second_bindings)


def test_lowered_row_and_report_budgets_fail_without_partial_population(tmp_path):
    request, _, _ = inputs(tmp_path, rows=[source_row("first"), source_row("second")])
    with pytest.raises(ValueError):
        intake.prepare_paired_payload_intake(**request, limits={"max_rows": 1})
    with pytest.raises(ValueError):
        intake.prepare_paired_payload_intake(**request, limits={"max_report_bytes": 1})
