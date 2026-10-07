"""Offline controls: genuine metadata owners, real retained assets, inert Hub/manager doubles.

Inert API receipts and temporary import plans are fixtures, never actual Hub or
training results. No live store, numerical model, encoder, optimizer or network
is opened. Existing raw trained checkpoints are copied byte-exact for tests.
"""
import copy
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import unittest
import sys
from types import SimpleNamespace

import publication_common as c
import prepare_retained_parallel_release as retained
import publish_dual_bank_release as publisher
import register_dual_bank_release as register


class RetainedPublicationControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='.inert-publication-fixture-', dir=Path(__file__).parent)
        cls.root = Path(cls.temporary.name).resolve()
        cls.stage_pin = retained.stage_retained(cls.root / 'stage')
        cls.prep = c.document(cls.stage_pin)
        cls.authentication = c.document(cls.prep['authentication_pin'])
        cls.hub, _ = c.load_native('ir_model_hub_publish')
        cls.importer, _ = c.load_native('ir_model_manager_import')
        cls.guard, _, _ = c.load_guard()
        cls.receipt_pins, cls.snapshots, cls.plans = [], [], []
        for index, plan_pin in enumerate(cls.prep['plan_pins']):
            plan = cls.hub._capture_plan(c.document(plan_pin))
            rows = []
            for operation in plan['operations']:
                raw = c.read(operation['file_pin'])
                rows.append(dict(rfilename=operation['path_in_repo'], size=len(raw),
                    blob_id=hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()))
            revision = str(index + 1) * 40
            class InertApi:
                def model_info(self, repository, **kwargs):
                    return SimpleNamespace(sha=revision, private=False, siblings=rows, gated=False, disabled=False)
                def create_repo(self, *args, **kwargs):
                    raise AssertionError('inert fixture must never create repository')
                def create_commit(self, *args, **kwargs):
                    raise AssertionError('inert fixture must never mutate remote metadata')
            api = InertApi()
            snapshot = publisher.remote_snapshot(cls.hub, api, plan['repository_id'])
            adapter = publisher.ReadOnlyExistingApi(api, plan['repository_id'], revision)
            receipt = cls.hub.publish_ir_model_hub_release(plan, api=adapter)
            cls.receipt_pins.append(c.write(cls.root / ('INERT-API-receipt-' + str(index) + '.json'), receipt))
            cls.snapshots.append(snapshot)
            cls.plans.append(plan)
        cls.record_prep_pin = retained.build_retained_records(cls.stage_pin, cls.receipt_pins, cls.root / 'INERT-import-plan')
        cls.record_prep = c.document(cls.record_prep_pin)
        cls.plan = c.document(cls.record_prep['import_plan_pin'])

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_actual_inventory_has_nine_raw_six_fitted_three_tensors(self):
        self.assertEqual(len(self.authentication['states']), 9)
        self.assertEqual(len(self.plan['models']), 6)
        self.assertEqual(len({r['tensor_sha256'] for r in self.authentication['states'] if r['role'] != 'initial'}), 3)
        self.assertEqual(self.authentication['physical_evaluation_panels'], 24)

    def test_original_raw_bytes_and_headers_are_preserved(self):
        for plan in self.plans:
            for row in self.authentication['states']:
                local = next(op['file_pin'] for op in plan['operations']
                    if op['path_in_repo'] == c.RETAINED_PREFIX + '/' + row['release_relative_path'])
                self.assertEqual(c.read(local), c.read(row['original_checkpoint_pin']))

    def test_initials_are_trained_parent_copies_with_no_new_fit_or_registration(self):
        rows = [r for r in self.authentication['states'] if r['role'] == 'initial']
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r['tensor_sha256'] == c.PARENT_TENSOR_SHA
            and r['new_continuation_training_executed'] is False and r['original_parent_already_trained'] is True
            and r['continuation_training_ref'] is None for r in rows))
        self.assertTrue(all(r['model_metadata']['huggingface_config']['original_state_role'] != 'initial' for r in self.plan['models']))

    def test_actual_dispositions_do_not_claim_new_fresh_matched_gate(self):
        rows = {r['arm']: r for r in self.authentication['states'] if r['role'] == 'selected'}
        self.assertIsNone(rows['control-wording-ce']['numerical_retention_passed'])
        self.assertFalse(rows['balanced-wording-ce']['numerical_retention_passed'])
        self.assertEqual(len(rows['balanced-wording-ce']['previously_exact_paragraph_regressions']), 15)
        self.assertTrue(rows['dual-bank-retention-ce']['numerical_retention_passed'])
        self.assertEqual(len(rows['dual-bank-retention-ce']['previously_exact_paragraph_regressions']), 3)
        self.assertFalse(rows['dual-bank-retention-ce']['bank_mix_effect_causally_isolated'])

    def test_six_actual_report_recipe_role_codec_null_schema_joins(self):
        joins = register.authentication_join(self.plan, self.authentication)
        self.assertEqual(len(joins), 6)
        for record in self.plan['models']:
            config = record['model_metadata']['huggingface_config']
            identity = config['ir_checkpoint']
            self.assertEqual(identity['task_id'], 'semantic_IR_reconstruction')
            self.assertEqual(identity['dimension_role'], 'input_embedding')
            self.assertEqual(identity['dimension'], 384)
            self.assertIsNone(identity['schema_version'])
            self.assertIsNone(identity['profile_id'])
            self.assertIsNone(identity['format_id'])
            self.assertTrue(identity['trained'])
            self.assertFalse(identity['initialization_only'])
            self.assertTrue(all(config[key] is False for key in c.AUTHORITY))
            self.assertEqual(config['continuation_training_ref'], next(row['continuation_training_ref']
                for row in self.authentication['states'] if row['original_checkpoint_pin'] == record['checkpoint_pin']))

    def test_actual_native_prepare_accepts_inert_publication_fixture_only(self):
        plan, _, _, _ = self.importer._prepare(self.record_prep['import_plan_pin'], self.receipt_pins,
            self.importer.MAX_REFERENCE_BYTES)
        self.assertEqual(plan, self.plan)

    def test_new_task_or_recipe_rebinding_is_refused(self):
        for field, bad in (('training_run_id', 'wrong-run'), ('continuation_arm', 'wrong-arm'),
                ('original_state_role', 'initial'), ('ordered_codec_sha256', '0' * 64),
                ('continuation_training_ref', None), ('disposition', 'production')):
            with self.subTest(field=field):
                plan = copy.deepcopy(self.plan)
                plan['models'][0]['model_metadata']['huggingface_config'][field] = bad
                with self.assertRaises(ValueError):
                    register.authentication_join(plan, self.authentication)

    def test_authority_or_native_schema_promotion_is_refused(self):
        for field, bad in (('runtime_ready', True), ('teacher_qualified', True), ('proof_authority', True),
                ('schema_version', 'guessed-v1'), ('profile_id', 'guessed-profile'), ('dimension', True)):
            with self.subTest(field=field):
                plan = copy.deepcopy(self.plan)
                plan['models'][0]['model_metadata']['huggingface_config']['ir_checkpoint'][field] = bad
                with self.assertRaises(ValueError):
                    register.authentication_join(plan, self.authentication)

    def test_exact_remote_prefix_reuses_existing_files(self):
        self.assertTrue(publisher.verify_prefix(self.hub, self.plans[0], {}, self.snapshots[0], prefix=c.RETAINED_PREFIX))

    def test_absent_remote_prefix_is_admissible_for_cooperative_cli_append(self):
        value = copy.deepcopy(self.snapshots[0]); value['file_identities'] = {}
        self.assertFalse(publisher.verify_prefix(self.hub, self.plans[0], {}, value, prefix=c.RETAINED_PREFIX))

    def test_partial_extra_or_conflicting_remote_prefix_is_refused(self):
        for kind in ('partial', 'extra', 'conflicting'):
            with self.subTest(kind=kind):
                value = copy.deepcopy(self.snapshots[0])
                if kind == 'partial':
                    value['file_identities'].pop(next(iter(value['file_identities'])))
                elif kind == 'extra':
                    value['file_identities'][c.RETAINED_PREFIX + '/unreviewed.json'] = dict(bytes=1, git_blob_oid='0' * 40)
                else:
                    value['file_identities'][next(iter(value['file_identities']))]['git_blob_oid'] = '0' * 40
                with self.assertRaises(ValueError):
                    publisher.verify_prefix(self.hub, self.plans[0], {}, value, prefix=c.RETAINED_PREFIX)

    def test_prior_remote_bytes_settings_and_addition_scope_are_preserved(self):
        value = copy.deepcopy(self.snapshots[0])
        publisher.check_preserved(value, copy.deepcopy(value), list(value['file_identities']))
        for kind in ('prior-file', 'private', 'unexpected-addition'):
            with self.subTest(kind=kind):
                after = copy.deepcopy(value)
                if kind == 'prior-file':
                    after['file_identities'][next(iter(after['file_identities']))]['bytes'] += 1
                elif kind == 'private':
                    after['settings']['private'] = True
                else:
                    after['file_identities']['root-unreviewed.json'] = dict(bytes=1, git_blob_oid='0' * 40)
                with self.assertRaises(ValueError):
                    publisher.check_preserved(value, after, list(value['file_identities']))

    def test_native_verifier_exposes_no_mutation_or_other_repository(self):
        adapter = publisher.ReadOnlyExistingApi(object(), c.REPOSITORIES[0], '1' * 40)
        for call in (lambda: adapter.create_repo('x'), lambda: adapter.create_commit('x'),
                lambda: adapter.model_info('other/repository'),
                lambda: adapter.model_info(c.REPOSITORIES[0], revision='main')):
            with self.assertRaises(ValueError):
                call()

    def test_upload_revision_parser_refuses_mutable_or_wrong_repository_urls(self):
        repo = c.REPOSITORIES[0]
        self.assertEqual(publisher.published_revision('https://huggingface.co/' + repo + '/commit/' + 'a' * 40, repo), 'a' * 40)
        for url in ('https://huggingface.co/' + repo + '/tree/main',
                'https://huggingface.co/other/repository/commit/' + 'a' * 40):
            with self.assertRaises(ValueError):
                publisher.published_revision(url, repo)

    def test_all_present_exact_records_never_construct_or_write_manager(self):
        baseline = [r['model_metadata'] for r in self.plan['models']]
        def forbidden(*args):
            raise AssertionError('no manager or plan staging allowed')
        result = self.guard.import_missing(self.importer, self.plan, baseline, make_manager=forbidden,
            stage_plan=forbidden, readback=None, releases=self.receipt_pins, max_reference_bytes=self.importer.MAX_REFERENCE_BYTES)
        self.assertEqual(result['missing_count'], 0)
        self.assertEqual(result['already_present_count'], 6)
        self.assertFalse(result['manager_constructed'])

    def test_same_model_id_with_conflicting_metadata_is_refused_before_factory(self):
        baseline = [copy.deepcopy(self.plan['models'][0]['model_metadata'])]
        baseline[0]['huggingface_config']['recipe']['weight'] = .75
        with self.assertRaises(ValueError):
            self.guard.partition_records(self.importer, self.plan, baseline)

    def test_instance_save_guard_and_empty_close_keep_foreign_rows_out(self):
        saves = []
        manager = SimpleNamespace(models={'target': object()}, _model_lock=threading.RLock(), con=None)
        manager._save_data = lambda: saves.append(set(manager.models))
        manager.close = lambda: manager._save_data()
        self.guard.guard_save_population(manager, {'target'})
        manager._save_data()
        manager.models['foreign'] = object()
        with self.assertRaises(ValueError):
            manager._save_data()
        self.guard.empty_close(manager)
        self.assertEqual(saves, [{'target'}, set()])

    def test_closed_stage_rejects_unreviewed_files_or_symlinks(self):
        root = self.root / 'closed-inventory-fixture'; root.mkdir()
        c.write_raw(root / 'reviewed.json', b'{}\n')
        c.exact_stage_files(root, {'reviewed.json'})
        c.write_raw(root / 'extra.json', b'{}\n')
        with self.assertRaises(ValueError):
            c.exact_stage_files(root, {'reviewed.json'})
        (root / 'extra.json').unlink()
        (root / 'alias').symlink_to(root / 'reviewed.json')
        with self.assertRaises(ValueError):
            c.exact_stage_files(root, {'reviewed.json'})

    def test_historical_hard_link_custody_does_not_relax_checkpoint_custody(self):
        path = self.root / 'hard-linked-source-fixture.py'
        c.write_raw(path, b'pass\n')
        os.link(path, self.root / 'historical-alias.py')
        observed = c.capture_historical_source(path)
        self.assertEqual(observed['sha256'], hashlib.sha256(b'pass\n').hexdigest())
        c.historical_source_fence([observed])
        with self.assertRaises(ValueError):
            c.capture(path)

    def test_duplicate_nonfinite_or_unknown_inventory_is_refused(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}'):
            with self.assertRaises(ValueError):
                c.decode(raw)
        with self.assertRaises(ValueError):
            c.inventory_contract('invented-schema/v1')

    def test_offline_fixture_campaign_has_no_heavy_or_live_store_owner(self):
        self.assertFalse({'torch', 'numpy', 'transformers', 'sentence_transformers',
            'huggingface_hub', 'duckdb', 'sqlite3', 'ipfs_accelerate_py.model_manager'} & set(sys.modules))


if __name__ == '__main__':
    unittest.main()
