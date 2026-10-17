"""Private real-Parquet evidence migration; no models, compiler passes or Hub."""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path

import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.logic.autoformal import paired_span_census as paired
from ipfs_datasets_py.logic.autoformal import paired_span_migration as migration

ROOT = Path(migration.__file__).resolve().parents[3]


def pins():
    paths = [ROOT / relative for relative in migration.SOURCE_RELATIVES]
    return {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def producer_receipt(count=8):
    rows = []
    for index in range(count):
        text = f"The agency shall submit report {index}."
        text_sha = hashlib.sha256(text.encode()).hexdigest()
        formula = dict(family="frame", format="fixture-formula/v1", payload={"predicate": f"submit_report_{index}"},
            origin="autoencoder_guided_compiler", independent=False, target_conditioned=True, syntax_status="not_checked")
        binding = dict(origin="autoencoder_guided_compiler", complete=True, source_text_sha256=text_sha,
            model_identity={"sha256": "7" * 64, "bytes": 10}, independent=False, target_conditioned=True)
        direct = {**formula, "origin": "deterministic_codec", "target_conditioned": False}
        rows.append(dict(source_span_id=f"span-{index}", sample_id=f"sample-{index}", legal_id=f"usc:fixture:{index}",
            text=text, source_sha256=text_sha, status="diagnostic_observed", admitted=False, formalized=False,
            semantic_qualified=False, learned_formula_generation=False,
            embedding_representation={"embedding_model": "mock:fixture", "semantic_embeddings": False},
            raw_decoder={"embedding": [0.1, 0.2], "cosine_similarity": 0.5, "reconstruction_loss": 0.5},
            compiler={"status": "abstained", "reason": "compiler_abstain", "rules": [],
                "compilation_complete": False, "roundtrip": False, "decompiled": ""},
            guided_compiler_observation={"guided_formal_outputs": [formula], "direct_formal_outputs": [direct],
                "model_formal_output_provenance": binding,
                "direct_formal_output_provenance": {"complete": True, "source_text_sha256": text_sha}}))
    return dict(schema_version="legacy-span-cuda-diagnostic/v1", mode="legacy_mock_diagnostic", rows=rows,
        raw_evaluation={}, producer_source={"sha256": "a" * 64}, checkpoint={"sha256": "7" * 64, "bytes": 10},
        campaign={"batch_id": "private-historical-batch"}, sample_count=count,
        admitted=False, formalized=False, semantic_qualified=False, training_executed=False)


def write_old(directory, receipt, *, mutation=None):
    directory.mkdir()
    runner = migration._runner(ROOT)
    code, model = "sha256:" + "a" * 64, "legacy-mock-diagnostic:sha256:" + "7" * 64
    current = paired.build_paired_census(migration._observations(receipt, runner), original_receipt=receipt,
        agent_id="private-migration", code_identity=code, model_identity=model)
    # Reproduce the historical producer independently of the migration helper:
    # its pre-serialization rows had full v2 comparisons, no learned-capture
    # fields, and IDs hashed before legacy Arrow discarded comparison fields.
    spans = deepcopy(current["paired_spans"])
    for span in spans:
        del span["autoencoder"]["learned_formula_capture_verified"]
        del span["autoencoder"]["learned_formula_observation_artifact_sha256"]
        del span["observation_id"]
        span["goal_ids"] = []
        raw = json.dumps(span, sort_keys=True, ensure_ascii=True,
                         separators=(",", ":"), allow_nan=False).encode("ascii")
        span["observation_id"] = hashlib.sha256(raw).hexdigest()
    by_source = {row["source"]["span_id"]: row for row in spans}
    archive = paired._Artifacts(paired.MAX_BYTES)
    receipt_ref = archive.add(receipt, "original_producer_receipt")
    goals = []
    for exported in paired._portable_repairs(spans, repository_id=paired.REPOSITORY,
            agent_id="private-migration", release_id="ipfs-uscode-5016b86a", code_identity=code, model_identity=model):
        source = by_source[exported["source_span_id"]]
        packet_raw, task_raw = exported["packet_json"].encode(), exported["task_json"].encode()
        packet, task = json.loads(packet_raw), json.loads(task_raw)
        goal = paired._goal_base(exported["task_id"], issue=task.get("reason", "retained historical repair"),
            work_kind=task.get("work_kind", "compiler_decompiler_repair"), kind=exported["record_kind"], code=code, model=model)
        goal.update(source_span_ids=[source["source"]["span_id"]], observation_ids=[source["observation_id"]],
            packet_sha256=exported["packet_sha256"], task_sha256=exported["task_sha256"],
            packet_artifact_sha256=archive.add(packet, "supervisor_packet", exact=packet_raw),
            task_artifact_sha256=archive.add(task, "supervisor_task", exact=task_raw),
            packet_schema=exported["packet_schema"], task_schema=exported["todo_schema"],
            legacy_census_sha256=exported["census_sha256"], repository_id=paired.REPOSITORY,
            agent_id="private-migration", release_id="ipfs-uscode-5016b86a", legal_id=source["source"]["legal_id"])
        goals.append(goal)
        source["goal_ids"].append(goal["goal_id"])
    tables = dict(paired_spans=spans, goals=goals, artifacts=list(archive.rows.values()))
    if mutation:
        mutation(tables)
    entries = {}
    schemas = paired.arrow_schemas(paired.LEGACY_SCHEMA)
    for kind, rows in tables.items():
        filename = kind + "-historical.parquet"
        pq.write_table(pa.Table.from_pylist(rows, schema=schemas[kind]), directory / filename, compression="zstd")
        raw = (directory / filename).read_bytes()
        entries[kind] = dict(filename=filename, path_in_repo=f"{paired.REPO_PREFIX}/{kind}/private-migration/{filename}",
            bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), row_count=len(rows))
    # The actual Arrow serialization, rather than this fixture's Python code,
    # discards the five comparison additions while retaining the earlier ID.
    tables["paired_spans"] = pq.read_table(directory / entries["paired_spans"]["filename"]).to_pylist()
    manifest = dict(schema=paired.MANIFEST_SCHEMA, repository_id=paired.REPOSITORY, agent_id="private-migration",
        exporter_sha256=migration.HISTORICAL_EXPORTER, tables=entries,
        original_receipt_artifact_sha256=receipt_ref, admitted=False, formalized=False, enqueued=False)
    fingerprint = hashlib.sha256(paired._json(manifest)).hexdigest()
    manifest.update(fingerprint=fingerprint, path_in_repo=f"{paired.REPO_PREFIX}/manifests/private-migration/manifest-{fingerprint}.json")
    path = directory / f"manifest-{fingerprint}.json"
    path.write_bytes(paired._json(manifest))
    receipt_path = directory / "retained-receipt.json"
    receipt_path.write_bytes(paired._json(receipt))
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), receipt_path, tables


