"""Retain reviewed compact evidence, excluding DBs, raw source and model assets."""
from pathlib import Path
import hashlib
import json
import os
import re
import stat

BASE = Path('/home/barberb/lift_coding')
CAMPAIGN = BASE / 'artifacts/uscode-span-rollout-20261011'
DATASETS = BASE / '.worktrees/retained-wording-checkpoint-integration-datasets-20261007'
ROOT = BASE / '.worktrees/dual-bank-wording-adapter-root-20261007'
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_BYTES = 16 * 1024 * 1024
SUFFIXES = {'.json', '.jsonl', '.xml', '.md', '.py', '.log'}
REQUIRED = {'STATUS.md', 'campaign-summary.json', 'review/final-status-review.json',
            'review/clone-implementation-review.json', 'review/rollout-results-review.json'}


def witness(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def selected_paths():
    if CAMPAIGN.resolve(strict=True) != CAMPAIGN or CAMPAIGN.is_symlink():
        raise ValueError('Campaign directory must be canonical')
    selected = {}
    for path in sorted(CAMPAIGN.rglob('*')):
        relative = path.relative_to(CAMPAIGN).as_posix()
        if (path.is_symlink() or '__pycache__' in path.parts or relative == 'index.json'
                or relative.startswith('publication') or path.suffix not in SUFFIXES):
            continue
        if path.is_file():
            selected[relative] = path
    if not REQUIRED.issubset(selected):
        raise ValueError('Required final document, summary or review is missing')
    return selected


def read_regular(path):
    if path.resolve(strict=True) != path or path.is_symlink():
        raise ValueError('Evidence files must be canonical without symlink aliases')
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
        raise ValueError('Evidence file exceeds its regular-file bound')
    with path.open('rb') as stream:
        if witness(os.fstat(stream.fileno())) != witness(before):
            raise ValueError('Evidence changed before read')
        body = stream.read(MAX_FILE_BYTES + 1)
        if witness(os.fstat(stream.fileno())) != witness(before):
            raise ValueError('Evidence changed while reading')
    if len(body) != before.st_size or witness(path.stat()) != witness(before):
        raise ValueError('Evidence changed after read')
    return body, witness(before)


def unchanged(paths, witnesses):
    if set(selected_paths()) != set(paths):
        raise ValueError('Selected evidence set changed during packaging')
    for relative, path in paths.items():
        if path.resolve(strict=True) != path or witness(path.stat()) != witnesses[relative]:
            raise ValueError('Selected evidence changed during packaging: ' + relative)


def accepted_document(files):
    review = json.loads(files['review/final-status-review.json'])
    checks = review.get('checks')
    if (review.get('status') != 'accepted' or review.get('findings') != []
            or not isinstance(checks, list) or not checks
            or any(not isinstance(c, dict) or c.get('passed') is not True for c in checks)
            or type(review.get('check_count')) is not int or review['check_count'] != len(checks)):
        raise ValueError('Final status needs accepted checks with zero findings')
    document = review.get('document', {})
    body = files['STATUS.md']
    if (document.get('path') != str(CAMPAIGN / 'STATUS.md')
            or document.get('bytes') != len(body)
            or document.get('sha256') != hashlib.sha256(body).hexdigest()):
        raise ValueError('Status bytes differ from their accepted document review')
    summary = json.loads(files['campaign-summary.json'])
    if summary.get('all_completed_windows_independently_reviewed') is not True:
        raise ValueError('Every completed window needs an independent accepted review')
    return summary


def standalone_document(body, prefix):
    def rewrite(match):
        target = match.group(1)
        if target.startswith(('#', '/', 'https://', 'http://')):
            return match.group(0)
        return '](' + prefix + target + ')'
    encoded = re.sub(r'\]\(([^)]+)\)', rewrite, body.decode('utf-8')).encode('utf-8')
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError('Standalone document exceeds its file bound')
    return encoded


def write_regular(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.resolve(strict=False) != path or path.is_symlink():
        raise ValueError('Publication target must be canonical without symlink aliases')
    with path.open('wb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    if read_regular(path)[0] != body:
        raise ValueError('Publication target differs from captured evidence')


def main():
    paths = selected_paths()
    files, witnesses, total = {}, {}, 0
    for relative, path in paths.items():
        body, signature = read_regular(path)
        total += len(body)
        if total > MAX_PACKAGE_BYTES:
            raise ValueError('Selected evidence exceeds aggregate package bound')
        files[relative], witnesses[relative] = body, signature
    summary = accepted_document(files)
    index = {'schema': 'uscode-span-rollout-evidence-index/v1',
             'scope': 'Archived-target generation; outside-target identities remain aggregate-only',
             'models_executed': False, 'training_executed': False, 'proof_authority': False,
             'final_summary': summary,
             'files': {relative: {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
                       for relative, body in files.items()}}
    encoded = (json.dumps(index, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    if len(encoded) > MAX_FILE_BYTES or total + len(encoded) > MAX_PACKAGE_BYTES:
        raise ValueError('Evidence bodies plus encoded index exceed package bounds')
    destinations = [
        (DATASETS / 'docs/autoencoders/evidence/uscode-span-rollout-20261011',
         DATASETS / 'docs/autoencoders/uscode_archive_rollout_20261011.md',
         standalone_document(files['STATUS.md'], 'evidence/uscode-span-rollout-20261011/')),
        (ROOT / 'artifacts/uscode-span-rollout-20261011',
         ROOT / 'implementation_plan/docs/72-uscode-archive-reconciliation-rollout-2026-10-11.md',
         standalone_document(files['STATUS.md'], '../../artifacts/uscode-span-rollout-20261011/'))]
    if any(total + len(encoded) + len(document) > MAX_PACKAGE_BYTES
           for _, _, document in destinations):
        raise ValueError('Package plus standalone document exceeds repository bound')
    unchanged(paths, witnesses)
    for destination, document_path, document in destinations:
        destination.mkdir(parents=True, exist_ok=True)
        if any(p.is_symlink() for p in destination.rglob('*')):
            raise ValueError('Evidence destination contains a symlink alias')
        existing = {p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file()}
        if existing.difference(set(files) | {'index.json'}):
            raise ValueError('Unexpected retained file in evidence destination')
        for relative, body in files.items():
            write_regular(destination / relative, body)
        write_regular(destination / 'index.json', encoded)
        write_regular(document_path, document)
        for relative, body in files.items():
            if read_regular(destination / relative)[0] != body:
                raise ValueError('Copied evidence differs from indexed bytes')
    unchanged(paths, witnesses)
    write_regular(CAMPAIGN / 'index.json', encoded)
    print(json.dumps({'files_per_package': len(files) + 1,
                      'bytes_per_package': total + len(encoded),
                      'standalone_document_bytes': [len(doc) for _, _, doc in destinations],
                      'index_sha256': hashlib.sha256(encoded).hexdigest()}))


if __name__ == '__main__':
    main()
