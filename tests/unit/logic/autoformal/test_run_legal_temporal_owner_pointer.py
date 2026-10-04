"""Selection and boundary checks that do not create current holdout targets."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from scripts.ops.legal_ir import run_legal_temporal_owner_pointer as runner


def stages():
    return [{'steps':s,'tuning_metrics':{'joint_correct':140,'composite_nll':2.}} for s in runner.STAGES]


def test_selection_uses_joint_accuracy_before_nll():
    rows=stages();rows[1]['tuning_metrics']={'joint_correct':141,'composite_nll':10.}
    assert runner.select(rows)['steps']==100


def test_selection_uses_nll_then_earlier_stage():
    rows=stages();rows[2]['tuning_metrics']['composite_nll']=1.
    rows[3]['tuning_metrics']['composite_nll']=1.
    assert runner.select(rows)['steps']==200
    assert runner.select(stages())['steps']==0


@pytest.mark.parametrize('steps',[(0,100,300),(0,100,100,300),(100,200,300),(0,200,100,300)])
def test_selection_rejects_missing_duplicate_or_reordered_stages(steps):
    with pytest.raises(ValueError):runner.select([{'steps':s,'tuning_metrics':{'joint_correct':1,'composite_nll':1.}} for s in steps])


@pytest.mark.parametrize('field,value',[('joint_correct',True),('joint_correct',289),('joint_correct',-1),
    ('composite_nll',float('nan')),('composite_nll',float('inf')),('composite_nll',-.1)])
def test_selection_rejects_invalid_rank(field,value):
    rows=stages();rows[1]['tuning_metrics'][field]=value
    with pytest.raises(ValueError):runner.select(rows)


def test_reference_projection_rejects_duplicate_ids_and_drops_source_features():
    rows=[{'id':'a','label':'norm','owner_anchor_span':{'char_start':0,'char_end':4},'source_text':'example'}]
    assert runner.target_map(rows)=={'a':{'label':'norm','owner_anchor_span':{'char_start':0,'char_end':4}}}
    with pytest.raises(ValueError):runner.target_map(rows+rows)


def test_reference_bytes_cannot_change_and_writes_are_exclusive(tmp_path):
    path=tmp_path/'evidence.json';pin=runner.write(path,{'value':1})
    assert runner.read(pin)=={'value':1}
    with pytest.raises(FileExistsError):runner.write(path,{'value':2})
    path.write_text('{"value":2}')
    with pytest.raises(ValueError):runner.read(pin)


def test_guard_denies_all_four_references_without_reading_contents(tmp_path):
    refs={}
    for key in runner.SEALED:refs[key]=runner.write(tmp_path/(key+'.json'),{'fictional_fixture':key})
    manifest=runner.write(tmp_path/'manifest.json',{'artifacts':refs})
    config=runner.write(tmp_path/'config.json',{'corpus_manifest':manifest})
    code="""
import sys
from pathlib import Path
from scripts.ops.legal_ir import run_legal_temporal_owner_pointer as r
r.install_guard(sys.argv[1])
for p in r.guard_receipt()['sealed_paths']:
 try: Path(p).read_bytes()
 except PermissionError: pass
 else: raise AssertionError('reference read allowed')
assert len(r.guard_receipt()['premature_read_attempts'])==4
assert not r.guard_receipt()['released']
"""
    env=dict(os.environ);env.update(CUDA_VISIBLE_DEVICES='-1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
    result=subprocess.run([sys.executable,'-c',code,config['path']],env=env,capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr
