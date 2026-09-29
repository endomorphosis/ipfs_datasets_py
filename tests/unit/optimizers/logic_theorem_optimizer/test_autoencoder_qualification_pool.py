"""Sealed qualification recovery and bounded spawn contracts; all work injected."""
from concurrent.futures import Future
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_qualification_pool as pool
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_candidate_qualification as candidate
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_incremental_training as inc


MANIFEST = {"sha256": "producer-fixture", "file_count": 1}


class Executor:
    """Synchronous test double, not native process evidence."""
    calls = []

    def __init__(self, **kwargs):
        self.calls.append(kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def submit(self, function, *args):
        future = Future()
        try:
            future.set_result(function(*args))
        except Exception as exc:
            future.set_exception(exc)
        return future


def _job(tmp_path, name="one"):
    return {"run_id": name, "training_job_sha256": "training", "qualification_policy_sha256": "policy",
            "candidate_version_id": "candidate-" + name,
            "candidate_artifact": {"sha256": "a" * 64, "bytes": 1, "path": "/not-read"},
            "checkpoint_dependencies": [], "samples": [{"text": "fixture " + name}],
            "heldout_samples": [], "model_config": {}, "lake_timeout_seconds": 60,
            "output_directory": str(tmp_path / name)}


def _qualifier(artifact, version, samples, directory, **kwargs):
    directory.mkdir()
    inc._write(directory / "qualification.json", {"candidate": version, "samples": samples, "admitted": False})
    project = directory / "training-0/lake-0"
    project.mkdir(parents=True)
    (project / "Legal.lean").write_text("-- injected, never Lake evidence\n")
    (project / "lake.log").write_text("injected\n")
    (project / ".lake").mkdir()
    (project / ".lake/disposable.olean").write_bytes(b"compiled products not sealed")


@pytest.fixture(autouse=True)
def injected(monkeypatch):
    monkeypatch.setattr(pool.native_pool, "_package_manifest", lambda: dict(MANIFEST))
    monkeypatch.setattr(candidate, "qualify_candidate", _qualifier)
    Executor.calls.clear()


def test_completed_worker_replays_only_exact_request_and_evidence(tmp_path, monkeypatch):
    job = _job(tmp_path)
    first = pool._execute_qualification_job(job, MANIFEST)
    assert first == {"run_id": "one", "recovered": False}
    monkeypatch.setattr(candidate, "qualify_candidate", lambda *a, **kw: pytest.fail("duplicate evaluation"))
    assert pool._execute_qualification_job(job, MANIFEST)["recovered"] is True
    seal = json.loads((Path(job["output_directory"]) / pool.SEAL_NAME).read_text())
    assert seal["job_sha256"] == inc._sha(job)
    assert set(seal["evidence"]) == {"qualification.json", "training-0/lake-0/Legal.lean", "training-0/lake-0/lake.log"}
    with pytest.raises(inc.IncrementalTrainingError, match="binding or evidence"):
        pool.recover_qualification({**job, "model_config": {"different": True}}, MANIFEST)


@pytest.mark.parametrize("path", ["qualification.json", "training-0/lake-0/Legal.lean", "training-0/lake-0/lake.log", pool.SEAL_NAME])
def test_receipt_proof_and_seal_tampering_fail_closed(tmp_path, path):
    job = _job(tmp_path)
    pool._execute_qualification_job(job, MANIFEST)
    (Path(job["output_directory"]) / path).write_text("{}")
    with pytest.raises(inc.IncrementalTrainingError, match="binding or evidence"):
        pool.recover_qualification(job, MANIFEST)


def test_unfinished_output_and_missing_worker_seal_require_recovery(tmp_path, monkeypatch):
    job = _job(tmp_path)
    Path(job["output_directory"]).mkdir()
    with pytest.raises(inc.IncrementalTrainingError, match="unfinished qualification"):
        pool._execute_qualification_job(job, MANIFEST)
    missing = _job(tmp_path, "missing")
    with pytest.raises(inc.IncrementalTrainingError, match="omitted its sealed completion"):
        pool.run_qualification_jobs([missing], max_workers=2, expected_manifest=MANIFEST,
            executor_factory=Executor, worker_function=lambda job, manifest: {"run_id": job["run_id"]})


def test_evidence_symlink_rejected(tmp_path):
    job = _job(tmp_path)
    pool._execute_qualification_job(job, MANIFEST)
    path = Path(job["output_directory"]) / "training-0/lake-0/lake.log"
    outside = tmp_path / "outside.log"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        pool.recover_qualification(job, MANIFEST)


@pytest.mark.parametrize("phase", ["before", "during"])
def test_source_drift_cannot_seal_a_completion(tmp_path, monkeypatch, phase):
    manifest = dict(MANIFEST)
    monkeypatch.setattr(pool.native_pool, "_package_manifest", lambda: dict(manifest))
    job = _job(tmp_path)
    if phase == "before":
        manifest["sha256"] = "changed"
    else:
        def changed(*args, **kwargs):
            _qualifier(*args, **kwargs)
            manifest["sha256"] = "changed"
        monkeypatch.setattr(candidate, "qualify_candidate", changed)
    with pytest.raises(inc.IncrementalTrainingError, match="producer source changed"):
        pool._execute_qualification_job(job, MANIFEST)
    assert not (Path(job["output_directory"]) / pool.SEAL_NAME).exists()


def test_default_executor_requests_spawn_and_stable_result_order(tmp_path, monkeypatch):
    monkeypatch.setattr(pool, "ProcessPoolExecutor", Executor)
    jobs = [_job(tmp_path, "second"), _job(tmp_path, "first")]
    receipts, report = pool.run_qualification_jobs(jobs, max_workers=2, expected_manifest=MANIFEST)
    assert Executor.calls[0]["mp_context"].get_start_method() == "spawn"
    assert [receipt["candidate"] for receipt in receipts] == ["candidate-second", "candidate-first"]
    assert report["run_ids"] == ["second", "first"]
    assert report["registry_writes_in_workers"] is False
    assert report["execution_strategy"] == "spawned_qualification_wave"


def test_worker_failure_leaves_successful_sibling_sealed_without_owner_mutation(tmp_path):
    jobs = [_job(tmp_path, "successful"), _job(tmp_path, "failed")]
    def worker(job, manifest):
        if job["run_id"] == "failed":
            raise RuntimeError("injected worker loss")
        return pool._execute_qualification_job(job, manifest)
    with pytest.raises(RuntimeError, match="worker loss"):
        pool.run_qualification_jobs(jobs, max_workers=2, expected_manifest=MANIFEST,
            executor_factory=Executor, worker_function=worker)
    assert pool.recover_qualification(jobs[0], MANIFEST)["candidate"] == "candidate-successful"
    assert not list(tmp_path.rglob("*.duckdb"))


@pytest.mark.parametrize("workers,count", [(True, 1), (1, 1), (33, 1), (2, 3), (2, 0)])
def test_invalid_wave_bounds_rejected(tmp_path, workers, count):
    with pytest.raises(inc.IncrementalTrainingError, match="width"):
        pool.run_qualification_jobs([_job(tmp_path, str(index)) for index in range(count)],
            max_workers=workers, expected_manifest=MANIFEST, executor_factory=Executor)


def test_output_root_alias_rejected_before_qualification(tmp_path):
    job = _job(tmp_path)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    Path(job["output_directory"]).symlink_to(outside, target_is_directory=True)
    with pytest.raises(inc.IncrementalTrainingError, match="aliases another directory"):
        pool._execute_qualification_job(job, MANIFEST)
    assert not list(outside.iterdir())


def test_missing_completed_output_and_duplicate_output_fail_closed(tmp_path):
    import shutil
    job = _job(tmp_path)
    pool._execute_qualification_job(job, MANIFEST)
    shutil.rmtree(job["output_directory"])
    assert pool.recover_qualification(job, MANIFEST) is None
    with pytest.raises(inc.IncrementalTrainingError, match="duplicate qualification"):
        pool.run_qualification_jobs([job, {**job, "run_id": "different"}],
            max_workers=2, expected_manifest=MANIFEST, executor_factory=Executor)
