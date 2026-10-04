"""Synthetic, model-free contracts for the matched-content comparison runner."""
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

PATH=Path(__file__).resolve().parents[5]/'scripts/ops/autoencoder/benchmark_content_matched_modality_training.py'
SPEC=importlib.util.spec_from_file_location('_content_matched_runner_tests',PATH)
subject=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(subject)


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def bank_fixture():
    rows=[]
    for actor in range(5):
        for action in range(3):
            for obj in range(2):
                for modality,phrases in [('O',('must','is required to')),('P',('may','is allowed to')),('F',('must not','is forbidden to'))]:
                    for style,phrase in enumerate(phrases):
                        text=f'The actor{actor} {phrase} action{action} the object{obj}.'
                        rows.append(dict(id=str(len(rows)),source_text=text,source_sha256=hashlib.sha256(text.encode()).hexdigest(),modality=modality,wording_style=style))
    return dict(rows=rows)


def sampler_report(candidate):
    bank=bank_fixture();groups,independent,matched=subject.sampler_inventory(bank,1729,digest)
    report={'config':{'seed':1729},'auxiliary_source_modality_bank_receipt':{},'committed_updates':[]}
    if candidate:
        report.update(auxiliary_source_modality_sampler='content_matched_cycles',auxiliary_source_modality_matched_update_bound=330,
            auxiliary_source_modality_independent_remainder_updates_planned=10,auxiliary_source_modality_matched_committed_updates=330,
            auxiliary_source_modality_independent_remainder_committed_updates=10,auxiliary_source_modality_full_budget_exposure_equivalence_reached=True)
        report['auxiliary_source_modality_bank_receipt'].update(sampler_policy='content_matched_cycles',content_group_count=30,content_group_order=groups,
            content_group_order_sha256=digest(groups),matched_update_bound=330,independent_remainder_updates=10,full_budget_per_source_exposure_matches_independent=True)
    for step,indices in enumerate(matched if candidate else independent):
        r={'indices':indices}
        if candidate:
            r.update(sampler_policy='content_matched_cycles',matched_update_bound=330,sampling_mode='content_matched' if step<330 else 'independent_remainder')
            if step<330:r.update(content_group_index=step%30,content_cycle_index=step//30,content_group={k:groups[step%30][k] for k in ('actor','action','object')})
        report['committed_updates'].append({'auxiliary_source_modality':{'receipt':r}})
    calls=[];ctx={'parent_runner':SimpleNamespace(validate_auxiliary_report=lambda *a:calls.append(a)),
        'core':SimpleNamespace(digest=digest),'modality_banks':{'full180':bank}}
    return ctx,report,calls


def test_exact_four_fits_same_bank_and_new_sampling_only():
    assert len(subject.jobs())==4
    assert [(d,s,r['name']) for d,s,r in subject.jobs()]==[(384,s,r['name']) for s in (1729,2718) for r in subject.ARMS]
    control,candidate=deepcopy(subject.ARMS);control.pop('name');candidate.pop('name')
    assert candidate.pop('auxiliary_source_modality_sampler')=='content_matched_cycles'
    assert control==candidate and control['bank_kind']=='full180'
    assert len(subject.CONTROLS)==8 and subject.FIXED['additional_candidate_control']=='recurrent-residual-off'
    assert subject.FIXED['fresh_evaluation_used_for_selection'] is False


@pytest.mark.parametrize('key,value',[('fit_count',6),('matched_optimizer_updates',340),('independent_remainder_updates',0),
    ('auxiliary_positive_presentations_per_fit',1980),('fixed_encoder_context_tokens',1024),('fixed_decoder_output_limit',1024),
    ('auxiliary_full_vocabulary_size',3),('temperature',1),('learning_rate',.01),('selection_unchanged',False),
    ('exposed_r6_panel_count',12),('max_seconds_entire_run',1500),('production_promotion_allowed',True),
    ('fresh_evaluation_used_for_selection',True),('fresh_evaluation_seed',20261006),('boundary_replay_atol',1e-4)])
def test_fixed_plan_refuses_exposure_or_gate_drift(key,value):
    plan=deepcopy(subject.FIXED);subject.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError,match='fixed content-matched'):subject.validate_plan(plan)


