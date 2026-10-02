"""Plan and frozen-replay input controls; these tests never load numerical models."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[5]
SCRIPTS = ROOT / "scripts/ops/autoencoder"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


subject = load("count_exposure_benchmark_unit", SCRIPTS / "benchmark_decoder_count_exposure.py")
replay = load("cardinality_replay_unit", SCRIPTS / "decoder_fidelity_replay.py")
helpers = load("cardinality_helpers_unit", SCRIPTS / "benchmark_decoder_source_fidelity.py")


previous = load("count_exposure_previous_budget", SCRIPTS / "benchmark_decoder_cardinality.py")


def fixed_plan():
    return dict(schema="decoder-count-exposure-plan/v1", representation_dimension=384,
        arms=[dict(name="current_stage", count_exposure="current_stage", guide_boundary=False, cardinality_weight=.25),
              dict(name="balanced_all", count_exposure="balanced_all", guide_boundary=False, cardinality_weight=.25)],
        seed_order=[1729, 2718], conditioning="every_step", loss="semantic_fields", epochs_per_source_stage=20,
        expected_optimizer_steps_per_arm=340, expected_training_token_presentations_per_arm=225840,
        expected_count_presentations_per_arm=2440,
        batch_size=8, learning_rate=.001, max_seconds_per_arm=60, validation_interval=4,
        fixed_encoder_context_tokens=512, fixed_decoder_output_limit=512, projection_frozen=True,
        teacher_distillation_used=False, selection_unchanged=True, no_downloads=True,
        generation_reference_count_access=False, native_qualification=False)


def test_plan_matches_four_fixed_training_arms_and_no_guidance():
    plan=fixed_plan();before=deepcopy(plan)
    subject.validate_plan(plan)
    assert plan==before
    assert len(plan['arms'])*len(plan['seed_order'])==4
    assert {arm['count_exposure'] for arm in plan['arms']}=={'current_stage','balanced_all'}
    assert all(arm['guide_boundary'] is False and arm['cardinality_weight']==.25 for arm in plan['arms'])
    subject.validate_plan({**plan,'description':'training-only all-length auxiliary exposure'})


@pytest.mark.parametrize('key,value', [
    ('representation_dimension',768),('seed_order',[1729]),('conditioning','first_step'),
    ('loss','reference_ce'),('epochs_per_source_stage',21),('expected_optimizer_steps_per_arm',339),
    ('expected_training_token_presentations_per_arm',225839),('expected_count_presentations_per_arm',2441),
    ('batch_size',16),('learning_rate',.01),('max_seconds_per_arm',120),('validation_interval',1),
    ('fixed_encoder_context_tokens',1024),('fixed_decoder_output_limit',1024),('projection_frozen',False),
    ('projection_frozen',1),('teacher_distillation_used',True),('selection_unchanged',False),
    ('no_downloads',False),('generation_reference_count_access',True),('native_qualification',True),
    ('schema','different-plan')])
def test_scope_change_fails_before_model_loading(key,value):
    plan=fixed_plan();plan[key]=value
    with pytest.raises(ValueError,match='unsupported count exposure experiment plan'):subject.validate_plan(plan)


@pytest.mark.parametrize('mutation',[
    lambda p:p['arms'].pop(),lambda p:p['arms'].reverse(),
    lambda p:p['arms'][0].update(cardinality_weight=0.),
    lambda p:p['arms'][1].update(guide_boundary=True),
    lambda p:p['arms'][1].update(count_exposure='current_stage'),
    lambda p:p['arms'][1].update(reference_count_at_generation=True),
    lambda p:p.pop('no_downloads')])
def test_recipe_mutations_reject(mutation):
    plan=fixed_plan();mutation(plan)
    with pytest.raises(ValueError):subject.validate_plan(plan)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def replay_inputs(tmp_path, monkeypatch):
    # Every preparation object is deliberately synthetic and stops before the
    # package import seam. No corpus, vectors, donor tensors or encoders load.
    extension_root = tmp_path / "extensions"
    dependency_root = tmp_path / "dependency"
    dependency_root.mkdir()
    relative = "scripts/ops/autoencoder/benchmark_decoder_source_fidelity.py"
    destination = extension_root / relative
    destination.parent.mkdir(parents=True)
    destination.write_bytes((SCRIPTS / "benchmark_decoder_source_fidelity.py").read_bytes())
    plan_path = tmp_path / "plan.json"
    plan_sha = write_json(plan_path, fixed_plan())
    manifest = dict(extensions={relative: helpers.sha(destination)}, inputs={}, plan_sha256=plan_sha)
    for key in ("donor", "paragraphs", "embeddings", "curriculum", "curriculum_inputs"):
        path = tmp_path / (key+".json")
        expected = write_json(path, dict(synthetic_identity=key))
        manifest[key] = str(path)
        manifest["inputs"][str(path)] = expected
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)
    arguments = SimpleNamespace(dependency_root=dependency_root, extension_root=extension_root,
        output=tmp_path/"new-results", manifest=manifest_path, plan=plan_path)
    calls = []
    def no_numerical_import(name):
        calls.append(name)
        raise RuntimeError("numerical import sentinel")
    monkeypatch.setattr(replay.importlib, "import_module", no_numerical_import)
    monkeypatch.delitem(sys.modules, "_decoder_fidelity_replay_helpers", raising=False)
    old_path, old_bytecode = list(sys.path), sys.dont_write_bytecode
    yield arguments, manifest, calls
    sys.modules.pop("_decoder_fidelity_replay_helpers", None)
    sys.path[:] = old_path
    sys.dont_write_bytecode = old_bytecode


def test_valid_frozen_preflight_reaches_explicit_import_seam_without_loading_models(replay_inputs):
    arguments, _, calls = replay_inputs
    with pytest.raises(RuntimeError, match="numerical import sentinel"):
        replay.load_context(arguments, validate_plan=subject.validate_plan)
    assert calls == ["ipfs_datasets_py.logic.formalization.autoencoder"]
    assert not arguments.output.exists()


@pytest.mark.parametrize("failure,reason", [
    ("output_exists", "fresh immutable"), ("plan_bytes", "plan changed"),
    ("unsupported_plan", "unsupported count exposure"), ("donor_bytes", "prepared input changed"),
    ("missing_pin", "not pinned"), ("helper_bytes", "replay helper differs"),
    ("wrong_helper_pin", "replay helper differs"), ("relative_input", "not pinned"),
])
def test_replay_guards_reject_mutated_inputs_before_package_import(replay_inputs, failure, reason):
    arguments, manifest, calls = replay_inputs
    if failure == "output_exists": arguments.output.mkdir()
    elif failure == "plan_bytes": arguments.plan.write_text("{}")
    elif failure == "unsupported_plan":
        plan = fixed_plan(); plan["generation_reference_count_access"] = True
        manifest["plan_sha256"] = write_json(arguments.plan, plan)
    elif failure == "donor_bytes": Path(manifest["donor"]).write_text("changed")
    elif failure == "missing_pin": manifest["inputs"].pop(manifest["donor"])
    elif failure == "helper_bytes":
        (arguments.extension_root / "scripts/ops/autoencoder/benchmark_decoder_source_fidelity.py").write_text("raise RuntimeError('must not execute')")
    elif failure == "wrong_helper_pin":
        manifest["extensions"]["scripts/ops/autoencoder/benchmark_decoder_source_fidelity.py"] = "0"*64
    elif failure == "relative_input": manifest["donor"] = "relative-donor.json"
    write_json(arguments.manifest, manifest)
    with pytest.raises(ValueError, match=reason):
        replay.load_context(arguments, validate_plan=subject.validate_plan)
    assert calls == []


def small_count_budget():
    rows=[dict(id=str(k),target_ids=[1,3,2]) for k in [1,2,4,8]]
    references=[dict(id=str(k),clause_count=k) for k in [1,2,4,8]]
    stages=[dict(name='short',training_ids=['1'],epochs=20),
        dict(name='all',training_ids=['1','2','4','8'],epochs=20)]
    plan={**fixed_plan(),'expected_optimizer_steps_per_arm':40,
        'expected_training_token_presentations_per_arm':200,'expected_count_presentations_per_arm':100}
    return stages,rows,references,plan


def test_count_budget_uses_training_references_and_matches_partial_batches():
    stages,rows,references,plan=small_count_budget();before=deepcopy((stages,rows,references,plan))
    result=subject.derive_count_budget(stages,rows,references,plan,previous)
    assert result['optimizer_steps']==40 and result['count_presentations']==100
    assert result['current_stage_count_presentations_by_class']=={1:40,2:20,4:20,8:20}
    assert result['balanced_all_count_presentations_by_class']=={1:25,2:25,4:25,8:25}
    assert result['balanced_all_count_inverse_batch_mass_by_class']=={1:10.,2:10.,4:10.,8:10.}
    assert 'shared conditioner' in result['balanced_gradient_scope']
    assert (stages,rows,references,plan)==before


@pytest.mark.parametrize('mutation,reason',[
    (lambda s,r,f,p:p.update(expected_count_presentations_per_arm=99),'count presentation budget'),
    (lambda s,r,f,p:f.pop(),'complete training count'),
    (lambda s,r,f,p:f[-1].update(id='foreign'),'unique bound'),
    (lambda s,r,f,p:f[-1].update(id='1'),'unique bound'),
    (lambda s,r,f,p:f[-1].update(clause_count=True),'bounded exact'),
    (lambda s,r,f,p:f[-1].update(clause_count=0),'bounded exact'),
    (lambda s,r,f,p:f[-1].update(clause_count=33),'bounded exact'),
    (lambda s,r,f,p:f[-1].update(clause_count=3),'original four count classes'),
    (lambda s,r,f,p:p.update(expected_optimizer_steps_per_arm=41),'update budget'),
    (lambda s,r,f,p:p.update(expected_training_token_presentations_per_arm=201),'token presentation'),
    (lambda s,r,f,p:s[-1].update(epochs=21),'epoch budget')])
def test_count_budget_rejects_unmatched_or_unbound_rows(mutation,reason):
    stages,rows,refs,plan=small_count_budget();mutation(stages,rows,refs,plan)
    with pytest.raises(ValueError,match=reason):subject.derive_count_budget(stages,rows,refs,plan,previous)


def full_synthetic_budget():
    rows=[dict(id=str(index),target_ids=[1,3,2]) for index in range(48)]
    refs=[dict(id=str(index),clause_count=[1,2,4,8][index//12]) for index in range(48)]
    stages=[dict(name=str(size),training_ids=[str(index) for index in range(size)],epochs=20)
        for size in [12,26,36,48]]
    plan={**fixed_plan(),'expected_training_token_presentations_per_arm':4880}
    return subject.derive_count_budget(stages,rows,refs,plan,previous)


def test_partial_count_batches_retain_cursor_and_balanced_mean_loss_mass():
    result=full_synthetic_budget()
    assert result['optimizer_steps']==340 and result['count_presentations']==2440
    assert result['current_stage_count_presentations_by_class']=={1:960,2:720,4:520,8:240}
    assert result['balanced_all_count_presentations_by_class']=={1:610,2:610,4:610,8:610}
    assert result['balanced_all_count_inverse_batch_mass_by_class']=={1:85.,2:85.,4:85.,8:85.}


@pytest.mark.parametrize('failure',[None,'rows','mass','missing_mass','nan_mass','bool_mass'])
def test_completed_exposure_checks_counts_and_actual_mean_loss_contribution(failure):
    budget=full_synthetic_budget()
    report=dict(count_training_presentations_by_class={str(k):610 for k in [1,2,4,8]},
        count_mean_loss_exposure_by_class={str(k):85. for k in [1,2,4,8]})
    if failure=='rows':report['count_training_presentations_by_class']['1']=609
    elif failure=='mass':report['count_mean_loss_exposure_by_class']['1']=86.
    elif failure=='missing_mass':report.pop('count_mean_loss_exposure_by_class')
    elif failure=='nan_mass':report['count_mean_loss_exposure_by_class']['1']=float('nan')
    elif failure=='bool_mass':report['count_mean_loss_exposure_by_class']['1']=True
    if failure is None:subject.validate_completed_exposure(report,budget,dict(count_exposure='balanced_all'))
    else:
        with pytest.raises(ValueError,match='exposure differs'):
            subject.validate_completed_exposure(report,budget,dict(count_exposure='balanced_all'))


def test_current_stage_mass_is_observed_not_inferred_without_decoder_shuffle():
    budget=full_synthetic_budget()
    report=dict(count_training_presentations_by_class={str(k):v for k,v in
        budget['current_stage_count_presentations_by_class'].items()})
    subject.validate_completed_exposure(report,budget,dict(count_exposure='current_stage'))


def test_frozen_predecessor_helper_is_pinned_before_execution(tmp_path):
    relative='scripts/ops/autoencoder/benchmark_decoder_cardinality.py'
    path=tmp_path/relative;path.parent.mkdir(parents=True)
    path.write_bytes((SCRIPTS/'benchmark_decoder_cardinality.py').read_bytes())
    pins={relative:hashlib.sha256(path.read_bytes()).hexdigest()}
    loaded=subject.load_control_helper(tmp_path,pins)
    assert loaded.control_scope('source_shuffle')['independent_count_generalization_test'] is False
    path.write_text("raise RuntimeError('should not execute')")
    with pytest.raises(ValueError,match='budget helper differs'):subject.load_control_helper(tmp_path,pins)


def probability_row(values,identity='one'):
    return dict(predictions=[dict(id=identity,probabilities=values)])


def test_uniform_probabilities_have_zero_hypothetical_boundary_correction():
    result=subject.hypothetical_boundary_diagnostics(probability_row([1/32]*32))
    assert result['applied_to_generation'] is False and result['observed_generation_boundaries'] is False
    assert result['reference_clause_count_used'] is False and result['guidance_enabled'] is False
    for value in result['rows'][0]['boundaries'].values():
        assert value['finite'] is True
        assert value['hypothetical_logit_correction']==pytest.approx(0.,abs=1e-14)


def test_support_only_prior_can_favor_stopping_without_source_discrimination():
    import math
    probabilities=[0.]*32
    for count in [1,2,4,8]:probabilities[count-1]=.25
    original=probability_row(probabilities);before=deepcopy(original)
    result=subject.hypothetical_boundary_diagnostics(original)
    assert result['rows'][0]['boundaries']['1']['hypothetical_logit_correction']==pytest.approx(math.log(31/3))
    assert result['rows'][0]['boundaries']['8']['hypothetical_logit_correction'] is None
    assert result['rows'][0]['boundaries']['8']['finite'] is False
    assert original==before
    json.dumps(result,allow_nan=False)


@pytest.mark.parametrize('case',['missing','wrong_width','nan','negative','greater_one','sum','duplicate_id','bad_id','boolean'])
def test_boundary_diagnostics_refuse_invalid_probability_evidence(case):
    row=probability_row([1/32]*32)
    if case=='missing':row['predictions'][0].pop('probabilities')
    elif case=='wrong_width':row['predictions'][0]['probabilities'].pop()
    elif case=='nan':row['predictions'][0]['probabilities'][0]=float('nan')
    elif case=='negative':row['predictions'][0]['probabilities'][0]=-.1
    elif case=='greater_one':row['predictions'][0]['probabilities'][0]=2.
    elif case=='sum':row['predictions'][0]['probabilities'][0]=.5
    elif case=='duplicate_id':row['predictions'].append(deepcopy(row['predictions'][0]))
    elif case=='bad_id':row['predictions'][0]['id']=None
    elif case=='boolean':row['predictions'][0]['probabilities'][0]=True
    with pytest.raises(ValueError):subject.hypothetical_boundary_diagnostics(row)
