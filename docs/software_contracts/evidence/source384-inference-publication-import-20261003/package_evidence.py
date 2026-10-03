"""Close the import separation evidence without weights, databases or task corpus."""
from pathlib import Path
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET

B = Path(__file__).resolve().parent
D = Path('/home/barberb/lift_coding/.worktrees/ir-release-datasets-20261002')
P = D/'docs/software_contracts/evidence/source384-inference-publication-import-20261003'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy(source, relative):
    target = P/relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def write(relative, value):
    path = P/relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')


P.mkdir(parents=True, exist_ok=False)
for directory in ('before', 'datasets-02-sources', 'final-sources'):
    for path in sorted((B/directory).rglob('*')):
        if path.is_file():
            copy(path, Path('sources')/directory/path.relative_to(B/directory))
for name in ('independent-diagnosis.json', 'independent-review.json', 'frozen-sources.json',
             'implementation.patch', 'actual-inference-verdict.json',
             'actual-training-proof-verdict.json', 'datasets-02-lake-failure.json'):
    copy(B/name, name)
for prefix in ('focused-01', 'datasets-02', 'datasets-03', 'accelerate-04'):
    for suffix in ('.log', '.xml', '-command.json', '-exit.json'):
        copy(B/(prefix+suffix), Path('controls')/(prefix+suffix))
copy(Path(__file__), 'package_evidence.py')

counts = {}
for prefix in ('focused-01', 'datasets-02', 'datasets-03', 'accelerate-04'):
    cases = ET.parse(B/(prefix+'.xml')).getroot().findall('.//testcase')
    counts[prefix] = dict(tests=len(cases), errors=sum(c.find('error') is not None for c in cases),
        failures=sum(c.find('failure') is not None for c in cases),
        skipped=sum(c.find('skipped') is not None for c in cases))
