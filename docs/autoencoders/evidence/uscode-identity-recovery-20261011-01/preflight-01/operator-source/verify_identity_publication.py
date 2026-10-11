"""Verify immutable identity evidence bytes and preservation of all three mains."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from types import ModuleType

BASE = Path('/home/barberb/lift_coding')
SOURCE = BASE / 'artifacts/uscode-span-rollout-20261011/operator-source/verify_publication.py'
SOURCE_SHA256 = '8769ac3705b16d5ae4b4de361dccc0bdff3b3b262c7e868d40a4f94e476922ae'
def signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


source_signature = SOURCE.stat()
if (SOURCE.resolve(strict=True) != SOURCE or SOURCE.is_symlink()
        or not stat.S_ISREG(source_signature.st_mode) or not 0 < source_signature.st_size <= 2 * 1024 * 1024):
    raise ValueError('Bounded canonical verifier source required')
with SOURCE.open('rb') as stream:
    if signature(os.fstat(stream.fileno())) != signature(source_signature):
        raise ValueError('Verifier source changed before read')
    source_body = stream.read(2 * 1024 * 1024 + 1)
    if signature(os.fstat(stream.fileno())) != signature(source_signature):
        raise ValueError('Verifier source changed during read')
if (len(source_body) != source_signature.st_size or signature(SOURCE.stat()) != signature(source_signature)
        or SOURCE.resolve(strict=True) != SOURCE or hashlib.sha256(source_body).hexdigest() != SOURCE_SHA256):
    raise ValueError('Authenticated immutable publication verifier changed')
accepted = ModuleType('accepted_publication_verifier')
accepted.__file__ = str(SOURCE)
exec(compile(source_body, str(SOURCE), 'exec'), accepted.__dict__)
accepted.PREFIXES = {
    'endomorphosis/lift_coding': 'artifacts/uscode-identity-recovery-20261011-01/',
    'endomorphosis/ipfs_datasets_py': 'docs/autoencoders/evidence/uscode-identity-recovery-20261011-01/'}
accepted.DOCUMENTS = {
    'endomorphosis/lift_coding': 'implementation_plan/docs/73-uscode-identity-recovery-2026-10-11.md',
    'endomorphosis/ipfs_datasets_py': 'docs/autoencoders/uscode_identity_recovery_20261011.md'}
REQUIRED = {'STATUS.md', 'campaign.json', 'arguments.json', 'command.json',
            'review/implementation-review.json', 'review/pilot-readiness.json',
            'review/pilot-results-review.json', 'review/final-status-review.json',
            'measured-run/results/report.json', 'measured-run/results/candidates.parquet'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def all_checks(review):
    checks = review.get('checks')
    return (isinstance(checks, list) and bool(checks)
            and all(isinstance(c, dict) and c.get('passed') is True for c in checks)
            and type(review.get('check_count')) is int and review['check_count'] == len(checks)
            and review.get('findings') == [])


def closure(by_key, commits, bodies, extras):
    index_bodies = [bodies[(repo, commits[repo], prefix + 'index.json')]
                    for repo, prefix in accepted.PREFIXES.items()]
    require(index_bodies[0] == index_bodies[1], 'Both published evidence indexes must match')
    result = []
    for repository, commit in commits.items():
        prefix = accepted.PREFIXES[repository]
        index = json.loads(bodies[(repository, commit, prefix + 'index.json')])
        require(index.get('schema') == 'uscode-identity-recovery-evidence-index/v1'
                and isinstance(index.get('files'), dict) and REQUIRED.issubset(index['files']),
                'Complete identity evidence index required')
        require(index.get('aliases_promoted') == 0 and index.get('models_executed') is False
                and index.get('training_executed') is False and index.get('embedding_reuse_qualified') is False
                and index.get('proof_authority') is False, 'Published evidence must remain unpromoted')
        expected = {prefix + 'index.json', accepted.DOCUMENTS[repository]}
        expected |= {path for repo, path in extras if repo == repository}
        for relative, pin in index['files'].items():
            accepted.safe_path(relative)
            key = (repository, commit, prefix + relative)
            require(relative != 'index.json' and isinstance(pin, dict) and key in by_key,
                    'Every indexed body must have an immutable verified entry')
            entry = by_key[key]
            require(type(pin.get('bytes')) is int and pin['bytes'] == entry['bytes']
                    and pin.get('sha256') == entry['sha256'], 'Indexed byte/hash pin differs')
            expected.add(prefix + relative)
        require(expected == {path for repo, sha, path in by_key if repo == repository and sha == commit},
                'Unindexed or missing publication entry')
        status = bodies[(repository, commit, prefix + 'STATUS.md')]
        review = json.loads(bodies[(repository, commit, prefix + 'review/final-status-review.json')])
        require(review.get('status') == 'accepted' and all_checks(review)
                and review.get('document', {}).get('path') == str(BASE / 'artifacts/uscode-identity-recovery-20261011-01/STATUS.md')
                and review.get('document', {}).get('bytes') == len(status)
                and review.get('document', {}).get('sha256') == hashlib.sha256(status).hexdigest(),
                'Published STATUS must match its independent accepted document review')
        results = json.loads(bodies[(repository, commit, prefix + 'review/pilot-results-review.json')])
        require(results.get('passed') is True and results.get('completed') is True and all_checks(results),
                'Published stopped results need independent acceptance')
        report = json.loads(bodies[(repository, commit, prefix + 'measured-run/results/report.json')])
        require(report.get('schema') == 'uscode-retained-ordinal-diagnosis/v1'
                and report.get('hypothesis') == 'per-document-span-ordinal-hypothesis/v1'
                and report.get('status') == 'completed_unpromoted_diagnosis', 'Exact completed diagnosis profile required')
        for field in ('original_source_read', 'models_loaded', 'tokenizers_loaded', 'aliases_created',
                      'original_producer_recipe_authenticated', 'full_source_uniqueness_verified',
                      'embedding_reuse_qualified', 'teacher_qualified', 'training_admitted',
                      'semantic_gold', 'semantic_fidelity_qualified', 'proof_authority'):
            require(report.get(field) is False, 'Published diagnosis must retain false qualification flags')
        inputs = report.get('input_pins')
        require(isinstance(inputs, dict) and set(inputs) == {'database', 'manifest', 'report', 'progress', 'accepted_review'}
                and results.get('input_pins') == inputs, 'Independent complete input custody must agree')
        arguments = json.loads(bodies[(repository, commit, prefix + 'arguments.json')])
        input_names = {'database': ('database_path', 'expected_database_sha256'),
                       'manifest': ('manifest_path', 'expected_manifest_sha256'),
                       'report': ('report_path', 'expected_report_sha256'),
                       'progress': ('progress_parquet', 'expected_progress_sha256'),
                       'accepted_review': ('accepted_review_path', 'expected_accepted_review_sha256')}
        for name, (path_name, hash_name) in input_names.items():
            pin = inputs[name]
            require(isinstance(pin, dict) and type(pin.get('bytes')) is int and 0 < pin['bytes'] <= 128 * 1024 * 1024
                    and isinstance(pin.get('sha256'), str) and accepted.SHA256.fullmatch(pin['sha256'])
                    and pin['sha256'] == arguments.get(hash_name) and isinstance(pin.get('path'), str)
                    and pin['path'] == arguments.get(path_name) and Path(pin['path']).is_absolute()
                    and Path(pin['path']).as_posix() == pin['path']
                    and '..' not in Path(pin['path']).parts and not any(ord(c) < 32 for c in pin['path']),
                    'Published input custody differs from admitted arguments')
        output_pins = results.get('actual_output_pins')
        require(isinstance(output_pins, dict) and set(output_pins) == {'report.json', 'candidates.parquet'},
                'Exact reviewed output inventory required')
        for filename, pin in output_pins.items():
            body = bodies[(repository, commit, prefix + 'measured-run/results/' + filename)]
            require(isinstance(pin, dict) and pin.get('path') == str(BASE /
                'external/ipfs_datasets/workspace/test-logs/uscode-identity-recovery-20261011-01/ordinal-profile-01/results' / filename)
                and type(pin.get('bytes')) is int and pin['bytes'] == len(body)
                and pin.get('sha256') == hashlib.sha256(body).hexdigest(), 'Independent reviewed output differs')
        candidate = bodies[(repository, commit, prefix + 'measured-run/results/candidates.parquet')]
        candidate_pin = report.get('candidate_artifact', {})
        require(candidate_pin.get('path') == 'candidates.parquet' and candidate_pin.get('bytes') == len(candidate)
                and candidate_pin.get('sha256') == hashlib.sha256(candidate).hexdigest()
                and type(candidate_pin.get('rows')) is int
                and candidate_pin['rows'] == report.get('counts', {}).get('candidate_pairs'), 'Published candidate report binding differs')
        import pyarrow as pa
        import pyarrow.parquet as pq
        parquet = pq.ParquetFile(io.BytesIO(candidate))
        columns = ['occurrence_id', 'generated_span_id', 'hypothesis_span_id', 'source_sha256',
                   'legal_id', 'entry_cid', 'citation', 'title', 'section', 'source_section_offset',
                   'source_section_span_ordinal', 'historical_span_ordinal', 'source_text_origin',
                   'raw_source_text_present', 'retained_match_count']
        numeric = {'source_section_offset', 'source_section_span_ordinal', 'historical_span_ordinal', 'retained_match_count'}
        require(parquet.schema_arrow.names == columns and 0 <= parquet.metadata.num_rows <= 65536
                and parquet.metadata.num_rows == candidate_pin['rows'], 'Published candidate identity schema/row count differs')
        for field in parquet.schema_arrow:
            expected_type = (pa.int64() if field.name in numeric else
                             pa.bool_() if field.name == 'raw_source_text_present' else pa.string())
            require(field.type == expected_type, 'Published candidate identity type differs')
        require(index.get('diagnostic_summary') == {key: report[key] for key in
                ('retained_physical_occurrences', 'baseline_verified_occurrences', 'archived_distinct_ids',
                 'unresolved_archived_ids', 'counts', 'unresolved_ids_without_retained_candidate')},
                'Published diagnostic summary differs from its stopped report')
        link_prefix = ('../../artifacts/uscode-identity-recovery-20261011-01/'
                       if repository == 'endomorphosis/lift_coding'
                       else 'evidence/uscode-identity-recovery-20261011-01/')
        def rewrite(match):
            target = match.group(1)
            if target.startswith(('#', '/')) or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target):
                return match.group(0)
            return '](' + link_prefix + target + ')'
        document = re.sub(r'\]\(([^)]+)\)', rewrite, status.decode()).encode()
        require(document == bodies[(repository, commit, accepted.DOCUMENTS[repository])],
                'Standalone document differs from reviewed STATUS/link rewriting')
        result.append({'repository': repository, 'commit': commit,
                       'indexed_body_count': len(index['files']), 'complete_indexed_body_coverage': True,
                       'verified_extra_file_count': sum(repo == repository for repo, _ in extras)})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    path, raw, signature = accepted.read_manifest(args.manifest)
    manifest = json.loads(raw)
    extras = accepted.extra_entries(manifest)
    by_key, commits = accepted.file_entries(manifest, extras)
    with ThreadPoolExecutor(max_workers=6) as pool:
        fetched = list(pool.map(accepted.verify, by_key.values()))
    bodies = {(entry['repository'], entry['commit'], entry['path']): body for entry, body in fetched}
    packages = closure(by_key, commits, bodies, extras)
    gitlinks = []
    for entry in manifest['gitlinks']:
        accepted.require_commit(entry['root_commit'])
        accepted.require_commit(entry['target_commit'])
        require(accepted.repository_for_tree(entry['worktree']) == 'endomorphosis/lift_coding'
                and entry['root_commit'] == commits['endomorphosis/lift_coding']
                and entry['path'] in {'external/ipfs_datasets', 'external/ipfs_accelerate'}, 'Exact root gitlink binding required')
        if entry['path'] == 'external/ipfs_datasets':
            require(entry['target_commit'] == commits['endomorphosis/ipfs_datasets_py'], 'Datasets link must bind its verified package')
        line = subprocess.check_output(['git', '-C', entry['worktree'], 'ls-tree', entry['root_commit'], entry['path']], text=True)
        require(line.split()[:3] == ['160000', 'commit', entry['target_commit']], 'Root gitlink differs')
        gitlinks.append(dict(entry, verified=True))
    require(len(gitlinks) == 2 and {e['path'] for e in gitlinks} == {'external/ipfs_datasets', 'external/ipfs_accelerate'},
            'Both exact root gitlinks required')
    checks = []
    seen = set()
    for entry in manifest['main_checks']:
        repository = accepted.repository_for_tree(entry['worktree'])
        require(repository not in seen and entry.get('repository', repository) == repository, 'Unique correct main check required')
        seen.add(repository)
        for field in ('published_commit', 'preserved_main_commit'):
            accepted.require_commit(entry[field])
        if repository in commits:
            require(entry['published_commit'] == commits[repository], 'Main commit differs from verified file generation')
        else:
            require(entry['published_commit'] == next(e['target_commit'] for e in gitlinks if e['path'] == 'external/ipfs_accelerate'),
                    'Accelerate main check differs from root link')
        lines = subprocess.check_output(['git', '-C', entry['worktree'], 'ls-remote', 'origin', 'refs/heads/main'], text=True).splitlines()
        require(len(lines) == 1 and lines[0].split()[1] == 'refs/heads/main', 'One immutable observed main required')
        remote = lines[0].split()[0]
        methods = [accepted.ancestor(entry['worktree'], repository, entry['published_commit'], remote),
                   accepted.ancestor(entry['worktree'], repository, entry['preserved_main_commit'], entry['published_commit'])]
        checks.append(dict(entry, repository=repository, observed_main=remote, ancestry_methods=methods,
                           published_on_main=True, previous_main_preserved=True))
    require(seen == accepted.MAIN_REPOSITORIES and path.resolve(strict=True) == path
            and accepted.witness(path.stat()) == signature, 'Complete stable main/manifest custody required')
    receipt = {'schema': 'uscode-identity-recovery-publication-verification/v1', 'passed': True,
               'manifest_sha256': hashlib.sha256(raw).hexdigest(), 'authenticated_verifier_sha256': SOURCE_SHA256,
               'file_count': len(fetched), 'files': [entry for entry, _ in fetched],
               'package_closure': packages, 'gitlinks': gitlinks, 'main_checks': checks,
               'git_mutations': False, 'scope': 'Immutable identity diagnostic evidence and main preservation; no model publication'}
    with args.receipt.open('x') as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'passed': True, 'file_count': len(fetched), 'gitlink_count': len(gitlinks),
                      'main_check_count': len(checks), 'package_closure_count': len(packages)}))


if __name__ == '__main__':
    main()
