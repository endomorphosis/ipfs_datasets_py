"""Publish accepted pending method evidence; never publish identity results.

This distinct operator leaves the completed-results helpers unchanged. Its
utilities are compiled from captured, hash-authenticated original helper bytes.
It is not an execution or storage-admission override.
"""
from pathlib import Path
import hashlib
import json
import os
import stat
from types import ModuleType

BASE = Path('/home/barberb/lift_coding')
CAMPAIGN = BASE / 'artifacts/uscode-identity-recovery-20261011-01'
UTILITY_PATH = CAMPAIGN / 'operator-source/package_identity_evidence.py'
UTILITY_SHA256 = '90111f8143f3c5e181380b280d4ccc3fa2de8fe61d7cf6efde16aa8cc4f695f6'
ADMISSION_SHA256 = 'b1e693a3ebb790a8f9d8dbda6479263573a7e2092fb7fb135f08289fc4a583c1'
MAX_FILE = 2 * 1024 * 1024
MAX_PACKAGE = 16 * 1024 * 1024
MAX_ENTRIES = 4096
SUFFIXES = {'.json', '.jsonl', '.xml', '.md', '.py', '.log'}
REQUIRED = {'STATUS.md', 'campaign.json', 'run-plan.json', 'command.json', 'arguments.json',
            'review/local-recipe-survey.json', 'review/remote-producer-survey.json',
            'review/identity-pilot-resource-survey.json', 'review/implementation-review.json',
            'review/pilot-readiness.json', 'review/final-status-review.json',
            'review/implementation-memory-review.json', 'review/pilot-readiness-02.json',
            'review/failed-attempt-resource-review.json', 'review/retry-admission-review.json',
            'review/memory-control-temporary-ownership-survey.json',
            'review/pending-publication-method-review.json'}
PARENT_COUNTS = {'retained_physical_occurrences': 64969, 'archived_distinct_ids': 443904,
                 'unresolved_archived_ids': 378935, 'source_occurrences': 3840988}


def witness(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def canonical(path, *, existing=True):
    if not path.is_absolute() or path.resolve(strict=existing) != path or path.is_symlink():
        raise ValueError('Canonical paths without aliases required')


def read_file(path):
    """Bounded canonical regular-FD capture with both path and FD fences."""
    canonical(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= MAX_FILE
                or witness(path.stat()) != witness(before)):
            raise ValueError('Evidence exceeds regular-file bounds or changed before read')
        chunks, remaining = [], before.st_size
        while remaining:
            block = os.read(fd, min(1024 * 1024, remaining))
            if not block:
                raise ValueError('Evidence shortened during capture')
            chunks.append(block)
            remaining -= len(block)
        if os.read(fd, 1):
            raise ValueError('Evidence grew during capture')
        canonical(path)
        if witness(os.fstat(fd)) != witness(before) or witness(path.stat()) != witness(before):
            raise ValueError('Evidence changed during capture')
        return b''.join(chunks), witness(before)
    finally:
        os.close(fd)


def utility_module():
    body, signature = read_file(UTILITY_PATH)
    if hashlib.sha256(body).hexdigest() != UTILITY_SHA256:
        raise ValueError('Original completed-results helper bytes differ from the frozen pin')
    module = ModuleType('authenticated_identity_packaging_utilities')
    module.__file__ = str(UTILITY_PATH)
    exec(compile(body, str(UTILITY_PATH), 'exec'), module.__dict__)
    module.REQUIRED = REQUIRED
    module.SUFFIXES = SUFFIXES
    module.read_file = read_file
    module.selected = selected
    return module, signature


def forbidden(relative, path):
    parts = Path(relative).parts
    return (path.suffix.lower() == '.parquet'
            or path.name in {'report.json', 'candidates.parquet', 'pilot-results-review.json'}
            or any(p == 'results' or p == 'measured-run' or p.startswith('measured-run-') for p in parts))


def selected():
    canonical(CAMPAIGN)
    result, count = {}, 0
    pending = [CAMPAIGN]
    while pending:
        directory = pending.pop()
        canonical(directory)
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                if count > MAX_ENTRIES:
                    raise ValueError('Campaign evidence entry bound exceeded')
                path = Path(entry.path)
                relative = path.relative_to(CAMPAIGN).as_posix()
                if forbidden(relative, path):
                    raise ValueError('Pending evidence refuses actual result/report/candidate/Parquet entries')
                if entry.is_symlink():
                    raise ValueError('Selected evidence must not use symlink aliases')
                if '__pycache__' in path.parts or relative == 'index.json' or relative.startswith('publication'):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False) and path.suffix in SUFFIXES:
                    result[relative] = path
    if not REQUIRED.issubset(result):
        raise ValueError('Required accepted pending method/resource/document evidence is missing')
    return dict(sorted(result.items()))


