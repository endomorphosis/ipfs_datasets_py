"""Register four fitted experimental endpoints through the unchanged genuine boundary.

The default performs offline native import-plan authentication only. Live storage
is opened only with --register and an exact independent review receipt. No direct
SQL mutation, full-population save, numerical model loading, or Hub access exists.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import publication_common as c


def authentication_join(plan, authentication):
    contract = c.inventory_contract(authentication['schema'])
    c.require(authentication.get('schema') == contract['authentication_schema']
        and authentication.get('complete') is True and authentication['full_state_count'] == contract['raw_count']
        and authentication['fitted_endpoint_binding_count'] == contract['fitted_count']
        and authentication['independently_trained_arm_count'] == contract['run_count']
        and authentication['typed_JSON_tensor_digest_authenticated'] is True,
        'actual six-state/four-binding authentication required')
    rows = [r for r in authentication['states'] if r['role'] in c.FITTED_ROLES]
    c.require(len(plan['models']) == len(rows) == contract['fitted_count']
        and {(r['arm'], r['role']) for r in rows} == {(a, r) for a in contract['arms'] for r in c.FITTED_ROLES},
        'exact four separate actual fitted run/role records required')
    joins = []
    for record in plan['models']:
        original = c.pin(record['checkpoint_pin'])
        matched = [r for r in rows if r['original_checkpoint_pin'] == original]
        c.require(len(matched) == 1, 'one exact authenticated fitted checkpoint required')
        row = matched[0]
        metadata = record['model_metadata']
        config = metadata['huggingface_config']
        identity = config['ir_checkpoint']
        expected = dict(ir_family_id='legal_ir', dimension=384, dimension_role='input_embedding',
            schema_version=None, task_id='semantic_IR_reconstruction', profile_id=None, format_id=None,
            trained=True, initialization_only=False, donor=None, runtime_ready=False,
            teacher_qualified=False, proof_authority=False, original_checkpoint_pin=original)
        c.require(all(identity.get(k) == v and type(identity.get(k)) is type(v) for k, v in expected.items()),
            'exact native family/width/task/null schema/status required')
        c.require(config['training_run_id'] == row['continuation_run_id']
            and config['continuation_arm'] == row['arm'] and config['original_state_role'] == row['role']
            and config['recipe'] == row['recipe'] and config['ordered_codec_sha256'] == row['codec_sha256']
            and config['checkpoint_serialization_schema'] == row['serialization_schema']
            and config['tensor_sha256'] == row['tensor_sha256']
            and config['continuation_training_ref'] == row['continuation_training_ref']
            and config['disposition'] == row['disposition']
            and config['numerical_retention_passed'] is row['numerical_retention_passed'],
            'actual fitted checkpoint/run/recipe/task/evaluation join differs')
        c.require(all(config.get(k) is False for k in c.AUTHORITY), 'availability cannot promote any authority')
        joins.append(dict(model_id=metadata['model_id'], checkpoint_pin=original,
            arm=row['arm'], role=row['role'], tensor_sha256=row['tensor_sha256'], disposition=row['disposition']))
    return joins


def validate_review(value, *, source_pins, guard_pin, custody_pin, plan_pin, auth_pin, releases, owners):
    c.require(value.get('schema') == 'dual-bank-model-manager-registration-driver-review/v1'
        and value.get('approved') is True and value.get('findings') == [],
        'approved independent genuine registration boundary review required')
    wanted = dict(reviewed_source_pins=source_pins, reviewed_reused_guard_pin=guard_pin,
        reviewed_reused_custody_pin=custody_pin, reviewed_plan_pin=plan_pin,
        reviewed_authentication_pin=auth_pin, reviewed_release_receipt_pins=releases,
        reviewed_source_owners=owners)
    for key, answer in wanted.items():
        c.require(c.wire(value.get(key)) == c.wire(answer), 'reviewed exact bytes/source differ: ' + key)


def register_plan(plan_preparation_pin, output_dir, *, register=False, review_pin=None):
    out = Path(output_dir)
    c.require(out.is_absolute() and not out.exists(), 'fresh absolute registration-attempt directory required')
    preparation = c.document(plan_preparation_pin)
    contract = c.inventory_contract(preparation['schema'])
    c.require(preparation['schema'] == contract['preparation_schema']
        and preparation['complete'] is True and preparation['source_pins'] == c.source_pins(),
        'exact four-record frozen native plan preparation required')
    plan_pin, auth_pin = preparation['import_plan_pin'], preparation['authentication_pin']
    releases = preparation['release_receipt_pins']
    native, importer_owner = c.load_native('ir_model_manager_import')
    c.require(importer_owner == preparation['importer_owner'], 'native importer source changed')
    full_plan, native_pins, _, _ = native._prepare(plan_pin, releases, native.MAX_REFERENCE_BYTES)
    authentication = c.document(auth_pin)
    joins = authentication_join(full_plan, authentication)
    guard, guard_pin, custody_pin = c.load_guard()
    owners = guard.selected_source_owners()
    protected = authentication['protected_input_pins'] + native_pins + preparation['source_pins'] + [
        c.pin(plan_preparation_pin), auth_pin, guard_pin, custody_pin]
    historical = authentication.get('historical_shared_or_large_source_input_pins', [])
    def fence_all():
        guard.fence(protected, owners)
        c.historical_source_fence(historical)
    fence_all()
    out.mkdir(parents=True)
    preflight_pin = c.write(out / 'preflight.json', dict(schema='dual-bank-registration-preflight/v1',
        complete=True, plan_preparation_pin=plan_preparation_pin, plan_pin=plan_pin, authentication_pin=auth_pin,
        source_pins=preparation['source_pins'], reused_guard_pin=guard_pin, reused_custody_pin=custody_pin,
        source_owners=owners, release_receipt_pins=releases, authentication_joins=joins,
        model_count=contract['fitted_count'], independent_training_run_count=contract['run_count'], database_opened=False,
        manager_constructed=False, **c.AUTHORITY))
    if not register:
        return preflight_pin
    c.require(review_pin is not None, 'explicit registration needs a pinned independent review')
    validate_review(c.document(review_pin), source_pins=preparation['source_pins'],
        guard_pin=guard_pin, custody_pin=custody_pin, plan_pin=plan_pin, auth_pin=auth_pin,
        releases=releases, owners=owners)
    protected.append(review_pin)
    phase, mutation_possible, manager, absent_ids = 'preflight', False, None, frozenset()
    try:
        guard.environment()
        sys.path[:0] = [str(c.ACCELERATE), str(c.DATASETS)]
        refused_imports, refused_events = guard.install_execution_fence(owners)
        fence_all()
        guard.store_witness()
        c.require(not Path(str(guard.STORE) + '.wal').exists(), 'active writer/WAL requires coordinated snapshot')
        import duckdb
        phase = 'fresh_complete_read_only_baseline'
        baseline, baseline_schema = guard.fresh_snapshot(duckdb)
        absent, present = guard.partition_records(native, full_plan, baseline)
        absent_ids = frozenset(item['model_metadata']['model_id'] for item in absent)
        before_pin = c.write(out / 'before-records.json', baseline)
        schema_pin = c.write(out / 'before-schema.json', baseline_schema)
        queries = []
        ModelManager = None
        if absent:
            phase = 'coherent_original_store_backup'
            original_store, backup_pin, backup_stat = guard.backup_database(out)
            repeated, repeated_schema = guard.fresh_snapshot(duckdb)
            c.require(c.wire(repeated) == c.wire(baseline) and c.wire(repeated_schema) == c.wire(baseline_schema),
                'full baseline changed during backup')
            repeated_absent, _ = guard.partition_records(native, full_plan, repeated)
            c.require({r['model_metadata']['model_id'] for r in repeated_absent} == set(absent_ids),
                'missing target population changed before construction')
            fence_all()
            c.require(guard.store_witness() == guard.witness(backup_stat)
                and not Path(str(guard.STORE) + '.wal').exists(), 'store changed before constructor')
            ModelManager = guard.genuine_manager_class()
            guard.loaded_owner_origins(owners)
            def make_manager(ids):
                nonlocal mutation_possible
                mutation_possible = True
                candidate = guard.construct_owned_manager(ModelManager, native, baseline, ids)
                try:
                    guard.loaded_owner_origins(owners)
                    c.require(c.wire(guard.schema_snapshot(candidate.con)) == c.wire(baseline_schema),
                        'genuine constructor changed database schema')
                    return candidate
                except BaseException:
                    guard.empty_close(candidate)
                    raise
            def readback(model_id):
                # A fresh native connection can share the engine cache while writable
                # manager connection is open. Cold independent reads follow real close.
                rows, schema = guard.fresh_snapshot(duckdb, read_only=False)
                c.require(c.wire(schema) == c.wire(baseline_schema), 'schema changed during genuine import')
                matching = [r for r in rows if r['model_id'] == model_id]
                c.require(len(matching) <= 1, 'unique fresh native readback required')
                queries.append(dict(model_id=model_id, fresh_native_connection=True,
                    shared_engine_cache_possible=True, manager_models_not_used=True))
                return matching[0] if matching else None
            phase = 'genuine_absent_only_public_api_import'
            registration = guard.import_missing(native, full_plan, baseline,
                make_manager=make_manager, stage_plan=lambda p: c.write(out / 'missing-only-import-plan.json', p),
                readback=readback, releases=releases, max_reference_bytes=native.MAX_REFERENCE_BYTES)
        else:
            original_store, backup_pin = None, None
            def forbidden(*args):
                raise ValueError('all-present exact metadata must not construct or stage a manager')
            registration = guard.import_missing(native, full_plan, baseline, make_manager=forbidden,
                stage_plan=forbidden, readback=None, releases=releases, max_reference_bytes=native.MAX_REFERENCE_BYTES)
        phase = 'cold_complete_native_readback'
        rows, schema = guard.fresh_snapshot(duckdb)
        c.require(c.wire(schema) == c.wire(baseline_schema), 'schema differs after genuine close')
        guard.check_population(native, rows, baseline, full_plan)
        catalog = guard.exact_catalog(full_plan)
        genuine_catalog = None
        if absent:
            phase = 'cold_genuine_reload_empty_close'
            manager = guard.construct_owned_manager(ModelManager, native, rows, frozenset())
            guard.loaded_owner_origins(owners)
            c.require(c.wire(guard.schema_snapshot(manager.con)) == c.wire(baseline_schema), 'cold schema differs')
            genuine_catalog = guard.genuine_catalog_targets(manager,
                {r['model_metadata']['model_id'] for r in full_plan['models']})
            guard.empty_close(manager)
            manager = None
        phase = 'closing_complete_read_only_readback'
        final_rows, final_schema = guard.fresh_snapshot(duckdb)
        c.require(c.wire(final_schema) == c.wire(baseline_schema), 'final schema differs')
        guard.check_population(native, final_rows, baseline, full_plan)
        c.require(c.wire(final_rows) == c.wire(rows), 'empty-population cold close changed metadata or activity')
        final_catalog = guard.exact_catalog(full_plan)
        c.require(c.wire(catalog) == c.wire(final_catalog), 'catalog generation changed at closing endpoint')
        c.require(not Path(str(guard.STORE) + '.wal').exists(), 'closing WAL remains')
        fence_all()
        native._prepare(plan_pin, releases, native.MAX_REFERENCE_BYTES)
        final_pin = c.write(out / 'after-records.json', final_rows)
        return c.write(out / 'registration-result.json', dict(schema='dual-bank-model-manager-registration-result/v1',
            complete=True, preflight_pin=preflight_pin, review_pin=review_pin, selected_storage=str(guard.STORE),
            before_records_pin=before_pin, before_schema_pin=schema_pin, original_store_pin=original_store,
            backup_pin=backup_pin, after_records_pin=final_pin, before_count=len(baseline), after_count=len(final_rows),
            absent_ids=sorted(absent_ids), already_present_ids=sorted(r['model_metadata']['model_id'] for r in present),
            fitted_endpoint_binding_count=contract['fitted_count'], independent_training_run_count=contract['run_count'], registration=registration,
            persisted_native_queries=queries, cold_exact_catalog=final_catalog, cold_genuine_catalog=genuine_catalog,
            all_baseline_metadata_and_activity_exactly_preserved=True, schema_and_indexes_unchanged=True,
            genuine_save_population_absent_targets_only=True, genuine_close_save_population_always_empty=True,
            all_input_files_preserved=True, optional_import_refusals=refused_imports, execution_refusals=refused_events,
            active_other_manager_process_refreshed=False, model_numerically_loaded=False,
            training_executed=False, inference_executed=False, embeddings_generated=False,
            Hub_updated_by_registration=False, cooperative_endpoint_scope=True,
            source_scope='Pinned genuine manager/catalog/import source with optional heavy owners blocked; no full eager-import closure claim.',
            **c.AUTHORITY))
    except BaseException as error:
        c.write(out / 'failure.json', dict(phase=phase, failure_type=type(error).__name__,
            database_may_have_changed=mutation_possible, absent_ids=sorted(absent_ids),
            partial_native_outcomes=getattr(error, 'outcomes', []), no_automatic_retry_or_rollback=True))
        raise
    finally:
        guard.empty_close(manager)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan-preparation', required=True, help='absolute file path=SHA256')
    parser.add_argument('--output-directory', required=True, type=Path)
    parser.add_argument('--register', action='store_true')
    parser.add_argument('--review-receipt', help='absolute file path=SHA256')
    args = parser.parse_args()
    result = register_plan(c.argument_pin(args.plan_preparation), args.output_directory,
        register=args.register, review_pin=c.argument_pin(args.review_receipt) if args.review_receipt else None)
    print(c.wire(dict(complete=True, result_pin=result, registration_requested=args.register)))


if __name__ == '__main__':
    main()