def test_real_old_parquet_regenerates_honest_v2_and_preserves_every_original(tmp_path):
    path, digest, receipt_path, old = write_old(tmp_path / "old", producer_receipt())
    original_files = {p: p.read_bytes() for p in path.parent.iterdir()}
    result = migration.migrate_historical_paired_bundle(path, tmp_path / "new", expected_manifest_sha256=digest,
        expected_sources=pins(), receipt_path=receipt_path)
    loaded = paired.load_paired_census_bundle(result["new_manifest"]["path"])
    assert len(loaded["paired_spans"]) == 8
    assert result["old_fingerprint"] != result["new_fingerprint"]
    assert result["batch_id"] == "private-historical-batch"
    assert result["staged"]["manifest"] == result["new_manifest"]
    assert result["supersedes"]["manifest"]["sha256"] == digest
    assert result["supersedes"]["manifest"]["path"] == str(path)
    assert result["owner_handoff"] == {"expected_status": "needs_schema_migration", "staged_status": "staged",
        "database_changed": False, "work_rows_changed": False, "completion_counts_changed": False}
    assert result["historical_goal_count"] == len(old["goals"]) == 8
    for row in loaded["paired_spans"]:
        assert row["autoencoder"]["learned_formula_capture_verified"] is False
        assert row["autoencoder"]["learned_formula_observation_artifact_sha256"] is None
        assert row["comparison"]["method"] == "exact_ast_and_validated_canonical_core/v2"
        assert row["comparison"]["independent"] is False
        assert row["admitted"] is row["formalized"] is row["lake"]["admitted"] is False
    artifacts = {row["artifact_sha256"]: row for row in loaded["artifacts"]}
    for artifact in old["artifacts"]:
        assert artifacts[artifact["artifact_sha256"]] == artifact
    lineage = json.loads(paired.decode_artifact(artifacts[result["lineage_artifact_sha256"]]))
    assert lineage["historical_goals"] == old["goals"]
    identity = lineage["historical_observation_identity"]
    assert identity["producer_sha256"] == "93a5b6c4fafabf45f84cd12b53347e7e8e96686592b489a6a7ea036d88d5b2e9"
    assert identity["comparison_method"] == "exact_ast_and_validated_canonical_core/v2"
    summaries = [row for row in loaded["goals"] if row["record_kind"] == "historical_goal_record"]
    assert len(summaries) == 8
    assert all(row["packet_artifact_sha256"] is row["task_artifact_sha256"] is None for row in summaries)
    archived_files = [json.loads(paired.decode_artifact(row)) for row in loaded["artifacts"]
                      if row["kind"] == "historical_paired_file"]
    assert len(archived_files) == 4
    for archived in archived_files:
        body = base64.b64decode(archived["payload_base64"], validate=True)
        assert hashlib.sha256(body).hexdigest() == archived["sha256"]
    assert all(p.read_bytes() == raw for p, raw in original_files.items())
    assert result["compiler_rerun"] is result["model_rerun"] is result["uploaded"] is result["admitted"] is False


