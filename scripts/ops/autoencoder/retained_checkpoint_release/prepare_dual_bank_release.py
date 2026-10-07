"""Stage six byte-exact experimental states; build four records after publication."""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import sys

import publication_common as c

PROTOCOL = c.BASE / 'artifacts/autoencoder-dual-bank-fit-20261007/predeclared-comparison-protocol.json'
PROTOCOL_SHA = '5a91408e4e3a78fc0d4d7d2fa00fda0fd4b580a19815a3d7888687d12420999c'
COHORTS = ('original_train48', 'normative_train48', 'new_balanced_train48', 'exposed_v3_48')
FALSE_FLAGS = ('qualified', 'admitted', 'proof_authority', 'checkpoint_promoted',
    'source_semantics_verified', 'fresh_holdout', 'lake_executed', 'optimizer_resumable')


def remember(protected, value):
    value = c.pin(value)
    c.require(value['path'] not in protected or protected[value['path']] == value, 'conflicting same-path pin')
    c.require(c.capture(value['path']) == value, 'input pin bytes differ')
    protected[value['path']] = value
    return value


def bound(protected, value, *, maximum=c.MAX_METADATA):
    return c.document(remember(protected, value), maximum=maximum)


def terminal(protected, child_exit_pin, resources_final_pin):
    child = bound(protected, child_exit_pin)
    resources = bound(protected, resources_final_pin)
    c.require(type(child.get('returncode')) is int and child['returncode'] == 0
        and resources.get('status') == 'released', 'successful released numerical phase required')


def source_closure(protected, state):
    for field in ('source_refs', 'continuation_source_refs'):
        values = state[field]
        c.require(type(values) is dict and 1 <= len(values) <= 20000, 'closed saved source-reference inventory required')
        for path, expected in values.items():
            observed = c.capture(Path(path))
            c.require(observed['sha256'] == expected, 'saved recursive source-reference bytes differ')
            remember(protected, observed)


