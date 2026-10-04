"""Closed paraphrase auxiliary recipe, source schedules and replay contracts."""
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

P=Path(__file__).resolve().parents[5]
PATH=P/'scripts/ops/autoencoder/benchmark_paraphrase_modality_training.py'
SPEC=importlib.util.spec_from_file_location('_paraphrase_modality_runner_tests',PATH)
subject=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(subject)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


@pytest.mark.parametrize('key,value',[('arms',[dict(name='new',weight=.1)]),('context_tokens',1024),
    ('temperature',1),('max_target_tokens',1024),('full_vocabulary_size',3),('optimizer_steps_per_fit',340),
    ('learning_rate',.001),('source_training_mixture_enabled',True),('grouping_or_contrastive_loss_added',True),
    ('selection_unchanged',False),('preprocessing_refitted',True),('zero_arm_exact_archived_original_only_replay',False),
    ('paraphrase_diagnostic_presentations_per_fit',2040),('original_auxiliary_presentations384',0)])
def test_fixed_recipe_refuses_data_budget_or_gate_changes(key,value):
    plan=deepcopy(subject.FIXED);subject.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError,match='recipe differs'):subject.validate_plan(plan)


def bank():
    rows=[]
    for stratum in subject.FIXED['paraphrase_auxiliary_strata']:
        modality,template=stratum.split(':',1)
        for index in range(30):
            text=f'{stratum}/{index}';sha=hashlib.sha256(text.encode()).hexdigest()
            rows.append(dict(id='clause:'+sha,source_sha256=sha,modality=modality,template=template,
                modality_token_id={'O':4,'P':5,'F':3}[modality]))
    rows.sort(key=lambda r:r['id']);return dict(rows=rows,bank_sha256='sealed')


def test_six_stratum_schedule_has_exact_exposure_and_targets():
    value=subject.schedule(bank(),digest)
    assert len(value['draws'])==170 and value['row_presentations']==1020
    counts=Counter(value['per_source_exposures'].values());assert counts=={6:120,5:60}
    assert all(draw['target_token_ids']==[4,4,5,5,3,3] and len(set(draw['row_ids']))==6 for draw in value['draws'])
    assert value==subject.schedule(bank(),digest)
    assert value['decoder_rows_changed'] is False


def test_missing_stratum_refused_and_cache_order_cannot_drift():
    short=bank();short['rows'].pop()
    with pytest.raises(ValueError,match='complete30row'):subject.schedule(short,digest)
    declared=subject.schedule(bank(),digest)
    cache=SimpleNamespace(receipt={'orders':declared['orders']})
    helper=SimpleNamespace(select_indices=lambda cache,step:tuple(declared['draws'][step]['indices']))
    subject.validate_cache_schedule(helper,cache,declared)
    cache.receipt['orders']=list(reversed(declared['orders']))
    with pytest.raises(ValueError,match='cache sampler'):subject.validate_cache_schedule(helper,cache,declared)


@pytest.mark.parametrize('width',[384,768])
@pytest.mark.parametrize('weight',[0.,.05])
def test_trainer_receives_only_new_auxiliary_and_preserves_original_owners(monkeypatch,width,weight):
    monkeypatch.setattr(subject.time,'monotonic',lambda:10.)
    seen={}
    def train(*args,**kwargs):seen.update(kwargs);return 'fit'
    lane=dict(dimension=width,owners={'long_span_source_value_training':SimpleNamespace(train=train)},
        rows={'train':'train','validation':'dev'},references={'train':'trainref','validation':'devref'},
        donor={'codec':'codec','input_transform':'original'},lineage='lineage',validate_rule='validator',
        validator_id='id',stages='original-stages',source_contexts='original-contexts',
        modality_banks={'used113':'original113'})
    payload={'source_inventory':'sealed','weight':weight}
    assert subject.train_candidate(lane,'model',payload,100.)=='fit'
    assert seen['paraphrase_modality_auxiliary'] is payload and 'source_training_mixture' not in seen
    assert seen['training_deadline']==100. and seen['config']['max_seconds']==90.
    assert seen['source_contexts']=='original-contexts' and seen['count_exposure']=='balanced_all'
    if width==384:assert seen['auxiliary_source_modality_bank']=='original113' and seen['auxiliary_source_modality_weight']==.05
    else:assert not any(k.startswith('auxiliary_source') for k in seen)


def report():
    keys=('token_ce','weighted_token_ce','count_ce','source_value_ce','raw_reconstruction_mse','objective',
        'preclip_norm','learning_rate','target_token_presentations','source_value_presentations')
    return dict(initial_weights_sha256='initial',selected_weights_sha256='selected',
        last_complete_attempt_weights_sha256='last',selected_epoch=40,
        committed_updates=[{key:i for key in keys} for i in range(170)])


def test_zero_control_requires_exact_tensors_and_all_original_update_math():
    baseline=report();current=deepcopy(baseline);subject.validate_zero_replay(current,baseline)
    current['committed_updates'][61]['preclip_norm']+=1e-10
    with pytest.raises(ValueError,match='numerical update'):subject.validate_zero_replay(current,baseline)
    current=deepcopy(baseline);current['selected_weights_sha256']='different'
    with pytest.raises(ValueError,match='archived baseline'):subject.validate_zero_replay(current,baseline)


def test_source_inventory_guard_rejects_unknown_or_changed_resident_module(monkeypatch,tmp_path):
    registered=tmp_path/'allowed.py';registered.write_text('pass\n')
    manifest={'producer_pins':{str(registered):subject.sha(registered)},'extensions':{}}
    args=SimpleNamespace(extension_root=tmp_path);ctx={'paraphrase_manifest':manifest}
    monkeypatch.setattr(subject,'package_inventory',lambda:{str(registered):subject.sha(registered)})
    assert subject.source_inventory(args,ctx)==manifest['producer_pins']
    registered.write_text('changed\n')
    with pytest.raises(ValueError,match='unbound resident'):subject.source_inventory(args,ctx)


def test_existing_output_rejected_before_any_parent_initialization(tmp_path):
    output=tmp_path/'old';output.mkdir()
    with pytest.raises(ValueError,match='remain absent'):subject.load_context(SimpleNamespace(output=output),100.)


def test_bound_input_rejects_mutation_and_unregistered_path(tmp_path):
    p=tmp_path/'artifact.json';p.write_text('{"old":true}')
    manifest={'inputs':{str(p):subject.sha(p)}}
    assert subject.bound(manifest,p)=={'old':True}
    p.write_text('{"old":false}')
    with pytest.raises(ValueError):subject.bound(manifest,p)
    with pytest.raises(ValueError):subject.bound({'inputs':{}},p)


def test_no_encoder_weight_download_or_contrastive_entrypoint():
    import ast
    tree=ast.parse(PATH.read_text())
    calls={node.func.attr for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)}
    assert not calls&{'produce_width','from_pretrained','snapshot_download','hf_hub_download','source_action_contrastive_loss'}
    assert all(value is False for value in subject.FALSE.values())
