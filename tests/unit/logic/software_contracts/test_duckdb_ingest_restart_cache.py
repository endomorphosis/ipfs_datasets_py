"""Small native restart-cache regressions, without model or profile loading.

Each test uses at most two authored source members. The cache selector is
retained separately from its database bytes. These tests cover historical
parser reuse; they do not grant source-currentness, catalog-head or proof
authority. Root qualification compiles this exact module under selected native
imports and runs its unittest suite. Import alone runs no test or SQL work.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

try:
    import duckdb
except ImportError:
    duckdb = None

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes, cid_for_bytes, cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    DuckDBASTStore, DuckDBASTStoreError, DuckDBASTStoreIntegrityError, SOURCE_SHARD_CACHE_TABLE,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import (
    DuckDBASTIngestor, DuckDBIngestError, SourceShardCache,
    SOURCE_SHARD_RESTART_MAX_BUNDLE_BYTES, SOURCE_SHARD_RESTART_MAX_ENTRIES,
)
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import (
    RepositorySnapshot, SnapshotEntry,
)


SOURCE_A = b'def increment(n):\n    return n + 1\n'
SOURCE_B = b'constant = 2\n'
AT = 1700000000.0


def _snapshot(sources):
    entries = tuple(SnapshotEntry(path, 'source', len(raw),
        source_cid=cid_for_bytes(raw), acquisition='captured',
        disposition='filesystem', captured_bytes=raw)
        for path, raw in sources.items())
    return RepositorySnapshot('restart-cache:unit-fixture', entries, 'filesystem',
        max_entries=2, max_file_bytes=512)


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


@unittest.skipIf(duckdb is None, 'DuckDB is unavailable')
class TestDuckDBIngestRestartCache(unittest.TestCase):
    def setUp(self):
        # The owned qualification runs outside the checkout and permits only
        # this private workspace. No default home or ambient state is selected.
        self.directory = tempfile.TemporaryDirectory(
            prefix='restart-cache-ci-', dir=str(Path.cwd()))
        self.root = Path(self.directory.name)
        self.connections = []

    def tearDown(self):
        for connection in self.connections:
            connection.close()
        self.connections.clear()
        self.directory.cleanup()

    def _open(self, name='cache'):
        connection = duckdb.connect(str(self.root / (name + '.duckdb')), config={
            'threads': 1, 'memory_limit': '128MB', 'enable_external_access': False,
            'autoinstall_known_extensions': False, 'autoload_known_extensions': False,
        })
        self.connections.append(connection)
        return connection, DuckDBASTStore(connection=connection)

    def _close(self, connection):
        connection.close()
        self.connections.remove(connection)

    def _seed(self):
        connection, store = self._open()
        snapshot = _snapshot({'a.py': SOURCE_A, 'b.py': SOURCE_B})
        ingestor = DuckDBASTIngestor(store=store)
        publication = ingestor.ingest_snapshot(snapshot, created_at=AT)
        raw = ingestor.shard_cache.export_bundle()
        expected_cid = ingestor.export_restart_cache()
        self.assertEqual(expected_cid, cid_for_bytes(raw))
        return connection, store, snapshot, publication, raw, expected_cid

    def _persistent_relation(self, connection):
        database, schema = connection.execute(
            'SELECT current_database(), current_schema()').fetchone()
        return '.'.join(_quote(name) for name in (database, schema, SOURCE_SHARD_CACHE_TABLE))

    def test_close_reopen_reuses_exact_shards_and_opt_out_reparses(self):
        connection, _, snapshot, original, _, expected = self._seed()
        self._close(connection)
        connection, store = self._open()
        reused = DuckDBASTIngestor(store=store, restart_cache_cid=expected)
        self.assertEqual(reused.list_publications(), ())
        self.assertEqual(reused.stats()['publication_count'], 0)
        self.assertEqual(len(reused.shard_cache), 2)
        self.assertEqual(store._by_blob, {})
        replay = reused.ingest_snapshot(snapshot, created_at=AT)
        self.assertEqual(replay.projections, original.projections)
        self.assertEqual(replay.identity.to_dict(), original.identity.to_dict())
        self.assertEqual(replay.stats.parsed_count, 0)
        self.assertEqual(replay.stats.reused_count, 2)
        self.assertEqual(reused.stats()['parse_invocations'], 0)
        for projection in replay.projections:
            self.assertEqual(store.get_by_ast_cid(projection.ast_cid), projection)
        self._close(connection)
        _, reference_store = self._open()
        reference = DuckDBASTIngestor(store=reference_store,
            restart_cache_cid=expected, optimized_restart_cache=False)
        self.assertEqual(len(reference.shard_cache), 0)
        self.assertEqual(reference.list_publications(), ())
        fresh = reference.ingest_snapshot(snapshot, created_at=AT)
        self.assertEqual(fresh.projections, original.projections)
        self.assertEqual(fresh.stats.parsed_count, 2)
        self.assertEqual(fresh.stats.reused_count, 0)

    def test_changed_source_path_and_parser_options_have_separate_misses(self):
        _, store, _, _, _, expected = self._seed()
        cases = (
            ({'a.py': SOURCE_A.replace(b'+ 1', b'+ 3'), 'b.py': SOURCE_B}, None, 1, 1),
            ({'renamed.py': SOURCE_A, 'b.py': SOURCE_B}, None, 1, 1),
            ({'a.py': SOURCE_A, 'b.py': SOURCE_B},
                {'python': PythonASTExtractor(max_source_bytes=512)}, 2, 0),
        )
        for sources, frontends, parsed, reused in cases:
            with self.subTest(paths=tuple(sources), changed_options=frontends is not None):
                ingestor = DuckDBASTIngestor(store=store,
                    restart_cache_cid=expected, frontends=frontends)
                actual = ingestor.ingest_snapshot(_snapshot(sources), created_at=AT)
                self.assertEqual(actual.stats.parsed_count, parsed)
                self.assertEqual(actual.stats.reused_count, reused)
                # A fresh native parser supplies independent complete outputs.
                reference = DuckDBASTIngestor(frontends=frontends,
                    optimized_restart_cache=False)
                wanted = reference.ingest_snapshot(_snapshot(sources), created_at=AT)
                self.assertEqual(actual.projections, wanted.projections)

    def test_exact_flags_cid_types_missing_admission_and_opt_out(self):
        _, store = self._open()
        for value in (None, 0, 1, 'true', [], {}):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaisesRegex(DuckDBIngestError, 'exact boolean'):
                    DuckDBASTIngestor(optimized_restart_cache=value)
        missing = cid_for_bytes(b'not admitted to this owner')
        class ForeignCID(str):
            def __eq__(self, other):
                raise AssertionError('CID subclass equality must not execute')
            __hash__ = str.__hash__
        with self.assertRaisesRegex(DuckDBIngestError, 'exact canonical raw CID'):
            DuckDBASTIngestor(restart_cache_cid=ForeignCID(missing))
        with self.assertRaisesRegex(DuckDBIngestError, 'missing from its owner'):
            DuckDBASTIngestor(store=store, restart_cache_cid=missing)
        opted_out = DuckDBASTIngestor(store=store, restart_cache_cid=missing,
            optimized_restart_cache=False)
        self.assertEqual(len(opted_out.shard_cache), 0)
        snapshot = _snapshot({'a.py': SOURCE_A})
        first = opted_out.ingest_snapshot(snapshot, created_at=AT)
        again = opted_out.ingest_snapshot(snapshot, created_at=AT)
        self.assertIs(again, first)
        self.assertEqual(opted_out.stats()['parse_invocations'], 1)
        self.assertEqual(opted_out.stats()['cache_hits'], 1)

    def test_hydration_bad_tail_duplicate_and_noncanonical_are_atomic(self):
        _, _, _, _, raw, _ = self._seed()
        document = json.loads(raw)
        initial = copy.deepcopy(document)
        initial['entries'] = initial['entries'][:1]
        initial_raw = canonical_dag_json_bytes(initial)
        cache = SourceShardCache()
        cache.hydrate_bundle(initial_raw, expected_cid=cid_for_bytes(initial_raw))
        before = cache.export_bundle()
        bad_tail = copy.deepcopy(document)
        bad_tail['entries'][-1]['ast_cid'] = cid_for_structured({'unrelated': True})
        duplicate = copy.deepcopy(document)
        duplicate['entries'].append(copy.deepcopy(duplicate['entries'][-1]))
        unknown = copy.deepcopy(document)
        unknown['entries'][-1]['unreviewed'] = True
        candidates = (canonical_dag_json_bytes(bad_tail),
                      canonical_dag_json_bytes(duplicate),
                      canonical_dag_json_bytes(unknown), b' ' + raw)
        for candidate in candidates:
            with self.subTest(bytes=len(candidate)):
                with self.assertRaises(DuckDBIngestError):
                    cache.hydrate_bundle(candidate, expected_cid=cid_for_bytes(candidate))
                self.assertEqual(cache.export_bundle(), before)
                self.assertEqual(len(cache), 1)
                self.assertEqual((cache.hits, cache.misses), (0, 0))

    def test_bundle_size_or_population_failure_preserves_existing_cache(self):
        _, _, _, _, raw, _ = self._seed()
        document = json.loads(raw)
        cache = SourceShardCache()
        cache.hydrate_bundle(raw, expected_cid=cid_for_bytes(raw))
        before = cache.export_bundle()
        document['entries'] = [document['entries'][0]] * (SOURCE_SHARD_RESTART_MAX_ENTRIES + 1)
        overpopulated = canonical_dag_json_bytes(document)
        with self.assertRaisesRegex(DuckDBIngestError, 'entry count exceeds'):
            cache.hydrate_bundle(overpopulated, expected_cid=cid_for_bytes(overpopulated))
        self.assertEqual(cache.export_bundle(), before)
        oversized = b'x' * (SOURCE_SHARD_RESTART_MAX_BUNDLE_BYTES + 1)
        with self.assertRaisesRegex(DuckDBIngestError, 'exact bounded bytes'):
            cache.hydrate_bundle(oversized, expected_cid=cid_for_bytes(raw))
        self.assertEqual(cache.export_bundle(), before)

    def test_coherent_sql_payload_and_selector_reseal_cannot_replace_external_anchor(self):
        connection, store, _, original, _, expected = self._seed()
        relation = self._persistent_relation(connection)
        replacement = canonical_dag_json_bytes({
            'schema': 'duckdb-ast-ingest/source-shard-restart-cache@1', 'entries': []})
        connection.execute('UPDATE ' + relation + ' SET payload=? WHERE cache_cid=?',
                           [replacement, expected])
        with self.assertRaises(DuckDBASTStoreIntegrityError):
            store.get_source_shard_cache(expected)
        resealed = cid_for_bytes(replacement)
        connection.execute('UPDATE ' + relation + ' SET cache_cid=? WHERE cache_cid=?',
                           [resealed, expected])
        self.assertEqual(store.get_source_shard_cache(resealed), replacement)
        with self.assertRaisesRegex(DuckDBIngestError, 'missing from its owner'):
            DuckDBASTIngestor(store=store, restart_cache_cid=expected)
        for projection in original.projections:
            self.assertEqual(store.get_by_ast_cid(projection.ast_cid), projection)

    def test_temp_shadow_does_not_redirect_persistent_cache_publication(self):
        connection, store = self._open()
        connection.execute('CREATE TEMP TABLE ' + _quote(SOURCE_SHARD_CACHE_TABLE)
                           + ' (cache_cid VARCHAR PRIMARY KEY, payload BLOB NOT NULL)')
        producer = DuckDBASTIngestor(store=store)
        producer.ingest_snapshot(_snapshot({'a.py': SOURCE_A}), created_at=AT)
        raw = producer.shard_cache.export_bundle()
        expected = producer.export_restart_cache()
        temp_relation = '.'.join(_quote(name) for name in ('temp', 'main', SOURCE_SHARD_CACHE_TABLE))
        self.assertEqual(connection.execute('SELECT count(*) FROM ' + temp_relation).fetchone(), (0,))
        self.assertEqual(connection.execute('SELECT count(*) FROM '
            + self._persistent_relation(connection)).fetchone(), (1,))
        self._close(connection)
        _, reopened = self._open()
        self.assertEqual(reopened.get_source_shard_cache(expected), raw)

    def test_caller_transaction_is_preserved_after_nested_cache_refusal(self):
        connection, store = self._open()
        connection.execute('CREATE TABLE caller_marker (value INTEGER)')
        raw = canonical_dag_json_bytes({
            'schema': 'duckdb-ast-ingest/source-shard-restart-cache@1', 'entries': []})
        connection.execute('BEGIN TRANSACTION')
        connection.execute('INSERT INTO caller_marker VALUES (7)')
        for operation in (lambda: store.put_source_shard_cache(raw),
                          lambda: store.get_source_shard_cache(cid_for_bytes(raw))):
            with self.assertRaisesRegex(DuckDBASTStoreError,
                    '^cache operation requires no caller-owned transaction$'):
                operation()
            self.assertEqual(connection.execute('SELECT value FROM caller_marker').fetchall(), [(7,)])
        connection.execute('INSERT INTO caller_marker VALUES (9)')
        connection.execute('ROLLBACK')
        self.assertEqual(connection.execute('SELECT value FROM caller_marker').fetchall(), [])

    def test_changed_captured_bytes_are_rejected_before_historical_cache_use(self):
        _, store, snapshot, original, _, expected = self._seed()
        restarted = DuckDBASTIngestor(store=store, restart_cache_cid=expected)
        object.__setattr__(snapshot.entries[0], 'captured_bytes', b'wrong captured source\n')
        with self.assertRaisesRegex(DuckDBIngestError, 'captured bytes do not verify'):
            restarted.ingest_snapshot(snapshot, created_at=AT)
        self.assertEqual(restarted.list_publications(), ())
        self.assertEqual(restarted.stats()['parse_invocations'], 0)
        self.assertEqual(restarted.stats()['cache_hits'], 0)
        for projection in original.projections:
            self.assertEqual(store.get_by_ast_cid(projection.ast_cid), projection)


if __name__ == '__main__':
    unittest.main()