def inspect_state(runtime, protected, value, run, role, parent):
    checkpoint_pin = remember(protected, value)
    state = c.document(checkpoint_pin)
    c.require(state['schema'] == state['state_serialization_schema'] == 'private-native-dimension-source-state/v1'
        and type(state['dimension']) is int and state['dimension'] == 384
        and state['ir_family_id'] == 'legal_ir' and state['dimension_role'] == 'input_embedding'
        and state['task_id'] == 'semantic_IR_reconstruction', 'exact LegalIR384 semantic checkpoint identity required')
    arm = run['arm']
    recipe = {'name': arm, 'weight': .05}
    c.require(type(state['recipe']['weight']) is float and state['recipe'] == state['continuation_recipe'] == recipe
        and state['role'] == state['continuation_role'] == role and state['continuation_arm'] == arm
        and state['continuation_run_id'] == run['_run_id'], 'actual run/arm/role/recipe header differs')
    c.require(type(state['selected']) is bool and (role != 'selected' or state['selected'] is True)
        and (role != 'initial' or state['selected'] is False), 'selected/initial header differs')
    c.require(all(state[name] is None for name in ('native_ir_schema_version', 'decoder_profile_id', 'decoder_format_id')),
        'unknown native schema/profile/format must remain null')
    c.require(all(state[name] is False for name in FALSE_FLAGS), 'state must remain unqualified and nonresumable')
    c.require(state['continuation_parent'] == run['parent_state'], 'original trained parent pin differs')
    for key in ('codec', 'architecture', 'input_transform', 'initializer_receipt', 'lineage', 'source_refs'):
        c.require(c.wire(state[key]) == c.wire(parent[key]), 'frozen inherited metadata differs: ' + key)
    c.require(state['codec']['schema'] == 'typed-json-lexical/v1'
        and len(state['codec']['target_vocabulary']) == len(set(state['codec']['target_vocabulary'])) == 32
        and state['codec_sha256'] == runtime._digest(state['codec'])
        and state['codec_sha256'] == state['lineage']['teacher_codec_sha256'], 'original ordered codec differs')
    shapes, _ = runtime._shapes(384)
    tensor_sha = runtime._tensor_digest(state['model_state'], shapes, integer_buffers=True)
    c.require(tensor_sha == state['tensor_sha256'] == value['tensor_sha256']
        and runtime._digest(state['model_state']) == state['weights_sha256']
        and len(state['model_state']) == 32, 'full typed32 checkpoint tensors differ')
    if role == 'initial':
        c.require(state['continuation_training_ref'] is None and state['continuation_training_executed'] is False
            and tensor_sha == c.PARENT_TENSOR_SHA, 'initial is original trained parent with no NEW continuation fit')
    else:
        c.require(state['continuation_training_ref'] == run['training_ref']
            and state['continuation_training_executed'] is True, 'actual new continuation report pointer required')
        report = bound(protected, run['training_ref'], maximum=64 * 1024**2)
        wanted = report['selected_weights_sha256' if role == 'selected' else 'last_complete_attempt_weights_sha256']
        c.require(tensor_sha == wanted, 'actual committed report endpoint differs')
    for key, expected in (('continuation_phase_manifest', c.TRAIN_MANIFEST_SHA),
            ('continuation_phase_plan', c.TRAIN_PLAN_SHA)):
        phase_pin = remember(protected, state[key])
        c.require(phase_pin['sha256'] == expected, 'original canonical phase seal differs')
    source_closure(protected, state)
    return state, dict(ir_family_id='legal_ir', dimension=384, dimension_role='input_embedding',
        task_id='semantic_IR_reconstruction', arm=arm, role=role, recipe=recipe,
        original_checkpoint_pin=checkpoint_pin, tensor_sha256=tensor_sha,
        serialization_schema=state['schema'], codec_sha256=state['codec_sha256'],
        selected_header_value=state['selected'], full_model_state_entries=32,
        continuation_run_id=run['_run_id'], continuation_training_ref=state['continuation_training_ref'],
        new_continuation_training_executed=role != 'initial', original_parent_already_trained=True,
        immediate_parent_pin=c.pin(run['parent_state']), immediate_parent_tensor_sha256=c.PARENT_TENSOR_SHA,
        native_ir_schema_version=None, decoder_profile_id=None, decoder_format_id=None,
        optimizer_resumable=False, **c.AUTHORITY)


