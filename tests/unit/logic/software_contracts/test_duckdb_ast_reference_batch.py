"""Small native reference-batching regressions, without model/profile dependencies.

Native execution belongs to the root's captured-module qualification child.
Every SQL recording facade delegates to a real private DuckDB connection.
Import alone runs no test or SQL work. Each ingest fixture has at most two
captured source entries and distinguishes prepared parser shards from committed
store indexes and catalog rows.
"""
from __future__ import annotations

import copy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

try:
    import duckdb
except ImportError:
    duckdb = None

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes, cid_for_structured
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    ASTS_CATALOG_TABLES, DuckDBASTStore, DuckDBASTStoreError,
    MAX_NODE_INSERT_ROWS, MAX_NODE_INSERT_STRING_BYTES,
    MAX_REFERENCE_INSERT_ROWS, MAX_REFERENCE_INSERT_STRING_BYTES, project_ast_record,
)
from ipfs_datasets_py.logic.software_contracts.ast_ir import ASTIRValidationError
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import RepositorySnapshot, SnapshotEntry

AT = 1700000000.0
CANONICAL_REFERENCE_MAX_ESTIMATED_STRING_BYTES = 4 * (2 * 66 + 11 + 3 * 512 + 2048 + 128)
RICH_SOURCE = b'import math\nclass Counter:\n    def __init__(self, value=0):\n        self.value = value\n    def step(self, amount=1):\n        self.value += amount\n        return math.floor(self.value)\ndef run():\n    result = Counter(2).step()\n    return result\n'


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def _heavy(count=100):
    return ('import math\n' + ''.join('value_%04d = math.floor(%d)\n' % (index, index)
                                    for index in range(count))).encode('ascii')


def _unicode_references():
    names = [('café_%03d_' % index).ljust(500, 'x') for index in range(4)]
    return (names[0] + ' = 0\n' + ('.'.join(names) + '\n') * 15).encode('utf-8')


def _snapshot(sources):
    entries = tuple(SnapshotEntry(path, 'source', len(raw), source_cid=cid_for_bytes(raw),
        acquisition='captured', disposition='filesystem', captured_bytes=raw)
        for path, raw in sources.items())
    return RepositorySnapshot('reference-batch:ci', entries, 'filesystem',
                              max_entries=2, max_file_bytes=1024 * 1024)


def _record(raw, path='source.py'):
    return PythonASTExtractor().extract(raw, path=path, repository_id='reference-batch:ci-record',
        revision='fixed-native-fixture', repository_tree_cid=cid_for_structured({'fixture': 'native-ci-store'}))


def _comparable(full):
    result = copy.deepcopy(full)
    columns = result['tables']['invalidations']['columns']; rows = []
    for values in result['tables']['invalidations']['rows']:
        row = dict(zip(columns, values))
        if row['reason'] == 'blob_replaced' and row['actor_id'] == 'duckdb-ast-store':
            timestamp = row['created_at']
            if type(timestamp) not in (int, float) or not 0 <= timestamp <= 2 ** 40:
                raise AssertionError('native invalidation timestamp must be finite')
            prefix = 'inv:' + (row['blob_id'] or row['file_id'] or row['revision_id'] or 'global') + ':blob_replaced:'
            if row['invalidation_id'] != prefix + str(int(timestamp * 1000000)):
                raise AssertionError('native invalidation ID must bind its unmodified timestamp')
            row['invalidation_id'] = prefix + '<native-clock>'; row['created_at'] = 0.0
        rows.append([row[name] for name in columns])
    result['tables']['invalidations']['rows'] = sorted(rows, key=_wire)
    return result


