"""Copy only a closed source/metadata allowlist; no typed/corpus payload opens."""
from pathlib import Path
import datetime
import hashlib
import json
import stat

PHASE = Path(__file__).resolve().parent
REPO = Path('/home/barberb/lift_coding/artifacts/legal-conditions-composition-diagnostic-20261015-01/datasets')
DEST = REPO / 'docs/autoencoders/evidence/legal-typed-reconstruction-20261016'
RUNS = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-validation-runs')
copies = []


def add(source, relative):
    source = Path(source)
    info = source.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 2 * 1024 * 1024
    raw = source.read_bytes()
    target = DEST / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert target.read_bytes() == raw
    target.write_bytes(raw)
    copies.append({'path': relative, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'source_path': str(source)})


for name in [
    'product-contract-v01.md', 'independent-review-gap-survey-v01.json',
    'source-implementation-audit-v01.json', 'source-helper-doc-audit-v01.json',
    'source-helper-doc-audit-v02.json', 'legacy-test-id-correction-v01.json',
    'comparison-inputs-v01.json', 'comparison-request-v05.json', 'comparison-request-v05.sha256',
    'qualification-source-roster-review-v01.json', 'qualification-source-roster-review-v03.json',
    'qualification-source-roster-review-v04.json', 'qualification-request-transition-review-v05.json',
    'qualification-independent-metadata-review-v05.json', 'comparison-independent-metadata-review-v05.json',
    'source-closure-correction-v01.json', 'parser-closure-correction-v01.json',
    'qualification04-admission-refusal-v01.json',
    'qualification-prelaunch-failure-v01.json', 'qualification-prelaunch-layout-failure-v01.json',
    'qualification-prelaunch-request-pin-failure-v01.json',
    'qualification-prelaunch-parent-stdout-v01.json', 'qualification-prelaunch-parent-stderr-v01.txt',
    'qualification-prelaunch-layout-parent-stdout-v01.json', 'qualification-prelaunch-layout-parent-stderr-v01.txt',
    'qualification-prelaunch-request-pin-parent-stdout-v04.json', 'qualification-prelaunch-request-pin-parent-stderr-v04.txt',
    'resource-plan-v01.json', 'resource-plan-v02.json',
    'storage-observation-v01.json', 'storage-observer-pins-v01.json', 'observe_storage_v01.py',
    'upstream-intersection-review-v01.json', 'run_retained_comparison_v01.py',
    'curate_publication_v01.py', 'qualified-legacy-test-before-ids.py.txt',
    'postqualification-test-format-reconciliation-v01.json',
    'qualified-reconstruction-test-before-eof-format.json',
    'recover_own_failed_qualification_v01.py', 'recover_own_failed_qualification02_v01.py',
    'recover_own_failed_qualification03_v01.py', 'recover_own_empty_qualification04_v01.py',
]:
    add(PHASE / name, name)
for number in range(1, 6):
    name = f'qualification-request-v{number:02}.json'
    add(PHASE / name, name)
for number in range(1, 5):
    name = f'qualification{number:02}-own-recovery-receipt-v01.json'
    add(PHASE / name, name)
for number in range(1, 4):
    prefix = f'qualification{number:02}'
    attempt = RUNS / f'legal-typed-reconstruction-20261016-{prefix}'
    for name in ['failure.json', 'qualification-failed.json', 'stdout.log', 'stderr.log']:
        add(attempt / 'logs' / name, f'{prefix}/{name}')
    add(PHASE / f'qualification-parent-stdout-v{number:02}.json', f'{prefix}/parent-stdout.json')
    add(PHASE / f'qualification-parent-stderr-v{number:02}.txt', f'{prefix}/parent-stderr.txt')
add(PHASE / 'qualification-parent-stdout-v04.json', 'qualification04/parent-stdout.json')
add(PHASE / 'qualification-parent-stderr-v04.txt', 'qualification04/parent-stderr.txt')
for kind, prefix in [('qualification', 'qualification05'), ('comparison', 'compare05')]:
    attempt = RUNS / f'legal-typed-reconstruction-20261016-{prefix}'
    for name in ['execution.json', 'result.json', 'stdout.log', 'stderr.log', 'validation-durability.json']:
        add(attempt / 'logs' / name, f'{prefix}/{name}')
    add(PHASE / f'{kind}-parent-stdout-v05.json', f'{prefix}/parent-stdout.json')
    add(PHASE / f'{kind}-parent-stderr-v05.txt', f'{prefix}/parent-stderr.txt')
    if kind == 'qualification':
        add(attempt / 'logs/qualification.json', 'qualification05/qualification.json')
        add(attempt / 'exports/junit.xml', 'qualification05/junit.xml')
    else:
        add(attempt / 'logs/retained-comparison-receipt.json', 'compare05/retained-comparison-receipt.json')
add('/home/barberb/lift_coding/artifacts/legal-primary-graph-export-20261015-01/run_export_qualification_v03.py', 'retained-qualification-driver-v03.py')
roster = {'schema': 'legal-typed-reconstruction-publication-copy-roster/v1',
    'observed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'scope': 'Exact curated source/metadata copies from final native jobs plus failed/refused and explicit own-recovery history. Absolute original paths are provenance, not portable replay inputs. No original typed request, source corpus, relational report or comparison payload bodies are copied. Failed raw JUnit and fixture exports remain local under their recovery inventory commitments.',
    'files': sorted(copies, key=lambda row: row['path']),
    'files_excluding_this_index': len(copies), 'bytes_excluding_this_index': sum(row['bytes'] for row in copies),
    'source_payloads_copied': False, 'new_relational_or_comparison_payloads_copied': False,
    'training_performed': False, 'Lean_executed': False,
    'limitations': ['Final187-case qualification is84new+70relational+33algebra; repeated earlier runs are not additive coverage.',
        'Final retained comparison has seven named artifact checks including two refusal operations, separate from pytest counts.',
        'Only two retained authored typed requests are exercised; old producer/source HTML/scope/join and complete old tree are not replayed.',
        'Fresh interpreter over retained originals; newly saved comparison validation is in that same interpreter.',
        'Published reconstruction test removes exactly one final LF after completed native work; full AST including attributes is identical. Exact executed test bytes and reconciliation proof are included.',
        'Only this phase\'s own failed reservations were explicitly reconciled. No foreign cleanup, new recovery grant or deletion.',
        'Native captures and administrative recovery receipts do not independently authenticate live scheduler state.',
        'No legal correctness, source equivalence, reviewed gold, learned accuracy, training, Hub upload or Lean build is established.']}
(DEST / 'publication-copy-roster.json').write_text(json.dumps(roster, sort_keys=True, indent=2) + '\n')
print(json.dumps({'files_excluding_index': len(copies), 'bytes_excluding_index': roster['bytes_excluding_this_index'], 'directory': str(DEST)}))
