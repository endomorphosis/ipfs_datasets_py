"""five full300 native SQL completion controls; root alone runs qualification.

Each test uses an owned private DuckDB/CAS pair and authored source fixtures.
Previously qualified54 controls are retained without replay. These
controls qualify source-bound graph assembly/atomic publication only, never
behavioral proof, target execution, models, training, CUDA or worker authority.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from dataclasses import replace
import json
import importlib.util
import sys
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

import duckdb
try:
    import selected_full300_fixture as fixture
except ModuleNotFoundError as error:
    if error.name != 'selected_full300_fixture':
        raise
    # Ordinary CI applies the byte-equal fixture beside this test module.
    fixture_path = Path(__file__).with_name('codebase_full300_fixture.py')
    fixture_spec = importlib.util.spec_from_file_location('codebase_full300_fixture', fixture_path)
    if fixture_spec is None or fixture_spec.loader is None:
        raise ImportError('ordinary semantic completion fixture is unavailable')
    fixture = importlib.util.module_from_spec(fixture_spec)
    sys.modules[fixture_spec.name] = fixture
    fixture_spec.loader.exec_module(fixture)
from ipfs_datasets_py.duckdb_control.codebase_catalog import (
    CodebaseCatalog, CodebaseCatalogLimits, CodebaseHeadConflict, CodebaseOperationConflict,

)
from ipfs_datasets_py.logic.software_contracts import codebase_preparation as protocol
from ipfs_datasets_py.logic.software_contracts import codebase_preparation_runtime as runtime_module
from ipfs_datasets_py.logic.software_contracts import codebase_preparation_projection as codec
from ipfs_datasets_py.logic.software_contracts import python_frontend as frontend_module
from ipfs_datasets_py.logic.software_contracts import duckdb_ingest as ingestion_module
from ipfs_datasets_py.logic.software_contracts import duckdb_ast_store as store_module
from ipfs_datasets_py.duckdb_control import codebase_catalog as catalog_module
from ipfs_datasets_py.logic.software_contracts import codebase_resources
from ipfs_datasets_py.logic.software_contracts.ast_ir import ASTRecord
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import CodebaseIRManifest
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore, project_ast_record
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import CountingFrontend, DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor
from ipfs_datasets_py.logic.software_contracts.semantic_index.scanner import RepositoryScanner
from ipfs_datasets_py.logic.software_contracts.semantic_index.python_analysis import PythonSemanticAnalyzer
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduling

CASE_NAMES = (
    'default_catalog256_refuses_before_assembly',
    'incomplete128_refuses_without_native_writes',
    'late_source_and_membership_drift_refuses_atomically',
    'full_inventory_head_retry_and_operation_conflict',
    'cache_handoff_default_optout_corruption_context',
)
OWNED_RESOURCES = None
MIB = 1024 * 1024
API_READY = True


def configure_owned_resources(workspace, scheduler, parent_lease):
    global OWNED_RESOURCES
    if type(workspace) is not type(Path.cwd()):
        raise ValueError('exact concrete owned workspace required')
    info = workspace.lstat()
    if (workspace != Path.cwd() or workspace.resolve(strict=True) != workspace
            or info.st_uid != os.getuid() or not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o700
            or not isinstance(scheduler, scheduling.GlobalResourceScheduler)
            or not isinstance(parent_lease, scheduling.ResourceLease)):
        raise ValueError('actual admitted private scheduler/child lease required')
    OWNED_RESOURCES = workspace, scheduler, parent_lease

def _sql_value(value):
    if type(value) is float:
        return {'float_hex': value.hex()}
    if type(value) in (tuple, list):
        return [_sql_value(item) for item in value]
    if value is None or type(value) in (int, bool, str):
        return value
    raise AssertionError('unexpected native SQL scalar: ' + type(value).__name__)

class TestFull300Preparation(unittest.TestCase):
    def setUp(self):
            if not API_READY:
                raise AssertionError('root must bind settled semantic completion APIs before qualification')
            parent = OWNED_RESOURCES[0] if OWNED_RESOURCES is not None else None
            self.temporary = tempfile.TemporaryDirectory(prefix='semantic-completion-', dir=parent)
            self.addCleanup(self.temporary.cleanup)
            self.workspace = Path(self.temporary.name)
            self.repository = self.workspace / 'repository'
            self.sources = fixture.write_fixture(self.repository)
            self.artifacts = ImmutableCAS(self.workspace / 'cas', max_object_bytes=4 * MIB)
            self.connection = self._fixture_connection(self.workspace / 'catalog.duckdb')
            self.addCleanup(self.connection.close)
            self.store = DuckDBASTStore(connection=self.connection)
            self.counter = CountingFrontend(PythonASTExtractor())
            self.ingestor = DuckDBASTIngestor(store=self.store, frontends={'python': self.counter}, languages=('python',))
            self.catalog = CodebaseCatalog(self.store, self.artifacts, limits=CodebaseCatalogLimits(max_entries=fixture.MAX_ENTRIES))
            self.actor = runtime_module.RepositoryCodebasePreparation(
                artifacts=self.artifacts, ingestor=self.ingestor, catalog=self.catalog)
            self.limits = protocol.CodebasePreparationLimits(max_entries=fixture.MAX_ENTRIES, page_entries=16)
            if OWNED_RESOURCES is None:
                healthy = scheduling.ProofHostResources(4, 4096, 4096)
                configuration = scheduling.ResourceSchedulerConfig.for_proof_host(
                    state_path=self.workspace / 'admission.json', lane_reservations={},
                    proof_resource_sampler=lambda: healthy, auto_renew_leases=False,
                    poll_interval_seconds=0.005, proof_backoff_seconds=0.02)
                self.scheduler, self.parent_lease = scheduling.GlobalResourceScheduler(configuration), None
            else:
                _, self.scheduler, self.parent_lease = OWNED_RESOURCES

    def _fixture_connection(self, path):
            connection = duckdb.connect(str(path))
            connection.execute("SET threads=1")
            connection.execute("SET memory_limit='128MB'")
            return connection

    def _fixture_resources(self, **overrides):
            value = {'scheduler': self.scheduler if self.parent_lease is None else None,
                     'parent_lease': self.parent_lease, 'memory_mb': 512,
                     'timeout_seconds': 900.0, 'admission_timeout_seconds': 30.0}
            value.update(overrides)
            return value

    def _fixture_start(self, *, expected=None, actor=None, clock=fixture.CREATED_AT):
            actor = self.actor if actor is None else actor
            return actor.start_current(self.repository, repository_id=fixture.REPOSITORY_ID,
                expected_head=expected, limits=self.limits, created_at=clock,
                **self._fixture_resources())

    def _fixture_pages(self, root, *, actor=None, stop=None):
            actor = self.actor if actor is None else actor
            cursor = None
            while cursor is None or cursor.next_offset < (fixture.ENTRY_COUNT if stop is None else stop):
                page = actor.prepare_page(self.repository, root.artifact_cid, cursor,
                    admitted_page_cid=None if cursor is None else cursor.previous_page_cid,
                    **self._fixture_resources())
                cursor = page.next_cursor
            return cursor

    def _fixture_complete(self, root, cursor, *, actor=None, operation=None, admitted=None, **overrides):
            actor = self.actor if actor is None else actor
            return actor.complete_current(self.repository, root.artifact_cid, cursor,
                operation_id=fixture.OPERATION_ID if operation is None else operation,
                admitted_page_cid=cursor.previous_page_cid if admitted is None else admitted,
                **self._fixture_resources(**overrides))

    def _fixture_native_state(self, connection=None):
            connection = self.connection if connection is None else connection
            result = {}
            for name in (*fixture.TABLE_NAMES, 'codebase_control.meta', 'codebase_control.heads', 'codebase_control.operations'):
                identifier = '.'.join('"' + part.replace('"', '""') + '"' for part in name.split('.'))
                rows = [_sql_value(row) for row in connection.execute('SELECT * FROM ' + identifier).fetchall()]
                result[name] = sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, separators=(',', ':')))
            return result

    def _fixture_manifest(self, receipt):
            return CodebaseIRManifest.from_dict(self.artifacts.get(receipt.manifest_cid))

    def _fixture_semantic_frontend_calls(self):
            calls = []
            original = PythonASTExtractor.extract_from_source
            def tracked(frontend, *args, **kwargs):
                calls.append(kwargs.get('path'))
                return original(frontend, *args, **kwargs)
            return calls, patch.object(PythonASTExtractor, 'extract_from_source', tracked)

    def test_default_catalog256_refuses_before_assembly(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root)
        before = self._fixture_native_state(); self.catalog.limits = CodebaseCatalogLimits()
        self.assertEqual(self.catalog.limits.max_entries, 256)
        with patch.object(RepositoryScanner, 'scan_snapshot', side_effect=AssertionError('over-bound scanner forbidden')):
            with self.assertRaises(ValueError): self._fixture_complete(root, cursor)
        self.assertEqual(self._fixture_native_state(), before)
        self.assertIsNone(self.catalog.current(fixture.REPOSITORY_ID))

    def test_incomplete128_refuses_without_native_writes(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root, stop=fixture.PREFIX_ENTRIES)
        self.assertEqual(cursor.next_offset, 128); self.assertEqual(self.counter.parse_invocations, 128)
        before = self._fixture_native_state()
        with patch.object(RepositoryScanner, 'scan_snapshot', side_effect=AssertionError('partial global graph forbidden')):
            with self.assertRaises(ValueError): self._fixture_complete(root, cursor)
        self.assertEqual(self._fixture_native_state(), before)

    def test_late_source_and_membership_drift_refuses_atomically(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root); before = self._fixture_native_state()
        path = self.repository / 'a295.py'; raw = path.read_bytes()
        extra = self.repository / 'extra.py'; renamed = self.repository / 'renamed.py'
        for kind in ('late_edit', 'add', 'delete', 'rename'):
            try:
                if kind == 'late_edit': path.write_bytes(fixture.SUCCESSOR_SOURCES['a295.py'])
                elif kind == 'add': extra.write_bytes(b'# authored membership drift\n')
                elif kind == 'delete': path.unlink()
                else: path.rename(renamed)
                with self.subTest(kind=kind), self.assertRaises(ValueError): self._fixture_complete(root, cursor)
                self.assertEqual(self._fixture_native_state(), before)
            finally:
                if renamed.exists(): renamed.rename(path)
                if extra.exists(): extra.unlink()
                path.write_bytes(raw)

    def test_full_inventory_head_retry_and_operation_conflict(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root)
        with fixture.fixed_module_clocks(fixture.CREATED_AT, ingestion_module, store_module, catalog_module):
            first = self._fixture_complete(root, cursor)
        before = self._fixture_native_state()
        with patch.object(self.store, 'apply_batch', side_effect=AssertionError('retry must not mutate native SQL')):
            self.assertEqual(self._fixture_complete(root, cursor), first)
        self.assertEqual(self._fixture_native_state(), before)
        fixture.apply_successor(self.repository)
        with self.assertRaises(ValueError): self._fixture_complete(root, cursor, operation='new-operation-with-stale-source')
        self.assertEqual(self._fixture_native_state(), before)
        successor = self._fixture_start(expected=first.head, clock=fixture.SUCCESSOR_CREATED_AT)
        saved = self.counter.parse_invocations; successor_cursor = self._fixture_pages(successor)
        self.assertEqual(self.counter.parse_invocations - saved, 1)
        with self.assertRaises(CodebaseOperationConflict): self._fixture_complete(successor, successor_cursor)
        self.assertEqual(self._fixture_native_state(), before)
        with fixture.fixed_module_clocks(fixture.SUCCESSOR_CREATED_AT, ingestion_module, store_module, catalog_module):
            second = self._fixture_complete(successor, successor_cursor, operation=fixture.SUCCESSOR_OPERATION_ID)
        self.assertEqual(second.generation, 2); self.assertEqual(second.previous_head, first.head)
        self.assertEqual(self.catalog.current(fixture.REPOSITORY_ID), second.head)
        after = self._fixture_native_state()
        self.assertEqual(len(after['ast_blobs']), 299)
        self.assertEqual(len(after['source_files']), 598)
        self.assertEqual(len(after['source_revisions']), 2)
        self.assertEqual(len(after['invalidations']), 1)
        self.assertEqual(len(after['codebase_control.operations']), 2)
        with patch.object(self.store, 'apply_batch', side_effect=AssertionError('historical replay must not alter successor')):
            self.assertEqual(self._fixture_complete(root, cursor), first)
            self.assertEqual(self._fixture_complete(successor, successor_cursor, operation=fixture.SUCCESSOR_OPERATION_ID), second)
        self.assertEqual({name: (self.repository / name).read_bytes() for name in fixture.ORDERED_PATHS}, fixture.SUCCESSOR_SOURCES)
        with self.assertRaises(ValueError):
            self._fixture_complete(successor, successor_cursor, operation='new-operation-with-stale-head')
        self.assertEqual(self._fixture_native_state(), after)

    def test_cache_handoff_default_optout_corruption_context(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root, stop=fixture.PREFIX_ENTRIES)
        projections = self.actor.load_projections(root.artifact_cid, cursor,
            admitted_page_cid=cursor.previous_page_cid, **self._fixture_resources())
        raw = self.ingestor.shard_cache.export_bundle(); anchor = fixture.cache_fingerprint(raw)
        before = self._fixture_native_state()
        def receiver():
            counter = CountingFrontend(PythonASTExtractor())
            ingestor = DuckDBASTIngestor(store=self.store, frontends={'python': counter}, languages=('python',))
            actor = runtime_module.RepositoryCodebasePreparation(artifacts=self.artifacts, ingestor=ingestor, catalog=self.catalog)
            actor.validate_current(self.repository, root.artifact_cid, cursor,
                admitted_page_cid=cursor.previous_page_cid, **self._fixture_resources())
            restored = actor.load_projections(root.artifact_cid, cursor,
                admitted_page_cid=cursor.previous_page_cid, **self._fixture_resources())
            self.assertEqual(counter.parse_invocations, 0)
            return counter, ingestor, actor, restored
        counter, ingestor, _, restored = receiver()
        for bad_raw, bad_anchor in ((raw + b' ', anchor), (raw, {**anchor, 'raw_cid_v1': root.artifact_cid})):
            with self.assertRaises(ValueError): fixture.admit_prefix_cache(bad_raw, bad_anchor, ingestor, restored)
            self.assertEqual(len(ingestor.shard_cache), 0)
        parsed = json.loads(raw); parsed['entries'].append(copy.deepcopy(parsed['entries'][0]))
        malformed = json.dumps(parsed, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        with self.assertRaises(ValueError): fixture.admit_prefix_cache(malformed, fixture.cache_fingerprint(malformed), ingestor, restored)
        self.assertEqual(len(ingestor.shard_cache), 0)
        counter._frontend.max_ast_depth -= 1
        with self.assertRaises(ValueError): fixture.admit_prefix_cache(raw, anchor, ingestor, restored)
        counter._frontend.max_ast_depth += 1
        self.assertEqual(len(ingestor.shard_cache), 0)
        with (patch.object(ingestor.shard_cache, 'hydrate_bundle', side_effect=AssertionError('opt-out hydrate forbidden')),
                patch.object(ingestor.shard_cache, 'get', side_effect=AssertionError('opt-out get forbidden')),
                patch.object(ingestor.shard_cache, 'export_bundle', side_effect=AssertionError('opt-out export forbidden')),
                patch.object(self.store, 'get_source_shard_cache', side_effect=AssertionError('opt-out store read forbidden')),
                patch.object(self.store, 'put_source_shard_cache', side_effect=AssertionError('opt-out store write forbidden'))):
            declined = fixture.admit_prefix_cache(object(), object(), ingestor, (), optimized_handoff_cache=False)
        self.assertEqual(declined, {'optimized_handoff_cache': False, 'restored_entries': 0})
        for flag in (None, 0, 1):
            with self.assertRaises(ValueError): fixture.admit_prefix_cache(raw, anchor, ingestor, restored, optimized_handoff_cache=flag)
        cold_counter, cold_ingestor, cold_actor, cold_prefix = receiver()
        fixture.admit_prefix_cache(raw, anchor, cold_ingestor, cold_prefix, optimized_handoff_cache=False)
        warm_counter, warm_ingestor, warm_actor, warm_prefix = receiver()
        accepted = fixture.admit_prefix_cache(raw, anchor, warm_ingestor, warm_prefix)
        self.assertEqual(accepted, {'optimized_handoff_cache': True, 'restored_entries': 128})
        self.assertEqual(warm_counter.parse_invocations, 0)
        for actor in (cold_actor, warm_actor):
            current = cursor
            while current.next_offset < fixture.ENTRY_COUNT:
                page = actor.prepare_page(self.repository, root.artifact_cid, current,
                    admitted_page_cid=current.previous_page_cid, **self._fixture_resources())
                current = page.next_cursor
        fixture.apply_successor(self.repository); bodies = []
        for counter, actor, expected in ((cold_counter, cold_actor, 129), (warm_counter, warm_actor, 1)):
            following = self._fixture_start(actor=actor, clock=fixture.SUCCESSOR_CREATED_AT)
            saved = counter.parse_invocations; following_cursor = self._fixture_pages(following, actor=actor)
            self.assertEqual(counter.parse_invocations - saved, expected)
            prepared = actor.load_projections(following.artifact_cid, following_cursor,
                admitted_page_cid=following_cursor.previous_page_cid, **self._fixture_resources())
            bodies.append([codec.encode_preparation_projection(item) for item in prepared])
        self.assertEqual(bodies[0], bodies[1]); self.assertEqual(self._fixture_native_state(), before)


def load_suite():
    if OWNED_RESOURCES is None or API_READY is not True:
        raise AssertionError('full300 qualification requires settled APIs and admitted private resources')
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestFull300Preparation)
    names = tuple(sorted(test._testMethodName.removeprefix('test_') for test in suite))
    if names != tuple(sorted(CASE_NAMES)) or suite.countTestCases() != 5:
        raise AssertionError('finite5 full300 case inventory differs')
    return suite


if __name__ == '__main__': unittest.main()
