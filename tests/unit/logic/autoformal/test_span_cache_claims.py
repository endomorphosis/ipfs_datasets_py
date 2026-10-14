"""Actual private native SpanCache transactions, not receipt-only fixtures."""
from copy import deepcopy
import hashlib
import os
import threading

import pytest

from ipfs_datasets_py.logic.autoformal.span_cache import SpanCache, SpanCacheError, SpanCacheTextLimits
from ipfs_datasets_py.logic.autoformal.span_cache_claims import SpanCacheClaims, SpanClaimError

REVISION = "a" * 40
NEXT_REVISION = "hub:" + "b" * 40
CODE = "sha256:" + "c" * 64
PATHS = {"ipfs_datasets_py/logic/legal_ir/canonical_compiler.py": "d" * 64}
TABLES = ("span_cache", "sealed_terms", "span_terms", "span_claim_owner",
          "span_source_bindings", "span_fenced_claims", "span_claim_operations", "span_claim_results")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source(span_id, *, text=None, legal_id="usc:us:5:552"):
    return dict(source_span_id=span_id, text=text or f"The agency shall file notice {span_id}.", legal_id=legal_id)


def _binding(row, *, revision=REVISION, expected=None):
    return dict(source_span_id=row["source_span_id"], source_revision=revision,
                source_sha256=_sha(row["text"]), expected_binding=expected)


@pytest.fixture
def owner(tmp_path):
    cache = SpanCache(tmp_path / "private-native.duckdb")
    # Each private native owner remains within the one-slot test lease.
    cache._db.execute("SET threads=1")
    clock = [1000.0]
    control = cache.fenced_claims(clock=lambda: clock[0])
    rows = [_source("s1"), _source("s2")]
    cache.enqueue(rows)
    control.bind_sources_fenced("bind-1", [_binding(row) for row in rows])
    try:
        yield cache, control, clock, rows
    finally:
        cache.close()


def _snapshot(cache):
    return {table: cache._db.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall() for table in TABLES}


def _claims(control, *, span_ids=None, operation="claim-1", seconds=20):
    receipt = control.claim_batch_fenced(operation, "worker-a", span_ids or ["s1", "s2"], lease_seconds=seconds)
    return receipt["claims"]


def _result(claim, *, agrees=True):
    return dict(claim=deepcopy(claim), agrees=agrees, decompiled="Agency must file notice.",
        rule={"modality": "obligation", "actor": "Agency", "action": "file", "object": "notice"},
        repair={} if agrees else {"failure": "unsupported"}, reason="" if agrees else "unsupported")


def _complete(control, rows, operation="finish-1", *, code=CODE, paths=None):
    return control.complete_claimed_fenced(operation, rows, code_identity=code, path_hashes=PATHS if paths is None else paths)


def _false(receipt):
    assert all(receipt[name] is False for name in ("qualified", "admitted", "formalized", "roundtrip_ok"))


def test_owner_uses_exact_native_connection_and_one_facade(owner):
    cache, control, _, _ = owner
    assert control._connection is cache._db
    assert cache.fenced_claims() is control
    with pytest.raises(SpanClaimError, match="already has"):
        SpanCacheClaims(cache)
    with pytest.raises(SpanClaimError, match="cannot be replaced"):
        cache.fenced_claims(clock=lambda: 1000)


def test_mixed_finish_updates_rows_terms_and_receipt_atomically(owner):
    cache, control, _, sources = owner
    claims = _claims(control)
    receipt = _complete(control, [_result(claims[0]), _result(claims[1], agrees=False)])
    assert (receipt["sealed"], receipt["gaps"]) == (1, 1)
    _false(receipt)
    assert cache._db.execute("SELECT source_span_id,status,sealed,claim_worker,claim_token,admitted,formalized FROM span_cache ORDER BY 1").fetchall() == [
        ("s1", "sealed", True, "", "", False, False), ("s2", "gap", False, "", "", False, False)]
    assert cache._db.execute("SELECT DISTINCT source_span_id FROM span_terms").fetchall() == [("s1",)]
    assert cache._db.execute("SELECT count(*) FROM span_fenced_claims").fetchone()[0] == 0
    assert cache._db.execute("SELECT count(*) FROM span_claim_operations WHERE operation_id='finish-1'").fetchone()[0] == 1
    assert cache._db.execute("SELECT source_span_id,source_text,source_sha256 FROM span_cache ORDER BY 1").fetchall() == [
        (row["source_span_id"], row["text"], _sha(row["text"])) for row in sources]