class _NativeSQL:
    def __init__(self, connection):
        self.connection = connection
        self.enabled = False
        self.nodes = []
        self.references = []

    def execute(self, query, parameters=None, **kwargs):
        if self.enabled and isinstance(query, str):
            normalized = ' '.join(query.split()).upper()
            if normalized.startswith('INSERT INTO AST_NODES VALUES'):
                destination, width, maximum = self.nodes, 15, MAX_NODE_INSERT_STRING_BYTES
            elif normalized.startswith('INSERT INTO "REFERENCES" VALUES'):
                destination, width, maximum = self.references, 13, MAX_REFERENCE_INSERT_STRING_BYTES
            else:
                destination = None
            if destination is not None:
                if not isinstance(parameters, (list, tuple)) or not parameters or len(parameters) % width:
                    raise AssertionError('actual native INSERT must bind its unchanged row width')
                count = len(parameters) // width
                budget = sum(4 * str.__len__(value) for value in parameters if isinstance(value, str))
                if not 1 <= count <= 64 or (count > 1 and budget > maximum):
                    raise AssertionError('actual native INSERT must respect row and conservative string bounds')
                destination.append({'rows': count, 'budget': budget, 'oversized': count == 1 and budget > maximum})
        if parameters is None:
            return self.connection.execute(query, **kwargs)
        return self.connection.execute(query, parameters, **kwargs)

    def __getattr__(self, name):
        return getattr(self.connection, name)


class _Rollback(Exception):
    pass


