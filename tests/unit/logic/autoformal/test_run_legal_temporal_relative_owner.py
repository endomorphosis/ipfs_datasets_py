"""Selection and boundary checks that do not create current holdout targets."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from scripts.ops.legal_ir import run_legal_temporal_relative_owner as runner


def stages():
    return [{'steps':s,'tuning_metrics':{'joint_correct':140,'selection_nll':2.}} for s in runner.STAGES]


def test_selection_uses_joint_accuracy_before_nll():
    rows=stages();rows[1]['tuning_metrics']={'joint_correct':141,'selection_nll':10.}
    assert runner.select(rows)['steps']==100


def test_selection_uses_nll_then_earlier_stage():
    rows=stages();rows[1]['tuning_metrics']['selection_nll']=1.
    rows[2]['tuning_metrics']['selection_nll']=1.
    assert runner.select(rows)['steps']==100
    assert runner.select(stages())['steps']==0


@pytest.mark.parametrize('steps',[(0,100),(0,100,100),(100,200,300),(0,200,100)])
def test_selection_rejects_missing_duplicate_or_reordered_stages(steps):
    with pytest.raises(ValueError):runner.select([{'steps':s,'tuning_metrics':{'joint_correct':1,'selection_nll':1.}} for s in steps])


@pytest.mark.parametrize('field,value',[('joint_correct',True),('joint_correct',289),('joint_correct',-1),
    ('selection_nll',float('nan')),('selection_nll',float('inf')),('selection_nll',-.1)])
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


def test_guard_denies_all_eight_references_without_reading_contents(tmp_path):
    refs={}
    for key in runner.SEALED:refs[key]=runner.write(tmp_path/(key+'.json'),{'fictional_fixture':key})
    manifest=runner.write(tmp_path/'manifest.json',{'artifacts':refs})
    config=runner.write(tmp_path/'config.json',{'corpus_manifest':manifest})
    code="""
import sys
from pathlib import Path
from scripts.ops.legal_ir import run_legal_temporal_relative_owner as r
r.install_guard(sys.argv[1])
for p in r.guard_receipt()['sealed_paths']:
 try: Path(p).read_bytes()
 except PermissionError: pass
 else: raise AssertionError('reference read allowed')
assert len(r.guard_receipt()['premature_read_attempts'])==8
assert not r.guard_receipt()['released']
"""
    env=dict(os.environ);env.update(CUDA_VISIBLE_DEVICES='-1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
    result=subprocess.run([sys.executable,'-c',code,config['path']],env=env,capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr


@pytest.mark.parametrize('corrupt',[False,True])
def test_prefit_parity_checks_inherited_fields_but_allows_new_factors(tmp_path,monkeypatch,corrupt):
    config={'parents':{str(seed):{'seed':seed} for seed in runner.SEEDS}}
    initial=runner.write(tmp_path/'initial.json',{'config':{'fixture':True},'optimizer_updates':0,
        'models':{f'{arm}-{seed}':{'arm':arm,'seed':seed} for seed in runner.SEEDS for arm in runner.runtime.ARMS}})
    monkeypatch.setattr(runner,'install_guard',lambda *_:None)
    monkeypatch.setattr(runner,'load_config',lambda *_:(config,{'fixture':True},{'tuning':[{}]*288}))
    monkeypatch.setattr(runner.runtime,'source_queries',lambda values:values)
    monkeypatch.setattr(runner,'producer_pins',lambda :{})
    def generate(checkpoint,sources,output,*,kind='relative_owner'):
        rows=[{'id':str(i),'span_confidence':.8} for i in range(288)]
        if kind=='relative_owner':
            for row in rows:row['new_factor_field']=[0.,1.]
            if corrupt:rows[287]['span_confidence']=.9
        return {'fixture':str(output)},{'rows':rows,'encoder_batch_forwards':6,'encoder_source_evaluations':288}
    monkeypatch.setattr(runner,'generate',generate)
    if corrupt:
        with pytest.raises(ValueError,match='initial inherited prediction differs'):
            runner.parity('fixture',initial['path'],tmp_path/'parity')
        assert not (tmp_path/'parity/parity-frozen.json').exists()
    else:
        pin=runner.parity('fixture',initial['path'],tmp_path/'parity')
        value=runner.read(pin)
        assert len(value['comparisons'])==6 and value['all_inherited_predictions_exact']
        assert value['encoder_source_evaluations']==2304 and value['encoder_batch_forwards']==48


def test_generation_rejects_unrecognized_decoder_kind(tmp_path):
    with pytest.raises(ValueError,match='declared decoder kind'):
        runner.generate({}, {}, tmp_path/'never.json',kind='unrecognized')
    assert not (tmp_path/'never.json').exists()


def test_producer_closure_includes_independent_metric_ancestor():
    ancestor=Path(runner.metrics.previous.__file__).resolve()
    assert runner.producer_pins()[str(ancestor)]==runner.ref(ancestor)['sha256']
