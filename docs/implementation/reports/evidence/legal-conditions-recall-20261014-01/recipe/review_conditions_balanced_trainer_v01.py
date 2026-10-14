"""Root source-only trainer qualification; no trained checkpoint is parsed."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

F=Path(__file__).resolve().parent
W=F/'datasets'
OLD=F.parent/'legal-head-repair-20261014-01'
artifacts={}
def pin(path):
    p=Path(path)
    assert p.is_absolute() and p.resolve()==p and p.is_file() and not p.is_symlink()
    assert 'private-runtime-snapshots' not in p.parts
    before=p.stat();raw=p.read_bytes();after=p.stat()
    assert (before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
    d=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    assert str(p) not in artifacts or artifacts[str(p)]==d
    artifacts[str(p)]=d
    return dict(path=str(p),**d)
model=W/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_conditions_balanced.py'
tests=W/'tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_conditions_balanced_contracts.py'
design=F/'training-design-v01.json'
for p in (model,tests,design):
    assert p.stat().st_mode & 0o222 == 0, 'Author must seal final source/test/design'
    pin(p)
proposal=json.loads(design.read_bytes())
retained_path=F/'retained-source-owners-v01.json';pin(retained_path)
retained=json.loads(retained_path.read_bytes())
assert retained['passed'] is True and retained['findings']==[]
assert len(retained['source_owner_pins'])==38
owners={}
for name,descriptor in retained['source_owner_pins'].items():
    assert pin(descriptor['path'])==descriptor
    owners[name]=descriptor
owners['ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_conditions_balanced']=pin(model)
previous=model.with_name('legal_span_conditions_presence.py')
pin(previous)
def functions(p):return {n.name:n for n in ast.parse(p.read_bytes()).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
new,old=functions(model),functions(previous)
unchanged=['_model','_configure_parameters','_partition','_initial_state','_inactive_state','_branch_digests',
    '_state_digest','_row_invariants','_validate_freeze_entry','_frozen_head_digest','_finite_shape','_trainable_shapes',
    '_validate_optimizer_state','_source','_origin','_validated','_restore','save_checkpoint','load_checkpoint','_write_artifact',
    'source_only_parity']
for name in unchanged:assert ast.dump(new[name],include_attributes=False)==ast.dump(old[name],include_attributes=False),name
for p in (F/'evaluation-contract-v01.json',F/'evaluation-contract-root-review-v01.json',F/'phase-intake-v01.json',
          OLD/'trainer-source-independent-review-v01.json'):
    pin(p)
test_command=[sys.executable,'-B',str(tests)]
started=time.monotonic()
result=subprocess.run(test_command,cwd=W,capture_output=True,text=True)
assert result.returncode==0 and 'Ran 9 tests' in result.stderr and result.stderr.rstrip().endswith('OK'),result.stdout+result.stderr
for p in (model,tests,design):pin(p)
log=F/'root-trainer-contract-controls-v01.log'
with log.open('x') as stream:stream.write(result.stdout+result.stderr)
log.chmod(0o444);pin(log)
for path,d in list(artifacts.items()):assert {k:pin(path)[k] for k in ('bytes','sha256')}==d
out=dict(schema='conditions-balanced-trainer-source-independent-review/v1',passed=True,findings=[],
    artifacts=artifacts,source_owner_pins=owners,retained_owners=38,total_model_owners=39,
    exact_unchanged_N11_function_owners=unchanged,
    model_geometry=dict(tensors=42,frozen=40,optimizer_tensors=2,active_values=130,inactive_values=390),
    loss='Mean over all12 rows of per-row conditions CE times fixed7/8 absent or7/6 present, derived only from96/72 training counts; unweighted CE separately traced.',
    donor='Exact trained N10; no N11 continuation or inherited Adam moments.',
    recipe=dict(new_updates=32,batch_size=12,seed=1729,source_occurrences=384),
    review_basis='Full N11-to-N12 source diff plus behavioral scalar/vector fake controls, closed policy/count/trace validation, unchanged factory/restore/provenance/serialization owners and retained38 raw hashes.',
    root_controls=dict(command=test_command,passed=True,cases=9,wall_seconds=time.monotonic()-started),
    actual_checkpoint_JSON_parses=0,model_or_numerical_imports=0,private_resource_reads=0,reference_body_reads=0,
    default_promotion=False,recall_improvement_guaranteed=False,actual_training_authorized_by_this_source_gate=False)
p=F/'trainer-source-independent-review-v01.json'
with p.open('x') as stream:json.dump(out,stream,sort_keys=True,indent=2);stream.write('\n')
p.chmod(0o444)
print(json.dumps(dict(passed=True,owners=len(owners),review=pin(p))))
