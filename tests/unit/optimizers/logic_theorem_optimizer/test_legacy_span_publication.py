"""Remote closure and crash-safe eviction tests; all Hub responses are fake."""
import hashlib
import json
from types import SimpleNamespace

import duckdb
import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_publication as module


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    runtime = tmp_path / "campaign"
    (runtime / "receipts").mkdir(parents=True)
    (runtime / "outbox").mkdir()
    batch_id, fingerprint, commit = "a" * 32, "b" * 64, "c" * 40
    rows = [{"source_span_id": "one", "sample_id": "sample-one", "text": "Agency shall file."},
            {"source_span_id": "two", "sample_id": "sample-two", "text": "Agency shall retain."}]
    raw = {"sample_count": 2, "decoded_embeddings": {"sample-one": [0.1], "sample-two": [0.2]},
           "legal_ir_losses": {"deontic": 0.1}, "sample_embedding_metrics": [{"id": "one"}], "empty": {}}
    receipt = {"rows": rows, "raw_evaluation": raw, "campaign": {"batch_id": batch_id}, "admitted": False}
    shared = {key: value for key, value in receipt.items() if key not in {"rows", "raw_evaluation"}}
    inputs = [{"source_span_id": row["source_span_id"], "autoencoder_observation": row,
               "batch_observation": shared,
               "raw_sample_evaluation": {"decoded_embeddings": raw["decoded_embeddings"][row["sample_id"]]}}
              for row in rows]
    inputs[0]["raw_batch_summary"] = {key: value for key, value in raw.items() if key != "decoded_embeddings"}
    census = [{"input_json": encoded(item).decode()} for item in inputs]
    paths = {"receipt": runtime / "receipts" / (batch_id + ".json"),
             "census": runtime / "outbox" / ("census-" + fingerprint + ".parquet"),
             "goals": runtime / "outbox" / ("goals-" + fingerprint + ".parquet"),
             "manifest": runtime / "outbox" / ("exchange-" + fingerprint + ".manifest.json")}
    paths["publication"] = paths["manifest"].with_name(paths["manifest"].name + ".publication.json")
    paths["receipt"].write_bytes(encoded(receipt))
    paths["census"].write_bytes(encoded(census))
    paths["goals"].write_bytes(b"fixture-goals")
    manifest = {"schema": "uscode-autoformal-exchange-manifest/v2", "repository_id": module.REPOSITORY,
                "fingerprint": fingerprint, "path_in_repo": "autoformal/uscode/exchanges/campaign/manifest.json"}
    for kind in ("census", "goals"):
        body = paths[kind].read_bytes()
        manifest[kind] = {"filename": paths[kind].name, "bytes": len(body),
                          "sha256": hashlib.sha256(body).hexdigest(),
                          "path_in_repo": f"autoformal/uscode/{kind}/campaign/{kind}.parquet"}
    paths["manifest"].write_bytes(encoded(manifest))
    publication = {"repository_id": module.REPOSITORY, "fingerprint": fingerprint,
        "manifest_sha256": hashlib.sha256(encoded(manifest)).hexdigest(),
        "manifest": {"path": str(paths["manifest"]), "path_in_repo": manifest["path_in_repo"]},
        "uploaded": True, "dry_run": False, "commit_sha": commit,
        "parent_commit": "d" * 40, "admitted": False, "formalized": False,
        "wrote_compiler": False, "enqueued": False}
    paths["publication"].write_bytes(encoded(publication))
    bundle = {"manifest_sha256": publication["manifest_sha256"], "manifest": manifest,
              "census_path": str(paths["census"]), "goals_path": str(paths["goals"]), "census_rows": census}
    monkeypatch.setattr(module, "_load_bundle", lambda path: bundle)
    remote = []
    for kind in ("manifest", "census", "goals"):
        body = paths[kind].read_bytes()
        path = manifest["path_in_repo"] if kind == "manifest" else manifest[kind]["path_in_repo"]
        remote.append({"path": path, "size": len(body),
                       "lfs": {"sha256": hashlib.sha256(body).hexdigest()} if kind == "census" else None,
                       "blob_id": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()})
    class Api:
        def __init__(self):
            self.requests = []
        def repo_info(self, **kwargs):
            self.requests.append(kwargs)
            assert kwargs["revision"] == commit
            return SimpleNamespace(sha=commit)
        def get_paths_info(self, **kwargs):
            self.requests.append(kwargs)
            assert kwargs["revision"] == commit
            return remote
    db = duckdb.connect(str(tmp_path / "queue.duckdb"))
    db.execute("CREATE TABLE batches(id VARCHAR PRIMARY KEY,status VARCHAR,manifest VARCHAR,publication VARCHAR,receipt_sha256 VARCHAR)")
    db.execute("INSERT INTO batches VALUES (?, 'published', ?, ?, ?)",
               [batch_id, str(paths["manifest"]), encoded(publication).decode(), hashlib.sha256(encoded(receipt)).hexdigest()])
    yield SimpleNamespace(runtime=runtime, batch_id=batch_id, db=db, api=Api(), paths=paths,
        bundle=bundle, remote=remote, receipt=receipt, inputs=inputs, publication=publication)
    db.close()


