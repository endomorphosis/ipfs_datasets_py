"""Durable normalized inventory integrity, migration and transaction boundaries."""
from dataclasses import replace
import json
import shutil
import subprocess
import sys
import threading

import pytest

from ipfs_datasets_py.duckdb_control import codebase_verification_catalog as module
from ipfs_datasets_py.duckdb_control.codebase_verification_queries import CodebaseVerificationSelector as Selector
from ipfs_datasets_py.duckdb_control.codebase_verification_projection import DOMAIN, DEPENDENCY_KINDS, validate_dependency
from ipfs_datasets_py.logic.software_contracts import codebase_verification as verifier
from ipfs_datasets_py.logic.software_verification.pipeline import ContractSpec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError
from tests.unit.duckdb_control.test_codebase_verification_catalog import prepared, publish


def query(prepared, selector=None, **kwargs):
    catalog, _, repository, head, _, _, owner, _, _ = prepared
    options = dict(expected_head=head, selector=selector or Selector(), scheduler=owner)
    options.update(kwargs)
    return catalog.query_current(repository, **options)


@pytest.mark.parametrize("sql", [
    f"DELETE FROM {DOMAIN}.dependencies WHERE kind='source'",
    f"UPDATE {DOMAIN}.dependencies SET value='hidden' WHERE kind='source'",
    f"DELETE FROM {DOMAIN}.entries",
    f"UPDATE {DOMAIN}.entries SET path='hidden.py'",
    f"UPDATE {DOMAIN}.entries SET head_cid='hidden'",
    f"UPDATE {DOMAIN}.dependencies SET entry_id='hidden'",
    f"UPDATE {DOMAIN}.dependencies SET value=repeat('x', 1024*1024) WHERE kind='source'",
])
def test_corruption_cannot_hide_rows_behind_an_empty_result(prepared, sql):
    projected = publish(prepared)
    source = projected.to_dict()['dependencies']['source_cid']
    prepared[7].execute(sql)
    with pytest.raises(module.CodebaseVerificationCatalogError):
        query(prepared, Selector(dependency_kind='source', dependency_value=source))


def test_missing_normalized_key_cannot_hide_native_key_lookup(prepared):
    if any(shutil.which(name) is None for name in ('z3', 'cvc5')):
        pytest.skip('native solver pair unavailable')
    catalog, index, repository, head, _, contract, owner, connection, _ = prepared
    (repository / 'counter.py').write_text('def increment(n: int) -> int:\n    return n + 1\n')
    head = index.prepare_current(repository, repository_id=head.repository_id, expected_head=head,
                                 operation_id='typed-key', scheduler=owner).head
    record = verifier.verify_current_codebase_unit(index, repository, expected_head=head, path='counter.py',
                                                   contracts=[contract], scheduler=owner)
    projected = catalog.publish(repository, expected_head=head, verification_cid=record.artifact_cid,
                                operation_id='typed-key', scheduler=owner)
    key = projected.to_dict()['contracts'][0]['canonical_keys'][0]['key_id']
    connection.execute(f'DELETE FROM {DOMAIN}.keys WHERE key_id=?', [key])
    with pytest.raises(module.CodebaseVerificationCatalogError, match='inventory'):
        query(prepared, Selector(canonical_key_id=key), expected_head=head)


def test_same_head_append_invalidates_cursor_and_reverse_dependencies_are_exact(prepared):
    first = publish(prepared)
    catalog, index, repository, head, _, _, owner, _, _ = prepared
    def append(number):
        record = verifier.verify_current_codebase_unit(index, repository, expected_head=head, path='counter.py',
            contracts=[ContractSpec('increment', postconditions=(f'result == n + {number}',))], scheduler=owner)
        return publish(prepared, verification_cid=record.artifact_cid, operation_id=str(number))
    append(2)
    page = query(prepared, page_size=1)
    assert page.next_cursor and not page.complete
    append(3)
    with pytest.raises(module.CodebaseVerificationCatalogError, match='inventory'):
        query(prepared, page_size=1, cursor=page.next_cursor)
    refreshed = query(prepared, Selector(dependency_kind='source',
        dependency_value=first.to_dict()['dependencies']['source_cid']))
    assert refreshed.complete and len(refreshed.entries) == 3 and refreshed.epoch > page.epoch
    assert refreshed.head == page.head


