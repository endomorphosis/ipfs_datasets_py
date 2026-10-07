"""Authenticate and stage existing parallel trials, without refitting or rewriting states.

This inventory contains three actual recipes and nine original containers. Its
six fitted selected/last bindings are three tensor endpoints. The unpublished
matched two-arm campaign is a separate API and is never invoked here.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path

import publication_common as c
import prepare_dual_bank_release as future

LOGS = c.BASE / 'external/ipfs_datasets/workspace/test-logs'
BALANCED = LOGS / 'decoder-balanced-wording-20261007'
DUAL = LOGS / 'decoder-dual-bank-replay-20261007'
COMPARISON = c.BASE / 'artifacts/autoencoder-dual-bank-replay-20261007/postfit-comparison.json'
CENSUS = c.BASE / 'artifacts/autoencoder-dual-bank-replay-20261007/development-error-census.json'
BALANCED_REVIEW = c.BASE / 'artifacts/autoencoder-balanced-wording-20261007/evaluation-review/actual-evaluation-r1-independent-review.json'
EXPECTED_TENSORS = dict(zip(c.RETAINED_ARMS, (
    '9e5772d99191e311b15f316138a27407d4a73346af3ce495129ad5febcf5bd4c',
    'c39a6acde9f5e836919dceb00db7bf7cf1b90465b7b0b7ca2d78f39ee3dc3cbb',
    '6e47fc6d5452bd0becbe4e36e60be7ee0a388d969dad68dc817123307412cea5')))
COHORTS = future.COHORTS


def remember(protected, value):
    value = c.pin(value)
    if value['path'] in protected:
        c.require(protected[value['path']] == value, 'conflicting retained source pin')
        return value
    c.require(c.capture(value['path']) == value, 'actual retained input changed')
    protected[value['path']] = value
    return value


def bound(protected, value, *, maximum=64 * 1024**2):
    return c.document(remember(protected, value), maximum=maximum)


def gather_pins(protected, value):
    if type(value) is dict:
        if {'path', 'bytes', 'sha256'} <= set(value):
            remember(protected, value)
        for child in value.values():
            if type(child) in (dict, list):
                gather_pins(protected, child)
    elif type(value) is list:
        for child in value:
            if type(child) in (dict, list):
                gather_pins(protected, child)


def hash_map(protected, values, *, root=None):
    c.require(type(values) is dict and 0 < len(values) <= 20000, 'bounded closed source hash map required')
    for path, expected in values.items():
        location = Path(path) if root is None else root / path
        if str(location) in protected:
            c.require(protected[str(location)]['sha256'] == expected, 'repeated source-reference hash differs')
        else:
            observed = c.capture_historical_source(location)
            c.require(observed['sha256'] == expected, 'retained producer/source closure bytes differ')
            protected[observed['path']] = observed


def phase_closure(protected, root, phase, attempt):
    exit_pin = c.capture(root / attempt / 'child-exit.json')
    resource_pin = c.capture(root / attempt / 'resources-final.json')
    future.terminal(protected, exit_pin, resource_pin)
    manifest_pin = c.capture(root / (phase + '-manifest.json'))
    manifest = bound(protected, manifest_pin)
    hash_map(protected, manifest['inputs'])
    hash_map(protected, manifest['extensions'], root=root / 'experiment-source')
    plan_pin = c.capture(root / (phase + '-plan.json'))
    c.require(plan_pin['sha256'] == manifest['plan_sha256'], 'actual retained phase plan differs')
    remember(protected, plan_pin)
    return dict(manifest_pin=manifest_pin, plan_pin=plan_pin,
        child_exit_pin=exit_pin, resources_final_pin=resource_pin)


def verify_raw_state(runtime, value, run, role, parent, report):
    c.require(value['schema'] == parent['schema'] == 'private-native-dimension-source-state/v1'
        and type(value['dimension']) is int and value['dimension'] == 384
        and value['role'] == role and value['recipe'] == run['recipe']
        and type(value['recipe']['weight']) is float and value['recipe']['weight'] == .05,
        'actual retained raw serialization/width/role/recipe differs')
    c.require(type(value['selected']) is bool and (role != 'selected' or value['selected'] is True)
        and (role != 'initial' or value['selected'] is False), 'actual raw selected/initial header differs')
    c.require(all(value[name] is False for name in future.FALSE_FLAGS), 'raw checkpoint must remain unqualified')
    runtime._false_flags(value)
    for key in ('architecture', 'codec', 'input_transform', 'initializer_receipt', 'lineage'):
        c.require(c.wire(value[key]) == c.wire(parent[key]), 'original inherited metadata changed: ' + key)
    c.require(value['codec']['schema'] == 'typed-json-lexical/v1'
        and len(value['codec']['target_vocabulary']) == len(set(value['codec']['target_vocabulary'])) == 32,
        'exact original lexical32 codec required')
    shapes, _ = runtime._shapes(384)
    typed = runtime._tensor_digest(value['model_state'], shapes, integer_buffers=True)
    c.require(typed == value['tensor_sha256'] == run['states'][role]['tensor_sha256']
        and runtime._digest(value['model_state']) == value['weights_sha256'], 'actual full typed32 endpoint differs')
    expected = c.PARENT_TENSOR_SHA if role == 'initial' else report[
        'selected_weights_sha256' if role == 'selected' else 'last_complete_attempt_weights_sha256']
    c.require(typed == expected, 'raw tensor differs from actual new report or original parent')
    c.require(runtime._digest(value['codec']) == value['lineage']['teacher_codec_sha256'], 'actual codec lineage differs')
    return typed


def actual_disposition(arm, role, panels, comparison, census, bank_metrics):
    metric = {p['cohort']: p['formula_metrics']['ordered_exact'] for p in panels}
    c.require(set(metric) == set(COHORTS), 'four complete retained evaluation cohorts required')
    if arm == 'control-wording-ce':
        c.require([metric[k] for k in COHORTS] == [48, 48, 48, 33], 'archived control observation differs')
        return dict(disposition='experimental_archived_retained_bank_control', numerical_retention_passed=None,
            retention_findings=[], previously_exact_paragraph_regressions=[],
            retention_scope='Recorded archived control; no newly computed modern gate is attributed to it.')
    if arm == 'balanced-wording-ce':
        c.require([metric[k] for k in COHORTS] == [48, 33, 48, 19]
            and bank_metrics['control']['modality']['correct'] == 170, 'balanced replacement regression evidence differs')
        return dict(disposition='experimental_rejected_retained_formula_and_modality_regression',
            numerical_retention_passed=False,
            retention_findings=['Retained normative TRAIN paragraphs fell from 48/48 control to 33/48.',
                'Retained source-bank modality fell below full180 retention: 170/180.'],
            previously_exact_paragraph_regressions=[],
            retention_scope='Direct actual archived-control comparison; this rejection is not relabeled as a freshly executed modern gate.')
    c.require(arm == 'dual-bank-retention-ce' and [metric[k] for k in COHORTS] == [48, 48, 48, 30],
        'actual dual-bank observation differs')
    gate = comparison['decisions'][role]
    c.require(gate['schema'] == 'dual-authored-wording-numerical-retention-gate/v1'
        and gate['numerical_retention_passed'] is True and gate['allowed_numerical_continuation'] is True
        and gate['findings'] == [] and comparison['baseline_formula_tensor_sha256'] == EXPECTED_TENSORS[c.RETAINED_ARMS[0]]
        and comparison['baseline_source_bank_tensor_sha256'] == c.PARENT_TENSOR_SHA
        and comparison['bank_mix_effect_causally_isolated'] is False and comparison['auxiliary_chronology_changed'] is True,
        'actual mixed-baseline numerical retention decision/scope differs')
    c.require(census['paragraph_transitions']['newly_wrong'] == 3 and len(census['changed_paragraphs']) == 3,
        'actual exposed-development regression census differs')
    return dict(disposition='experimental_authored_retention_passed_exposed_v3_declined',
        numerical_retention_passed=True, retention_findings=[],
        previously_exact_paragraph_regressions=[dict(cohort='exposed_v3_48', id=r['id'], transition=r['transition'])
            for r in census['changed_paragraphs']], retention_scope=comparison['baseline_scope'],
        bank_mix_effect_causally_isolated=False, auxiliary_chronology_changed=True,
        exposed_v3_used_for_selection=False)


def authenticate_retained():
    protected, states, all_panels, phases, summaries = {}, [], [], {}, {}
    comparison_pin, census_pin = c.capture(COMPARISON), c.capture(CENSUS)
    comparison, census = bound(protected, comparison_pin), bound(protected, census_pin)
    c.require(comparison['schema'] == 'dual-bank-replay-postfit-comparison/v1' and comparison['complete'] is True
        and census['schema'] == 'dual-bank-replay-exposed-development-error-census/v1' and census['complete'] is True,
        'actual completed comparison and error census required')
    for report in (comparison, census):
        for path, reference in report['artifacts'].items():
            remember(protected, dict(path=path, **reference))
    review_pin = c.capture(BALANCED_REVIEW)
    review = bound(protected, review_pin)
    c.require(review['passed'] is True and review['findings'] == []
        and review['distinct_tensor_endpoints'] == 2, 'complete independent retained evaluation review required')
    gather_pins(protected, review.get('artifacts', {}))
    runtime, runtime_owner = c.load_native('contextual_legal_ir_runtime')
    remember(protected, runtime_owner['pin'])
    for root, training_attempt, arms, training_schema, evaluation_schema in (
            (BALANCED, 'training-384-r2', c.RETAINED_ARMS[:2], 'balanced-wording-continuation-result/v1',
                'balanced-wording-postfit-evaluation-plan/v1'),
            (DUAL, 'training-384-r1', c.RETAINED_ARMS[2:], 'dual-bank-replay-result/v1',
                'dual-bank-replay-postfit-evaluation-plan/v1')):
        phases[root.name] = {phase: phase_closure(protected, root, phase, attempt) for phase, attempt in
            (('training', training_attempt), ('evaluation', 'evaluation-r1'))}
        training_pin = c.capture(root / training_attempt / 'results/summary.json')
        evaluation_pin = c.capture(root / 'evaluation-r1/results/summary.json')
        training, evaluation = bound(protected, training_pin), bound(protected, evaluation_pin)
        c.require(training['schema'] == training_schema and training['complete'] is True
            and training['phase'] == 'training' and training['dimension'] == 384
            and training['parent_tensor_sha256'] == c.PARENT_TENSOR_SHA
            and len(training['runs']) == len(arms), 'actual completed retained training campaign differs')
        c.require(evaluation['schema'] == evaluation_schema and evaluation['complete'] is True
            and evaluation['phase'] == 'evaluation' and evaluation['physical_panels'] == evaluation['logical_panels'] == len(arms) * 8
            and len(evaluation['panels']) == len(arms) * 8,
            'actual sixteen/eight physical evaluation inventory required')
        expected_panels = {(a, r, co) for a in arms for r in c.FITTED_ROLES for co in COHORTS}
        c.require({(p['arm'], p['role'], p['cohort']) for p in evaluation['panels']} == expected_panels,
            'closed actual retained arm/role/cohort inventory differs')
        summaries[root.name] = dict(training_summary_pin=training_pin, evaluation_summary_pin=evaluation_pin)
        seen = set()
        for run_ref in training['runs']:
            run = bound(protected, run_ref)
            arm = run['arm']
            c.require(arm in arms and arm not in seen and run['budget_completed'] is True
                and run['seed'] == 1729 and type(run['seed']) is int
                and run['recipe'] == {'name': arm, 'weight': .05} and type(run['recipe']['weight']) is float
                and run['fresh_optimizer'] is True and run['fresh_scheduler'] is True
                and run['exact_optimizer_resume'] is False and run['selected_last_tensor_alias'] is True
                and run['initial_tensor_sha256'] == run['parent_state']['tensor_sha256'] == c.PARENT_TENSOR_SHA,
                'authentic completed retained recipe/parent required')
            gather_pins(protected, run)
            parent = bound(protected, run['parent_state'])
            report = bound(protected, run['training_ref'])
            counts = dict(optimizer_steps=170, row_presentations=1220, count_training_row_presentations=1220,
                valid_target_token_presentations=112920, source_value_presentations=12800,
                auxiliary_source_modality_presentations=1020)
            c.require(all(type(report[k]) is int and report[k] == v for k, v in counts.items())
                and report['stopped_reason'] == 'epochs_completed' and len(report['committed_updates']) == 170,
                'actual retained committed training report budget differs')
            for role in c.ROLES:
                original = remember(protected, run['states'][role])
                raw = bound(protected, original)
                tensor = verify_raw_state(runtime, raw, run, role, parent, report)
                row = dict(ir_family_id='legal_ir', dimension=384, dimension_role='input_embedding',
                    task_id='semantic_IR_reconstruction', task_binding_scope='Declared intended semantic lexical IR task; native output schema remains unknown.',
                    arm=arm, role=role, recipe=run['recipe'], original_checkpoint_pin=original,
                    tensor_sha256=tensor, serialization_schema=raw['schema'], codec_sha256=runtime._digest(raw['codec']),
                    selected_header_value=raw['selected'], full_model_state_entries=32,
                    continuation_run_id=str(root / training_attempt / 'results'),
                    continuation_training_ref=c.pin(run['training_ref']) if role != 'initial' else None,
                    new_continuation_training_executed=role != 'initial', original_parent_already_trained=True,
                    raw_headers_preserved=True, raw_headers_lack_new_continuation_fields=True,
                    actual_report_pointer_carried_in_inventory_and_registration=True,
                    immediate_parent_pin=c.pin(run['parent_state']), immediate_parent_tensor_sha256=c.PARENT_TENSOR_SHA,
                    native_ir_schema_version=None, decoder_profile_id=None, decoder_format_id=None,
                    optimizer_resumable=False, release_relative_path='checkpoints/384d/' + arm + '/' + role + '-state.json',
                    training_summary_pin=training_pin, evaluation_summary_pin=evaluation_pin,
                    actual_training_phase=phases[root.name]['training'], **c.AUTHORITY)
                if role == 'initial':
                    row.update(disposition='initial_parent_copy_no_new_fit', numerical_retention_passed=None)
                else:
                    c.require(tensor == EXPECTED_TENSORS[arm], 'exact retained trained recipe tensor differs')
                    panels = [p for p in evaluation['panels'] if p['arm'] == arm and p['role'] == role]
                    for panel in panels:
                        c.require(panel['state_ref'] == run['states'][role] and panel['physical_panel_computed'] is True,
                            'actual panel/checkpoint byte and tensor identity differs')
                        gather_pins(protected, panel)
                    bank_metrics = {}
                    for bank, ref in run['full180_postfit_readouts'][role].items():
                        readout = bound(protected, ref)
                        c.require(readout['complete'] is True and readout['row_count'] == 180
                            and len(readout['rows']) == 180 and readout['model_tensor_sha256'] == tensor
                            and set(readout['by_field']) == {'actor', 'action', 'modality', 'object'}
                            and all(readout['by_field'][f]['total'] == 180 for f in readout['by_field']),
                            'actual full180 source bank endpoint metrics required')
                        bank_metrics[bank] = readout['by_field']
                    c.require(set(bank_metrics) == {'control', 'balanced'}, 'both actual source-bank inventories required')
                    row.update(actual_disposition(arm, role, panels, comparison, census, bank_metrics))
                    if arm == 'balanced-wording-ce':
                        retained_panel = next(p for p in panels if p['cohort'] == 'normative_train48')
                        fidelity = bound(protected, retained_panel['formula_fidelity_ref'])
                        regressions = [dict(cohort='normative_train48', id=p['id'],
                            candidate_ordered_exact=p['counts']['ordered_exact'], archived_control_ordered_exact=1)
                            for p in fidelity['rows'] if p['counts']['ordered_exact'] != 1]
                        c.require(len(regressions) == 15, 'all fifteen rejected retained-wording paragraph cases required')
                        row['previously_exact_paragraph_regressions'] = regressions
                    row['formula_cohort_ordered_exact'] = {p['cohort']: p['formula_metrics']['ordered_exact'] for p in panels}
                    row['source_bank_fields'] = bank_metrics
                    all_panels.extend(panels)
                states.append(row)
            seen.add(arm)
        c.require(seen == set(arms), 'complete actual retained campaign arms required')
    c.require(len(states) == 9 and len(all_panels) == 24
        and len({r['tensor_sha256'] for r in states if r['role'] != 'initial'}) == 3,
        'exact nine raw/six fitted/three tensor inventory required')
    historical = [p for p in protected.values() if Path(p['path']).stat().st_nlink != 1
        or p['bytes'] == 0 or p['bytes'] > 128 * 1024**2]
    strict = [p for p in protected.values() if p not in historical]
    c.fence(strict)
    c.historical_source_fence(historical)
    return dict(schema='retained-wording-release-authentication/v1', complete=True, states=states,
        full_state_count=9, fitted_endpoint_binding_count=6, independently_trained_arm_count=3,
        unique_fitted_tensor_count=3, physical_evaluation_panels=24, campaigns=summaries,
        phases=phases, comparison_pin=comparison_pin, error_census_pin=census_pin,
        independent_balanced_evaluation_review_pin=review_pin, runtime_metadata_owner=runtime_owner,
        typed_JSON_tensor_digest_authenticated=True, raw_state_headers_not_rewritten=True,
        no_new_matched_campaign_executed=True, protected_input_pins=strict,
        historical_shared_or_large_source_input_pins=historical,
        historical_source_input_count=len(historical), historical_source_input_bytes=sum(p['bytes'] for p in historical),
        strict_input_count=len(strict), strict_input_bytes=sum(p['bytes'] for p in strict),
        full_custody_input_count=len(protected), full_custody_input_bytes=sum(p['bytes'] for p in protected.values()),
        historical_source_scope='Hash-only historical lineage; existing hard links observed at sequential fenced endpoints. No numeric execution, producer admission, or copying.',
        publication_driver_model_execution=False, raw_source_vectors_copied=False, **c.AUTHORITY)


def stage_retained(output_dir):
    out = Path(output_dir)
    c.require(out.is_absolute() and not out.exists(), 'fresh absolute retained staging directory required')
    auth = authenticate_retained()
    native, native_owner = c.load_native('ir_model_hub_publish')
    out.mkdir(parents=True)
    authentication_pin = c.write(out / 'authentication.json', auth)
    public = {k: v for k, v in auth.items() if k != 'protected_input_pins'}
    public.update(source_closure_pin_count=len(auth['protected_input_pins']),
        source_closure_pins_sha256=c.digest(auth['protected_input_pins']))
    staged, manifests, plans = [], [], []
    for repo in c.REPOSITORIES:
        folder = out / 'repositories' / repo.replace('/', '--')
        operations = []
        for row in auth['states']:
            copied = c.write_raw(folder / row['release_relative_path'], c.read(row['original_checkpoint_pin']))
            c.require(copied['sha256'] == row['original_checkpoint_pin']['sha256'], 'raw header/tensor copy changed bytes')
            operations.append(dict(file_pin=copied, path_in_repo=c.RETAINED_PREFIX + '/' + row['release_relative_path']))
        metadata_pin = c.write(folder / 'metadata/authenticated-release.json', public)
        readme = ('# Retained authored wording LegalIR384 experiments\n\n'
            'This release reuses three existing trained recipes: archived retained-bank control, balanced-bank '
            'replacement, and the parallel dual-bank replay trial. Nine byte-exact raw containers contain three '
            'initial copies of the already trained original parent and six fitted selected/last state files. '
            'The six fitted files represent three tensor endpoints and three actual training runs. No new '
            'matched continuation campaign was executed to create this release.\n\n'
            'Control preserves 48/48 paragraphs on all three authored TRAIN cohorts and scores 33/48 on exposed '
            'development wording. Balanced replacement is explicitly rejected: retained wording drops to 33/48, '
            'retained-bank modality reaches 170/180, and exposed development is 19/48. Dual-bank replay preserves '
            '48/48 on the three authored TRAIN cohorts but declines to 30/48 on exposed development. Its recorded '
            'numerical retention decision uses archived control formula panels and original-parent source-bank '
            'floors; auxiliary chronology also changed, so a bank-mix causal improvement is not established.\n\n'
            'The intended task is semantic_IR_reconstruction using original native 384D paragraph and ordered '
            'clause embeddings, original lexical32 codec, saved transforms and a 512-token scope/output budget. '
            'Raw checkpoints retain their older headers; this release inventory and later registration bind the '
            'actual new report/run/recipe separately. Native IR schema/version, decoder profile, and format remain '
            'unknown. Source vectors, corpora, optimizer states, and an executable restoration closure are not '
            'bundled. This is experimental availability, including rejected weights, without default replacement, '
            'runtime admission, teacher qualification, proof authority, fresh semantic generalization, exact original '
            'legal-prose reconstruction, or 8192-token qualification.\n')
        readme_pin = c.write_raw(folder / 'README.md', readme.encode())
        manifest = dict(schema='retained-wording-experimental-checkpoint-release/v1', repository_id=repo,
            release_prefix=c.RETAINED_PREFIX, ir_family_id='legal_ir', dimension=384, dimension_role='input_embedding',
            task_id='semantic_IR_reconstruction', states=auth['states'], full_state_count=9,
            fitted_endpoint_binding_count=6, independently_trained_arm_count=3, unique_fitted_tensor_count=3,
            campaigns=auth['campaigns'], comparison_pin=auth['comparison_pin'], error_census_pin=auth['error_census_pin'],
            raw_headers_preserved_byte_exact=True, no_new_matched_campaign_executed=True,
            source_tokens=512, decoder_output_tokens=512, raw_source_vectors_bundled=False,
            executable_runtime_restoration_closure_bundled=False, optimizer_resumable=False,
            native_ir_schema_version=None, decoder_profile_id=None, decoder_format_id=None, **c.AUTHORITY)
        manifest_pin = c.write(folder / 'manifest.json', manifest)
        operations.extend(dict(file_pin=p, path_in_repo=c.RETAINED_PREFIX + '/' + relative)
            for p, relative in ((metadata_pin, 'metadata/authenticated-release.json'), (readme_pin, 'README.md'),
                (manifest_pin, 'manifest.json')))
        plan = native._capture_plan(dict(schema=native.PLAN_SCHEMA, manifest_pin=manifest_pin,
            repository_id=repo, private_new=False, operations=operations))
        native._freeze_files(plan)
        c.exact_stage_files(folder, [op['path_in_repo'][len(c.RETAINED_PREFIX) + 1:] for op in operations])
        plans.append(c.write(out / 'plans' / (repo.replace('/', '--') + '.json'), plan))
        manifests.append(manifest_pin)
        staged.extend(op['file_pin'] for op in operations)
    result = dict(schema='retained-wording-publication-preparation/v1', complete=True,
        source_pins=c.source_pins(), native_publisher_owner=native_owner, authentication_pin=authentication_pin,
        plan_pins=plans, manifest_pins=manifests, staged_file_pins=staged, repository_ids=list(c.REPOSITORIES),
        release_prefix=c.RETAINED_PREFIX, full_state_count=9, fitted_endpoint_binding_count=6,
        unique_fitted_tensor_count=3, preparation_without_network=True, model_or_database_constructed=False,
        publication_executed=False, database_write_executed=False, **c.AUTHORITY)
    c.fence(auth['protected_input_pins'] + result['source_pins'] + staged)
    c.historical_source_fence(auth['historical_shared_or_large_source_input_pins'])
    return c.write(out / 'preparation.json', result)


def build_retained_records(preparation_pin, release_pins, output_dir):
    out = Path(output_dir)
    c.require(out.is_absolute() and not out.exists(), 'fresh absolute retained record directory required')
    prep = c.document(preparation_pin)
    c.require(prep['schema'] == 'retained-wording-publication-preparation/v1' and prep['complete'] is True
        and prep['source_pins'] == c.source_pins(), 'exact frozen retained publication preparation required')
    auth = c.document(prep['authentication_pin'])
    native, owner = c.load_native('ir_model_manager_import')
    receipts = [c.document(p) for p in release_pins]
    c.require(len(receipts) == 2 and {r['repository_id'] for r in receipts} == set(c.REPOSITORIES),
        'both actually published immutable repository receipts required')
    for receipt in receipts:
        c.require(receipt['schema'] == native.PUBLICATION_SCHEMA and receipt['files_verified'] is True
            and receipt['repository_private'] is False, 'native verified immutable public receipt required')
        for row in auth['states']:
            wanted = c.RETAINED_PREFIX + '/' + row['release_relative_path']
            c.require(len([f for f in receipt['files'] if f['path_in_repo'] == wanted
                and f['sha256'] == row['original_checkpoint_pin']['sha256'] and f['verified'] is True]) == 1,
                'both repositories must retain all nine actual state bytefiles')
    lane = next(r for r in receipts if r['repository_id'] == c.REPOSITORIES[1])
    records = []
    for row in auth['states']:
        if row['role'] == 'initial':
            continue
        initial = next(r['original_checkpoint_pin'] for r in auth['states'] if r['arm'] == row['arm'] and r['role'] == 'initial')
        state = c.document(row['original_checkpoint_pin'])
        role = row['arm'].replace('-', '_') + '_' + row['role'].replace('-', '_') + '_semantic_decoder_state'
        record = future.checkpoint_record(native, state, row, lane, prep['authentication_pin'],
            row['training_summary_pin'], row['evaluation_summary_pin'], initial,
            prefix=c.RETAINED_PREFIX, binding_role=role)
        config = record['model_metadata']['huggingface_config']
        config.update(study_id='retained-wording-recipes-20261007', actual_training_phase=row['actual_training_phase'],
            checkpoint_headers_preserved=True, checkpoint_headers_lack_current_continuation_fields=True,
            actual_report_pointer_carried_in_registration=True, no_new_matched_campaign_executed=True,
            retention_scope=row['retention_scope'], formula_cohort_ordered_exact=row['formula_cohort_ordered_exact'],
            source_bank_fields=row['source_bank_fields'], comparison_pin=auth['comparison_pin'],
            exposed_development_error_census_pin=auth['error_census_pin'],
            bank_mix_effect_causally_isolated=False, auxiliary_chronology_changed=row['arm'] == 'dual-bank-retention-ce')
        record['model_metadata']['model_name'] = 'LegalIR384 retained ' + row['arm'] + ' ' + row['role']
        records.append(record)
    c.require(len(records) == 6 and len({r['model_metadata']['model_id'] for r in records}) == 6,
        'six distinct actual fitted recipe/role byte bindings required')
    c.fence(auth['protected_input_pins'] + prep['source_pins'] + prep['staged_file_pins'] + list(release_pins))
    c.historical_source_fence(auth['historical_shared_or_large_source_input_pins'])
    out.mkdir(parents=True)
    plan_pin = c.write(out / 'model-manager-import-plan.json', dict(schema=native.SCHEMA, models=records))
    native._prepare(plan_pin, release_pins, native.MAX_REFERENCE_BYTES)
    return c.write(out / 'preparation.json', dict(schema='retained-wording-model-manager-plan-preparation/v1',
        complete=True, import_plan_pin=plan_pin, publication_preparation_pin=preparation_pin,
        authentication_pin=prep['authentication_pin'], release_receipt_pins=list(release_pins), importer_owner=owner,
        source_pins=c.source_pins(), fitted_endpoint_binding_count=6, independent_training_run_count=3,
        native_prepare_passed=True, manager_or_database_constructed=False, **c.AUTHORITY))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    authenticate = commands.add_parser('authenticate')
    stage = commands.add_parser('stage')
    records = commands.add_parser('build-records')
    records.add_argument('--preparation', required=True)
    records.add_argument('--release-receipt', action='append', required=True)
    for command in (authenticate, stage, records):
        command.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'authenticate':
        c.require(args.output_directory.is_absolute() and not args.output_directory.exists(), 'fresh authentication output required')
        value = authenticate_retained()
        result = c.write(args.output_directory / 'authentication.json', value)
    elif args.command == 'stage':
        result = stage_retained(args.output_directory)
    else:
        result = build_retained_records(c.argument_pin(args.preparation),
            [c.argument_pin(p) for p in args.release_receipt], args.output_directory)
    print(c.wire(dict(complete=True, result_pin=result, network_executed=False, database_write_executed=False,
        model_numerically_executed=False, new_training_executed=False)))


if __name__ == '__main__':
    main()