def authenticate(training_pin, evaluation_pin, terminals):
    protected = {}
    protocol_pin = remember(protected, c.capture(PROTOCOL))
    c.require(protocol_pin['sha256'] == PROTOCOL_SHA, 'predeclared exact protocol changed')
    for exit_pin, resource_pin in terminals:
        terminal(protected, exit_pin, resource_pin)
    training = bound(protected, training_pin)
    evaluation = bound(protected, evaluation_pin)
    c.require(training.get('schema') == 'dual-bank-wording-continuation-result/v1'
        and training.get('complete') is True and training.get('phase') == 'training'
        and type(training.get('dimension')) is int and training['dimension'] == 384
        and len(training['runs']) == 2, 'two actual completed matched fits required')
    c.require(evaluation.get('schema') == 'dual-bank-wording-postfit-evaluation-plan/v1'
        and evaluation.get('complete') is True and evaluation.get('phase') == 'evaluation'
        and evaluation.get('parent_tensor_sha256') == c.PARENT_TENSOR_SHA
        and evaluation.get('physical_panels') == evaluation.get('logical_panels') == 20
        and len(evaluation['panels']) == 20 and len(evaluation['raw_original_probes']) == 45,
        'complete actual closed twenty-panel evaluation required')
    runtime, runtime_owner = c.load_native('contextual_legal_ir_runtime')
    remember(protected, runtime_owner['pin'])
    runs, state_rows, checkpoint_data = {}, [], {}
    for run_ref in training['runs']:
        run = bound(protected, run_ref)
        arm = run['arm']
        c.require(arm in c.ARMS and arm not in runs and run['budget_completed'] is True
            and run['natural_stop'] == 'epochs_completed' and type(run['seed']) is int and run['seed'] == 1729
            and run['recipe'] == {'name': arm, 'weight': .05} and type(run['recipe']['weight']) is float
            and set(run['states']) == set(c.ROLES) and run['fresh_optimizer'] is True
            and run['fresh_scheduler'] is True and run['exact_optimizer_resume'] is False,
            'exact completed matched arm required')
        run['_run_id'] = str(Path(training_pin['path']).parent)
        parent = bound(protected, run['parent_state'])
        c.require(run['initial_tensor_sha256'] == run['parent_state']['tensor_sha256'] == c.PARENT_TENSOR_SHA,
            'exact original trained parent tensor required')
        report = bound(protected, run['training_ref'], maximum=64 * 1024**2)
        expected_counts = dict(optimizer_steps=170, row_presentations=1220,
            count_training_row_presentations=1220, valid_target_token_presentations=112920,
            source_value_presentations=12800, auxiliary_source_modality_presentations=1020)
        c.require(all(type(report[k]) is int and report[k] == v for k, v in expected_counts.items())
            and report['stopped_reason'] == 'epochs_completed' and len(report['committed_updates']) == 170,
            'actual unchanged committed training budget required')
        for role in c.ROLES:
            state, row = inspect_state(runtime, protected, run['states'][role], run, role, parent)
            relative = 'checkpoints/384d/' + arm + '/' + role + '-state.json'
            row['release_relative_path'] = relative
            state_rows.append(row)
            checkpoint_data[(arm, role)] = state
        c.require(run['selected_last_tensor_alias'] is
            (run['states']['selected']['tensor_sha256'] == run['states']['last-attempt']['tensor_sha256']),
            'selected/last alias observation differs')
        runs[arm] = run
    c.require(set(runs) == set(c.ARMS), 'both matched arms required')
    expected_panels = {('parent', 'selected', cohort) for cohort in COHORTS}
    expected_panels |= {(arm, role, cohort) for arm in c.ARMS for role in c.FITTED_ROLES for cohort in COHORTS}
    c.require({(p['arm'], p['role'], p['cohort']) for p in evaluation['panels']} == expected_panels,
        'exact complete endpoint/cohort panels required')
    for panel in evaluation['panels']:
        wanted = runs[c.ARMS[0]]['parent_state'] if panel['arm'] == 'parent' else runs[panel['arm']]['states'][panel['role']]
        c.require(panel['state_ref'] == wanted and panel['physical_panel_computed'] is True
            and panel['paragraphs'] == 48 and panel['rules'] == 180,
            'evaluation panel must bind actual original or fitted endpoint')
        for key in ('trace_ref', 'predictions_ref', 'scalar_score_ref', 'formula_fidelity_ref',
                'scalar_formula_join_ref', 'gate_panel_ref'):
            remember(protected, panel[key])
    gates = evaluation['retention_gates']
    c.require(type(gates) is list and len(gates) == 4
        and {(g['arm'], g['role']) for g in gates} == {(a, r) for a in c.ARMS for r in c.FITTED_ROLES},
        'four complete actual retention dispositions required')
    for row in state_rows:
        if row['role'] == 'initial':
            row.update(disposition='initial_parent_copy_no_new_fit', numerical_retention_passed=None)
        else:
            result = next(g for g in gates if (g['arm'], g['role']) == (row['arm'], row['role']))
            gate = result['gate']
            c.require(gate['schema'] == 'dual-authored-wording-numerical-retention-gate/v1'
                and type(gate['numerical_retention_passed']) is bool
                and gate['allowed_numerical_continuation'] is gate['numerical_retention_passed']
                and type(gate['findings']) is list and all(type(s) is str for s in gate['findings'])
                and gate['numerical_retention_passed'] is (not gate['findings'])
                and (not gate['numerical_retention_passed'] or not result['previously_exact_paragraph_regressions']),
                'truthful experimental/rejected retention disposition required')
            row.update(disposition='experimental_retention_passed' if gate['numerical_retention_passed']
                else 'experimental_rejected_retention_failed', numerical_retention_passed=gate['numerical_retention_passed'],
                retention_findings=deepcopy(gate['findings']),
                previously_exact_paragraph_regressions=deepcopy(result['previously_exact_paragraph_regressions']))
    c.fence(list(protected.values()))
    return dict(schema='dual-bank-release-authentication/v1', complete=True, states=state_rows,
        training_summary_pin=c.pin(training_pin), evaluation_summary_pin=c.pin(evaluation_pin), protocol_pin=protocol_pin,
        terminal_pins=terminals, runtime_metadata_owner=runtime_owner, full_state_count=6,
        fitted_endpoint_binding_count=4, independently_trained_arm_count=2,
        unique_fitted_tensor_count=len({s['tensor_sha256'] for s in state_rows if s['role'] != 'initial'}),
        typed_JSON_tensor_digest_authenticated=True, raw_source_vectors_copied=False,
        protected_input_pins=list(protected.values()), **c.AUTHORITY), checkpoint_data