def test_tampered_table_is_rejected_before_output(tmp_path):
    path, digest, _, _ = write_old(tmp_path / "old", producer_receipt(1))
    target = path.parent / "artifacts-historical.parquet"
    target.write_bytes(target.read_bytes() + b"tampered")
    with pytest.raises(paired.PairedCensusError, match="hash/size"):
        migration.migrate_historical_paired_bundle(path, tmp_path / "never", expected_manifest_sha256=digest, expected_sources=pins())
    assert not (tmp_path / "never").exists()


def test_changed_old_observation_cannot_be_recreated_from_original_receipt(tmp_path):
    def mutate(tables):
        tables["paired_spans"][0]["compiler"]["reason"] = "invented replacement reason"
    path, digest, _, _ = write_old(tmp_path / "old", producer_receipt(1), mutation=mutate)
    with pytest.raises(paired.PairedCensusError, match="exactly reproduce"):
        migration.migrate_historical_paired_bundle(path, tmp_path / "never", expected_manifest_sha256=digest, expected_sources=pins())
    assert not (tmp_path / "never").exists()


@pytest.mark.parametrize("change", ["observation_id", "comparison_method"])
def test_historical_identity_and_method_cannot_be_substituted(tmp_path, change):
    def mutate(tables):
        span = tables["paired_spans"][0]
        if change == "observation_id":
            span["observation_id"] = "0" * 64
        else:
            span["comparison"]["method"] = "exact_canonical_ast_sequence/v1"
    path, digest, _, _ = write_old(tmp_path / "old", producer_receipt(1), mutation=mutate)
    with pytest.raises(paired.PairedCensusError, match="exactly reproduce"):
        migration.migrate_historical_paired_bundle(path, tmp_path / "never",
            expected_manifest_sha256=digest, expected_sources=pins())
    assert not (tmp_path / "never").exists()


