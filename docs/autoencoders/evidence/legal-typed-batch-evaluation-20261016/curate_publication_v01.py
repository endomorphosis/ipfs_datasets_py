"""Copy explicitly selected source/native metadata only, never batch payloads."""
from pathlib import Path
import hashlib
import json
import os
import stat

PHASE = Path('/home/barberb/lift_coding/artifacts/legal-typed-batch-evaluation-20261016-01')
ROOT = Path('/home/barberb/lift_coding/artifacts/legal-conditions-composition-diagnostic-20261015-01/datasets')
DEST = ROOT / 'docs/autoencoders/evidence/legal-typed-batch-evaluation-20261016'
GUARD = Path('/home/barberb/lift_coding/artifacts/legal-primary-graph-export-20261015-01/run_export_qualification_v03.py')
LOCAL = [
    'product-contract-v01.md', 'resource-plan-v01.json', 'source-design-survey-v01.json',
    'observe_storage_v01.py', 'storage-observer-pins-v01.json', 'storage-observation-v01.json',
    'make_native_requests_v01.py', 'run_retained_batch_v01.py', 'comparison-inputs-v01.json',
    'source-author-audit-v01.json', 'source-author-audit-v02.json', 'authored-test-source-roster-v02.json',
    'namespace-correction-proof-v01.json', 'namespace-source-correction-static-review-v01.json',
    'qualification01-original-product-source.py.txt', 'recover_own_failed_qualification01_v01.py',
    'qualification01-own-recovery-receipt-v01.json',
    'qualification-source-roster-review-v01.json', 'qualification-source-roster-review-v02.json',
    'source-helper-doc-audit-v01.json', 'source-helper-doc-audit-v02.json', 'source-helper-doc-audit-v03.json',
    'qualification-independent-metadata-review-v02.json', 'retained-batch-independent-metadata-review-v02.json',
    'qualification-request-v01.json', 'qualification-request-v01.sha256',
    'qualification-request-v02.json', 'qualification-request-v02.sha256',
    'retained-batch-request-v01.json', 'retained-batch-request-v01.sha256',
    'retained-batch-request-v02.json', 'retained-batch-request-v02.sha256',
    'qualification-parent-stdout-v01.json', 'qualification-parent-stderr-v01.txt',
    'qualification-parent-stdout-v02.json', 'qualification-parent-stderr-v02.txt',
    'retained-batch-parent-stdout-v02.json', 'retained-batch-parent-stderr-v02.txt',
    'curate_publication_v01.py',
]


def snapshot(path):
    path = Path(path)
    for parent in (path.parent, *path.parent.parents):
        assert stat.S_ISDIR(parent.lstat().st_mode)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 <= before.st_size <= 4 * 1024 * 1024
        raw = stream.read(4 * 1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
    identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)
    assert len(raw) == before.st_size and identity(before) == identity(after) == identity(path.lstat())
    return raw


def main():
    assert Path.cwd() == ROOT
    sources = [(PHASE / name, name, 'source_or_metadata') for name in LOCAL]
    sources.append((GUARD, 'checked_buffer_qualification_guard_v03.py', 'source'))
    for label, request_name in [('qualification', 'qualification-request-v02.json'),
                                ('retained-batch', 'retained-batch-request-v02.json')]:
        request = json.loads(snapshot(PHASE / request_name))
        attempt = Path(request['attempt_directory'])
        relative_paths = ['logs/execution.json', 'logs/result.json', 'logs/validation-durability.json',
            'logs/stdout.log', 'logs/stderr.log']
        relative_paths += ['logs/qualification.json', 'exports/junit.xml'] if label == 'qualification' else ['logs/retained-batch-receipt.json']
        for relative in relative_paths:
            sources.append((attempt / relative, label + '/' + relative, 'native_metadata'))
    failed = Path(json.loads(snapshot(PHASE / 'qualification-request-v01.json'))['attempt_directory'])
    for name in ['failure.json', 'qualification-failed.json']:
        sources.append((failed / 'logs' / name, 'failed-qualification01/' + name, 'failed_native_metadata'))
    entries = []
    DEST.mkdir(parents=True, exist_ok=True)
    for source, relative, kind in sources:
        raw = snapshot(source)
        target = DEST / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert snapshot(target) == raw, 'different existing curated copy'
        else:
            with target.open('xb') as stream:
                stream.write(raw)
        assert snapshot(target) == raw
        entries.append({'path': relative, 'source_path': str(source), 'kind': kind,
            'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    index = {'schema': 'legal-typed-batch-evaluation-publication-copy-roster/v1',
        'listed_files': len(entries), 'listed_bytes': sum(row['bytes'] for row in entries),
        'files': entries, 'actual_payload_bodies_copied': False, 'authority_granted': False,
        'training_mask': 0, 'evaluation_gold_mask': 0,
        'limitations': ['The failed first run retained299collected/223successful/76namespace-source failures separately; the unchanged299case roster was rerun after an exact proven two-entry namespace correction. Only this phase own failed storage claim was reconciled; no failed output deletion or foreign cleanup.',
            'Only explicit source and native metadata copies are published; original typed requests and new population/reference/prediction/evaluation payloads remain local.',
            'This subset is not a self-contained payload replay corpus or a decoder inference/accuracy/Lean result.',
            'The 299-case qualification includes the112new and187existingcases, with no additive historical coverage claim.',
            'The native retained exercise is10authoredaccountingqueries from2retainedhypotheses, not10laws or modelpredictions.',
            'Saved batch revalidation runs in the same consumer; original producer/sourceHTML/scope/join/wholeoldtree were not replayed.',
            'Only native parent closeout metadata asserts sealing and resource release; producer artifacts do not grant live resource authority.']}
    raw = (json.dumps(index, sort_keys=True, indent=2) + '\n').encode()
    target = DEST / 'publication-copy-roster.json'
    if target.exists():
        assert snapshot(target) == raw
    else:
        with target.open('xb') as stream:
            stream.write(raw)
    print(json.dumps({'curated_files': len(entries) + 1, 'listed_bytes': index['listed_bytes'],
        'index_sha256': hashlib.sha256(raw).hexdigest()}, sort_keys=True))


if __name__ == '__main__':
    main()
