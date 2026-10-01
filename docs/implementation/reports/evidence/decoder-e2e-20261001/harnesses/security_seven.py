import copy
from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
require_workspace_logic_tree()
from ipfs_datasets_py.logic.formalization.autoencoder.domain_targets import prepare_security_targets
from ipfs_datasets_py.logic.security_ir.code_logic_projection import CodeLogicEvidence, SUPPORTED_KINDS
from ipfs_datasets_py.logic.software_verification.program import ProgramIR

fixture_path = ROOT / 'tests/unit/logic/security_ir/test_code_logic_projection.py'
spec = importlib.util.spec_from_file_location('_security_seven_e2e', fixture_path)
fixture = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fixture
spec.loader.exec_module(fixture)

def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

source_paths = [fixture_path, ROOT / 'scripts/ops/autoencoder/train_native_formula.py']
for root, glob in [(ROOT / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer', '*formula*.py'),
                   (ROOT / 'ipfs_datasets_py/logic/security_ir', '*code_logic*.py')]:
    source_paths.extend(sorted(root.glob(glob)))
source_paths.extend(ROOT / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer' / name for name in
    ['autoencoder_runtime_registry.py', 'autoencoder_schema_lake.py', 'autoencoder_decoded_schema.py',
     'autoencoder_projection_features.py'])
source_paths.append(ROOT / 'ipfs_datasets_py/logic/formalization/autoencoder/domain_targets.py')
before = {str(path.relative_to(ROOT)): sha(path) for path in source_paths}
training = []
authored_inputs = []
for index in (1, 2):
    body = f'def one():\n    return {index}\n'.encode()
    fixture.BODY = body
    unit, source = fixture.binding.__wrapped__()
    owners = fixture.evidence(source)
    adjusted = []
    for item in owners:
        doc = item.document
        if isinstance(doc, ProgramIR):
            doc = replace(doc, program_id='', expressions=tuple(replace(expression, attributes={'value': index})
                if expression.expression_id == 'expr:one' else expression for expression in doc.expressions))
        adjusted.append(CodeLogicEvidence(doc, source))
    envelope = prepare_security_targets(code_unit=unit, source_bytes=body,
        typed_inputs=adjusted, requested_kinds=SUPPORTED_KINDS)
    training.append(envelope.to_dict())
    authored_inputs.append({'body': body.decode(), 'body_sha256': hashlib.sha256(body).hexdigest(),
        'unit': unit.to_dict(), 'source': source.to_dict(),
        'typed_inputs': [{'document': item.document.to_dict(), 'type': type(item.document).__name__}
                         for item in adjusted]})

tuning = copy.deepcopy(training)
for index, target in enumerate(tuning):
    target['source_digest'] = hashlib.sha256(f'security-seven-diagnostic-tuning/{index}'.encode()).hexdigest()
projection_ids = [row['projection_id'] for row in training[0]['projections']]
save(OUT / 'authored-inputs.json', authored_inputs)
save(OUT / 'corpus.json', {'training_targets': training, 'tuning_targets': tuning,
                          'projection_ids': projection_ids})
command = [sys.executable, str(ROOT / 'scripts/ops/autoencoder/train_native_formula.py'),
    '--domain', 'security_ir', '--corpus', str(OUT / 'corpus.json'),
    '--registry', str(OUT / 'control.duckdb'), '--artifact-root', str(OUT / 'artifacts'),
    '--output', str(OUT / 'trained'), '--max-seconds', '60', '--lake-timeout-seconds', '60',
    '--epochs', '35', '--latent-width', '8', '--learning-rate', '.04', '--batch-size', '1', '--seed', '1729']
env = dict(os.environ, PYTHONPATH=str(ROOT), CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='1',
           MKL_NUM_THREADS='1', IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE='0')
start = time.perf_counter()
result = subprocess.run(['/usr/bin/time', '-v', '-o', str(OUT / 'resources.txt'), *command],
    cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
(OUT / 'stdout.log').write_text(result.stdout)
(OUT / 'stderr.log').write_text(result.stderr)
after = {str(path.relative_to(ROOT)): sha(path) for path in source_paths}
report = {'schema': 'security-seven-native-cli-e2e/v1', 'command': command, 'returncode': result.returncode,
    'wall_seconds': time.perf_counter() - start, 'source_hashes_before': before, 'source_hashes_after': after,
    'source_files_unchanged': before == after, 'supported_kinds': list(SUPPORTED_KINDS),
    'projection_ids': projection_ids, 'training_samples': 2, 'tuning_samples': 2,
    'corpus_scope': 'Authored fixed-shape structures; tuning repeats training expressions under diagnostic disjoint source IDs. This is reconstruction plumbing, not semantic generalization.',
    'source_semantics_verified': False, 'model_checker_executed': False,
    'tla_scope': 'Typed transition projection may contain TLA+ model compilation; no TLC proof.',
    'admitted': False, 'qualified': False, 'publication_performed': False, 'downloads_performed': False,
    'torch_threads': 1, 'device': 'cpu', 'dtype': 'float64', 'stderr_tail': result.stderr[-4000:]}
for filename in ['training.json', 'schema-validation.json']:
    path = OUT / 'trained' / filename
    if path.exists():
        report[filename] = json.loads(path.read_text())
save(OUT / 'report.json', report)
print(json.dumps({'returncode': result.returncode, 'wall_seconds': report['wall_seconds'],
    'projection_ids': projection_ids, 'source_files_unchanged': before == after,
    'schema_pass_count': report.get('schema-validation.json', {}).get('schema_pass_count'),
    'schema_checks_complete': report.get('schema-validation.json', {}).get('schema_checks_complete'),
    'stderr': report['stderr_tail']}))
