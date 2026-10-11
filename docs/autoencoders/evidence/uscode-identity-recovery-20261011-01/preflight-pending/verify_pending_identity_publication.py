"""Verify a published admission-pending milestone without inventing results."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from types import ModuleType

BASE = Path('/home/barberb/lift_coding')
CAMPAIGN = BASE / 'artifacts/uscode-identity-recovery-20261011-01'
SOURCE = CAMPAIGN / 'operator-source/verify_identity_publication.py'
SOURCE_SHA256 = 'aba749850fd8697e397674bcb6ef27e174cb16462950b84d5c8f150f5b4b6b49'
SCHEMA = 'uscode-identity-recovery-pending-evidence-index/v1'
REQUIRED = {'STATUS.md', 'campaign.json', 'arguments.json', 'command.json', 'run-plan.json',
            'review/implementation-review.json', 'review/implementation-memory-review.json',
            'review/pilot-readiness.json', 'review/pilot-readiness-02.json',
            'review/failed-attempt-resource-review.json', 'review/retry-admission-review.json',
            'review/memory-control-temporary-ownership-survey.json',
            'review/pending-publication-method-review.json', 'review/final-status-review.json'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def witness(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def captured_source():
    require(SOURCE.resolve(strict=True) == SOURCE and not SOURCE.is_symlink(), 'Canonical helper required')
    before = SOURCE.stat()
    require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= 2 * 1024 * 1024, 'Bounded helper required')
    with SOURCE.open('rb') as stream:
        require(witness(os.fstat(stream.fileno())) == witness(before), 'Helper changed before read')
        body = stream.read(2 * 1024 * 1024 + 1)
        require(witness(os.fstat(stream.fileno())) == witness(before), 'Helper changed during read')
    require(len(body) == before.st_size and witness(SOURCE.stat()) == witness(before)
            and SOURCE.resolve(strict=True) == SOURCE and hashlib.sha256(body).hexdigest() == SOURCE_SHA256,
            'Authenticated completed helper changed')
    module = ModuleType('frozen_identity_publication_helpers')
    module.__file__ = str(SOURCE)
    exec(compile(body, str(SOURCE), 'exec'), module.__dict__)
    return module


completed = captured_source()
accepted = completed.accepted


def all_checks(review):
    checks = review.get('checks')
    return (isinstance(checks, list) and bool(checks)
            and all(isinstance(c, dict) and c.get('passed') is True for c in checks)
            and type(review.get('check_count')) is int and review['check_count'] == len(checks))


def closure(by_key, commits, bodies, extras):
    indexes = [bodies[(repo, commits[repo], prefix + 'index.json')]
               for repo, prefix in accepted.PREFIXES.items()]
    require(indexes[0] == indexes[1], 'Both pending indexes must match')
    result = []
    for repository, commit in commits.items():
        prefix = accepted.PREFIXES[repository]
        index = json.loads(bodies[(repository, commit, prefix + 'index.json')])
        require(index.get('schema') == SCHEMA and index.get('stage') == 'awaiting_storage_admission'
                and isinstance(index.get('files'), dict) and REQUIRED.issubset(index['files']),
                'Complete explicitly pending evidence required')
        require(index.get('actual_result_review_completed') is False and index.get('aliases_promoted') == 0
                and index.get('models_executed') is False and index.get('training_executed') is False
                and index.get('embedding_reuse_qualified') is False and index.get('proof_authority') is False,
                'Pending milestone must not promote execution or authority')
        require('review/pilot-results-review.json' not in index['files']
                and not any(p.startswith('measured-run/') or p.endswith('.parquet') for p in index['files']),
                'Pending milestone cannot contain actual diagnosis outputs or result acceptance')
        expected = {prefix + 'index.json', accepted.DOCUMENTS[repository]}
        expected |= {path for repo, path in extras if repo == repository}
        for relative, pin in index['files'].items():
            accepted.safe_path(relative)
            key = (repository, commit, prefix + relative)
            require(relative != 'index.json' and isinstance(pin, dict) and key in by_key,
                    'Each indexed body requires an immutable entry')
            entry = by_key[key]
            require(type(pin.get('bytes')) is int and pin['bytes'] == entry['bytes']
                    and pin.get('sha256') == entry['sha256'], 'Indexed byte/hash differs')
            expected.add(prefix + relative)
        require(expected == {path for repo, sha, path in by_key if repo == repository and sha == commit},
                'Unindexed or missing publication entry')
        status = bodies[(repository, commit, prefix + 'STATUS.md')]
        review = json.loads(bodies[(repository, commit, prefix + 'review/final-status-review.json')])
        require(review.get('status') == 'accepted' and review.get('findings') == [] and all_checks(review)
                and review.get('document', {}).get('path') == str(CAMPAIGN / 'STATUS.md')
                and review['document'].get('bytes') == len(status)
                and review['document'].get('sha256') == hashlib.sha256(status).hexdigest(),
                'Pending STATUS must match its accepted document review')
        method = json.loads(bodies[(repository, commit, prefix + 'review/pending-publication-method-review.json')])
        require(method.get('status') == 'accepted' and method.get('findings') == [] and all_checks(method),
                'Separate pending publication method must be accepted')
        denial = json.loads(bodies[(repository, commit, prefix + 'review/retry-admission-review.json')])
        evidence = denial.get('no_attempt_evidence', {})
        require(denial.get('passed') is True and all_checks(denial)
                and denial.get('status') == 'admission_refused_before_reservation_and_child'
                and all(evidence.get(k) is False for k in ('attempt02_exists', 'child_created',
                        'new_disk_record_created', 'new_resource_lease_created')),
                'Independent actual denial and no-child evidence required')
        observation = denial.get('filesystem_free_observation', {})
        for name in ('minimum_free_bytes', 'required_free_bytes', 'observed_free_shortfall_bytes'):
            require(type(observation.get(name)) is int and observation[name] >= 0,
                    'Exact nonnegative free-space observations required')
        require(observation['required_free_bytes'] - observation['minimum_free_bytes']
                == observation['observed_free_shortfall_bytes'] > 0, 'Free-space shortfall differs')
        command = bodies[(repository, commit, prefix + 'command.json')]
        args = json.loads(bodies[(repository, commit, prefix + 'arguments.json')])
        pin = denial.get('input_pins', {}).get('exact_command', {})
        require(pin.get('path') == str(CAMPAIGN / 'command.json') and pin.get('bytes') == len(command)
                and pin.get('sha256') == hashlib.sha256(command).hexdigest(), 'Rejected command custody differs')
        require(args.get('output_directory') == str(BASE / 'external/ipfs_datasets/workspace/test-logs/uscode-identity-recovery-20261011-01/ordinal-profile-02/results'),
                'Exact refused attempt output binding required')
        plan = json.loads(bodies[(repository, commit, prefix + 'run-plan.json')])
        require(plan.get('retained_occurrences') == 64969 and plan.get('unresolved_archive_ids') == 378935,
                'Accepted parent counts differ')
        parent = index.get('parent_coverage', {})
        require(parent.get('scope') == 'accepted_parent_scan_not_new_diagnosis'
                and parent.get('retained_occurrences') == 64969 and parent.get('archived_distinct_ids') == 443904
                and parent.get('unresolved_archive_ids') == 378935 and parent.get('source_occurrences') == 3840988,
                'Pending index must identify original parent measurement scope')
        link_prefix = ('../../artifacts/uscode-identity-recovery-20261011-01/'
                       if repository == 'endomorphosis/lift_coding' else 'evidence/uscode-identity-recovery-20261011-01/')
        def rewrite(match):
            target = match.group(1)
            if target.startswith(('#', '/')) or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target):
                return match.group(0)
            return '](' + link_prefix + target + ')'
        document = re.sub(r'\]\(([^)]+)\)', rewrite, status.decode()).encode()
        require(document == bodies[(repository, commit, accepted.DOCUMENTS[repository])],
                'Standalone pending document differs from reviewed STATUS')
        result.append({'repository': repository, 'commit': commit, 'indexed_body_count': len(index['files']),
                       'complete_indexed_body_coverage': True, 'actual_result_review_completed': False,
                       'verified_extra_file_count': sum(repo == repository for repo, _ in extras)})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    path, raw, signature = accepted.read_manifest(args.manifest)
    manifest = json.loads(raw)
    require(manifest.get('schema') == 'uscode-identity-recovery-pending-publication-manifest/v1',
            'Separate pending publication manifest required')
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
                and entry['path'] in {'external/ipfs_datasets', 'external/ipfs_accelerate'}, 'Exact root gitlink required')
        if entry['path'] == 'external/ipfs_datasets':
            require(entry['target_commit'] == commits['endomorphosis/ipfs_datasets_py'], 'Datasets link differs')
        line = subprocess.check_output(['git', '-C', entry['worktree'], 'ls-tree', entry['root_commit'], entry['path']], text=True)
        require(line.split()[:3] == ['160000', 'commit', entry['target_commit']], 'Root gitlink differs')
        gitlinks.append(dict(entry, verified=True))
    require(len(gitlinks) == 2 and {e['path'] for e in gitlinks} == {'external/ipfs_datasets', 'external/ipfs_accelerate'},
            'Both root gitlinks required')
    checks, seen = [], set()
    for entry in manifest['main_checks']:
        repository = accepted.repository_for_tree(entry['worktree'])
        require(repository not in seen and entry.get('repository', repository) == repository, 'Unique main check required')
        seen.add(repository)
        for field in ('published_commit', 'preserved_main_commit'):
            accepted.require_commit(entry[field])
        expected = commits.get(repository, next(e['target_commit'] for e in gitlinks if e['path'] == 'external/ipfs_accelerate'))
        require(entry['published_commit'] == expected, 'Main commit differs from verified generation')
        lines = subprocess.check_output(['git', '-C', entry['worktree'], 'ls-remote', 'origin', 'refs/heads/main'], text=True).splitlines()
        require(len(lines) == 1 and lines[0].split()[1] == 'refs/heads/main', 'One observed main required')
        remote = lines[0].split()[0]
        methods = [accepted.ancestor(entry['worktree'], repository, entry['published_commit'], remote),
                   accepted.ancestor(entry['worktree'], repository, entry['preserved_main_commit'], entry['published_commit'])]
        checks.append(dict(entry, repository=repository, observed_main=remote, ancestry_methods=methods,
                           published_on_main=True, previous_main_preserved=True))
    require(seen == accepted.MAIN_REPOSITORIES and path.resolve(strict=True) == path
            and accepted.witness(path.stat()) == signature, 'Stable complete main/manifest custody required')
    receipt = {'schema': 'uscode-identity-recovery-pending-publication-verification/v1', 'passed': True,
               'manifest_sha256': hashlib.sha256(raw).hexdigest(), 'authenticated_completed_helper_sha256': SOURCE_SHA256,
               'authenticated_ancestor_helper_sha256': completed.SOURCE_SHA256,
               'actual_result_review_completed': False, 'file_count': len(fetched),
               'files': [entry for entry, _ in fetched], 'package_closure': packages, 'gitlinks': gitlinks,
               'main_checks': checks, 'git_mutations': False,
               'scope': 'Reviewed implementation, failed/admission-denied attempts and remaining plan; no successful diagnosis or model publication'}
    with args.receipt.open('x') as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'passed': True, 'file_count': len(fetched), 'gitlink_count': len(gitlinks),
                      'main_check_count': len(checks), 'package_closure_count': len(packages),
                      'actual_result_review_completed': False}))


if __name__ == '__main__':
    main()