def test_read_source_requires_current_live_claim(owner):
    _, control, clock, sources = owner
    claim = _claims(control, span_ids=["s1"])[0]
    read = control.read_claim_source_fenced(claim)
    assert read["text"] == sources[0]["text"] and read["legal_id"] == sources[0]["legal_id"]
    _false(read)
    clock[0] = claim["expires_at"]
    with pytest.raises(SpanClaimError, match="expired"):
        control.read_claim_source_fenced(claim)


@pytest.mark.parametrize("field,value", [
    ("source_revision", NEXT_REVISION), ("source_sha256", "e" * 64),
    ("claim_worker", "wrong-worker"), ("claim_token", "wrong-token"),
    ("owner_generation", 999), ("fence", 999), ("legal_id", "usc:us:9:999"),
    ("source_span_id", "unknown"), ("schema", "wrong-schema"),
    ("owner_generation", True), ("expires_at", True),
])
@pytest.mark.parametrize("action", ["finish", "release"])
def test_forged_claim_refuses_without_any_table_mutation(owner, field, value, action):
    cache, control, _, _ = owner
    claims = _claims(control)
    claims[1][field] = value
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError):
        if action == "finish":
            _complete(control, [_result(claim) for claim in claims])
        else:
            control.release_claims_fenced("release-1", claims)
    assert _snapshot(cache) == before


@pytest.mark.parametrize("action", ["finish", "release"])
def test_deadline_boundary_blocks_new_operations(owner, action):
    cache, control, clock, _ = owner
    claims = _claims(control)
    clock[0] = claims[0]["expires_at"]
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError, match="expired"):
        if action == "finish":
            _complete(control, [_result(claim) for claim in claims])
        else:
            control.release_claims_fenced("release-1", claims)
    assert _snapshot(cache) == before


@pytest.mark.parametrize("seconds", [0, -1, 86401, True, float("nan"), float("inf"), "20"])
def test_invalid_lease_refuses_without_mutation(owner, seconds):
    cache, control, _, _ = owner
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError):
        _claims(control, seconds=seconds)
    assert _snapshot(cache) == before


@pytest.mark.parametrize("clock_value", [float("nan"), float("inf"), True, "1000"])
def test_nonfinite_or_non_numeric_owner_clock_refuses(owner, clock_value):
    cache, control, clock, _ = owner
    clock[0] = clock_value
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError):
        _claims(control)
    assert _snapshot(cache) == before


def test_exact_finish_retry_remains_original_after_expiry(owner):
    cache, control, clock, _ = owner
    results = [_result(claim) for claim in _claims(control)]
    original = _complete(control, results)
    clock[0] = 2000
    before = _snapshot(cache)
    assert _complete(control, results) == original
    assert control.resolve_operation("finish-1", "CompleteSpans", dict(rows=results, code_identity=CODE, path_hashes=PATHS)) == original
    assert _snapshot(cache) == before


def test_exact_release_retry_remains_original_after_expiry(owner):
    cache, control, clock, _ = owner
    claims = _claims(control)
    original = control.release_claims_fenced("release-1", claims)
    assert original["released"] == 2
    clock[0] = 2000
    before = _snapshot(cache)
    assert control.release_claims_fenced("release-1", claims) == original
    assert _snapshot(cache) == before


