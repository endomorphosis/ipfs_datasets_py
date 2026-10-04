"""Postfit source-only evaluation separates persisted generation from labels."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[5]/'scripts/ops/autoencoder/evaluate_source_margin_holdout.py'
SPEC = importlib.util.spec_from_file_location('_source_margin_holdout_tests', PATH)
subject = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(subject)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
    return dict(path=str(path), sha256=subject.sha(path), bytes=path.stat().st_size)


def digest(value):
    import hashlib
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',',':'), ensure_ascii=False,
        allow_nan=False).encode()).hexdigest()


@pytest.mark.parametrize('key,value', [('panel_count',18),('state_count',18),('fit_count',12),('samples_per_panel',1),
    ('roles',['last-attempt']),('primary_endpoint','selected'),('temperature',.1),('batch_size',16),
    ('fixed_encoder_context_tokens',1024),('fixed_decoder_output_limit',1024),('generation_reference_access',True),
    ('all_predictions_persisted_before_reference_load',False),('optimizer_steps',1),('qualified',True),
    ('selection_performed',True),('max_seconds_entire_run',3600)])
def test_plan_cannot_relax_exposure_or_success(key,value):
    plan = deepcopy(subject.FIXED); subject.validate_plan(plan); plan[key] = value
    with pytest.raises(ValueError, match='fixed source-margin holdout'):
        subject.validate_plan(plan)


def test_registered_jobs_preserve_all_arms_seeds_and_roles():
    assert len(subject.jobs()) == len(set(subject.jobs())) == 18
    assert subject.ROLES == ['last-attempt','selected']
    assert len([(job,role) for job in subject.jobs() for role in subject.ROLES]) == 36
    assert all(value is False for value in subject.FALSE.values())


@pytest.mark.parametrize('field', ['target','target_ids','target_token_ids','rules','references','components','training_pair_seen'])
def test_source_container_rejects_labels_even_in_unused_metadata(field):
    with pytest.raises(ValueError, match='reference material'):
        subject._source_only(dict(dimensions={'8':dict(rows=[dict(id='x',source_text='x',input=[0.])],
            representation=dict(extra={field:[]}))}))


def test_source_vectors_and_descriptors_are_allowed():
    subject._source_only(dict(dimensions={'8':dict(rows=[dict(id='x',source_text='x',input=[0.])],
        source_contexts={'x':dict(source_sha256='h',segments=[dict(source_text='x',vector=[0.])])})}))


def run_fixture(tmp_path):
    manifest = dict(inputs={}, saved_summaries={}); records = []
    def bound(path,value):
        ref = save(path,value); manifest['inputs'][str(path.resolve())] = ref['sha256']; return ref
    for dimension,seed,arm in subject.jobs():
        name = f'{dimension}-{arm}-{seed}'; folder = tmp_path/name
        report = bound(folder/'training.json',dict(stopped_reason='epochs_completed',optimizer_steps=340))
        states = {role:bound(folder/(role+'.json'),dict(role=role)) for role in subject.ROLES}
        ref = bound(folder/'summary.json',dict(arm=name,dimension=dimension,seed=seed,recipe=dict(name=arm),
            budget_completed=True,training_ref=report,states=states))
        manifest['saved_summaries'][name] = ref['path']
        records.append(dict(arm=name,summary_path=ref['path'],summary_sha256=ref['sha256']))
    summary = dict(schema='source-margin-training-comparison/v1',complete=True,training_executed=True,
        all_six_published_source_head_lr10_baselines_replayed=True,runs=records)
    return manifest,summary


def test_exact_complete_eighteen_runs_are_required_before_loading_models(tmp_path):
    manifest,summary = run_fixture(tmp_path)
    assert list(subject.validate_saved_runs(manifest,summary)) == [r['arm'] for r in summary['runs']]
    summary['runs'].pop()
    with pytest.raises(ValueError,match='eighteen saved run'):
        subject.validate_saved_runs(manifest,summary)


@pytest.mark.parametrize('mutation',['incomplete','unbound_state','changed_state','unbound_summary','unfinished_steps'])
def test_invalid_saved_run_prevents_evaluation(tmp_path,mutation):
    manifest,summary = run_fixture(tmp_path)
    item = summary['runs'][0]; path = Path(item['summary_path']); run = json.loads(path.read_text())
    if mutation == 'incomplete':
        summary['complete'] = False
    elif mutation == 'unbound_state':
        manifest['inputs'].pop(str(Path(run['states']['selected']['path']).resolve()))
    elif mutation == 'changed_state':
        Path(run['states']['last-attempt']['path']).write_text('{}')
    elif mutation == 'unbound_summary':
        manifest['saved_summaries'][item['arm']] = str(tmp_path/'other.json')
    else:
        training = Path(run['training_ref']['path'])
        training.write_text(json.dumps(dict(stopped_reason='deadline',optimizer_steps=339)))
        run['training_ref']['sha256'] = manifest['inputs'][str(training)] = subject.sha(training)
        path.write_text(json.dumps(run)); item['summary_sha256'] = manifest['inputs'][str(path)] = subject.sha(path)
    with pytest.raises(ValueError):
        subject.validate_saved_runs(manifest,summary)


def test_references_cannot_open_until_all_prediction_roles_exist(monkeypatch):
    calls = []
    monkeypatch.setattr(subject,'bound_json',lambda *a,**kw:calls.append(a))
    with pytest.raises(ValueError,match='all36 predictions'):
        subject.load_fresh_references({},[])
    assert calls == []


def prediction_inventory(tmp_path):
    records = []
    rows = [dict(id=f'fresh-{i}', source_text=f'fresh clause{i}',input=[0.]) for i in range(48)]
    for dimension,seed,arm in subject.jobs():
        name = f'{dimension}-{arm}-{seed}'
        for role in subject.ROLES:
            ref = save(tmp_path/name/(role+'.json'),dict(complete=True,model_tensor_sha256='same',
                generation_reference_access=False,predictions=[dict(id=r['id']) for r in rows]))
            records.append(dict(arm=name,role=role,predictions_ref=ref,state_ref=dict(tensor_sha256='same')))
    ctx = dict(fresh_inputs=dict(dimensions={'8':dict(rows=rows)}))
    return ctx,records


@pytest.mark.parametrize('mutation',['bytes','complete','state','identities','label_access'])
def test_persisted_predictions_are_verified_before_any_label_read(tmp_path,monkeypatch,mutation):
    ctx,records = prediction_inventory(tmp_path); ref = records[0]['predictions_ref']; path = Path(ref['path'])
    value = json.loads(path.read_text())
    if mutation == 'complete': value['complete'] = False
    elif mutation == 'state': value['model_tensor_sha256'] = 'changed'
    elif mutation == 'identities': value['predictions'].pop()
    elif mutation == 'label_access': value['generation_reference_access'] = True
    else: value['changed'] = True
    path.write_text(json.dumps(value))
    if mutation != 'bytes': ref['sha256'] = subject.sha(path)
    monkeypatch.setattr(subject,'bound_json',lambda *a,**kw:pytest.fail('opened references before prediction check'))
    with pytest.raises(ValueError,match='persisted predictions'):
        subject.load_fresh_references(ctx,records)


def generation_fixture():
    torch = pytest.importorskip('torch')
    model = torch.nn.Module(); model.dimension = 8
    model.register_parameter('weight',torch.nn.Parameter(torch.tensor([1.])))
    model.child = torch.nn.Dropout(); model.child.eval()
    rows = [dict(id=f'row-{i}',source_text=f'clause{i}',input=[1.]+[0.]*7) for i in range(9)]
    contexts = {row['id']:dict(source_only=True) for row in rows}; calls = []
    def greedy(actual_torch, actual_model, data, cap, size, deadline, **kwargs):
        assert not torch.is_grad_enabled() and not model.training
        assert actual_model is model and cap == 512 and size == 32
        calls.append((data.clone(),kwargs))
        return data,[[3] for _ in data],['eos' for _ in data]
    core = SimpleNamespace(_torch=lambda:torch,digest=digest,tensor_digest=lambda m:digest(m.weight.tolist()),
        _greedy=greedy,_source_context_kwargs=lambda t,part,ctx,transform:dict(source_context={'ids':[r['id'] for r in part]}))
    ctx = dict(core=core,native_runner=SimpleNamespace(transformed_rows=lambda t,part,transform:t.tensor([r['input'] for r in part])))
    lane = dict(fresh_rows=rows,fresh_contexts=contexts,donor=dict(input_transform=dict(scale=1.),codec=dict(target_vocabulary=list(range(32)))))
    return torch,ctx,lane,model,calls


def test_generation_is_single_source_only_pass_and_restores_modes():
    torch,ctx,lane,model,calls = generation_fixture()
    modes = {name:part.training for name,part in model.named_modules()}
    result = subject.generate_panel(ctx,lane,model,subject.time.monotonic()+30)
    assert len(calls) == 2 and [len(call[0]) for call in calls] == [8,1]
    assert [p['id'] for p in result['predictions']] == [r['id'] for r in lane['fresh_rows']]
    assert result['generation_reference_access'] is False and result['reconstructed_input_mse'] == 0.
    assert {name:part.training for name,part in model.named_modules()} == modes
    assert model.weight.grad is None and all(result[key] is False for key in subject.FALSE)


@pytest.mark.parametrize('mode',['timeout','mutation','labels'])
def test_generation_cannot_publish_incomplete_or_mutated_output(mode):
    torch,ctx,lane,model,calls = generation_fixture()
    if mode == 'timeout': ctx['core']._greedy = lambda *a,**kw:None
    elif mode == 'labels': lane['fresh_rows'][0]['target_ids'] = [1,3,2]
    else:
        original = ctx['core']._greedy
        def changed(*a,**kw):
            with torch.no_grad(): model.weight.add_(1.)
            return original(*a,**kw)
        ctx['core']._greedy = changed
    with pytest.raises(ValueError):
        subject.generate_panel(ctx,lane,model,subject.time.monotonic()+30)


def test_scoring_uses_saved_generation_and_one_teacher_forced_pass(monkeypatch):
    torch = pytest.importorskip('torch')
    from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
    from ipfs_datasets_py.logic.formalization.autoencoder import decoder_source_fidelity as scorer
    from .test_ordered_clause_recurrent_training_runner import real_fixture
    old_threads = torch.get_num_threads(); torch.set_num_threads(1)
    try:
        model,_,train,_,options,contexts = real_fixture(monkeypatch)
        rows = [{k:r[k] for k in ('id','source_text','input')} for r in train]
        targets = {r['id']:r['target_ids'] for r in train}
        refs = [dict(row,template_family='synthetic_family',target_ids=targets[row['id']],
            components=[dict(slot=i,training_pair_seen=True) for i in range(row['clause_count'])])
            for row in options['training_references']]
        predictions = [dict(id=row['id'],token_ids=row['target_ids'][1:-1],generation_status='eos',eos_reached=True) for row in train]
        prediction = dict(complete=True,predictions=predictions,model_tensor_sha256=core.tensor_digest(model),
            source_rows_sha256=core.digest(rows),source_contexts_sha256=core.digest(contexts['train']))
        lane = dict(fresh_rows=rows,fresh_contexts=contexts['train'],dimension=8,
            donor=dict(codec=options['codec'],input_transform=options['input_transform']),
            validate_rule=options['validate_rule'],validator_id=options['validator_id'])
        ctx = dict(core=core,scorer=scorer)
        monkeypatch.setattr(core,'_greedy',lambda *a,**kw:pytest.fail('posthoc greedy repeated'))
        original = core._logits; calls = []
        def observed(*a,**kw):
            calls.append(kw)
            assert not torch.is_grad_enabled()
            return original(*a,**kw)
        monkeypatch.setattr(core,'_logits',observed)
        result = subject.score_panel(ctx,lane,model,prediction,refs,subject.time.monotonic()+30)
        assert len(calls) == (len(rows)+7)//8
        assert result['fidelity']['metrics']['ordered_exact'] == len(rows)
        assert result['by_training_pair_stratum']['all_seen']['metrics']['ordered_exact'] == len(rows)
        numerical = result['teacher_forced']; measured = numerical['rows']
        assert numerical['valid_target_tokens'] == sum(len(r['target_ids'])-1 for r in train)
        assert numerical['token_cross_entropy'] == pytest.approx(sum(sum(r['token_cross_entropies']) for r in measured)/numerical['valid_target_tokens'])
        assert numerical['greedy_repeated'] is False and numerical['used_for_selection'] is False
        assert all(result[key] is False for key in subject.FALSE)
    finally:
        torch.set_num_threads(old_threads)


def main_fixture(tmp_path,monkeypatch, *, fail_after=None):
    plan_path = tmp_path/'plan.json'; save(plan_path,{})
    output = tmp_path/'out'; events = []
    monkeypatch.setattr(sys,'argv',['run','--dependency-root',str(tmp_path),'--extension-root',str(tmp_path),
        '--manifest',str(tmp_path/'manifest.json'),'--plan',str(plan_path),'--output',str(output),'--phase','evaluation'])
    runs = {f'{d}-{arm}-{seed}':dict(states={role:dict(tensor_sha256=f'{d}-{arm}-{seed}-{role}')
        for role in subject.ROLES}) for d,seed,arm in subject.jobs()}
    ctx = dict(helpers=SimpleNamespace(save=save,inventory=lambda *a:{'source':'stable'}),
        core=SimpleNamespace(digest=digest),manifest=dict(inputs={},plan_sha256=subject.sha(plan_path),comparison_seal='seal'),
        plan={},tree={},pins={},saved_runs=runs)
    monkeypatch.setattr(subject,'load_context',lambda args:ctx)
    monkeypatch.setattr(subject,'prepare_lane',lambda c,d:dict(dimension=d))
    monkeypatch.setattr(subject,'restore_state',lambda c,l,r,role:(dict(role=role,dimension=l['dimension']),{}))
    def generate(*a):
        if fail_after is not None and len(events) == fail_after: raise TimeoutError('synthetic generation timeout')
        events.append('generation')
        return dict(elapsed_seconds=.01,complete=True)
    def labels(c,records):
        assert len(records) == 36 and events == ['generation']*36
        assert (output/'predictions-complete.json').exists()
        assert len(list(output.glob('*/*-predictions.json'))) == 36
        assert not list(output.glob('*/*-score.json'))
        events.append('labels')
        return [],dict(authored_modal_assumption='synthetic',target_provenance='authored')
    def score(*a):
        assert 'labels' in events
        events.append('score')
        return dict(elapsed_seconds=.02,fidelity=dict(metrics=dict(ordered_exact=0,syntax_valid=0)),
            teacher_forced=dict(token_cross_entropy=3.))
    monkeypatch.setattr(subject,'generate_panel',generate)
    monkeypatch.setattr(subject,'load_fresh_references',labels)
    monkeypatch.setattr(subject,'score_panel',score)
    return output,events


def test_driver_persists_all36_predictions_before_any_labels_or_scoring(tmp_path,monkeypatch):
    output,events = main_fixture(tmp_path,monkeypatch)
    subject.main()
    assert events == ['generation']*36+['labels']+['score']*36
    summary = json.loads((output/'summary.json').read_text())
    assert summary['complete'] is True and len(summary['panels']) == 36
    assert all(summary[key] is False for key in subject.FALSE)
    assert summary['fresh_authored_holdout'] is True and summary['fresh_holdout_exposed_after_this_evaluation'] is True


def test_partial_generation_retains_files_but_never_opens_labels(tmp_path,monkeypatch):
    output,events = main_fixture(tmp_path,monkeypatch,fail_after=3)
    with pytest.raises(TimeoutError): subject.main()
    assert events == ['generation']*3 and len(list(output.glob('*/*-predictions.json'))) == 3
    assert not (output/'predictions-complete.json').exists() and not (output/'summary.json').exists()


def restore_fixture(tmp_path):
    torch = pytest.importorskip('torch')
    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__(); self.weight = torch.nn.Parameter(torch.zeros(1))
        def describe(self): return dict(schema='synthetic')
    recipe = dict(name=subject.ARMS[0]); codec = dict(target_vocabulary=['a']); transform = dict(scale=1.)
    values = {'weight':[2.]}; tensor_hash = digest([2.])
    state = dict(schema='private-native-dimension-source-state/v1',role='last-attempt',dimension=8,
        recipe=recipe,codec=codec,input_transform=transform,weights_sha256=digest(values),
        tensor_sha256=tensor_hash,model_state=values,architecture=dict(schema='synthetic'),
        qualified=False,admitted=False,proof_authority=False,checkpoint_promoted=False)
    ref = save(tmp_path/'state.json',state); ref['tensor_sha256'] = tensor_hash
    run = dict(dimension=8,seed=1729,recipe=recipe,states={'last-attempt':ref})
    checks = []
    ctx = dict(manifest=dict(inputs={str(tmp_path/'state.json'):ref['sha256']}),
        core=SimpleNamespace(digest=digest,tensor_digest=lambda model:digest(model.weight.tolist())),
        training_runner=SimpleNamespace(ARMS=[recipe],bind_candidate=lambda *a:Model()),
        clause_runner=SimpleNamespace(restored_tensors=lambda lane,values,current:{k:torch.tensor(v) for k,v in values.items()}),
        native_runner=SimpleNamespace(validate_wrapper_state=lambda lane,values:checks.append(values)))
    lane = dict(dimension=8,donor=dict(codec=codec,input_transform=transform))
    return ctx,lane,run,state,checks


def test_saved_state_uses_exact_architecture_transform_and_tensor_digest(tmp_path):
    ctx,lane,run,state,checks = restore_fixture(tmp_path)
    model,actual = subject.restore_state(ctx,lane,run,'last-attempt')
    assert actual == state and model.weight.tolist() == [2.] and len(checks) == 1


@pytest.mark.parametrize('key,value',[('role','selected'),('dimension',384),('codec',{}),('input_transform',{}),
    ('architecture',{'schema':'changed'}),('weights_sha256','changed'),('tensor_sha256','changed'),('admitted',True)])
def test_even_rehashed_state_cannot_change_registered_model_identity(tmp_path,key,value):
    ctx,lane,run,state,_ = restore_fixture(tmp_path)
    state[key] = value; path = Path(run['states']['last-attempt']['path']); path.write_text(json.dumps(state))
    run['states']['last-attempt']['sha256'] = ctx['manifest']['inputs'][str(path)] = subject.sha(path)
    with pytest.raises(ValueError): subject.restore_state(ctx,lane,run,'last-attempt')


def preparation_fixture(tmp_path):
    rows = [dict(id=f'fresh-{i}',source_text=f'new clause{i}',input=[1.]+[0.]*7) for i in range(48)]
    contexts = {r['id']:dict(source='context') for r in rows}; codec = {}; saved = tmp_path/'training/8'
    lane = dict(dimension=8,preparation=dict(training_only=True),source_contexts=dict(train={},validation={}),
        rows=dict(train=[dict(id='old',source_text='old clause')],validation=[dict(id='dev',source_text='dev clause')]),
        donor=dict(codec=codec,input_transform=dict(scale=2.)))
    manifest = dict(inputs={},saved_summaries={'8-source-head-lr10-1729':str(tmp_path/'training/8-source-head-lr10-1729/summary.json')})
    for name,value in [('preprocessing.json',lane['preparation']),('source-contexts.json',lane['source_contexts']),('training-rows.json',lane['rows'])]:
        ref = save(saved/name,value); manifest['inputs'][str(saved/name)] = ref['sha256']
    owner = SimpleNamespace(build_source_contexts=lambda sources,cache:deepcopy(contexts),
        validate_contexts=lambda actual,context:dict(dimension=8,reference_labels_accessed=False))
    ctx = dict(manifest=manifest,saved_runs={'8-source-head-lr10-1729':dict(arm='8-source-head-lr10-1729')},
        native_runner=SimpleNamespace(prepare_dimension=lambda c,d:deepcopy(lane)),core=SimpleNamespace(_vector=lambda vector,d:None),
        owners=dict(clause_source_context=owner),fresh_inputs=dict(dimensions={'8':dict(rows=rows,source_contexts=contexts,clause_cache=[])}))
    return ctx,lane


def test_fresh_preprocessing_reuses_saved_training_only_values(tmp_path):
    ctx,old = preparation_fixture(tmp_path); lane = subject.prepare_lane(ctx,8)
    assert lane['preparation'] == old['preparation'] and lane['donor'] == old['donor']
    assert len(lane['fresh_rows']) == 48 and len(lane['fresh_contexts']) == 48


@pytest.mark.parametrize('mutation',['preprocessing','contexts','row_target','paragraph_overlap','clause_overlap'])
def test_fresh_context_or_preprocessing_drift_is_rejected(tmp_path,mutation):
    ctx,lane = preparation_fixture(tmp_path)
    data = ctx['fresh_inputs']['dimensions']['8']
    if mutation == 'preprocessing':
        ctx['native_runner'].prepare_dimension = lambda c,d:dict(lane,preparation=dict(training_only=False))
    elif mutation == 'contexts': data['source_contexts'] = {}
    elif mutation == 'row_target': data['rows'][0]['target_ids'] = [1,3,2]
    elif mutation == 'paragraph_overlap': data['rows'][0]['source_text'] = 'old clause'
    else: data['rows'][0]['source_text'] = 'new clause\n\nold clause'
    with pytest.raises(ValueError): subject.prepare_lane(ctx,8)
