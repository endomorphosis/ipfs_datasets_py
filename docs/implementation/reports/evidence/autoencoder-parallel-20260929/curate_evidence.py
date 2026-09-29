"""Curate this campaign's receipts and Lean inputs, never checkpoint/build bytes.

Default is a read-only plan. --apply curates completed native runs and records
missing runs. Failed source audits remain visible and are never relabeled.
Publication source candidates are read only; only explicit evidence paths are
appended to publication-files.json. Run again after additional test receipts.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[3]
OUT = ROOT / 'docs/implementation/reports/evidence/autoencoder-parallel-20260929'
LABELS = ['baseline', 'optimized', 'rechecked', 'automatic-retry']
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_FILES = 3000
ROOT_NAMES = {
    'input.jsonl', 'validation.jsonl', 'test-paths.json', 'sources-before.json',
    'source-scope.json', 'preexisting-ui-registry-scope.json',
    'automatic-command.json', 'automatic-binding.json', 'automatic.log',
    'owner-bottleneck-audit.json', 'owner-cpu-readiness.json', 'owner-cpu.patch',
    'owner-cpu-audit-harness-checks.json', 'inventory-abba.json',
    'resource-lexical-microbenchmark.json', 'resource-audit.json', 'resource-closeout.json',
    'tracking-replay-aborted-1.json', 'tracking-replay-comparison.json',
    'modal-lazy-semantic-gates.json', 'readiness-provenance-audit.json', 'post-optimized-producer-drift.json',
    'package-current.json', 'package-readiness-before-reconstructed.json',
    'package-controlled-before.json', 'resource-closeout.json',
    'native-performance-summary.json', 'automatic-hardware-plan.json',
    'audit_native_runs.py', 'audit_readiness_provenance.py', 'audit_modal_lazy_semantic_gates.py',
    'benchmark_inventory.py', 'benchmark_tracking.py', 'native_compare.py',
    'summarize_native_performance.py', 'curate_evidence.py', 'test_prepared_main.py', 'prepare_publication.py',
}
PROOF_NAMES = {'qualification.json', 'Legal.lean', 'lake-manifest.json', 'lakefile.lean',
               'lakefile.toml', 'lake.log', 'lean-toolchain'}
COMPONENT_FILES = {
    'modal-lazy-evidence': {'change-manifest.json', 'validation-results.json', 'historical_exports.json',
        'cold-import-measurement.json', 'measure_cold_structural.py', 'test_family_qualification.before.py',
        'family_qualification.before.py', 'family_qualification.after.py', 'modal_init.before.py', 'modal_init.after.py',
        'prechange-ui-registry-failure.log'},
    'tracking-fastpath-scratch': {'before-sha256.json', 'modal_autoencoder_state_version.before.py',
        'modal_autoencoder_state_version.py', 'test_modal_autoencoder_tracking_fastpath.py'},
}


def read(path):
    return json.loads(path.read_bytes())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.curation-', delete=False) as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def selection():
    selected = {}
    def add(path):
        if path.exists():
            if path.is_symlink() or not path.is_file() or '.lake' in path.parts:
                raise ValueError('Evidence is not an allowed regular file: ' + str(path))
            if path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError('Evidence file exceeds 8 MiB: ' + str(path))
            selected[path.relative_to(BASE).as_posix()] = path
    for name in ROOT_NAMES:
        add(BASE / name)
    # These controlled test/audit prefixes preserve failed attempts as well as
    # final receipts, without sweeping unrelated workspace state or binaries.
    for path in BASE.iterdir():
        test_receipt = (path.name.startswith(('readiness', 'main-source-', 'isolated-prepared-', 'prepared-main-', 'tracking-tests', 'resource-tests'))
                        and path.suffix in {'.json', '.xml', '.log'})
        parity_receipt = path.name.endswith('-parity-audit.json')
        capacity_failure_receipt = path.name.startswith('automatic-capacity-blocked-') and path.suffix in {'.json', '.log', '.txt'}
        if test_receipt or parity_receipt or capacity_failure_receipt:
            add(path)
    for folder, names in COMPONENT_FILES.items():
        for name in names:
            add(BASE / folder / name)
    for label in LABELS:
        for suffix in ['-audit.json', '-binding.json', '-command.json', '.log']:
            add(BASE / (label + suffix))
        if not all((BASE / (label + suffix)).exists() for suffix in ['-audit.json', '-command.json', '-binding.json']):
            continue  # Do not snapshot mutable worker output from an incomplete run.
        root = BASE / label
        for path in (root / 'cycles').glob('*/*'):
            if path.name in {'cycle.json', 'resources.json', 'process-observations.json'}:
                add(path)
        for path in (root / 'progress').glob('qualified-*.json'):
            if not path.name.endswith('.qualification-payload.json'):
                add(path)
        for path in (root / 'progress/outputs').glob('*/receipt.json'):
            add(path)
        for path in (root / 'progress/repair-outbox').glob('*.json'):
            add(path)
        for directory in (root / 'progress/qualifications').glob('*'):
            for path in directory.rglob('*'):
                if path.name in PROOF_NAMES and path.is_file() and '.lake' not in path.parts:
                    add(path)
    assert not any('.state.json' in key or key.endswith(('.arrow', '.parquet', '.duckdb', '.olean', '.so', '.pstats'))
                   or '/.lake/' in key or '/artifacts/' in key for key in selected)
    total = sum(path.stat().st_size for path in selected.values())
    if len(selected) > MAX_FILES or total > MAX_TOTAL_BYTES:
        raise ValueError('Evidence selection exceeds explicit count or byte bound')
    return dict(sorted(selected.items())), total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    selected, total = selection()
    missing = [name for label in LABELS for name in [label + '-audit.json', label + '-command.json', label + '-binding.json']
               if name not in selected]
    if not args.apply:
        print(json.dumps({'mode': 'read_only_plan', 'evidence_files': len(selected), 'total_bytes': total,
                          'missing_native_completion_evidence': missing, 'destination': str(OUT)}, sort_keys=True))
        return
    completed = [label for label in LABELS if all(label + suffix in selected for suffix in ['-audit.json', '-command.json', '-binding.json'])]
    if not completed:
        raise ValueError('No completed native run receipts available')
    native_audits = {}
    failed_commands = {}
    automatic_command = BASE / 'automatic-command.json'
    if automatic_command.exists() and read(automatic_command)['returncode'] != 0:
        failed_commands['automatic'] = {'returncode': read(automatic_command)['returncode'],
            'elapsed_seconds': read(automatic_command)['wall_seconds'],
            'excluded_from_completed_training_timings': True, 'evidence': 'automatic-command.json'}
    for label in completed:
        audit, command = read(BASE / (label + '-audit.json')), read(BASE / (label + '-command.json'))
        if command['returncode'] != 0:
            failed_commands[label] = {'returncode': command['returncode'], 'elapsed_seconds': command['wall_seconds'],
                                     'excluded_from_completed_training_timings': True, 'evidence': label + '-command.json'}
            continue
        native_audits[label] = {'passed': audit['passed'], 'check_count': audit['check_count'],
                              'failures': audit['failures'], 'observations_only': not audit['passed']}
        assert command['source_unchanged'] and command['checkpoint_unchanged']
        for name in ['command', 'binding']:
            path = BASE / (label + '-' + name + '.json')
            raw = path.read_bytes()
            assert audit[name]['sha256'] == sha(raw) and audit[name]['bytes'] == len(raw)
    provenance = read(BASE / 'readiness-provenance-audit.json')
    assert provenance['source_unchanged'] is False
    assert set(provenance['external_change_before_readiness']) == {'logic/autoformal/lean_units.py'}
    assert set(provenance['concurrent_external_producer_changes_during_readiness']) == {
        'huggingface/autoformal_span_cache.py', 'logic/autoformal/entity_cache.py', 'logic/autoformal/span_cache.py'}
    candidates_path = BASE / 'publication-file-candidates.json'
    candidates_before = candidates_path.read_bytes()
    publication_path = BASE / 'publication-files.json'
    publication_before = publication_path.read_bytes()
    publication = json.loads(publication_before)
    assert isinstance(publication, list) and all(isinstance(name, str) for name in publication)
    existing_evidence = {p.relative_to(OUT).as_posix() for p in OUT.rglob('*') if p.is_file()} if OUT.exists() else set()
    unexpected = existing_evidence - set(selected) - {'artifact-manifest.json'}
    if unexpected:
        raise ValueError('Unindexed preexisting evidence; refusing to publish implicitly: ' + repr(sorted(unexpected)))
    entries = {}
    for relative, source in selected.items():
        raw = source.read_bytes()
        destination = OUT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Only this exact explicit file may be refreshed on a later curation.
        if not destination.exists() or destination.read_bytes() != raw:
            destination.write_bytes(raw)
        assert destination.read_bytes() == raw
        entries[relative] = {'sha256': sha(raw), 'bytes': len(raw), 'source_path': str(source)}
    manifest = {'schema': 'autoencoder-parallel-evidence/v1', 'files': entries,
        'file_count_excluding_manifest': len(entries), 'total_bytes_excluding_manifest': sum(row['bytes'] for row in entries.values()),
        'weights_included': False, 'lake_build_binaries_included': False,
        'native_run_audits': native_audits, 'failed_commands': failed_commands,
        'missing_native_completion_evidence': missing,
        'sample_scope': 'Eight synthetic duration fixtures with mock stable-hash embeddings; repeated30-day tuning validation, not federal-law coverage or independent held-out validation.',
        'readiness_provenance': {'source_unchanged': False, 'test_exit_code': provenance['test_exit_code'],
            'external_change_before_readiness': list(provenance['external_change_before_readiness']),
            'concurrent_external_producer_changes_during_readiness': list(provenance['concurrent_external_producer_changes_during_readiness']),
            'qualification': provenance['qualification'], 'native_comparison_limitation': provenance['native_comparison_limitation']},
        'admitted': False, 'formalized': False, 'constitution_formalized': False}
    atomic_json(OUT / 'artifact-manifest.json', manifest)
    additions = [str((OUT / relative).relative_to(ROOT)) for relative in entries]
    additions.append(str((OUT / 'artifact-manifest.json').relative_to(ROOT)))
    assert candidates_path.read_bytes() == candidates_before, 'Source publication candidates changed during curation'
    assert publication_path.read_bytes() == publication_before, 'Publication list changed during curation; retry without overwriting concurrent work'
    atomic_json(publication_path, list(dict.fromkeys([*publication, *additions])))
    print(json.dumps({'evidence_files': len(entries) + 1, 'bytes_excluding_manifest': manifest['total_bytes_excluding_manifest'],
                      'publication_file_count': len(set([*publication, *additions])), 'source_candidates_unchanged': True,
                      'readiness_guard_failure_preserved': True, 'output': str(OUT)}, sort_keys=True))

if __name__ == '__main__':
    main()
