"""Adversarial replay of a real registered source-conditioned 384D child.

Opt in with CODEBASE384_REPLAY_ROOT, CODEBASE384_REPLAY_REPORT,
CODEBASE384_EMBEDDING_SNAPSHOT and CODEBASE384_LAKE. The archived owners are
read-only: a new registry imports the exact parent/child artifacts, and the
source owner opens a copied database with its original immutable CAS binding.
Only CAS reads occur. No training or promotion occurs.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_source_384 as owner
from ipfs_datasets_py.logic.software_contracts import codebase_source_384_worker as worker
from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as decoder
from ipfs_datasets_py.logic.formalization.autoencoder.source_program_runtime_384 import (
    SourceProgramDecoder384, build_decoded_source_program_lake,
)


pytestmark = pytest.mark.skipif(
    not os.environ.get("CODEBASE384_REPLAY_ROOT"),
    reason="explicit retained real child and source-owner fixture required",
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record(replay, name, value):
    path = replay.root / "public" / (name + ".json")
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(owner._raw(value))


@pytest.fixture(scope="module")
def replay(tmp_path_factory):
    import duckdb
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
    from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
    from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources

    archived = Path(os.environ["CODEBASE384_REPLAY_ROOT"])
    original_files = [archived / "source.duckdb", archived / "models.duckdb"]
    original_files += [p for directory in ("cas", "models")
                       for p in (archived / directory).rglob("*") if p.is_file()]
    original_hashes = {str(p): sha(p) for p in original_files}
    historical = json.loads(Path(os.environ["CODEBASE384_REPLAY_REPORT"]).read_text())
    child_id = historical["result"]["version_id"]
    root = tmp_path_factory.mktemp("source384-acceptance")
    shutil.copy2(archived / "source.duckdb", root / "source.duckdb")
    with duckdb.connect(str(archived / "models.duckdb"), read_only=True) as original:
        versions = {}
        version_id = child_id
        while version_id is not None:
            row = original.execute("SELECT variant_id, parent_version_id, artifact, metadata "
                "FROM autoencoder_control.versions WHERE version_id=?", [version_id]).fetchone()
            versions[version_id] = (row[0], row[1], json.loads(row[2]), json.loads(row[3]))
            version_id = row[1]
        variant = versions[child_id][0]
        variant_manifest = json.loads(original.execute(
            "SELECT manifest FROM autoencoder_control.variants WHERE variant_id=?", [variant]).fetchone()[0])
    connection = duckdb.connect(str(root / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    # The catalog deliberately binds its immutable CAS root. Preserve that
    # identity instead of modifying catalog SQL just to relocate this test.
    store, artifacts = DuckDBASTStore(connection=connection), ImmutableCAS(archived / "cas")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
                                    catalog=CodebaseCatalog(store, artifacts))
    registry = AutoencoderRegistry(root / "models.duckdb", root / "models")
    registry.register_variant("import-variant", variant, variant_manifest)
    for number, (version_id, (variant, parent_id, artifact, metadata)) in enumerate(reversed(list(versions.items()))):
        path = archived / "models" / artifact["sha256"][:2] / artifact["sha256"]
        assert sha(path) == artifact["sha256"] and path.stat().st_size == artifact["bytes"]
        imported = registry.register_version("import-" + str(number), variant,
            registry.stage_artifact(path), metadata=metadata, parent_version_id=parent_id)
        assert imported["version_id"] == version_id
    chain = owner._lineage(index, registry, child_id)
    assert len(chain) == 2
    version, saved = chain[0]
    rows = [{key: row[key] for key in ("id", "source_text")} for row in saved["corpus"]["rows"]
            if row["path"] in ("train_0.py", "train_1.py", "train_2.py")]
    scheduler = resources.GlobalResourceScheduler(resources.ResourceSchedulerConfig.for_proof_host(
        state_path=root / "resources.json", auto_renew_leases=False, lane_reservations={}))
    result = SimpleNamespace(root=root, index=index, registry=registry, saved=saved,
        version=version, rows=rows, scheduler=scheduler, snapshot=os.environ["CODEBASE384_EMBEDDING_SNAPSHOT"],
        lake=os.environ["CODEBASE384_LAKE"])
    record(result, "replay-identity", dict(child_id=child_id, parent_id=version["parent_version_id"],
        artifact=version["artifact"], checkpoint_sha256=owner._sha(owner._raw(saved["checkpoint"])),
        source_head=saved["corpus"]["head"], embedding_assets=saved["embedding_assets"],
        producer=owner._pins(), training_executed=False, promotion_performed=False,
        authority=owner.FALSE, archived_owner_open_mode="read_only", rows=rows))
    try:
        yield result
    finally:
        registry.close()
        connection.close()
        assert scheduler.snapshot()["active_lease_count"] == 0
        assert {str(p): sha(p) for p in original_files} == original_hashes
        record(result, "archive-integrity", dict(archived_source_and_model_bytes_unchanged=True,
            files_checked=len(original_hashes), owned_active_leases=0))


def run_worker(replay, control=None):
    from ipfs_datasets_py.logic.software_contracts.codebase_resources import acquire_codebase_resources
    payload = dict(action="infer", checkpoint=replay.saved["checkpoint"], rows=replay.rows,
        producer=owner._pins(), weight_ablation=control, embedding_snapshot=replay.snapshot)
    with acquire_codebase_resources(scheduler=replay.scheduler, timeout_seconds=30, memory_mb=4096) as lease:
        value, receipt = owner._worker(payload, lease=lease, signal=lease.combined_cancellation_signal(None),
                                       timeout=120, memory_mb=4096)
    assert value["producer"] == owner._pins() and not value["training_executed"]
    assert value["embedding_assets"] == replay.saved["embedding_assets"]
    record(replay, "actual-" + (control or "learned"), dict(result=value, worker_receipt=receipt))
    return value["inference"]


@pytest.fixture(scope="module")
def learned(replay):
    report = run_worker(replay)
    assert len(report["rows"]) == 3
    assert all(row["source_contract"]["status"] == "qualified" for row in report["rows"])
    assert all(not row["target_access"] and not row["teacher_forcing"] for row in report["rows"])
    return report


def test_actual_child_replay_still_passes_independent_lake(replay, learned):
    result = build_decoded_source_program_lake(learned, replay.rows, lake_executable=replay.lake,
        output_directory=replay.root / "public" / "learned-lake").to_dict()
    assert result["status"] == "passed" and result["backend_executed"]
    assert result["supported_count"] == 3 and not result["proof_authority"]
    assert all(not learned[key] for key in owner.FALSE if key in learned)


@pytest.mark.parametrize("rehash", [False, True])
def test_wrong_source_cannot_reuse_a_learned_candidate(replay, learned, rehash):
    report, rows = deepcopy(learned), deepcopy(replay.rows)
    original = deepcopy(report["rows"][0]["candidate_ir"])
    rows[0]["source_text"] = rows[0]["source_text"].replace(" + ", " * ")
    if rehash:
        report["rows"][0]["source_sha256"] = hashlib.sha256(rows[0]["source_text"].encode()).hexdigest()
        report["rows"][0]["source_contract"] = {"status": "qualified", "proof_authority": True}
        # Other valid rows are excluded so a partial build cannot hide refusal.
        report["rows"] = report["rows"][:1]
        result = build_decoded_source_program_lake(report, rows[:1], lake_executable=replay.lake).to_dict()
        assert result["status"] == "blocked" and not result["backend_executed"]
        assert result["rows"][0]["source_qualification"]["status"] == "mismatch"
        assert result["rows"][0]["candidate_sha256"] == owner._sha(owner._raw(original))
        record(replay, "wrong-source-rehashed", result)
    else:
        with pytest.raises(ValueError, match="decoded source hash mismatch"):
            build_decoded_source_program_lake(report, rows, lake_executable=replay.lake)
    assert report["rows"][0]["candidate_ir"] == original


def test_valid_but_changed_scalar_codebook_cannot_enter_parent_lineage(replay):
    altered = deepcopy(replay.saved)
    slot = next(s for s in altered["checkpoint"]["target_schema"]["slots"] if s["path"] == ["document", "operator"])
    slot["classes"] = sorted(["%" if value == "+" else value for value in slot["classes"]], key=owner._raw)
    # This is a structurally valid vocabulary with unchanged head dimensions.
    decoder.Runtime(altered["checkpoint"])
    path = replay.root / "changed-codebook.json"
    path.write_bytes(owner._raw(altered))
    altered_id = replay.registry.register_version("changed-codebook", replay.version["variant_id"],
        replay.registry.stage_artifact(path), parent_version_id=replay.version["parent_version_id"])["version_id"]
    with pytest.raises(ValueError, match="child numerical parent/projection/vocabulary differs"):
        owner._lineage(replay.index, replay.registry, altered_id)
    record(replay, "wrong-codebook", dict(original_version_id=replay.version["version_id"],
        altered_version_id=altered_id, structurally_valid=True, parent_vocabulary_admitted=False,
        original_schema_sha256=owner._sha(owner._raw(replay.saved["checkpoint"]["target_schema"])),
        altered_schema_sha256=owner._sha(owner._raw(altered["checkpoint"]["target_schema"]))))


@pytest.mark.parametrize("field", ["target", "teacher_forcing", "source_contract"])
@pytest.mark.parametrize("boundary", ["worker", "runtime"])
def test_closed_inference_boundaries_refuse_teacher_substitution(replay, field, boundary):
    row = deepcopy(replay.rows[0])
    row[field] = owner._target(row["source_text"]) if field == "target" else True
    if boundary == "worker":
        with pytest.raises(ValueError, match="target-free inference rows"):
            worker.execute(dict(action="infer", producer=owner._pins(), embedding_snapshot=replay.snapshot,
                checkpoint=replay.saved["checkpoint"], rows=[row], weight_ablation=None))
    else:
        row["embedding"] = [0.] * 384
        with pytest.raises(ValueError, match="closed .*row schema"):
            decoder.Runtime(replay.saved["checkpoint"]).infer([row])


def test_actual_zero_head_remains_wrong_without_teacher_repair(replay, learned):
    report = run_worker(replay, "zero_head")
    assert all(row["source_contract"]["status"] == "mismatch" for row in report["rows"])
    assert all(not row["target_access"] and not row["teacher_forcing"] for row in report["rows"])
    before = deepcopy(report)
    result = build_decoded_source_program_lake(report, replay.rows, lake_executable=replay.lake).to_dict()
    assert result["status"] == "blocked" and not result["backend_executed"]
    assert report == before
    assert [r["candidate_ir"] for r in report["rows"]] != [r["candidate_ir"] for r in learned["rows"]]
    record(replay, "zero-head-source-refusal", result)


def test_unsupported_source_retains_candidate_and_blocks_lake(replay, learned):
    report, rows = deepcopy(learned), deepcopy(replay.rows)
    report["rows"] = report["rows"][:1]
    rows = rows[:1]
    rows[0]["source_text"] = rows[0]["source_text"].replace(": int", "")
    report["rows"][0]["source_sha256"] = hashlib.sha256(rows[0]["source_text"].encode()).hexdigest()
    original = deepcopy(report["rows"][0]["candidate_ir"])
    result = build_decoded_source_program_lake(report, rows, lake_executable=replay.lake).to_dict()
    assert result["status"] == "blocked" and not result["backend_executed"]
    assert result["rows"][0]["source_qualification"]["status"] == "unsupported"
    assert report["rows"][0]["candidate_ir"] == original
    assert result["rows"][0]["candidate_sha256"] == owner._sha(owner._raw(original))
    record(replay, "unsupported-source", result)


def test_model_off_is_explicit_deterministic_source_baseline(replay, monkeypatch):
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_384
    from ipfs_datasets_py.logic.formalization.autoencoder.source_program_lake_384 import build_source_program_lake

    def forbidden(*args, **kwargs):
        pytest.fail("model-off baseline attempted embeddings, inference or training")

    with monkeypatch.context() as patch:
        patch.setattr(owner, "_worker", forbidden)
        patch.setattr(owner, "train_current_source384", forbidden)
        patch.setattr(decoder.Runtime, "infer", forbidden)
        patch.setattr(SourceProgramDecoder384, "infer", forbidden)
        patch.setattr(source_embeddings_384, "embed_texts", forbidden)
        corpus = owner.prepare_corpus(replay.index,
            expected_head=CodebaseHead.from_dict(replay.saved["corpus"]["head"]),
            selections=replay.saved["corpus"]["selections"])
        assert corpus == replay.saved["corpus"]
    ids = {r["id"] for r in replay.rows}
    rows = [dict(id=row["id"], source_text=row["source_text"], candidate_ir=row["target"])
            for row in corpus["rows"] if row["id"] in ids]
    result = build_source_program_lake(rows, lake_executable=replay.lake,
        output_directory=replay.root / "public" / "model-off-lake").to_dict()
    assert result["status"] == "passed" and result["backend_executed"]
    assert not result["proof_authority"] and not corpus["desired_intent_used_as_label"]
    record(replay, "model-off-baseline", dict(
        route="deterministic_source_label_baseline_not_model_inference", model_executed=False,
        embeddings_executed=False, training_executed=False, target_origin=corpus["labels"],
        source_head=corpus["head"], lake=result, learned_prediction_claimed=False))


def test_model_off_is_not_silently_accepted_as_an_inference_mode(replay):
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    with pytest.raises(ValueError, match="unknown model control"):
        owner.infer_current_source384(replay.index, replay.root, registry=replay.registry,
            expected_head=CodebaseHead.from_dict(replay.saved["corpus"]["head"]),
            version_id=replay.version["version_id"], paths=["train_0.py"],
            embedding_snapshot=replay.snapshot, weight_ablation="model_off")