@pytest.mark.parametrize('candidate',[False,True])
def test_trainer_call_differs_only_sampler_keyword(candidate):
    calls=[];ctx=dict(owners={'long_span_source_value_training':SimpleNamespace(train=lambda *a,**k:calls.append((a,k)))},
        rows={'train':['train'],'validation':['dev']},references={'train':['labels'],'validation':['dev labels']},
        donor={'codec':{},'input_transform':{}},lineage={},validate_rule='validator',validator_id='id',stages=[],source_contexts={},
        modality_banks={'full180':{'bank':'180'}})
    subject.train_candidate(ctx,'model',1729,subject.ARMS[int(candidate)]);a,kw=calls[0]
    assert a==('model',['train'],['dev']) and kw['auxiliary_source_modality_bank'] is ctx['modality_banks']['full180']
    assert kw['auxiliary_source_modality_weight']==.05 and kw['generated_boundary_retry_on_mismatch'] is True
    assert kw['generated_boundary_weight']==kw['action_contrastive_weight']==.05
    assert kw['source_value_weight']==kw['cardinality_weight']==.25 and kw['non_action_learning_rate_multiplier']==10.
    assert kw.get('auxiliary_source_modality_sampler')==('content_matched_cycles' if candidate else None)
    assert kw['config']['max_optimizer_steps']==1000 and kw['config']['max_target_tokens']==512 and kw['config']['max_seconds']==180


@pytest.mark.parametrize('seed',[1729,2718])
def test_grouping_preserves_every_source_exposure_and_exact_tail(seed):
    bank=bank_fixture();groups,independent,matched=subject.sampler_inventory(bank,seed,digest)
    assert len(groups)==30 and matched[330:]==independent[330:]
    assert Counter(i for row in matched for i in row)==Counter(i for row in independent for i in row)
    assert Counter(Counter(i for row in matched for i in row).values())=={11:120,12:60}
    for step,row in enumerate(matched[:330]):
        assert row==groups[step%30]['indices']
        assert [(bank['rows'][i]['modality'],bank['rows'][i]['wording_style']) for i in row]==[('O',0),('O',1),('P',0),('P',1),('F',0),('F',1)]


@pytest.mark.parametrize('change',[lambda b:b['rows'].pop(),lambda b:b['rows'].__setitem__(0,b['rows'][1]),lambda b:b['rows'][0].update(source_text='Unparsed source')])
def test_incomplete_or_repeated_content_group_refused(change):
    bank=bank_fixture();change(bank)
    with pytest.raises(ValueError):subject.sampler_inventory(bank,1729,digest)


@pytest.mark.parametrize('candidate',[False,True])
def test_new_sampler_validator_checks_complete_inventory(candidate):
    ctx,report,calls=sampler_report(candidate)
    receipt=subject.validate_auxiliary_report(ctx,report,subject.ARMS[int(candidate)])
    assert receipt['complete'] and sum(receipt['per_source_presentations'].values())==2040
    assert calls[0][2]==subject.ARMS[0]


@pytest.mark.parametrize('change',[lambda r:r['committed_updates'][0]['auxiliary_source_modality']['receipt']['indices'].reverse(),
    lambda r:r['committed_updates'][330]['auxiliary_source_modality']['receipt'].update(indices=[0,1,2,3,4,5]),
    lambda r:r.update(auxiliary_source_modality_matched_committed_updates=340),
    lambda r:r['auxiliary_source_modality_bank_receipt'].update(content_group_order_sha256='forged'),
    lambda r:r['committed_updates'][1]['auxiliary_source_modality']['receipt'].update(content_cycle_index=1),
    lambda r:r['committed_updates'][330]['auxiliary_source_modality']['receipt'].update(content_group={}),
    lambda r:r['committed_updates'][329]['auxiliary_source_modality']['receipt'].update(sampling_mode='independent_remainder'),
    lambda r:r['committed_updates'].pop()])