assert counts['datasets-03'] == dict(tests=43, errors=0, failures=0, skipped=0)
assert counts['accelerate-04'] == dict(tests=13, errors=0, failures=0, skipped=0)
pins = json.loads((B/'frozen-sources.json').read_text())
assert all(sha(D/rel) == digest for rel,digest in pins.items())
assert sha(D/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_schema_lake.py') == json.loads((B/'before/sources.json').read_text())['ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_schema_lake.py']
write('closeout.json', dict(schema='source384-inference-publication-import-closeout@1',
    change='Move identical canonical JSON staging to already pinned shared Source384 owner; generation compatibility delegates, inference avoids training imports.',
    final_datasets_sources=pins, controls=counts, distinct_final_tests=56,
    runtime_deadlines_changed=False, training_workspace_guard_changed=False,
    model_weights_changed=False, checkpoint_release_performed=False,
    actual_inference_scope='authored local source fixture with real pinned checkpoint/GTE, import blocking and reopened registry replay',
    training_regression_scope='existing authored scalar generation tests include bounded fitting and native Lake property checks; inference itself never trains',
    docker_qualification_claimed=False, benchmark_score_claimed=False,
    authority_or_decoder_accuracy_improvement_claimed=False,
    excluded=['model weights', 'databases', 'raw benchmark corpus', 'full fixture inference output'],
    consumer_test_scope='A13 raw controls included; A source snapshots and full Docker follow-up are retained in their separate consumer evidence package',
    prior_failure='D02 selected Elan launcher and failed 20 fixture setups with zero checked properties; exact native Lake path fixes setup without relaxing assertions; test-owned replacement-registry teardown also corrected.'))
write('control-generations.json', dict(schema='source384-publication-control-generations@1',
    focused_01=dict(source='sources/datasets-02-sources', tests=5,
        note='Publication test file unchanged in final generation; five tests are a subset of final43.'),
    datasets_02=dict(source='sources/datasets-02-sources', passed=23, errors=20,
        reason='native Lake launcher refused; final source-unit fixture closes replacement registry'),
    datasets_03=dict(source='sources/final-sources', passed=43, errors=0,
        source_pins='frozen-sources.json', lake='/home/barberb/.elan/toolchains/leanprover--lean4---v4.34.1/bin/lake'),
    accelerate_04=dict(datasets_source='sources/final-sources', passed=13, errors=0)))
(P/'README.md').write_text('''# Inference publication without training workspace imports

Source384 inference now stages its artifact through the existing shared Source384
owner. The former lazy import loaded model-generation training code, which loaded
the canonical proof-workspace guard and correctly refused the deployed checkout
without Git metadata. The helper keeps the same canonical JSON bytes, temporary
directory prefix, registry staging call and cleanup behavior. Model-generation
callers retain their compatibility wrapper. No training or proof guard is relaxed.

The shared helper is covered by the existing shared source producer hash. No new
runtime module or unpinned dependency is introduced. Current-source observations,
model/producer checks, operation attachment, replay validation, cancellation and
deadlines remain at the same boundaries.

Final datasets controls passed **43/43** in 33.12 seconds. They include five staging
and guard controls, actual pinned-checkpoint/GTE inference with training/proof
imports forbidden, source/report drift rejection, replay after closing and
reopening the native registry, and the existing training-generation/proof suite.
The actual inference fixture has five functions: four decode to unverified
candidates and one exceeds the GTE token limit. Two candidates fail open for
source-contract mismatch and two for unsupported source contracts. Model execution
and publication do not establish formalization correctness or proof authority.

The existing supervisor consumer suite passed **13/13** in 41.37 seconds on the
same datasets sources, including actual inference reaching planning/dispatch and
checkpoint drift rejection. Its raw controls are included; its source snapshots
and fresh Docker qualification belong to the separate consumer evidence package.
The final distinct count is 56, without counting repeated historical controls.

The initial five staging controls passed. A subsequent broader attempt passed 23
tests and failed 20 fixture setups because its explicit Lake path selected the
Elan launcher. The native owner returned `select_installed_native_lake_not_elan_shim`.
The final run uses the previously qualified installed Lake binary. No assertion
was removed or weakened. A test-owned reopened registry handle also gained correct
teardown. Exact earlier source snapshots, failed XML/logs and the failure receipt
summary are retained beside the final successful generation.

The originating Docker trace shows the worker had returned and output checks had
run before the import failure. It did not retain a committed inference artifact or
complete qualification receipt, so it cannot support independently verified output
counts or successful inference qualification. The diagnosis records that limit.
The host controls here are not a completed Docker run or a benchmark score.

`manifest.json` closes source/test snapshots, the implementation diff, executed
commands, raw logs/XML, producer and real asset hashes, reviews and small verdicts.
Weights, databases, benchmark corpus and full fixture outputs are excluded. Their
hashes and local references support binding, not reconstruction from absent bytes.
The training regression includes bounded fixture adaptation; inference itself
does not train. No checkpoint upload, model promotion or release occurs here.
''')
files = [dict(path=p.relative_to(P).as_posix(), bytes=p.stat().st_size, sha256=sha(p))
         for p in sorted(P.rglob('*')) if p.is_file()]
write('manifest.json', dict(schema='source384-inference-publication-import-evidence@1', files=files))
scope = ['.gitattributes', 'docs/software_contracts/CODEBASE_SOURCE_UNITS_384.md',
    *[p for p in pins if p in ('ipfs_datasets_py/logic/software_contracts/codebase_source_384.py',
    'ipfs_datasets_py/logic/software_contracts/codebase_source_units_384.py',
    'ipfs_datasets_py/logic/software_contracts/codebase_model_generation.py',
    'tests/integration/logic/software_contracts/test_codebase_source384_publication.py',
    'tests/integration/logic/software_contracts/test_codebase_source_units_384.py')],
    *[p.relative_to(D).as_posix() for p in sorted(P.rglob('*')) if p.is_file()]]
(B/'scoped-files.json').write_text(json.dumps(scope, indent=2)+'\n')
(B/'scoped-files.txt').write_text('\n'.join(scope)+'\n')
print(json.dumps(dict(package=str(P), manifest_sha256=sha(P/'manifest.json'),
    members=len(files), member_bytes=sum(x['bytes'] for x in files), scoped_files=len(scope)), indent=2))
