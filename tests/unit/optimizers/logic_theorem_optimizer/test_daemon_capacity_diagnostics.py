"""Stdlib-only synthetic tests; never import a resource owner or acquire work.

Only the actual error class, _account method, stderr formatter and owner.open
exception handler ASTs execute. Inventory/free-space observations are invented;
no ledger, scheduler, corpus, process group or resource reservation is opened.
"""
from __future__ import annotations

import ast
import copy
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[4]
OWNER = ROOT / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py'
LAUNCHER = ROOT / 'scripts/ops/legal_ir/run_owned_validation.py'


def source_tree(path):
    with path.open('rb') as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('bounded control source required')
    return ast.parse(raw, filename=str(path))


class CapacityDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        owner = source_tree(OWNER)
        launcher = source_tree(LAUNCHER)
        error = next(n for n in owner.body if isinstance(n, ast.ClassDef) and n.name == 'DaemonResourceError')
        reservation = next(n for n in owner.body if isinstance(n, ast.ClassDef) and n.name == 'DaemonResourceReservation')
        account = next(n for n in reservation.body if isinstance(n, ast.FunctionDef) and n.name == '_account')
        cap = next(n.value for n in owner.body if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == 'MAX_STORAGE_BYTES' for t in n.targets))
        cls.cap = ast.literal_eval(cap)
        namespace = {'copy': copy, 'MAX_STORAGE_BYTES': cls.cap}
        detached = ast.fix_missing_locations(ast.Module(body=[error, account], type_ignores=[]))
        exec(compile(detached, str(OWNER), 'exec', dont_inherit=True), namespace)
        cls.error_type = namespace['DaemonResourceError']
        cls.account = staticmethod(namespace['_account'])
        cls.account_globals = namespace
        cls.formatter_node = next(n for n in launcher.body
            if isinstance(n, ast.FunctionDef) and n.name == 'report_capacity_refusal')
        main = next(n for n in launcher.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        cls.open_handler = next(n for n in ast.walk(main) if isinstance(n, ast.Try)
            and len(n.body) == 1 and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Call)
            and ast.unparse(n.body[0].value.func) == 'owner.open')

    def observe(self, observed, outstanding, additional, free):
        calls = {'inventory': 0, 'disk': 0, 'roots': 0}
        inventory = {'apparent_bytes': observed, 'private_paths': ['not-public'], 'owner_pid': 999999}
        def invented_inventory(roots):
            self.assertEqual(roots, ('invented-root',))
            calls['inventory'] += 1
            return inventory
        def invented_free(root):
            self.assertEqual(root, 'invented-root')
            calls['disk'] += 1
            return SimpleNamespace(free=free)
        self.account_globals['_inventory'] = invented_inventory
        self.account_globals['shutil'] = SimpleNamespace(disk_usage=invented_free)
        subject = SimpleNamespace(roots=('invented-root',),
            _verify_owner_roots=lambda: calls.__setitem__('roots', calls['roots'] + 1))
        ledger = {'reservations': {'private-row': {'status': 'retained', 'storage_bytes': outstanding},
            'already-released': {'status': 'released', 'storage_bytes': self.cap}}}
        try:
            result = self.account(subject, ledger, additional=additional)
        except self.error_type as error:
            result = error
        self.assertEqual((calls['inventory'], calls['disk']), (1, 1))
        self.assertEqual(calls['roots'], 0 if isinstance(result, Exception) else 1)
        return result, inventory

    def failure(self, observed, outstanding=80, additional=30, free=1000):
        error, inventory = self.observe(observed, outstanding, additional, free)
        self.assertIs(type(error), self.error_type)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(str(error), 'storage reservation capacity exceeded')
        self.assertEqual(error.args, ('storage reservation capacity exceeded',))
        return error, inventory

    def formatter(self, sink=None):
        sink = io.StringIO() if sink is None else sink
        namespace = {'json': json, 'sys': SimpleNamespace(stderr=sink)}
        module = ast.fix_missing_locations(ast.Module(body=[self.formatter_node], type_ignores=[]))
        exec(compile(module, str(LAUNCHER), 'exec', dont_inherit=True), namespace)
        return namespace['report_capacity_refusal'], sink

    def test_cap_constant_is_unchanged(self):
        self.assertEqual(self.cap, 220_000_000_000)

    def test_global_only_refusal(self):
        error, _ = self.failure(self.cap - 100)
        d = error.capacity_observation
        self.assertTrue(d['storage_capacity_exceeded'])
        self.assertFalse(d['filesystem_free_insufficient'])
        self.assertEqual((d['storage_capacity_deficit_bytes'], d['filesystem_free_deficit_bytes']), (10, 0))

    def test_physical_only_refusal(self):
        error, _ = self.failure(100, free=100)
        d = error.capacity_observation
        self.assertFalse(d['storage_capacity_exceeded'])
        self.assertTrue(d['filesystem_free_insufficient'])
        self.assertEqual((d['storage_capacity_deficit_bytes'], d['filesystem_free_deficit_bytes']), (0, 10))

    def test_both_refusal_conditions(self):
        error, _ = self.failure(self.cap - 100, free=100)
        d = error.capacity_observation
        self.assertTrue(d['storage_capacity_exceeded'])
        self.assertTrue(d['filesystem_free_insufficient'])
        self.assertEqual((d['storage_capacity_deficit_bytes'], d['filesystem_free_deficit_bytes']), (10, 10))

    def test_equality_at_both_boundaries_still_passes(self):
        result, inventory = self.observe(self.cap - 100, 80, 20, 100)
        self.assertEqual(result['charged_bytes'], self.cap)
        self.assertEqual(result['minimum_filesystem_free_bytes'], 100)
        self.assertIs(result['inventory'], inventory)

    def test_physical_equality_with_global_headroom_still_passes(self):
        result, _ = self.observe(100, 80, 20, 100)
        self.assertEqual(result['charged_bytes'], 200)

    def test_released_claim_is_excluded_and_full_retained_claim_is_charged(self):
        result, _ = self.observe(0, 80, 0, 80)
        self.assertEqual(result['outstanding_full_reservations_bytes'], 80)
        self.assertEqual(result['additional_requested_bytes'], 0)

    def test_snapshot_access_is_detached_and_contains_no_inventory(self):
        error, inventory = self.failure(self.cap - 100)
        first = error.capacity_observation
        first['observed_apparent_bytes'] = 0
        inventory['private_paths'].append('another-private-path')
        self.assertEqual(error.capacity_observation['observed_apparent_bytes'], self.cap - 100)
        encoded = json.dumps(error.capacity_observation)
        for private in ('inventory', 'private_paths', 'owner_pid', 'private-row', 'not-public'):
            self.assertNotIn(private, encoded)

    def test_other_errors_have_no_capacity_snapshot(self):
        self.assertIsNone(self.error_type('different refusal').capacity_observation)

    def test_stderr_is_bounded_exact_aggregate_json(self):
        error, _ = self.failure(self.cap - 100)
        formatter, sink = self.formatter()
        self.assertTrue(formatter(error))
        raw = sink.getvalue()
        self.assertLessEqual(len(raw.encode()), 4096)
        self.assertEqual(len(raw.splitlines()), 1)
        result = json.loads(raw)
        self.assertEqual(set(result), {'schema', 'stage', 'error_type', 'error', 'observation'})
        self.assertEqual(result['schema'], 'owned-validation-capacity-refusal/v1')
        self.assertEqual(result['stage'], 'owner.open')
        self.assertEqual(result['observation'], error.capacity_observation)

    def test_missing_or_extra_fields_are_not_published(self):
        formatter, sink = self.formatter()
        error, _ = self.failure(self.cap - 100)
        for change in ('missing', 'extra'):
            with self.subTest(change=change):
                data = error.capacity_observation
                if change == 'missing':
                    data.pop('limit_bytes')
                else:
                    data['foreign_record'] = {'owner_pid': 123}
                error._capacity_observation = data
                self.assertFalse(formatter(error))
                self.assertEqual(sink.getvalue(), '')
                error, _ = self.failure(self.cap - 100)

    def test_invalid_scalar_bool_or_inconsistent_deficit_is_not_published(self):
        formatter, sink = self.formatter()
        for field, bad in [('charged_bytes', True), ('limit_bytes', 2**63),
                ('storage_capacity_exceeded', 1), ('storage_capacity_deficit_bytes', 0)]:
            with self.subTest(field=field):
                error, _ = self.failure(self.cap - 100)
                error._capacity_observation[field] = bad
                self.assertFalse(formatter(error))
                self.assertEqual(sink.getvalue(), '')

    def test_noncapacity_message_is_not_relabelled(self):
        error, _ = self.failure(self.cap - 100)
        other = self.error_type('different refusal')
        other._capacity_observation = error.capacity_observation
        formatter, sink = self.formatter()
        self.assertFalse(formatter(other))
        self.assertEqual(sink.getvalue(), '')

    def test_stderr_failure_does_not_replace_original_exception(self):
        class Unavailable:
            def write(self, raw):
                raise OSError('invented unavailable stderr')
        error, _ = self.failure(self.cap - 100)
        formatter, _ = self.formatter(Unavailable())
        self.assertFalse(formatter(error))
        self.assertEqual(str(error), 'storage reservation capacity exceeded')

    def test_actual_launcher_handler_reraises_identical_error_once(self):
        error, _ = self.failure(self.cap - 100)
        calls = []
        def invented_open():
            calls.append('open')
            raise error
        formatter, sink = self.formatter()
        function = ast.FunctionDef(name='detached_open_handler',
            args=ast.arguments(posonlyargs=[], args=[], vararg=None, kwonlyargs=[],
                kw_defaults=[], kwarg=None, defaults=[]),
            body=[self.open_handler], decorator_list=[], returns=None,
            type_comment=None, type_params=[])
        module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
        namespace = {'owner': SimpleNamespace(open=invented_open),
            'host': SimpleNamespace(DaemonResourceError=self.error_type),
            'report_capacity_refusal': formatter}
        exec(compile(module, str(LAUNCHER), 'exec', dont_inherit=True), namespace)
        with self.assertRaises(self.error_type) as caught:
            namespace['detached_open_handler']()
        self.assertIs(caught.exception, error)
        self.assertEqual(calls, ['open'])
        self.assertEqual(json.loads(sink.getvalue())['observation'], error.capacity_observation)


if __name__ == '__main__':
    unittest.main()
