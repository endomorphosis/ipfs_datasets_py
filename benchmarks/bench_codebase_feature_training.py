"""Captured source -> bounded feature fitting -> independent checks -> edit/resume.

Small authored qualification fixture; no learned semantic decoding, production
promotion, behavioral authority or many-core training claim.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import bench_codebase_ir as base
from bench_codebase_current import open_index
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from ipfs_datasets_py.duckdb_control.codebase_evidence_index import CodebaseEvidenceIndex
from ipfs_datasets_py.logic.software_contracts import codebase_feature_training as training
from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import IntegerOffsetContract
from ipfs_datasets_py.logic.software_contracts.codebase_ir import StaleCodebaseError
from ipfs_datasets_py.logic.software_contracts.codebase_property_cache import CodebasePropertyCache
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
from ipfs_accelerate_py.agent_supervisor.planning.checked_integer_batch import (
    build_integer_offset_requirements, match_checked_integer_requirements,
)

VIEW = "worktree:codebase-feature-training-benchmark"


def clean():
    base.require(not any(row["owner_pid"] == os.getpid()
                         for row in base.get_global_resource_scheduler().active_leases()), "owned lease leaked")


def replay(request):
    def forbidden(*args, **kwargs):
        raise AssertionError("historical replay attempted numerical training or a solver")
    features.train_projection_features = forbidden
    from ipfs_datasets_py.logic.software_contracts import codebase_integer_profile as profile
    profile.execute_integer_offset = forbidden
    index, connection, _ = open_index(request["database"], request["artifacts"])
    try:
        head = CodebaseHead.from_dict(request["head"])
        index.observe_current(request["repository"], expected_head=head, timeout_seconds=30)
        with AutoencoderRegistry(request["models"], request["model_artifacts"]) as registry:
            restored = runtimes.load_version(registry, request["version_id"], domain="codebase_ir", version=training.RUNTIME_VERSION)
            base.require(features.digest(restored.state) == request["state_sha256"], "numerical state changed on restart")
            base.require(restored.training_report["codebase_cohort"]["cohort_sha256"] == request["cohort_sha256"], "cohort lost on restart")
        evidence = CodebaseEvidenceIndex(index.catalog)
        records = [evidence.get(cid, expected_head=head) for cid in request["receipts"]]
        base.require(all(record is not None for record in records), "indexed evidence lost on restart")
        clean()
        return {"correctness_passed": True, "state_sha256": features.digest(restored.state),
                "completed_epochs": restored.state["completed_epochs"], "records": len(records),
                "training_executed": False, "solver_executed": False, "inference_executed": False}
    finally:
        connection.close()


def run(root):
    repository = root / "repository"
    base.fixture(repository, 4, 1)
    for number, offset in enumerate((1, 2, 1, 2)):
        (repository / f"module_{number:03d}.py").write_text(f"def operation_{number}_0(n: int) -> int:\n    return n + {offset}\n")
    samples = [training.CodebaseFeatureSample(role, IntegerOffsetContract(
        f"module_{number:03d}.py", f"operation_{number}_0", "n", offset))
        for number, (role, offset) in enumerate((("training", 1), ("training", 2), ("tuning", 1), ("canary", 2)))]
    requirements = build_integer_offset_requirements([
        f"Under python-integer-offset@1, module_000.py::operation_0_0(n) must return n + {offset}." for offset in (1, 2)])
    database, artifacts = root / "ast.duckdb", root / "artifacts"
    models, model_artifacts = root / "models.duckdb", root / "model-artifacts"
    index, connection, _ = open_index(database, artifacts)
    cache = CodebasePropertyCache(root / "properties")
    rows = []
    try:
        head = index.prepare_current(repository, repository_id=VIEW, operation_id="initial", expected_head=None,
            limits=base.CodebaseScanLimits(max_entries=8, max_file_bytes=1024)).head
        with AutoencoderRegistry(models, model_artifacts) as registry:
            parent, original_state, basis = None, None, None
            for ordinal, stage in enumerate(("initial", "changed_source_resume")):
                if ordinal:
                    path = repository / "module_000.py"
                    path.write_bytes(path.read_bytes().replace(b"n + 1", b"n + 2"))
                    try:
                        index.observe_current(repository, expected_head=head, timeout_seconds=30)
                    except StaleCodebaseError:
                        pass
                    else:
                        raise AssertionError("old source head was accepted")
                    head = index.prepare_current(repository, repository_id=VIEW, operation_id="edit", expected_head=head,
                        limits=base.CodebaseScanLimits(max_entries=8, max_file_bytes=1024)).head
                started = time.perf_counter()
                trained = training.train_current_codebase_features(index, repository, expected_head=head,
                    registry=registry, directory=root / ("candidate-" + stage), samples=samples,
                    parent_version_id=parent, epochs=2 if ordinal == 0 else 1)
                training_seconds = time.perf_counter() - started
                base.require(trained["status"] == "candidate_registered", "candidate failed fixed canary gate")
                runtime = runtimes.load_version(registry, trained["candidate"]["version_id"], domain="codebase_ir", version=training.RUNTIME_VERSION)
                if ordinal:
                    base.require(trained["report"]["base_state_sha256"] == features.digest(original_state), "optimizer parent differs")
                    base.require(runtime.feature_space == basis, "feature basis changed on continuation")
                    base.require(runtime.state["completed_epochs"] > original_state["completed_epochs"], "no numerical continuation selected")
                else:
                    original_state, basis = runtime.state, runtime.feature_space
                    base.require(original_state["completed_epochs"] > 0, "no numerical fitting selected")
                started = time.perf_counter()
                matched = match_checked_integer_requirements(index=index, repository=repository, repository_id=VIEW,
                    requirements=requirements, expected_head=head, cache=cache, max_workers=2)
                proof_seconds = time.perf_counter() - started
                expected = ["conditional_contract_matched", "conditional_contract_refuted"]
                if ordinal:
                    expected.reverse()
                base.require([row["status"] for row in matched["requirement_results"]] == expected, "wrong source-property outcomes")
                base.require(not matched["current_facts"] and len(matched["residual_requirements"]) == 2, "conditional results gained runtime authority")
                base.require(all(row["solver_replayed"] for row in matched["verification_batch"]["results"]), "native proof bypass")
                parent = trained["candidate"]["version_id"]
                rows.append({"stage": stage, "training_seconds": training_seconds, "proof_matching_seconds": proof_seconds,
                             "training": trained, "matching": matched, "correctness_passed": True})
                clean()
                print(f"stage={stage} train={training_seconds:.3f}s checks={proof_seconds:.3f}s", file=sys.stderr)
            request = {"models": str(models), "model_artifacts": str(model_artifacts), "database": str(database),
                "artifacts": str(artifacts), "repository": str(repository), "head": head.to_dict(), "version_id": parent,
                "state_sha256": features.digest(runtime.state), "cohort_sha256": trained["cohort_sha256"],
                "receipts": matched["verification_batch"]["evidence_receipt_cids"]}
    finally:
        connection.close()
    path = root / "replay.json"
    path.write_text(json.dumps(request))
    child = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--replay", str(path)],
                           capture_output=True, text=True, timeout=60)
    base.require(child.returncode == 0, child.stderr[-8000:])
    return rows, json.loads(child.stdout.splitlines()[-1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    if args.replay:
        print(json.dumps(replay(json.loads(args.replay.read_text()))))
        return
    if args.output is None:
        parser.error("--output required")
    base.require(base.get_global_resource_scheduler().config.proof_safety_enabled, "default resource safety disabled")
    started = datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix="codebase-feature-benchmark-") as directory:
        stages, restarted = run(Path(directory))
    sources = [Path(__file__).resolve(), Path(training.__file__), Path(features.__file__), Path(runtimes.__file__),
               Path(training.__file__).with_name("codebase_feature_worker.py")]
    report = {"schema": "codebase-feature-training-benchmark@1", "started_at_utc": started,
        "correctness_passed": True, "stages": stages, "fresh_process": restarted,
        "source_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        "configuration": {"scheduler": "shared_default", "resource_safety_enabled": True, "source_files": 4,
            "training_sources": 2, "tuning_sources": 1, "canary_sources": 1, "latent_width": 8,
            "native_training_processes": 1, "torch_threads": 1, "proof_workers": 2, "ast_duckdb": base.DB_CONFIG},
        "qualification_limits": [
            "One tiny authored run, not a throughput/scaling or semantic generalization claim.",
            "Learned compiler features and deterministic source-property checks are independent. No learned feature becomes a formal proof or planner fact.",
            "Fixed tuning and canary sources are not independent semantic/generalization populations; canary acceptance gates repeated candidate registration.",
            "No active model head is promoted; old-source refusal and historical model/evidence restart are distinct from production admission.",
            "Default pressure sensing remains on; no deliberate external host stress was induced.",
            "Numerical worker has hard per-process virtual-memory/CPU/time/file bounds and sampled RSS guard; parent Python memory remains cooperative.",
            "Fresh-process replay only loads the model and historical evidence, with training/solver execution forbidden; inference replay is covered separately in runtime tests.",
            "Temporary fixtures are removed after restart; retained reports contain metadata rather than every model/database artifact.",
        ]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"correctness_passed": True, "stages": [{key: row[key] for key in
        ("stage", "training_seconds", "proof_matching_seconds")} for row in stages], "fresh_process": restarted}, indent=2))


if __name__ == "__main__":
    main()