def checks_passed(value, *, zero_findings=True):
    checks = value.get('checks')
    return (isinstance(checks, list) and 0 < len(checks) <= 256
            and all(isinstance(c, dict) and c.get('passed') is True for c in checks)
            and type(value.get('check_count')) is int and value['check_count'] == len(checks)
            and (not zero_findings or value.get('findings') == []))


def pin_matches(pin, path, body):
    return (isinstance(pin, dict) and pin.get('path') == str(path)
            and pin.get('bytes') == len(body)
            and pin.get('sha256') == hashlib.sha256(body).hexdigest())


def reviewed(files):
    for name, body in files.items():
        if forbidden(name, Path(name)):
            raise ValueError('Actual identity results cannot enter pending evidence')
        if name.endswith('.json'):
            value = json.loads(body)
            if isinstance(value, dict) and value.get('schema') == 'uscode-retained-ordinal-diagnosis/v1':
                raise ValueError('An actual diagnostic report cannot be relabeled as pending evidence')
    final = json.loads(files['review/final-status-review.json'])
    if (final.get('status') != 'accepted' or not checks_passed(final)
            or not pin_matches(final.get('document'), CAMPAIGN / 'STATUS.md', files['STATUS.md'])):
        raise ValueError('Final pending document must match its accepted zero-finding review')
    for name in ('review/implementation-review.json', 'review/implementation-memory-review.json',
                 'review/pending-publication-method-review.json'):
        value = json.loads(files[name])
        if value.get('status') != 'accepted' or value.get('passed') is not True or not checks_passed(value):
            raise ValueError('Accepted zero-finding static method review required: ' + name)
    ready = json.loads(files['review/pilot-readiness-02.json'])
    if (ready.get('passed') is not True or ready.get('attempt') != 'ordinal-profile-02'
            or not checks_passed(ready)):
        raise ValueError('Accepted attempt02 readiness required; readiness does not establish execution')
    failed = json.loads(files['review/failed-attempt-resource-review.json'])
    if (failed.get('completed') is not True or failed.get('successful_diagnosis') is not False
            or failed.get('resource_cleanup_accepted') is not True or not checks_passed(failed)):
        raise ValueError('Failed attempt01 needs accepted stopped-resource evidence, not result acceptance')
    admission_body = files['review/retry-admission-review.json']
    admission = json.loads(admission_body)
    absent = admission.get('no_attempt_evidence', {})
    custody = admission.get('custody', {})
    findings = admission.get('findings')
    known_findings = {('execution_gate', 'filesystem_free_below_full_claims_plus_request'),
                      ('measurement_limit', 'rejected_fresh_inventory_not_durable')}
    if (hashlib.sha256(admission_body).hexdigest() != ADMISSION_SHA256
            or admission.get('schema') != 'identity-diagnosis-retry-admission-review/v1'
            or admission.get('status') != 'admission_refused_before_reservation_and_child'
            or admission.get('passed') is not True or admission.get('attempt') != 'ordinal-profile-02'
            or not checks_passed(admission, zero_findings=False)
            or not isinstance(findings, list) or len(findings) != 2
            or {(f.get('kind'), f.get('code')) for f in findings} != known_findings
            or any(absent.get(k) is not False for k in ('child_created', 'new_disk_record_created',
                'new_resource_lease_created', 'attempt02_exists', 'attempt02_adoption_receipt_exists'))
            or absent.get('child_identity') is not None or absent.get('attempt02_record_count') != 0
            or any(custody.get(k) != 0 for k in ('new_records', 'changed_records', 'missing_records'))
            or admission.get('actual_receipt_pins') or admission.get('actual_output_pins')):
        raise ValueError('Pinned accepted retry refusal and explicit no-child/record/lease evidence required')
    for key, name in (('readiness02', 'review/pilot-readiness-02.json'),
                      ('prior_failed_resource_review', 'review/failed-attempt-resource-review.json'),
                      ('exact_command', 'command.json'), ('retry_launch_binding', 'review/retry-launch-binding.json')):
        if not pin_matches(admission.get('input_pins', {}).get(key), CAMPAIGN / name, files.get(name, b'')):
            raise ValueError('Retry refusal input binding differs from captured evidence')
    campaign = json.loads(files['campaign.json'])
    parent_pin = campaign.get('parent_evidence', {}).get('campaign-summary.json')
    if not isinstance(parent_pin, dict) or not isinstance(parent_pin.get('path'), str):
        raise ValueError('Accepted parent summary reference required')
    parent_path = Path(parent_pin['path'])
    parent_body, parent_signature = read_file(parent_path)
    if not pin_matches(parent_pin, parent_path, parent_body):
        raise ValueError('Accepted parent summary byte pin differs')
    summary = json.loads(parent_body)
    observed = dict(retained_physical_occurrences=summary.get('final_accounting', {}).get('target_occurrence_count'),
        archived_distinct_ids=summary.get('archived_span_ids'), unresolved_archived_ids=summary.get('unresolved_archived_span_ids'),
        source_occurrences=summary.get('final_accounting', {}).get('source_occurrence_count'))
    if (observed != PARENT_COUNTS or summary.get('all_completed_windows_independently_reviewed') is not True
            or summary.get('complete_source_scan') is not True):
        raise ValueError('Coverage must match inherited accepted parent counts')
    return parent_pin, parent_signature