@pytest.mark.parametrize("action", ["finish", "release", "claim"])
def test_historical_retry_survives_legitimate_native_restart(tmp_path, action):
    path = tmp_path / "private-restart.duckdb"
    cache = SpanCache(path)
    control = cache.fenced_claims(clock=lambda: 1000)
    source = _source("s1")
    cache.enqueue([source])
    control.bind_sources_fenced("bind", [_binding(source)])
    claims = _claims(control, span_ids=["s1"])
    results = [_result(claims[0])]
    if action == "finish":
        original = _complete(control, results)
    elif action == "release":
        original = control.release_claims_fenced("release", claims)
    else:
        original = control.claim_batch_fenced("claim-1", "worker-a", ["s1"], lease_seconds=20)
    generation = control.owner_generation
    cache.close()
    cache = SpanCache(path)
    control = cache.fenced_claims(clock=lambda: 2000)
    try:
        assert control.owner_generation == generation + 1
        before = _snapshot(cache)
        if action == "finish":
            assert _complete(control, results) == original
        elif action == "release":
            assert control.release_claims_fenced("release", claims) == original
        else:
            assert control.claim_batch_fenced("claim-1", "worker-a", ["s1"], lease_seconds=20) == original
        assert _snapshot(cache) == before
        with pytest.raises(SpanClaimError):
            control.read_claim_source_fenced(claims[0])
        _false(original)
    finally:
        cache.close()


@pytest.mark.parametrize("change", ["result", "code", "paths", "span_set", "command"])
def test_conflicting_operation_retry_cannot_change_rows_or_terms(owner, change):
    cache, control, _, _ = owner
    results = [_result(claim) for claim in _claims(control)]
    _complete(control, results)
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError, match="conflicts"):
        if change == "result":
            results[0]["decompiled"] += " Changed."
            _complete(control, results)
        elif change == "code":
            _complete(control, results, code="sha256:" + "f" * 64)
        elif change == "paths":
            _complete(control, results, paths={next(iter(PATHS)): "e" * 64})
        elif change == "span_set":
            _complete(control, results[:1])
        else:
            control.release_claims_fenced("finish-1", [row["claim"] for row in results])
    assert _snapshot(cache) == before


@pytest.mark.parametrize("action", ["finish", "release", "claim", "bind"])
def test_duplicate_batch_ids_refuse_before_writes(owner, action):
    cache, control, _, sources = owner
    claims = _claims(control, span_ids=["s1"])
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError, match="duplicate"):
        if action == "finish":
            _complete(control, [_result(claims[0]), _result(claims[0])])
        elif action == "release":
            control.release_claims_fenced("release", claims + claims)
        elif action == "claim":
            control.claim_batch_fenced("another", "worker-b", ["s2", "s2"])
        else:
            row = _binding(sources[1], expected=dict(source_revision=REVISION, source_sha256=_sha(sources[1]["text"])))
            control.bind_sources_fenced("bind-other", [row, row])
    assert _snapshot(cache) == before


def test_binding_never_invents_missing_source_revision(owner):
    cache, control, _, _ = owner
    row = _source("s3")
    cache.enqueue([row])
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError, match="explicit pinned"):
        control.bind_sources_fenced("bind-missing", [_binding(row, revision="")])
    with pytest.raises(SpanClaimError, match="binding required"):
        _claims(control, span_ids=["s3"])
    assert _snapshot(cache) == before


@pytest.mark.parametrize("revision", ["main", "latest", "derived-source-version", "A" * 40, "a" * 39])
def test_mutable_or_unpinned_revision_refuses(owner, revision):
    cache, control, _, sources = owner
    before = _snapshot(cache)
    expected = dict(source_revision=REVISION, source_sha256=_sha(sources[0]["text"]))
    with pytest.raises(SpanClaimError, match="explicit pinned"):
        control.bind_sources_fenced("rebind", [_binding(sources[0], revision=revision, expected=expected)])
    assert _snapshot(cache) == before