@unittest.skipIf(duckdb is None, 'DuckDB is unavailable')
class TestDuckDBASTReferenceBatch(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='reference-batch-ci-', dir=str(Path.cwd()))
        self.root = Path(self.directory.name)
        self.connections = []
        self.serial = 0

    def tearDown(self):
        for connection in self.connections:
            connection.close()
        self.connections.clear()
        self.directory.cleanup()

    def _open(self, *, flag=None, node_flag=True, label=None, record_sql=False):
        self.serial += 1
        path = self.root / ((label or ('lane-%d' % self.serial)) + '.duckdb')
        connection = duckdb.connect(str(path), config={
            'threads': 1, 'memory_limit': '128MB', 'enable_external_access': False,
            'autoinstall_known_extensions': False, 'autoload_known_extensions': False})
        self.connections.append(connection)
        probe = _NativeSQL(connection)
        kwargs = {'optimized_node_inserts': node_flag}
        if flag is not None:
            kwargs['optimized_reference_inserts'] = flag
        store = DuckDBASTStore(connection=probe if record_sql else connection, **kwargs)
        probe.enabled = record_sql
        return connection, store, probe

    def _close(self, connection):
        connection.close(); self.connections.remove(connection)

    def _tables(self, connection):
        self.assertEqual(len(ASTS_CATALOG_TABLES), 13)
        result = {}
        for name in ASTS_CATALOG_TABLES:
            cursor = connection.execute('SELECT * FROM "' + name + '"')
            result[name] = {'columns': [value[0] for value in cursor.description],
                            'rows': sorted([list(row) for row in cursor.fetchall()], key=_wire)}
        return result

    def _observe(self, connection, store, projection):
        self.assertEqual(store.get_by_ast_cid(projection.ast_cid), projection)
        return {'projection': asdict(projection), 'tables': self._tables(connection), 'stats': store.stats()}

    def test_invalid_independent_flags_are_refused_before_native_schema_installation(self):
        connection = duckdb.connect(str(self.root / 'flags.duckdb'), config={
            'threads': 1, 'memory_limit': '128MB', 'enable_external_access': False,
            'autoinstall_known_extensions': False, 'autoload_known_extensions': False})
        self.connections.append(connection)
        before = connection.execute('SELECT table_name FROM information_schema.tables ORDER BY table_name').fetchall()
        for field in ('optimized_node_inserts', 'optimized_reference_inserts'):
            for value in (None, 0, 1, 'true', [], {}):
                with self.subTest(field=field, value_type=type(value).__name__):
                    with self.assertRaisesRegex(DuckDBASTStoreError, '^' + field + ' must be an exact boolean$'):
                        DuckDBASTStore(connection=connection, **{field: value})
                    self.assertEqual(connection.execute('SELECT table_name FROM information_schema.tables ORDER BY table_name').fetchall(), before)
        memory = []
        native = _record(b'value=0\nvalue\n')
        for node_flag in (False, True):
            for reference_flag in (False, True):
                store = DuckDBASTStore(optimized_node_inserts=node_flag, optimized_reference_inserts=reference_flag)
                projection = store.put(native, created_at=AT)
                memory.append((asdict(store.get_by_ast_cid(projection.ast_cid)), store.stats()))
        self.assertTrue(all(row == memory[0] for row in memory))

    def test_native_reference_batches_independent_node_flags_and_exact_boundaries(self):
        native = _record(_heavy())
        observed, combinations = [], []
        for node_flag in (False, True):
            for reference_flag in (False, True):
                connection, store, probe = self._open(flag=reference_flag, node_flag=node_flag, record_sql=True)
                projection = store.put(native, created_at=AT)
                self.assertGreater(len(projection.references), 256)
                observed.append(self._observe(connection, store, projection))
                for enabled, events, count in ((node_flag, probe.nodes, len(projection.nodes)),
                                              (reference_flag, probe.references, len(projection.references))):
                    self.assertEqual(sum(event['rows'] for event in events), count)
                    if enabled:
                        self.assertTrue(any(event['rows'] > 1 for event in events))
                    else:
                        self.assertTrue(all(event['rows'] == 1 for event in events))
                combinations.append((node_flag, reference_flag)); self._close(connection)
        self.assertEqual(combinations, [(False, False), (False, True), (True, False), (True, True)])
        self.assertTrue(all(row == observed[0] for row in observed))
        for wanted in (63, 64, 65):
            native = _record(('value=0\n' + 'value\n' * (wanted - 1)).encode('ascii'))
            pair, recorded = [], []
            for flag in (False, None):
                connection, store, probe = self._open(flag=flag, record_sql=True)
                projection = store.put(native, created_at=AT)
                self.assertEqual(len(projection.references), wanted)
                pair.append(self._observe(connection, store, projection)); recorded.append(probe.references)
                self._close(connection)
            self.assertEqual(pair[0], pair[1])
            self.assertEqual([event['rows'] for event in recorded[0]], [1] * wanted)
            self.assertLessEqual(recorded[1][0]['budget'], MAX_REFERENCE_INSERT_STRING_BYTES)
            self.assertEqual([event['rows'] for event in recorded[1]], [wanted] if wanted <= 64 else [64, 1])

    def test_unicode_byte_flush_and_closed_reference_row_bounds_preserve_rows(self):
        native = _record(_unicode_references())
        observed, events = [], []
        for flag in (False, None):
            connection, store, probe = self._open(flag=flag, record_sql=True)
            projection = store.put(native, created_at=AT)
            self.assertEqual(len(projection.references), 61)
            self.assertTrue(all(len(row.name) <= 2048 and len(row.reference_id) <= 512
                                and len(row.scope_id) <= 512 and len(row.blob_id) == 66
                                for row in projection.references))
            observed.append(self._observe(connection, store, projection)); events.append(probe.references)
            self._close(connection)
        self.assertEqual(observed[0], observed[1])
        self.assertEqual([event['rows'] for event in events[0]], [1] * 61)
        self.assertGreater(len(events[1]), 1)
        self.assertTrue(all(event['rows'] < 64 and event['budget'] <= MAX_REFERENCE_INSERT_STRING_BYTES
                            and not event['oversized'] for event in events[1]))
        self.assertGreater(sum(event['budget'] for event in events[1]), MAX_REFERENCE_INSERT_STRING_BYTES)
        self.assertLess(CANONICAL_REFERENCE_MAX_ESTIMATED_STRING_BYTES, MAX_REFERENCE_INSERT_STRING_BYTES)
        # Canonical reference names are bounded, not opaque JSON payload rows.
        # This exercises the public schema refusal; it grants no oversized SQL credit.
        damaged = native.references[0].to_dict(); damaged['name'] = 'x' * 2049
        with self.assertRaises(ASTIRValidationError):
            type(native.references[0]).from_dict(damaged)

    def test_repeat_replacement_and_native_parse_failure_keep_complete_history(self):
        records = [_record(_heavy(20)), _record(_heavy(20)),
                   _record(_heavy(21)), _record(b'def broken(:\n')]
        history = []
        for flag in (False, None):
            connection, store, _ = self._open(flag=flag)
            steps = []
            for native in records:
                projection = store.put(native, created_at=AT)
                steps.append(self._observe(connection, store, projection))
            self.assertEqual(projection.ast_blob.parse_status, 'failed')
            self.assertEqual(store.stats()['puts'], 4)
            self.assertTrue(any(row['reason'] == 'blob_replaced' for row in
                                [dict(zip(steps[-1]['tables']['invalidations']['columns'], value))
                                 for value in steps[-1]['tables']['invalidations']['rows']]))
            history.append(steps)
        self.assertEqual([_comparable(row) for row in history[0]], [_comparable(row) for row in history[1]])

    def test_late_before_commit_rolls_back_rows_counters_and_committed_indexes(self):
        initial = _record(b'value = 1\n'); replacement = _record(_heavy())
        recovered = []
        for flag in (False, None):
            connection, store, _ = self._open(flag=flag)
            store.put(initial, created_at=AT)
            marker = b'private committed source-shard artifact'
            marker_cid = store.put_source_shard_cache(marker)
            prepared = project_ast_record(replacement, created_at=AT)
            before = self._tables(connection), store.stats(), copy.deepcopy((store._by_blob,
                store._by_ast_cid, store._by_file, store._invalidations, store._source_shard_cache_payloads))
            reached = []
            def late_refusal(native_connection):
                count = native_connection.execute('SELECT count(*) FROM "references" WHERE blob_id=?', [prepared.blob_id]).fetchone()[0]
                self.assertEqual(count, len(prepared.references)); self.assertGreater(count, 256)
                reached.append(count); raise _Rollback('controlled late native refusal')
            with self.assertRaises(_Rollback):
                store.apply_batch((prepared,), before_commit=late_refusal)
            self.assertEqual(reached, [len(prepared.references)])
            self.assertEqual(self._tables(connection), before[0]); self.assertEqual(store.stats(), before[1])
            self.assertEqual(store.get_source_shard_cache(marker_cid), marker)
            self.assertEqual((store._by_blob, store._by_ast_cid, store._by_file,
                              store._invalidations, store._source_shard_cache_payloads), before[2])
            store.apply_batch((prepared,)); recovered.append(self._observe(connection, store, prepared))
        self.assertEqual(_comparable(recovered[0]), _comparable(recovered[1]))

    def test_full_ingestion_preserves_decisions_failure_invalidations_and_counters(self):
        snapshot = _snapshot({'a.py': _heavy() + RICH_SOURCE, 'broken.py': b'def broken(:\n'})
        observed = []
        for flag in (False, None):
            connection, store, _ = self._open(flag=flag)
            ingestor = DuckDBASTIngestor(store=store)
            publication = ingestor.ingest_snapshot(snapshot, created_at=AT)
            self.assertEqual(publication.stats.parse_failed_count, 1)
            kinds = {node.node_kind for projection in publication.projections for node in projection.nodes}
            self.assertTrue({'module','scope','symbol','import','reference','call','effect','interface'} <= kinds)
            observed.append({'public': publication.to_dict(), 'projections': [asdict(value) for value in publication.projections],
                'tables': self._tables(connection), 'store_stats': store.stats(), 'ingestor_stats': ingestor.stats()})
        self.assertEqual(observed[0], observed[1])

    def test_trusted_hydrated_source_reuse_preserves_native_reference_publication(self):
        snapshot = _snapshot({'a.py': _heavy(), 'b.py': b'constant = 2\n'})
        seed_connection, seed_store, _ = self._open(label='seed')
        seed = DuckDBASTIngestor(store=seed_store)
        seed.ingest_snapshot(snapshot, created_at=AT)
        raw = seed.shard_cache.export_bundle(); expected = seed.export_restart_cache()
        self.assertEqual(expected, cid_for_bytes(raw)); self._close(seed_connection)
        observed = []
        for flag in (False, None):
            connection, store, _ = self._open(flag=flag)
            self.assertEqual(store.put_source_shard_cache(raw), expected)
            ingestor = DuckDBASTIngestor(store=store, restart_cache_cid=expected)
            self.assertEqual(ingestor.list_publications(), ())
            publication = ingestor.ingest_snapshot(snapshot, created_at=AT)
            self.assertEqual(ingestor.stats()['parse_invocations'], 0)
            self.assertEqual(publication.stats.parsed_count + publication.stats.parse_failed_count,
                             ingestor.stats()['parse_invocations'])
            self.assertEqual(publication.stats.reused_count, 2)
            observed.append({'public': publication.to_dict(), 'projections': [asdict(value) for value in publication.projections],
                'tables': self._tables(connection), 'store_stats': store.stats(), 'ingestor_stats': ingestor.stats()})
        self.assertEqual(observed[0], observed[1])


if __name__ == '__main__':
    unittest.main()
