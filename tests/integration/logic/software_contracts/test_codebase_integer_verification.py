"""Actual bounded native checking bound to durable current repository heads."""
from dataclasses import replace
import json
import os
import shutil
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_integer_profile as profile
from ipfs_datasets_py.logic.software_contracts.codebase_integer_verification import (
    SCHEMA, CodebaseIntegerVerifier, CodebaseVerificationError,
)
from ipfs_datasets_py.logic.software_contracts.codebase_ir import StaleCodebaseError
from ipfs_datasets_py.logic.software_contracts.codebase_property_cache import CodebasePropertyCache
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseTimeoutError
from .test_codebase_current import repository, scheduler, current_index, publish, VIEW, change

NATIVE = pytest.mark.skipif(
    not sys.platform.startswith("linux") or not shutil.which("z3") or not shutil.which("cvc5"),
    reason="native Linux Z3 and CVC5 required",
)


def contract(offset=1):
    return profile.IntegerOffsetContract("counter.py", "increment", "n", offset)


@pytest.fixture
def verifier(current_index, tmp_path):
    index, _, _ = current_index
    return CodebaseIntegerVerifier(index, CodebasePropertyCache(tmp_path / "property-cache"))


@NATIVE
def test_native_proved_refuted_and_cache_history_always_rechecks(repository, verifier, scheduler, monkeypatch):
    owner, _, _ = scheduler
    head = publish(verifier.index, repository, owner, "first").head
    native = profile.execute_integer_offset
    calls = []
    def counted(*args, **kwargs):
        calls.append(1)
        return native(*args, **kwargs)
    monkeypatch.setattr(profile, "execute_integer_offset", counted)
    first = verifier.verify(repository, expected_head=head, contract=contract(), scheduler=owner)
    assert first["status"] == "proved", first
    assert not first["cache_history_hit"]
    second = verifier.verify(repository, expected_head=head, contract=contract(), scheduler=owner)
    assert second["status"] == "proved" and second["cache_history_hit"]
    assert len(calls) == 2
    false = verifier.verify(repository, expected_head=head, contract=contract(2), scheduler=owner)
    assert false["status"] == "refuted", false
    assert not false["cache_history_hit"]
    assert false["cache_binding"]["canonical_key_id"] != first["cache_binding"]["canonical_key_id"]
    for result in (first, second, false):
        assert result["solver_replayed"] is True
        assert result["kernel_checked"] is result["behavior_authority"] is False
        assert result["execution_authority"] is result["completion_authority"] is False
        sealed = verifier.index.artifacts.get(result["receipt_cid"], expected_schema=SCHEMA)
        assert sealed == {k: v for k, v in result.items() if k != "receipt_cid"}


@NATIVE
def test_source_edit_rejects_old_head_and_successor_rechecks_new_contract(repository, verifier, scheduler):
    owner, _, _ = scheduler
    first = publish(verifier.index, repository, owner, "first").head
    old = verifier.verify(repository, expected_head=first, contract=contract(), scheduler=owner)
    change(repository, 2)
    with pytest.raises(StaleCodebaseError):
        verifier.verify(repository, expected_head=first, contract=contract(), scheduler=owner)
    second = publish(verifier.index, repository, owner, "second", first).head
    fixed = verifier.verify(repository, expected_head=second, contract=contract(2), scheduler=owner)
    assert fixed["status"] == "proved" and not fixed["cache_history_hit"]
    assert fixed["source_cid"] != old["source_cid"]
    change(repository, 1)
    restored = publish(verifier.index, repository, owner, "restored", second).head
    with pytest.raises(StaleCodebaseError):
        verifier.verify(repository, expected_head=first, contract=contract(), scheduler=owner)
    current = verifier.verify(repository, expected_head=restored, contract=contract(), scheduler=owner)
    assert current["status"] == "proved" and current["cache_history_hit"]
    assert current["head"]["generation"] == 3
    assert current["solver_replayed"] is True


def test_unsupported_signature_never_runs_source_or_solver(repository, verifier, scheduler, monkeypatch, tmp_path):
    owner, _, _ = scheduler
    trap = tmp_path / "executed"
    (repository / "counter.py").write_text(
        f"def increment(n: int = __import__('pathlib').Path({str(trap)!r}).touch()) -> int:\n    return n + 1\n")
    head = publish(verifier.index, repository, owner, "first").head
    def forbidden(*args, **kwargs):
        pytest.fail("unsupported source reached a solver")
    monkeypatch.setattr(profile, "execute_integer_offset", forbidden)
    result = verifier.verify(repository, expected_head=head, contract=contract(), scheduler=owner)
    assert result["status"] == "unsupported" and result["solver_replayed"] is False
    assert not trap.exists()


