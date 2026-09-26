"""Synthetic owner compaction fixtures; no native training or inference.

The original verifier body is frozen below to compare complete owner summaries
and artifact bytes independently of the candidate's compaction control flow.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator as coordinator
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_sparse_checkpoint as sparse
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_coordinator import (
    ImmediateExecutor, _prepare, _prepare_sparse, _prepare_child, _sparse_trainer, _trainer,
)

_ORIGINAL_COORDINATOR_SHA256 = 'db12aaf0faf6ef7c0deace1ff17fe0f3fd7dcbd424b5c06a510cc81ec611e93a'
_OLD_VERIFY_SHA256 = 'd9fdd24788919d919ef615e8f8098e3e4a1901c16ecde7aa781f50d88f9cfeb0'
_OLD_VERIFY_SOURCE = 'def _verify_and_stage_patches(registry: Any, spec: TrainingJobSpec, receipt: Mapping[str, Any],\n                              policy: SparseCheckpointPolicy) -> tuple[dict[str, Any], dict[str, Any] | None]:\n    """Replay accepted updates before staging a manifest or compacted checkpoint.\n\n    Full candidates keep the previous byte and state checks. Sparse candidates\n    seal the exact materialized bytes without writing those bytes on each job.\n    The owner chooses compaction independently of worker artifact descriptors.\n    """\n    segments = receipt.get("sparse_patch_segments")\n    if not isinstance(segments, list):\n        raise TrainingCoordinationError("sparse_patch_segments must be an array")\n    if not spec.capture_sparse_patches:\n        if segments:\n            raise TrainingCoordinationError("unexpected sparse segments without capture enabled")\n        return {"sparse_replay_verified": False, "sparse_patch_artifacts": [],\n                "checkpoint_storage": "full_json", "checkpoint_dependencies": []}, None\n    if len(segments) != receipt["optimizer_accepted_epochs"]:\n        raise TrainingCoordinationError("sparse segment count differs from accepted epochs")\n    from .modal_autoencoder_patch_codec import MAX_PATCH_BYTES, decode_patch, replay_patch\n    from .modal_autoencoder_sparse_checkpoint import (\n        checkpoint_identity, encode_manifest, resolve_checkpoint, write_checkpoint,\n    )\n\n    started = time.perf_counter()\n    references = [spec.base_checkpoint, *spec.base_checkpoint_dependencies]\n    paths = {ref.sha256: ref for ref in references}\n\n    def resolver(reference: Mapping[str, Any]) -> Path:\n        bound = paths.get(reference["sha256"])\n        if bound is None or bound.bytes != reference["bytes"]:\n            raise TrainingCoordinationError("checkpoint dependency is missing from the job binding")\n        descriptor = registry.verify_artifact(reference)\n        if Path(bound.path).resolve() != registry.artifact_path(descriptor).resolve():\n            raise TrainingCoordinationError("checkpoint dependency is not owner staged")\n        return registry.artifact_path(descriptor)\n\n    resolved = None\n    if "candidate_storage" in spec.to_dict():\n        resolved = resolve_checkpoint({"sha256": spec.base_checkpoint.sha256, "bytes": spec.base_checkpoint.bytes},\n                                      resolver=resolver)\n        if {(ref["sha256"], ref["bytes"]) for ref in resolved.artifacts} != {(ref.sha256, ref.bytes) for ref in references}:\n            raise TrainingCoordinationError("checkpoint dependency closure contains unused artifacts")\n        state = resolved.state\n    else:\n        from .modal_autoencoder import ModalAutoencoderTrainingState\n        base = _read_bounded(Path(spec.base_checkpoint.path), min(spec.base_checkpoint.bytes, registry.max_artifact_bytes))\n        if len(base) != spec.base_checkpoint.bytes or _sha(base) != spec.base_checkpoint.sha256:\n            raise TrainingCoordinationError("base changed before sparse replay")\n        state = ModalAutoencoderTrainingState.from_dict(_read_json(base))\n        del base\n    if state.state_identity_record().to_dict() != receipt["base_state_identity"]:\n        raise TrainingCoordinationError("sparse base state identity differs from receipt")\n    staged = []\n    for index, descriptor in enumerate(segments):\n        if not isinstance(descriptor, dict) or type(descriptor.get("bytes")) is not int or not 0 < descriptor["bytes"] <= MAX_PATCH_BYTES:\n            raise TrainingCoordinationError("invalid sparse segment descriptor or byte bound")\n        path = Path(descriptor.get("path", ""))\n        expected_path = Path(spec.output_directory) / f"accepted-{index:06d}.patch.json"\n        if path.is_symlink() or path.resolve() != expected_path.resolve():\n            raise TrainingCoordinationError("sparse segment is outside its ordered attempt path")\n        raw = _read_bounded(path, descriptor["bytes"])\n        if len(raw) != descriptor.get("bytes") or _sha(raw) != descriptor.get("sha256"):\n            raise TrainingCoordinationError("sparse segment size or SHA-256 mismatch")\n        segment = decode_patch(raw)\n        expected_provenance = {"job_id": spec.job_id, "run_id": spec.run_id,\n                               "job_spec_sha256": spec.canonical_sha256,\n                               "commit_label": descriptor.get("capture_context", {}).get("label", "")}\n        if dict(segment.provenance) != expected_provenance:\n            raise TrainingCoordinationError("sparse segment job/attempt provenance mismatch")\n        context = descriptor.get("capture_context", {})\n        for name, expected in {"base_state_identity": segment.base_state_identity,\n                               "result_state_identity": segment.result_state_identity,\n                               "base_revision": segment.patch.base_revision,\n                               "result_revision": segment.patch.result_revision}.items():\n            if context.get(name) != expected:\n                raise TrainingCoordinationError("sparse capture context differs from sealed segment")\n        replay_patch(state, segment, expected_base_version_id=spec.base_version_id, expected_sequence=index)\n        staged.append(registry.stage_artifact(path, descriptor["sha256"]))\n    candidate_limit = min(registry.max_artifact_bytes, 1024 * 1024) if spec.candidate_storage == "sparse" else registry.max_artifact_bytes\n    candidate_raw = _read_bounded(Path(receipt["candidate"]["path"]), candidate_limit)\n    if len(candidate_raw) != receipt["candidate"]["bytes"] or _sha(candidate_raw) != receipt["candidate"]["sha256"]:\n        raise TrainingCoordinationError("candidate changed before sparse replay comparison")\n    if spec.candidate_storage != "sparse" and _bytes(state.to_dict()) != _bytes(_read_json(candidate_raw)):\n        raise TrainingCoordinationError("sparse replay does not reconstruct the complete candidate")\n    if state.state_identity_record().to_dict() != receipt["candidate_state_identity"]:\n        raise TrainingCoordinationError("sparse replay candidate identity mismatch")\n    summary = {"sparse_replay_verified": True, "sparse_patch_artifacts": staged,\n               "sparse_patch_bytes": sum(item["bytes"] for item in staged)}\n    materialized = (checkpoint_identity(state) if resolved is not None\n                    else {key: receipt["candidate"][key] for key in ("sha256", "bytes")})\n    if "candidate_storage" in spec.to_dict():\n        if receipt.get("candidate_materialized_checkpoint") != materialized:\n            raise TrainingCoordinationError("sparse replay does not reconstruct the complete candidate bytes")\n        if receipt.get("base_materialized_checkpoint") != resolved.materialized_checkpoint:\n            raise TrainingCoordinationError("base materialized checkpoint differs from verified parent")\n    summary["candidate_materialized_checkpoint"] = materialized\n    if spec.candidate_storage != "sparse":\n        summary.update(checkpoint_storage="full_json", checkpoint_dependencies=[])\n        summary["sparse_replay_seconds"] = time.perf_counter() - started\n        return summary, None\n\n    assert resolved is not None\n    expected_manifest = encode_manifest(\n        parent={"sha256": spec.base_checkpoint.sha256, "bytes": spec.base_checkpoint.bytes},\n        base_version_id=spec.base_version_id, patches=staged,\n        materialized_checkpoint=materialized, state_identity=state.state_identity(),\n        result_revision=state.state_identity_record().to_dict()["revision"],\n        provenance={"job_id": spec.job_id, "run_id": spec.run_id, "job_spec_sha256": spec.canonical_sha256})\n    if candidate_raw != expected_manifest:\n        raise TrainingCoordinationError("sparse candidate manifest differs from verified parent and accepted patches")\n    depth = resolved.depth + 1\n    cumulative_bytes = resolved.total_patch_bytes + summary["sparse_patch_bytes"]\n    reasons = []\n    if depth >= policy.max_depth:\n        reasons.append("max_depth")\n    if cumulative_bytes >= resolved.anchor_checkpoint["bytes"] * policy.max_patch_fraction:\n        reasons.append("patch_fraction")\n    summary.update(\n        worker_candidate_artifact={key: receipt["candidate"][key] for key in ("sha256", "bytes")},\n        sparse_compaction_policy={"max_depth": policy.max_depth, "max_patch_fraction": policy.max_patch_fraction},\n        sparse_compaction_performed=bool(reasons), sparse_compaction_reasons=reasons,\n        candidate_chain_depth_before_compaction=depth,\n        candidate_cumulative_patch_bytes_before_compaction=cumulative_bytes)\n    if reasons:\n        with tempfile.TemporaryDirectory(prefix=".compact-", dir=registry.artifact_root) as directory:\n            written = write_checkpoint(state, Path(directory) / "candidate.state.json", expected_identity=materialized)\n            candidate = registry.stage_artifact(written["path"], written["sha256"])\n        if candidate != materialized:\n            raise TrainingCoordinationError("compacted checkpoint bytes differ from replay identity")\n        # Retain the small worker manifest as auditable evidence of compaction.\n        registry.stage_artifact(receipt["candidate"]["path"], receipt["candidate"]["sha256"])\n        summary.update(checkpoint_storage="full_json", checkpoint_dependencies=[],\n                       checkpoint_chain_depth=0, checkpoint_cumulative_patch_bytes=0,\n                       checkpoint_anchor=candidate)\n    else:\n        candidate = registry.stage_artifact(receipt["candidate"]["path"], receipt["candidate"]["sha256"])\n        closure = {ref["sha256"]: dict(ref) for ref in (*resolved.artifacts, *staged)}\n        summary.update(checkpoint_storage="sparse_manifest",\n                       checkpoint_dependencies=sorted(closure.values(), key=lambda ref: ref["sha256"]),\n                       checkpoint_chain_depth=depth, checkpoint_cumulative_patch_bytes=cumulative_bytes,\n                       checkpoint_anchor=dict(resolved.anchor_checkpoint))\n    summary["sparse_replay_seconds"] = time.perf_counter() - started\n    return summary, candidate\n'


def _old_verify():
    assert hashlib.sha256(_OLD_VERIFY_SOURCE.encode()).hexdigest() == _OLD_VERIFY_SHA256
    namespace = vars(coordinator).copy()
    exec(compile(_OLD_VERIFY_SOURCE, '<frozen-pre-single-serialization-owner>', 'exec'), namespace)
    return namespace['_verify_and_stage_patches']


def _without_timing(result):
    summary, descriptor = result
    assert summary.get('sparse_replay_seconds', 0) >= 0
    return {key: value for key, value in summary.items() if key != 'sparse_replay_seconds'}, descriptor


def _prepare_mode(registry, root, mode):
    if mode == 'sparse':
        return _prepare_sparse(registry, root)
    updates = {'schema_version': 'autoencoder-training-job-v2', 'capture_sparse_patches': True}
    if mode == 'modern-full':
        updates.update(schema_version='autoencoder-training-job-v3', candidate_storage='full')
    elif mode == 'no-capture':
        updates['capture_sparse_patches'] = False
    return _prepare(registry, root, job_updates=updates)


def _receipt(spec):
    return worker.execute_training_job(spec, trainer=_sparse_trainer if spec.capture_sparse_patches else _trainer)


def _count_owner_serializations(monkeypatch, function, *args):
    """Keep required parent-chain verification separate from the new endpoint.

    Worker serialization has already finished before this scope starts. Native
    serialization is counted at its byte-producing entry point, not by counting
    a replacement encoder, and both verifier bodies execute unchanged.
    """
    original_encode = sparse.canonical_checkpoint_bytes
    original_resolve = sparse.resolve_checkpoint
    counts = {'endpoint': 0, 'parent_chain': 0}
    resolving = False

    def encode(state):
        counts['parent_chain' if resolving else 'endpoint'] += 1
        return original_encode(state)

    def resolve(*values, **options):
        nonlocal resolving
        assert not resolving
        resolving = True
        try:
            return original_resolve(*values, **options)
        finally:
            resolving = False

    with monkeypatch.context() as patch:
        patch.setattr(sparse, 'canonical_checkpoint_bytes', encode)
        patch.setattr(sparse, 'resolve_checkpoint', resolve)
        result = function(*args)
    return result, counts


@pytest.mark.parametrize('mode,max_depth,fraction,reasons,old_count', [
    ('sparse', 1, 1.0, ['max_depth'], 2),
    ('sparse', 8, 0.001, ['patch_fraction'], 2),
    ('sparse', 1, 0.001, ['max_depth', 'patch_fraction'], 2),
    ('sparse', 8, 1.0, [], 1),
    ('modern-full', 1, 0.001, [], 1),
    ('legacy-full', 1, 0.001, [], 0),
    ('no-capture', 1, 0.001, [], 0),
])
def test_owner_summaries_and_artifacts_match_frozen_old_verifier_with_one_compaction_serialization(
        tmp_path, monkeypatch, mode, max_depth, fraction, reasons, old_count):
    with AutoencoderRegistry(tmp_path / 'registry.duckdb', tmp_path / 'artifacts') as registry:
        spec = _prepare_mode(registry, tmp_path, mode)
        receipt = _receipt(spec)
        policy = coordinator.SparseCheckpointPolicy(max_depth=max_depth, max_patch_fraction=fraction)
        original_base = Path(spec.base_checkpoint.path).read_bytes()
        old, old_calls = _count_owner_serializations(monkeypatch, _old_verify(), registry, spec, receipt, policy)
        current, current_calls = _count_owner_serializations(
            monkeypatch, coordinator._verify_and_stage_patches, registry, spec, receipt, policy)
        assert _without_timing(current) == _without_timing(old)
        assert old_calls == {'endpoint': old_count, 'parent_chain': 0}
        assert current_calls == {'endpoint': 1 if reasons else old_count, 'parent_chain': 0}
        summary, descriptor = current
        if mode == 'sparse':
            assert summary['sparse_compaction_reasons'] == reasons
            assert descriptor == registry.verify_artifact(descriptor)
            raw = registry.artifact_path(descriptor).read_bytes()
            if reasons:
                assert descriptor == receipt['candidate_materialized_checkpoint']
                assert raw.endswith(b'\n')
                assert json.loads(raw)['feature_embedding_weights']['fixture'] == [0.5, -0.25]
                assert summary['checkpoint_dependencies'] == []
                assert registry.verify_artifact(summary['worker_candidate_artifact'])
            else:
                assert raw == Path(receipt['candidate']['path']).read_bytes()
                assert summary['checkpoint_storage'] == 'sparse_manifest'
        else:
            assert descriptor is None
            assert summary['checkpoint_storage'] == 'full_json'
        assert Path(spec.base_checkpoint.path).read_bytes() == original_base
        assert registry.get_run(spec.run_id)['status'] == 'queued'
        assert registry.resolve_head('english-0', 'best')['version_id'] == spec.base_version_id
        assert list(registry.artifact_root.glob('.compact-*')) == []


def test_parent_chain_hashing_is_retained_and_counted_separately_from_compacted_endpoint(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / 'registry.duckdb', tmp_path / 'artifacts') as registry:
        parent = _prepare_sparse(registry, tmp_path)
        first = coordinator.run_training_jobs(registry, [parent], executor_factory=ImmediateExecutor,
            worker_function=_receipt, sparse_checkpoint_policy=coordinator.SparseCheckpointPolicy(max_patch_fraction=1.0))
        assert not first['failed']
        completed_parent = first['completed'][0]
        assert completed_parent['result']['checkpoint_storage'] == 'sparse_manifest'
        spec = _prepare_child(registry, tmp_path, completed_parent['version_id'])
        receipt = _receipt(spec)
        policy = coordinator.SparseCheckpointPolicy(max_depth=2, max_patch_fraction=1.0)
        old, old_calls = _count_owner_serializations(monkeypatch, _old_verify(), registry, spec, receipt, policy)
        current, current_calls = _count_owner_serializations(
            monkeypatch, coordinator._verify_and_stage_patches, registry, spec, receipt, policy)
        assert _without_timing(current) == _without_timing(old)
        assert old_calls == {'endpoint': 2, 'parent_chain': 1}
        assert current_calls == {'endpoint': 1, 'parent_chain': 1}
        assert current[0]['candidate_chain_depth_before_compaction'] == 2
        assert current[0]['sparse_compaction_reasons'] == ['max_depth']
        assert json.loads(registry.artifact_path(current[1]).read_bytes())['feature_embedding_weights']['fixture'] == [1.0, -0.25]
        assert not list(registry.artifact_root.glob('.compact-*'))


def test_actual_owner_completion_serializes_compacted_endpoint_once_and_reopens_exact_bytes(tmp_path, monkeypatch):
    database, artifacts = tmp_path / 'registry.duckdb', tmp_path / 'artifacts'
    with AutoencoderRegistry(database, artifacts) as registry:
        spec = _prepare_sparse(registry, tmp_path)
        receipts = []
        original_verify = coordinator._verify_and_stage_patches
        counts = []

        def injected_worker(current):
            receipt = _receipt(current)
            receipts.append(receipt)
            return receipt

        def verify(*args):
            result, observed = _count_owner_serializations(monkeypatch, original_verify, *args)
            counts.append(observed)
            return result

        monkeypatch.setattr(coordinator, '_verify_and_stage_patches', verify)
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
            worker_function=injected_worker,
            sparse_checkpoint_policy=coordinator.SparseCheckpointPolicy(max_depth=1, max_patch_fraction=1.0))
        assert not result['failed'], result
        assert counts == [{'endpoint': 1, 'parent_chain': 0}]
        completed = result['completed'][0]
        assert len(receipts) == 1
        assert completed['candidate'] == receipts[0]['candidate_materialized_checkpoint']
        raw = registry.artifact_path(completed['candidate']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == completed['candidate']['sha256']
        assert len(raw) == completed['candidate']['bytes']
        assert completed['result']['execution_mode'] == 'injected_test'
        assert completed['result']['admitted'] is False
        assert completed['result']['promotion_performed'] is False
        assert registry.resolve_head('english-0', 'best')['version_id'] == spec.base_version_id
        assert not list(artifacts.glob('.compact-*'))
    with AutoencoderRegistry(database, artifacts) as registry:
        saved = registry.get_run(spec.run_id)
        assert saved['status'] == 'completed'
        assert saved['result']['candidate_materialized_checkpoint'] == completed['candidate']
        assert registry.verify_artifact(completed['candidate']) == completed['candidate']
        assert registry.artifact_path(completed['candidate']).read_bytes() == raw
        assert registry.verify_artifact(saved['result']['worker_candidate_artifact'])
        assert registry.resolve_head('english-0', 'best')['version_id'] == spec.base_version_id


def _reseal_receipt(spec, receipt):
    Path(spec.output_directory, 'receipt.json').write_text(json.dumps(receipt, sort_keys=True))


def _is_scratch(path):
    return any(part.startswith('.compact-') for part in Path(path).parts)


@pytest.mark.parametrize('forgery', ['candidate-materialized', 'base-materialized', 'base-identity',
                                     'candidate-identity', 'manifest'])
def test_failed_binding_cannot_stage_compacted_candidate_or_complete_run(tmp_path, monkeypatch, forgery):
    with AutoencoderRegistry(tmp_path / 'registry.duckdb', tmp_path / 'artifacts') as registry:
        spec = _prepare_sparse(registry, tmp_path)
        original_base = Path(spec.base_checkpoint.path).read_bytes()

        def injected_worker(current):
            receipt = _receipt(current)
            if forgery == 'candidate-materialized':
                receipt['candidate_materialized_checkpoint']['sha256'] = 'f' * 64
            elif forgery == 'base-materialized':
                receipt['base_materialized_checkpoint']['sha256'] = 'f' * 64
            elif forgery in {'base-identity', 'candidate-identity'}:
                receipt['base_state_identity' if forgery == 'base-identity' else 'candidate_state_identity']['revision'] += 1
            else:
                path = Path(receipt['candidate']['path'])
                data = json.loads(path.read_bytes())
                data['base_version_id'] = 'different-registered-base'
                raw = json.dumps(data, sort_keys=True, separators=(',', ':')).encode()
                path.write_bytes(raw)
                receipt['candidate'].update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
            _reseal_receipt(current, receipt)
            return receipt

        staged = []
        original_stage = registry.stage_artifact

        def stage(path, expected_sha256=None):
            staged.append(Path(path))
            return original_stage(path, expected_sha256)

        monkeypatch.setattr(registry, 'stage_artifact', stage)
        monkeypatch.setattr(registry, 'complete_run', lambda *args, **kwargs: pytest.fail('completed invalid compaction'))
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
            worker_function=injected_worker,
            sparse_checkpoint_policy=coordinator.SparseCheckpointPolicy(max_depth=1, max_patch_fraction=1.0))
        assert not result['completed']
        assert len(result['failed']) == 1 and result['failed'][0]['failure_recorded'] is True
        assert registry.get_run(spec.run_id)['status'] == 'failed'
        assert not any(_is_scratch(path) or path.name == 'candidate.manifest.json' for path in staged)
        assert not list(registry.artifact_root.glob('.compact-*'))
        assert registry.resolve_head('english-0', 'best')['version_id'] == spec.base_version_id
        assert Path(spec.base_checkpoint.path).read_bytes() == original_base


@pytest.mark.parametrize('failure', ['write', 'fsync', 'stage', 'stage-corruption', 'stage-descriptor'])
def test_compaction_io_failure_cleans_private_scratch_and_cannot_complete(tmp_path, monkeypatch, failure):
    with AutoencoderRegistry(tmp_path / 'registry.duckdb', tmp_path / 'artifacts') as registry:
        spec = _prepare_sparse(registry, tmp_path)
        original_base = Path(spec.base_checkpoint.path).read_bytes()
        touched = []
        original_write = sparse.write_checkpoint
        original_stage = registry.stage_artifact
        original_fsync = os.fsync

        def write(state, destination, **kwargs):
            path = Path(destination)
            touched.append(path)
            assert _is_scratch(path) and path.parent.is_dir()
            if failure == 'write':
                path.write_bytes(b'partial-private-checkpoint')
                raise OSError('synthetic compaction write failure')
            return original_write(state, destination, **kwargs)

        def fsync(descriptor):
            path = Path(os.readlink(f'/proc/self/fd/{descriptor}'))
            if failure == 'fsync' and _is_scratch(path):
                assert path.read_bytes().endswith(b'\n')
                raise OSError('synthetic compaction fsync failure')
            return original_fsync(descriptor)

        def stage(path, expected_sha256=None):
            if _is_scratch(path):
                assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected_sha256
                if failure == 'stage':
                    raise OSError('synthetic compaction stage failure')
                if failure == 'stage-corruption':
                    raw = Path(path).read_bytes()
                    Path(path).write_bytes(b' ' + raw[1:])
                if failure == 'stage-descriptor':
                    # A real staged copy may survive; no rollback of CAS is
                    # claimed, but a mismatched return must never complete.
                    descriptor = original_stage(path, expected_sha256)
                    return {**descriptor, 'bytes': descriptor['bytes'] + 1}
            return original_stage(path, expected_sha256)

        monkeypatch.setattr(sparse, 'write_checkpoint', write)
        monkeypatch.setattr(os, 'fsync', fsync)
        monkeypatch.setattr(registry, 'stage_artifact', stage)
        monkeypatch.setattr(registry, 'complete_run', lambda *args, **kwargs: pytest.fail('completed failed compaction'))
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
            worker_function=_receipt,
            sparse_checkpoint_policy=coordinator.SparseCheckpointPolicy(max_depth=1, max_patch_fraction=1.0))
        assert not result['completed']
        assert len(result['failed']) == 1 and result['failed'][0]['failure_recorded'] is True
        assert registry.get_run(spec.run_id)['status'] == 'failed'
        assert len(touched) == 1
        assert not touched[0].exists() and not touched[0].parent.exists()
        assert not list(registry.artifact_root.glob('.compact-*'))
        assert not list(registry.artifact_root.glob('.stage-*'))
        assert registry.resolve_head('english-0', 'best')['version_id'] == spec.base_version_id
        assert Path(spec.base_checkpoint.path).read_bytes() == original_base


def test_reported_owner_replay_time_still_includes_private_compaction_cleanup(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / 'registry.duckdb', tmp_path / 'artifacts') as registry:
        spec = _prepare_sparse(registry, tmp_path)
        receipt = _receipt(spec)
        original_directory = coordinator.tempfile.TemporaryDirectory
        clock = [10.0]
        cleaned = []

        class TimedCleanup:
            def __init__(self, *args, **kwargs):
                self.directory = original_directory(*args, **kwargs)

            def __enter__(self):
                return self.directory.__enter__()

            def __exit__(self, *args):
                result = self.directory.__exit__(*args)
                cleaned.append(self.directory.name)
                clock[0] += 7.0
                return result

        monkeypatch.setattr(coordinator.tempfile, 'TemporaryDirectory', TimedCleanup)
        monkeypatch.setattr(coordinator.time, 'perf_counter', lambda: clock[0])
        summary, descriptor = coordinator._verify_and_stage_patches(registry, spec, receipt,
            coordinator.SparseCheckpointPolicy(max_depth=1, max_patch_fraction=1.0))
        assert summary['sparse_replay_seconds'] == 7.0
        assert len(cleaned) == 1 and not Path(cleaned[0]).exists()
        assert registry.verify_artifact(descriptor) == descriptor
