"""Run the existing bounded smoke end-to-end within one verified source capsule."""
from pathlib import Path
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import nullcontext

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[4]
sys.path.insert(0, str(ROOT))
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_source_snapshot import verify_frozen_runtime_from_environment


def write(name, value):
    with (BASE / name).open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())


def run(name, argv, timeout, *, sizing_reservation=False):
    started = time.monotonic()
    frozen = verify_frozen_runtime_from_environment()
    if frozen is None:
        raise RuntimeError('This successor requires a verified frozen source runtime')
    write(name + '-launch.json', {'argv': argv, 'timeout_seconds': timeout, 'frozen': frozen, 'admitted': False})
    owner = None
    if sizing_reservation:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import DaemonResourceReservation
        ledger = ROOT / 'workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json'
        roots = [Path(row['path']) for row in json.loads(ledger.read_text())['roots']]
        owner = DaemonResourceReservation(ledger, roots=roots, storage_bytes=32*1024*1024,
            memory_mb=8192, cpu_slots=1, child_process_slots=1, timeout_seconds=0, ledger_lock_timeout_seconds=60)
    with owner if owner is not None else nullcontext():
        evidence = BASE / (name + '-resources')
        if owner is not None:
            evidence.mkdir()
            owner.check_usage(evidence)
            owner.account_external_bytes('sizing-log-and-shape-receipts', 16*1024*1024)
        with (BASE / (name + '.log')).open('xb') as log:
            child = subprocess.Popen(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=owner is not None)
            try:
                if owner is not None:
                    owner.check_usage(evidence, child_pid=child.pid)
                deadline = time.monotonic() + timeout
                while child.poll() is None:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(name + ' deadline expired')
                    if owner is not None:
                        owner.check_usage(evidence, child_pid=child.pid)
                    time.sleep(1)
                result = child.returncode
            except BaseException:
                if owner is not None:
                    os.killpg(child.pid, signal.SIGTERM)
                else:
                    child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    if owner is not None:
                        os.killpg(child.pid, signal.SIGKILL)
                    else:
                        child.kill()
                    child.wait(timeout=5)
                raise
            finally:
                log.flush(); os.fsync(log.fileno())
        if owner is not None:
            outputs = [BASE / (name + '.log'), BASE / 'nonview-sparse-shape.json', BASE / 'structural-sparse-shape.json']
            references = []
            for path in outputs:
                with path.open('rb') as stream:
                    content = stream.read(); os.fsync(stream.fileno())
                references.append({'path': str(path), 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
            if sum(row['bytes'] for row in references) > 16*1024*1024:
                raise RuntimeError('Sizing output bound exceeded')
            write(name + '-resources/artifacts.json', references)
            for directory in (BASE, evidence):
                descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            receipt = owner.finalize(evidence, artifacts_durable=True)
            write(name + '-resources/resources.json', receipt)
    after = verify_frozen_runtime_from_environment()
    if frozen != after:
        raise RuntimeError('Frozen source identity changed')
    write(name + '-exit.json', {'returncode': result, 'elapsed_seconds': time.monotonic()-started,
                               'frozen': frozen, 'admitted': False})
    if result != 0:
        raise RuntimeError(f'{name} exited with {result}; retained evidence is not qualification')


def main():
    started = time.monotonic()
    invocation = json.loads((BASE / 'target-preparation-invocation.json').read_text())
    os.environ.update(invocation['environment_overrides'])
    run('target-preparation', invocation['argv'], 660)
    targets = json.loads((BASE / 'shared-targets/receipt.json').read_text())
    if targets['target_completeness']['complete'] is not True or targets['legal_ir_target_count'] != 8:
        raise RuntimeError('All eight complete five-bridge targets are required')
    os.environ.update(targets['runner_environment'])
    inputs = ROOT / 'workspace/test-logs/federal-corpus-audits/parallel-training-campaign-20260929T042818Z/verified-embeddings-r1'
    command = [sys.executable, '-B', str(ROOT / 'scripts/ops/legal_ir/run_incremental_autoencoders.py'),
        '--state-directory', str(BASE / 'feature-training'), '--training-purpose', 'feature_pretraining',
        '--feature-input-manifest', str(inputs / 'embedded-split.json'),
        '--checkpoint', str(BASE / 'fresh-gte-small-384.state.json'),
        '--input-jsonl', str(inputs / 'training.jsonl'), '--validation-jsonl', str(inputs / 'tuning.jsonl'),
        '--workers', '2', '--parallel-workers', '2', '--reuse-training-workers',
        '--max-batches', '6', '--epochs', '3', '--max-seconds', '180', '--line-search-attempts', '2',
        '--projection-optimizer-mode', 'productive_adaptive', '--projection-momentum', '0.25',
        '--projection-candidate-update-order', 'decoded_embedding_structural',
        '--shared-targets', targets['target_artifact']['path'], '--target-snapshot-id', targets['target_snapshot_id'],
        '--target-shard-max-bytes', '268435456', '--memory-mb', '24576', '--storage-bytes', '650000000',
        '--cycle-timeout', '360', '--polls', '1', '--model-variant', 'gte-small384-feature-smoke']
    run('feature-training', command, 440)
    first_cycles = list((BASE / 'feature-training/cycles').glob('*/cycle.json'))
    if len(first_cycles) != 1:
        raise RuntimeError('Expected exactly one completed initial cycle')
    first = json.loads(first_cycles[0].read_text())['training']
    if first['blocked'] or first['completed_batch_count'] != 6 or first['pending_batch_count'] != 0 or len(first['dispatched_run_ids']) != 6:
        raise RuntimeError('Feature training did not complete all six batches')
    if not first['completed'] or sum(row['optimizer_accepted_epochs'] for row in first['completed']) <= 2:
        raise RuntimeError('Feature smoke did not establish continued epoch learning')
    # An identical intake on resume must verify completed sparse lane heads and
    # skip already consumed rows, without touching independent canary data.
    run('feature-resume', command, 160)
    cycles = sorted((BASE / 'feature-training/cycles').glob('*/cycle.json'))
    resume_cycles = [p for p in cycles if p not in first_cycles]
    if len(resume_cycles) != 1:
        raise RuntimeError('Expected exactly one resume cycle')
    resumed = json.loads(resume_cycles[0].read_text())['training']
    if resumed['dispatched_run_ids'] or resumed['blocked'] or resumed['completed_batch_count'] != 6 or resumed['pending_batch_count'] != 0:
        raise RuntimeError('Resume duplicated work or lost completed batches')
    write('frozen-feature-smoke-result.json', {
        'schema': 'frozen-feature-pretraining-smoke/v1', 'elapsed_seconds': time.monotonic()-started,
        'frozen': verify_frozen_runtime_from_environment(), 'cycle_files': [str(p) for p in cycles],
        'scope': 'Private feature pretraining plus exact-resume smoke on six training/two repeated-tuning rows; not broad generalization or distillation evidence.',
        'admitted': False, 'formalized': False, 'qualified': False,
        'constitution_formalized': False, 'weights_downloaded': False, 'hub_published': False})


if __name__ == '__main__':
    main()