def stage_publication(training_pin, evaluation_pin, terminals, output_dir):
    out = Path(output_dir)
    c.require(out.is_absolute() and not out.exists(), 'fresh absolute staging directory required')
    authentication, _ = authenticate(training_pin, evaluation_pin, terminals)
    native, native_owner = c.load_native('ir_model_hub_publish')
    out.mkdir(parents=True)
    auth_pin = c.write(out / 'authentication.json', authentication)
    # Full source closure stays local; no corpus/reference/cache files are staged.
    public = {k: v for k, v in authentication.items() if k != 'protected_input_pins'}
    public['source_closure_pin_count'] = len(authentication['protected_input_pins'])
    public['source_closure_pins_sha256'] = c.digest(authentication['protected_input_pins'])
    plans, manifests, staged = [], [], []
    for repo in c.REPOSITORIES:
        directory = out / 'repositories' / repo.replace('/', '--')
        ops = []
        for row in authentication['states']:
            local = c.write_raw(directory / row['release_relative_path'], c.read(row['original_checkpoint_pin']))
            c.require(local['sha256'] == row['original_checkpoint_pin']['sha256'], 'copy changed checkpoint bytes')
            ops.append(dict(file_pin=local, path_in_repo=c.PREFIX + '/' + row['release_relative_path']))
        metadata_pin = c.write(directory / 'metadata/authenticated-release.json', public)
        readme = ('# Experimental matched LegalIR384 continuation\n\n'
            'Six exact raw state containers preserve initial, selected, and last-attempt states for two matched '
            'seed-1729 continuation arms. The initial states are copies of an already trained original parent; '
            'they received no new continuation fitting. Four fitted endpoint bindings represent two training '
            'runs; selected/last may alias the same tensors. This is an experimental release, including explicitly '
            'rejected endpoints when the complete authored retention gate failed.\n\n'
            'The task is semantic_IR_reconstruction from retained native 384D paragraph and ordered clause '
            'embeddings, with the original typed JSON lexical codec and saved input transforms. Source and output '
            'scope remain 512 tokens. No embeddings were regenerated. Raw source vectors, corpora, optimizer '
            'state, parent weights, or an executable restoration closure are bundled. Native output schema/version, '
            'decoder profile and decoder format remain unknown. The recorded panels measure authored rule '
            'reconstruction; they do not establish exact original legal-prose reconstruction or fresh legal semantics.\n\n'
            'Runtime admission, default replacement, teacher qualification, proof authority, legal-text '
            'reconstruction qualification, and 8192-token qualification remain false, including for endpoints '
            'that passed numerical retention. See manifest.json for exact checkpoint, run, recipe, codec, '
            'evaluation pins and retention dispositions.\n')
        readme_pin = c.write_raw(directory / 'README.md', readme.encode())
        manifest = dict(schema='dual-bank-experimental-checkpoint-release/v1', repository_id=repo,
            release_prefix=c.PREFIX, family='legal_ir', dimension=384, dimension_role='input_embedding',
            task_id='semantic_IR_reconstruction', states=authentication['states'],
            full_state_count=6, fitted_endpoint_binding_count=4, independently_trained_arm_count=2,
            unique_fitted_tensor_count=authentication['unique_fitted_tensor_count'],
            training_summary_pin=c.pin(training_pin), evaluation_summary_pin=c.pin(evaluation_pin),
            protocol_pin=authentication['protocol_pin'], source_tokens=512, decoder_output_tokens=512,
            exact_original_checkpoint_bytes=True, raw_source_vectors_bundled=False,
            complete_runtime_restoration_closure_bundled=False, optimizer_resumable=False,
            native_ir_schema_version=None, decoder_profile_id=None, decoder_format_id=None, **c.AUTHORITY)
        manifest_pin = c.write(directory / 'manifest.json', manifest)
        ops.extend(dict(file_pin=p, path_in_repo=c.PREFIX + '/' + relative) for p, relative in
            ((metadata_pin, 'metadata/authenticated-release.json'), (readme_pin, 'README.md'), (manifest_pin, 'manifest.json')))
        plan = native._capture_plan(dict(schema=native.PLAN_SCHEMA, manifest_pin=manifest_pin,
            repository_id=repo, private_new=False, operations=ops))
        native._freeze_files(plan)
        c.exact_stage_files(directory, [op['path_in_repo'][len(c.PREFIX) + 1:] for op in ops])
        plans.append(c.write(out / 'plans' / (repo.replace('/', '--') + '.json'), plan))
        manifests.append(manifest_pin)
        staged.extend(op['file_pin'] for op in ops)
    result = dict(schema='dual-bank-publication-preparation/v1', complete=True,
        source_pins=c.source_pins(), native_publisher_owner=native_owner, authentication_pin=auth_pin,
        plan_pins=plans, manifest_pins=manifests, staged_file_pins=staged,
        repository_ids=list(c.REPOSITORIES), release_prefix=c.PREFIX,
        preparation_without_network=True, model_or_database_constructed=False,
        publication_executed=False, database_write_executed=False, **c.AUTHORITY)
    c.fence(authentication['protected_input_pins'] + result['source_pins'] + staged)
    return c.write(out / 'preparation.json', result)