def test_bad_sampler_receipts_rejected(change):
    ctx,report,_=sampler_report(True);change(report)
    with pytest.raises(ValueError):subject.validate_auxiliary_report(ctx,report,subject.ARMS[1])


def test_default_does_not_gain_sampler_metadata():
    ctx,report,_=sampler_report(False);report['auxiliary_source_modality_sampler']='independent'
    with pytest.raises(ValueError,match='default sampler'):subject.validate_auxiliary_report(ctx,report,subject.ARMS[0])


def timing_fixture():
    return dict(elapsed_seconds=1.,auxiliary_source_modality_preparation_elapsed_seconds=2.,
        auxiliary_source_modality_bank_receipt={'elapsed_seconds':3.,'sampling':'stable'},
        committed_updates=[dict(auxiliary_source_modality={'receipt':{'elapsed_seconds':4.,'indices':[1,2]}},
            generated_boundary=dict(elapsed_seconds=5.,generation={'elapsed_seconds':6.,'token_ids':[4]},
                collection_sha256='timed digest',replay_attempts=[{'elapsed_seconds':7.,'elapsed_seconds_scope':'stable','logits':[.5]}]))])


def test_control_only_excludes_declared_timing_and_preserves_raw_receipt():
    old=timing_fixture();new=deepcopy(old);new['elapsed_seconds']=100.;new['committed_updates'][0]['generated_boundary']['collection_sha256']='different'
    assert subject.baseline_comparable(old)==subject.baseline_comparable(new)
    assert old['elapsed_seconds']==1. and old['committed_updates'][0]['generated_boundary']['collection_sha256']=='timed digest'
    new['committed_updates'][0]['generated_boundary']['replay_attempts'][0]['logits']=[.6]
    assert subject.baseline_comparable(old)!=subject.baseline_comparable(new)


