"""Independently review a stopped, authenticated US Code archive continuation.

No source generation, resource reservation, network, model or writer is opened.
The previously reviewed parent prefix is reused; every newly committed source
occurrence is replayed with different paging and independent descriptor/digest
construction. Run only after the guardian has stopped/reaped its owned child.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time


BASE = Path('/home/barberb/lift_coding')
CAMPAIGN = BASE / 'artifacts/uscode-span-rollout-20261011'
PARENT = BASE / 'external/ipfs_datasets/workspace/test-logs/uscode-span-continuation-20261011/archived-reconciliation-01/results'
READINESS_SHA256 = 'e0a234ea886c7a1f389502b6ddfb0b3f9cd9d78ed2a1c581ed11e4bce4f32792'
PRIOR_REVIEW = BASE / 'artifacts/uscode-span-continuation-20261011/review/results-review.json'
PRIOR_REVIEW_SHA256 = 'a51dff39b62eeb9f7d71568ea07e8a9fa9903efee7b812841a43fb880015c660'
CODE_PATHS = {
    'intake': 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/legacy_span_intake.py',
    'census': 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_source_census.py',
    'constitution_inventory': 'ipfs_datasets_py/logic/autoformal/constitution_inventory.py',
    'uscode_ingest': 'ipfs_datasets_py/logic/autoformal/uscode_ingest.py',
    'uscode_dataset': 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_dataset.py',
    'span_pages': 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/legacy_span_pages.py',
    'archive_reconciliation': 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_archive_reconciliation.py',
}
EXTRA_OWNER_PATHS = {
    'resume_owner': 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/uscode_archive_resume.py',
    'resume_cli': 'scripts/ops/legal_ir/resume_uscode_archive.py',
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def signature(path):
    s = Path(path).stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def pin(path):
    before = signature(path)
    digest = sha(path)
    if before != signature(path):
        raise ValueError('Reviewed file changed while hashing: ' + str(path))
    return {'path': str(path), 'sha256': digest, 'bytes': before[2],
            'stat_signature': before}


@contextmanager
def stopped_database(directory, filename):
    import duckdb
    directory = Path(directory)
    if directory.resolve() != directory or directory.is_symlink():
        raise ValueError('Stopped evidence directory must be canonical')
    if (directory / (filename + '.wal')).exists():
        raise ValueError('Stopped evidence has a WAL')
    with (directory / 'writer.lock').open('r') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        db = duckdb.connect(str(directory / filename), read_only=True)
        try:
            yield db
        finally:
            db.close()
            fcntl.flock(lock, fcntl.LOCK_UN)


def target_rows(connection):
    columns = [c[0] for c in connection.execute('SELECT * FROM target_occurrences LIMIT 0').description]
    return {row[0]: dict(zip(columns, row)) for row in connection.execute(
        'SELECT * FROM target_occurrences').fetchall()}


def occurrence(candidate, source):
    """Independent reproduction; does not call controller/census row helpers."""
    binding = {
        'source_repository': 'justicedao/ipfs_uscode',
        'source_revision': source['revision'],
        'source_artifact_sha256': source['sha256'],
        'entry_cid': candidate['entry_cid'],
        'source_section_offset': candidate['source_section_offset'],
        'source_span_id': candidate['source_span_id'],
        'source_sha256': candidate['source_sha256'],
        'release_id': source['release_id'],
        'identity_reconstruction': 'historical-64-document-ordinal/v1',
        'historical_document_batch_index': candidate['historical_document_batch_index'],
        'historical_span_ordinal': candidate['historical_span_ordinal'],
    }
    count = len(candidate['text'].encode('utf-8'))
    cohort = next((f'le_{n}' for n in (512, 4096, 32768, 131072)
                   if count <= n), 'gt_131072')
    return {
        'occurrence_id': bytes.fromhex(hashlib.sha256(canonical(binding)).hexdigest()),
        **{k: candidate[k] for k in (
            'source_span_id', 'source_sha256', 'legal_id', 'entry_cid', 'title',
            'section', 'citation', 'source_section_offset',
            'historical_document_batch_index', 'historical_span_ordinal')},
        'utf8_bytes': count, 'unicode_characters': len(candidate['text']),
        'token_count': None, 'byte_cohort': cohort, 'token_cohort': None,
        'source_join_disposition': candidate['source_join_disposition'],
        **{k: candidate[k] for k in (
            'source_section_span_ordinal', 'source_text_origin', 'raw_source_text_present')},
    }


def account_row(account, row, target):
    descriptor = {k: (v.hex() if isinstance(v, bytes) else v) for k, v in row.items()}
    encoded = canonical(descriptor)
    def bump(mapping, key):
        mapping[key] = mapping.get(key, 0) + 1
    account['all_occurrence_digest'] = hashlib.sha256(
        bytes.fromhex(account['all_occurrence_digest']) + encoded).hexdigest()
    account['source_occurrence_count'] += 1
    for count, maximum, field in (
            ('source_utf8_bytes', 'max_source_utf8_bytes', 'utf8_bytes'),
            ('source_unicode_characters', 'max_source_unicode_characters', 'unicode_characters')):
        account[count] += row[field]
        account[maximum] = max(account[maximum], row[field])
    bump(account['source_byte_cohorts'], row['byte_cohort'])
    bump(account['source_text_origins'], row['source_text_origin'])
    if target:
        account['target_occurrence_count'] += 1
        bump(account['target_dispositions'], row['source_join_disposition'])
    else:
        account['outside_target_occurrence_count'] += 1
        bump(account['outside_target_byte_cohorts'], row['byte_cohort'])
        account['outside_target_digest'] = hashlib.sha256(
            bytes.fromhex(account['outside_target_digest']) + encoded).hexdigest()


def process_identity(pid):
    try:
        fields = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
    except (FileNotFoundError, ProcessLookupError):
        return None
    return {'pid': pid, 'birth': fields[19], 'state': fields[0], 'group': int(fields[2])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', type=Path, default=BASE / 'external/ipfs_datasets/workspace/test-logs/uscode-span-rollout-20261011/archived-reconciliation-02')
    parser.add_argument('--source-root', type=Path, default=BASE / '.worktrees/retained-wording-checkpoint-integration-datasets-20261007')
    parser.add_argument('--output', type=Path, default=CAMPAIGN / 'review/results-review.json')
    parser.add_argument('--replay-page-spans', type=int, default=37)
    args = parser.parse_args()
    if not 1 <= args.replay_page_spans <= 1024:
        raise ValueError('Bounded review page size required')
    # Refuse before opening any result DB unless durable guardian cleanup exists.
    exit_path = args.attempt / 'child-exit.json'
    resource_path = args.attempt / 'resources-final.json'
    if not exit_path.is_file() or not resource_path.is_file():
        raise ValueError('Guardian completion notification/receipts required before review')
    exit_receipt = json.loads(exit_path.read_text())
    resources = json.loads(resource_path.read_text())
    if exit_receipt['returncode'] or resources['record']['status'] != 'released':
        raise ValueError('Review requires a successful stopped and released attempt')
    if args.output.exists():
        raise ValueError('Completed independent review is immutable')
    started = time.monotonic()
    checks = []
    def check(name, passed, detail=None):
        item = {'id': name, 'passed': bool(passed)}
        if detail is not None:
            item['detail'] = detail
        checks.append(item)

    readiness_path = CAMPAIGN / 'review/readiness.json'
    check('frozen-readiness-and-prefix-review', sha(readiness_path) == READINESS_SHA256
          and sha(PRIOR_REVIEW) == PRIOR_REVIEW_SHA256)
    readiness = json.loads(readiness_path.read_text())
    original_review = json.loads(PRIOR_REVIEW.read_text())
    output = args.attempt / 'results'
    manifest = json.loads((output / 'manifest.json').read_text())
    report = json.loads((output / 'report.json').read_text())
    clone = json.loads((output / 'clone-custody.json').read_text())
    parent_manifest = json.loads((PARENT / 'manifest.json').read_text())
    parent_report = json.loads((PARENT / 'report.json').read_text())
    parent_pins = {n: pin(PARENT / n) for n in ('reconciliation.duckdb', 'manifest.json', 'report.json')}
    check('stopped-parent-three-file-custody', all(
        p['sha256'] == original_review['actual_receipt_pins']['results/' + n]['sha256']
        for n, p in parent_pins.items()))
    check('clone-three-file-custody', clone['schema'] == 'uscode-archive-generation-clone/v1'
          and clone['status'] == 'authenticated_clone_ready'
          and clone['parent_directory'] == str(PARENT)
          and clone['destination_directory'] == str(output)
          and all(clone['parent_files'][n] == {k: p[k] for k in ('path', 'sha256', 'bytes')}
                  for n, p in parent_pins.items()))
    check('inherited-generation-manifest', manifest == parent_manifest
          and sha(output / 'manifest.json') == parent_pins['manifest.json']['sha256']
          and hashlib.sha256(canonical(manifest)).hexdigest() == clone['generation_manifest_sha256']
          == report['manifest_sha256'])
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.source_root))
    import duckdb
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_intake as intake
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_pages import iter_joined_span_pages
    code_pins = {k: pin(args.source_root / path) for k, path in CODE_PATHS.items()}
    operator_pins = {k: pin(args.source_root / path) for k, path in EXTRA_OWNER_PATHS.items()}
    check('generation-and-clone-operator-source-pins', all(
        p['sha256'] == manifest['source_code_sha256'][k] for k, p in code_pins.items())
        and all(p['sha256'] == clone['clone_operator_sha256'][k] for k, p in operator_pins.items()))
    input_pins = {k: pin(manifest[k]['path']) for k in ('source', 'progress')}
    seed_pins = {k: pin(v['path']) for k, v in manifest['seed']['files'].items()}
    check('original-source-queue-and-seed-custody', all(
        p['sha256'] == manifest[k]['sha256'] for k, p in input_pins.items())
        and all(p['sha256'] == manifest['seed']['files'][k]['sha256'] for k, p in seed_pins.items()))

    with stopped_database(PARENT, 'reconciliation.duckdb') as parent_db, \
            stopped_database(output, 'reconciliation.duckdb') as current_db:
        parents = target_rows(parent_db)
        actual = target_rows(current_db)
        parent_state = dict(parent_db.execute('SELECT key,value FROM reconciliation_state').fetchall())
        state = dict(current_db.execute('SELECT key,value FROM reconciliation_state').fetchall())
        start_cursor = (int(parent_state['next_section']), int(parent_state['next_span']))
        end_cursor = (int(state['next_section']), int(state['next_span']))
        parent_account = json.loads(parent_state['accounting'])
        check('parent-targets-and-prefix-remain-intact', len(parents) == 2806
              and start_cursor == (199, 64) and parent_account == parent_report['accounting']
              and all(k in actual and actual[k] == row for k, row in parents.items()))
        summary = dict(next_section=start_cursor[0], next_span=start_cursor[1],
            done=parent_state['done'] == 'true', seed_applied=parent_state['seed_applied'] == 'true',
            source_occurrence_count=parent_account['source_occurrence_count'],
            target_occurrence_count=parent_account['target_occurrence_count'],
            outside_target_occurrence_count=parent_account['outside_target_occurrence_count'],
            all_occurrence_digest=parent_account['all_occurrence_digest'],
            outside_target_digest=parent_account['outside_target_digest'],
            accounting_sha256=hashlib.sha256(canonical(parent_account)).hexdigest())
        check('clone-prefix-state-and-digest-custody', summary == clone['parent_state'])
        check('durable-report-state-rows', json.loads(state['accounting']) == report['accounting']
              and end_cursor == (report['next_section'], report['next_span'])
              and (state['done'] == 'true') == report['complete_source_scan']
              and len(actual) == report['persisted_target_occurrences']
              == report['accounting']['target_occurrence_count'])
        check('actual-forward-progress', end_cursor > start_cursor)
        connection = duckdb.connect(':memory:')
        connection.execute('SET threads=1')
        connection.execute("SET memory_limit='768MB'")
        index = intake.prepare_progress_index(connection, manifest['progress']['path'],
            expected_sha256=manifest['progress']['sha256'], repository_revision=manifest['progress']['revision'],
            max_row_group_bytes=manifest['bounds']['max_row_group_bytes'])
        # In this pinned archive all identities are valid and unique. A conflict
        # or invalid future archive refuses this review instead of misclassifying.
        check('pinned-archive-valid-and-unique', index.stats['span_row_count'] == 443904
              and index.stats['unique_span_count'] == 443904 and index.stats['duplicate_span_count'] == 0,
              index.stats)
        account = copy.deepcopy(parent_account)
        new_targets = set()
        same_rows = True
        page_count = new_count = 0
        max_candidates = 0
        max_candidate_bytes = 0
        last_cursor = start_cursor
        for page in iter_joined_span_pages(index, manifest['source']['path'],
                expected_laws_sha256=manifest['source']['sha256'],
                source_revision=manifest['source']['revision'], release_id=manifest['source']['release_id'],
                start_section=start_cursor[0], start_span=start_cursor[1],
                max_page_spans=args.replay_page_spans,
                max_page_bytes=manifest['bounds']['max_page_bytes'],
                max_section_bytes=manifest['bounds']['max_section_bytes'],
                max_row_group_bytes=manifest['bounds']['max_row_group_bytes']):
            page_count += 1
            max_candidates = max(max_candidates, len(page['candidate_rows']))
            max_candidate_bytes = max(max_candidate_bytes, len(canonical(page['candidate_rows'])))
            if page['section_start'] >= end_cursor[0] and end_cursor[1] == 0:
                break
            account['empty_section_count'] += page['counts']['empty_section_count']
            for candidate in page['candidate_rows']:
                position = (candidate['source_section_offset'], candidate['source_section_span_ordinal'])
                if position >= end_cursor:
                    break
                row = occurrence(candidate, manifest['source'])
                target = candidate['source_join_disposition'] != 'unlisted_source'
                account_row(account, row, target)
                new_count += 1
                if target:
                    key = row['occurrence_id']
                    new_targets.add(key)
                    same_rows &= key in actual and actual[key] == row
            last_cursor = (page['next_section'], page['next_span'])
            if last_cursor >= end_cursor:
                break
        connection.close()
        check('all-new-target-descriptors-and-physical-rows', same_rows
              and new_targets == set(actual).difference(parents),
              {'compared_new_targets': len(new_targets), 'compared_parent_targets': len(parents)})
        check('all-new-occurrences-and-cumulative-digests', account == report['accounting'],
              {'replayed_new_occurrences': new_count, 'different_review_page_spans': args.replay_page_spans,
               'actual_page_spans': manifest['bounds']['max_page_spans'], 'review_pages_read': page_count,
               'maximum_candidate_page_rows': max_candidates,
               'maximum_serialized_candidate_page_bytes': max_candidate_bytes,
               'all_digest': account['all_occurrence_digest'],
               'outside_digest': account['outside_target_digest']})
        check('physical-source-accounting', len(actual) + account['outside_target_occurrence_count']
              == account['source_occurrence_count'] and new_count == account['source_occurrence_count']
              - parent_account['source_occurrence_count'])
        check('replay-reaches-durable-cursor', last_cursor >= end_cursor)
        check('parent-files-unchanged-after-review', all(
            signature(p['path']) == p['stat_signature'] for p in parent_pins.values()))

    identity = json.loads((args.attempt / 'child-identity.json').read_text())
    binding = json.loads((args.attempt / 'lease-binding.json').read_text())
    command = json.loads((args.attempt / 'command.json').read_text())
    leader = process_identity(identity['pid'])
    group = [p for e in Path('/proc').iterdir() if e.name.isdecimal()
             for p in [process_identity(int(e.name))]
             if p and p['group'] == identity['pid'] and p['state'] != 'Z']
    check('owned-pid-birth-group-stopped', identity == exit_receipt['cleanup']['identity']
          == resources['record']['child'] and exit_receipt['cleanup']['leader_reaped']
          and not group and (leader is None or leader['birth'] != identity['birth']),
          {'identity': identity, 'current_leader': leader, 'live_group': group})
    ledger = json.loads(Path(resources['ledger_path']).read_text())
    own_id = resources['reservation_id']
    own = ledger['reservations'][own_id]
    cutoff = readiness['created_at_unix']
    older = {k: v for k, v in ledger['reservations'].items() if v['created_at'] <= cutoff}
    preexisting = {**ledger, 'reservations': older}
    previous_sha = hashlib.sha256(canonical(preexisting) + b'\n').hexdigest()
    newer = {k: v for k, v in ledger['reservations'].items() if v['created_at'] > cutoff and k != own_id}
    scheduler = json.loads(Path(binding['state_path']).read_text())
    config_sha = hashlib.sha256(canonical(scheduler['config'])).hexdigest()
    check('own-resources-released-foreign-history-preserved', own['status'] == 'released'
          and resources['resource_lease']['released']
          and resources['resource_lease']['lease_id'] not in scheduler['leases']
          and previous_sha == readiness['disk']['ledger_sha256']
          and config_sha == binding['config_sha256'],
          {'own_reservation': own_id, 'own_lease': resources['resource_lease']['lease_id'],
           'preexisting_ledger_sha256': previous_sha,
           'newer_foreign_reservations_preserved': {k: {'status': v['status'],
               'storage_bytes': v['storage_bytes'], 'owner_pid': v['owner_pid']} for k, v in newer.items()},
           'current_foreign_lease_ids': list(scheduler['leases'])})
    events_bytes = (args.attempt / 'lease-observations.jsonl').read_bytes().splitlines(keepends=True)
    events = [json.loads(e) for e in events_bytes]
    observations = [e for e in events if e['schema'] == 'guardian-owned-lease-observation/v1']
    post_bytes = sum(len(b) for b, e in zip(events_bytes, events) if e.get('stage') == 'post_finalize')
    check('sampled-own-lease-custody', observations and all(e['healthy'] and e['configuration_matches']
          and e['read_only'] and e['continuous_coverage_claimed'] is False for e in observations)
          and observations[-1]['stage'] == 'post_finalize' and observations[-1]['lease_present'] is False,
          {'observation_count': len(observations), 'continuous_coverage_claimed': False})
    total_files = sum(p.stat().st_size for p in args.attempt.rglob('*')
                      if p.is_file() and not p.is_symlink())
    resource_receipt_bytes = resource_path.stat().st_size
    finalization_bytes = resources['record']['final_attempt_bytes']
    check('finalization-vs-later-receipt-bytes', total_files - finalization_bytes
          == resource_receipt_bytes + post_bytes,
          {'guardian_finalization_bytes': finalization_bytes, 'current_attempt_bytes': total_files,
           'later_resources_receipt_bytes': resource_receipt_bytes, 'later_post_finalize_bytes': post_bytes})
    check('cooperative-storage-and-rss-bounds', finalization_bytes <= resources['record']['storage_bytes']
          and resources['record']['final_accounting']['charged_bytes'] < resources['storage_limit_bytes']
          and report['kernel_maxrss']['raw_unit'] == 'KiB'
          and report['kernel_maxrss']['bytes'] == report['kernel_maxrss']['raw'] * 1024
          and report['kernel_maxrss']['bytes'] < command['memory_mb'] * 1024**2,
          {'rss': report['kernel_maxrss'], 'resource_enforcement': resources['enforcement']})
    check('no-inference-semantic-or-proof-authority', all(report[k] is False for k in (
        'inference_executed', 'training_executed', 'admitted', 'formalized', 'proof_authority',
        'semantic_reconstruction_measured', 'token_counts_measured', 'complete_all_source_occurrence_inventory')))
    receipt = {
        'schema': 'uscode-span-rollout-independent-results-review/v1', 'completed': True,
        'passed': all(c['passed'] for c in checks), 'checks': checks,
        'findings': [c for c in checks if not c['passed']], 'elapsed_seconds': time.monotonic() - started,
        'reviewer_source': pin(Path(__file__).resolve()), 'input_pins': input_pins,
        'seed_pins': seed_pins, 'code_pins': code_pins, 'clone_operator_pins': operator_pins,
        'parent_pins': parent_pins, 'start_cursor': list(start_cursor), 'final_cursor': list(end_cursor),
        'authenticated_parent_accounting': parent_account, 'independently_rebuilt_final_accounting': account,
        'actual_receipt_pins': {str(p.relative_to(args.attempt)): pin(p) for p in (
            exit_path, resource_path, output / 'clone-custody.json', output / 'manifest.json',
            output / 'report.json', output / 'reconciliation.duckdb',
            args.attempt / 'lease-observations.jsonl', args.attempt / 'child-identity.json')},
        'scope': 'Previously reviewed parent prefix reused; every new committed occurrence independently rebuilt under different paging. All databases opened read-only after stopped guardian notification.',
        'limits': [
            'Replay establishes custody only through the final durable cursor; full source exhaustion is a separate flag.',
            'Outside-target rows have aggregate counts/cohorts/digests and bounded examples, not a complete persisted outside inventory.',
            'RSS is process-lifetime self high-water, not an isolated phase or process-group peak.',
            'Resource enforcement and lease observations are cooperative and sampled, not kernel quotas or continuous coverage.',
            'Concurrent legitimate newer foreign claims/leases are reported and preserved; only this run must release its own resources.',
            'No numerical model, token geometry, semantic reconstruction or proof result was evaluated.',
        ],
        'mutations': {'models_loaded': 0, 'source_jobs_launched': 0, 'claims_acquired': 0,
                      'claims_released': 0, 'leases_acquired': 0, 'leases_released': 0},
    }
    with args.output.open('x') as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({'path': str(args.output), 'sha256': sha(args.output),
                      'passed': receipt['passed'], 'checks': len(checks), 'findings': len(receipt['findings'])}))
    raise SystemExit(0 if receipt['passed'] else 1)


if __name__ == '__main__':
    main()