def test_source_revision_cas_rebinding_retires_claims_and_preserves_exact_retries(owner):
    cache, control, _, sources = owner
    claims = _claims(control, span_ids=["s1"])
    expected = dict(source_revision=REVISION, source_sha256=_sha(sources[0]["text"]))
    rebinding = [_binding(sources[0], revision=NEXT_REVISION, expected=expected)]
    receipt = control.bind_sources_fenced("rebind", rebinding)
    assert receipt["retired_claims"] == ["s1"]
    assert cache.pending()[0]["source_span_id"] == "s1"
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError):
        _complete(control, [_result(claims[0])])
    assert control.bind_sources_fenced("rebind", rebinding) == receipt
    assert _snapshot(cache) == before
    current = _claims(control, span_ids=["s1"], operation="claim-2")[0]
    assert current["source_revision"] == NEXT_REVISION and current["claim_token"] != claims[0]["claim_token"]


def test_source_rebinding_conflict_is_whole_batch_atomic(owner):
    cache, control, _, sources = owner
    rows = [_binding(source, revision=NEXT_REVISION,
        expected=dict(source_revision=REVISION, source_sha256=_sha(source["text"]))) for source in sources]
    rows[1]["expected_binding"]["source_revision"] = "c" * 40
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError, match="compare-and-swap"):
        control.bind_sources_fenced("rebind", rows)
    assert _snapshot(cache) == before


def test_explicit_sha256_revision_is_supported_without_derivation(owner):
    cache, control, _, _ = owner
    source = _source("s3")
    cache.enqueue([source])
    revision = "sha256:" + "f" * 64
    control.bind_sources_fenced("document-source", [_binding(source, revision=revision)])
    assert _claims(control, span_ids=["s3"], operation="doc-claim")[0]["source_revision"] == revision


def test_legacy_source_edit_cannot_silently_carry_forward_source_binding(owner):
    cache, control, _, sources = owner
    new_text = sources[0]["text"] + " Changed."
    cache._db.execute("UPDATE span_cache SET source_text=?,source_sha256=? WHERE source_span_id='s1'", [new_text, _sha(new_text)])
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError, match="binding required"):
        _claims(control, span_ids=["s1"])
    assert _snapshot(cache) == before


def test_inconsistent_cached_source_bytes_hash_cannot_be_bound(owner):
    cache, control, _, sources = owner
    cache._db.execute("UPDATE span_cache SET source_text=source_text || ' Changed.' WHERE source_span_id='s1'")
    before = _snapshot(cache)
    expected = dict(source_revision=REVISION, source_sha256=_sha(sources[0]["text"]))
    with pytest.raises(SpanClaimError, match="bytes/hash"):
        control.bind_sources_fenced("rebind", [_binding(sources[0], revision=NEXT_REVISION, expected=expected)])
    assert _snapshot(cache) == before


def test_legacy_release_does_not_let_old_fenced_claim_finish(owner):
    cache, control, _, _ = owner
    claims = _claims(control, span_ids=["s1"])
    cache.release_claims(["s1"])
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError, match="cached span claim"):
        _complete(control, [_result(claims[0])])
    assert _snapshot(cache) == before


def test_legacy_unknown_claim_is_not_replaced_by_fenced_owner(owner):
    cache, control, _, _ = owner
    cache.claim_batch("legacy", limit=2)
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError, match="legacy or unknown"):
        _claims(control)
    assert _snapshot(cache) == before


def test_release_and_reclaim_fences_prior_token(owner):
    cache, control, _, _ = owner
    old = _claims(control, span_ids=["s1"])[0]
    control.release_claims_fenced("release", [old])
    fresh = _claims(control, span_ids=["s1"], operation="claim-2")[0]
    assert fresh["fence"] > old["fence"]
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError, match="persisted claim differs"):
        _complete(control, [_result(old)])
    assert _snapshot(cache) == before


def test_expired_claim_can_be_reclaimed_but_old_work_cannot_finish(owner):
    cache, control, clock, _ = owner
    old = _claims(control, span_ids=["s1"])[0]
    clock[0] = old["expires_at"]
    fresh = _claims(control, span_ids=["s1"], operation="claim-2")[0]
    assert fresh["claim_token"] != old["claim_token"]
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError):
        _complete(control, [_result(old)])
    assert _snapshot(cache) == before


def test_unexpired_lease_prevents_another_claim(owner):
    cache, control, _, _ = owner
    _claims(control)
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError, match="live claim"):
        _claims(control, operation="claim-2")
    assert _snapshot(cache) == before


