"""The saved-state scalar observer must preserve provenance and target separation."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

PATH=Path(__file__).resolve().parents[5]/'scripts/ops/autoencoder/diagnose_contextual_scalar_margins.py'
SPEC=importlib.util.spec_from_file_location('_scalar_margin_runner_tests',PATH)
subject=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(subject)


def fixture():
    rows=[dict(id='row:'+str(i),source_text='The clerk shall file the report.',input=[float(i)],target_ids=[1,3,2]) for i in range(48)]
    predictions=[dict(id=r['id'],token_ids=[3],generation_status='eos',eos_reached=True) for r in rows]
    contexts={r['id']:{'source_only':True} for r in rows}
    events=[];model={'digest':'initial'}
    def collect(actual,sources,**kwargs):
        events.append(('collect',actual,deepcopy(sources),kwargs))
        return dict(predictions=deepcopy(predictions),complete=True,model_tensor_sha256='initial')
    def score(trace,actual,references,**kwargs):
        events.append(('score',trace,actual,references,kwargs))
        return dict(complete=True,split=kwargs['split'],per_field={})
    observer=SimpleNamespace(collect_source_scalar_trace=collect,score_scalar_trace=score)
    ctx=dict(core=SimpleNamespace(tensor_digest=lambda m:m['digest']),observer=observer)
    lane=dict(rows={'train':rows,'validation':rows},source_contexts={'train':contexts,'validation':contexts},
        references={'train':'training-labels','validation':'development-labels'},donor={'codec':{},'input_transform':{}},validate_rule=object())
    expected=dict(predictions=[dict(p,exact_target=True,reconstructed_input=[.0]) for p in predictions])
    return ctx,lane,model,expected,events


@pytest.mark.parametrize('split,scope,reference',[('train','training','training-labels'),('validation','exposed_development','development-labels')])
def test_exactly_one_label_free_collection_precedes_posthoc_labels(split,scope,reference):
    ctx,lane,model,expected,events=fixture()
    result=subject.observe_panel(ctx,lane,model,split,scope,expected,subject.time.monotonic()+30)
    assert [event[0] for event in events]==['collect','score']
    collection=events[0]
    assert collection[1] is model and len(collection[2])==48
    assert all(set(row)=={'id','input','source_text'} for row in collection[2])
    assert set(collection[3])=={'codec','input_transform','source_contexts','max_target_tokens','batch_size','deadline','max_memory_bytes'}
    assert collection[3]['max_target_tokens']==512 and collection[3]['batch_size']==8
    assert events[1][3]==reference and events[1][4]['split']==scope
    assert result['generation_predictions_exact'] and result['greedy_passes']==1 and result['optimizer_steps']==0
    assert result['training_executed'] is result['qualified'] is result['admitted'] is False
    assert model=={'digest':'initial'}


@pytest.mark.parametrize('key,value',[('id','wrong'),('token_ids',[4]),('generation_status','output_limit'),('eos_reached',False)])
def test_generation_mismatch_stops_before_any_label_scoring(key,value):
    ctx,lane,model,expected,events=fixture();expected['predictions'][0][key]=value
    with pytest.raises(ValueError,match='archived predictions'):
        subject.observe_panel(ctx,lane,model,'train','training',expected,subject.time.monotonic()+30)
    assert [event[0] for event in events]==['collect']


def test_model_change_during_observation_stops_before_labels():
    ctx,lane,model,expected,events=fixture();original=ctx['observer'].collect_source_scalar_trace
    def changed(*args,**kwargs):
        result=original(*args,**kwargs);model['digest']='changed';return result
    ctx['observer'].collect_source_scalar_trace=changed
    with pytest.raises(ValueError,match='observer changed'):
        subject.observe_panel(ctx,lane,model,'train','training',expected,subject.time.monotonic()+30)
    assert [event[0] for event in events]==['collect']


def test_model_change_during_scoring_cannot_claim_complete():
    ctx,lane,model,expected,events=fixture();original=ctx['observer'].score_scalar_trace
    def changed(*args,**kwargs):
        result=original(*args,**kwargs);model['digest']='changed';return result
    ctx['observer'].score_scalar_trace=changed
    with pytest.raises(ValueError,match='posthoc scoring changed'):
        subject.observe_panel(ctx,lane,model,'train','training',expected,subject.time.monotonic()+30)


@pytest.mark.parametrize('ticks,expected_events',[(iter([10.]),[]),(iter([0.,0.,10.]),['collect']),(iter([0.,0.,0.,10.]),['collect','score'])])
def test_panel_deadline_cannot_produce_a_completed_receipt(monkeypatch,ticks,expected_events):
    ctx,lane,model,expected,events=fixture();monkeypatch.setattr(subject.time,'monotonic',lambda:next(ticks))
    with pytest.raises(ValueError,match='deadline'):
        subject.observe_panel(ctx,lane,model,'train','training',expected,5.)
    assert [event[0] for event in events]==expected_events


@pytest.mark.parametrize('split,scope',[('train','exposed_development'),('validation','training'),('test','training'),('train','fresh_holdout')])
def test_split_cannot_be_relabelled(split,scope):
    ctx,lane,model,expected,events=fixture()
    with pytest.raises(ValueError,match='unregistered observation split'):
        subject.observe_panel(ctx,lane,model,split,scope,expected,subject.time.monotonic()+30)
    assert not events


def test_panel_rejects_unregistered_sample_count_before_collection():
    ctx,lane,model,expected,events=fixture();lane['rows']['train']=lane['rows']['train'][:-1]
    with pytest.raises(ValueError,match='panel coverage'):
        subject.observe_panel(ctx,lane,model,'train','training',expected,subject.time.monotonic()+30)
    assert not events


def test_unfinished_observer_never_invokes_reference_scoring():
    ctx,lane,model,expected,events=fixture()
    def failed(*args,**kwargs):raise TimeoutError('interrupted collector')
    ctx['observer'].collect_source_scalar_trace=failed
    with pytest.raises(TimeoutError):subject.observe_panel(ctx,lane,model,'train','training',expected,subject.time.monotonic()+30)
    assert not events


@pytest.mark.parametrize('key,value',[('temperature',1),('panel_count',18),('state_count',6),('greedy_passes_per_panel',2),
    ('optimizer_steps',1),('new_targets_created',True),('fixed_encoder_context_tokens',1024),('fixed_decoder_output_limit',1024),
    ('generation_reference_access',True),('fresh_holdout',True),('qualified',True),('max_seconds_per_panel',300)])
def test_fixed_diagnostic_contract_cannot_silently_change(key,value):
    plan=deepcopy(subject.FIXED);subject.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError,match='diagnostic plan'):subject.validate_plan(plan)


def test_all_saved_lineages_and_seeds_are_registered_without_training():
    jobs=subject.jobs()
    assert len(jobs)==18 and len(set(jobs))==18
    assert set(jobs)=={(d,s,a) for d in (8,384,768) for s in (1729,2718) for a in subject.ARMS}
    assert subject.FIXED['state_role']=='last-attempt' and subject.FIXED['training_executed'] is False
    assert subject.FIXED['splits']==['training','exposed_development']


def publication_fixture(tmp_path):
    path=tmp_path/'state.json';path.write_text('{"model":"saved"}')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    manifest={'inputs':{str(path.resolve()):digest}}
    public={'original_artifact_archive_paths':{str(path.resolve()):'states/a.json'},
        'members':{'states/a.json':{'sha256':digest,'bytes':path.stat().st_size}}}
    return path,manifest,public,digest


def test_saved_json_requires_both_sealed_and_published_identity(tmp_path):
    path,manifest,public,digest=publication_fixture(tmp_path)
    assert subject.published_json(manifest,public,path,digest)=={'model':'saved'}
    path.write_text('{"model":"other"}')
    with pytest.raises(ValueError):subject.published_json(manifest,public,path,digest)


def test_published_artifact_cannot_be_rebound_by_changing_only_input_hash(tmp_path):
    path,manifest,public,digest=publication_fixture(tmp_path)
    path.write_text('{"model":"other"}');manifest['inputs'][str(path.resolve())]=subject.sha(path)
    with pytest.raises(ValueError,match='unbound artifact alias'):
        subject.published_json(manifest,public,path)


def test_unpublished_alias_is_rejected_even_if_hash_is_sealed(tmp_path):
    path,manifest,public,digest=publication_fixture(tmp_path)
    public['original_artifact_archive_paths'].clear()
    with pytest.raises(ValueError,match='absent from published'):
        subject.published_json(manifest,public,path,digest)


def test_unsealed_alias_is_rejected_even_if_publication_has_same_bytes(tmp_path):
    path,manifest,public,digest=publication_fixture(tmp_path);manifest['inputs'].clear()
    with pytest.raises(ValueError,match='unbound artifact alias'):
        subject.published_json(manifest,public,path,digest)


def test_generation_comparison_is_exact_and_does_not_mutate_panels():
    value=[dict(id='x',token_ids=[3,4],generation_status='eos',eos_reached=True,exact_target=False,reconstructed_input=[1.])]
    original=deepcopy(value);result=subject.generation_predictions(value)
    assert value==original and result==[{k:original[0][k] for k in ('id','token_ids','generation_status','eos_reached')}]
    result[0]['token_ids'].append(9)
    assert value==original


@pytest.mark.parametrize('key,value',[('complete',False),('complete',1),('model_tensor_sha256','other')])
def test_incomplete_or_wrong_model_trace_is_not_scored(key,value):
    ctx,lane,model,expected,events=fixture();original=ctx['observer'].collect_source_scalar_trace
    def altered(*args,**kwargs):
        result=original(*args,**kwargs);result[key]=value;return result
    ctx['observer'].collect_source_scalar_trace=altered
    with pytest.raises(ValueError,match='complete trace'):
        subject.observe_panel(ctx,lane,model,'train','training',expected,subject.time.monotonic()+30)
    assert [event[0] for event in events]==['collect']


def test_cold_frozen_extension_imports_load_real_dependencies_in_order(tmp_path,monkeypatch):
    """Reproduce the original package-path failure without any model execution.

    The three extension sources and extension loader are real. Only already
    loaded native prerequisites are minimal inert modules. No package search
    path can discover an extension implicitly, matching the frozen runner.
    """
    package_name='_isolated_scalar_extension_import_test'
    prefix=package_name+'.'
    baseline=tmp_path/'frozen-native-package';baseline.mkdir()
    extension_root=tmp_path/'frozen-extensions'
    parent=ModuleType(package_name);parent.__path__=[str(baseline)]
    monkeypatch.setitem(sys.modules,package_name,parent)
    monkeypatch.setattr(subject,'PREFIX',prefix)
    prereqs={
        'decoder_cardinality_experiment':{},
        'decoder_distillation_experiment':{'_require':subject.require},
        'generated_boundary_training':{'FALSE':{},'_check_deadline':lambda *_:None,'_state_versions':lambda *_:None},
        'source_value_decoder_experiment':{'SOURCE_FIELDS':('actor','action','modality','object')},
    }
    for name,values in prereqs.items():
        module=ModuleType(prefix+name)
        module.__dict__.update(values)
        monkeypatch.setitem(sys.modules,prefix+name,module)
        setattr(parent,name,module)
    names=('contextual_generated_boundary_training','generated_field_training','generated_scalar_observation')
    pins={}
    for name in names:
        relative=subject.AUTO+name+'.py'
        output=extension_root/relative;output.parent.mkdir(parents=True,exist_ok=True)
        output.write_bytes((PATH.parents[3]/relative).read_bytes())
        pins[relative]=subject.sha(output)
    helper_spec=importlib.util.spec_from_file_location('_real_frozen_extension_loader',
        PATH.with_name('benchmark_decoder_source_fidelity.py'))
    helper=importlib.util.module_from_spec(helper_spec);helper_spec.loader.exec_module(helper)
    ctx={'helpers':helper,'owners':{}}
    try:
        # This is the previous failing order. Preserve the original package path
        # rather than hiding the defect by prepending extensions to __path__.
        with pytest.raises(ImportError,match='generated_field_training'):
            helper.extension(extension_root,subject.AUTO+names[-1]+'.py',prefix+names[-1],pins)
        sys.modules.pop(prefix+names[-1])
        with pytest.raises(ImportError,match='contextual_generated_boundary_training'):
            helper.extension(extension_root,subject.AUTO+names[1]+'.py',prefix+names[1],pins)
        sys.modules.pop(prefix+names[1])
        observer=subject.load_observer_extensions(ctx,extension_root,pins)
        assert list(ctx['owners'])==list(names)
        assert observer is ctx['owners'][names[-1]]
        assert observer.fields is ctx['owners']['generated_field_training']
        assert observer.boundary is ctx['owners']['contextual_generated_boundary_training']
        assert observer.fields.boundary is observer.boundary
        assert observer._Observer.__mro__[1] is observer.fields._Collector
        assert observer.fields._Collector.__mro__[1] is observer.boundary._Collector
        assert parent.__path__==[str(baseline)]
        assert all(Path(ctx['owners'][name].__file__).is_relative_to(extension_root) for name in names)
    finally:
        for name in names:sys.modules.pop(prefix+name,None)


def test_observer_extension_hash_mismatch_stops_before_import(tmp_path):
    relative=subject.AUTO+'contextual_generated_boundary_training.py'
    path=tmp_path/relative;path.parent.mkdir(parents=True)
    path.write_text('raise RuntimeError("untrusted file must not execute")\n')
    helper_spec=importlib.util.spec_from_file_location('_real_frozen_extension_loader_hash',
        PATH.with_name('benchmark_decoder_source_fidelity.py'))
    helper=importlib.util.module_from_spec(helper_spec);helper_spec.loader.exec_module(helper)
    with pytest.raises(ValueError,match='frozen extension changed'):
        subject.load_observer_extensions({'helpers':helper,'owners':{}},tmp_path,{relative:'0'*64})
