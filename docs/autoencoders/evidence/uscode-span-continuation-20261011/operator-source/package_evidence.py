"""Package only compact owned evidence; never copy source DBs, vectors or weights."""
from pathlib import Path
import hashlib
import json
import shutil

BASE = Path('/home/barberb/lift_coding')
CAMPAIGN = BASE / 'artifacts/uscode-span-continuation-20261011'
DATASETS = BASE / '.worktrees/retained-wording-checkpoint-integration-datasets-20261007'
ROOT = BASE / '.worktrees/dual-bank-wording-adapter-root-20261007'
DESTINATIONS = [DATASETS / 'docs/autoencoders/evidence/uscode-span-continuation-20261011',
                ROOT / 'artifacts/uscode-span-continuation-20261011']
required = ['PROGRESS.md', 'review/implementation-review.json', 'review/results-review.json',
            'review/progress-document-review.json', 'validation/integrated-controls-receipt.json',
            'validation/incoming-source384-controls-receipt.json']
for relative in required:
    assert (CAMPAIGN / relative).is_file(), relative
for relative in required[1:4]:
    receipt = json.loads((CAMPAIGN / relative).read_bytes())
    if relative == 'review/results-review.json':
        assert receipt['passed'] and not receipt['findings']
files = []
for path in sorted(CAMPAIGN.rglob('*')):
    if not path.is_file() or path.is_symlink() or '__pycache__' in path.parts:
        continue
    relative = path.relative_to(CAMPAIGN).as_posix()
    if relative == 'index.json' or relative.startswith('publication'):
        continue
    if path.suffix not in {'.json', '.jsonl', '.xml', '.md', '.py', '.log'}:
        continue
    assert path.stat().st_size < 512_000, relative
    files.append((relative, path.read_bytes()))
index = {'schema': 'uscode-span-continuation-evidence-index/v1',
         'scope': 'archived-target inventory and bounded source-only continuation; complete_source_scan=false',
         'models_executed': False, 'training_executed': False, 'proof_authority': False,
         'source_occurrences': 24191, 'persisted_archived_targets': 2806,
         'outside_target_aggregate_count': 21385, 'cursor': {'next_section': 199, 'next_span': 64},
         'validation': {'intake_cases_passed': 375, 'incoming_source384_cases_passed': 70,
                        'independent_result_checks_passed': 28},
         'files': {relative: {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
                   for relative, body in files}}
encoded = (json.dumps(index, sort_keys=True, indent=2) + '\n').encode()
(CAMPAIGN / 'index.json').write_bytes(encoded)
for destination in DESTINATIONS:
    destination.mkdir(parents=True, exist_ok=True)
    for relative, body in files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    (destination / 'index.json').write_bytes(encoded)
    for relative, pin in index['files'].items():
        body = (destination / relative).read_bytes()
        assert len(body) == pin['bytes'] and hashlib.sha256(body).hexdigest() == pin['sha256']
progress = (CAMPAIGN / 'PROGRESS.md').read_bytes()
(DATASETS / 'docs/autoencoders/uscode_span_continuation_20261011.md').write_bytes(progress)
(ROOT / 'implementation_plan/docs/70-uscode-archived-target-reconciliation-2026-10-11.md').write_bytes(progress)
print(json.dumps({'files_per_package': len(files)+1, 'bytes_per_package': sum(len(x[1]) for x in files)+len(encoded),
                  'index_sha256': hashlib.sha256(encoded).hexdigest()}))
