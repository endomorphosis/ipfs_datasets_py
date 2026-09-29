#!/usr/bin/env python3
"""Curate bounded optimizer receipts/source proofs, never weights or DB/build bytes.

Default only plans. --apply copies explicitly selected evidence and appends only
those paths to the publication agent's publication-files.json. Failed guards and
attempts remain named as failures; no source provenance is relabeled.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import tempfile

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[3]
OUT = ROOT / 'docs/implementation/reports/evidence/autoencoder-convergence-20260929'
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_FILES = 3000
ROOT_NAMES = {
    'run_convergence_benchmark.py', 'audit_convergence.py', 'audit_semantic_gates.py',
    'curate_evidence.py', 'close_resources.py', 'prepared-plan.json', 'prepared-plan-v2.json',
    'harness-preflight.json', 'harness-ready.json', 'harness-ready-v2.json',
    'research-context.json', 'reproduce_nonfinite_guard.py', 'nonfinite-guard-comparison.json',
    'optimizer-before-manifest.json', 'optimizer-after-manifest.json', 'optimizer-readiness.json',
    'worker-cli-before.json', 'worker-cli-after.json', 'worker-cli.patch',
    'publication-owned-sources.json', 'source-scope.json', 'source-change-manifest.json',
    'resource-closeout.json', 'resource-audit.json', 'native-three-arm-audit.json',
    'convergence-summary.json', 'prepare_publication.py', 'test_prepared_main.py', 'push_publication.py',
    'package-before.json', 'package-after.json', 'native-command.json', 'native-audit.json',
    'optimizer-focused-tests.log', 'optimizer-change-manifest.json', 'optimizer-owned-delta.patch',
    'optimizer-rationale.json', 'plot_convergence.py', 'summarize_convergence.py',
    'publication-change-manifest.json', 'publication-helper-readiness.json',
}
ROOT_PREFIXES = ('semantic-gates', 'readiness', 'main-source-', 'isolated-prepared-', 'prepared-main-',
                 'optimizer-tests', 'worker-cli-', 'optimizer-readiness', 'optimizer-targeted-',
                 'nonfinite-', 'nan-', 'research-', 'harness-', 'native-', 'convergence-')
PROOFS = {'qualification.json', 'qualification-completion.json', 'Legal.lean', 'lakefile.lean',
          'lakefile.toml', 'lake-manifest.json', 'lake.log', 'lean-toolchain'}
RUN_NAMES = {'plan.json', 'capacity.json', 'effective-environment.json', 'command.json', 'comparison.json',
             'native-guard.json', 'selection-before-canary.json', 'selected-canary.json', 'native.log',
             'failure.json', 'retained-resources.json', 'resources.json', 'process-observations.json'}
SOURCE_SNAPSHOTS = [prefix + path for prefix in ('before/', 'after/') for path in (
    'ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py',
    'ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder_adaptive_optimizer.py',
    'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_worker.py',
    'scripts/ops/legal_ir/run_incremental_autoencoders.py')]
ARM_NAMES = {'arm-binding.json', 'job.json', 'dispatch.json', 'summary.json', 'package-begin.json', 'package-end.json'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def atomic(path, value):
    data = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.curation-', delete=False) as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
        temp = Path(stream.name)
    os.replace(temp, path)


def select():
    selected, runs = {}, {}
    def add(path):
        if not path.exists():
            return
        rel = path.relative_to(BASE).as_posix()
        if (path.is_symlink() or not path.is_file() or '.lake' in path.parts or 'artifacts' in path.parts or
                '.state.json' in path.name or path.suffix in {'.arrow', '.parquet', '.duckdb', '.olean', '.so', '.pstats'} or
                path.stat().st_size > MAX_FILE):
            raise ValueError('Disallowed or oversized evidence ' + rel)
        selected[rel] = path
    for path in BASE.iterdir():
        if path.name in ROOT_NAMES or (path.name.startswith(ROOT_PREFIXES) and path.suffix in {'.json', '.xml', '.log', '.svg', '.png', '.csv'}):
            add(path)
    for path in (BASE / 'scoped-deltas').glob('*.patch'):
        add(path)
    for name in SOURCE_SNAPSHOTS:
        add(BASE / name)
    # Native folders are included only once a durable terminal/retained receipt
    # exists. Do not snapshot mutable output from an in-progress run.
    for directory in BASE.iterdir():
        if not directory.is_dir() or not directory.name.startswith(('native-three-arm', 'integrated-')):
            continue
        completed, retained = (directory / 'command.json').exists(), (directory / 'retained-resources.json').exists()
        if not completed and not retained:
            runs[directory.name] = {'status': 'incomplete_excluded'}
            continue
        guard = read(directory / 'native-guard.json') if (directory / 'native-guard.json').exists() else None
        runs[directory.name] = {'status': 'completed' if completed else 'failed_retained',
            'source_guard': guard, 'matched_comparison_eligible': bool(completed and guard and all(guard.get(k) is True for k in
                ('source_unchanged', 'core_unchanged', 'orchestration_unchanged', 'protected_seed_unchanged')))}
        for path in directory.iterdir():
            if path.name in RUN_NAMES or (path.name.startswith('package-') and path.suffix == '.json'):
                add(path)
        for arm in ('fixed', 'adaptive_lr', 'adaptive_momentum', 'adaptive_momentum_refined'):
            root = directory / arm
            for name in ARM_NAMES:
                add(root / name)
            add(root / 'worker/receipt.json')
            for path in (root / 'qualification').rglob('*'):
                if path.is_file() and path.name in PROOFS and '.lake' not in path.parts:
                    add(path)
    selected = dict(sorted(selected.items()))
    total = sum(path.stat().st_size for path in selected.values())
    if len(selected) > MAX_FILES or total > MAX_TOTAL:
        raise ValueError(f'Evidence bounds exceeded: files={len(selected)}, bytes={total}')
    return selected, total, runs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    selected, total, runs = select()
    if not args.apply:
        print(json.dumps({'mode': 'read_only_plan', 'files': len(selected), 'bytes': total, 'runs': runs, 'destination': str(OUT)}))
        return
    if not any(row['status'] != 'incomplete_excluded' for row in runs.values()):
        raise ValueError('No terminal native receipts available')
    publication_path = BASE / 'publication-files.json'
    candidates_path = BASE / 'publication-file-candidates.json'
    publication_before = publication_path.read_bytes()
    candidates_before = candidates_path.read_bytes() if candidates_path.exists() else None
    publication = json.loads(publication_before)
    if not isinstance(publication, list) or not all(isinstance(item, str) for item in publication):
        raise ValueError('Publication file list must be a string array')
    existing = {p.relative_to(OUT).as_posix() for p in OUT.rglob('*') if p.is_file()} if OUT.exists() else set()
    unexpected = existing - set(selected) - {'artifact-manifest.json'}
    if unexpected:
        raise ValueError('Unindexed existing evidence: ' + repr(sorted(unexpected)))
    entries = {}
    for relative, source in selected.items():
        data = source.read_bytes()
        destination = OUT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists() or destination.read_bytes() != data:
            destination.write_bytes(data)
        if destination.read_bytes() != data:
            raise ValueError('Evidence copy differs')
        entries[relative] = {'sha256': sha(data), 'bytes': len(data), 'source_path': str(source)}
    manifest = {'schema': 'autoencoder-convergence-evidence/v1', 'files': entries,
        'file_count_excluding_manifest': len(entries), 'total_bytes_excluding_manifest': total,
        'native_runs': runs, 'weights_included': False, 'arrow_arrays_included': False,
        'databases_included': False, 'lake_build_binaries_included': False,
        'scope': 'Fixed-parent synthetic-duration optimizer ablation; eight training, one tuning, two experiment-held canaries. Source or timing failures are retained, not relabeled. Qualification outcomes do not establish full federal law or Constitution formalization.',
        'admitted': False, 'constitution_formalized': False, 'global_minimum_claim': False}
    atomic(OUT / 'artifact-manifest.json', manifest)
    if publication_path.read_bytes() != publication_before:
        raise ValueError('Publication list changed concurrently; refusing to overwrite')
    if candidates_before is not None and candidates_path.read_bytes() != candidates_before:
        raise ValueError('Source candidates changed during curation')
    additions = [str((OUT / name).relative_to(ROOT)) for name in entries]
    additions.append(str((OUT / 'artifact-manifest.json').relative_to(ROOT)))
    atomic(publication_path, list(dict.fromkeys([*publication, *additions])))
    print(json.dumps({'evidence_files': len(entries) + 1, 'evidence_bytes_excluding_manifest': total,
                      'publication_file_count': len(set([*publication, *additions])), 'output': str(OUT)}))


if __name__ == '__main__':
    main()
