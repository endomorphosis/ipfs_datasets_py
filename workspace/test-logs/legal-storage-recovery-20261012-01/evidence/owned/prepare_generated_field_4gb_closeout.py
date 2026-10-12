"""Prepare one retained claim for review; never invoke recovery or alter outputs."""
from __future__ import annotations

import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import stat
import sys
import time

F = Path(__file__).resolve().parent
PACKAGE = Path('/home/barberb/lift_coding/external/ipfs_datasets')
CAMPAIGN = PACKAGE / 'workspace/test-logs/decoder-generated-field-training-20261003'
ATTEMPT = CAMPAIGN / 'training-r1'
LEDGER = PACKAGE / 'workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json'
OWN = '474ee6b5ae784516ae1dab7ca38c8cc6'
OUTPUT = F / 'generated-field-4gb-closeout-preparation-v01.json'
EXPECTED_LEDGER_SHA256 = '1f93e0ca70ea6199f16d58834e30d60d127f9891e380454e470df352720bb824'
EXPECTED_RECORD_SHA256 = '4ca144ebfb780e5aa9e502fd7459f620052b00b20d00f8351aedaaa3829ef687'
sys.dont_write_bytecode = True


def require(value, message):
    if not value:
        raise ValueError(message)


class DenyModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'numpy', 'transformers', 'sentence_transformers'}:
            raise AssertionError('Numerical/model import forbidden: ' + fullname)
        return None


def audit(event, args):
    if event.startswith(('socket.', 'subprocess.', 'os.exec', 'os.spawn')) or event in {
            'os.system', 'os.fork', 'os.posix_spawn', 'os.kill', 'os.killpg'}:
        raise AssertionError('No network, process or signals in closeout preparation')
    if event != 'open':
        return
    path, mode, flags = args
    write = isinstance(mode, str) and any(letter in mode for letter in 'wax+')
    write |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
    if not write:
        return
    require(not isinstance(path, int) and Path(os.fsdecode(path)).absolute() == OUTPUT,
            'Only the owned preparation metadata report may be created')
    require(mode is None and flags == os.O_CLOEXEC | os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            'Metadata report requires exclusive nofollow create')


sys.meta_path.insert(0, DenyModels())
sys.addaudithook(audit)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def ordinary(path, *, directory=False):
    path = Path(os.path.abspath(os.fspath(path)))
    for component in (*reversed(path.parents), path):
        info = component.lstat()
        require(not stat.S_ISLNK(info.st_mode), 'Symlink path refused')
        require(stat.S_ISDIR(info.st_mode) if component != path or directory else stat.S_ISREG(info.st_mode),
                'Ordinary path required')
    return path


def identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def pin(path, *, sync=False):
    path = ordinary(path)
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        if sync or path.is_relative_to(ATTEMPT):
            require(before.st_nlink == 1, 'Aliased retained artifact refused')
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        if sync:
            os.fsync(stream.fileno())
        after = os.fstat(stream.fileno())
    require(identity(before) == identity(after) == identity(path.stat()), 'Artifact changed during read')
    return {'path': str(path), 'bytes': before.st_size, 'sha256': sha}


def read_metadata(path):
    info = pin(path)
    require(info['bytes'] <= 16 * 1024 * 1024, 'Bounded metadata JSON required')
    return json.loads(Path(path).read_bytes())


def roots_identity(roots):
    return [{'path': row['path'], 'device': ordinary(row['path'], directory=True).stat().st_dev,
             'inode': ordinary(row['path'], directory=True).stat().st_ino} for row in roots]


def inventory(sync):
    ordinary(ATTEMPT, directory=True)
    before = ATTEMPT.stat()
    paths = sorted(ATTEMPT.rglob('*'))
    require(len(paths) <= 200_000, 'Bounded attempt inventory required')
    files, directories = [], [ATTEMPT]
    for path in paths:
        if stat.S_ISDIR(path.lstat().st_mode):
            ordinary(path, directory=True)
            directories.append(path)
        else:
            item = pin(path, sync=sync)
            files.append({'path': str(path.relative_to(ATTEMPT)), 'bytes': item['bytes'], 'sha256': item['sha256']})
    if sync:
        for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    require(identity(before) == identity(ATTEMPT.stat()), 'Attempt metadata changed during inventory')
    return files, [{'path': str(path.relative_to(ATTEMPT)), 'device': path.stat().st_dev,
                    'inode': path.stat().st_ino} for path in directories]