@NATIVE
def test_cached_status_cannot_override_fresh_native_evidence(repository, verifier, scheduler):
    owner, _, _ = scheduler
    head = publish(verifier.index, repository, owner, "first").head
    checked = verifier.verify(repository, expected_head=head, contract=contract(), scheduler=owner)
    poisoned = {**checked["checks"], "status": "refuted"}
    verifier.cache.put(checked["cache_binding"], poisoned)
    with pytest.raises(CodebaseVerificationError, match="disagrees"):
        verifier.verify(repository, expected_head=head, contract=contract(), scheduler=owner)


@NATIVE
@pytest.mark.parametrize("stage", ["solver", "receipt"])
def test_edits_during_check_or_final_seal_withhold_result(repository, verifier, scheduler, monkeypatch, stage):
    owner, _, _ = scheduler
    head = publish(verifier.index, repository, owner, "first").head
    if stage == "solver":
        original = profile.execute_integer_offset
        def alter(*args, **kwargs):
            result = original(*args, **kwargs)
            change(repository, 2)
            return result
        monkeypatch.setattr(profile, "execute_integer_offset", alter)
    else:
        original = verifier.index.artifacts.put
        def alter(value):
            cid = original(value)
            if value.get("schema") == SCHEMA:
                change(repository, 2)
            return cid
        monkeypatch.setattr(verifier.index.artifacts, "put", alter)
    with pytest.raises(StaleCodebaseError):
        verifier.verify(repository, expected_head=head, contract=contract(), scheduler=owner)
    assert verifier.index.current(VIEW) == head


def test_pressure_blocks_before_current_source_or_solver_reads(repository, verifier, scheduler, monkeypatch):
    owner, pressure, healthy = scheduler
    head = publish(verifier.index, repository, owner, "first").head
    pressure[0] = replace(healthy, memory_stall_percent=10)
    def forbidden(*args, **kwargs):
        pytest.fail("work started while admission was blocked")
    monkeypatch.setattr(verifier.index, "observe_current", forbidden)
    monkeypatch.setattr(profile, "execute_integer_offset", forbidden)
    with pytest.raises(LeaseTimeoutError):
        verifier.verify(repository, expected_head=head, contract=contract(), scheduler=owner,
                        admission_timeout_seconds=0.03)


@NATIVE
def test_native_restart_cache_is_history_and_solver_executes_again(repository, verifier, current_index, scheduler, tmp_path):
    owner, _, _ = scheduler
    head = publish(verifier.index, repository, owner, "first").head
    first = verifier.verify(repository, expected_head=head, contract=contract(), scheduler=owner)
    _, connection, database = current_index
    request = {"repository": str(repository), "database": str(database),
               "artifacts": str(tmp_path / "artifacts"), "cache": str(tmp_path / "property-cache"),
               "head": head.to_dict()}
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request))
    connection.close()
    script = """
import json,sys,duckdb
from pathlib import Path
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog,CodebaseHead
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import IntegerOffsetContract
from ipfs_datasets_py.logic.software_contracts.codebase_integer_verification import CodebaseIntegerVerifier
from ipfs_datasets_py.logic.software_contracts.codebase_property_cache import CodebasePropertyCache
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler,ResourceSchedulerConfig
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
request=json.loads(open(sys.argv[1]).read())
owner=GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
 state_path=Path(sys.argv[1]).with_name('restart-admission.json'),
 proof_resource_sampler=lambda:ProofHostResources(8,8192,8192),
 lane_reservations={},auto_renew_leases=False,proof_backoff_seconds=0.02,poll_interval_seconds=0.005))
with duckdb.connect(request['database'],config={'threads':1,'memory_limit':'64MB'}) as connection:
 store=DuckDBASTStore(connection=connection); artifacts=ImmutableCAS(request['artifacts'])
 index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=artifacts,catalog=CodebaseCatalog(store,artifacts))
 verifier=CodebaseIntegerVerifier(index,CodebasePropertyCache(request['cache']))
 result=verifier.verify(request['repository'],expected_head=CodebaseHead.from_dict(request['head']),contract=IntegerOffsetContract('counter.py','increment','n',1),scheduler=owner)
 state=owner.snapshot()
 assert state['active_lease_count']==state['waiting_request_count']==0
 print(json.dumps(result))
"""
    replay = subprocess.run([sys.executable, "-c", script, str(request_path)],
                            capture_output=True, text=True, timeout=45, env=dict(os.environ))
    assert replay.returncode == 0, replay.stderr
    result = json.loads(replay.stdout.splitlines()[-1])
    assert result["status"] == "proved" and result["cache_history_hit"]
    assert result["solver_replayed"] is True
    assert result["cache_binding"] == first["cache_binding"]
