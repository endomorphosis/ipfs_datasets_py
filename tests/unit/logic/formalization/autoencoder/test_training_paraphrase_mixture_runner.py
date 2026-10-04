"""Matched recipe, exact source inventories and deadline adapters; no models."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

P = Path(__file__).resolve().parents[5]
PATH = P/'scripts/ops/autoencoder/benchmark_training_paraphrase_mixture.py'
SPEC = importlib.util.spec_from_file_location('_mixture_runner_test',PATH)
subject = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(subject)


@pytest.mark.parametrize('key,value', [('learning_rate',.001),('temperature',1),('context_tokens',1024),
    ('full_vocabulary_size',16),('optimizer_steps_per_fit',340),('candidate_augmented_presentations',611),
    ('boundary_atol',1e-4),('preprocessing_refitted',True),('auxiliary768','new'),('selection_unchanged',False)])
def test_fixed_recipe_refuses_budget_context_and_gate_changes(key,value):
    plan = deepcopy(subject.FIXED); subject.validate_plan(plan); plan[key] = value
    with pytest.raises(ValueError,match='recipe differs'): subject.validate_plan(plan)


def test_parent_hashes_and_no_authority():
    assert set(subject.PARENT_HASHES) == {'384','768'}
    assert subject.FIXED['row_presentations'] == 1220
    assert subject.FIXED['valid_target_token_presentations'] == 112920
    assert all(value is False for value in subject.FALSE.values())


def test_bound_rejects_missing_mutated_and_wrong_expected(tmp_path):
    path = tmp_path/'input.json'; path.write_text('{"a":1}')
    manifest = {'inputs':{str(path):subject.sha(path)}}
    assert subject.bound(manifest,path) == {'a':1}
    with pytest.raises(ValueError): subject.bound(manifest,path,'wrong')
    path.write_text('{"a":2}')
    with pytest.raises(ValueError): subject.bound(manifest,path)
    with pytest.raises(ValueError): subject.bound({'inputs':{}},path)


def test_cached_evaluation_vectors_record_missing_coverage_and_only_matching_text(tmp_path):
    path = tmp_path/'prior.json'
    rows = [dict(id='one',source_text='first\n\nsecond',input=[1.]*384),
            dict(id='clause',source_text='second',input=[2.]*384),
            dict(id='train',source_text='other',input=[3.]*384)]
    path.write_text(json.dumps({'rows':rows}))
    manifest = {'inputs':{str(path):subject.sha(path)}}
    preparation = {'prior_vector_rows':{'384':[dict(path=str(path),keys=['rows'])]*2}}
    prior = {name:[dict(id=name,source_text='absent')] for name in subject.EVALUATION_DATASETS}
    prior['paragraph_validation'] = [dict(id='one',source_text='first\n\nsecond')]
    result = subject.evaluation_vectors(manifest,preparation,384,prior)
    assert result['paragraph_validation'] == rows[:2]
    assert set(result) == set(subject.EVALUATION_DATASETS)
    assert all(value == [] for name,value in result.items() if name != 'paragraph_validation')


def test_bounded_evaluate_preserves_plan_and_clamps_remaining_time(monkeypatch):
    monkeypatch.setattr(subject.time,'monotonic',lambda:10.)
    seen = []
    lane = dict(plan={'max_seconds_per_postfit':30,'other':1},
        clause_runner=SimpleNamespace(evaluate=lambda local,*args:seen.append(local) or 'result'))
    assert subject.bounded_evaluate(lane,object(),'validation','conditioned',15.) == 'result'
    assert seen[0]['plan'] == {'max_seconds_per_postfit':5.,'other':1}
    assert lane['plan']['max_seconds_per_postfit'] == 30
    with pytest.raises(TimeoutError): subject.bounded_evaluate(lane,object(),'validation','conditioned',10.)


def test_original_panels_keep_all_controls_and_refuse_diagnostic_without_time(monkeypatch,tmp_path):
    monkeypatch.setattr(subject.time,'monotonic',lambda:10.)
    labels = ['validation','training','zero-condition','source-shuffle','cross-length-shuffle',
        'context-only-shuffle','context-reverse','context-rotate']
    controls = [(name,'validation','conditioned') for name in labels]
    diagnostics = []; saved = []
    lane = dict(plan={'max_seconds_per_postfit':30},
        continuation_runner=SimpleNamespace(CONTROLS=controls),
        helpers=SimpleNamespace(save=lambda path,value:saved.append(path)),
        owners={'ordered_clause_recurrent_decoder_experiment':SimpleNamespace(bind_residual_off_model=lambda model:'disabled')},
        clause_runner=SimpleNamespace(evaluate=lambda *args:dict(predictions=['same'],execution={})),
        prior_margin=SimpleNamespace(recurrent_residual_diagnostic=lambda *args:diagnostics.append(args) or 'observed'),
        prior=SimpleNamespace(compact_panel=lambda panel,**kwargs:panel))
    panels = subject.original_panels(lane,'model',['same'],tmp_path,60.)
    assert len(panels) == len(saved) == len(diagnostics) == 9
    assert panels['recurrent-residual-off']['execution']['recurrent_residual_disabled'] is True
    diagnostics.clear()
    with pytest.raises(ValueError,match='insufficient deadline'):
        subject.original_panels(lane,'model',['same'],tmp_path,39.)
    assert diagnostics == []


@pytest.mark.parametrize('width',[384,768])
def test_train_call_has_absolute_deadline_and_only_original384_auxiliary(monkeypatch,width):
    monkeypatch.setattr(subject.time,'monotonic',lambda:10.)
    seen = {}
    def train(*args,**kwargs): seen.update(kwargs); return 'fit'
    lane = dict(dimension=width,owners={'long_span_source_value_training':SimpleNamespace(train=train)},
        rows={'train':['train'],'validation':['dev']},references={'train':['trainref'],'validation':['devref']},
        donor={'codec':'codec','input_transform':'original'},lineage='lineage',validate_rule='validator',
        validator_id='id',stages='original-stages',source_contexts='original-contexts',
        modality_banks={'used113':'original113'})
    envelope = {'sentinel':True}
    assert subject.train_candidate(lane,'model',envelope,100.) == 'fit'
    assert seen['training_deadline'] == 100. and seen['config']['max_seconds'] == 90.
    assert seen['source_training_mixture'] is envelope and seen['source_contexts'] == 'original-contexts'
    assert seen['config']['learning_rate'] == .0001 and seen['non_action_learning_rate_multiplier'] == 10.
    if width == 384:
        assert seen['auxiliary_source_modality_bank'] == 'original113'
        assert seen['auxiliary_source_modality_weight'] == .05
    else: assert not any(key.startswith('auxiliary_source') for key in seen)


def test_initialization_refuses_existing_output_before_reading_any_manifest(tmp_path):
    output = tmp_path/'already'; output.mkdir()
    with pytest.raises(ValueError,match='remain absent'):
        subject.load_context(SimpleNamespace(output=output),1.)


def test_report_requires_exact_predeclared_committed_effective_rows():
    calls = []
    lane = {'selected_runner':SimpleNamespace(validate_report=lambda *args:calls.append(args))}
    report = {'committed_updates':[{'source_training_mixture':{'effective_ids':['a']},'count_row_ids':['count']}]}
    subject.validate_report(lane,report,'parent',{'draws':[{'effective_ids':['a']}],'count_row_ids':[['count']]})
    assert len(calls) == 1
    with pytest.raises(ValueError,match='predeclared'):
        subject.validate_report(lane,report,'parent',{'draws':[{'effective_ids':['b']}]})


def test_no_encoder_or_download_entrypoint_in_runner():
    import ast
    tree = ast.parse(PATH.read_text())
    calls = {n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
    assert not calls & {'produce_width','from_pretrained','snapshot_download','hf_hub_download'}
    assert subject.FIXED['encoder_executed'] is False