def checkpoint_record(native, state, row, publication, auth_pin, training_pin, evaluation_pin, initial_pin,
                      *, prefix=c.PREFIX, binding_role=None):
    original = c.pin(row['original_checkpoint_pin'])
    path = prefix + '/' + row['release_relative_path']
    matches = [f for f in publication['files'] if f['path_in_repo'] == path
        and f['sha256'] == original['sha256'] and f['bytes'] == original['bytes'] and f['verified'] is True]
    c.require(len(matches) == 1, 'one exact immutable published endpoint required')
    release = dict(repository_id=publication['repository_id'], revision=publication['revision'],
        path_in_repo=path, checkpoint_sha256=original['sha256'])
    role = binding_role or ('dual_bank_replay_20261007_run_01_' + row['arm'] + '_' + row['role'].replace('-', '_') + '_semantic_decoder_state')
    model_id = native.ir_model_asset_record_id('legal_ir', 384, 'input_embedding', role, original['sha256'])
    identity = dict(record_id=model_id, ir_family_id='legal_ir', dimension=384, dimension_role='input_embedding',
        role=role, schema_version=None, task_id='semantic_IR_reconstruction', profile_id=None, format_id=None,
        original_checkpoint_pin=original, trained=True, donor=None, initialization_only=False,
        runtime_ready=False, teacher_qualified=False, proof_authority=False)
    config = dict(ir_checkpoint=identity, complete_runtime_io_contract=False,
        checkpoint_serialization_schema=state['schema'], native_output_schema_status='unknown',
        study_id='dual-bank-replay-20261007', training_run_id=row['continuation_run_id'],
        continuation_arm=row['arm'], recipe=row['recipe'], original_state_role=row['role'],
        original_selected_field=state['selected'], full_model_state_entry_count=32,
        tensor_sha256=row['tensor_sha256'], frozen_weights_sha256=state['weights_sha256'],
        selected_last_not_independent_training_runs=True, optimizer_resumable=False,
        decoder_codec=state['codec'], ordered_codec_sha256=row['codec_sha256'],
        saved_input_transform_sha256=c.digest(state['input_transform']), original_lineage=state['lineage'],
        independent_custody_receipt_pin=auth_pin, immediate_parent_pin=row['immediate_parent_pin'],
        immediate_parent_tensor_sha256=c.PARENT_TENSOR_SHA, continued_initial_state_pin=initial_pin,
        continuation_training_ref=row['continuation_training_ref'],
        continuation_phase_manifest=c.pin(state['continuation_phase_manifest']) if state.get('continuation_phase_manifest') else None,
        continuation_phase_plan=c.pin(state['continuation_phase_plan']) if state.get('continuation_phase_plan') else None,
        native_raw_header_has_current_training_ref=state.get('continuation_training_ref') == row['continuation_training_ref'],
        training_summary_pin=training_pin, evaluation_summary_pin=evaluation_pin,
        disposition=row['disposition'], numerical_retention_passed=row['numerical_retention_passed'],
        retention_findings=row['retention_findings'], previously_exact_paragraph_regressions=row['previously_exact_paragraph_regressions'],
        source_context_tokens=512, declared_decoder_output_token_limit=512,
        input_contract=dict(paragraph_width=384, clause_width=384, max_source_clauses=8,
            saved_normalization_required=True, original_cached_vectors_required=True,
            original_contextual_facade_recipe_supported=False, vector_producer_authenticated=False),
        production_checkpoint=False, release=release, **c.AUTHORITY)
    metadata = dict(model_id=model_id, model_name='LegalIR384 dual-bank run-01 ' + row['arm'] + ' ' + row['role'],
        model_type='decoder_only', architecture=state['architecture']['schema'],
        inputs=[dict(name='native_paragraph_embedding', data_type='embeddings', shape=[-1, 384]),
            dict(name='native_clause_embeddings', data_type='embeddings', shape=[-1, 8, 384]),
            dict(name='clause_mask', data_type='features', shape=[-1, 8], dtype='bool')],
        outputs=[dict(name='canonical_ir_tokens', data_type='tokens', shape=[-1, -1], dtype='int64')],
        huggingface_config=config, model_revision=original['sha256'], revision_id=original['sha256'],
        source_url='https://huggingface.co/' + release['repository_id'] + '/blob/' + release['revision'] + '/' + path,
        tags=['legal_ir', '384d', row['arm'], row['role'], 'experimental', 'runtime-unqualified', row['disposition']],
        description='Actual matched continuation state with exact report/run/recipe/codec lineage. Experimental availability only. Retention disposition is explicit; selected/last are not independent runs. Native schema/profile/format, runtime dispatch, teacher qualification, exact legal prose, and proof authority remain unqualified.')
    return dict(model_metadata=metadata, checkpoint_pin=original, release=release)