def test_verified_remote_closure_evicts_only_owned_files_and_preserves_database(setup):
    protected = setup.runtime / "weights.json"
    protected.write_bytes(b"untouched weights")
    other = setup.runtime / "receipts" / ("f" * 32 + ".json")
    other.write_bytes(b"other batch")
    result = module.verify_and_evict_published_batch(setup.db, setup.runtime, setup.batch_id, api=setup.api)
    assert result["status"] == "evicted" and result["deleted_bytes"] > 0
    assert all(not path.exists() for path in setup.paths.values())
    assert protected.read_bytes() == b"untouched weights" and other.read_bytes() == b"other batch"
    status, plan, verification = setup.db.execute("SELECT status,plan,remote_verification FROM legacy_span_evictions").fetchone()
    assert status == "evicted"
    assert json.loads(plan)["publication"] == setup.publication
    assert len(json.loads(verification)["files"]) == 3
    assert setup.db.execute("SELECT status,publication FROM batches").fetchone() == ("published", encoded(setup.publication).decode())
    assert module.verify_and_evict_published_batch(setup.db, setup.runtime, setup.batch_id, api=setup.api)["status"] == "already_evicted"


@pytest.mark.parametrize("fault", ["missing", "digest", "size", "duplicate"])
def test_remote_failure_keeps_every_local_file(setup, fault):
    if fault == "missing":
        setup.remote.pop()
    elif fault == "digest":
        setup.remote[1]["lfs"]["sha256"] = "0" * 64
    elif fault == "size":
        setup.remote[0]["size"] += 1
    else:
        setup.remote.append(dict(setup.remote[0]))
    with pytest.raises(ValueError):
        module.verify_and_evict_published_batch(setup.db, setup.runtime, setup.batch_id, api=setup.api)
    assert all(path.exists() for path in setup.paths.values())
    assert not setup.db.execute("SELECT * FROM legacy_span_evictions").fetchall()


def test_partial_unlink_recovers_from_durable_journal_without_batch_receipt(setup, monkeypatch):
    unlink, calls = module.os.unlink, []
    def fail_second(path, **kwargs):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("simulated interruption")
        return unlink(path, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "unlink", fail_second)
        with pytest.raises(OSError, match="simulated"):
            module.verify_and_evict_published_batch(setup.db, setup.runtime, setup.batch_id, api=setup.api)
    assert not setup.paths["receipt"].exists()
    assert setup.db.execute("SELECT status FROM legacy_span_evictions").fetchone()[0] == "verified"
    result = module.verify_and_evict_published_batch(setup.db, setup.runtime, setup.batch_id, api=setup.api)
    assert result["status"] == "evicted"
    assert all(not path.exists() for path in setup.paths.values())
    assert len(setup.api.requests) == 4


@pytest.mark.parametrize("fault", ["batch_meta", "row", "raw_summary", "sample_map"])
def test_incomplete_remote_receipt_reconstruction_refuses_eviction(setup, fault):
    item = dict(setup.inputs[0])
    if fault == "batch_meta":
        item["batch_observation"] = {}
    elif fault == "row":
        item["autoencoder_observation"] = {}
    elif fault == "raw_summary":
        item["raw_batch_summary"] = {"sample_count": 2}
    else:
        item["raw_sample_evaluation"] = {}
    setup.bundle["census_rows"][0]["input_json"] = encoded(item).decode()
    with pytest.raises(ValueError, match="census"):
        module.verify_and_evict_published_batch(setup.db, setup.runtime, setup.batch_id, api=setup.api)
    assert all(path.exists() for path in setup.paths.values())


def test_changed_receipt_and_symlinks_are_not_deleted(setup):
    setup.paths["receipt"].write_bytes(b"different receipt")
    with pytest.raises(ValueError, match="durable database digest"):
        module.verify_and_evict_published_batch(setup.db, setup.runtime, setup.batch_id, api=setup.api)
    assert all(path.exists() for path in setup.paths.values())


def test_shared_or_unpublished_artifacts_refused(setup):
    setup.db.execute("UPDATE batches SET status='staged'")
    with pytest.raises(ValueError, match="explicitly published"):
        module.verify_and_evict_published_batch(setup.db, setup.runtime, setup.batch_id, api=setup.api)
    setup.db.execute("UPDATE batches SET status='published'")
    setup.db.execute("INSERT INTO batches SELECT ?,status,manifest,publication,receipt_sha256 FROM batches", ["e" * 32])
    with pytest.raises(ValueError, match="another batch"):
        module.verify_and_evict_published_batch(setup.db, setup.runtime, setup.batch_id, api=setup.api)


def test_cleanup_status_does_not_revisit_completed_journal(setup):
    assert len(module.cleanup_published_batches(setup.db, setup.runtime, api=setup.api)) == 1
    assert module.cleanup_published_batches(setup.db, setup.runtime, api=setup.api) == []


def test_campaign_paths_cannot_escape_or_alias(setup, tmp_path):
    with pytest.raises(ValueError, match="invalid campaign batch"):
        module.verify_and_evict_published_batch(setup.db, setup.runtime, "../outside", api=setup.api)
    alias = tmp_path / "alias"
    alias.symlink_to(setup.runtime, target_is_directory=True)
    with pytest.raises(ValueError, match="unaliased"):
        module.verify_and_evict_published_batch(setup.db, alias, setup.batch_id, api=setup.api)
    setup.paths["goals"].unlink()
    setup.paths["goals"].symlink_to(setup.paths["census"])
    with pytest.raises(OSError):
        module.verify_and_evict_published_batch(setup.db, setup.runtime, setup.batch_id, api=setup.api)


def test_legacy_full_batch_capture_is_also_losslessly_verified(setup):
    census = []
    for item in setup.inputs:
        old = {key: value for key, value in item.items() if key not in {"raw_batch_summary", "raw_sample_evaluation"}}
        old["raw_batch_evaluation"] = setup.receipt["raw_evaluation"]
        census.append({"input_json": encoded(old).decode()})
    module._coverage(setup.receipt, census)