def test_old_catalog_requires_explicit_native_rebuild_and_survives_restart(prepared):
    projection = publish(prepared)
    catalog, index, repository, head, _, _, owner, connection, root = prepared
    connection.execute(f'DROP SCHEMA {DOMAIN} CASCADE')
    migrated = module.CodebaseVerificationCatalog(index)
    with pytest.raises(module.CodebaseVerificationCatalogError, match='rebuild_current'):
        migrated.query_current(repository, expected_head=head, selector=Selector(), scheduler=owner)
    state = migrated.rebuild_current(repository, expected_head=head, scheduler=owner)
    page = migrated.query_current(repository, expected_head=head, selector=Selector(), scheduler=owner)
    assert page.complete and page.entries[0].projection.projection_cid == projection.projection_cid
    assert page.inventory_cid == state.inventory_cid
    connection.close()
    code = '''
import json,sys
from pathlib import Path
import duckdb
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog,CodebaseHead
from ipfs_datasets_py.duckdb_control.codebase_verification_catalog import CodebaseVerificationCatalog
from ipfs_datasets_py.duckdb_control.codebase_verification_queries import CodebaseVerificationSelector
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler,ResourceSchedulerConfig
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
root=Path(sys.argv[1]); head=CodebaseHead.from_dict(json.loads(sys.argv[2]))
cx=duckdb.connect(str(root/'catalog.duckdb'),config={'threads':1,'memory_limit':'64MB'})
store=DuckDBASTStore(connection=cx); cas=ImmutableCAS(root/'artifacts')
index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=cas,catalog=CodebaseCatalog(store,cas))
owner=GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(state_path=root/'restart-query.json',
    proof_resource_sampler=lambda:ProofHostResources(8,8192,8192),lane_reservations={},auto_renew_leases=False))
page=CodebaseVerificationCatalog(index).query_current(root/'source',expected_head=head,
    selector=CodebaseVerificationSelector(),scheduler=owner)
assert page.complete and page.inventory_cid==sys.argv[3] and len(page.entries)==1
assert page.entries[0].projection.verification.observed_live is False
assert not page.to_dict()['authority']['behavioral_satisfaction']
assert owner.snapshot()['active_lease_count']==0
cx.close()
'''
    subprocess.run([sys.executable, '-c', code, str(root), json.dumps(head.to_dict()), state.inventory_cid],
                   check=True, capture_output=True, timeout=30)


def test_rebuild_cancellation_rolls_back_epoch_and_all_normalized_rows(prepared, monkeypatch):
    publish(prepared)
    catalog, _, repository, head, _, _, owner, connection, _ = prepared
    before = query(prepared)
    snapshots = {table: connection.execute(f'SELECT * FROM {DOMAIN}.{table} ORDER BY 1').fetchall()
                 for table in ('inventories', 'entries', 'keys', 'dependencies')}
    original = catalog._queries.synchronize
    def cancel_after_write(**kwargs):
        original(**kwargs)
        raise LeaseCancelledError('cancelled before commit')
    monkeypatch.setattr(catalog._queries, 'synchronize', cancel_after_write)
    with pytest.raises(LeaseCancelledError):
        catalog.rebuild_current(repository, expected_head=head, scheduler=owner)
    for table, rows in snapshots.items():
        assert connection.execute(f'SELECT * FROM {DOMAIN}.{table} ORDER BY 1').fetchall() == rows
    monkeypatch.setattr(catalog._queries, 'synchronize', original)
    assert query(prepared).inventory_cid == before.inventory_cid


def test_explicit_rebuild_repairs_deleted_derived_row_but_invalidates_epoch(prepared):
    publish(prepared)
    catalog, _, repository, head, _, _, owner, connection, _ = prepared
    previous = query(prepared)
    connection.execute(f"DELETE FROM {DOMAIN}.dependencies WHERE kind='source'")
    state = catalog.rebuild_current(repository, expected_head=head, scheduler=owner)
    assert state.epoch > previous.epoch and state.inventory_cid != previous.inventory_cid
    assert len(query(prepared).entries) == 1