def test_baseexception_during_second_row_rolls_back_first_row_and_terms(owner, monkeypatch):
    cache, control, _, _ = owner
    claims = _claims(control)
    before = _snapshot(cache)
    original = cache._seal_row
    def fail_second(row, **kwargs):
        original(row, **kwargs)
        if row["source_span_id"] == "s2":
            raise KeyboardInterrupt("after native row/term mutations")
    monkeypatch.setattr(cache, "_seal_row", fail_second)
    with pytest.raises(KeyboardInterrupt):
        _complete(control, [_result(claim) for claim in claims])
    assert _snapshot(cache) == before


def test_baseexception_after_receipt_insert_rolls_back_receipt_and_outputs(owner, monkeypatch):
    cache, control, _, _ = owner
    results = [_result(claim) for claim in _claims(control)]
    before = _snapshot(cache)
    original = control._store_receipt
    def fail_receipt(cx, *args):
        original(cx, *args)
        raise SystemExit("after native durable receipt INSERT")
    monkeypatch.setattr(control, "_store_receipt", fail_receipt)
    with pytest.raises(SystemExit):
        _complete(control, results)
    assert _snapshot(cache) == before


def test_caught_nested_failure_poison_rolls_back_successful_inner_mutation(owner):
    cache, control, _, _ = owner
    claims = _claims(control)
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError, match="poisons"):
        with control._transaction():
            control.release_claims_fenced("release", claims)
            try:
                with control._transaction():
                    raise KeyboardInterrupt("nested failure caught by outer caller")
            except KeyboardInterrupt:
                pass
    assert _snapshot(cache) == before


def test_foreign_thread_cannot_use_original_native_connection(owner):
    cache, control, _, _ = owner
    before = _snapshot(cache)
    errors = []
    def other_thread():
        try:
            _claims(control)
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=other_thread)
    thread.start()
    thread.join()
    assert len(errors) == 1 and isinstance(errors[0], SpanClaimError)
    assert _snapshot(cache) == before


def test_fork_identity_is_rejected_before_database_access(owner, monkeypatch):
    cache, control, _, _ = owner
    before = _snapshot(cache)
    original_pid = os.getpid()
    with monkeypatch.context() as patch:
        patch.setattr(os, "getpid", lambda: original_pid + 1)
        with pytest.raises(SpanClaimError, match="foreign"):
            _claims(control)
        with pytest.raises(SpanClaimError, match="foreign"):
            cache.fenced_claims()
    assert _snapshot(cache) == before


def test_closed_connection_refuses_before_database_access(tmp_path):
    cache = SpanCache(tmp_path / "closed-private.duckdb")
    control = cache.fenced_claims()
    cache.close()
    with pytest.raises(SpanClaimError, match="closed"):
        _claims(control)
    with pytest.raises(SpanClaimError, match="closed"):
        cache.fenced_claims()


def test_later_native_connection_fences_older_generation(owner):
    cache, control, _, _ = owner
    another_cache = SpanCache(cache.path)
    another_control = another_cache.fenced_claims(clock=lambda: 1000)
    try:
        assert another_control.owner_generation > control.owner_generation
        before = _snapshot(cache)
        with pytest.raises(SpanClaimError, match="stale native owner"):
            _claims(control)
        assert _snapshot(cache) == before
    finally:
        another_cache.close()


