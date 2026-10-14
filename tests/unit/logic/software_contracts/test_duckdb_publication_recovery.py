"""UNEXECUTED native publication recovery and catalog persistence qualification.

Root freezes and executes this source through the selected virtual-package
loader. Import performs no SQL, resource admission, Git, model or target-source
execution. Each fixture uses at most two authored parseable sources. Closed-image
reopening in this module is a connection restart; a separate process qualification
must supply its own native lifecycle evidence. All admitted CIDs are retained
outside the database before the producer closes it.
"""
from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

try:
    import duckdb
except ImportError as error:
    raise unittest.SkipTest("native DuckDB is required for publication recovery tests") from error

from ipfs_datasets_py.logic.software_contracts import duckdb_ingest as ingest_module
from ipfs_datasets_py.logic.software_contracts import duckdb_ast_store as store_module
from ipfs_datasets_py.logic.software_contracts.ast_ir import ASTRecord, SourceProvenance
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import (
    CodebaseIRManifest, CodebaseScanLimits, CodebaseUnit, RepositoryCodebaseIndex,
    StaleCodebaseError,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes, cid_for_bytes,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    ASTS_CATALOG_TABLES, DuckDBASTStore, DuckDBASTStoreError,
    DuckDBASTStoreIntegrityError, SOURCE_SHARD_CACHE_TABLE, project_ast_record, project_parse_failure,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import (
    DuckDBASTIngestor, DuckDBIngestError,
)
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor
from ipfs_datasets_py.logic.software_contracts.semantic_index.scanner import RepositoryScanner
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import (
    RepositorySnapshot, SnapshotEntry,
)
from ipfs_datasets_py.duckdb_control.codebase_catalog import (
    CodebaseCatalog, CodebaseCatalogError, CodebaseHeadConflict,
    CodebaseOperationConflict,
)

AT = 1700000000.0
REPOSITORY_ID = 'publication-recovery:authored-two-source-fixture'
SOURCES = {
    'a.py': b'import math\ndef rounded(value):\n    return math.floor(value)\n',
    'b.py': b'class Counter:\n    def __init__(self, value=0):\n        self.value = value\n    def step(self):\n        self.value += 1\n        return self.value\n',
}
CHANGED_A = b'import math\ndef rounded(value):\n    return math.ceil(value)\n'
MAX_DATABASE_BYTES = 16 * 1024 * 1024
OWNED_RESOURCES = None

CASE_NAMES = (
    'publication_closed_image_full_parity',
    'independent_restart_optouts',
    'exact_bool_rejected_before_side_effects',
    'unchanged_keeps_hooks_without_reprojection',
    'options_and_custom_frontend_context_miss',
    'fresh_source_bytes_verify_before_reuse',
    'complete_edit_add_delete_rename_successors',
    'opaque_only_publication_recovery',
    'external_cid_missing_and_reseal_refused',
    'malformed_bundle_atomic_adoption',
    'missing_extra_ast_membership_hydration_refused',
    'direct_sql_after_hydration_refused',
    'catalog_new_operation_retry_stale_head',
    'catalog_explicit_optout_table_receipt_parity',
    'catalog_timestamp_drift_and_canonical_corruption',
    'catalog_missing_extra_membership_not_empty_batch',
    'catalog_late_cancellation_full_rollback',
    'catalog_empty_ast_new_generation',
    'prepare_current_closing_source_fence',
    'prepare_current_cancellation_fence',
    'canonical_validation_exact_bool_preddl',
    'canonical_validation_every_family_corruption',
    'canonical_validation_clock_header_fallback',
    'canonical_validation_parse_failure_parity',
    'canonical_validation_checkpoint_corruption_rollback',
    'canonical_validation_checkpoint_membership_rollback',
    'canonical_validation_budget_fallback',
)


def configure_owned_resources(scheduler, parent_lease):
    """Root's authenticated child supplies its existing admitted capability.

    This configuration uses the existing owner and never creates/reconfigures MAIN.
    The qualification suite refuses to run if the owner omits this contract.
    """
    global OWNED_RESOURCES
    if scheduler is None or parent_lease is None:
        raise ValueError('actual admitted scheduler and parent lease are required')
    OWNED_RESOURCES = (scheduler, parent_lease)


def _snapshot(sources=None, *, opaque=False, exclusions=()):
    sources = SOURCES if sources is None else sources
    entries = [SnapshotEntry(path, 'source', len(raw), source_cid=cid_for_bytes(raw),
        acquisition='captured', disposition='filesystem', captured_bytes=raw)
        for path, raw in sources.items()]
    if opaque:
        entries.append(SnapshotEntry('opaque.bin', 'opaque', 0,
            opaque_reason='unreadable_authored_fixture', acquisition='opaque',
            disposition='opaque'))
    return RepositorySnapshot(REPOSITORY_ID, tuple(entries), 'filesystem',
        max_entries=3, max_file_bytes=4096, exclusions=exclusions)


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _rows(connection):
    """Complete rows and ordered columns for every authoritative AST family."""
    result = {}
    for table in ASTS_CATALOG_TABLES:
        query = connection.execute('SELECT * FROM main.' + _quote(table))
        result[table] = {'columns': tuple(item[0] for item in query.description),
                         'rows': tuple(sorted(query.fetchall(), key=repr))}
    if len(result) != 13:
        raise AssertionError('qualification requires all thirteen AST families')
    return result


def _control(connection):
    return {name: tuple(sorted(connection.execute(
        'SELECT * FROM codebase_control.' + _quote(name)).fetchall(), key=repr))
        for name in ('heads', 'operations')}


def _active(store, publication, *, checkpoint=None):
    return store.validate_active_revision(publication.projections, publication.invalidations,
        revision_id=publication.revision_id, repository_id=publication.repository_id,
        revision=publication.revision, repository_tree_cid=publication.repository_tree_cid,
        checkpoint=checkpoint)


class _UnqualifiedPythonFrontend:
    """Actual native extraction through an intentionally unqualified protocol."""
    def __init__(self):
        self.native = PythonASTExtractor()
        self.calls = 0

    def extract_from_source(self, source, **kwargs):
        self.calls += 1
        return self.native.extract_from_source(source, **kwargs)


class TestPublicationRecovery(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='publication-recovery-ci-',
            dir=str(Path.cwd()) if OWNED_RESOURCES is not None else None)
        self.root = Path(self.directory.name)
        self.connections = []
        self.serial = 0

    def tearDown(self):
        for connection in self.connections:
            connection.close()
        self.connections.clear()
        self.directory.cleanup()

    def _open(self, name=None, *, optimized_canonical_validation=True):
        self.serial += 1
        name = name or ('lane-%02d' % self.serial)
        path = self.root / (name + '.duckdb')
        connection = duckdb.connect(str(path), config={
            'threads': 1, 'memory_limit': '128MB', 'enable_external_access': False,
            'autoinstall_known_extensions': False, 'autoload_known_extensions': False,
        })
        self.connections.append(connection)
        return connection, DuckDBASTStore(connection=connection,
            optimized_canonical_validation=optimized_canonical_validation), path

    def _close(self, connection):
        connection.close()
        self.connections.remove(connection)

    def _seed(self, name=None, *, snapshot=None):
        connection, store, path = self._open(name)
        snapshot = snapshot or _snapshot()
        ingestor = DuckDBASTIngestor(store=store)
        publication = ingestor.ingest_snapshot(snapshot, created_at=AT)
        cache_cid = ingestor.export_restart_cache()
        publication_cid = ingestor.export_restart_publication(publication.revision_id)
        cache_raw = store.get_source_shard_cache(cache_cid)
        publication_raw = store.get_source_shard_cache(publication_cid)
        self.assertEqual(cid_for_bytes(cache_raw), cache_cid)
        self.assertEqual(cid_for_bytes(publication_raw), publication_cid)
        return {'connection': connection, 'store': store, 'path': path,
            'snapshot': snapshot, 'ingestor': ingestor, 'publication': publication,
            'cache_cid': cache_cid, 'publication_cid': publication_cid,
            'cache_raw': cache_raw, 'publication_raw': publication_raw}

    def _reopen(self, seed, **options):
        # Pin the complete producer-closed image before opening a consumer.
        self._close(seed['connection'])
        self.assertFalse(Path(str(seed['path']) + '.wal').exists())
        raw = seed['path'].read_bytes()
        self.assertLessEqual(len(raw), MAX_DATABASE_BYTES)
        image_pin = (len(raw), hashlib.sha256(raw).hexdigest(), cid_for_bytes(raw))
        copied = self.root / ('closed-copy-%02d.duckdb' % self.serial)
        with copied.open('xb') as stream:
            stream.write(raw)
        received = copied.read_bytes()
        self.assertEqual((len(received), hashlib.sha256(received).hexdigest(),
            cid_for_bytes(received)), image_pin)
        connection = duckdb.connect(str(copied), config={
            'threads': 1, 'memory_limit': '128MB', 'enable_external_access': False,
            'autoinstall_known_extensions': False, 'autoload_known_extensions': False,
        })
        self.connections.append(connection)
        store = DuckDBASTStore(connection=connection)
        self.assertEqual(store.get_source_shard_cache(seed['publication_cid']),
                         seed['publication_raw'])
        self.assertEqual(store.get_source_shard_cache(seed['cache_cid']), seed['cache_raw'])
        ingestor = DuckDBASTIngestor(store=store,
            restart_cache_cid=seed['cache_cid'],
            restart_publication_cid=seed['publication_cid'], **options)
        return connection, store, ingestor

    def _candidate(self, seed, *, artifacts=None, publication=None):
        publication = publication or seed['publication']
        snapshot = seed['snapshot']
        self.assertEqual(snapshot.to_dict(), publication.identity.snapshot.to_dict())
        artifacts = artifacts or ImmutableCAS(self.root / ('cas-%02d' % self.serial))
        sources = {entry.source_key: entry.captured_bytes for entry in snapshot.entries
                   if not entry.is_opaque}
        state = RepositoryScanner(repository_id=snapshot.repository_id).scan_snapshot(
            snapshot, sources)
        by_path = {projection.source_file.path: projection
                   for projection in publication.projections}
        units = tuple(CodebaseUnit(entry.source_key, entry.entry_cid,
            None if entry.path not in by_path else by_path[entry.path].ast_cid,
            'opaque' if entry.is_opaque else 'unindexed' if entry.path not in by_path
            else by_path[entry.path].ast_blob.parse_status)
            for entry in snapshot.entries)
        manifest = CodebaseIRManifest(snapshot, state, publication.revision_id, units)
        for raw in sources.values():
            artifacts.put_bytes(raw)
        for projection in publication.projections:
            self.assertEqual(artifacts.put(json.loads(projection.ast_blob.payload_json)),
                             projection.ast_cid)
        self.assertEqual(artifacts.put(manifest.to_dict()), manifest.cid)
        return manifest, artifacts

    def _catalog(self, seed, *, optimized=True):
        manifest, artifacts = self._candidate(seed)
        catalog = CodebaseCatalog(seed['store'], artifacts,
            optimized_unchanged_publication=optimized)
        receipt = catalog.publish(operation_id='first', manifest=manifest,
            expected_head=None, projections=seed['publication'].projections)
        return catalog, manifest, receipt

    def _count_writes(self, store):
        observations = []
        native = store._persist_projection
        def observed(projection):
            observations.append(projection.ast_cid)
            return native(projection)
        return patch.object(store, '_persist_projection', observed), observations

    def _cache_relation(self, connection):
        database, schema = connection.execute(
            'SELECT current_database(), current_schema()').fetchone()
        return '.'.join(_quote(name) for name in (database, schema, SOURCE_SHARD_CACHE_TABLE))

    def _extra_projection(self, publication):
        record = PythonASTExtractor().extract_from_source(b'extra = 3\n', path='extra.py',
            repository_id=publication.repository_id, revision=publication.revision,
            repository_tree_cid=publication.repository_tree_cid)
        return project_ast_record(record, created_at=AT)

    def test_publication_closed_image_full_parity(self):
        fixtures = (SOURCES, {'broken.py': b'def broken(:\n', 'b.py': SOURCES['b.py']})
        for sources in fixtures:
            with self.subTest(paths=tuple(sources)):
                seed = self._seed(snapshot=_snapshot(sources))
                before = _rows(seed['connection'])
                connection, store, ingestor = self._reopen(seed)
                self.assertEqual(ingestor.list_publications(), (seed['publication'],))
                self.assertTrue(_active(store, seed['publication']))
                context, writes = self._count_writes(store)
                with context:
                    recovered = ingestor.ingest_snapshot(_snapshot(sources), created_at=AT + 99)
                self.assertEqual(recovered, seed['publication'])
                self.assertEqual(recovered.to_dict(), seed['publication'].to_dict())
                self.assertEqual(recovered.projections, seed['publication'].projections)
                self.assertEqual(recovered.invalidations, seed['publication'].invalidations)
                self.assertEqual(writes, [])
                self.assertEqual(ingestor.stats()['parse_invocations'], 0)
                self.assertEqual(_rows(connection), before)
                if 'broken.py' in sources:
                    self.assertEqual(recovered.stats.parse_failed_count, 1)
                    self.assertEqual(recovered.projection_for_path('broken.py').ast_blob.parse_status,
                                     'failed')

    def test_independent_restart_optouts(self):
        for publication_on, cache_on in ((True, True), (True, False),
                                          (False, True), (False, False)):
            with self.subTest(publication=publication_on, cache=cache_on):
                seed = self._seed()
                before = _rows(seed['connection'])
                connection, store, ingestor = self._reopen(seed,
                    optimized_restart_publication=publication_on,
                    optimized_restart_cache=cache_on)
                self.assertEqual(len(ingestor.list_publications()), int(publication_on))
                context, writes = self._count_writes(store)
                with context:
                    actual = ingestor.ingest_snapshot(_snapshot(), created_at=AT)
                self.assertEqual(actual.projections, seed['publication'].projections)
                self.assertEqual(_rows(connection), before)
                self.assertEqual(len(writes), 0 if publication_on else 2)
                self.assertEqual(ingestor.stats()['parse_invocations'],
                    0 if publication_on or cache_on else 2)

    def test_exact_bool_rejected_before_side_effects(self):
        def forbidden():
            raise AssertionError('invalid flags must fail before implicit store creation')
        with patch.object(ingest_module, 'build_duckdb_ast_store', forbidden):
            for invalid in (None, 0, 1, 'true', [], object()):
                with self.subTest(value=repr(invalid)):
                    with self.assertRaises(DuckDBIngestError):
                        DuckDBASTIngestor(optimized_restart_publication=invalid)
                    with self.assertRaises(CodebaseCatalogError):
                        CodebaseCatalog(None, None, optimized_unchanged_publication=invalid)
        seed = self._seed()
        catalog, manifest, first = self._catalog(seed)
        catalog.optimized_unchanged_publication = 1
        with self.assertRaises(CodebaseCatalogError):
            catalog.publish(operation_id='invalid-flag', manifest=manifest,
                expected_head=first.head, projections=seed['publication'].projections)
        self.assertEqual(len(_control(seed['connection'])['operations']), 1)

    def test_unchanged_keeps_hooks_without_reprojection(self):
        seed = self._seed()
        _, store, ingestor = self._reopen(seed)
        events = []
        def checkpoint():
            events.append('checkpoint')
        def before(publication):
            self.assertEqual(publication, seed['publication'])
            events.append('before')
        def publisher(publication):
            self.assertEqual(publication, seed['publication'])
            self.assertTrue(_active(store, publication))
            events.append('publish')
        def forbidden(*args, **kwargs):
            raise AssertionError('unchanged recovery must not rebind or project ASTs')
        with patch.object(ingest_module, 'rebind_ast_record', forbidden), \
                patch.object(ingest_module, 'project_ast_record', forbidden):
            actual = ingestor.ingest_snapshot(_snapshot(), created_at=AT + 1,
                checkpoint=checkpoint, before_publish=before, publish_batch=publisher)
        self.assertEqual(actual, seed['publication'])
        self.assertEqual(events.count('before'), 1)
        self.assertEqual(events.count('publish'), 1)
        self.assertLess(events.index('before'), events.index('publish'))
        self.assertGreater(events.count('checkpoint'), 2)
        prior = ingestor.list_publications()
        def late_failure(publication):
            raise RuntimeError('owner publisher rejected')
        with self.assertRaisesRegex(RuntimeError, 'owner publisher rejected'):
            ingestor.ingest_snapshot(_snapshot(), publish_batch=late_failure)
        self.assertEqual(ingestor.list_publications(), prior)

    def test_options_and_custom_frontend_context_miss(self):
        for frontend in (PythonASTExtractor(max_ast_depth=100),
                         _UnqualifiedPythonFrontend()):
            with self.subTest(frontend=type(frontend).__name__):
                seed = self._seed()
                _, store, ingestor = self._reopen(seed, frontends={'python': frontend})
                self.assertEqual(ingestor.list_publications(), ())
                actual = ingestor.ingest_snapshot(_snapshot(), created_at=AT)
                self.assertEqual(len(actual.projections), 2)
                self.assertEqual(ingestor.stats()['parse_invocations'], 2)
                self.assertTrue(_active(store, actual))
                if type(frontend) is _UnqualifiedPythonFrontend:
                    self.assertEqual(frontend.calls, 2)
        # A language/exclusion/path policy change has a new complete identity,
        # and cannot return the prior admitted publication.
        for changed in (_snapshot(exclusions=('ignored',)),
                        _snapshot({'renamed.py': SOURCES['a.py'], 'b.py': SOURCES['b.py']})):
            seed = self._seed()
            _, _, ingestor = self._reopen(seed)
            actual = ingestor.ingest_snapshot(changed, created_at=AT + 1)
            self.assertNotEqual(actual.revision_id, seed['publication'].revision_id)
            self.assertNotEqual(actual.identity.snapshot.snapshot_cid,
                                seed['snapshot'].snapshot_cid)
        seed = self._seed()
        _, _, ingestor = self._reopen(seed, languages=('javascript',))
        self.assertEqual(ingestor.list_publications(), ())
        actual = ingestor.ingest_snapshot(_snapshot(), created_at=AT)
        self.assertEqual(actual.projections, ())
        self.assertEqual(actual.stats.skipped_count, 2)
        # Already adopted state must preserve the original revision/context
        # collision refusal after an actual parser option change.
        seed = self._seed()
        connection, _, ingestor = self._reopen(seed)
        before = _rows(connection)
        counting = ingestor._frontends['python']
        counting._frontend.feature_version = (3, 10)
        with self.assertRaisesRegex(DuckDBIngestError, 'already binds different'):
            ingestor.ingest_snapshot(_snapshot(), created_at=AT)
        self.assertEqual(counting.parse_invocations, 2)
        self.assertEqual(_rows(connection), before)
        self.assertEqual(ingestor.list_publications(), (seed['publication'],))
        # A context change can leave the AST CID identical. It must still take
        # the normal extraction path; legacy late idempotence may return the
        # original publication after those actual parser calls.
        seed = self._seed()
        connection, _, ingestor = self._reopen(seed)
        before = _rows(connection)
        counting = ingestor._frontends['python']
        counting._frontend.max_ast_depth = 100
        actual = ingestor.ingest_snapshot(_snapshot(), created_at=AT)
        self.assertEqual(counting.parse_invocations, 2)
        self.assertEqual(actual, seed['publication'])
        self.assertEqual(_rows(connection), before)

    def test_fresh_source_bytes_verify_before_reuse(self):
        seed = self._seed()
        connection, _, ingestor = self._reopen(seed)
        before = _rows(connection)
        changed = _snapshot()
        object.__setattr__(changed.entries[0], 'captured_bytes', b'forged source\n')
        with self.assertRaisesRegex(DuckDBIngestError, 'captured bytes do not verify'):
            ingestor.ingest_snapshot(changed, created_at=AT)
        self.assertEqual(_rows(connection), before)
        self.assertEqual(ingestor.stats()['parse_invocations'], 0)
        self.assertEqual(ingestor.list_publications(), (seed['publication'],))

    def test_complete_edit_add_delete_rename_successors(self):
        warm = self._seed('warm-successors')
        cold = self._seed('cold-successors')
        cold_connection, cold_store, cold_ingestor = self._reopen(cold)
        stages = (
            ({'a.py': CHANGED_A, 'b.py': SOURCES['b.py']}, 'source_changed'),
            ({'a.py': CHANGED_A}, 'path_removed'),
            ({'a.py': CHANGED_A, 'new.py': b'new_value = 3\n'}, None),
            ({'a.py': CHANGED_A, 'renamed.py': b'new_value = 3\n'}, 'path_removed'),
        )
        for index, (sources, reason) in enumerate(stages, 1):
            snapshot = _snapshot(sources)
            expected = warm['ingestor'].ingest_snapshot(snapshot, created_at=AT + index)
            actual = cold_ingestor.ingest_snapshot(snapshot, created_at=AT + index)
            self.assertEqual(actual.to_dict(), expected.to_dict())
            self.assertEqual(actual.projections, expected.projections)
            self.assertEqual(actual.invalidations, expected.invalidations)
            self.assertEqual(_rows(cold_connection), _rows(warm['connection']))
            self.assertEqual({p.source_file.path for p in actual.projections}, set(sources))
            self.assertTrue(_active(cold_store, actual))
            self.assertTrue(any(row.reason == 'revision_superseded'
                                for row in actual.invalidations))
            if reason:
                self.assertTrue(any(row.reason == reason for row in actual.invalidations))
        self.assertEqual(actual.stats.renamed_path_count, 1)
        for old in cold['publication'].projections:
            self.assertIsNone(cold_store.get_by_ast_cid(old.ast_cid))
        # The exported successor retains the actual full invalidation bodies.
        expected_cid = cold_ingestor.export_restart_publication(actual.revision_id)
        restored = DuckDBASTIngestor(store=cold_store, restart_publication_cid=expected_cid)
        self.assertEqual(restored.list_publications(), (actual,))
        self.assertEqual(restored.get_publication(actual.revision_id).invalidations,
                         actual.invalidations)

    def test_opaque_only_publication_recovery(self):
        for opaque in (False, True):
            with self.subTest(opaque=opaque):
                seed = self._seed(snapshot=_snapshot({}, opaque=opaque))
                before = _rows(seed['connection'])
                connection, store, ingestor = self._reopen(seed)
                self.assertEqual(ingestor.list_publications(), (seed['publication'],))
                self.assertEqual(seed['publication'].projections, ())
                self.assertEqual(len(seed['publication'].decisions), int(opaque))
                self.assertTrue(_active(store, seed['publication']))
                actual = ingestor.ingest_snapshot(_snapshot({}, opaque=opaque), created_at=AT + 1)
                self.assertEqual(actual, seed['publication'])
                self.assertEqual(_rows(connection), before)
                store.invalidate(revision_id=seed['publication'].revision_id,
                    reason='revision_superseded', actor_id='qualification-fixture',
                    detail='explicit old empty/opaque generation', created_at=AT + 2)
                self.assertFalse(_active(store, seed['publication']))
                with self.assertRaises(DuckDBIngestError):
                    DuckDBASTIngestor(store=store,
                        restart_publication_cid=seed['publication_cid'])
                with self.assertRaises(DuckDBIngestError):
                    ingestor.ingest_snapshot(_snapshot({}, opaque=opaque), created_at=AT + 3)

    def test_external_cid_missing_and_reseal_refused(self):
        seed = self._seed()
        connection, store, _ = self._reopen(seed)
        relation = self._cache_relation(connection)
        missing = cid_for_bytes(b'not admitted by producer')
        with self.assertRaises(DuckDBIngestError):
            DuckDBASTIngestor(store=store, restart_publication_cid=missing)
        changed = copy.deepcopy(json.loads(seed['publication_raw']))
        changed['unadmitted_reseal'] = True
        replacement = canonical_dag_json_bytes(changed)
        resealed = cid_for_bytes(replacement)
        connection.execute('UPDATE ' + relation + ' SET payload=? WHERE cache_cid=?',
                           [replacement, seed['publication_cid']])
        with self.assertRaises(DuckDBASTStoreIntegrityError):
            DuckDBASTIngestor(store=store, restart_publication_cid=seed['publication_cid'])
        connection.execute('UPDATE ' + relation + ' SET cache_cid=? WHERE cache_cid=?',
                           [resealed, seed['publication_cid']])
        self.assertEqual(store.get_source_shard_cache(resealed), replacement)
        with self.assertRaises(DuckDBIngestError):
            DuckDBASTIngestor(store=store, restart_publication_cid=seed['publication_cid'])
        for projection in seed['publication'].projections:
            self.assertEqual(store.get_by_ast_cid(projection.ast_cid), projection)

    def test_malformed_bundle_atomic_adoption(self):
        seed = self._seed()
        connection, store, _ = self._reopen(seed)
        before = _rows(connection)
        document = json.loads(seed['publication_raw'])
        extra = copy.deepcopy(document); extra['unreviewed'] = True
        duplicate = copy.deepcopy(document)
        duplicate['projections'].append(copy.deepcopy(duplicate['projections'][0]))
        missing = copy.deepcopy(document); missing['projections'].pop()
        wrong_timestamp = copy.deepcopy(document)
        wrong_timestamp['publication']['created_at_hex'] = 'nan'
        for value in (extra, duplicate, missing, wrong_timestamp):
            raw = canonical_dag_json_bytes(value)
            admitted = store.put_source_shard_cache(raw)
            with self.subTest(bytes=len(raw)):
                with self.assertRaises((DuckDBIngestError, DuckDBASTStoreError, ValueError)):
                    DuckDBASTIngestor(store=store, restart_publication_cid=admitted)
                self.assertEqual(_rows(connection), before)
        # External CID verification still rejects noncanonical whitespace even
        # when the caller explicitly identifies those exact malformed bytes.
        raw = b' ' + seed['publication_raw']
        admitted = store.put_source_shard_cache(raw)
        with self.assertRaises(DuckDBIngestError):
            DuckDBASTIngestor(store=store, restart_publication_cid=admitted)
        self.assertEqual(_rows(connection), before)

    def test_missing_extra_ast_membership_hydration_refused(self):
        for damage in ('missing', 'extra'):
            with self.subTest(damage=damage):
                seed = self._seed()
                store = seed['store']; connection = seed['connection']
                if damage == 'missing':
                    connection.execute('DELETE FROM ast_blobs WHERE blob_id=?',
                        [seed['publication'].projections[0].blob_id])
                else:
                    store.put_projection(self._extra_projection(seed['publication']))
                before = _rows(connection)
                self.assertFalse(_active(store, seed['publication']))
                with self.assertRaises((DuckDBIngestError, DuckDBASTStoreError)):
                    DuckDBASTIngestor(store=store,
                        restart_publication_cid=seed['publication_cid'])
                self.assertEqual(_rows(connection), before)
        # Public validation refuses a caller-owned transaction before nested
        # BEGIN, so the caller's pending writes survive the refusal.
        seed = self._seed()
        connection = seed['connection']
        connection.execute('CREATE TABLE caller_marker(value INTEGER)')
        connection.execute('BEGIN TRANSACTION')
        connection.execute('INSERT INTO caller_marker VALUES (7)')
        with self.assertRaises(DuckDBASTStoreError):
            _active(seed['store'], seed['publication'])
        self.assertEqual(connection.execute('SELECT value FROM caller_marker').fetchall(), [(7,)])
        connection.execute('INSERT INTO caller_marker VALUES (9)')
        connection.execute('ROLLBACK')
        self.assertEqual(connection.execute('SELECT value FROM caller_marker').fetchall(), [])
        # Unqualified family reads cannot be redirected through a TEMP shadow.
        connection.execute('CREATE TEMP TABLE ast_blobs AS SELECT * FROM main.ast_blobs')
        with self.assertRaises(DuckDBASTStoreError):
            _active(seed['store'], seed['publication'])
        connection.execute('DROP TABLE temp.main.ast_blobs')
        self.assertTrue(_active(seed['store'], seed['publication']))
        connection.execute('CREATE TEMP VIEW symbols AS SELECT * FROM main.symbols')
        with self.assertRaises(DuckDBASTStoreError):
            _active(seed['store'], seed['publication'])
        connection.execute('DROP VIEW temp.main.symbols')
        self.assertTrue(_active(seed['store'], seed['publication']))

    def test_direct_sql_after_hydration_refused(self):
        for damage in ('missing', 'canonical-family', 'early-clock-later-corruption'):
            with self.subTest(damage=damage):
                seed = self._seed()
                connection, store, ingestor = self._reopen(seed)
                if damage == 'missing':
                    connection.execute('DELETE FROM ast_blobs WHERE blob_id=?',
                        [seed['publication'].projections[0].blob_id])
                else:
                    if damage == 'early-clock-later-corruption':
                        first = seed['publication'].projections[0]
                        clock_changed = project_ast_record(ASTRecord.from_dict(
                            json.loads(first.ast_blob.payload_json)), created_at=AT + 1)
                        store.put_projection(clock_changed)
                        self.assertFalse(_active(store, seed['publication']))
                        connection.execute('UPDATE symbols SET name=? WHERE blob_id=?',
                            ['unadmitted-name', seed['publication'].projections[-1].blob_id])
                    else:
                        connection.execute('UPDATE symbols SET name=? WHERE symbol_id=(SELECT symbol_id FROM symbols LIMIT 1)',
                                           ['unadmitted-name'])
                before = _rows(connection)
                context, writes = self._count_writes(store)
                expected_error = DuckDBIngestError if damage == 'missing' else DuckDBASTStoreIntegrityError
                with context, self.assertRaises(expected_error):
                    ingestor.ingest_snapshot(_snapshot(), created_at=AT)
                self.assertEqual(writes, [])
                self.assertEqual(_rows(connection), before)
                self.assertEqual(ingestor.stats()['parse_invocations'], 0)

    def test_catalog_new_operation_retry_stale_head(self):
        seed = self._seed()
        catalog, manifest, first = self._catalog(seed)
        before = _rows(seed['connection'])
        context, writes = self._count_writes(seed['store'])
        with context:
            second = catalog.publish(operation_id='second', manifest=manifest,
                expected_head=first.head, projections=seed['publication'].projections)
            self.assertEqual(second.head.generation, 2)
            self.assertNotEqual(second.cid, first.cid)
            self.assertEqual(catalog.publish(operation_id='second', manifest=manifest,
                expected_head=first.head, projections=seed['publication'].projections), second)
            with self.assertRaises(CodebaseHeadConflict):
                catalog.publish(operation_id='stale', manifest=manifest,
                    expected_head=first.head, projections=seed['publication'].projections)
            with self.assertRaises(CodebaseOperationConflict):
                catalog.publish(operation_id='second', manifest=manifest,
                    expected_head=second.head, projections=seed['publication'].projections)
        self.assertEqual(writes, [])
        self.assertEqual(catalog.current(REPOSITORY_ID), second.head)
        self.assertEqual(_rows(seed['connection']), before)
        self.assertEqual(len(_control(seed['connection'])['operations']), 2)

    def test_catalog_explicit_optout_table_receipt_parity(self):
        observed = []
        for optimized in (True, False):
            seed = self._seed()
            catalog, manifest, first = self._catalog(seed, optimized=optimized)
            before_stats = seed['store'].stats().copy()
            context, writes = self._count_writes(seed['store'])
            with context:
                second = catalog.publish(operation_id='second', manifest=manifest,
                    expected_head=first.head, projections=seed['publication'].projections)
            self.assertEqual(len(writes), 0 if optimized else 2)
            self.assertEqual(seed['store'].stats()['puts'] - before_stats['puts'],
                             0 if optimized else 2)
            observed.append((first.to_dict(), second.to_dict(), _rows(seed['connection']),
                             _control(seed['connection'])))
        self.assertEqual(observed[0], observed[1])

    def test_catalog_timestamp_drift_and_canonical_corruption(self):
        seed = self._seed()
        catalog, manifest, first = self._catalog(seed)
        newer = tuple(project_ast_record(ASTRecord.from_dict(
            json.loads(p.ast_blob.payload_json)), created_at=AT + 1)
            for p in seed['publication'].projections)
        context, writes = self._count_writes(seed['store'])
        with context:
            second = catalog.publish(operation_id='new-clock', manifest=manifest,
                expected_head=first.head, projections=newer)
        self.assertEqual(len(writes), 2)
        self.assertEqual(second.head.generation, 2)
        for projection in newer:
            self.assertEqual(seed['store'].get_by_ast_cid(projection.ast_cid), projection)
        seed['connection'].execute('UPDATE symbols SET name=? WHERE symbol_id=(SELECT symbol_id FROM symbols LIMIT 1)',
                                   ['unadmitted-name'])
        before = _rows(seed['connection']); controls = _control(seed['connection'])
        context, writes = self._count_writes(seed['store'])
        with context, self.assertRaises(DuckDBASTStoreIntegrityError):
            catalog.publish(operation_id='corrupt-family', manifest=manifest,
                expected_head=second.head, projections=newer)
        self.assertEqual(writes, [])
        self.assertEqual(_rows(seed['connection']), before)
        self.assertEqual(_control(seed['connection']), controls)

    def test_catalog_missing_extra_membership_not_empty_batch(self):
        for damage in ('missing', 'extra'):
            with self.subTest(damage=damage):
                seed = self._seed()
                catalog, manifest, first = self._catalog(seed)
                if damage == 'missing':
                    seed['connection'].execute('DELETE FROM ast_blobs WHERE blob_id=?',
                        [seed['publication'].projections[0].blob_id])
                else:
                    seed['store'].put_projection(self._extra_projection(seed['publication']))
                self.assertFalse(_active(seed['store'], seed['publication']))
                controls = _control(seed['connection'])
                damaged_rows = _rows(seed['connection'])
                damaged_stats = seed['store'].stats().copy()
                context, writes = self._count_writes(seed['store'])
                refused = False
                with context:
                    try:
                        actual = catalog.publish(operation_id='damaged-membership', manifest=manifest,
                            expected_head=first.head, projections=seed['publication'].projections)
                    except (DuckDBASTStoreError, CodebaseCatalogError):
                        refused = True
                if refused:
                    self.assertEqual(_control(seed['connection']), controls)
                    self.assertEqual(_rows(seed['connection']), damaged_rows)
                    self.assertEqual(seed['store'].stats(), damaged_stats)
                else:
                    self.assertGreater(len(writes), 0)
                    self.assertTrue(_active(seed['store'], seed['publication']))
                    self.assertEqual(actual.head.generation, 2)
                    expected_connection, expected_store, _ = self._open('repaired-baseline')
                    expected_store.apply_batch(seed['publication'].projections)
                    self.assertEqual(_rows(seed['connection']), _rows(expected_connection))

    def test_catalog_late_cancellation_full_rollback(self):
        for optimized in (True, False):
            with self.subTest(optimized=optimized):
                seed = self._seed()
                catalog, manifest, first = self._catalog(seed, optimized=optimized)
                before = _rows(seed['connection']); controls = _control(seed['connection'])
                stats = seed['store'].stats().copy()
                checkpoint_count = 0
                def checkpoint():
                    nonlocal checkpoint_count
                    checkpoint_count += 1
                    pending = seed['connection'].execute(
                        "SELECT operation_id FROM codebase_control.operations WHERE operation_id='cancelled'").fetchone()
                    if pending is not None:
                        raise InterruptedError('cancelled after tentative control writes')
                with self.assertRaisesRegex(InterruptedError, 'tentative control'):
                    catalog.publish(operation_id='cancelled', manifest=manifest,
                        expected_head=first.head, projections=seed['publication'].projections,
                        checkpoint=checkpoint)
                self.assertGreater(checkpoint_count, 3)
                self.assertEqual(_rows(seed['connection']), before)
                self.assertEqual(_control(seed['connection']), controls)
                self.assertEqual(seed['store'].stats(), stats)
                self.assertEqual(catalog.current(REPOSITORY_ID), first.head)
                self.assertIsNone(catalog.resolve_operation('cancelled',
                    catalog.request_identity(manifest, first.head)))

    def test_catalog_empty_ast_new_generation(self):
        seed = self._seed(snapshot=_snapshot({}, opaque=True))
        catalog, manifest, first = self._catalog(seed)
        before = _rows(seed['connection'])
        second = catalog.publish(operation_id='second', manifest=manifest,
            expected_head=first.head, projections=())
        self.assertEqual(second.head.generation, 2)
        self.assertEqual(catalog.current(REPOSITORY_ID), second.head)
        self.assertEqual(_rows(seed['connection']), before)
        self.assertEqual(len(_control(seed['connection'])['operations']), 2)

    def _owned_preparer(self, name):
        connection, store, _ = self._open(name)
        artifacts = ImmutableCAS(self.root / (name + '-cas'))
        catalog = CodebaseCatalog(store, artifacts)
        repository = self.root / (name + '-repository'); repository.mkdir()
        for path, raw in SOURCES.items():
            (repository / path).write_bytes(raw)
        ingestor = DuckDBASTIngestor(store=store)
        index = RepositoryCodebaseIndex(ingestor=ingestor, artifacts=artifacts, catalog=catalog)
        if OWNED_RESOURCES is None:
            # Direct unit-test invocation owns only a new state file beneath
            # this test's temporary directory. The captured root qualification
            # enters through load_suite(), which refuses this fallback.
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
                GlobalResourceScheduler, ResourceSchedulerConfig,
            )
            scheduler = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
                state_path=self.root / (name + '-private-resources.json'),
                proof_resource_sampler=lambda: ProofHostResources(4, 2048, 2048),
                lane_reservations={}, auto_renew_leases=False,
            ))
            parent_lease = None
        else:
            scheduler, parent_lease = OWNED_RESOURCES
        kwargs = {'scheduler': scheduler if parent_lease is None else None, 'parent_lease': parent_lease,
            'limits': CodebaseScanLimits(max_entries=2, max_file_bytes=4096),
            'memory_mb': 128, 'timeout_seconds': 30, 'admission_timeout_seconds': 0}
        first = index.prepare_current(repository, repository_id=REPOSITORY_ID,
            operation_id='first', expected_head=None, **kwargs)
        return connection, store, catalog, ingestor, index, repository, first, kwargs

    def test_prepare_current_closing_source_fence(self):
        connection, store, catalog, ingestor, index, repository, first, kwargs = self._owned_preparer('source-fence')
        before = _rows(connection); controls = _control(connection)
        prior = ingestor.list_publications()
        native = ingestor.ingest_snapshot
        def changed_after_seal(snapshot, **options):
            before_publish = options['before_publish']
            def changed(publication):
                before_publish(publication)
                (repository / 'a.py').write_bytes(CHANGED_A)
            options['before_publish'] = changed
            return native(snapshot, **options)
        with patch.object(ingestor, 'ingest_snapshot', changed_after_seal), \
                self.assertRaises(StaleCodebaseError):
            index.prepare_current(repository, repository_id=REPOSITORY_ID,
                operation_id='closing-source', expected_head=first.head, **kwargs)
        self.assertEqual(_rows(connection), before)
        self.assertEqual(_control(connection), controls)
        self.assertEqual(ingestor.list_publications(), prior)
        self.assertEqual(catalog.current(REPOSITORY_ID), first.head)

    def test_prepare_current_cancellation_fence(self):
        connection, store, catalog, ingestor, index, repository, first, kwargs = self._owned_preparer('cancel-fence')
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError
        before = _rows(connection); controls = _control(connection)
        prior = ingestor.list_publications(); cancel = threading.Event()
        native = ingestor.ingest_snapshot
        def cancelled_after_seal(snapshot, **options):
            before_publish = options['before_publish']
            def cancelled(publication):
                before_publish(publication)
                cancel.set()
            options['before_publish'] = cancelled
            return native(snapshot, **options)
        with patch.object(ingestor, 'ingest_snapshot', cancelled_after_seal), \
                self.assertRaises(LeaseCancelledError):
            index.prepare_current(repository, repository_id=REPOSITORY_ID,
                operation_id='cancel-fence', expected_head=first.head,
                cancel_event=cancel, **kwargs)
        self.assertEqual(_rows(connection), before)
        self.assertEqual(_control(connection), controls)
        self.assertEqual(ingestor.list_publications(), prior)
        self.assertEqual(catalog.current(REPOSITORY_ID), first.head)

    def _canonical_seed(self, optimized, *, created_at=AT):
        """Two real sources populate every family, including intrinsic failure facts."""
        connection, store, path = self._open(optimized_canonical_validation=optimized)
        sources = {'a.py': (b'from other import helper\nshared = 0\n'
            b'def step(n: int) -> int:\n    global shared\n    shared = n\n'
            b'    return helper(n) + 1\n'), 'b.py': b'def broken(:\n'}
        snapshot = _snapshot(sources)
        ingestor = DuckDBASTIngestor(store=store)
        projected = []
        def publish(publication):
            # Persist only the final synthetic failure projection, avoiding an
            # intermediate replacement with a wall-clock invalidation row.
            actual = tuple(project_parse_failure(provenance=SourceProvenance(
                source_cid=row.source_cid, path=row.source_file.path,
                repository_id=publication.repository_id, revision=publication.revision,
                repository_tree_cid=publication.repository_tree_cid), language='python',
                message='authored parser failure', created_at=created_at)
                if row.source_file.path == 'b.py' else row for row in publication.projections)
            store.apply_batch(actual)
            projected.append(actual)
        publication = ingestor.ingest_snapshot(snapshot, created_at=created_at, publish_batch=publish)
        publication = replace(publication, projections=projected[0])
        return {'connection': connection, 'store': store, 'path': path,
            'snapshot': snapshot, 'ingestor': ingestor, 'publication': publication}

    def test_canonical_validation_exact_bool_preddl(self):
        def forbidden(*args, **kwargs):
            raise AssertionError('invalid canonical flag must fail before schema DDL')
        with patch.object(DuckDBASTStore, 'install_schema', forbidden):
            for invalid in (None, 0, 1, 'true', [], object()):
                with self.subTest(value=repr(invalid)), self.assertRaises(DuckDBASTStoreError):
                    DuckDBASTStore(connection=object(), optimized_canonical_validation=invalid)
        for optimized in (True, False):
            seed = self._canonical_seed(optimized)
            self.assertTrue(_active(seed['store'], seed['publication']))
            self._close(seed['connection'])

    def test_canonical_validation_every_family_corruption(self):
        fields = (('source_revisions', 'revision'), ('source_files', 'path'),
            ('ast_blobs', 'parse_error'), ('ast_nodes', 'label'), ('scopes', 'kind'),
            ('symbols', 'name'), ('imports', 'module'), ('references', 'name'),
            ('calls', 'callee_name'), ('effects', 'subject'), ('interfaces', 'name'),
            ('diagnostics', 'message'), ('invalidations', 'detail'))
        self.assertEqual({table for table, _ in fields}, set(ASTS_CATALOG_TABLES))
        for optimized in (True, False):
            seed = self._canonical_seed(optimized)
            connection, store = seed['connection'], seed['store']
            clean = _rows(connection)
            for table, field in fields + (('ast_blobs', 'payload_json'),):
                with self.subTest(optimized=optimized, table=table, field=field):
                    self.assertGreater(len(clean[table]['rows']), 0)
                    connection.execute('UPDATE main.' + _quote(table) + ' SET ' +
                        _quote(field) + '=?', ['unadmitted-canonical-fact'])
                    damaged = _rows(connection); stats = store.stats().copy()
                    with self.assertRaises(DuckDBASTStoreIntegrityError):
                        _active(store, seed['publication'])
                    self.assertEqual(_rows(connection), damaged)
                    self.assertEqual(store.stats(), stats)
                    # Restore only this deliberately damaged relation from the
                    # captured full rows. This is fixture cleanup, not repair credit.
                    connection.execute('DELETE FROM main.' + _quote(table))
                    query = 'INSERT INTO main.' + _quote(table) + ' VALUES (' + \
                        ','.join('?' for _ in clean[table]['columns']) + ')'
                    for row in clean[table]['rows']:
                        connection.execute(query, list(row))
                    self.assertEqual(_rows(connection), clean)
                    self.assertTrue(_active(store, seed['publication']))
            self._close(connection)

    def test_canonical_validation_clock_header_fallback(self):
        for optimized in (True, False):
            for damage in ('projection-clock', 'failure-header', 'boolean-blob-clock'):
                with self.subTest(optimized=optimized, damage=damage):
                    seed = self._canonical_seed(optimized, created_at=1.0)
                    connection, store, publication = seed['connection'], seed['store'], seed['publication']
                    if damage == 'projection-clock':
                        updated = tuple(store._rebuild(dict(row.ast_blob.to_dict(), created_at=2.0),
                            dict(row.source_revision.to_dict(), created_at=2.0),
                            [item.to_dict() for item in row.diagnostics],
                            [item.to_dict() for item in row.invalidations]) for row in publication.projections)
                        store.apply_batch(updated)
                    elif damage == 'failure-header':
                        failed = publication.projections[-1]
                        changed = replace(failed, ast_blob=replace(failed.ast_blob,
                            frontend_name='other-authored-parser'))
                        store.put_projection(changed)
                        updated = publication.projections[:-1] + (changed,)
                    else:
                        connection.execute('ALTER TABLE main.ast_blobs ALTER COLUMN created_at TYPE BOOLEAN '
                            'USING created_at::BOOLEAN')
                        self.assertIs(type(connection.execute('SELECT created_at FROM main.ast_blobs LIMIT 1').fetchone()[0]), bool)
                    before = _rows(connection); stats = store.stats().copy()
                    if damage == 'boolean-blob-clock':
                        with self.assertRaises(DuckDBASTStoreIntegrityError):
                            _active(store, publication)
                    else:
                        self.assertFalse(_active(store, publication))
                        self.assertTrue(_active(store, replace(publication, projections=updated)))
                    self.assertEqual(_rows(connection), before)
                    self.assertEqual(store.stats(), stats)
                    self._close(connection)

    def test_canonical_validation_parse_failure_parity(self):
        observations = []
        for optimized in (True, False):
            seed = self._canonical_seed(optimized)
            publication, store = seed['publication'], seed['store']
            failure = publication.projections[-1]
            self.assertEqual(failure.ast_blob.parse_status, 'failed')
            self.assertEqual(len(failure.diagnostics), 1)
            self.assertEqual(len(failure.invalidations), 1)
            self.assertTrue(_active(store, publication))
            self.assertEqual(store.get_by_ast_cid(failure.ast_cid), failure)
            observations.append((_rows(seed['connection']), publication.projections))
            self._close(seed['connection'])
        self.assertEqual(observations[0], observations[1])

    def test_canonical_validation_checkpoint_corruption_rollback(self):
        for optimized in (True, False):
            for damage in ('after-membership', 'caller-alias-during-load'):
                with self.subTest(optimized=optimized, damage=damage):
                    seed = self._canonical_seed(optimized)
                    catalog, manifest, first = self._catalog(seed)
                    connection, store, publication = seed['connection'], seed['store'], seed['publication']
                    before, controls, stats = _rows(connection), _control(connection), store.stats().copy()
                    selected = publication.projections[0].symbols[0]
                    original_name = selected.name
                    phase = {'inside': False, 'validated': set(), 'matched': 0, 'mutated': False}
                    native_active, native_validate = store._active_revision_matches, store._validate_projection
                    def active(*args, **kwargs):
                        phase['inside'] = True
                        phase['validated'] = set()
                        try:
                            result = native_active(*args, **kwargs)
                            if result is True:
                                phase['matched'] += 1
                            return result
                        finally:
                            phase['inside'] = False
                    def validate(projection, **kwargs):
                        result = native_validate(projection, **kwargs)
                        if phase['inside']:
                            phase['validated'].add(id(projection))
                        return result
                    def checkpoint():
                        ready = phase['matched'] == 1 if damage == 'after-membership' else \
                            phase['inside'] and len(phase['validated']) == len(publication.projections)
                        if ready and not phase['mutated']:
                            phase['mutated'] = True
                            if damage == 'caller-alias-during-load':
                                object.__setattr__(selected, 'name', 'unadmitted-callback-name')
                            connection.execute('UPDATE main.symbols SET name=? WHERE symbol_id=?',
                                ['unadmitted-callback-name', selected.symbol_id])
                    try:
                        with patch.object(store, '_active_revision_matches', active), \
                                patch.object(store, '_validate_projection', validate), \
                                self.assertRaises(DuckDBASTStoreIntegrityError):
                            catalog.publish(operation_id='callback-corruption', manifest=manifest,
                                expected_head=first.head, projections=publication.projections, checkpoint=checkpoint)
                    finally:
                        object.__setattr__(selected, 'name', original_name)
                    self.assertTrue(phase['mutated'])
                    self.assertEqual(_rows(connection), before)
                    self.assertEqual(_control(connection), controls)
                    self.assertEqual(store.stats(), stats)
                    self.assertEqual(catalog.current(REPOSITORY_ID), first.head)
                    self.assertIsNone(catalog.resolve_operation('callback-corruption',
                        catalog.request_identity(manifest, first.head)))
                    self.assertTrue(_active(store, publication))
                    self._close(connection)

    def test_canonical_validation_checkpoint_membership_rollback(self):
        for optimized in (True, False):
            for damage in ('missing', 'extra'):
                with self.subTest(optimized=optimized, damage=damage):
                    seed = self._canonical_seed(optimized)
                    catalog, manifest, first = self._catalog(seed)
                    connection, store, publication = seed['connection'], seed['store'], seed['publication']
                    before, controls, stats = _rows(connection), _control(connection), store.stats().copy()
                    extra = self._extra_projection(publication)
                    matched, mutations = [], []
                    native_active = store._active_revision_matches
                    def active(*args, **kwargs):
                        result = native_active(*args, **kwargs)
                        if result is True:
                            matched.append(True)
                        return result
                    def checkpoint():
                        if matched and not mutations:
                            mutations.append(damage)
                            if damage == 'missing':
                                connection.execute('DELETE FROM main.ast_blobs WHERE blob_id=?',
                                    [publication.projections[0].blob_id])
                            else:
                                # Use the actual native projection writer inside
                                # the admitted transaction, without nesting BEGIN.
                                store._persist_projection(extra)
                    with patch.object(store, '_active_revision_matches', active), \
                            self.assertRaises((DuckDBASTStoreError, CodebaseCatalogError)):
                        catalog.publish(operation_id='callback-membership', manifest=manifest,
                            expected_head=first.head, projections=publication.projections, checkpoint=checkpoint)
                    self.assertEqual(mutations, [damage])
                    self.assertEqual(_rows(connection), before)
                    self.assertEqual(_control(connection), controls)
                    self.assertEqual(store.stats(), stats)
                    self.assertEqual(catalog.current(REPOSITORY_ID), first.head)
                    self.assertIsNone(catalog.resolve_operation('callback-membership',
                        catalog.request_identity(manifest, first.head)))
                    self.assertTrue(_active(store, publication))
                    self._close(connection)

    def test_canonical_validation_budget_fallback(self):
        seed = self._canonical_seed(True)
        store, publication = seed['store'], seed['publication']
        before, stats = _rows(seed['connection']), store.stats().copy()
        native_rebuild = store._rebuild
        rebuilt = []
        def observed(*args, **kwargs):
            rebuilt.append(args[0]['blob_id'])
            return native_rebuild(*args, **kwargs)
        # Only physical _load reconstruction uses this instance method. Input
        # canonical validation remains the real class-level reconstruction.
        with patch.object(store, '_rebuild', observed):
            self.assertTrue(_active(store, publication))
            self.assertEqual(rebuilt, [])
            for limit in ('_MAX_CANONICAL_REUSE_BLOBS', '_MAX_CANONICAL_REUSE_PAYLOAD_BYTES',
                          '_MAX_CANONICAL_REUSE_ROWS'):
                with self.subTest(limit=limit), patch.object(store_module, limit, 0):
                    rebuilt.clear()
                    self.assertTrue(_active(store, publication))
                    self.assertEqual(len(rebuilt), len(publication.projections))
                    self.assertEqual(_rows(seed['connection']), before)
                    self.assertEqual(store.stats(), stats)
            rebuilt.clear()
            self.assertEqual(store.get_by_ast_cid(publication.projections[0].ast_cid),
                             publication.projections[0])
            self.assertEqual(rebuilt, [publication.projections[0].blob_id])
        self.assertEqual(_rows(seed['connection']), before)


def load_suite():
    if OWNED_RESOURCES is None:
        raise AssertionError('root qualification requires the existing admitted scheduler and parent lease')
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestPublicationRecovery)
    actual = tuple(sorted(test._testMethodName.removeprefix('test_') for test in suite))
    if actual != tuple(sorted(CASE_NAMES)) or suite.countTestCases() != 27:
        raise AssertionError('finite native qualification case inventory differs')
    return suite


if __name__ == '__main__':
    raise SystemExit('root owned captured-module harness must configure and run load_suite()')