def test_normalized_row_capacity_refuses_atomically(prepared):
    catalog, index, repository, head, record, _, owner, connection, _ = prepared
    bounded = module.CodebaseVerificationCatalog(index, limits=replace(catalog.limits, max_query_dependencies=1))
    with pytest.raises(module.CodebaseVerificationCatalogError, match='row bounds'):
        bounded.publish(repository, expected_head=head, verification_cid=record.artifact_cid,
                        operation_id='capacity', scheduler=owner)
    assert connection.execute('SELECT count(*) FROM codebase_verification_control.records').fetchone()[0] == 0
    assert connection.execute(f'SELECT count(*) FROM {DOMAIN}.entries').fetchone()[0] == 0


def test_missing_or_corrupted_inventory_cas_refuses_query_and_exact_replay(prepared):
    publish(prepared)
    page = query(prepared)
    prepared[1].artifacts.path_for(page.inventory_cid).write_bytes(b'{}')
    with pytest.raises(module.CodebaseVerificationCatalogError):
        query(prepared)
    with pytest.raises(module.CodebaseVerificationCatalogError):
        publish(prepared)


def test_native_concurrent_head_writer_conflicts_without_changing_complete_head(prepared, monkeypatch):
    duckdb = pytest.importorskip('duckdb')
    catalog, _, _, _, _, _, _, connection, root = prepared
    before = connection.execute('SELECT * FROM codebase_control.heads').fetchall()
    competing = duckdb.connect(str(root/'catalog.duckdb'), config={'threads': 1, 'memory_limit': '64MB'})
    original = catalog._queries.synchronize
    seen = []
    def racing_writer(**kwargs):
        try:
            competing.execute('UPDATE codebase_control.heads SET generation=generation+1')
        except duckdb.TransactionException:
            seen.append('conflict')
        else:
            pytest.fail('competing writer bypassed native head conflict guard')
        return original(**kwargs)
    monkeypatch.setattr(catalog._queries, 'synchronize', racing_writer)
    try:
        publish(prepared)
    finally:
        competing.close()
    assert seen and connection.execute('SELECT * FROM codebase_control.heads').fetchall() == before


def test_dependency_vocabulary_is_closed_and_preserves_identity_types(prepared):
    publish(prepared)
    assert {'source', 'ast', 'ast_revision', 'authored_contract', 'lowered_contract', 'canonical_assumptions'} <= DEPENDENCY_KINDS
    with pytest.raises(module.CodebaseVerificationCatalogError):
        validate_dependency('model', 'imagined')
    with pytest.raises(module.CodebaseVerificationCatalogError):
        validate_dependency('source', prepared[3].snapshot_cid)
    with pytest.raises(module.CodebaseVerificationCatalogError):
        validate_dependency('canonical_environment', 'unknown')


def test_missing_inventory_rebuild_uses_independent_monotonic_epoch(prepared):
    publish(prepared)
    catalog, _, repository, head, _, _, owner, connection, _ = prepared
    previous = query(prepared)
    connection.execute(f'DELETE FROM {DOMAIN}.inventories')
    with pytest.raises(module.CodebaseVerificationCatalogError, match='rebuild_current'):
        query(prepared)
    rebuilt = catalog.rebuild_current(repository, expected_head=head, scheduler=owner)
    assert rebuilt.epoch > previous.epoch and rebuilt.inventory_cid != previous.inventory_cid
    connection.execute(f'DELETE FROM {DOMAIN}.inventories')
    again = catalog.rebuild_current(repository, expected_head=head, scheduler=owner)
    assert again.epoch > rebuilt.epoch and again.inventory_cid != rebuilt.inventory_cid


def test_missing_epoch_allocator_cannot_be_recreated_on_restart(prepared):
    publish(prepared)
    prepared[7].execute(f'DELETE FROM {DOMAIN}.epochs')
    with pytest.raises(module.CodebaseVerificationCatalogError, match='allocator'):
        module.CodebaseVerificationCatalog(prepared[1])


def test_deleted_source_inventory_cannot_silently_clear_residual_rows(prepared):
    publish(prepared)
    connection = prepared[7]
    connection.execute('DELETE FROM codebase_verification_control.records')
    connection.execute(f'DELETE FROM {DOMAIN}.inventories')
    before = connection.execute(f'SELECT * FROM {DOMAIN}.entries').fetchall()
    with pytest.raises(module.CodebaseVerificationCatalogError, match='retains normalized'):
        query(prepared)
    assert connection.execute(f'SELECT * FROM {DOMAIN}.entries').fetchall() == before
