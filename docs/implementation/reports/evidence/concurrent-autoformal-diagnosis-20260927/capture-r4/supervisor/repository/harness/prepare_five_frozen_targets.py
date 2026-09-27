#!/usr/bin/env python3
"""Direct target preparation child; run only inside the existing reserved owner.

No training, weights, retries, sample selection, registry mutation, or upload.
The owner must enforce its whole-process deadline, RSS and directory census.
This child enforces a 30 MB per-file limit and verifies final artifact bytes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import stat
import sys
import time


ROOT = Path('/home/barberb/lift_coding/external/ipfs_datasets')
OWNED = ROOT / 'workspace/test-logs/federal-corpus-audits'
BRIDGES = ('modal_frame_logic', 'deontic_norms', 'fol_tdfol', 'cec_dcec', 'external_prover_router')
MAX_ARTIFACT_BYTES = 30_000_000


def digest(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def bounded_json(path: Path, expected: str, maximum: int = 4_000_000):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.resolve(strict=True) != path.absolute() or info.st_size > maximum:
        raise ValueError('input must be bounded canonical regular data')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('input digest differs')
    return json.loads(raw)


def package_manifest() -> dict[str, str]:
    package = ROOT / 'ipfs_datasets_py'
    result = {}
    for path in sorted(package.rglob('*.py')):
        if path.is_symlink() or not path.resolve().is_relative_to(package):
            raise ValueError('package source aliases another tree')
        if path.is_dir():
            continue
        result[path.relative_to(package).as_posix()] = digest(path)
    return result


def manifest_digest(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def write(path: Path, value: dict) -> None:
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    if len(raw) > 2_000_000:
        raise ValueError('preparation receipt exceeds metadata bound')
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--payload-sha256', required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    payload = bounded_json(args.payload, args.payload_sha256)
    if (payload.get('schema') != 'five-frozen-sample-direct-target-preparation/v1'
            or payload.get('launch_ready') is not True
            or payload.get('canonical_root') != str(ROOT)
            or payload.get('artifact_format') != 'bundle'
            or payload.get('artifact_max_bytes') != MAX_ARTIFACT_BYTES
            or payload.get('expected_unique_sample_count') != 5
            or payload.get('target_timeout_seconds') != 60
            or os.environ.get('IPFS_DATASETS_LEGAL_IR_TARGET_TIMEOUT_SECONDS') != '60'
            or payload.get('retries') != 0
            or payload.get('selection_frozen') is not True
            or not re.fullmatch('[0-9a-f]{64}', payload.get('expected_package_python_manifest_sha256', ''))):
        raise ValueError('preparation payload is not finalized for this bounded scope')
    prior = payload['parent_worker_receipt']
    parent_path = Path(prior['path'])
    parent = bounded_json(parent_path, prior['sha256'])
    if parent_path.stat().st_size != prior['bytes']:
        raise ValueError('frozen parent receipt size differs')
    job = parent['job_spec']
    if (payload['samples'] != job['samples'] or payload['validation_samples'] != job['validation_samples']
            or len(payload['samples']) != 3 or len(payload['validation_samples']) != 2
            or payload['training_config'] != job['training_config']
            or payload['parent_job_spec_canonical_sha256'] != parent['job_spec_canonical_sha256']):
        raise ValueError('frozen inputs or parent job identity differ')
    directory = args.output_directory.absolute()
    if directory.exists() or directory.is_symlink() or not directory.parent.is_dir():
        raise ValueError('output must be a new child of an existing owned attempt')
    if directory.resolve() != directory or not directory.is_relative_to(OWNED):
        raise ValueError('output must be canonical and inside the owned audit root')
    before = package_manifest()
    if manifest_digest(before) != payload['expected_package_python_manifest_sha256']:
        raise ValueError('reviewed package source manifest changed; no rehash fallback')
    for name, module in tuple(sys.modules.items()):
        if name == 'ipfs_datasets_py' or name.startswith('ipfs_datasets_py.'):
            filename = getattr(module, '__file__', None)
            if filename and not Path(filename).resolve().is_relative_to(ROOT / 'ipfs_datasets_py'):
                raise ValueError('foreign datasets module was loaded first')
    sys.path.insert(0, str(ROOT))
    sys.dont_write_bytecode = True
    os.environ.update({
        'IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE': '0',
        'IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI': '0',
        'IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS': '0',
        'IPFS_DATASETS_MODAL_AUTOENCODER_AUTO_CUDA': '0',
        'CUDA_VISIBLE_DEVICES': '', 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
        'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
    })
    soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    cap = min([MAX_ARTIFACT_BYTES] + [value for value in (soft, hard) if value != resource.RLIM_INFINITY])
    resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import (
        SampleRecord, TrainingConfig, TrainingJobSpec,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_target_preparation import (
        prepare_training_targets,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_bundle import load_target_bundle
    tree = require_workspace_logic_tree()
    if any(not Path(value).resolve().is_relative_to(ROOT / 'ipfs_datasets_py') for value in tree.values()):
        raise ValueError('canonical logic tree differs')
    if TrainingJobSpec.from_dict(job).canonical_sha256 != parent['job_spec_canonical_sha256']:
        raise ValueError('parent canonical job hash differs')
    config = TrainingConfig.from_dict(payload['training_config'])
    if (tuple(config.legal_ir_bridge_names) != BRIDGES or config.legal_ir_evaluate_provers is not False
            or config.legal_ir_parallel_workers != 1 or config.metric_disk_cache != 0
            or config.use_sample_memory is not False):
        raise ValueError('preparation bridge policy differs')
    rows = [SampleRecord.from_dict(row) for row in payload['samples']]
    validation = [SampleRecord.from_dict(row) for row in payload['validation_samples']]
    directory.mkdir()
    result = {
        'schema': 'five-frozen-sample-direct-target-observation/v1',
        'payload_sha256': args.payload_sha256, 'script_sha256': digest(Path(__file__)),
        'parent_worker_receipt': prior,
        'parent_job_spec_canonical_sha256': parent['job_spec_canonical_sha256'],
        'source_manifest_sha256': manifest_digest(before), 'source_file_count': len(before),
        'tree_pin': tree, 'sample_count': 5, 'training_sample_count': 3, 'validation_sample_count': 2,
        'ordered_training_samples': [asdict(row) for row in rows],
        'ordered_validation_samples': [asdict(row) for row in validation],
        'bridge_names': list(BRIDGES), 'legal_ir_evaluate_provers': False,
        'legal_ir_parallel_workers': 1, 'metric_disk_cache': 0, 'use_sample_memory': False,
        'cache_policy': 'direct preparation bypasses metric/multiview caches; OS cache uncontrolled',
        'artifact_max_bytes': MAX_ARTIFACT_BYTES, 'effective_rlimit_fsize': cap,
        'target_timeout_seconds': 60, 'previous_target_timeout_seconds': 15,
        'failure_disposition': 'retain all statuses and bridge failures; no retries or reselection',
        'artifact_observed_and_verified': False, 'all_requested_bridge_reports_received': False,
        'all_bridge_reports_accepted': False, 'source_unchanged': False,
        'base_checkpoint_loaded': False, 'training_executed': False,
        'heldout_canary_qualified': False, 'admitted': False, 'formalized': False,
        'promotion_performed': False, 'huggingface_upload_performed': False,
        'error': None,
    }
    started = time.perf_counter()
    exit_code = 1
    try:
        prepared = prepare_training_targets(rows, directory / 'targets.bundle',
            validation_records=validation, training_config=config, artifact_format='bundle')
        result['target_preparation'] = prepared
        expected = set(prepared['statuses'])
        observations = prepared['bridge_report_telemetry']
        if (prepared['sample_count'] != 5 or prepared['legal_ir_target_count'] != 5 or len(expected) != 5
                or set(observations) != expected or set(prepared['statuses'].values()) - {'ready', 'timeout'}):
            raise ValueError('all five target observations must be retained')
        ref = prepared['artifact']
        artifact = Path(ref['path'])
        if (artifact != directory / 'targets.bundle' or artifact.is_symlink()
                or artifact.stat().st_size != ref['bytes'] or not 0 < ref['bytes'] <= MAX_ARTIFACT_BYTES
                or digest(artifact) != ref['sha256']):
            raise ValueError('target artifact binding or 30 MB bound differs')
        with load_target_bundle(artifact, expected_sha256=ref['sha256'], max_bytes=MAX_ARTIFACT_BYTES) as loaded:
            if loaded.snapshot_id != prepared['target_snapshot_id'] or loaded.statuses != prepared['statuses']:
                raise ValueError('immutable target bundle readback differs')
        result['target_status_counts'] = dict(Counter(prepared['statuses'].values()))
        result['all_requested_bridge_reports_received'] = all(
            prepared['statuses'][key] == 'ready' and row['report_received'] is True
            and set(row['attempted_bridge_names'] or ()) == set(BRIDGES)
            and set(row['implemented_bridge_names'] or ()) == set(BRIDGES)
            and not row['failures'] and not row['failed_bridge_names'] and row['outer_timeout'] is None
            for key, row in observations.items())
        result['all_bridge_reports_accepted'] = all(
            row['report_accepted'] is True and set(row['accepted_bridge_names'] or ()) == set(BRIDGES)
            for row in observations.values())
        result['artifact_observed_and_verified'] = True
        exit_code = 0
    except Exception as exc:
        result['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        result['elapsed_seconds'] = time.perf_counter() - started
        result['wall_seconds_per_input_span'] = result['elapsed_seconds'] / 5
        result['source_unchanged'] = package_manifest() == before
        result['frozen_payload_unchanged'] = digest(args.payload) == args.payload_sha256
        result['parent_receipt_unchanged'] = digest(parent_path) == prior['sha256']
        if not all(result[key] for key in ('source_unchanged', 'frozen_payload_unchanged', 'parent_receipt_unchanged')):
            exit_code = 1
        result['exit_code'] = exit_code
        write(directory / 'target-preparation-observation.json', result)
    print(json.dumps({key: result[key] for key in ('exit_code', 'artifact_observed_and_verified',
        'all_requested_bridge_reports_received', 'all_bridge_reports_accepted', 'source_unchanged', 'admitted')}, sort_keys=True))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
