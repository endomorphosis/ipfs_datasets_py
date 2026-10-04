"""Fresh384D evaluation lifecycle; all inputs are synthetic test fixtures."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[5] / 'scripts/ops/autoencoder/evaluate_content_matched_holdout.py'
SPEC = importlib.util.spec_from_file_location('_content_matched_fresh_tests', PATH)
subject = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(subject)
OLD_PATH = PATH.parent / 'evaluate_source_margin_holdout.py'
OLD_SPEC = importlib.util.spec_from_file_location('_content_matched_fresh_old_kernel', OLD_PATH)
old = importlib.util.module_from_spec(OLD_SPEC); OLD_SPEC.loader.exec_module(old)


def digest(value):
    import hashlib
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
        allow_nan=False).encode()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:json.dump(value, stream, sort_keys=True, allow_nan=False)
    return dict(path=str(path), sha256=subject.sha(path), bytes=path.stat().st_size)


def bound(manifest, path, value):
    ref = save(path, value); manifest['inputs'][str(path.resolve())] = ref['sha256']; return ref


@pytest.mark.parametrize('key,value', [('panel_count',4), ('fit_count',6), ('dimensions',[8,384]),
    ('samples_per_panel',1), ('roles',['last-attempt']), ('primary_endpoint','selected'), ('temperature',.1),
    ('batch_size',16), ('fixed_encoder_context_tokens',1024), ('fixed_decoder_output_limit',1024),
    ('generation_reference_access',True), ('all_predictions_persisted_before_reference_load',False),
    ('optimizer_steps',1), ('qualified',True), ('selection_performed',True), ('max_seconds_entire_run',3600)])
def test_fixed_plan_cannot_relax_exposure_or_success(key, value):
    plan = deepcopy(subject.FIXED); subject.validate_plan(plan); plan[key] = value
    with pytest.raises(ValueError, match='fixed content-matched fresh'):
        subject.validate_plan(plan)


def test_job_inventory_has_exactly_four_fits_and_eight_endpoints():
    assert len(subject.jobs()) == len(set(subject.jobs())) == 4
    assert all(d == 384 for d, _, _ in subject.jobs())
    assert subject.ROLES == ['last-attempt', 'selected']
    assert all(v is False for v in subject.FALSE.values())


def run_fixture(tmp_path):
    manifest = dict(inputs={}); records = []
    recipes = [dict(name=arm, prescribed_recipe=True) for arm in subject.ARMS]
    for dimension, seed, arm in subject.jobs():
        name = f'{dimension}-{arm}-{seed}'; folder = tmp_path / name
        training = bound(manifest, folder / 'training.json', dict(stopped_reason='epochs_completed',
            optimizer_steps=340, selected_weights_sha256='selected-tensor', last_complete_attempt_weights_sha256='final-tensor'))
        states = {role:dict(bound(manifest, folder / (role + '.json'), dict(role=role)),
            tensor_sha256='selected-tensor' if role == 'selected' else 'final-tensor') for role in subject.ROLES}
        ref = bound(manifest, folder / 'summary.json', dict(arm=name, dimension=dimension, seed=seed,
            recipe=recipes[subject.ARMS.index(arm)], budget_completed=True, training_ref=training, states=states))
        records.append(dict(arm=name, summary_path=ref['path'], summary_sha256=ref['sha256']))
    summary = dict(schema='content-matched-modality-training-comparison/v1', complete=True, training_executed=True,
        all_two_published_384_full180_controls_replayed=True, per_source_auxiliary_exposure_identical=True, runs=records)
    return manifest, summary, recipes


def test_four_authenticated_completed_runs_are_required_before_model_load(tmp_path):
    manifest, summary, recipes = run_fixture(tmp_path)
    assert list(subject.validate_saved_runs(manifest, summary, recipes)) == [r['arm'] for r in summary['runs']]
    summary['runs'].pop()
    with pytest.raises(ValueError, match='exact four'):
        subject.validate_saved_runs(manifest, summary, recipes)


@pytest.mark.parametrize('mutation', ['incomplete', 'wrong_recipe', 'unbound_state', 'changed_state', 'incomplete_steps', 'wrong_tensor'])
def test_changed_saved_comparison_is_rejected(tmp_path, mutation):
    manifest, summary, recipes = run_fixture(tmp_path)
    item = summary['runs'][0]; path = Path(item['summary_path']); run = json.loads(path.read_bytes())
    if mutation == 'incomplete':summary['complete'] = False
    elif mutation == 'unbound_state':manifest['inputs'].pop(str(Path(run['states']['selected']['path']).resolve()))
    elif mutation == 'changed_state':Path(run['states']['selected']['path']).write_text('{}')
    elif mutation == 'wrong_recipe':run['recipe']['extra'] = True
    elif mutation == 'wrong_tensor':run['states']['selected']['tensor_sha256'] = 'changed'
    else:
        report_path = Path(run['training_ref']['path']); report = json.loads(report_path.read_bytes())
        report['optimizer_steps'] = 339; report_path.write_text(json.dumps(report))
        run['training_ref'].update(sha256=subject.sha(report_path), bytes=report_path.stat().st_size)
        manifest['inputs'][str(report_path)] = subject.sha(report_path)
    if mutation in ('wrong_recipe', 'wrong_tensor', 'incomplete_steps'):
        path.write_text(json.dumps(run)); item['summary_sha256'] = manifest['inputs'][str(path)] = subject.sha(path)
    with pytest.raises(ValueError):subject.validate_saved_runs(manifest, summary, recipes)


def preparation_fixture(tmp_path):
    manifest = dict(inputs={}, comparison_seal='a'*64)
    rows = [dict(id='source', source_text='synthetic')]
    plan = dict(source_rows=rows, sealed_comparison_sha256='a'*64)
    assembled = dict(schema='fresh-scalar-source-inputs-single/v1', dimension=384, complete=True, rows=rows)
    preparation = dict(schema='content-matched-fresh-preparation/v1', complete=True, dimension=384,
        comparison_seal='a'*64, training_executed=False, downloads_performed=False, qualified=False,
        admitted=False, lake_executed=False, formalized=False, roundtrip_ok=False, checkpoint_promoted=False)
    for key, value in [('source_rows',rows), ('source_plan',plan), ('production',dict(source_only=True)),
            ('dimension_inputs',assembled), ('references',dict(secret='unparsed')), ('holdout_receipt',dict(secret='unparsed'))]:
        preparation[key] = bound(manifest, tmp_path / (key + '.json'), value)
    ctx = dict(exposed_evaluator=old, fresh_owners={'fresh_scalar_source_inputs_single':
        SimpleNamespace(assemble=lambda *a, **kw:deepcopy(assembled))})
    return ctx, manifest, preparation, assembled


def test_source_validation_never_parses_reference_or_builder_receipt(tmp_path, monkeypatch):
    ctx, manifest, preparation, assembled = preparation_fixture(tmp_path)
    original = subject.bound_json; reads = []
    forbidden = {preparation[k]['path'] for k in ('references','holdout_receipt')}
    def observed(m, path, expected=None):
        assert str(path) not in forbidden
        reads.append(str(path)); return original(m, path, expected)
    monkeypatch.setattr(subject, 'bound_json', observed)
    assert subject.validate_preparation(ctx, manifest, preparation) == assembled
    assert len(reads) == 4


@pytest.mark.parametrize('mutation', ['wrong_dimension', 'wrong_schema', 'tampered_vectors', 'reference_inside_sources', 'unbound_plan', 'shared_reference_path'])
def test_preparation_requires_exact_single_width_native_reconstruction(tmp_path, mutation):
    ctx, manifest, preparation, assembled = preparation_fixture(tmp_path)
    if mutation == 'unbound_plan':manifest['inputs'].pop(preparation['source_plan']['path'])
    elif mutation == 'shared_reference_path':preparation['references'] = preparation['source_rows']
    else:
        path = Path(preparation['dimension_inputs']['path']); value = json.loads(path.read_bytes())
        if mutation == 'wrong_dimension':value['dimension'] = 768
        elif mutation == 'wrong_schema':value['schema'] = 'fresh-scalar-source-inputs/v1'
        elif mutation == 'tampered_vectors':value['extra'] = True
        else:value['rows'][0]['target'] = {'rules':[]}
        path.write_text(json.dumps(value)); preparation['dimension_inputs'].update(sha256=subject.sha(path), bytes=path.stat().st_size)
        manifest['inputs'][str(path)] = subject.sha(path)
    with pytest.raises(ValueError):subject.validate_preparation(ctx, manifest, preparation)


def prediction_fixture(tmp_path):
    from ipfs_datasets_py.logic.formalization.autoencoder import authored_modality_holdout_v2 as builder
    from .test_authored_modality_holdout_v2 import inputs
    args = inputs(); args['seed'] = 20261005; produced = builder.build_holdout(**args)
    rows = [dict(r, input=[1.]+[0.]*383) for r in produced['source_rows']]
    contexts = {r['id']:dict(source_only=True) for r in rows}
    manifest = dict(inputs={}, comparison_seal=args['sealed_comparison_sha256'])
    preparation = {k:bound(manifest, tmp_path / (k+'.json'), produced['receipt' if k == 'holdout_receipt' else k])
        for k in ('references', 'holdout_receipt')}
    runs = {}; records = []
    for d, seed, arm in subject.jobs():
        name = f'{d}-{arm}-{seed}'; runs[name] = dict(states={})
        for role in subject.ROLES:
            state = dict(tensor_sha256=name+'-'+role); runs[name]['states'][role] = state
            ref = save(tmp_path / name / (role+'.json'), dict(complete=True, model_tensor_sha256=state['tensor_sha256'],
                generation_reference_access=False, source_rows_sha256=digest(rows), source_contexts_sha256=digest(contexts),
                predictions=[dict(id=r['id']) for r in rows]))
            records.append(dict(arm=name, role=role, predictions_ref=ref, state_ref=deepcopy(state)))
    lane = dict(fresh_contexts=contexts, donor=dict(codec=args['codec']), rows=dict(train=args['training_rows']),
        references=dict(train=[dict(id=r['id'],target=r['target']) for r in args['training_rows']]),
        validate_rule=args['validate_rule'])
    ctx = dict(core=SimpleNamespace(digest=digest), saved_runs=runs, fresh_inputs=dict(rows=rows),
        evaluation_manifest=manifest, preparation=preparation, prior_inventory=args['prior_sources_by_dataset'],
        preparation_plan=dict(family_roles=args['family_roles'], seed=args['seed']),
        fresh_owners={'authored_modality_holdout_v2':builder})
    return ctx, lane, records, produced


def test_all_eight_predictions_unlock_exact_pure_reference_validation(tmp_path):
    ctx, lane, records, produced = prediction_fixture(tmp_path)
    refs, receipt = subject.load_fresh_references(ctx, lane, records)
    assert refs == produced['references'] and receipt == produced['receipt']


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'bytes', 'complete', 'model', 'source', 'context', 'labels', 'state_ref', 'identities'])
def test_all_prediction_checks_precede_any_label_read(tmp_path, monkeypatch, mutation):
    ctx, lane, records, _ = prediction_fixture(tmp_path)
    if mutation == 'missing':records.pop()
    elif mutation == 'duplicate':records[0] = deepcopy(records[1])
    elif mutation == 'state_ref':records[0]['state_ref']['tensor_sha256'] = 'foreign'
    else:
        ref = records[0]['predictions_ref']; path = Path(ref['path']); value = json.loads(path.read_bytes())
        if mutation == 'bytes':value['extra'] = True
        elif mutation == 'complete':value['complete'] = False
        elif mutation == 'model':value['model_tensor_sha256'] = 'foreign'
        elif mutation == 'source':value['source_rows_sha256'] = 'foreign'
        elif mutation == 'context':value['source_contexts_sha256'] = 'foreign'
        elif mutation == 'labels':value['generation_reference_access'] = True
        else:value['predictions'].pop()
        path.write_text(json.dumps(value))
        if mutation != 'bytes':ref['sha256'] = subject.sha(path)
    monkeypatch.setattr(subject, 'bound_ref', lambda *a:pytest.fail('fresh references opened before all predictions validated'))
    with pytest.raises(ValueError):subject.load_fresh_references(ctx, lane, records)


def test_rehashed_authored_reference_repair_is_rejected(tmp_path):
    ctx, lane, records, _ = prediction_fixture(tmp_path)
    reference = ctx['preparation']['references']; path = Path(reference['path']); rows = json.loads(path.read_bytes())
    rows[0]['target']['rules'][0]['modality'] = 'P' if rows[0]['target']['rules'][0]['modality'] != 'P' else 'O'
    path.write_text(json.dumps(rows)); reference.update(sha256=subject.sha(path), bytes=path.stat().st_size)
    ctx['evaluation_manifest']['inputs'][str(path)] = subject.sha(path)
    with pytest.raises(ValueError, match='pure construction'):
        subject.load_fresh_references(ctx, lane, records)


def test_restore_delegates_only_after_registered_endpoint_hash(tmp_path):
    ref = save(tmp_path/'state.json', dict(state='synthetic')); run = dict(arm='registered', states={'selected':ref})
    calls = []; marker = object()
    ctx = dict(saved_runs={'registered':run}, evaluation_manifest=dict(inputs={ref['path']:ref['sha256']}),
        comparison_runner=SimpleNamespace(restore_endpoint=lambda *args:(calls.append(args),marker)[1]))
    assert subject.restore_state(ctx, {}, run, 'selected') is marker and len(calls) == 1
    Path(ref['path']).write_text('{}')
    with pytest.raises(ValueError, match='endpoint bytes'):subject.restore_state(ctx, {}, run, 'selected')
    assert len(calls) == 1


@pytest.mark.parametrize('collision', [None, 'identity', 'normalized_clause', 'raw_vector', 'float32_vector'])
def test_fresh_sources_exclude_training_and_exposed_literals_and_vectors(monkeypatch, collision):
    def row(identity, text, number):
        return dict(id=identity, source_text=text, input=[number]+[0.]*383)
    old_train = row('old-train', 'Old training clause.', 1.)
    old_exposed = row('old-exposed', 'Old exposed clause.', 2.)
    fresh_row = row('fresh', 'New source clause.', 3.)
    if collision == 'identity':fresh_row['id'] = old_train['id']
    elif collision == 'normalized_clause':fresh_row['source_text'] = '  OLD \t EXPOSED   CLAUSE.  '
    elif collision == 'raw_vector':fresh_row['input'] = list(old_exposed['input'])
    elif collision == 'float32_vector':fresh_row['input'] = [2.+1e-10]+[0.]*383
    originals = {'raw_train':{'rows':[]}, 'raw_val':{'rows':[]},
        'exposed':dict(dimensions={'384':dict(rows=[old_exposed],clause_cache=[])})}
    monkeypatch.setattr(subject, 'bound_json', lambda manifest,path:originals[path])
    ctx = dict(core=SimpleNamespace(_vector=lambda v,d:None),
        prior_inventory={'prior':[dict(id='prior',source_text='Another old source.')]},
        manifest=dict(auxiliary_sources=dict(original_training='raw_train',forbidden={'validation':'raw_val'}),
            exposed_source_inputs='exposed'),
        parent_runner=SimpleNamespace(source_only_original_rows=lambda raw,split:[]))
    lane = dict(rows=dict(train=[old_train],validation=[]),clause_cache=dict(train=[],validation=[]))
    fresh = dict(rows=[fresh_row],clause_cache=[])
    if collision:
        with pytest.raises(ValueError,match='overlaps prior data'):
            subject.validate_source_exclusion(ctx,lane,fresh)
    else:
        assert subject.validate_source_exclusion(ctx,lane,fresh)['no_prior_overlap'] is True


def test_generation_wrapper_keeps_existing_source_only_kernel_contract():
    from .test_source_margin_holdout_evaluation import generation_fixture
    _, ctx, lane, model, calls = generation_fixture()
    ctx['exposed_evaluator'] = old
    result = subject.generate_panel(ctx, lane, model, subject.time.monotonic()+30)
    assert result['schema'] == 'content-matched-fresh-predictions/v1'
    assert len(calls) == 2 and [len(call[0]) for call in calls] == [8,1]
    assert result['generation_reference_access'] is False
    assert all(result[k] is False for k in subject.FALSE)


def main_fixture(tmp_path, monkeypatch, fail_after=None):
    plan = tmp_path/'plan.json'; save(plan, {}); output = tmp_path/'out'; events = []
    monkeypatch.setattr(sys, 'argv', ['run', '--dependency-root',str(tmp_path), '--extension-root',str(tmp_path),
        '--manifest',str(tmp_path/'manifest.json'), '--plan',str(plan), '--output',str(output), '--phase','evaluation'])
    runs = {f'{d}-{arm}-{seed}':dict(states={role:dict(tensor_sha256=role) for role in subject.ROLES})
        for d,seed,arm in subject.jobs()}
    ctx = dict(helpers=SimpleNamespace(save=save), core=SimpleNamespace(digest=digest),
        evaluation_manifest=dict(inputs={}, extensions={}, plan_sha256=subject.sha(plan), comparison_seal='sealed'),
        evaluation_plan={}, tree={}, saved_runs=runs,
        comparison_runner=SimpleNamespace(source_inventory=lambda *a:{'producer':'unchanged'}), comparison_args=None)
    monkeypatch.setattr(subject, 'load_context', lambda args:ctx)
    monkeypatch.setattr(subject, 'prepare_lane', lambda ctx:dict(fresh_source_exclusion={'no_prior_overlap':True}))
    monkeypatch.setattr(subject, 'restore_state', lambda *a:object())
    def generate(*a):
        if fail_after is not None and len(events) == fail_after:raise TimeoutError('synthetic timeout')
        events.append('generation'); return dict(elapsed_seconds=.01,complete=True)
    def labels(c, lane, records):
        assert len(records) == 8 and events == ['generation']*8
        assert len(list(output.glob('*/*-predictions.json'))) == 8
        assert (output/'predictions-complete.json').exists() and not list(output.glob('*/*-score.json'))
        events.append('labels');return [],dict(authored_modal_assumption='synthetic',target_provenance='authored')
    def score(*a):
        assert 'labels' in events
        events.append('score')
        return dict(elapsed_seconds=.02, fidelity=dict(metrics=dict(ordered_exact=0,syntax_valid=0)),
            teacher_forced=dict(token_cross_entropy=3.))
    monkeypatch.setattr(subject,'generate_panel',generate)
    monkeypatch.setattr(subject,'load_fresh_references',labels)
    monkeypatch.setattr(subject,'score_panel',score)
    return output, events


def test_driver_persists_all_eight_panels_before_labels_and_scoring(tmp_path, monkeypatch):
    output, events = main_fixture(tmp_path, monkeypatch); subject.main()
    assert events == ['generation']*8 + ['labels'] + ['score']*8
    result = json.loads((output/'summary.json').read_bytes())
    assert result['complete'] is True and len(result['panels']) == 8
    assert all(result[k] is False for k in subject.FALSE)
    assert result['fresh_authored_holdout'] is True and result['fresh_holdout_exposed_after_this_evaluation'] is True
    assert result['bridge_names'] == [] and result['samples_per_panel'] == 48


def test_partial_generation_never_opens_labels_or_claims_completion(tmp_path, monkeypatch):
    output, events = main_fixture(tmp_path, monkeypatch, fail_after=3)
    with pytest.raises(TimeoutError):subject.main()
    assert events == ['generation']*3
    assert len(list(output.glob('*/*-predictions.json'))) == 3
    assert not (output/'predictions-complete.json').exists() and not (output/'summary.json').exists()
