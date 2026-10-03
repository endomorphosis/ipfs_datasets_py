"""Stage SQL diagnostic evidence; final closure requires later actual results."""
from pathlib import Path
import hashlib
import json
import shutil

B = Path(__file__).parent
C = B.parent / 'source384-sql-vector-candidate-20261003'
D = Path('/home/barberb/lift_coding/.worktrees/ir-release-datasets-20261002')
DEST = D / 'docs/software_contracts/evidence/source-sql-column-performance-20261003'


def copy(source, relative):
    target = DEST / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def main():
    if (DEST / 'manifest.json').exists():
        raise ValueError('closed evidence package must not be rewritten')
    DEST.mkdir(parents=True, exist_ok=True)
    replay_files = [
        'sql_replay.py', 'test_sql_replay.py', 'final-pins.json',
        'prepared-pins.json', 'host-pair-admission.json', 'host-pair-comparison.json',
        'independent-replay-review.json', 'control-generations.json', 'export-verified.json',
        'export-verified.stderr', 'initial-export.json', 'initial-export.stderr',
        'export.json', 'export.stderr', 'export-head-envelope-refused.stderr',
        'host-baseline-01.stdout', 'host-baseline-01.stderr',
        'host-candidate-01.stdout', 'host-candidate-01.stderr',
        'host-baseline-01/receipt.json', 'host-candidate-01/receipt.json',
    ]
    for number in range(1, 6):
        replay_files.extend(f'tiny-{number:02d}.{suffix}' for suffix in ('log', 'xml'))
    for folder in ('tiny-02-sources', 'tiny-03-sources', 'tiny-04-sources', 'final-sources'):
        replay_files.extend(f'{folder}/{name}' for name in ('sql_replay.py', 'test_sql_replay.py'))
    for name in replay_files:
        copy(B / name, 'replay/' + name)
    for name in ('run_docker_pair.py', 'check_docker_pair.py', 'docker-inputs.json',
                 'docker-wrapper-controls.log', 'docker-wrapper-controls-exit.json',
                 'independent-docker-launcher-review.json'):
        if (B / name).exists():
            copy(B / name, 'docker-launcher/' + name)
    for name in ('docker-pair-comparison.json', 'docker-cleanup-confirmation.json',
                 'docker-pair-result.json', 'docker-producer-verification.json', 'docker-go.json',
                 'docker-baseline-receipt.json', 'docker-candidate-receipt.json',
                 'docker-baseline.stdout', 'docker-baseline.stderr',
                 'docker-candidate.stdout', 'docker-candidate.stderr',
                 'docker-baseline-status.json', 'docker-candidate-status.json',
                 'docker-baseline-collection.json', 'docker-candidate-collection.json',
                 'docker-resources-before/resources.json', 'docker-01/resources.json',
                 'docker-01/deployment/python-install.log',
                 'docker-01/deployment/python-runtime-install.log',
                 'docker-01/deployment/native-imports.log',
                 'runtime-isolation-comparison.json'):
        if (B / name).exists():
            copy(B / name, 'runtime-comparison/' + name)
    for name in ('admission.json', 'import_probe.py', 'imports-complete.json',
                 'imports-complete.stderr', 'preflight-recovery.json',
                 'interrupted-install.stdout', 'interrupted-install.stderr',
                 'install-no-bin.stdout', 'install-no-bin.stderr',
                 'baseline.stdout', 'baseline.stderr', 'baseline/receipt.json',
                 'candidate.stdout', 'candidate.stderr', 'candidate/receipt.json'):
        copy(B / 'standalone-runtime-01' / name, 'runtime-comparison/standalone-runtime-01/' + name)
    candidate_files = [
        'vector_candidate.py', 'vector_candidate.py.frozen', 'check_and_measure.py',
        'check_and_measure.py.frozen', 'README.md', 'tiny-01-command.json',
        'tiny-01-process.log', 'tiny-01-exit.json', 'tiny-01/receipt.json',
        'tiny-01/check_and_measure.py.snapshot', 'tiny-01/controls.log',
        'tiny-02-command.json', 'tiny-02-process.log', 'tiny-02-exit.json',
        'tiny-02/receipt.json', 'tiny-02/controls.log',
        'production-column-unnest.patch', 'production-patch/receipt.json',
        'production-patch/apply-check.json',
    ]
    for name in candidate_files:
        copy(C / name, 'external-candidate/' + name)
    for generation in ('before', 'after'):
        for path in sorted((C / 'production-patch' / generation).rglob('*.py')):
            copy(path, 'external-candidate/' + str(path.relative_to(C)))
    export = json.loads((B / 'export-verified.json').read_text())
    recipe = dict(
        schema='retained-sql-corpus-reproduction@1', corpus_packaged=False,
        source_database_packaged=False, model_weights_packaged=False,
        corpus_sha256=export['corpus_sha256'], corpus_bytes=export['bytes'],
        source=export['source'], table_families=13, projections=31,
        tables=export['tables'],
        exporter='replay/sql_replay.py',
        required_inputs=dict(
            native_receipt='source-combined-observation-performance-20261003/full-context-04/state/receipt.json',
            source_database='source-combined-observation-performance-20261003/full-context-04/state/source.duckdb'),
        export_arguments=['export', '--source-database', '<retained source.duckdb>',
            '--source-receipt', '<retained receipt.json>', '--output', '<fresh corpus.json>'],
        replay_arguments=['replay', '--corpus', '<corpus.json>', '--expected-sha256',
            export['corpus_sha256'], '--output', '<fresh private output directory>'],
        candidate_arguments=['--candidate-path', '<vector_candidate.py>', '--candidate-sha256',
            'be404be397941857bc21f2b99af2240a29a4dc7944018bd6a1f72ce70736b72c'],
        limits=dict(read_only_export=True, maximum_corpus_bytes=33554432,
            maximum_rows_per_table=100000, selected_projection_count=31,
            permitted_source_count=220, duckdb_threads=1, duckdb_memory_limit='512MB',
            replay_deadline_seconds=90, batch_rows=128, parameter_byte_target=262144),
        caveat='Reproduction requires the retained source database and native receipt; hashes alone cannot reconstruct unavailable source artifacts.',
    )
    (DEST / 'corpus-reproduction.json').write_text(json.dumps(recipe, indent=2) + '\n')
    copy(B / 'README.md', 'host-scope.md')
    (DEST / 'README.md').write_text(
        '# SQL column-list performance evidence — staging\n\n'
        'This package is not closed. Genuine missing-dependency isolation results are pending. '
        'No production performance or benchmark claim is made. The production SQL patch remains unapplied.\n\n'
        'The Docker SQL pair preserved all 13 tables but did not reproduce the large host timing improvement: '
        'baseline/candidate execute times were 40.269/38.692 seconds (apply_batch 41.391/39.863). '
        'Both used the same DuckDB binary as the host, with no recorded cgroup throttling. '
        'Standalone Python 3.12.12 on the host with existing host dependencies remained fast, '
        'but its Feb12 build differs from the Docker Dec17 build; this is not a byte-identical interpreter control. '
        'See runtime-comparison/runtime-isolation-comparison.json for exact receipts and limits.\n\n'
        'The retained host SQL diagnostic is described in [host-scope.md](host-scope.md). '
        'The exact task AST corpus and databases remain outside this package; '
        '[corpus-reproduction.json](corpus-reproduction.json) binds their hashes and bounded reproduction inputs.\n\n'
        'All retained replay controls and source snapshots are included. The earliest tiny-01 run '
        'has no separately recovered exact source snapshot and is historical only. '
        'Later tiny-02, tiny-03, tiny-04 and final tiny-05 generations are explicitly snapshotted. '
        'The failed real head-envelope export remains a failure and was corrected before the paired host run. '
        'The external candidate and its off-tree production patch are proposals, not evidence of an installed runtime.\n')
    copy(Path(__file__), 'prepare_package.py')
    members = [dict(path=p.relative_to(DEST).as_posix(), bytes=p.stat().st_size,
        sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        for p in sorted(DEST.rglob('*')) if p.is_file()]
    (B / 'staged-package.json').write_text(json.dumps(dict(
        schema='sql-performance-evidence-staging@1', closed=False,
        directory=str(DEST), files=members, bytes=sum(row['bytes'] for row in members),
    ), indent=2) + '\n')
    print(json.dumps(dict(closed=False, members=len(members), bytes=sum(row['bytes'] for row in members))))


if __name__ == '__main__':
    main()