def build_registration_plan(preparation_pin, release_pins, output_dir):
    out = Path(output_dir)
    c.require(out.is_absolute() and not out.exists(), 'fresh absolute plan directory required')
    prep = c.document(preparation_pin)
    c.require(prep['schema'] == 'dual-bank-publication-preparation/v1' and prep['complete'] is True
        and prep['source_pins'] == c.source_pins(), 'exact frozen publication preparation required')
    auth = c.document(prep['authentication_pin'])
    native, importer_owner = c.load_native('ir_model_manager_import')
    publications = [c.document(p) for p in release_pins]
    c.require(len(publications) == 2 and {r['repository_id'] for r in publications} == set(c.REPOSITORIES),
        'both actual immutable repository receipts required')
    for publication in publications:
        c.require(publication['schema'] == native.PUBLICATION_SCHEMA and publication['files_verified'] is True
            and publication['repository_private'] is False, 'verified public native publication required')
        for row in auth['states']:
            path = c.PREFIX + '/' + row['release_relative_path']
            matches = [f for f in publication['files'] if f['path_in_repo'] == path
                and f['sha256'] == row['original_checkpoint_pin']['sha256'] and f['verified'] is True]
            c.require(len(matches) == 1, 'both repositories must retain all six exact state containers')
    lane = next(r for r in publications if r['repository_id'] == c.REPOSITORIES[1])
    records = []
    for row in auth['states']:
        if row['role'] == 'initial':
            continue
        initial = next(r['original_checkpoint_pin'] for r in auth['states'] if r['arm'] == row['arm'] and r['role'] == 'initial')
        records.append(checkpoint_record(native, c.document(row['original_checkpoint_pin']), row, lane,
            prep['authentication_pin'], auth['training_summary_pin'], auth['evaluation_summary_pin'], initial))
    c.require(len(records) == 4 and len({r['model_metadata']['model_id'] for r in records}) == 4,
        'exact four distinct fitted role/run bindings required')
    c.fence(auth['protected_input_pins'] + prep['source_pins'] + prep['staged_file_pins'] + list(release_pins))
    out.mkdir(parents=True)
    manifest_pin = c.write(out / 'model-manager-import-plan.json', dict(schema=native.SCHEMA, models=records))
    native._prepare(manifest_pin, release_pins, native.MAX_REFERENCE_BYTES)
    result = dict(schema='dual-bank-model-manager-plan-preparation/v1', complete=True, import_plan_pin=manifest_pin,
        publication_preparation_pin=c.pin(preparation_pin), authentication_pin=prep['authentication_pin'],
        release_receipt_pins=list(release_pins), importer_owner=importer_owner, source_pins=c.source_pins(),
        fitted_endpoint_binding_count=4, independent_training_run_count=2,
        native_prepare_passed=True, manager_or_database_constructed=False, **c.AUTHORITY)
    return c.write(out / 'preparation.json', result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    stage = commands.add_parser('stage')
    stage.add_argument('--training-summary', required=True)
    stage.add_argument('--evaluation-summary', required=True)
    for phase in ('training', 'evaluation'):
        stage.add_argument('--' + phase + '-child-exit', required=True)
        stage.add_argument('--' + phase + '-resources-final', required=True)
    records = commands.add_parser('build-records')
    records.add_argument('--preparation', required=True)
    records.add_argument('--release-receipt', action='append', required=True)
    for command in (stage, records):
        command.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'stage':
        terminals = [(c.argument_pin(getattr(args, phase + '_child_exit')),
            c.argument_pin(getattr(args, phase + '_resources_final'))) for phase in ('training', 'evaluation')]
        result = stage_publication(c.argument_pin(args.training_summary), c.argument_pin(args.evaluation_summary), terminals, args.output_directory)
    else:
        result = build_registration_plan(c.argument_pin(args.preparation),
            [c.argument_pin(p) for p in args.release_receipt], args.output_directory)
    print(c.wire(dict(completed=True, result_pin=result, network_executed=False, database_write_executed=False)))


if __name__ == '__main__':
    main()