def processes():
    observations = {}
    entries = list(Path('/proc').iterdir())
    require(len(entries) <= 100_000, 'Bounded process observation required')
    for path in entries:
        if not path.name.isdecimal():
            continue
        try:
            raw = (path / 'stat').read_text()
        except (FileNotFoundError, ProcessLookupError):
            continue
        fields = raw[raw.rfind(')') + 2:].split()
        require(len(fields) >= 22, 'Ordinary /proc identity required')
        observations[int(path.name)] = {'state': fields[0], 'group_pid': int(fields[2]), 'birth': fields[19]}
    return observations


def main():
    require(not OUTPUT.exists(), 'Preparation report is immutable; use a distinct reviewed version')
    ledger_pin = pin(LEDGER)
    require(ledger_pin['sha256'] == EXPECTED_LEDGER_SHA256, 'Fresh ledger endpoint required')
    ledger = read_metadata(LEDGER)
    record = ledger['reservations'][OWN]
    require(digest(record) == EXPECTED_RECORD_SHA256 and record['status'] == 'retained'
            and record['storage_bytes'] == 4_000_000_000 and record['external_charges'] == {}, 'Exact retained claim required')
    require(ledger['limit_bytes'] == 145_000_000_000 and len(ledger['reservations']) == 513, 'Current policy and record set required')
    require(roots_identity(ledger['roots']) == ledger['roots'], 'Named roots changed')
    root_info = ordinary(ATTEMPT, directory=True).stat()
    require(record['attempt_directory'] == {'path': str(ATTEMPT), 'device': root_info.st_dev, 'inode': root_info.st_ino},
            'Exact attempt identity required')
    current, directories = inventory(True)
    require(len(current) == 109 and sum(item['bytes'] for item in current) == 249_979_161, 'Exact attempt inventory required')
    previous_path = CAMPAIGN / 'failed-attempt-cleanup-review.json'
    previous = read_metadata(previous_path)
    require(previous['passed'] is True and previous['attempt'] == str(ATTEMPT), 'Prior cleanup review identity required')
    old = previous['immutable_artifact_inventory']
    attempt_old = {name[len('training-r1/'):]: value for name, value in old.items() if name.startswith('training-r1/')}
    normalized = {row['path']: {'bytes': row['bytes'], 'sha256': row['sha256']} for row in current}
    require(normalized == attempt_old, 'Prior attempt inventory differs')
    sibling_old = {name: value for name, value in old.items() if not name.startswith('training-r1/')}
    require(len(old) == 117 and len(sibling_old) == 8, 'Prior review scope differs')
    siblings = {}
    for name, expected in sibling_old.items():
        actual = pin(CAMPAIGN / name)
        require({'bytes': actual['bytes'], 'sha256': actual['sha256']} == expected, 'Prior sibling changed')
        siblings[name] = actual
    manifest = read_metadata(CAMPAIGN / 'training-manifest.json')
    extensions = {}
    for name, expected_sha in manifest['extensions'].items():
        actual = pin(CAMPAIGN / 'experiment-source' / name)
        require(actual['sha256'] == expected_sha, 'Frozen source generation changed')
        extensions[name] = actual
    second, second_directories = inventory(False)
    require(second == current and second_directories == directories, 'Attempt changed across independent inventories')
    process_map = processes()
    require(record['owner_pid'] not in process_map, 'Original owner PID exists or was reused')
    child_rows = []
    for child in [record.get('child'), *record.get('prior_children', [])]:
        if child is None:
            continue
        leader = process_map.get(child['pid'])
        require(leader is None or leader['birth'] == child['birth'], 'Recorded child PID was reused')
        live = sum(row['group_pid'] == child['pid'] and row['state'] != 'Z' for row in process_map.values())
        require(live == 0, 'Recorded child group is live')
        child_rows.append({'pid': child['pid'], 'birth': child['birth'], 'leader_observed': leader is not None,
                           'live_non_zombie_group_members': live})
    failure = read_metadata(ATTEMPT / 'failure.json')
    historical = failure['resources']
    scheduler_path = Path('/tmp/ipfs-datasets-resource-scheduler-1000.json')
    scheduler_pin = pin(scheduler_path)
    scheduler = read_metadata(scheduler_path)
    historical_lease_id = historical['resource_lease']['lease_id']
    require(historical_lease_id not in scheduler['leases'], 'Historical candidate scheduler lease reappeared')
    command = read_metadata(ATTEMPT / 'command.json')
    original_owner_path = Path(command['cwd']) / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py'
    base = read_metadata(CAMPAIGN / 'base.json')['base']
    source_paths = [CAMPAIGN / name for name in ('run_training_reserved.py', 'review_failed_attempt.py',
                    'adopt_shared_scheduler.py', 'training-plan.json', 'training-manifest.json', 'readiness.json',
                    'publication-script-review-attempt2.json', 'publish.py', 'guardian-exit.json', 'before.json')]
    source_paths += [previous_path, original_owner_path, F / 'administrative-storage-closeout-independent-review-v01.json',
                     F / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_resource_recovery.py',
                     F / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py']
    proof_pins = {str(path): pin(path) for path in source_paths}
    asset_manifest = Path(manifest['asset_manifest'])
    assets = read_metadata(asset_manifest)
    proof_pins[str(asset_manifest)] = pin(asset_manifest)
    report = {
        'schema': 'generated-field-single-claim-closeout-preparation/v1', 'passed': True, 'findings': [],
        'prepared_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'preparer': pin(Path(__file__)),
        'ledger_before': ledger_pin, 'reservation_id': OWN, 'record_body_sha256': EXPECTED_RECORD_SHA256,
        'original_owner_pid': record['owner_pid'], 'record_status': 'retained', 'storage_bytes': 4_000_000_000,
        'attempt_identity': record['attempt_directory'], 'roots': ledger['roots'], 'child_group_observations': child_rows,
        'actual_owner_pid_absent': True, 'registered_external_charges': 0,
        'complete_regular_unaliased_artifact_inventory': current, 'directory_identities': directories,
        'artifact_count': 109, 'artifact_bytes': 249_979_161, 'readonly_file_fsync_completed': True,
        'readonly_directory_fsync_completed': True, 'hash_inventory_checked_again': True,
        'prior_review': pin(previous_path), 'prior_review_count_explanation': {
            'total_regular_file_entries': 117, 'attempt_files_with_training_r1_prefix': 109,
            'sibling_source_test_plan_readiness_files': 8, 'directory_entries_in_prior_inventory': 0,
            'all_109_attempt_bytes_and_sha256_match': True, 'all_8_sibling_bytes_and_sha256_match': True,
            'current_attempt_descendant_directory_count': len(directories) - 1},
        'prior_sibling_pins': siblings, 'source_base_declared_by_campaign': base,
        'source_metadata_pins': proof_pins, 'frozen_source_extensions': extensions,
        'registered_input_dependencies_not_deleted_or_replayed': manifest['inputs'],
        'historical_guardian': {'resource_source_current_pin': pin(original_owner_path),
            'historical_source_file_current_link_count': original_owner_path.stat().st_nlink,
            'historical_receipt_storage_limit_bytes': historical['storage_limit_bytes'],
            'memory_mb': 4096, 'cpu_slots': 1, 'child_process_slots': 1,
            'child_failure': failure['error'], 'claimed_cleanup_leader_reaped': failure['cleanup']['leader_reaped'],
            'claimed_cleanup_live_groups': failure['cleanup']['live_group_processes'],
            'historical_scheduler_lease_id': historical['resource_lease']['lease_id'],
            'historical_lease_released': historical['resource_lease']['released'],
            'historical_lease_cancelled': historical['resource_lease']['cancelled'],
            'actual_scheduler_state_at_read': scheduler_pin,
            'actual_owned_historical_lease_absent': True,
            'historical_source_hardlink_aliasing_is_metadata_only_not_attempt_artifact_qualification': True},
        'retained_outputs': {'model_state_files_by_name_only': [row for row in current if row['path'].endswith('-state.json')],
            'fit_summary_directories_by_name_only': sorted(path.parent.name for path in (ATTEMPT / 'results').glob('*/summary.json')),
            'aggregate_summary_exists': (ATTEMPT / 'results/summary.json').exists(),
            'campaign_publication_receipt_exists': (CAMPAIGN / 'publication.json').exists(),
            'metadata_describes_partial_four_fit_attempt_not_completed_eighteen_fit_comparison': True,
            'target_model_states_parsed_or_replayed': False, 'all_output_bytes_to_remain_unchanged': True},
        'local_hf_asset_provenance': {'asset_manifest': pin(asset_manifest), 'model_revision': assets['model_revision'],
            'code_revision': assets['code_revision'], 'registered_asset_metadata': assets['files'],
            'meaning': 'Frozen input encoder assets, not proof that these target decoder states are archived on HF.',
            'fresh_hub_calls': 0, 'target_decoder_hf_archive_verified': False},
        'proposed_single_claim_procedure': [
            'Obtain owner-scoped concrete independent review for this exact claim and immutable artifact inventory. This preparation does not authorize release.',
            'Use the reviewed modern administrative recovery API with explicit capacity_policy=administrative_closeout and unchanged145GB b00 owner; do not invoke historical140GB guardian or adopt its PID.',
            'Prepare a distinct narrow-write applicator/protocol pinned to then-current ledger, exact target body, all512 other body hashes, roots, source and live-owner/group absence.',
            'Retain exact109 output files and8 prior sibling artifacts. Invoke no models, replay, compiler, leases, admission, deletion, archival migration or bulk closeout.',
            'Use existing stable owner lock and one atomic fsynced writer; full target4GB stays charged in first scan, second scan projects only this record released with explicitly prospective accounting.',
            'Only reviewed closeout bookkeeping fields on selected record may change; preserve every foreign body, limit, roots and record set. Full ledger backups stay private.',
            'Verify actual released-record readback and run a separate fresh actual postwrite census, retain all output hashes, and report any remaining overage without claiming admission.',
            'Run no training until a separate fresh qualified admission and sufficient stable margin; do not retry or roll back on uncertain atomic-write failure.'],
        'ledger_record_count': 513,
        'foreign_512_record_body_hashes': {key: digest(value) for key, value in ledger['reservations'].items() if key != OWN},
        'full_pre_claim_bytes_at_preparation': sum(value['storage_bytes'] for value in ledger['reservations'].values() if value['status'] != 'released'),
        'hypothetical_post_claim_bytes_excluding_only_this_claim': sum(value['storage_bytes'] for value in ledger['reservations'].values() if value['status'] != 'released') - 4_000_000_000,
        'hypothetical_values_not_actual_postwrite_census': True,
        'claims_or_outputs_modified': False, 'recovery_api_invoked': False, 'live_lock_acquired': False,
        'models_or_compiler_started': False, 'training_or_promotion_authority': False,
        'scope_or_release_approval': False, 'bulk_foreign_closeout_approved': False}
    require(pin(LEDGER) == ledger_pin and roots_identity(ledger['roots']) == ledger['roots'], 'Ledger or roots changed during preparation')
    require(pin(scheduler_path) == scheduler_pin, 'Scheduler endpoint changed during preparation')
    output_bytes = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    fd = os.open(OUTPUT, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        written = 0
        while written < len(output_bytes):
            count = os.write(fd, memoryview(output_bytes)[written:])
            require(count > 0, 'Metadata report write made no progress')
            written += count
        os.fsync(fd)
    finally:
        os.close(fd)
    print(json.dumps({'report': pin(OUTPUT), 'passed': True, 'recovery_api_invoked': False,
                      'live_lock_acquired': False, 'artifact_count': 109, 'artifact_bytes': 249_979_161}, sort_keys=True))


if __name__ == '__main__':
    main()
