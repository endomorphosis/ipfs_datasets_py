"""22 native SQL completion controls; root alone runs qualification.

Each test uses an owned private DuckDB/CAS pair and authored source fixtures.
The old32 regressions run in another process without a DuckDB importer. These
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
    import selected_semantic_completion_fixture as fixture
except ModuleNotFoundError as error:
    if error.name != 'selected_semantic_completion_fixture':
        raise
    # Ordinary CI applies the byte-equal fixture beside this test module.
    fixture_path = Path(__file__).with_name('codebase_semantic_completion_fixture.py')
    fixture_spec = importlib.util.spec_from_file_location('codebase_semantic_completion_fixture', fixture_path)
    if fixture_spec is None or fixture_spec.loader is None:
        raise ImportError('ordinary semantic completion fixture is unavailable')
    fixture = importlib.util.module_from_spec(fixture_spec)
    sys.modules[fixture_spec.name] = fixture
    fixture_spec.loader.exec_module(fixture)
from ipfs_datasets_py.duckdb_control.codebase_catalog import (
    CodebaseCatalog, CodebaseHeadConflict, CodebaseOperationConflict,
)
from ipfs_datasets_py.logic.software_contracts import codebase_preparation as protocol
from ipfs_datasets_py.logic.software_contracts import codebase_preparation_runtime as runtime_module
from ipfs_datasets_py.logic.software_contracts import codebase_preparation_projection as codec
from ipfs_datasets_py.logic.software_contracts import python_frontend as frontend_module
from ipfs_datasets_py.logic.software_contracts import duckdb_ingest as ingestion_module
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
    'complete_requires_complete_prefix',
    'default_frontend_reuse_full_native_publication',
    'explicit_optout_full_semantic_and_SQL_parity',
    'cross_page_import_fixture_configuration_edges',
    'exact_reuse_boolean_and_owner_identity',
    'source_membership_drift_refusal',
    'parser_context_and_implementation_refusal',
    'external_cursor_and_page_admission_refusal',
    'missing_corrupt_saved_AST_refusal',
    'cancellation_before_and_during_semantic_assembly',
    'cancellation_after_manifest_seal_no_publication',
    'cancellation_after_AST_apply_rolls_back_native_rows',
    'before_commit_fault_rolls_back_head_and_receipt',
    'initial_head_conflict_no_publication',
    'competitor_before_apply_preserves_committed_head',
    'same_operation_retry_no_new_native_writes',
    'historical_operation_retry_after_edit_and_successor',
    'operation_identifier_conflict_preserves_native_state',
    'post_commit_cancellation_returns_committed_receipt',
    'committed_cleanup_error_carries_durable_receipt',
    'staged_profile_mismatch_and_explicit_optout',
    'checkpoint_callback_caller_alias_detached',
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


class TestPreparationSemanticCompletion(unittest.TestCase):
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
        self.catalog = CodebaseCatalog(self.store, self.artifacts)
        self.actor = runtime_module.RepositoryCodebasePreparation(
            artifacts=self.artifacts, ingestor=self.ingestor, catalog=self.catalog)
        self.limits = protocol.CodebasePreparationLimits(max_entries=64, page_entries=16)
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
                 'timeout_seconds': 120.0, 'admission_timeout_seconds': 30.0}
        value.update(overrides)
        return value

    def _fixture_start(self, *, expected=None, actor=None):
        actor = self.actor if actor is None else actor
        return actor.start_current(self.repository, repository_id=fixture.REPOSITORY_ID,
            expected_head=expected, limits=self.limits, created_at=fixture.CREATED_AT,
            **self._fixture_resources())

    def _fixture_pages(self, root, *, actor=None, stop=None):
        actor = self.actor if actor is None else actor
        cursor = None
        while cursor is None or cursor.next_offset < (34 if stop is None else stop):
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

    def _fixture_assert_published(self, receipt):
        self.assertEqual(self.catalog.current(fixture.REPOSITORY_ID), receipt.head)
        self.assertEqual(receipt.generation, 1)
        self.assertEqual(self.connection.execute('SELECT count(*) FROM codebase_control.operations').fetchone()[0], 1)
        self.assertEqual(self.connection.execute('SELECT count(*) FROM ast_blobs').fetchone()[0], 33)
        self.assertEqual(len(self._fixture_manifest(receipt).units), 34)

    def test_complete_requires_complete_prefix(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root, stop=16)
        before = self._fixture_native_state()
        with patch.object(RepositoryScanner, 'scan_snapshot', side_effect=AssertionError('incomplete scan forbidden')):
            with self.assertRaises(ValueError): self._fixture_complete(root, cursor)
        self.assertEqual(self._fixture_native_state(), before)
        self.assertIsNone(self.catalog.current(fixture.REPOSITORY_ID))

    def test_default_frontend_reuse_full_native_publication(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root)
        self.assertEqual(self.counter.parse_invocations, 33)
        before = self._fixture_native_state()
        self.assertEqual(before['ast_blobs'], [])
        calls, observation = self._fixture_semantic_frontend_calls()
        with observation: receipt = self._fixture_complete(root, cursor)
        self.assertEqual(calls, [])
        self._fixture_assert_published(receipt)
        fixture.graph_witnesses(self._fixture_manifest(receipt).semantic_state)

    def test_explicit_optout_full_semantic_and_SQL_parity(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root)
        calls, observation = self._fixture_semantic_frontend_calls()
        with observation: first = self._fixture_complete(root, cursor)
        self.assertEqual(calls, [])
        comparison = self.workspace / 'comparison'; comparison.mkdir(mode=0o700)
        connection = self._fixture_connection(comparison / 'catalog.duckdb')
        self.addCleanup(connection.close)
        store = DuckDBASTStore(connection=connection)
        counter = CountingFrontend(PythonASTExtractor())
        ingestor = DuckDBASTIngestor(store=store, frontends={'python': counter}, languages=('python',))
        catalog = CodebaseCatalog(store, self.artifacts)
        actor = runtime_module.RepositoryCodebasePreparation(artifacts=self.artifacts, ingestor=ingestor, catalog=catalog)
        calls, observation = self._fixture_semantic_frontend_calls()
        with observation: receipt = self._fixture_complete(root, cursor, actor=actor, optimized_frontend_reuse=False)
        self.assertEqual(sorted(calls), list(fixture.PYTHON_PATHS))
        self.assertEqual(first.to_dict(), receipt.to_dict())
        self.assertEqual(self._fixture_manifest(first).to_dict(), self._fixture_manifest(receipt).to_dict())
        self.assertEqual(self._fixture_native_state(), self._fixture_native_state(connection))
        self.assertEqual(catalog.current(fixture.REPOSITORY_ID), receipt.head)
        fixture.graph_witnesses(self._fixture_manifest(receipt).semantic_state)

    def test_cross_page_import_fixture_configuration_edges(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root)
        receipt = self._fixture_complete(root, cursor)
        witnesses = fixture.graph_witnesses(self._fixture_manifest(receipt).semantic_state)
        self.assertEqual(len(witnesses['cross_page_calls']), 3)
        self.assertEqual(len(witnesses['pytest_fixture_dependencies']), 3)
        self.assertGreaterEqual(len(witnesses['configured_tests']), 2)

    def test_exact_reuse_boolean_and_owner_identity(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root); before = self._fixture_native_state()
        for flag in (None, 0, 1, 'true'):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                self._fixture_complete(root, cursor, optimized_frontend_reuse=flag)
        memory = DuckDBASTIngestor(frontends={'python': CountingFrontend(PythonASTExtractor())}, languages=('python',))
        mismatched = runtime_module.RepositoryCodebasePreparation(artifacts=self.artifacts, ingestor=memory, catalog=self.catalog)
        with self.assertRaises(ValueError): self._fixture_complete(root, cursor, actor=mismatched)
        saved_limits = self.catalog.limits
        try:
            for field in ('max_entries', 'max_source_bytes', 'max_ast_bytes', 'max_manifest_bytes'):
                self.catalog.limits = replace(saved_limits, **{field: 1})
                with self.subTest(limit=field), self.assertRaises(ValueError):
                    self._fixture_complete(root, cursor)
                self.assertEqual(self._fixture_native_state(), before)
        finally:
            self.catalog.limits = saved_limits
        with patch.object(RepositoryScanner, 'scan_snapshot', side_effect=AssertionError('reservation refused before semantic scan')):
            with self.assertRaises(ValueError): self._fixture_complete(root, cursor, memory_mb=1)
        self.assertEqual(self._fixture_native_state(), before)

    def test_source_membership_drift_refusal(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root); before = self._fixture_native_state()
        path = self.repository / 'a00.py'; raw = path.read_bytes()
        for kind in ('edit', 'add', 'delete', 'rename', 'configuration'):
            extra = self.repository / 'extra.py'; renamed = self.repository / 'renamed.py'
            configuration = self.repository / 'pyproject.toml'; saved = configuration.read_bytes()
            try:
                if kind == 'edit': path.write_bytes(raw + b'\n# source changed\n')
                elif kind == 'add': extra.write_bytes(b'# extra authored source\n')
                elif kind == 'delete': path.unlink()
                elif kind == 'rename': path.rename(renamed)
                else: configuration.write_bytes(saved + b'\n# configuration changed\n')
                with self.subTest(kind=kind), self.assertRaises(ValueError): self._fixture_complete(root, cursor)
                self.assertEqual(self._fixture_native_state(), before)
            finally:
                if renamed.exists(): renamed.rename(path)
                if extra.exists(): extra.unlink()
                path.write_bytes(raw); configuration.write_bytes(saved)

    def test_parser_context_and_implementation_refusal(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root); before = self._fixture_native_state()
        native = self.counter._frontend; saved = native.max_ast_depth; native.max_ast_depth -= 1
        try:
            with self.assertRaises(ValueError): self._fixture_complete(root, cursor)
        finally: native.max_ast_depth = saved
        changed = self.workspace / 'changed-parser.py'
        changed.write_bytes(Path(frontend_module.__file__).read_bytes() + b'\n# authored implementation change\n')
        with patch.object(frontend_module, '__file__', str(changed)), self.assertRaises(ValueError):
            self._fixture_complete(root, cursor)
        self.assertEqual(self._fixture_native_state(), before)

    def test_external_cursor_and_page_admission_refusal(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root); before = self._fixture_native_state()
        wrong = protocol.PreparationCursor(root.artifact_cid, cursor.next_offset, root.artifact_cid)
        with self.assertRaises(ValueError): self._fixture_complete(root, wrong, admitted=cursor.previous_page_cid)
        with self.assertRaises(ValueError): self._fixture_complete(root, cursor, admitted=root.artifact_cid)
        self.assertEqual(self._fixture_native_state(), before)

    def test_missing_corrupt_saved_AST_refusal(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root); before = self._fixture_native_state()
        page = protocol.load_preparation_page(self.artifacts, cursor.previous_page_cid)
        descriptor = page.to_dict()['entries'][0]['ast_artifact']; path = self.artifacts.path_for(descriptor['cid'])
        raw = path.read_bytes()
        for kind in ('missing', 'corrupt'):
            try:
                if kind == 'missing': path.unlink()
                else: path.write_bytes(b'{}')
                with self.subTest(kind=kind), self.assertRaises((ValueError, FileNotFoundError, OSError)):
                    self._fixture_complete(root, cursor)
                self.assertEqual(self._fixture_native_state(), before)
            finally: path.write_bytes(raw)

    def test_cancellation_before_and_during_semantic_assembly(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root); before = self._fixture_native_state()
        cancelled = threading.Event(); cancelled.set()
        with self.assertRaises(scheduling.LeaseCancelledError): self._fixture_complete(root, cursor, cancel_event=cancelled)
        cancelled.clear(); analyzed = []; original = PythonSemanticAnalyzer.analyze
        def stop_after_source(analyzer, *args, **kwargs):
            state = original(analyzer, *args, **kwargs); analyzed.append(True); cancelled.set(); return state
        with patch.object(PythonSemanticAnalyzer, 'analyze', stop_after_source), self.assertRaises(scheduling.LeaseCancelledError):
            self._fixture_complete(root, cursor, cancel_event=cancelled)
        self.assertEqual(analyzed, [True])
        self.assertEqual(self._fixture_native_state(), before)

    def test_cancellation_after_manifest_seal_no_publication(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root); before = self._fixture_native_state()
        cancelled = threading.Event(); sealed = []; original = self.artifacts._publish
        def publish(target, raw):
            original(target, raw); value = json.loads(raw)
            if isinstance(value, dict) and value.get('schema') == 'codebase-ir-structural-manifest@1':
                sealed.append(target.name); cancelled.set()
        with patch.object(self.artifacts, '_publish', publish), self.assertRaises(scheduling.LeaseCancelledError):
            self._fixture_complete(root, cursor, cancel_event=cancelled)
        self.assertEqual(len(sealed), 1)
        self.assertEqual(self._fixture_native_state(), before)

    def test_cancellation_after_AST_apply_rolls_back_native_rows(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root); before = self._fixture_native_state()
        cancelled = threading.Event(); applied = []; original = self.store._persist_projection
        def persist(projection):
            original(projection); applied.append(projection.blob_id); cancelled.set()
        with patch.object(self.store, '_persist_projection', persist), self.assertRaises(scheduling.LeaseCancelledError):
            self._fixture_complete(root, cursor, cancel_event=cancelled)
        self.assertGreater(len(applied), 0)
        self.assertEqual(self._fixture_native_state(), before)

    def test_before_commit_fault_rolls_back_head_and_receipt(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root); before = self._fixture_native_state()
        inserted = []; original = self.store.apply_batch
        def apply(*args, **kwargs):
            hook = kwargs['before_commit']
            def fault(connection):
                hook(connection)
                inserted.append(connection.execute('SELECT count(*) FROM codebase_control.operations').fetchone()[0])
                raise RuntimeError('authored fault after receipt insertion before COMMIT')
            kwargs['before_commit'] = fault
            return original(*args, **kwargs)
        with patch.object(self.store, 'apply_batch', apply), self.assertRaisesRegex(RuntimeError, 'authored fault'):
            self._fixture_complete(root, cursor)
        self.assertEqual(inserted, [1])
        self.assertEqual(self._fixture_native_state(), before)

    def test_initial_head_conflict_no_publication(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root); receipt = self._fixture_complete(root, cursor)
        before = self._fixture_native_state()
        with patch.object(self.catalog, 'publish', side_effect=AssertionError('stale publication forbidden')):
            with self.assertRaises(ValueError): self._fixture_complete(root, cursor, operation='another-operation')
        self.assertEqual(self._fixture_native_state(), before)
        self.assertEqual(self.catalog.current(fixture.REPOSITORY_ID), receipt.head)

    def test_competitor_before_apply_preserves_committed_head(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root); committed = []; original = self.catalog.publish
        def compete(**kwargs):
            competitor = dict(kwargs); competitor['operation_id'] = 'independent-competitor'
            committed.append(original(**competitor))
            return original(**kwargs)
        with patch.object(self.catalog, 'publish', compete), self.assertRaises(CodebaseHeadConflict):
            self._fixture_complete(root, cursor)
        self.assertEqual(len(committed), 1)
        self.assertEqual(self.catalog.current(fixture.REPOSITORY_ID), committed[0].head)
        self.assertEqual(self.connection.execute('SELECT operation_id FROM codebase_control.operations').fetchall(), [('independent-competitor',)])
        self.assertEqual(self.connection.execute('SELECT count(*) FROM ast_blobs').fetchone()[0], 33)

    def test_same_operation_retry_no_new_native_writes(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root); receipt = self._fixture_complete(root, cursor)
        before = self._fixture_native_state()
        with patch.object(self.store, 'apply_batch', side_effect=AssertionError('AST writes on replay')):
            replay = self._fixture_complete(root, cursor)
        self.assertEqual(replay, receipt)
        self.assertEqual(self._fixture_native_state(), before)

    def test_historical_operation_retry_after_edit_and_successor(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root); first = self._fixture_complete(root, cursor)
        (self.repository / 'a01.py').write_bytes(self.sources['a01.py'] + b'\n# authored successor\n')
        before = self._fixture_native_state()
        self.assertEqual(self._fixture_complete(root, cursor), first)
        self.assertEqual(self._fixture_native_state(), before)
        with self.assertRaises(ValueError): self._fixture_complete(root, cursor, operation='drifted-new-operation')
        successor_root = self._fixture_start(expected=first.head); successor_cursor = self._fixture_pages(successor_root)
        second = self._fixture_complete(successor_root, successor_cursor, operation='authored-successor')
        self.assertEqual(second.generation, 2); before = self._fixture_native_state()
        with patch.object(self.store, 'apply_batch', side_effect=AssertionError('historical AST mutation')):
            self.assertEqual(self._fixture_complete(root, cursor), first)
        self.assertEqual(self.catalog.current(fixture.REPOSITORY_ID), second.head)
        self.assertEqual(self._fixture_native_state(), before)

    def test_operation_identifier_conflict_preserves_native_state(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root); first = self._fixture_complete(root, cursor)
        (self.repository / 'a01.py').write_bytes(self.sources['a01.py'] + b'\n# conflicting operation request\n')
        new_root = self._fixture_start(expected=first.head); new_cursor = self._fixture_pages(new_root)
        before = self._fixture_native_state()
        with self.assertRaises(CodebaseOperationConflict): self._fixture_complete(new_root, new_cursor)
        self.assertEqual(self._fixture_native_state(), before)

    def test_post_commit_cancellation_returns_committed_receipt(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root); cancelled = threading.Event()
        original = self.catalog.publish
        def publish(**kwargs):
            receipt = original(**kwargs); cancelled.set(); return receipt
        with patch.object(self.catalog, 'publish', publish):
            receipt = self._fixture_complete(root, cursor, cancel_event=cancelled)
        self.assertTrue(cancelled.is_set())
        self._fixture_assert_published(receipt)

    def test_committed_cleanup_error_carries_durable_receipt(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root)
        original = codebase_resources.acquire_codebase_resources
        @contextmanager
        def released_then_fault(*args, **kwargs):
            with original(*args, **kwargs) as actual:
                yield actual
            if not actual.released: raise AssertionError('real operation lease not released')
            raise RuntimeError('authored fault after committed lease cleanup')
        with patch.object(codebase_resources, 'acquire_codebase_resources', released_then_fault):
            with self.assertRaises(runtime_module.CodebasePreparationCommittedError) as observed:
                self._fixture_complete(root, cursor)
        receipt = observed.exception.receipt
        self._fixture_assert_published(receipt)

    def test_staged_profile_mismatch_and_explicit_optout(self):
        self.counter._frontend.max_ast_depth -= 1
        root = self._fixture_start(); cursor = self._fixture_pages(root); before = self._fixture_native_state()
        with self.assertRaises(ValueError): self._fixture_complete(root, cursor)
        self.assertEqual(self._fixture_native_state(), before)
        calls, observation = self._fixture_semantic_frontend_calls()
        with observation: receipt = self._fixture_complete(root, cursor, optimized_frontend_reuse=False)
        self.assertEqual(sorted(calls), list(fixture.PYTHON_PATHS))
        self._fixture_assert_published(receipt)

    def test_checkpoint_callback_caller_alias_detached(self):
        root = self._fixture_start(); cursor = self._fixture_pages(root)
        snapshot = root.to_dict()['snapshot']
        from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import RepositorySnapshot
        captured = RepositorySnapshot.from_dict(snapshot)
        sources = {entry.source_key: self.artifacts.get_bytes(entry.source_cid)
                   for entry in captured.entries if not entry.is_opaque}
        projections = self.actor.load_projections(root.artifact_cid, cursor,
            admitted_page_cid=cursor.previous_page_cid, **self._fixture_resources())
        by_path = {projection.source_file.path: projection for projection in projections}
        records = {entry.source_key: ASTRecord.from_json(by_path[entry.path].ast_blob.payload_json)
                   for entry in captured.entries if entry.path.endswith('.py')}
        contexts = {entry.source_key: ingestion_module._frontend_cache_context(
            self.counter, language='python', path=entry.path) for entry in captured.entries if entry.path.endswith('.py')}
        expected = RepositoryScanner(repository_id=fixture.REPOSITORY_ID).scan_snapshot(captured, sources,
            prepared_ast_records=records, prepared_ast_contexts=contexts)
        invoked = []
        def mutate():
            invoked.append(True); records.clear(); contexts.clear()
        actual = RepositoryScanner(repository_id=fixture.REPOSITORY_ID).scan_snapshot(captured, sources,
            prepared_ast_records=records, prepared_ast_contexts=contexts, checkpoint=mutate)
        self.assertGreater(len(invoked), 0)
        self.assertEqual(actual.to_dict(), expected.to_dict())


def load_suite():
    if OWNED_RESOURCES is None or API_READY is not True:
        raise AssertionError('qualification requires settled APIs and actual admitted private resources')
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestPreparationSemanticCompletion)
    names = tuple(sorted(test._testMethodName.removeprefix('test_') for test in suite))
    if names != tuple(sorted(CASE_NAMES)) or suite.countTestCases() != 22:
        raise AssertionError('finite22 integration case inventory differs')
    return suite


if __name__ == '__main__':unittest.main()