def main():
    utility, utility_signature = utility_module()
    paths = selected()
    files, signatures, total = {}, {}, 0
    for relative, path in paths.items():
        files[relative], signatures[relative] = read_file(path)
        total += len(files[relative])
        if total > MAX_PACKAGE:
            raise ValueError('Pending evidence exceeds aggregate package bound')
    parent_pin, parent_signature = reviewed(files)
    index = {'schema': 'uscode-identity-recovery-pending-evidence-index/v1',
             'stage': 'awaiting_storage_admission', 'scope': 'Accepted method and blocked execution; no actual ordinal results',
             'actual_result_review_completed': False, 'actual_diagnosis_completed': False,
             'aliases_promoted': 0, 'models_executed': False, 'training_executed': False,
             'embedding_reuse_qualified': False, 'proof_authority': False,
             'parent_coverage': {'status': 'accepted_parent_counts_not_new_measurement',
                                 'source_summary_pin': parent_pin, **PARENT_COUNTS},
             'reused_utility': {'path': str(UTILITY_PATH), 'sha256': UTILITY_SHA256},
             'files': {name: {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
                       for name, body in files.items()}}
    encoded = (json.dumps(index, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    destinations = [
        (utility.DATASETS / 'docs/autoencoders/evidence/uscode-identity-recovery-20261011-01',
         utility.DATASETS / 'docs/autoencoders/uscode_identity_recovery_20261011.md',
         'evidence/uscode-identity-recovery-20261011-01/'),
        (utility.ROOT / 'artifacts/uscode-identity-recovery-20261011-01',
         utility.ROOT / 'implementation_plan/docs/73-uscode-identity-recovery-2026-10-11.md',
         '../../artifacts/uscode-identity-recovery-20261011-01/')]
    for destination, document, prefix in destinations:
        canonical(destination, existing=False)
        canonical(document, existing=False)
        body = utility.standalone(files['STATUS.md'], prefix)
        if (len(encoded) > MAX_FILE or len(body) > MAX_FILE or total + len(encoded) + len(body) > MAX_PACKAGE):
            raise ValueError('Pending package, index and document exceed publication bounds')
        if destination.exists() or document.exists():
            raise ValueError('Pending publication must use both fresh repository destinations')
    canonical(CAMPAIGN / 'index.json', existing=False)
    if (CAMPAIGN / 'index.json').exists():
        raise ValueError('Pending campaign index must be fresh')
    utility.unchanged(paths, signatures)
    if (read_file(UTILITY_PATH)[1] != utility_signature
            or read_file(Path(parent_pin['path']))[1] != parent_signature):
        raise ValueError('Authenticated utility or parent reference changed before mutation')
    for destination, document, prefix in destinations:
        destination.mkdir(parents=True, exist_ok=False)
        for relative, body in files.items():
            utility.write_new(destination / relative, body)
        utility.write_new(destination / 'index.json', encoded)
        utility.write_new(document, utility.standalone(files['STATUS.md'], prefix))
    utility.unchanged(paths, signatures)
    if (read_file(UTILITY_PATH)[1] != utility_signature
            or read_file(Path(parent_pin['path']))[1] != parent_signature):
        raise ValueError('Authenticated utility or parent reference changed after copy')
    utility.write_new(CAMPAIGN / 'index.json', encoded)
    print(json.dumps({'stage': index['stage'], 'actual_result_review_completed': False,
                      'files_per_package': len(files) + 1, 'bytes_per_package': total + len(encoded),
                      'index_sha256': hashlib.sha256(encoded).hexdigest()}))


if __name__ == '__main__':
    main()
