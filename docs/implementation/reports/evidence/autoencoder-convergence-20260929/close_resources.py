#!/usr/bin/env python3
"""Read-only closeout: never alters/releases a ledger claim or inventories roots."""
from collections import Counter
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[3]


def read(path):
    return json.loads(Path(path).read_bytes())


def reference(path):
    path = Path(path)
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(path), 'sha256': digest, 'bytes': path.stat().st_size}


def surviving_group(child):
    result = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            text = (path / 'stat').read_text()
            fields = text[text.rfind(')') + 2:].split()
            if int(fields[2]) == child['pid']:
                result.append({'pid': int(path.name), 'birth': fields[19], 'state': fields[0]})
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, action='append', help='Repeat for owned failed/completed attempts; defaults to initial and retry.')
    parser.add_argument('--output', type=Path, default=BASE / 'resource-closeout.json')
    args = parser.parse_args()
    run_paths = args.run or [BASE / 'native-three-arm', BASE / 'native-three-arm-retry']
    before_path = BASE / 'ledger-before.json'
    before = read(before_path)
    receipts = []
    for directory in run_paths:
        directory = directory.resolve()
        path = directory / 'resources.json'
        completed = path.exists()
        if not completed:
            path = directory / 'retained-resources.json'
        receipts.append((directory, path, read(path), completed))
    ledger_paths = {item[2]['ledger_path'] for item in receipts}
    if len(ledger_paths) != 1:
        raise ValueError('Owned attempts name different resource ledgers')
    ledger_path = Path(next(iter(ledger_paths)))
    after_raw = ledger_path.read_bytes()
    after = json.loads(after_raw)
    old, current = before['reservations'], after['reservations']
    missing = sorted(set(old) - set(current))
    modified = sorted(key for key in set(old) & set(current) if old[key] != current[key])
    preserved_meta = {k: v for k, v in before.items() if k != 'reservations'} == {k: v for k, v in after.items() if k != 'reservations'}
    source_path = ROOT / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py'
    cli_path = ROOT / 'scripts/ops/legal_ir/run_incremental_autoencoders.py'
    caps = (b'MAX_STORAGE_BYTES = 80_000_000_000' in source_path.read_bytes() and
            b'not 1 <= args.storage_bytes <= 50_000_000_000' in cli_path.read_bytes())
    seed = ROOT / 'workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json'
    seed_ref = reference(seed)
    seed_ok = seed_ref['sha256'] == '1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd' and seed_ref['bytes'] == 25895338
    retained_before = [key for key, record in old.items() if record['status'] == 'retained']
    retained_after = [key for key, record in current.items() if record['status'] == 'retained']
    new = set(current) - set(old)
    owned_ids, owned_rows, owned_checks = set(), [], {}
    for directory, path, resource, completed in receipts:
        rid = resource['reservation_id']
        if rid in owned_ids:
            raise ValueError('Duplicate owned reservation')
        owned_ids.add(rid)
        record = current.get(rid, {})
        group = surviving_group(record.get('child', {'pid': -1}))
        checks = {'owned_claim_is_new': rid in new,
            'owned_storage_budget': record.get('storage_bytes') == 750000000,
            'owned_attempt_matches': record.get('attempt_directory', {}).get('path') == str(directory),
            'no_surviving_owned_process_group_members': not group}
        if completed:
            checks.update(owned_receipt_matches_ledger=resource['record'] == record,
                owned_lease_released=resource['status'] == record.get('status') == 'released' and resource['resource_lease']['released'] is True,
                owned_outputs_durable=record.get('artifacts_durable_asserted') is True and resource['cleanup_error'] is None,
                owned_actual_bytes_bounded=record.get('final_total_charged_bytes', 750000001) <= 750000000)
        else:
            failure_path, guard_path = directory / 'failure.json', directory / 'native-guard.json'
            checks.update(failed_claim_retained_without_release=record.get('status') == 'retained' and record.get('released_at') is None,
                          failed_evidence_preserved=failure_path.exists() and guard_path.exists())
            # The immutable snapshot is written before reservation.__exit__, so
            # its status can be active; record the distinction without relabeling.
        owned_checks[directory.name] = checks
        owned_rows.append({'run': directory.name, 'reservation_id': rid, 'completed': completed,
            'resource_receipt': reference(path), 'receipt_status_at_capture': resource['status'],
            'current_ledger_status': record.get('status'), 'current_resource_record': record,
            'surviving_owned_process_group': group, 'checks': checks})
    stable = ledger_path.read_bytes() == after_raw
    checks = {'original_167_records_present': len(old) == 167 and not missing,
        'original_records_byte_semantics_unchanged': not modified,
        'original_61_retained_claims_preserved': len(retained_before) == 61 and set(retained_before) <= set(retained_after),
        'ledger_metadata_roots_limit_unchanged': preserved_meta, 'ledger_stable_during_read': stable,
        'all_owned_attempt_checks_passed': all(all(row.values()) for row in owned_checks.values()),
        'storage_cap_80GB_worker_cap_50GB': after['limit_bytes'] == 80000000000 and caps,
        'protected_seed_unchanged': seed_ok}
    report = {'schema': 'read-only-resource-closeout/v2', 'checked_at': datetime.now(timezone.utc).isoformat(),
        'passed': all(checks.values()), 'checks': checks, 'before_ledger': reference(before_path),
        'after_ledger': {'path': str(ledger_path), 'sha256': hashlib.sha256(after_raw).hexdigest(), 'bytes': len(after_raw)},
        'missing_original_records': missing, 'modified_original_records': modified,
        'original_record_count': len(old), 'current_record_count': len(current),
        'status_counts_before': dict(Counter(row['status'] for row in old.values())),
        'status_counts_after': dict(Counter(row['status'] for row in current.values())),
        'unrelated_new_records': sorted(new - owned_ids), 'owned_reservations': owned_rows,
        'protected_seed': seed_ref, 'global_cap_source': reference(source_path), 'per_worker_cap_source': reference(cli_path),
        'scope': 'Read-only validation of existing finalization and deliberately retained failed claims. No release operation, no ledger writes, no whole-root inventory. Historical headroom readings are not a new capacity estimate. Unrelated new records are reported and never modified.',
        'admitted': False}
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(json.dumps({'passed': report['passed'], 'checks': checks, 'owned': owned_checks, 'unrelated_new_record_count': len(new - owned_ids)}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