def test_native_generation_transition_conflicts_with_inflight_completion_owner_row(owner, monkeypatch):
    """An actual second native owner cannot change the generation mid-commit.

    Each private DuckDB connection is opened and closed on its own thread.
    The rejected owner constructor creates no operation or output evidence.
    This exercises native MVCC conflict rather than a fabricated stale token.
    """
    import duckdb

    cache, control, _, _ = owner
    rows = [_result(claim) for claim in _claims(control)]
    prepared, attempt, finished = threading.Event(), threading.Event(), threading.Event()
    errors, constructed = [], []

    def second_native_owner():
        other = None
        try:
            other = SpanCache(cache.path)
            other._db.execute("SET threads=1")
            prepared.set()
            assert attempt.wait(5), "original owner did not begin native completion"
            constructed.append(other.fenced_claims(clock=lambda: 1000))
        except BaseException as error:
            errors.append(error)
        finally:
            if other is not None:
                other.close()
            finished.set()

    worker = threading.Thread(target=second_native_owner)
    worker.start()
    original = control._store_result

    def overlapping_generation(cx, *args):
        original(cx, *args)
        if not attempt.is_set():
            attempt.set()
            assert finished.wait(5), "second private native owner did not finish"

    try:
        assert prepared.wait(5), "second private native connection was not ready"
        monkeypatch.setattr(control, "_store_result", overlapping_generation)
        receipt = _complete(control, rows)
        assert finished.wait(5)
        assert not constructed
        assert len(errors) == 1 and isinstance(errors[0], duckdb.TransactionException)
        assert "Conflict on update" in str(errors[0])
        assert cache._db.execute("SELECT owner_generation FROM span_claim_owner").fetchone() == (control.owner_generation,)
        assert cache._db.execute("SELECT operation_id FROM span_claim_operations ORDER BY 1").fetchall() == [
            ("bind-1",), ("claim-1",), ("finish-1",)]
        assert cache._db.execute("SELECT operation_id,source_span_id FROM span_claim_results ORDER BY 1,2").fetchall() == [
            ("finish-1", "s1"), ("finish-1", "s2")]
        assert receipt["sealed"] == 2
        assert control.read_completion_results_fenced("finish-1", rows,
            code_identity=CODE, path_hashes=PATHS)["results"][0]["result"] == rows[0]
        _false(receipt)
    finally:
        attempt.set()
        worker.join(timeout=5)
        assert not worker.is_alive(), "private native owner thread did not close"


@pytest.mark.parametrize("extra", ["roundtrip_ok", "formalized", "compiler_status", "text", "source_span_id"])
def test_worker_cannot_smuggle_source_or_authority_fields(owner, extra):
    cache, control, _, _ = owner
    row = _result(_claims(control, span_ids=["s1"])[0])
    row[extra] = "roundtrip_ok" if extra == "compiler_status" else True
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError, match="closed completion"):
        _complete(control, [row])
    assert _snapshot(cache) == before


def test_constitution_compile_cache_receipt_never_claims_roundtrip_or_formalization(owner):
    cache, control, _, _ = owner
    source = _source("constitution.article1", text="All legislative Powers herein granted shall be vested in a Congress.", legal_id="us-constitution:article-i")
    cache.enqueue([source])
    control.bind_sources_fenced("bind-constitution", [_binding(source)])
    claim = _claims(control, span_ids=[source["source_span_id"]], operation="constitution-claim")[0]
    result = _complete(control, [_result(claim)], operation="constitution-compile-cache")
    _false(result)
    assert cache._db.execute("SELECT admitted,formalized FROM span_cache WHERE source_span_id=?", [source["source_span_id"]]).fetchone() == (False, False)


def test_full_utf8_text_is_preserved_and_decompilation_limit_refuses_whole_batch(tmp_path):
    source = _source("s1", text="界" * 20000)
    cache = SpanCache(tmp_path / "utf8-private.duckdb")
    control = cache.fenced_claims(clock=lambda: 1000)
    try:
        cache.enqueue([source])
        control.bind_sources_fenced("bind", [_binding(source)])
        claim = _claims(control, span_ids=["s1"])[0]
        assert control.read_claim_source_fenced(claim)["text"] == source["text"]
        row = _result(claim)
        _complete(control, [row])
        assert cache._db.execute("SELECT source_text FROM span_cache").fetchone()[0] == source["text"]
    finally:
        cache.close()