def test_historical_portable_goal_must_retain_its_original_source_binding(tmp_path):
    def mutate(tables):
        tables["goals"][0]["source_span_ids"] = ["invented-source"]
    path, digest, _, _ = write_old(tmp_path / "old", producer_receipt(1), mutation=mutate)
    with pytest.raises(paired.PairedCensusError, match="historical goal source links differ"):
        migration.migrate_historical_paired_bundle(path, tmp_path / "never",
            expected_manifest_sha256=digest, expected_sources=pins())
    assert not (tmp_path / "never").exists()


@pytest.mark.parametrize("field,value", [("row_count", 129), ("bytes", 64 * 1024 * 1024 + 1)])
def test_manifest_bounds_refuse_before_parquet_allocation(tmp_path, field, value):
    path, _, _, _ = write_old(tmp_path / "old", producer_receipt(1))
    manifest = json.loads(path.read_bytes())
    manifest["tables"]["paired_spans"][field] = value
    manifest["fingerprint"] = hashlib.sha256(paired._json({k: v for k, v in manifest.items()
        if k not in {"fingerprint", "path_in_repo"}})).hexdigest()
    path.write_bytes(paired._json(manifest))
    with pytest.raises(paired.PairedCensusError, match="bound"):
        migration.migrate_historical_paired_bundle(path, tmp_path / "never",
            expected_manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), expected_sources=pins())
    assert not (tmp_path / "never").exists()


def test_missing_guidance_does_not_create_flags_or_empty_success(tmp_path):
    receipt = producer_receipt(1)
    receipt["rows"][0]["guided_compiler_observation"].pop("direct_formal_outputs")
    with pytest.raises(paired.PairedCensusError, match="guided/direct evidence is incomplete"):
        migration._observations(receipt, migration._runner(ROOT))


def test_wrong_original_receipt_file_refuses_migration(tmp_path):
    path, digest, receipt, _ = write_old(tmp_path / "old", producer_receipt(1))
    receipt.write_bytes(b'{"different":"receipt"}')
    with pytest.raises(paired.PairedCensusError, match="retained receipt file differs"):
        migration.migrate_historical_paired_bundle(path, tmp_path / "never", expected_manifest_sha256=digest,
            expected_sources=pins(), receipt_path=receipt)


def test_only_the_exact_seven_field_missing_arrow_layout_is_supported(tmp_path):
    path, _, _, _ = write_old(tmp_path / "old", producer_receipt(1))
    manifest = json.loads(path.read_bytes())
    table_path = path.parent / manifest["tables"]["paired_spans"]["filename"]
    table = pq.read_table(table_path).drop(["compiler"])
    pq.write_table(table, table_path)
    raw = table_path.read_bytes()
    manifest["tables"]["paired_spans"].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    manifest["fingerprint"] = hashlib.sha256(paired._json({k: v for k, v in manifest.items()
        if k not in {"fingerprint", "path_in_repo"}})).hexdigest()
    path.write_bytes(paired._json(manifest))
    with pytest.raises(paired.PairedCensusError, match="unsupported historical Arrow layout"):
        migration.migrate_historical_paired_bundle(path, tmp_path / "never",
            expected_manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), expected_sources=pins())
    assert not (tmp_path / "never").exists()


def test_changed_reviewed_producer_pin_refuses_before_output(tmp_path):
    path, digest, _, _ = write_old(tmp_path / "old", producer_receipt(1))
    expected = pins()
    expected[str(Path(migration.__file__).resolve())] = "0" * 64
    with pytest.raises(paired.PairedCensusError, match="migration producer source changed"):
        migration.migrate_historical_paired_bundle(path, tmp_path / "never",
            expected_manifest_sha256=digest, expected_sources=expected)
    assert not (tmp_path / "never").exists()
