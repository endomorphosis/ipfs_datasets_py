"""Fenced metadata orchestration; injected workers never run D inference.

Temporary native catalogs and real immutable Parquet validation are used.
Formula strings below are authored fixtures, not model/semantic/Lean evidence.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pyarrow as pa
import pytest

from ipfs_datasets_py.logic.autoformal import span_cache_exchange as exchange
from ipfs_datasets_py.logic.autoformal import span_cache_fenced_ingest as ingest
from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache, _sha
from ipfs_datasets_py.logic.autoformal.span_cache_claims import SpanClaimError

HASHES = {"fixture/declared-compiler.py": "b"*64}
CODE = "sha256:" + "c"*64
REV = "hub:" + "a"*40
TEXT = "Authored fixture source, never parser inference."


class MetadataPool:
    def map(self, function, values):
        return map(function, values)


def worker(item):
    return {**item, "agrees": True, "rule": {"modality": "O", "actor": "fixture-agent", "action": "observe"},
            "decompiled": "Authored diagnostic rendering.", "repair": {}, "reason": "fixture-only",
            "compiler_result": {"status": "abstain", "rule": {}}, "compiler_status": "abstain",
            "model_identity": "fixture:no-model", "family_evidence": {"fol": "forall x. P(x)"},
            "goals": [{"id": "fixture-goal", "body": "retained full observation "*7000}]}


def manifest():
    return {"schema": ingest.SOURCE_SCHEMA, "corpus_id": "fixture:corpus", "release_id": "fixture-release",
            "source_revision": REV, "spans": [{"source_span_id": "span-a", "legal_id": "fixture:law",
                "source_sha256": _sha(TEXT), "expected_binding": None}]}


@pytest.fixture
def owner(tmp_path):
    cache = SpanCache(tmp_path/"owner.duckdb")
    cache._db.execute("SET threads=1")
    cache._set_meta("dataset_id", "fixture:corpus")
    cache.enqueue([{"source_span_id": "span-a", "legal_id": "fixture:law", "text": TEXT}])
    try:
        yield cache
    finally:
        cache.close()


def metadata_stager(destination, release="fixture-release", code=CODE, hashes=HASHES):
    def stage(rows):
        assert len(rows) == 1
        item = {**rows[0], "release_id": release, "code_identity": code, "compiler_path_hashes": hashes}
        schema = exchange._schema(exchange.CENSUS_COLUMNS)
        census = {field.name: (False if pa.types.is_boolean(field.type) else None if pa.types.is_floating(field.type) or pa.types.is_integer(field.type) else "") for field in schema}
        census.update(schema_version=exchange.CENSUS_SCHEMA, record_kind="span",
            repository_id="justicedao/uscode-autoformal-span-cache", agent_id="fixture-owner",
            source_span_id=item["source_span_id"], legal_id=item["legal_id"], source_text=item["text"],
            source_text_sha256=_sha(item["text"]), input_json=exchange._json(item), comparison_json="{}",
            comparison_provenance_json="{}", admitted=False, formalized=False, wrote_compiler=False)
        census.update(exchange._explicit_outputs(item, ""))
        census["census_sha256"] = exchange._row_hash(census)
        fingerprint = exchange._fingerprint([census], [])
        receipt = exchange._save_bundle({"census_rows": [census], "goal_rows": []},
            Path(destination)/("census-"+fingerprint+".parquet"), Path(destination)/("goals-"+fingerprint+".parquet"),
            repository_id="justicedao/uscode-autoformal-span-cache", agent_id="fixture-owner")
        return {"manifests": [receipt["manifest"]["path"]]}
    return stage


def run(cache, tmp_path, *, source_manifest=None, **kwargs):
    destination = tmp_path/"exchange"
    defaults = dict(worker_pool=MetadataPool(), compile_worker=worker,
        stage_exchange=metadata_stager(destination), exchange_dir=destination,
        code_identity=CODE, path_hashes=HASHES, source_guard=lambda: dict(HASHES))
    defaults.update(kwargs)
    return ingest.drain_fenced_manifest(cache, source_manifest or manifest(), **defaults)


@pytest.mark.parametrize("change", [
    lambda m: m.pop("source_revision"),
    lambda m: m.update(source_revision="not-a-pinned-revision"),
    lambda m: m["spans"].append(dict(m["spans"][0])),
    lambda m: m["spans"][0].update(source_sha256="wrong"),
    lambda m: m["spans"][0].update(extra_field=True),
    lambda m: m["spans"][0].update(expected_binding={"source_revision": REV}),
])
def test_closed_source_manifest_refuses_missing_or_ambiguous_identity(change):
    value = manifest()
    change(value)
    with pytest.raises((ingest.FencedIngestError, SpanClaimError)):
        ingest.validate_source_manifest(value)


@pytest.mark.parametrize("field", ["source_revision", "source_span_id", "source_sha256"])
def test_source_manifest_loader_rejects_duplicate_json_keys_even_with_equal_values(tmp_path, field):
    value = manifest()
    raw = json.dumps(value)
    field_value = value.get(field, value["spans"][0].get(field))
    entry = json.dumps(field)+": "+json.dumps(field_value)
    assert entry in raw
    path = tmp_path/"source-manifest.json"
    path.write_text(raw.replace(entry, entry+", "+entry, 1))
    with pytest.raises(ingest.FencedIngestError, match="duplicate source manifest JSON key"):
        ingest.load_source_manifest(path)


def test_source_manifest_reference_retains_exact_bounded_bytes_not_only_logical_identity(tmp_path):
    raw = json.dumps(manifest(), indent=2).encode("utf-8")
    path = tmp_path/"source-manifest.json"
    path.write_bytes(raw)
    loaded, ref = ingest.load_source_manifest(path)
    assert loaded == manifest()
    assert ref == {"path": str(path.resolve()), "bytes": len(raw), "sha256": ingest.hashlib.sha256(raw).hexdigest()}
    assert ingest.MAX_MANIFEST_BYTES == 16*1024*1024


def test_whole_extra_evidence_is_staged_before_bounded_fenced_completion(owner, tmp_path):
    before_modules = set(sys.modules)
    report = run(owner, tmp_path)
    assert report["processed"] == 1
    assert report["qualified"] is False
    completion = report["completions"][0]
    raw = Path(completion["worker_output"]["path"]).read_bytes()
    assert len(raw) > ingest.MAX_CONTROL_BYTES
    observation = json.loads(raw)
    assert observation["family_evidence"] == worker({})["family_evidence"]
    assert observation["goals"] == worker({})["goals"]
    row = owner._db.execute("SELECT result_json FROM span_claim_results").fetchone()[0]
    saved = json.loads(row)
    assert saved["rule"] == observation["rule"]
    assert saved["decompiled"] == observation["decompiled"]
    assert saved["agrees"] is False  # no independent model qualification
    assert len(ingest.encoded(saved, ingest.MAX_CONTROL_BYTES)) < ingest.MAX_CONTROL_BYTES
    assert owner.stats()["gaps"] == 1
    assert owner.stats()["sealed"] == 0
    for module in ("ipfs_datasets_py.logic.legal_ir.canonical_compiler", "ipfs_datasets_py.logic.deontic.utils.deontic_parser"):
        assert module not in set(sys.modules)-before_modules


def test_legacy_shaped_worker_omissions_are_enriched_with_exact_owner_binding(owner, tmp_path):
    original = []
    def legacy_shaped(item):
        result = worker(item)
        result.pop("source_revision")
        result.pop("source_sha256")
        result["source_text_sha256"] = _sha(item["text"])
        original.append(dict(result))
        return result
    report = run(owner, tmp_path, compile_worker=legacy_shaped)
    completion = report["completions"][0]
    retained = json.loads(Path(completion["worker_output"]["path"]).read_text())
    assert all(retained[key] == value for key, value in original[0].items())
    assert retained["source_revision"] == REV and retained["source_sha256"] == _sha(TEXT)
    assert retained["fenced_source_binding"] == {"schema": "span-cache-fenced-ingest-source-binding/v1",
        "origin": "native_fenced_claim", "source_span_id": "span-a", "source_revision": REV,
        "source_sha256": _sha(TEXT), "legal_id": "fixture:law", **ingest._FALSE}
    bundle = exchange.load_exchange_bundle(completion["exchange_manifests"][0]["path"])
    assert json.loads(bundle["census_rows"][0]["input_json"]) == {
        **retained, "release_id": "fixture-release", "code_identity": CODE, "compiler_path_hashes": HASHES}


@pytest.mark.parametrize("conflict", [
    {"source_revision": "hub:"+"e"*40},
    {"source_sha256": "e"*64},
    {"fenced_source_binding": {"origin": "worker-supplied-other-source"}},
])
def test_worker_source_binding_conflicts_are_refused_without_overwriting_evidence(owner, tmp_path, conflict):
    with pytest.raises(ingest.FencedIngestError, match="source revision differs|source digest differs|source provenance"):
        run(owner, tmp_path, compile_worker=lambda item: {**worker(item), **conflict})
    assert owner._db.execute("SELECT count(*) FROM span_claim_results").fetchone()[0] == 0
    assert owner._db.execute("SELECT status FROM span_cache").fetchone()[0] == "pending"


def test_current_fenced_receipts_resume_without_running_worker_or_stager(owner, tmp_path):
    run(owner, tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("resumed completed row invoked another producer")
    result = run(owner, tmp_path, compile_worker=forbidden, stage_exchange=forbidden)
    assert result["processed"] == 0 and result["resumed"] == 1 and result["held"] == []


def test_result_row_without_exact_native_operation_receipt_is_held(owner, tmp_path):
    first = run(owner, tmp_path)
    operation_id = first["completions"][0]["operation_id"]
    owner._db.execute("DELETE FROM span_claim_operations WHERE operation_id=?", [operation_id])
    result = run(owner, tmp_path)
    assert result["resumed"] == result["processed"] == 0
    assert result["held"][0]["reason"] == "terminal_row_requires_explicit_owner_reconciliation"
    assert owner._db.execute("SELECT count(*) FROM span_claim_results").fetchone()[0] == 1


def test_changed_staged_bytes_prevent_resume(owner, tmp_path):
    first = run(owner, tmp_path)
    Path(first["completions"][0]["worker_output"]["path"]).write_text("changed bytes")
    with pytest.raises(ingest.FencedIngestError, match="immutable bytes changed"):
        run(owner, tmp_path)


def test_legacy_terminal_or_changed_compiler_identity_is_held_not_unsealed(owner, tmp_path):
    value = manifest()
    binding = {"source_span_id": "span-a", "source_revision": REV, "source_sha256": _sha(TEXT), "expected_binding": None}
    owner.fenced_claims().bind_sources_fenced("fixture:legacy-terminal-binding", [binding])
    value["spans"][0]["expected_binding"] = {"source_revision": REV, "source_sha256": _sha(TEXT)}
    owner._db.execute("UPDATE span_cache SET status='gap',code_identity=?", [CODE])
    held = run(owner, tmp_path, source_manifest=value)
    assert held["processed"] == 0 and held["held"][0]["reason"] == "terminal_row_requires_explicit_owner_reconciliation"
    assert owner.stats()["gaps"] == 1


def test_changed_compiler_identity_never_reopens_completed_fenced_row(owner, tmp_path):
    run(owner, tmp_path)
    result = run(owner, tmp_path, code_identity="sha256:"+"d"*64)
    assert result["processed"] == 0 and result["resumed"] == 0
    assert result["held"][0]["reason"] == "terminal_row_requires_explicit_owner_reconciliation"
    assert owner._db.execute("SELECT count(*) FROM span_claim_results").fetchone()[0] == 1


def test_owner_restart_resumes_current_source_and_exact_staged_receipts(owner, tmp_path):
    run(owner, tmp_path)
    old_generation = owner.fenced_claims().owner_generation
    owner.close()
    restarted = SpanCache(tmp_path/"owner.duckdb")
    restarted._db.execute("SET threads=1")
    try:
        result = run(restarted, tmp_path)
        assert restarted.fenced_claims().owner_generation > old_generation
        assert result["resumed"] == 1 and result["processed"] == 0 and result["held"] == []
    finally:
        restarted.close()


def test_resume_selects_exact_current_result_before_bounded_history_limit(owner, tmp_path):
    first = run(owner, tmp_path)
    operation = first["completions"][0]["operation_id"]
    original = json.loads(owner._db.execute("SELECT result_json FROM span_claim_results WHERE operation_id=?", [operation]).fetchone()[0])
    control = owner.fenced_claims()
    prior = {"source_revision": REV, "source_sha256": _sha(TEXT)}
    for index in range(70):
        revision = "sha256:"+_sha("authored metadata history "+str(index))
        control.bind_sources_fenced("zz:history:bind:"+str(index), [{"source_span_id": "span-a",
            "source_revision": revision, "source_sha256": _sha(TEXT), "expected_binding": prior}])
        lease = control.claim_batch_fenced("zz:history:claim:"+str(index), "fixture:history", ["span-a"])["claims"][0]
        row = {"claim": lease, "agrees": False, "rule": {"fixture_history": index},
               "decompiled": "Authored history rendering "+str(index), "repair": {"fixture_history": index},
               "reason": "authored private metadata fixture"}
        control.complete_claimed_fenced("zz:history:complete:"+str(index), [row], code_identity=CODE, path_hashes=HASHES)
        prior = {"source_revision": revision, "source_sha256": _sha(TEXT)}
    control.bind_sources_fenced("aa:restore:bind", [{"source_span_id": "span-a", "source_revision": REV,
        "source_sha256": _sha(TEXT), "expected_binding": prior}])
    lease = control.claim_batch_fenced("aa:restore:claim", "fixture:restore", ["span-a"])["claims"][0]
    control.complete_claimed_fenced("aa:restore:complete", [{**original, "claim": lease}], code_identity=CODE, path_hashes=HASHES)
    # Both current matching receipts sort below 70 real, unrelated histories.
    # Selection must filter in SQL before LIMIT64, without fetching that history.
    assert owner._db.execute("SELECT count(*) FROM span_claim_results").fetchone()[0] == 72
    def forbidden(*args, **kwargs):
        pytest.fail("exact current history was hidden by an arbitrary operation order")
    resumed = run(owner, tmp_path, compile_worker=forbidden, stage_exchange=forbidden)
    assert resumed["resumed"] == 1 and resumed["processed"] == 0 and resumed["held"] == []


@pytest.mark.parametrize("binding_state", ["missing", "explicit_prior"])
def test_terminal_resume_requires_current_binding_equal_desired_not_only_expected(owner, tmp_path, binding_state):
    run(owner, tmp_path)
    value = manifest()
    if binding_state == "missing":
        owner._db.execute("DELETE FROM span_source_bindings")
    else:
        prior = "hub:"+"e"*40
        owner._db.execute("UPDATE span_source_bindings SET source_revision=?", [prior])
        value["spans"][0]["expected_binding"] = {"source_revision": prior, "source_sha256": _sha(TEXT)}
    before = owner._db.execute("SELECT count(*) FROM span_claim_operations").fetchone()[0]
    result = run(owner, tmp_path, source_manifest=value)
    assert result["processed"] == result["resumed"] == 0
    assert result["held"][0]["reason"] == "terminal_source_binding_drift"
    assert owner._db.execute("SELECT count(*) FROM span_claim_operations").fetchone()[0] == before
    assert owner._db.execute("SELECT status FROM span_cache").fetchone()[0] == "gap"


def two_span_manifest(owner):
    owner.enqueue([{"source_span_id": "span-b", "legal_id": "fixture:law-b", "text": TEXT+" Second."}])
    value = manifest()
    value["spans"].append({"source_span_id": "span-b", "legal_id": "fixture:law-b",
                           "source_sha256": _sha(TEXT+" Second."), "expected_binding": None})
    return value


def test_bounded_scan_returns_explicit_cursor_and_does_not_skip_held_evidence(owner, tmp_path):
    value = two_span_manifest(owner)
    owner._db.execute("UPDATE span_cache SET status='gap' WHERE source_span_id='span-a'")
    first = run(owner, tmp_path, source_manifest=value, max_examined=1)
    assert first["examined"] == 1 and first["processed"] == 0
    assert first["next_manifest_index"] == 1 and first["remaining_manifest_rows"] == 1
    assert first["held"][0]["source_span_id"] == "span-a"
    second = run(owner, tmp_path, source_manifest=value, start_index=first["next_manifest_index"])
    assert second["examined"] == 1 and second["processed"] == 1
    assert second["next_manifest_index"] is None and second["remaining_manifest_rows"] == 0
    assert owner._db.execute("SELECT status FROM span_cache WHERE source_span_id='span-a'").fetchone()[0] == "gap"


def test_partial_batch_failure_resumes_only_pending_span_with_original_bind_operations(owner, tmp_path):
    value = two_span_manifest(owner)
    calls = []
    def interrupted(item):
        calls.append(item["source_span_id"])
        if item["source_span_id"] == "span-b":
            raise KeyboardInterrupt("authored interruption after first commit")
        return worker(item)
    with pytest.raises(KeyboardInterrupt, match="first commit"):
        run(owner, tmp_path, source_manifest=value, compile_worker=interrupted, batch_size=2)
    assert owner._db.execute("SELECT status FROM span_cache WHERE source_span_id='span-b'").fetchone()[0] == "pending"
    calls.clear()
    def capture(item):
        calls.append(item["source_span_id"])
        return worker(item)
    result = run(owner, tmp_path, source_manifest=value, compile_worker=capture)
    assert calls == ["span-b"] and result["processed"] == result["resumed"] == 1
    assert owner._db.execute("SELECT count(*) FROM span_claim_operations WHERE operation_id LIKE 'fenced-ingest:bind:%'").fetchone()[0] == 2


def test_missing_source_and_malformed_legacy_metadata_are_held_without_fallback(owner, tmp_path):
    value = two_span_manifest(owner)
    binding = {"source_span_id": "span-a", "source_revision": REV, "source_sha256": _sha(TEXT), "expected_binding": None}
    owner.fenced_claims().bind_sources_fenced("fixture:malformed-terminal-binding", [binding])
    value["spans"][0]["expected_binding"] = {"source_revision": REV, "source_sha256": _sha(TEXT)}
    owner._db.execute("DELETE FROM span_cache WHERE source_span_id='span-b'")
    owner._db.execute("UPDATE span_cache SET status='gap',code_identity=?,path_hashes=?,rule_json=? WHERE source_span_id='span-a'",
                      [CODE, json.dumps(HASHES), "malformed"])
    result = run(owner, tmp_path, source_manifest=value)
    assert result["processed"] == 0
    assert [row["reason"] for row in result["held"]] == ["terminal_row_requires_explicit_owner_reconciliation", "owner_source_missing_or_invalid"]


def test_changed_source_binding_cannot_reuse_historical_binding_receipt(owner, tmp_path):
    def failed(rows):
        raise RuntimeError("stop after initial binding")
    with pytest.raises(RuntimeError):
        run(owner, tmp_path, stage_exchange=failed)
    owner._db.execute("UPDATE span_source_bindings SET source_revision=?", ["hub:"+"e"*40])
    result = run(owner, tmp_path)
    assert result["processed"] == 0 and result["held"][0]["reason"] == "source_binding_drift"
    assert owner._db.execute("SELECT status FROM span_cache").fetchone()[0] == "pending"


def test_new_release_cannot_guess_first_binding_over_existing_owner_binding(owner, tmp_path):
    def failed(rows):
        raise RuntimeError("stop after initial binding")
    with pytest.raises(RuntimeError):
        run(owner, tmp_path, stage_exchange=failed)
    changed = manifest()
    changed["release_id"] = "fixture-release-2"
    refused = run(owner, tmp_path, source_manifest=changed)
    assert refused["processed"] == 0
    assert refused["held"][0]["reason"] == "source_binding_requires_explicit_expected_binding"
    assert owner._db.execute("SELECT count(*) FROM span_claim_operations WHERE operation_id LIKE 'fenced-ingest:bind:%'").fetchone()[0] == 1
    changed["spans"][0]["expected_binding"] = {"source_revision": REV, "source_sha256": _sha(TEXT)}
    accepted = run(owner, tmp_path, source_manifest=changed,
                   stage_exchange=metadata_stager(tmp_path/"exchange", release="fixture-release-2"))
    assert accepted["processed"] == 1 and accepted["held"] == []
    assert owner._db.execute("SELECT count(*) FROM span_claim_operations WHERE operation_id LIKE 'fenced-ingest:bind:%'").fetchone()[0] == 2


def test_maximum_span_identity_keeps_operation_ids_bounded(owner, tmp_path):
    span_id = "s"*512
    value = manifest()
    value["spans"][0]["source_span_id"] = span_id
    owner.enqueue([{"source_span_id": span_id, "legal_id": "fixture:law", "text": TEXT}])
    result = run(owner, tmp_path, source_manifest=value)
    assert result["processed"] == 1
    assert len(result["completions"][0]["operation_id"]) < 512


def test_manifest_corpus_and_source_identity_cannot_rebind_existing_cache(owner, tmp_path):
    owner._set_meta("dataset_id", "different:corpus")
    with pytest.raises(ingest.FencedIngestError, match="corpus differs"):
        run(owner, tmp_path)
    owner._set_meta("dataset_id", "fixture:corpus")
    owner._db.execute("UPDATE span_cache SET legal_id='foreign:law'")
    held = run(owner, tmp_path)
    assert held["processed"] == 0 and held["held"][0]["reason"] == "source_identity_drift"


def test_stage_failure_releases_only_exact_live_native_claim(owner, tmp_path):
    def failed(rows):
        raise RuntimeError("authored fixture stage failure")
    with pytest.raises(RuntimeError, match="stage failure"):
        run(owner, tmp_path, stage_exchange=failed)
    assert owner._db.execute("SELECT status FROM span_cache").fetchone()[0] == "pending"
    assert owner._db.execute("SELECT count(*) FROM span_claim_results").fetchone()[0] == 0
    assert list((tmp_path/"exchange").glob("fenced-output-*.json"))


def test_late_failure_never_uses_legacy_release_for_expired_claim(owner, tmp_path, monkeypatch):
    now = [100.0]
    owner.fenced_claims(clock=lambda: now[0])
    def failed(rows):
        now[0] = 500
        raise RuntimeError("late fixture stage failure")
    monkeypatch.setattr(owner, "release_claims", lambda *args: pytest.fail("legacy release fallback"))
    with pytest.raises(RuntimeError, match="late fixture") as failure:
        run(owner, tmp_path, stage_exchange=failed, lease_seconds=1)
    assert any("cleanup refused" in note for note in failure.value.__notes__)
    assert owner._db.execute("SELECT status FROM span_cache").fetchone()[0] == "claimed"


def test_source_changes_after_staging_refuse_completion_and_preserve_exchange(owner, tmp_path):
    guard_calls = [0]
    def guard():
        guard_calls[0] += 1
        return HASHES if guard_calls[0] < 4 else {"changed.py": "d"*64}
    with pytest.raises(ingest.FencedIngestError, match="source changed"):
        run(owner, tmp_path, source_guard=guard)
    assert owner._db.execute("SELECT count(*) FROM span_claim_results").fetchone()[0] == 0
    assert list((tmp_path/"exchange").glob("*.manifest.json"))


def test_oversized_required_rule_refuses_without_truncating_staged_output(owner, tmp_path):
    def large(item):
        result = worker(item)
        result["rule"]["opaque_fixture_field"] = "x"*70000
        return result
    with pytest.raises(ingest.FencedIngestError, match="byte bound"):
        run(owner, tmp_path, compile_worker=large)
    outputs = list((tmp_path/"exchange").glob("fenced-output-*.json"))
    assert len(json.loads(outputs[0].read_text())["rule"]["opaque_fixture_field"]) == 70000
    assert owner._db.execute("SELECT count(*) FROM span_claim_results").fetchone()[0] == 0


def test_worker_cannot_replace_source_or_omit_claimed_population(owner, tmp_path):
    with pytest.raises(ingest.FencedIngestError, match="source bytes"):
        run(owner, tmp_path, compile_worker=lambda item: dict(worker(item), text="other"))
    class EmptyPool:
        def map(self, function, values):
            return []
    with pytest.raises(ingest.FencedIngestError, match="omitted"):
        run(owner, tmp_path, worker_pool=EmptyPool())


def test_cli_selects_explicit_profile_and_rejects_real_inference_from_D(monkeypatch, tmp_path):
    script = Path(__file__).resolve().parents[3]/"scripts/ops/legal_ir/ingest_ipfs_uscode_corpus.py"
    spec = importlib.util.spec_from_file_location("fenced_ingest_cli_fixture", script)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    # Exercise a genuinely noncanonical caller regardless of the checkout
    # selected for this storage-contract suite; never invoke its parser.
    monkeypatch.setattr(cli, "ROOT", tmp_path/"unreviewed-logic-tree")
    with pytest.raises(RuntimeError, match="canonical workspace tree"):
        cli._fenced_compiler_preflight()
    seen = []
    def metadata_only(args, *, runtime=None):
        seen.append((args.claim_profile, args.batch, args.source_manifest))
        return {"held": [], "qualified": False, "admitted": False}
    monkeypatch.setattr(cli, "_run_fenced_cli", metadata_only)
    assert cli.main(["--cache", str(tmp_path/"not-opened.duckdb"), "--claim-profile", "fenced-v1", "--source-manifest", "fixture.json"]) == 0
    assert seen == [("fenced-v1", 16, Path("fixture.json"))]
    assert not (tmp_path/"not-opened.duckdb").exists()


def test_new_attempt_resumes_exact_history_only_under_explicit_owner_evidence_root(owner, tmp_path):
    first = tmp_path/"first-attempt"
    second = tmp_path/"second-attempt"
    first_report = run(owner, first)
    (second/"exchange").mkdir(parents=True)
    def forbidden(*args, **kwargs):
        pytest.fail("historical resume invoked a new producer")
    with pytest.raises(ingest.FencedIngestError, match="escapes"):
        run(owner, second, compile_worker=forbidden, stage_exchange=forbidden)
    resumed = run(owner, second, historical_evidence_roots=[tmp_path],
                  compile_worker=forbidden, stage_exchange=forbidden)
    assert resumed["resumed"] == 1 and resumed["processed"] == 0 and resumed["held"] == []
    assert list((second/"exchange").iterdir()) == []
    assert all(resumed[flag] is False for flag in ingest._FALSE)
    original = Path(first_report["completions"][0]["worker_output"]["path"])
    original.write_text("tampered historical bytes")
    with pytest.raises(ingest.FencedIngestError, match="immutable bytes changed"):
        run(owner, second, historical_evidence_roots=[tmp_path], compile_worker=forbidden)


def test_historical_evidence_root_cannot_be_a_symlink(owner, tmp_path):
    run(owner, tmp_path/"first-attempt")
    second = tmp_path/"second-attempt"
    (second/"exchange").mkdir(parents=True)
    alias = tmp_path/"root-alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlink"):
        run(owner, second, historical_evidence_roots=[alias])



@pytest.fixture
def coordinate_owner(tmp_path):
    from ipfs_datasets_py.logic.autoformal.uscode_ingest import (
        inventory_uscode_source_coordinates, uscode_source_coordinates_sha256)
    documents = [{"legal_id": "fixture:law", "title": "1", "section": "1",
                  "text": " \tΩ agency shall\r\n retain records.  "}]
    coordinates = inventory_uscode_source_coordinates(documents)
    pin = uscode_source_coordinates_sha256(coordinates)
    cache = SpanCache(tmp_path / "coordinate-owner.duckdb")
    cache._db.execute("SET threads=1")
    cache._set_meta("dataset_id", "fixture:corpus")
    cache.enqueue_source_coordinates(coordinates, documents, expected_report_sha256=pin)
    span = coordinates["spans"][0]
    source_manifest = {"schema": ingest.SOURCE_SCHEMA, "corpus_id": "fixture:corpus",
        "release_id": "fixture-release", "source_revision": REV,
        "spans": [{"source_span_id": span["source_span_id"], "legal_id": "fixture:law",
                   "source_sha256": _sha(span["text"]), "expected_binding": None}]}
    try:
        yield cache, coordinates, documents, pin, source_manifest
    finally:
        cache.close()


def test_coordinate_reference_reaches_worker_and_immutable_exchange(coordinate_owner, tmp_path):
    cache, coordinates, documents, pin, source_manifest = coordinate_owner
    expected = cache.pending(limit=1)[0]["source_provenance_json"]
    seen = []
    def observed(item):
        seen.append(dict(item))
        return worker(item)
    result = run(cache, tmp_path, source_manifest=source_manifest, compile_worker=observed)
    assert result["processed"] == 1 and result["qualified"] is False
    assert seen[0]["source_provenance_json"] == expected
    assert len(expected.encode("utf-8")) < 2048
    assert documents[0]["text"] not in expected  # shared original remains in the cache report
    completion = result["completions"][0]
    retained = json.loads(Path(completion["worker_output"]["path"]).read_text())
    assert retained["source_provenance_json"] == expected
    bundle = exchange.load_exchange_bundle(completion["exchange_manifests"][0]["path"])
    exported = json.loads(bundle["census_rows"][0]["input_json"])
    assert exported["source_provenance_json"] == expected
    assert cache.read_source_coordinate_report(expected_report_sha256=pin) == coordinates
    assert cache.read_source_coordinate_report(expected_report_sha256=pin)["documents"][0]["source_text"] == documents[0]["text"]
    saved = json.loads(cache._db.execute("SELECT result_json FROM span_claim_results").fetchone()[0])
    from ipfs_datasets_py.logic.autoformal.span_cache_claims import _LEASE_FIELDS
    assert set(saved["claim"]) == set(_LEASE_FIELDS)
    assert "source_provenance_json" not in saved["claim"]
    assert saved["agrees"] is False


def test_owner_coordinate_reference_enriches_an_omitting_worker(coordinate_owner, tmp_path):
    cache, _, _, _, source_manifest = coordinate_owner
    expected = cache.pending(limit=1)[0]["source_provenance_json"]
    def omitted(item):
        result = worker(item)
        result.pop("source_provenance_json")
        result["source_provenance"] = {"source_provenance_json": expected}
        return result
    result = run(cache, tmp_path, source_manifest=source_manifest, compile_worker=omitted)
    retained = json.loads(Path(result["completions"][0]["worker_output"]["path"]).read_text())
    assert retained["source_provenance_json"] == expected
    assert retained["source_provenance"]["source_provenance_json"] == expected


@pytest.mark.parametrize("location,value", [("top", "{}"), ("top", None), ("nested", "{}"), ("nested", None)])
def test_coordinate_worker_conflict_is_refused_before_staging(coordinate_owner, tmp_path, location, value):
    cache, _, _, _, source_manifest = coordinate_owner
    def altered(item):
        if location == "top":
            # In-process pools must not let this overwrite the owner's expectation.
            item["source_provenance_json"] = value
        result = worker(item)
        if location == "nested":
            result["source_provenance"] = {"source_provenance_json": value}
        return result
    def forbidden_stage(rows):
        pytest.fail("conflicting source coordinates reached staging")
    with pytest.raises(ingest.FencedIngestError, match="coordinate provenance"):
        run(cache, tmp_path, source_manifest=source_manifest, compile_worker=altered, stage_exchange=forbidden_stage)
    assert cache._db.execute("SELECT count(*) FROM span_claim_results").fetchone()[0] == 0
    assert cache._db.execute("SELECT status FROM span_cache").fetchone()[0] == "pending"


def test_worker_cannot_invent_coordinate_provenance_for_legacy_row(owner, tmp_path):
    with pytest.raises(ingest.FencedIngestError, match="coordinate provenance"):
        run(owner, tmp_path, compile_worker=lambda item: {**worker(item), "source_provenance_json": "{}"})
    assert owner._db.execute("SELECT status FROM span_cache").fetchone()[0] == "pending"


def test_coordinate_metadata_is_charged_to_source_batch_bound(coordinate_owner, tmp_path, monkeypatch):
    cache, coordinates, _, _, source_manifest = coordinate_owner
    monkeypatch.setattr(ingest, "MAX_SOURCE_BATCH_BYTES", len(coordinates["spans"][0]["text"].encode("utf-8"))+1)
    def forbidden(item):
        pytest.fail("oversized source/provenance packet reached worker")
    with pytest.raises(ingest.FencedIngestError, match="byte bound|batch exceeds"):
        run(cache, tmp_path, source_manifest=source_manifest, compile_worker=forbidden)
    assert cache._db.execute("SELECT status FROM span_cache").fetchone()[0] == "pending"