def test_existing_text_limits_refuse_completion_before_row_or_term_changes(tmp_path):
    cache = SpanCache(tmp_path / "limits-private.duckdb", text_limits=SpanCacheTextLimits(max_text_bytes=50, max_batch_text_bytes=100))
    control = cache.fenced_claims(clock=lambda: 1000)
    source = _source("s1")
    try:
        cache.enqueue([source])
        control.bind_sources_fenced("bind", [_binding(source)])
        claim = _claims(control, span_ids=["s1"])[0]
        row = _result(claim)
        row["decompiled"] = "界" * 17
        before = _snapshot(cache)
        with pytest.raises(SpanCacheError, match="max_text_bytes"):
            _complete(control, [row])
        assert _snapshot(cache) == before
    finally:
        cache.close()


def test_command_bound_refuses_without_mutation(owner):
    cache, control, _, _ = owner
    row = _result(_claims(control, span_ids=["s1"])[0])
    row["decompiled"] = "a" * 65536
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError, match="byte bound"):
        _complete(control, [row])
    assert _snapshot(cache) == before


@pytest.mark.parametrize("agrees", [True, False])
def test_full_result_ledger_preserves_rule_repair_and_diagnostics_on_both_dispositions(owner, agrees):
    cache, control, clock, _ = owner
    row = _result(_claims(control, span_ids=["s1"])[0], agrees=agrees)
    row["rule"] = {"modality": "prohibition", "actor": "Agency", "action": "disclose", "object": "records"}
    row["repair"] = {"decoder_candidate": {"formula": "O(file(agency,notice))"}, "reason": "model/compiler disagree"}
    row["reason"] = "Retain this census diagnostic even when compile cache agrees."
    receipt = _complete(control, [row])
    clock[0] = 2000
    before = _snapshot(cache)
    evidence = control.read_completion_results_fenced("finish-1", [row], code_identity=CODE, path_hashes=PATHS)
    assert evidence["results"] == [dict(source_span_id="s1", result=row, code_identity=CODE, path_hashes=PATHS)]
    _false(evidence)
    assert evidence["historical_receipt_only"] is True
    assert "text" not in evidence["results"][0]["result"]
    assert _complete(control, [row]) == receipt
    assert cache._db.execute("SELECT count(*) FROM span_claim_results").fetchone()[0] == 1
    assert _snapshot(cache) == before


def test_full_result_read_requires_exact_original_payload_and_detects_tampering(owner):
    cache, control, _, _ = owner
    row = _result(_claims(control, span_ids=["s1"])[0])
    _complete(control, [row])
    before = _snapshot(cache)
    forged = deepcopy(row)
    forged["repair"] = {"changed": True}
    with pytest.raises(SpanClaimError, match="conflicts"):
        control.read_completion_results_fenced("finish-1", [forged], code_identity=CODE, path_hashes=PATHS)
    with pytest.raises(SpanClaimError, match="no exact committed"):
        control.read_completion_results_fenced("unknown", [row], code_identity=CODE, path_hashes=PATHS)
    assert _snapshot(cache) == before
    cache._db.execute("UPDATE span_claim_results SET result_json='{}' WHERE operation_id='finish-1'")
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError, match="content differs"):
        control.read_completion_results_fenced("finish-1", [row], code_identity=CODE, path_hashes=PATHS)
    assert _snapshot(cache) == before


def test_full_result_history_survives_native_owner_restart(tmp_path):
    path = tmp_path / "private-result-history.duckdb"
    cache = SpanCache(path)
    control = cache.fenced_claims(clock=lambda: 1000)
    source = _source("s1")
    cache.enqueue([source])
    control.bind_sources_fenced("bind", [_binding(source)])
    rows = [_result(_claims(control, span_ids=["s1"])[0], agrees=False)]
    _complete(control, rows)
    original = control.read_completion_results_fenced("finish-1", rows, code_identity=CODE, path_hashes=PATHS)
    cache.close()
    cache = SpanCache(path)
    control = cache.fenced_claims(clock=lambda: 2000)
    try:
        assert control.read_completion_results_fenced("finish-1", rows, code_identity=CODE, path_hashes=PATHS) == original
        with pytest.raises(SpanClaimError):
            control.read_claim_source_fenced(rows[0]["claim"])
    finally:
        cache.close()


