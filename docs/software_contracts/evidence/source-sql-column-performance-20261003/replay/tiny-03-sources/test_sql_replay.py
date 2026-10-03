"""Tiny diagnostic controls only; never opens the retained benchmark database."""
import json
from pathlib import Path

import duckdb
import pytest

import sql_replay as harness
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore, ASTS_CATALOG_TABLES, project_ast_record
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor

CANDIDATE = Path('/home/barberb/lift_coding/artifacts/source384-sql-vector-candidate-20261003/vector_candidate.py')
CANDIDATE_SHA = 'be404be397941857bc21f2b99af2240a29a4dc7944018bd6a1f72ce70736b72c'


@pytest.fixture
def tiny(tmp_path):
    database = tmp_path / 'original.duckdb'
    projections = tuple(project_ast_record(PythonASTExtractor().extract_from_source(
        'def answer(x):\n    return x if x is not None else "λ"\n',
        path=path, repository_id='diagnostic:tiny', revision='tiny'), created_at=1.25)
        for path in ('a.py', 'b.py'))
    with duckdb.connect(str(database), config=harness.CONFIG) as connection:
        DuckDBASTStore(connection=connection).apply_batch(projections)
        tables = harness.table_inventory(connection)
    value = dict(schema=harness.SCHEMA, producer=harness.pins(),
        inputs=[dict(blob=p.ast_blob.to_dict(), revision=p.source_revision.to_dict(),
                     diagnostics=[v.to_dict() for v in p.diagnostics],
                     invalidations=[v.to_dict() for v in p.invalidations]) for p in projections],
        tables=tables, source={'diagnostic_fixture': True},
        export_read_only=True, contains_model_weights=False)
    path = tmp_path / 'tiny.json'
    digest = harness.write(path, value)
    return path, digest, value


@pytest.mark.parametrize('candidate', [False, True])
def test_tiny_native_replay_keeps_every_table_and_cold_read(tiny, tmp_path, candidate):
    path, digest, corpus = tiny
    original = DuckDBASTStore._insert_rows
    options = dict(candidate_path=CANDIDATE, candidate_sha256=CANDIDATE_SHA) if candidate else {}
    report = harness.replay(path, digest, tmp_path / 'replay', **options)
    assert report['qualified'] and report['all_table_parity'] and report['cold_native_replay']
    assert report['tables'] == corpus['tables'] and set(report['tables']) == set(ASTS_CATALOG_TABLES)
    assert report['platform']['duckdb_settings']['threads'] == '1'
    assert report['producer_before'] == report['producer_after']
    assert report['execute_groups']['INSERT:symbols']['insert_rows'] == corpus['tables']['symbols']['rows']
    assert report['execute_groups']['INSERT:symbols']['scalar_parameters'] > 0
    assert DuckDBASTStore._insert_rows is original
    assert report['provider_calls'] == report['model_loads'] == report['training_steps'] == 0


def test_proxy_passes_original_parameter_object_and_cursor():
    cursor = object()
    class Native:
        def execute(self, *args):
            self.args = args
            return cursor
    native = Native()
    proxy = harness.ExecuteTiming(native)
    parameters = ['λ', None, True]
    assert proxy.execute('INSERT INTO symbols VALUES (?,?,?)', parameters) is cursor
    assert native.args[1] is parameters
    assert proxy.groups['INSERT:symbols']['parameters'] == 3


def test_proxy_preserves_exception_identity():
    failure = RuntimeError('injected')
    class Native:
        def execute(self, *args): raise failure
    proxy = harness.ExecuteTiming(Native())
    with pytest.raises(RuntimeError) as caught:
        proxy.execute('INSERT INTO symbols VALUES (?)', ['λ'])
    assert caught.value is failure
    assert proxy.groups['INSERT:symbols']['failures'] == 1


def test_tampered_corpus_refused_before_database(tiny, tmp_path):
    path, digest, _ = tiny
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError, match='digest'):
        harness.replay(path, digest, tmp_path / 'bad')
    assert not (tmp_path / 'bad/replay.duckdb').exists()


def test_corpus_row_digest_mismatch_cannot_qualify(tiny, tmp_path, monkeypatch):
    path, _, corpus = tiny
    corpus['tables']['symbols']['sha256'] = '0' * 64
    path.write_bytes(harness.raw(corpus))
    native = DuckDBASTStore._insert_rows
    stores = []
    def capture(self, statement, rows):
        stores.append(self)
        return native(self, statement, rows)
    monkeypatch.setattr(DuckDBASTStore, '_insert_rows', capture)
    original = DuckDBASTStore._insert_rows
    with pytest.raises(ValueError, match='row digest'):
        harness.replay(path, harness.sha(path.read_bytes()), tmp_path / 'bad')
    report = json.loads((tmp_path / 'bad/receipt.json').read_text())
    assert report['qualified'] is False and DuckDBASTStore._insert_rows is original
    assert stores and all(not isinstance(store._connection, harness.ExecuteTiming) for store in stores)


def test_native_producer_mismatch_refused(tiny, tmp_path):
    path, _, corpus = tiny
    corpus['producer'][harness.OWNER_NAMES[0]] = '0' * 64
    path.write_bytes(harness.raw(corpus))
    with pytest.raises(ValueError, match='producer'):
        harness.replay(path, harness.sha(path.read_bytes()), tmp_path / 'bad')
    assert not (tmp_path / 'bad/replay.duckdb').exists()


def test_selected_candidate_digest_required(tiny, tmp_path):
    path, digest, _ = tiny
    with pytest.raises(ValueError, match='candidate digest'):
        harness.replay(path, digest, tmp_path / 'bad', candidate_path=CANDIDATE,
                       candidate_sha256='0' * 64)
    assert not (tmp_path / 'bad/replay.duckdb').exists()


@pytest.mark.parametrize('damage', [False, True])
def test_export_head_binds_actual_control_row(damage):
    head = dict(repository_id='repo', generation=1, manifest_cid='m', snapshot_cid='s',
                ast_revision_id='ast', receipt_cid='r')
    class ReadOnlyHead:
        def execute(self, query, args):
            assert query.startswith('SELECT ') and args == ['repo']
            return self
        def fetchall(self):
            return [('repo', 2 if damage else 1, 'm', 's', 'ast', 'r')]
    if damage:
        with pytest.raises(ValueError, match='head differs'):
            harness.require_retained_head(ReadOnlyHead(), head)
    else:
        harness.require_retained_head(ReadOnlyHead(), head)
