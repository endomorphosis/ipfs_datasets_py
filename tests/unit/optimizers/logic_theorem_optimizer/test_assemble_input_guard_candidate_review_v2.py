"""CG5 successor controls joining current-audit and document-authority scope.

Temporary fixtures are fictional audit records, never native evidence. Only
the historical production row bytes are copied. No model, producer, scheduler
or tensor library executes. Root owns execution of these portable controls.
"""
import base64
import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

WORKSPACE = Path(__file__).absolute().parents[6]
SOURCE = WORKSPACE / 'artifacts/codebase_ir_terminal_bench/assemble_input_guard_candidate_review_20261004_v2.py'
SOURCE_SHA = '56fad9e7157e999b5281d55fb254e2552978d8b1ff3a38d6f4fc938db0c008f6'
TABLE = 'external/ipfs_accelerate/docs/architecture/repository_proof_index_and_codebase_ir.todo.md'


def load_current():
    before = SOURCE.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= 1024**2:
        raise ValueError('bounded current assembler source required')
    descriptor = os.open(SOURCE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(1024**2 + 1)
        final = os.fstat(stream.fileno())
    after = SOURCE.lstat()
    identities = [(value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
                   value.st_size, value.st_mtime_ns, value.st_ctime_ns)
                  for value in (before, opened, final, after)]
    if any(identity != identities[0] for identity in identities[1:]) or hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise ValueError('current assembler source changed')
    specification = importlib.util.spec_from_file_location('_authored_input_guard_assembler_v2', SOURCE)
    module = importlib.util.module_from_spec(specification)
    exec(compile(raw, str(SOURCE), 'exec'), module.__dict__)
    if SOURCE.read_bytes() != raw:
        raise ValueError('current assembler source changed during import')
    return module


class OrdinaryInputGuardAssemblyControlsV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assembler = load_current()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.base = self.root / 'artifacts'
        self.base.mkdir()
        root_patch = patch.object(self.assembler, 'ROOT', self.root)
        base_patch = patch.object(self.assembler, 'BASE', self.base)
        root_patch.start()
        base_patch.start()
        self.addCleanup(root_patch.stop)
        self.addCleanup(base_patch.stop)
        self.addCleanup(self.temporary.cleanup)

    def write(self, relative, value=None, *, raw=None):
        data = self.assembler.wire(value) if raw is None else raw
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        path.write_bytes(data)
        path.chmod(0o444)
        return {'path': relative, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

    def value(self, pin):
        return self.assembler.strict_json(self.assembler.checked(pin))

    def replace_pin(self, selection, old, new):
        selection['files'] = [new if pin == old else pin for pin in selection['files']]
        for key in ('review', 'report', 'plan', 'resource_observation'):
            if selection[key] == old:
                selection[key] = new
        for key in ('controls', 'audits', 'results'):
            selection[key] = [new if pin == old else pin for pin in selection[key]]

    def repin_document(self, selection, pin, value):
        new = self.write(pin['path'], value)
        self.replace_pin(selection, pin, new)
        return new

    def selection(self):
        snapshot = {'allocated': {'cpu_slots': 0, 'memory_mb': 0}, **{name: 0 for name in (
            'active_lease_count', 'active_child_lease_count', 'active_root_lease_count',
            'allocated_gpu_memory_mb', 'allocated_unified_memory_mb',
            'allocated_child_process_slots', 'waiting_request_count')}}
        common = {'diagnostic_only': True, 'performance_qualified': False,
            'selected_existing_profile_changed': False, 'current_passing_test_cases': 7,
            'production_qualified': False, 'proof_authority': False, 'execution_attestation': False}
        pins = {'review': self.write('review.json', {**common,
            'schema': self.assembler.DOCUMENT_SCHEMAS['review'],
            'native_leanstral_outputs_qualified': False, 'trained4096_qualification_established': False,
            'span_candidate_native_cuda_qualification': False}),
            'report': self.write('report.md', raw=b'Ordinary fixture [source](source.py).\n'),
            'plan': self.write('plan.json', {**common,
                'schema': self.assembler.DOCUMENT_SCHEMAS['plan'], 'fictional_fixture': True}),
            'resource_observation': self.write('resources.json', {'resources_after': snapshot})}
        source = self.write('source.py', raw=b'# Inert bytes; never execute this retained fixture.\n')
        controls = [self.write(f'controls-{index}.json', {'qualified': True, 'tests': number,
            'errors': 0, 'failures': 0, 'skipped': 0, 'fixture_id': index})
                    for index, number in enumerate((2, 5))]
        results, audits = [], []
        for index in range(2):
            result = self.write(f'archive-{index}/result.json', {'schema': self.assembler.RESULT_SCHEMA,
                'qualified': True, 'error': None, 'selected_existing_profile_changed': False, 'fixture_id': index})
            panel = self.write(f'archive-{index}/panel.json', {'fictional_inert_data': index})
            retained = [self.assembler.absolute_pin(result), self.assembler.absolute_pin(panel)]
            audit = self.write(f'audit-{index}/audit.json', {'schema': self.assembler.AUDIT_SCHEMA,
                'qualified': True, 'closed_artifacts_consistent': True, 'error': None,
                'result_pin': self.assembler.absolute_pin(result), 'expected_result_sha256': result['sha256'],
                'retained_pins': retained, 'bounded_archive_files': 2,
                'bounded_archive_bytes': sum(pin['bytes'] for pin in retained), 'fictional_fixture': True,
                'check_current_sources': True, 'current_sources_verified': True,
                'current_source_pins': [self.assembler.absolute_pin(source)],
                'fixture_id': index, 'execution_attestation': False})
            results.append(result)
            audits.append(audit)
        value = {'schema': self.assembler.SELECTION_SCHEMA, **pins, 'controls': controls,
            'files': [*pins.values(), source, *controls, *audits, *results],
            'directories': {'native_a': 'archive-0', 'native_b': 'archive-1',
                            'audit_a': 'audit-0', 'audit_b': 'audit-1'},
            'audits': audits, 'results': results, 'production_table_path': TABLE}
        return value

    def run_selection(self, selection, namespace='authored-closure'):
        pin = self.write('selection.json', selection)
        return self.assembler.run(self.root / pin['path'], pin['sha256'], namespace)

    def copy_production_rows(self):
        rows = b''.join(line for line in (WORKSPACE / TABLE).read_bytes().splitlines(keepends=True)
                        if line.startswith(b'| RPI-'))
        self.assertEqual(len(rows), 19064)
        self.assertEqual(hashlib.sha256(rows).hexdigest(), self.assembler.ROW_SHA)
        self.write(TABLE, raw=rows)

    def test_positive_complete_joins_counts_and_cid_scope(self):
        selection = self.selection()
        self.copy_production_rows()
        closure = self.value(self.run_selection(selection))
        self.assertEqual(closure['schema'], 'input-guard-candidate-ordinary-review-closure/v1')
        self.assertEqual(closure['current_passing_test_cases'], 7)
        self.assertEqual(len(closure['audit_result_joins']), 2)
        self.assertEqual(closure['directory_manifest_count'], 4)
        self.assertEqual(closure['member_count'], 6)
        self.assertEqual(closure['production_acceptance_rows_closed'], 0)
        for name in ('proof_authority', 'performance_qualified', 'production_qualified', 'execution_attestation',
                     'ipfs_publication_performed', 'scheduler_or_model_executed_by_assembler',
                     'selected_existing_profile_changed'):
            self.assertIs(closure[name], False)
        self.assertEqual(closure['resolved_report_links'], [selection['files'][4]])
        descriptor = closure['directory_manifests']['native_a']
        raw = self.assembler.checked(descriptor['manifest'])
        self.assertEqual(raw, self.assembler.wire(self.assembler.manifest('archive-0')))
        cid = descriptor['cidv1_dag_json']
        self.assertEqual(cid[0], 'b')
        payload = base64.b32decode(cid[1:].upper() + '=' * (-len(cid[1:]) % 8))
        self.assertEqual(payload[:5], bytes((1, 0xa9, 2, 0x12, 0x20)))
        self.assertEqual(payload[5:], hashlib.sha256(raw).digest())

    def test_wire_is_canonical_sorted_ascii_and_preserves_zero_sign(self):
        self.assertEqual(self.assembler.wire({'z': -0.0, 'a': '§'}), b'{"a":"\\u00a7","z":-0.0}')
        self.assertEqual(self.assembler.wire({'b': 2, 'a': 1}), self.assembler.wire({'a': 1, 'b': 2}))
        with self.assertRaises(ValueError):
            self.assembler.wire({'value': float('nan')})

    def test_json_duplicate_constants_and_overflow_exponents_refuse(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":1e999}', b'{"x":-1e999}', b'{"x":NaN}', b'{"x":Infinity}'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    self.assembler.strict_json(raw)

    def test_control_counts_require_plain_positive_ints_and_plain_zero_results(self):
        for key, aliases in (('tests', (True, 2.0, 0, -1)), ('errors', (False, 0.0, 1)),
                             ('failures', (False, 0.0, 1)), ('skipped', (False, 0.0, 1))):
            for alias in aliases:
                with self.subTest(key=key, alias=alias):
                    selection = self.selection()
                    old = selection['controls'][0]
                    value = self.value(old)
                    value[key] = alias
                    self.repin_document(selection, old, value)
                    with self.assertRaisesRegex(ValueError, 'passing current controls'):
                        self.run_selection(selection)

    def test_control_qualified_boolean_alias_and_duplicate_receipts_refuse(self):
        selection = self.selection()
        old = selection['controls'][0]
        value = self.value(old)
        value['qualified'] = 1
        self.repin_document(selection, old, value)
        with self.assertRaisesRegex(ValueError, 'passing current controls'):
            self.run_selection(selection)
        selection = self.selection()
        selection['controls'] = [selection['controls'][0]] * 2
        with self.assertRaisesRegex(ValueError, 'duplicate current control pin'):
            self.run_selection(selection)
        selection = self.selection()
        old = selection['controls'][1]
        cloned = self.write(old['path'], raw=self.assembler.checked(selection['controls'][0]))
        self.replace_pin(selection, old, cloned)
        with self.assertRaisesRegex(ValueError, 'duplicate current control pin'):
            self.run_selection(selection)

    def test_review_count_and_scope_require_exact_values(self):
        for key, aliases in (('current_passing_test_cases', (True, 7.0, 8)),
                             ('diagnostic_only', (1, False)), ('performance_qualified', (0, True)),
                             ('selected_existing_profile_changed', (0, True))):
            for alias in aliases:
                with self.subTest(key=key, alias=alias):
                    selection = self.selection()
                    old = selection['review']
                    value = self.value(old)
                    value[key] = alias
                    self.repin_document(selection, old, value)
                    with self.assertRaisesRegex(ValueError, 'diagnostic document scope'):
                        self.run_selection(selection)

    def test_resource_allocation_and_lease_zeros_require_plain_ints(self):
        fields = ('active_lease_count', 'active_child_lease_count', 'active_root_lease_count',
                  'allocated_gpu_memory_mb', 'allocated_unified_memory_mb',
                  'allocated_child_process_slots', 'waiting_request_count', 'cpu_slots', 'memory_mb')
        for field in fields:
            for alias in (False, 0.0, 1):
                with self.subTest(field=field, alias=alias):
                    selection = self.selection()
                    old = selection['resource_observation']
                    value = self.value(old)
                    target = value['resources_after']['allocated'] if field in ('cpu_slots', 'memory_mb') else value['resources_after']
                    target[field] = alias
                    self.repin_document(selection, old, value)
                    with self.assertRaisesRegex(ValueError, 'closed resource observation'):
                        self.run_selection(selection)

    def test_exact_two_distinct_audits_and_results_required(self):
        for key in ('audits', 'results'):
            for size in (0, 1, 3):
                with self.subTest(key=key, size=size):
                    selection = self.selection()
                    selection[key] = [selection[key][0]] * size
                    with self.assertRaisesRegex(ValueError, 'two distinct ordinary audits/results'):
                        self.run_selection(selection)
            selection = self.selection()
            selection[key] = [selection[key][0]] * 2
            with self.assertRaisesRegex(ValueError, 'two distinct ordinary audits/results'):
                self.run_selection(selection)

    def test_audit_positive_booleans_error_and_schema_must_match(self):
        for key, replacement in (('qualified', 1), ('closed_artifacts_consistent', 1),
                                 ('error', {}), ('schema', 'wrong/v1')):
            with self.subTest(key=key):
                selection = self.selection()
                old = selection['audits'][0]
                value = self.value(old)
                value[key] = replacement
                self.repin_document(selection, old, value)
                with self.assertRaisesRegex(ValueError, 'closed candidate ordinary audit'):
                    self.run_selection(selection)

    def test_result_positive_scope_schema_and_basename_are_exact(self):
        for key, replacement in (('schema', 'wrong/v1'), ('qualified', 1),
                                 ('error', {}), ('selected_existing_profile_changed', 0)):
            with self.subTest(key=key):
                selection = self.selection()
                old = selection['results'][0]
                value = self.value(old)
                value[key] = replacement
                self.repin_document(selection, old, value)
                with self.assertRaisesRegex(ValueError, 'positive source-scoped formula candidate result'):
                    self.run_selection(selection)
        selection = self.selection()
        old = selection['results'][0]
        new = self.write('archive-0/other.json', raw=self.assembler.checked(old))
        self.replace_pin(selection, old, new)
        with self.assertRaisesRegex(ValueError, 'exact external result.json'):
            self.run_selection(selection)

    def test_audit_result_path_bytes_sha_and_external_digest_join(self):
        for key, replacement in (('path', str(self.root / 'archive-1/result.json')),
                                 ('bytes', 1), ('sha256', '0' * 64)):
            with self.subTest(key=key):
                selection = self.selection()
                old = selection['audits'][0]
                value = self.value(old)
                value['result_pin'][key] = replacement
                self.repin_document(selection, old, value)
                with self.assertRaisesRegex(ValueError, 'audit result path/bytes/SHA join differs'):
                    self.run_selection(selection)
        selection = self.selection()
        old = selection['audits'][0]
        value = self.value(old)
        value['expected_result_sha256'] = selection['results'][1]['sha256']
        self.repin_document(selection, old, value)
        with self.assertRaisesRegex(ValueError, 'audit result path/bytes/SHA join differs'):
            self.run_selection(selection)

    def test_audits_cannot_both_reuse_one_result(self):
        selection = self.selection()
        old = selection['audits'][1]
        value = self.value(old)
        first = self.value(selection['audits'][0])
        value.update({key: copy.deepcopy(first[key]) for key in ('expected_result_sha256', 'result_pin',
                     'retained_pins', 'bounded_archive_files', 'bounded_archive_bytes')})
        self.repin_document(selection, old, value)
        with self.assertRaisesRegex(ValueError, 'audit external result SHA join differs'):
            self.run_selection(selection)

    def test_retained_inventory_needs_one_result_and_plain_correct_counts(self):
        for mutation in ('duplicate', 'missing', 'files_bool', 'bytes_bool', 'bytes_wrong', 'outside'):
            with self.subTest(mutation=mutation):
                selection = self.selection()
                old = selection['audits'][0]
                value = self.value(old)
                if mutation == 'duplicate':
                    value['retained_pins'].append(value['retained_pins'][0])
                elif mutation == 'missing':
                    value['retained_pins'].pop(0)
                elif mutation == 'outside':
                    value['retained_pins'][1]['path'] = str(self.root / 'source.py')
                else:
                    value['bounded_archive_files' if mutation == 'files_bool' else 'bounded_archive_bytes'] = (
                        False if mutation.endswith('bool') else 1)
                self.repin_document(selection, old, value)
                with self.assertRaises(ValueError):
                    self.run_selection(selection)

    def test_retained_inventory_hash_tampering_refused_by_manifest_join(self):
        selection = self.selection()
        old = selection['audits'][0]
        value = self.value(old)
        value['retained_pins'][1]['sha256'] = '0' * 64
        self.repin_document(selection, old, value)
        self.copy_production_rows()
        with self.assertRaisesRegex(ValueError, 'audit retained pins differ from archive manifest'):
            self.run_selection(selection)

    def test_unmanifested_native_leaf_refused_by_audit_inventory_join(self):
        selection = self.selection()
        self.write('archive-0/extra.json', {'unjoined': True})
        self.copy_production_rows()
        with self.assertRaisesRegex(ValueError, 'audit retained pins differ from archive manifest'):
            self.run_selection(selection)

    def test_selected_pins_require_plain_bytes_and_canonical_paths(self):
        pin = self.write('ordinary.json', {'value': 1})
        for path in ('../ordinary.json', './ordinary.json', '/ordinary.json', 'x//ordinary.json'):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    self.assembler.pin_shape({**pin, 'path': path})
        for value in (True, 1.0, 0):
            with self.subTest(bytes=value):
                with self.assertRaises(ValueError):
                    self.assembler.pin_shape({**pin, 'bytes': value})

    def test_selected_files_and_namespace_bounds_refuse(self):
        selection = self.selection()
        selection['files'].append(selection['files'][0])
        with self.assertRaisesRegex(ValueError, 'duplicate selected file path'):
            self.run_selection(selection)
        selection = self.selection()
        selection['directories']['duplicate'] = selection['directories']['native_a']
        with self.assertRaisesRegex(ValueError, 'unique simple manifest'):
            self.run_selection(selection)
        selection = self.selection()
        selection['directories']['parent'] = '.'
        with self.assertRaisesRegex(ValueError, 'overlapping manifest'):
            self.run_selection(selection)
        selection = self.selection()
        with patch.object(self.assembler, 'MAX_SELECTED_FILES', 2):
            with self.assertRaisesRegex(ValueError, 'bounded review inputs'):
                self.run_selection(selection)
        with patch.object(self.assembler, 'MAX_SELECTED_DIRECTORIES', 1):
            with self.assertRaisesRegex(ValueError, 'bounded manifest selection'):
                self.run_selection(selection)

    def test_external_selection_sha_and_declared_file_bytes_are_checked(self):
        selection = self.selection()
        pin = self.write('selection.json', selection)
        with self.assertRaisesRegex(ValueError, 'external review selection pin differs'):
            self.assembler.run(self.root / pin['path'], '0' * 64, 'unused')
        source = self.root / 'source.py'
        source.unlink()
        self.write('source.py', raw=b'# changed inert bytes\n')
        with self.assertRaisesRegex(ValueError, 'declared bytes differ'):
            self.run_selection(selection)

    def test_manifest_file_byte_and_directory_limits_are_enforced(self):
        self.write('bounded/one.json', {'value': 1})
        self.write('bounded/two.json', {'value': 2})
        with patch.object(self.assembler, 'MAX_FILES', 1):
            with self.assertRaisesRegex(ValueError, 'manifest file budget'):
                self.assembler.manifest('bounded')
        with patch.object(self.assembler, 'MAX_TOTAL_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'manifest byte budget'):
                self.assembler.manifest('bounded')
        for index in range(3):
            (self.root / 'empty' / str(index)).mkdir(parents=True)
        with patch.object(self.assembler, 'MAX_MANIFEST_DIRECTORIES', 2):
            with self.assertRaisesRegex(ValueError, 'directory/depth budget'):
                self.assembler.manifest('empty')

    def test_symlink_hardlink_fifo_and_writable_leaves_refuse(self):
        pin = self.write('ordinary.json', {'value': 1})
        source, alias = self.root / pin['path'], self.root / 'alias.json'
        alias.symlink_to(source)
        with self.assertRaises((ValueError, OSError)):
            self.assembler.read('alias.json')
        alias.unlink()
        os.link(source, alias)
        with self.assertRaises(ValueError):
            self.assembler.read('ordinary.json')
        alias.unlink()
        source.chmod(0o644)
        with self.assertRaises(ValueError):
            self.assembler.read('ordinary.json')
        os.mkfifo(self.root / 'pipe.json')
        with self.assertRaises(ValueError):
            self.assembler.read('pipe.json')

    def test_parent_directory_substitution_during_read_refuses(self):
        self.write('parent/ordinary.json', {'value': 1})
        parent, calls = self.root / 'parent', 0
        actual = self.assembler.directory_fd
        def replace(path):
            nonlocal calls
            if Path(path) == parent:
                calls += 1
                if calls == 2:
                    parent.rename(self.root / 'old-parent')
                    parent.mkdir()
                    self.write('parent/ordinary.json', {'value': 1})
            return actual(path)
        with patch.object(self.assembler, 'directory_fd', replace):
            with self.assertRaisesRegex(ValueError, 'parent changed during read'):
                self.assembler.read('parent/ordinary.json')

    def test_report_links_require_selected_ordinary_targets(self):
        for destination in ('https://example.com/file', '../outside.json', 'missing.py'):
            with self.subTest(destination=destination):
                selection = self.selection()
                old = selection['report']
                new = self.write(old['path'], raw=f'[source]({destination})'.encode())
                self.replace_pin(selection, old, new)
                with self.assertRaises((ValueError, OSError)):
                    self.run_selection(selection)
        selection = self.selection()
        (self.root / 'alias.py').symlink_to(self.root / 'source.py')
        old = selection['report']
        new = self.write(old['path'], raw=b'[source](alias.py)')
        self.replace_pin(selection, old, new)
        with self.assertRaisesRegex(ValueError, 'link symlink refused'):
            self.run_selection(selection)

    def test_result_archive_must_be_selected_as_a_manifest_namespace(self):
        selection = self.selection()
        del selection['directories']['native_a']
        with self.assertRaisesRegex(ValueError, 'external result archive omitted'):
            self.run_selection(selection)

    def test_production_acceptance_rows_remain_exact_and_unclosed(self):
        selection = self.selection()
        self.copy_production_rows()
        path = self.root / TABLE
        raw = path.read_bytes().replace(b'| RPI-', b'| XPI-', 1)
        self.write(TABLE, raw=raw)
        with self.assertRaisesRegex(ValueError, 'production acceptance rows changed'):
            self.run_selection(selection)

    def test_saved_output_must_match_intended_canonical_bytes(self):
        actual = self.assembler.read
        def substitute(relative, **kwargs):
            self.write(relative, raw=b'{"substituted":true}')
            return actual(relative, **kwargs)
        with patch.object(self.assembler, 'read', substitute):
            with self.assertRaisesRegex(ValueError, 'written closure differs'):
                self.assembler.save(self.base, 'inert.manifest.json', {'intended': True})


    def test_audits_require_actual_current_check_flags_and_nonempty_pins(self):
        changes = (('check_current_sources', False), ('check_current_sources', 1),
                   ('current_sources_verified', False), ('current_sources_verified', 1),
                   ('current_source_pins', []), ('current_source_pins', None))
        for key, replacement in changes:
            with self.subTest(key=key, replacement=replacement):
                selection = self.selection()
                old = selection['audits'][0]
                value = self.value(old)
                value[key] = replacement
                self.repin_document(selection, old, value)
                with self.assertRaisesRegex(ValueError, 'currently verified source audit'):
                    self.run_selection(selection)
        for key in ('check_current_sources', 'current_sources_verified', 'current_source_pins'):
            with self.subTest(missing=key):
                selection = self.selection()
                old = selection['audits'][0]
                value = self.value(old)
                del value[key]
                self.repin_document(selection, old, value)
                with self.assertRaisesRegex(ValueError, 'currently verified source audit'):
                    self.run_selection(selection)

    def test_current_source_pins_require_exact_shape_bounds_and_unique_paths(self):
        for mutation in ('duplicate', 'bytes_bool', 'sha_malformed', 'relative', 'outside', 'extra'):
            with self.subTest(mutation=mutation):
                selection = self.selection()
                old = selection['audits'][0]
                value = self.value(old)
                pin = value['current_source_pins'][0]
                if mutation == 'duplicate':
                    value['current_source_pins'].append(copy.deepcopy(pin))
                elif mutation == 'bytes_bool':
                    pin['bytes'] = True
                elif mutation == 'sha_malformed':
                    pin['sha256'] = 'not-a-sha256'
                elif mutation == 'relative':
                    pin['path'] = 'source.py'
                elif mutation == 'outside':
                    pin['path'] = str(self.root.parent / 'outside.py')
                else:
                    pin['unchecked'] = True
                self.repin_document(selection, old, value)
                with self.assertRaises(ValueError):
                    self.run_selection(selection)

    def test_review_and_plan_reject_forged_or_missing_authority_declarations(self):
        for role in ('review', 'plan'):
            for field in ('production_qualified', 'proof_authority', 'execution_attestation'):
                for replacement in (True, 'missing'):
                    with self.subTest(role=role, field=field, replacement=replacement):
                        selection = self.selection()
                        old = selection[role]
                        value = self.value(old)
                        if replacement == 'missing':
                            del value[field]
                        else:
                            value[field] = replacement
                        self.repin_document(selection, old, value)
                        with self.assertRaisesRegex(ValueError, 'diagnostic document scope'):
                            self.run_selection(selection)

    def test_native_qualification_scope_is_false_and_review_declarations_present(self):
        fields = ('native_leanstral_outputs_qualified', 'trained4096_qualification_established',
                  'span_candidate_native_cuda_qualification')
        for field in fields:
            for mutation in ('true', 'missing'):
                with self.subTest(field=field, mutation=mutation):
                    selection = self.selection()
                    old = selection['review']
                    value = self.value(old)
                    if mutation == 'missing':
                        del value[field]
                    else:
                        value[field] = True
                    self.repin_document(selection, old, value)
                    with self.assertRaisesRegex(ValueError, 'scope'):
                        self.run_selection(selection)
        selection = self.selection()
        old = selection['plan']
        value = self.value(old)
        value['native_leanstral_outputs_qualified'] = True
        self.repin_document(selection, old, value)
        with self.assertRaisesRegex(ValueError, 'diagnostic document scope'):
            self.run_selection(selection)

    def test_plan_schema_diagnostic_and_current_control_count_match_review_scope(self):
        for field, replacement in (('schema', 'wrong/v1'), ('diagnostic_only', 1),
                                   ('current_passing_test_cases', 8), ('performance_qualified', True),
                                   ('selected_existing_profile_changed', True), ('publication_performed', True)):
            with self.subTest(field=field):
                selection = self.selection()
                old = selection['plan']
                value = self.value(old)
                value[field] = replacement
                self.repin_document(selection, old, value)
                with self.assertRaisesRegex(ValueError, 'diagnostic document scope'):
                    self.run_selection(selection)


if __name__ == '__main__':
    unittest.main()