def test_receipt_without_complete_result_history_is_explicitly_unavailable(owner):
    cache, control, _, _ = owner
    rows = [_result(_claims(control, span_ids=["s1"])[0])]
    original = _complete(control, rows)
    cache._db.execute("DELETE FROM span_claim_results WHERE operation_id='finish-1'")
    before = _snapshot(cache)
    assert _complete(control, rows) == original
    with pytest.raises(SpanClaimError, match="ledger unavailable"):
        control.read_completion_results_fenced("finish-1", rows, code_identity=CODE, path_hashes=PATHS)
    assert _snapshot(cache) == before


def test_failure_after_result_insert_rolls_back_result_rows_terms_and_receipt(owner, monkeypatch):
    cache, control, _, _ = owner
    rows = [_result(claim) for claim in _claims(control)]
    before = _snapshot(cache)
    original = control._store_result
    def failed_result(cx, *args):
        original(cx, *args)
        raise KeyboardInterrupt("after actual result INSERT")
    monkeypatch.setattr(control, "_store_result", failed_result)
    with pytest.raises(KeyboardInterrupt):
        _complete(control, rows)
    assert _snapshot(cache) == before


def test_deadline_crossed_during_output_work_rolls_back_all_result_and_term_writes(owner, monkeypatch):
    cache, control, clock, _ = owner
    rows = [_result(claim) for claim in _claims(control)]
    before = _snapshot(cache)
    original = cache._seal_row
    def slow_second(row, **kwargs):
        original(row, **kwargs)
        if row["source_span_id"] == "s2":
            clock[0] = row["claim"]["expires_at"]
    monkeypatch.setattr(cache, "_seal_row", slow_second)
    with pytest.raises(SpanClaimError, match="deadline crossed before commit"):
        _complete(control, rows)
    assert _snapshot(cache) == before


@pytest.mark.parametrize("action", ["claim", "finish", "release"])
def test_deadline_crossed_after_receipt_insert_rolls_back_every_native_table(owner, monkeypatch, action):
    cache, control, clock, _ = owner
    if action == "claim":
        claims = []
    else:
        claims = _claims(control)
    before = _snapshot(cache)
    original = control._store_receipt
    def delayed_receipt(cx, *args):
        original(cx, *args)
        clock[0] = 2000
    monkeypatch.setattr(control, "_store_receipt", delayed_receipt)
    with pytest.raises(SpanClaimError, match="deadline crossed before commit"):
        if action == "claim":
            _claims(control)
        elif action == "finish":
            _complete(control, [_result(claim) for claim in claims])
        else:
            control.release_claims_fenced("release", claims)
    assert _snapshot(cache) == before


def test_nonfinite_clock_after_output_work_rolls_back_every_native_table(owner, monkeypatch):
    cache, control, clock, _ = owner
    rows = [_result(_claims(control, span_ids=["s1"])[0])]
    before = _snapshot(cache)
    original = control._store_result
    def failed_clock(cx, *args):
        original(cx, *args)
        clock[0] = float("nan")
    monkeypatch.setattr(control, "_store_result", failed_clock)
    with pytest.raises(SpanClaimError, match="clock must be finite"):
        _complete(control, rows)
    assert _snapshot(cache) == before


def test_result_lookup_refuses_oversized_full_response_without_truncation(owner):
    cache, control, _, _ = owner
    row = _result(_claims(control, span_ids=["s1"])[0])
    row["repair"] = {"diagnostic": "x" * 63000}
    # The stored bounded command can be smaller than a complete export reply
    # which adds per-result compiler identity/path evidence and response fields.
    from ipfs_datasets_py.logic.autoformal.span_cache_claims import _raw
    payload = dict(rows=[row], code_identity=CODE, path_hashes=PATHS)
    remainder = 65536 - len(_raw(dict(command="CompleteSpans", payload=payload)))
    row["repair"]["diagnostic"] += "x" * remainder
    _complete(control, [row])
    before = _snapshot(cache)
    with pytest.raises(SpanClaimError, match="byte bound"):
        control.read_completion_results_fenced("finish-1", [row], code_identity=CODE, path_hashes=PATHS)
    assert _snapshot(cache) == before
