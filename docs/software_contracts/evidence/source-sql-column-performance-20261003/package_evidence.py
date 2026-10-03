"""Close the retained SQL/dependency diagnosis without shipping corpus/binaries."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

B = Path(__file__).parent
D = Path('/home/barberb/lift_coding/.worktrees/ir-release-datasets-20261002')
DEST = D / 'docs/software_contracts/evidence/source-sql-column-performance-20261003'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy(source, relative):
    if source.is_symlink() or not source.is_file():
        raise ValueError('only explicit regular evidence files are copied')
    target = DEST / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def main():
    if (DEST / 'manifest.json').exists():
        raise ValueError('closed evidence is immutable')
    baseline = json.loads((B / 'host-baseline-01/receipt.json').read_text())
    native = []
    for module, expected in baseline['producer_before'].items():
        relative = module.replace('.', '/') + '.py'
        source = D / relative
        if sha(source) != expected:
            raise ValueError('unmodified native producer differs from replay')
        copy(source, 'production-sources/' + relative)
        native.append(dict(path=relative, sha256=expected, unchanged_for_diagnostic=True))
    # Exclude downloaded upstream sources and private dependency symlink roots.
    diagnosis = B / 'runtime-diagnosis'
    freeze_path = diagnosis / 'dependency-timing-freeze.json'
    if sha(freeze_path) != 'b9f6ea3d25a2e824c1cc6a7dfcafb08ae951deec905aaa8641cb78432fa5e84a':
        raise ValueError('dependency experiment freeze differs')
    for row in json.loads(freeze_path.read_text())['files']:
        source = diagnosis / row['path']
        if source.suffix not in ('.py', '.json', '.stdout', '.stderr', '.log', '.md') or source.name.startswith('src__'):
            raise ValueError('unexpected dependency evidence type')
        if sha(source) != row['sha256'] or source.stat().st_size != row['bytes']:
            raise ValueError('frozen dependency evidence changed')
        copy(source, 'runtime-diagnosis/' + source.name)
    copy(freeze_path, 'runtime-diagnosis/' + freeze_path.name)
    copy(B / 'final-package-README.md', 'README.md')
    copy(Path(__file__), 'package_evidence.py')
    report = dict(
        schema='source-sql-column-performance-closeout@1',
        diagnostic_only=True, production_sql_patch_applied=False,
        full_source384_qualification_claimed=False, benchmark_result=False,
        model_loads=0, provider_calls=0, training_steps=0,
        native_producers=native,
        datasets_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=D, text=True).strip(),
        control_suites=dict(final_replay_controls=12, mocked_docker_wrapper_controls=8,
            external_candidate_controls=10, genuine_dependency_processes=4),
        exact_task_corpus_packaged=False, databases_packaged=False,
        model_weights_packaged=False, interpreter_binaries_packaged=False,
        dependency_symlink_roots_packaged=False, upstream_cpp_sources_packaged=False,
        corpus_reproduction='corpus-reproduction.json',
        host_pair='replay/host-pair-comparison.json',
        docker_pair='runtime-comparison/docker-pair-comparison.json',
        standalone_caveat='runtime-comparison/runtime-isolation-comparison.json',
        dependency_causality='runtime-diagnosis/dependency-timing-results.json',
        scope='Bounded native SQL replay and dependency diagnosis; corrected deployment qualification is separate.',
    )
    (DEST / 'closeout.json').write_text(json.dumps(report, indent=2) + '\n')
    members = []
    for path in sorted(DEST.rglob('*')):
        if path.is_symlink():
            raise ValueError('evidence cannot contain symlinks')
        if not path.is_file():
            continue
        if path.name in ('corpus.json', 'initial-corpus.json') or path.suffix in ('.duckdb', '.so', '.cpp', '.hpp'):
            raise ValueError('excluded payload entered evidence')
        members.append(dict(path=path.relative_to(DEST).as_posix(), bytes=path.stat().st_size, sha256=sha(path)))
    manifest = dict(schema='source-sql-column-performance-evidence@1', files=members,
        bytes=sum(row['bytes'] for row in members))
    (DEST / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(dict(directory=str(DEST), members=len(members), bytes=manifest['bytes'],
        manifest_sha256=sha(DEST / 'manifest.json')), indent=2))


if __name__ == '__main__':
    main()