@pytest.mark.parametrize('n',[0,7,9,12])
def test_all_eight_panels_required_before_reference_access(n,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('reference read before complete prediction barrier')
    monkeypatch.setattr(subject,'bound_json',forbidden)
    with pytest.raises(ValueError,match='all8 exposed'):subject.load_exposed_references({},[{}]*n)


def test_failed_fit_clears_no_progress_claim_and_hides_error_message(tmp_path,monkeypatch):
    saved=[]
    def fail(*args):raise ValueError('secret diagnostic must not be copied')
    monkeypatch.setattr(subject,'train_candidate',fail)
    ctx={'core':SimpleNamespace(tensor_digest=lambda _: 'initial'),'helpers':SimpleNamespace(save=lambda p,v:saved.append(v))}
    with pytest.raises(ValueError):subject.fit_and_record(ctx,'model',1729,subject.ARMS[1],tmp_path,'initial')
    assert saved[0]['completed_optimizer_steps'] is None and saved[0]['caller_tensor_unchanged']
    assert 'secret diagnostic' not in json.dumps(saved[0])


def test_four_frozen_roots_are_authenticated_and_hacc_rejected(tmp_path,monkeypatch):
    roots=[tmp_path/n for n in ('dependency','parent','previous','new')];relative=subject.TRAINER
    for i,root in enumerate(roots):(root/relative).parent.mkdir(parents=True);(root/relative).write_text(str(i))
    modules={subject.PREFIX+str(i):SimpleNamespace(__file__=str(root/relative)) for i,root in enumerate(roots)}
    monkeypatch.setattr(subject.sys,'modules',modules)
    ctx=dict(manifest={'parent_extension_root':str(roots[1])},parent_manifest={'extensions':{relative:subject.sha(roots[1]/relative)}},
        previous_extension_root=roots[2],previous_manifest={'extensions':{relative:subject.sha(roots[2]/relative)}},outer_pins={relative:subject.sha(roots[3]/relative)})
    args=SimpleNamespace(dependency_root=roots[0],extension_root=roots[3]);assert len(subject.source_inventory(args,ctx))==4
    bad=tmp_path/'HACC.py';bad.write_text('drift');modules[subject.PREFIX+'bad']=SimpleNamespace(__file__=str(bad))
    with pytest.raises(ValueError,match='outside four isolated'):subject.source_inventory(args,ctx)


@pytest.mark.parametrize('seed',[1729,2718])
def test_published_full180_report_and_panel_interface_without_model_execution(seed):
    """Historical artifact schema smoke; never imports a producer or model."""
    candidates=[parent/'workspace/test-logs/decoder-modality-gap-r2-20261004' for parent in PATH.parents]
    root=next((path for path in candidates if path.is_dir()),candidates[0])
    folder=root/'training-r1/results'/f'384-aux-full180-{seed}'
    if not folder.exists():pytest.skip('optional authenticated historical workspace artifacts unavailable')
    run=json.loads((folder/'summary.json').read_bytes());refs=[run['training_ref'],*run['states'].values(),
        *[r for panels in run['postfit'].values() for r in panels.values()]]
    inputs={str(Path(r['path']).resolve()):r['sha256'] for r in refs}
    manifest={'inputs':inputs};report=subject.bound_json(manifest,run['training_ref']['path'],run['training_ref']['sha256'])
    assert len(report['committed_updates'])==340
    comparable=subject.baseline_comparable(report)
    assert comparable['optimizer_steps']==340 and comparable['auxiliary_source_modality_presentations']==2040
    assert 'elapsed_seconds' not in comparable and 'elapsed_seconds' in report
    panels={role:{label:{'predictions':subject.bound_json(manifest,ref['path'],ref['sha256'])['predictions'],
        'numerical':subject.bound_json(manifest,ref['path'],ref['sha256'])['report']} for label,ref in items.items()}
        for role,items in run['postfit'].items()}
    for panels_by_role in panels.values():
        for panel in panels_by_role.values():
            for key in subject.FIXED['control_panel_numerical_equivalence_exclusions']:panel['numerical'][key]+=1.
    ctx={'control_runs':{run['arm']:run},'outer_manifest':manifest}
    receipt=subject.validate_control(ctx,report,panels,run['states'],seed)
    assert receipt['complete'] and receipt['all_tensors_and_predictions_equal'] and receipt['numerical_reports_equal']
    assert receipt['excluded_fields']==subject.FIXED['baseline_equivalence_exclusions']


def test_panel_numerics_exclude_only_declared_time_derived_fields():
    a={'elapsed_seconds':1.,'spans_per_wall_second':2.,'wall_seconds_per_span':3.,'timing_scope':'whole','metrics':{'ce':.5}}
    b=dict(a,elapsed_seconds=10.,spans_per_wall_second=20.,wall_seconds_per_span=30.)
    assert subject.numerical_comparable(a)==subject.numerical_comparable(b)
    b['metrics']={'ce':.6}
    assert subject.numerical_comparable(a)!=subject.numerical_comparable(b)


def overlay_fixture(tmp_path,monkeypatch,*,attribute=False,fail=None):
    from types import ModuleType
    oldroot,newroot=(tmp_path/x for x in ('old','new'))
    for root in (oldroot,newroot):
        for relative in (subject.HELPER,subject.TRAINER):
            path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('marker='+repr(str(root))+'\n')
    canonical=subject.PREFIX+'source_modality_auxiliary_training'
    package=ModuleType(subject.PREFIX.rstrip('.'))
    spec=importlib.util.spec_from_file_location(canonical,oldroot/subject.HELPER)
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    canonical_trainer=ModuleType('historical_canonical')
    previous_trainer=ModuleType('historical_sibling')
    modules={canonical:old,subject.PREFIX.rstrip('.'):package,
        subject.PREFIX+'long_span_source_value_training':canonical_trainer,
        subject.PREFIX+'_source_modality_training_owner':previous_trainer}
    monkeypatch.setattr(subject.sys,'modules',modules)
    if attribute:setattr(package,'source_modality_auxiliary_training',old)
    def extension(root,relative,name,pins):
        assert name not in modules
        assert subject.sha(root/relative)==pins[relative]
        spec=importlib.util.spec_from_file_location(name,root/relative);module=importlib.util.module_from_spec(spec)
        modules[name]=module
        if fail==relative:raise RuntimeError('retained test import failure')
        spec.loader.exec_module(module);return module
    ctx={'helpers':SimpleNamespace(extension=extension),'owners':{'source_modality_auxiliary_training':old,
        'long_span_source_value_training':previous_trainer}}
    pins=lambda root:{p:subject.sha(root/p) for p in (subject.HELPER,subject.TRAINER)}
    return ctx,oldroot,newroot,pins(oldroot),pins(newroot),package,old,canonical_trainer,previous_trainer


@pytest.mark.parametrize('attribute',[False,True])
def test_authenticated_overlay_keeps_old_trainers_and_binds_lazy_import(tmp_path,monkeypatch,attribute):
    ctx,oldroot,newroot,oldpins,pins,package,old,canonical_trainer,previous_trainer=overlay_fixture(tmp_path,monkeypatch,attribute=attribute)
    subject.load_intervention_extensions(ctx,oldroot,newroot,oldpins,pins)
    modules=subject.sys.modules
    assert modules[subject.PREFIX+'_r7_modality_helper_before_content_matched'] is old
    assert modules[subject.PREFIX+'long_span_source_value_training'] is canonical_trainer
    assert modules[subject.PREFIX+'_source_modality_training_owner'] is previous_trainer
    assert modules[subject.PREFIX+'_content_matched_modality_training_owner'] is ctx['owners']['long_span_source_value_training']
    assert package.source_modality_auxiliary_training is ctx['owners']['source_modality_auxiliary_training']
    assert package.source_modality_auxiliary_training is not old
    assert ctx['source_overlay']['previous_package_attribute_present'] is attribute


@pytest.mark.parametrize('attribute',[False,True])
@pytest.mark.parametrize('fail',[subject.HELPER,subject.TRAINER])
def test_overlay_import_failure_restores_module_cache_and_package(tmp_path,monkeypatch,attribute,fail):
    ctx,oldroot,newroot,oldpins,pins,package,old,*_=overlay_fixture(tmp_path,monkeypatch,attribute=attribute,fail=fail)
    previous=dict(subject.sys.modules);owners=dict(ctx['owners'])
    with pytest.raises(RuntimeError,match='retained test import failure'):
        subject.load_intervention_extensions(ctx,oldroot,newroot,oldpins,pins)
    assert subject.sys.modules==previous and ctx['owners']==owners and 'source_overlay' not in ctx
    assert hasattr(package,'source_modality_auxiliary_training') is attribute
    if attribute:assert package.source_modality_auxiliary_training is old


@pytest.mark.parametrize('case',['foreign_attribute','wrong_path','wrong_spec','changed_old','changed_new','wrong_owner','existing_alias','existing_trainer'])
def test_overlay_rejects_unowned_or_changed_source_before_mutation(tmp_path,monkeypatch,case):
    ctx,oldroot,newroot,oldpins,pins,package,old,*_=overlay_fixture(tmp_path,monkeypatch)
    if case=='foreign_attribute':package.source_modality_auxiliary_training=object()
    elif case=='wrong_path':old.__file__=str(newroot/subject.HELPER)
    elif case=='wrong_spec':old.__spec__.origin=str(newroot/subject.HELPER)
    elif case=='changed_old':oldpins[subject.HELPER]='0'*64
    elif case=='changed_new':pins[subject.TRAINER]='0'*64
    elif case=='wrong_owner':ctx['owners']['source_modality_auxiliary_training']=object()
    elif case=='existing_alias':subject.sys.modules[subject.PREFIX+'_r7_modality_helper_before_content_matched']=object()
    elif case=='existing_trainer':subject.sys.modules[subject.PREFIX+'_content_matched_modality_training_owner']=object()
    before=dict(subject.sys.modules);owners=dict(ctx['owners'])
    with pytest.raises(ValueError):subject.load_intervention_extensions(ctx,oldroot,newroot,oldpins,pins)
    assert subject.sys.modules==before and ctx['owners']==owners


def test_real_frozen_registration_closure_without_models_or_torch():
    """Real historical imports reproduce the collision without donor restoration."""
    import os,subprocess,sys
    candidates=[parent for parent in PATH.parents if (parent/'workspace/test-logs/decoder-source-margin-20261004/experiment-source').is_dir()]
    if not candidates:pytest.skip('authenticated historical workspace unavailable')
    root=candidates[0]
    code=r"""
import importlib,importlib.abc,importlib.util,json,sys
from pathlib import Path
from types import SimpleNamespace
P=Path(sys.argv[1]); runner_path=Path(sys.argv[2])
F6=P/'workspace/test-logs/decoder-source-margin-20261004/experiment-source'
F7=P/'workspace/test-logs/decoder-modality-gap-r2-20261004/experiment-source'
S=P/'workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2'
class NoModels(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in ('torch','transformers','sentence_transformers'):
   raise AssertionError('model import forbidden in registration smoke: '+fullname)
sys.meta_path.insert(0,NoModels());sys.dont_write_bytecode=True;sys.path.insert(0,str(S))
spec=importlib.util.spec_from_file_location('_overlay_registration_runner',runner_path)
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
package=importlib.import_module(r.PREFIX.rstrip('.'))
package.__path__.insert(0,str(F6/r.AUTO))
spec=importlib.util.spec_from_file_location('_frozen_exact_extension_loader',F6/'scripts/ops/autoencoder/benchmark_decoder_source_fidelity.py')
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
f6=json.loads((F6.parent/'training-manifest.json').read_bytes())['extensions']
f7=json.loads((F7.parent/'training-manifest.json').read_bytes())['extensions']
canonical=h.extension(F6,r.TRAINER,r.PREFIX+'long_span_source_value_training',f6)
old=h.extension(F7,r.HELPER,r.PREFIX+'source_modality_auxiliary_training',f7)
previous=h.extension(F7,r.TRAINER,r.PREFIX+'_source_modality_training_owner',f7)
ctx={'helpers':h,'owners':{'source_modality_auxiliary_training':old,'long_span_source_value_training':previous}}
newroot=runner_path.parents[3]
pins={p:r.sha(newroot/p) for p in (r.HELPER,r.TRAINER)}
r.load_intervention_extensions(ctx,F7,newroot,f7,pins)
assert sys.modules[r.PREFIX+'long_span_source_value_training'] is canonical
assert sys.modules[r.PREFIX+'_source_modality_training_owner'] is previous
assert sys.modules[r.PREFIX+'_r7_modality_helper_before_content_matched'] is old
assert package.source_modality_auxiliary_training is ctx['owners']['source_modality_auxiliary_training']
assert ctx['owners']['long_span_source_value_training'].__name__==r.PREFIX+'_content_matched_modality_training_owner'
assert 'sampler' in __import__('inspect').signature(package.source_modality_auxiliary_training.prepare_tensor_cache).parameters
assert 'torch' not in sys.modules
for name,module in list(sys.modules.items()):
 if name.startswith('ipfs_datasets_py') and getattr(module,'__file__',None):
  path=Path(module.__file__).resolve()
  assert any(path.is_relative_to(root) for root in (S,F6,F7,newroot)),str(path)
print('real frozen registration closure passed; no model imports or forwards')
"""
    env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',CUDA_VISIBLE_DEVICES='',PYTHONDONTWRITEBYTECODE='1')
    result=subprocess.run([sys.executable,'-c',code,str(root),str(PATH)],cwd=root,env=env,text=True,capture_output=True,timeout=60)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert 'real frozen registration closure passed' in result.stdout
