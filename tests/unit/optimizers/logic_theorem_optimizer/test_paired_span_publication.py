"""Verify real Arrow bundles survive upload, interruption and local eviction."""
import hashlib
import json
from types import SimpleNamespace

import duckdb
import pytest

from ipfs_datasets_py.logic.autoformal.paired_span_census import build_paired_census, write_paired_census_bundle
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import paired_span_publication as module
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_publication as cleanup


class Api:
    def __init__(self):
        self.objects = {}
        self.sha = "a" * 40
        self.commits = 0
        self.omit = None

    def repo_info(self, **kwargs):
        assert kwargs.get("revision", self.sha) == self.sha
        return SimpleNamespace(sha=self.sha)

    def get_paths_info(self, **kwargs):
        assert kwargs["revision"] == self.sha
        return [SimpleNamespace(path=path, size=len(self.objects[path]),
                 lfs={"sha256": hashlib.sha256(self.objects[path]).hexdigest()}, blob_id=None)
                for path in kwargs["paths"] if path in self.objects and path != self.omit]

    def create_commit(self, **kwargs):
        assert kwargs["parent_commit"] == self.sha
        for operation in kwargs["operations"]:
            self.objects[operation.path_in_repo] = operation.path_or_fileobj
        self.commits += 1
        self.sha = "b" * 40
        return SimpleNamespace(oid=self.sha)


@pytest.fixture
def bundle(tmp_path):
    (tmp_path / "receipts").mkdir()
    batch = "c" * 32
    receipt = {"rows": [{"source_span_id": "test", "text": "The agency shall retain records."}],
               "raw_evaluation": {"vectors": [0.1, 0.2], "metrics": {"loss": 0.7}},
               "campaign": {"batch_id": batch}, "admitted": False}
    row = {**receipt["rows"][0], "compiler_result": {"compiler_status": "abstain", "reason": "no_parser_elements"},
           "autoencoder_observation": {"raw_decoder": {"embedding": [0.1, 0.2]}}}
    built = build_paired_census([row], original_receipt=receipt, code_identity="code", model_identity="model")
    written = write_paired_census_bundle(built, tmp_path / "outbox")
    receipt_path = tmp_path / "receipts" / (batch + ".json")
    receipt_path.write_text(json.dumps(receipt))
    return SimpleNamespace(root=tmp_path, batch=batch, receipt=receipt, receipt_path=receipt_path,
                           manifest=written["manifest"]["path"], built=built)


def test_upload_verifies_four_objects_and_retry_is_idempotent(bundle):
    api = Api()
    result = module.publish_paired_manifest(bundle.manifest, upload=True, api=api)
    assert result["uploaded"] is True and result["admitted"] is False
    assert len(api.objects) == 4 and api.commits == 1
    assert module.publish_paired_manifest(bundle.manifest, upload=True, api=api) == result
    assert api.commits == 1


def test_missing_remote_artifact_does_not_create_publication_receipt(bundle):
    api = Api()
    manifest = json.loads(open(bundle.manifest).read())
    api.omit = manifest["tables"]["artifacts"]["path_in_repo"]
    with pytest.raises(ValueError, match="missing"):
        module.publish_paired_manifest(bundle.manifest, upload=True, api=api)
    assert not __import__("pathlib").Path(str(bundle.manifest) + ".publication.json").exists()


def test_conflicting_remote_path_is_never_overwritten(bundle):
    api = Api()
    manifest = json.loads(open(bundle.manifest).read())
    api.objects[manifest["tables"]["paired_spans"]["path_in_repo"]] = b"conflicting data"
    with pytest.raises(ValueError, match="conflicts"):
        module.publish_paired_manifest(bundle.manifest, upload=True, api=api)
    assert api.commits == 0


def _published_db(bundle, result):
    db = duckdb.connect()
    db.execute("CREATE TABLE batches(id VARCHAR,status VARCHAR,manifest VARCHAR,publication VARCHAR,receipt_sha256 VARCHAR)")
    db.execute("INSERT INTO batches VALUES (?, 'published', ?, ?, ?)", [bundle.batch, bundle.manifest,
               json.dumps(result), hashlib.sha256(bundle.receipt_path.read_bytes()).hexdigest()])
    return db


def test_remote_verified_cleanup_preserves_complete_receipt_and_recovers(bundle, monkeypatch):
    api = Api()
    result = module.publish_paired_manifest(bundle.manifest, upload=True, api=api)
    db = _published_db(bundle, result)
    original_unlink, calls = cleanup.os.unlink, []
    def interrupted(path, **kwargs):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("interrupted")
        return original_unlink(path, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(cleanup.os, "unlink", interrupted)
        with pytest.raises(OSError, match="interrupted"):
            cleanup.verify_and_evict_published_batch(db, bundle.root, bundle.batch, api=api)
    assert db.execute("SELECT status FROM legacy_span_evictions").fetchone()[0] == "verified"
    result = cleanup.verify_and_evict_published_batch(db, bundle.root, bundle.batch, api=api)
    assert result["status"] == "evicted"
    assert not list((bundle.root / "outbox").iterdir())
    assert not bundle.receipt_path.exists()
    assert len(api.objects) == 4
    db.close()


def test_cleanup_refuses_unarchived_evidence(bundle):
    api = Api()
    result = module.publish_paired_manifest(bundle.manifest, upload=True, api=api)
    bundle.receipt["new_evidence"] = "not captured in artifact"
    bundle.receipt_path.write_text(json.dumps(bundle.receipt))
    db = _published_db(bundle, result)
    with pytest.raises(ValueError, match="full producer receipt"):
        cleanup.verify_and_evict_published_batch(db, bundle.root, bundle.batch, api=api)
    assert bundle.receipt_path.exists()
    db.close()
