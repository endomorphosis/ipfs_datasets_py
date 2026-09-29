"""Spawned, immutable candidate qualification; registry writes stay in the owner.

Seals permit an owner to recover a completed worker response. They attest the
exact output bytes and request, never turn a failed gate into an admission.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import time

from . import autoencoder_incremental_training as inc
from . import autoencoder_native_pool as native_pool

SCHEMA = "autoencoder-qualification-completion/v1"
SEAL_NAME = "qualification-completion.json"
MAX_EVIDENCE_FILES = 8192
MAX_EVIDENCE_BYTES = 256 * 1024 * 1024


def _read(path, maximum=MAX_EVIDENCE_BYTES):
    from ...huggingface.publisher import _read_regular_file_nofollow_components
    return _read_regular_file_nofollow_components(Path(path).absolute(),
        label="qualification completion evidence", maximum_bytes=maximum)


def _ref(raw):
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _guard(manifest):
    if native_pool._package_manifest() != manifest:
        raise inc.IncrementalTrainingError("qualification pool producer source changed; start a fresh cycle")


def _evidence(directory):
    """Seal portable evidence, excluding disposable Lake compilation products."""
    entries, total = {}, 0
    for root, directories, files in os.walk(directory, followlinks=False):
        directories[:] = [name for name in directories if name != ".lake"]
        for name in directories:
            if (Path(root) / name).is_symlink():
                raise inc.IncrementalTrainingError("qualification evidence directory is a symlink")
        for name in files:
            path = Path(root) / name
            relative = path.relative_to(directory).as_posix()
            if relative == SEAL_NAME:
                continue
            raw = _read(path)
            total += len(raw)
            entries[relative] = _ref(raw)
            if len(entries) > MAX_EVIDENCE_FILES or total > MAX_EVIDENCE_BYTES:
                raise inc.IncrementalTrainingError("qualification evidence exceeds sealed bound")
    if "qualification.json" not in entries:
        raise inc.IncrementalTrainingError("qualification completion receipt missing")
    return entries


def recover_qualification(job, manifest):
    """Return only a completely sealed, same-request, same-source result."""
    _guard(manifest)
    directory = Path(job["output_directory"])
    if directory.is_symlink() or directory.absolute() != directory.resolve():
        raise inc.IncrementalTrainingError("qualification output path aliases another directory")
    seal_path = directory / SEAL_NAME
    if not seal_path.exists():
        if directory.exists():
            raise inc.IncrementalTrainingError("unfinished qualification requires recovery: " + job["run_id"])
        return None
    seal = json.loads(_read(seal_path, 16 * 1024 * 1024))
    expected = {"schema_version": SCHEMA, "job_sha256": inc._sha(job),
                "producer_manifest": manifest, "evidence": _evidence(directory)}
    if seal != expected:
        raise inc.IncrementalTrainingError("sealed qualification binding or evidence changed")
    receipt = json.loads(_read(directory / "qualification.json"))
    _guard(manifest)
    return receipt


def _execute_qualification_job(job, manifest):
    from .autoencoder_candidate_qualification import qualify_candidate
    recovered = recover_qualification(job, manifest)
    if recovered is not None:
        return {"run_id": job["run_id"], "recovered": True}
    directory = Path(job["output_directory"])
    qualify_candidate(job["candidate_artifact"], job["candidate_version_id"],
        job["samples"], directory, checkpoint_dependencies=job["checkpoint_dependencies"],
        model_config=job["model_config"], heldout_samples=job["heldout_samples"],
        lake_timeout_seconds=job["lake_timeout_seconds"])
    _guard(manifest)
    seal = {"schema_version": SCHEMA, "job_sha256": inc._sha(job),
            "producer_manifest": manifest, "evidence": _evidence(directory)}
    inc._write(directory / SEAL_NAME, seal)
    _guard(manifest)
    return {"run_id": job["run_id"], "recovered": False}


def run_qualification_jobs(jobs, *, max_workers, expected_manifest,
                           executor_factory=None, worker_function=_execute_qualification_job):
    """Bound one process wave; collect in request order, never receive a registry.

    Worker failures leave any successful siblings sealed for verified replay.
    No database completion or artifact staging occurs inside this function.
    """
    if type(max_workers) is not int or not 2 <= max_workers <= 32 or not 1 <= len(jobs) <= max_workers:
        raise inc.IncrementalTrainingError("invalid qualification process wave width")
    if (len({job["run_id"] for job in jobs}) != len(jobs)
            or len({job["output_directory"] for job in jobs}) != len(jobs)):
        raise inc.IncrementalTrainingError("duplicate qualification job or output")
    _guard(expected_manifest)
    started = time.monotonic()
    factory = executor_factory or ProcessPoolExecutor
    arguments = {"max_workers": max_workers}
    if executor_factory is None:
        arguments["mp_context"] = multiprocessing.get_context("spawn")
    with factory(**arguments) as executor:
        futures = [executor.submit(worker_function, job, expected_manifest) for job in jobs]
        results = [future.result() for future in futures]
    _guard(expected_manifest)
    if [row.get("run_id") for row in results] != [job["run_id"] for job in jobs]:
        raise inc.IncrementalTrainingError("qualification worker result identity changed")
    receipts = [recover_qualification(job, expected_manifest) for job in jobs]
    if any(receipt is None for receipt in receipts):
        raise inc.IncrementalTrainingError("qualification worker omitted its sealed completion")
    return receipts, {"max_workers": max_workers, "job_count": len(jobs),
        "run_ids": [job["run_id"] for job in jobs], "elapsed_seconds": time.monotonic() - started,
        "execution_strategy": "spawned_qualification_wave", "producer_manifest": expected_manifest,
        "registry_writes_in_workers": False, "admitted": False}
