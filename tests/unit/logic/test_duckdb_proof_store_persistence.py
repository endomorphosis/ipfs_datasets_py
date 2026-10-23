"""Genuine DuckDB persistence and authority tests for the unified proof store.

Run only through the repository's frozen-request owned validation launcher.
DuckDB is imported inside a fixture; importing this module opens no database.
These are authored observations, not legal artifacts or theorem receipts.
"""

from __future__ import annotations

from dataclasses import replace
import importlib
import json

import pytest

from ipfs_datasets_py.logic.backends.cache_protocol import (
    CacheLookupReason,
    CachePolarity,
)
from ipfs_datasets_py.logic.backends.results import (
    CandidateResult,
    ResultAuthority,
    ResultStatus,
)
from ipfs_datasets_py.logic.common.duckdb_proof_store import (
    DuckDBProofStore,
    DuckDBProofStoreError,
    DuckDBProofStoreIntegrityError,
    ImmutableEnvelopeReference,
    PROOF_AUTHORITY_DIMENSION_SET,
    ProofEvidenceRecord,
    ProofOutcomeKind,
    ProofTrustLevel,
    UnifiedProofEntry,
    build_unified_proof_key,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap


@pytest.fixture
def duckdb_module():
    # Missing DuckDB is a qualification failure, not a skipped persistence test.
    return importlib.import_module("duckdb")


@pytest.fixture
def sql_store(duckdb_module, tmp_path):
    path = tmp_path / "observations.duckdb"
    connection = duckdb_module.connect(str(path))
    store = DuckDBProofStore(connection=connection, max_entries=16)
    yield path, connection, store
    connection.close()


def _key(**changes):
    values = {
        "ir": {"preparation": "authored-corpus-a", "family": "fol"},
        "property_value": {"kind": "retained-packet-observation"},
        "assumptions": ("source-review-pending", "historical-evidence-only"),
        "selected_premises": ({"source": "donor"}, {"source": "consumer"}),
        "translator": {"reader": "byte-packet/v1", "source_pin": "a" * 64},
        "solver_identities": ({"backend": "retained-observation", "executed": False},),
        "toolchain": {"historical": "leanprover/lean4:v4.26.0"},
        "theorem_registry": {"kind": "historical-names", "names": ["donor", "consumer"]},
        "policy": {"proof_admission": False, "training_mask": 0},
        "resources": {"packet_bytes": 64 * 1024 * 1024},
        "tree": {"corpus_preparation_sha256": "b" * 64},
        "backend_id": "retained-packet-reader",
        "backend_binary": {"reader_sha256": "c" * 64},
        "backend_version": "retained-observation/v1",
        "backend_config": {"fresh_native_execution": False},
    }
    values.update(changes)
    return build_unified_proof_key(**values)


def _entry(key=None, *, tag="original", created_at=100.0):
    key = key or _key()
    raw_observation = ("authored observation: " + tag).encode()
    raw_receipt = ("authored historical receipt: " + tag).encode()
    envelope = ImmutableEnvelopeReference.from_bytes(
        raw_observation, media_type="application/json"
    )
    receipt = ImmutableEnvelopeReference.from_bytes(
        raw_receipt, media_type="application/json"
    )
    result = CandidateResult(
        result_id="observation:" + tag,
        backend_id=key.backend_id,
        backend_version=key.backend_version,
        authority=ResultAuthority.CANDIDATE,
        status=ResultStatus.UNKNOWN,
        translation_ceiling=EvidenceAuthority.NONE,
        witness={"observation_reference": envelope.to_dict()},
        reason="Retained engineering evidence supplies no new proof authority.",
        metadata={
            "kernel_accepted": False,
            "native_execution_performed": False,
            "proof_cache_admission_verified": False,
            "training_mask": 0,
            "evaluation_gold_mask": 0,
            "historical_kernel_observations_retained": True,
        },
    )
    evidence = ProofEvidenceRecord(
        evidence_id="receipt:" + key.digest + ":" + tag,
        evidence_kind="unreviewed_historical_runtime_observation",
        evidence_authority=EvidenceAuthority.NONE,
        content_digest=receipt.content_digest,
        payload=FrozenMap({"reference": receipt.to_dict()}),
        created_at=created_at,
    )
    return UnifiedProofEntry.from_typed_result(
        key,
        result,
        created_at=created_at,
        evidence_authority=EvidenceAuthority.NONE,
        trust_level=ProofTrustLevel.NONE,
        envelope=envelope,
        evidence=(evidence,),
    )


def _assert_observation(entry, expected):
    assert entry is not None
    assert entry.to_dict() == expected.to_dict()
    assert entry.outcome is ProofOutcomeKind.UNKNOWN
    assert entry.status is ResultStatus.UNKNOWN
    assert entry.result_authority is ResultAuthority.CANDIDATE
    assert entry.evidence_authority is EvidenceAuthority.NONE
    assert entry.trust_level is ProofTrustLevel.NONE
    assert entry.polarity is CachePolarity.NEGATIVE
    assert entry.envelope == expected.envelope
    assert entry.evidence == expected.evidence
    metadata = entry.result_payload.to_dict()["metadata"]
    assert metadata["kernel_accepted"] is False
    assert metadata["native_execution_performed"] is False
    assert metadata["proof_cache_admission_verified"] is False
    assert metadata["training_mask"] == metadata["evaluation_gold_mask"] == 0
    assert metadata["historical_kernel_observations_retained"] is True


def _scalar(connection, sql, parameters=()):
    return connection.execute(sql, parameters).fetchone()[0]


def test_real_file_reopen_preserves_exact_observation(duckdb_module, tmp_path):
    path = tmp_path / "reopen.duckdb"
    entry = _entry()
    with duckdb_module.connect(str(path)) as connection:
        store = DuckDBProofStore(connection=connection, max_entries=16)
        stored = store.put(entry, now=100.0)
        assert stored.reason is CacheLookupReason.STORED
        assert _scalar(connection, "SELECT count(*) FROM proof_keys") == 1
        assert _scalar(connection, "SELECT count(*) FROM proof_entries") == 1
        assert _scalar(connection, "SELECT count(*) FROM proof_evidence") == 1
    with duckdb_module.connect(str(path)) as connection:
        reopened = DuckDBProofStore(connection=connection, max_entries=16)
        _assert_observation(reopened.get(entry.key, now=101.0), entry)
        projected = reopened.lookup(entry.key.to_verification_cache_key(), now=101.0)
        assert projected.hit and projected.usable
        assert projected.reason is CacheLookupReason.NEGATIVE_HIT
        assert projected.entry.status is ResultStatus.UNKNOWN
        assert projected.entry.evidence_authority is EvidenceAuthority.NONE


def test_cold_verification_key_get_recovers_full_unified_identity(sql_store):
    _, connection, store = sql_store
    entry = _entry()
    store.put(entry, now=100.0)
    cold = DuckDBProofStore(connection=connection, max_entries=16)
    _assert_observation(cold.get(entry.key.to_verification_cache_key(), now=100.0), entry)


def test_normalized_rows_retain_all_fifteen_dimensions_and_premises(sql_store):
    _, connection, store = sql_store
    entry = _entry()
    store.put(entry, now=100.0)
    dimensions = dict(connection.execute(
        "SELECT dimension_name, dimension_digest FROM proof_key_dimensions WHERE key_digest=?",
        [entry.key.digest],
    ).fetchall())
    assert set(dimensions) == PROOF_AUTHORITY_DIMENSION_SET
    assert len(dimensions) == 15
    assert dimensions == dict(entry.key.dimension_map())
    premises = connection.execute(
        "SELECT premise_digest, premise_ordinal FROM premises WHERE key_digest=? ORDER BY premise_ordinal",
        [entry.key.digest],
    ).fetchall()
    assert premises == [(value, index) for index, value in enumerate(entry.key.selected_premise_digests)]
    key_payload = json.loads(_scalar(connection,
        "SELECT key_payload_json FROM proof_keys WHERE key_digest=?", [entry.key.digest]))
    assert key_payload == entry.key.to_dict()


@pytest.mark.parametrize("field", (
    "ir_digest", "property_digest", "assumptions_digest", "selected_premise_digests",
    "translator_digest", "solver_identities_digest", "toolchain_identity_digest",
    "theorem_registry_digest", "policy_digest", "resources_digest", "tree_digest",
    "backend_id", "backend_binary_digest", "backend_version", "backend_config_digest",
))
def test_each_dimension_change_misses_after_cold_sql_reload(sql_store, field):
    _, connection, store = sql_store
    entry = _entry()
    store.put(entry, now=100.0)
    value = ("sha256:" + "f" * 64,)
    if field != "selected_premise_digests":
        value = "different-reader" if field in {"backend_id", "backend_version"} else value[0]
    changed = replace(entry.key, **{field: value})
    assert changed.digest != entry.key.digest
    cold = DuckDBProofStore(connection=connection, max_entries=16)
    assert not cold.lookup(changed, now=100.0).usable
    assert not cold.lookup(changed.to_verification_cache_key(), now=100.0).usable
    _assert_observation(cold.get(entry.key, now=100.0), entry)


def test_duplicate_write_is_one_exact_sql_record(sql_store):
    _, connection, store = sql_store
    entry = _entry()
    store.put(entry, now=100.0)
    store.put(entry, now=100.0)
    assert _scalar(connection, "SELECT count(*) FROM proof_keys") == 1
    assert _scalar(connection, "SELECT count(*) FROM proof_entries") == 1
    assert _scalar(connection, "SELECT count(*) FROM proof_evidence") == 1
    assert _scalar(connection, "SELECT count(*) FROM proof_key_dimensions") == 15
    _assert_observation(DuckDBProofStore(connection=connection).get(entry.key, now=100.0), entry)


def test_same_key_overwrite_removes_old_entry_and_evidence(sql_store):
    _, connection, store = sql_store
    original = _entry()
    replacement = _entry(original.key, tag="replacement", created_at=101.0)
    store.put(original, now=100.0)
    store.put(replacement, now=101.0)
    assert _scalar(connection, "SELECT count(*) FROM proof_entries") == 1
    assert _scalar(connection, "SELECT count(*) FROM proof_evidence") == 1
    assert _scalar(connection, "SELECT count(*) FROM proof_entries WHERE entry_digest=?", [original.entry_digest]) == 0
    assert _scalar(connection, "SELECT count(*) FROM proof_evidence WHERE entry_digest=?", [original.entry_digest]) == 0
    _assert_observation(DuckDBProofStore(connection=connection).get(original.key, now=101.0), replacement)


def test_warm_memory_cannot_mask_deleted_sql_entry(sql_store):
    _, connection, store = sql_store
    entry = _entry()
    store.put(entry, now=100.0)
    _assert_observation(store.get(entry.key, now=100.0), entry)
    connection.execute("DELETE FROM proof_entries WHERE key_digest=?", [entry.key.digest])
    # A retained key with no entry is catalog corruption, not a legitimate miss.
    with pytest.raises(DuckDBProofStoreIntegrityError):
        store.lookup(entry.key, now=100.0)


def test_complete_sql_delete_is_a_miss_despite_warm_memory(sql_store):
    _, connection, store = sql_store
    entry = _entry()
    store.put(entry, now=100.0)
    connection.execute("BEGIN TRANSACTION")
    connection.execute("DELETE FROM proof_evidence WHERE entry_digest=?", [entry.entry_digest])
    for table in ("proof_key_dimensions", "premises", "proof_entries", "proof_keys"):
        connection.execute("DELETE FROM " + table + " WHERE key_digest=?", [entry.key.digest])
    connection.execute("COMMIT")
    assert not store.lookup(entry.key, now=100.0).usable
    assert store.get(entry.key, now=100.0) is None


def test_warm_memory_cannot_mask_missing_sql_key(sql_store):
    _, connection, store = sql_store
    entry = _entry()
    store.put(entry, now=100.0)
    connection.execute("DELETE FROM proof_keys WHERE key_digest=?", [entry.key.digest])
    with pytest.raises(DuckDBProofStoreIntegrityError):
        store.lookup(entry.key, now=100.0)


@pytest.mark.parametrize("corruption", (
    "key_column", "key_payload", "dimension", "missing_dimension", "premise",
    "entry_status", "entry_payload", "evidence_payload",
))
def test_sql_tamper_is_visible_and_never_uses_warm_memory(sql_store, corruption):
    _, connection, store = sql_store
    entry = _entry()
    store.put(entry, now=100.0)
    if corruption == "key_column":
        connection.execute("UPDATE proof_keys SET ir_digest=? WHERE key_digest=?", ["sha256:" + "f" * 64, entry.key.digest])
    elif corruption == "key_payload":
        connection.execute("UPDATE proof_keys SET key_payload_json='{}' WHERE key_digest=?", [entry.key.digest])
    elif corruption == "dimension":
        connection.execute("UPDATE proof_key_dimensions SET dimension_digest=? WHERE key_digest=? AND dimension_name='tree'", ["sha256:" + "f" * 64, entry.key.digest])
    elif corruption == "missing_dimension":
        connection.execute("DELETE FROM proof_key_dimensions WHERE key_digest=? AND dimension_name='tree'", [entry.key.digest])
    elif corruption == "premise":
        connection.execute("UPDATE premises SET premise_ordinal=99 WHERE key_digest=? AND premise_ordinal=0", [entry.key.digest])
    elif corruption == "entry_status":
        connection.execute("UPDATE proof_entries SET status='proved' WHERE key_digest=?", [entry.key.digest])
    elif corruption == "entry_payload":
        connection.execute("UPDATE proof_entries SET payload_json='{}' WHERE key_digest=?", [entry.key.digest])
    else:
        connection.execute("UPDATE proof_evidence SET payload_json='{}' WHERE entry_digest=?", [entry.entry_digest])
    with pytest.raises(DuckDBProofStoreIntegrityError):
        store.lookup(entry.key, now=100.0)


@pytest.mark.parametrize("corruption", ("duplicate", "unknown", "schema", "nonfinite"))
def test_sql_entry_json_is_strict_and_closed(sql_store, corruption):
    _, connection, store = sql_store
    entry = _entry()
    store.put(entry, now=100.0)
    document = entry.to_dict()
    if corruption == "duplicate":
        raw = json.dumps(document)
        raw = '{"schema_version":' + json.dumps(document["schema_version"]) + "," + raw[1:]
    else:
        if corruption == "unknown":
            document["unsupported_authority"] = True
        elif corruption == "schema":
            document["schema_version"] = "unified-proof-entry/v999"
        else:
            document["created_at"] = float("nan")
        raw = json.dumps(document)
    connection.execute("UPDATE proof_entries SET payload_json=? WHERE key_digest=?", [raw, entry.key.digest])
    with pytest.raises(DuckDBProofStoreIntegrityError):
        store.lookup(entry.key, now=100.0)


@pytest.mark.parametrize("table,column,oversize", (
    ("proof_keys", "key_payload_json", 64 * 1024 + 1),
    ("proof_entries", "payload_json", 8 * 1024 * 1024 + 1),
))
def test_oversized_sql_json_row_is_refused(sql_store, table, column, oversize):
    _, connection, store = sql_store
    entry = _entry()
    store.put(entry, now=100.0)
    # Identifiers are closed parameters above; only the oversized value is data.
    connection.execute(f"UPDATE {table} SET {column}=? WHERE key_digest=?", [" " * oversize, entry.key.digest])
    with pytest.raises(DuckDBProofStoreIntegrityError):
        store.lookup(entry.key, now=100.0)


class _FailEntryInsert:
    """Inject one SQL failure while keeping a genuine DuckDB transaction."""

    def __init__(self, connection):
        self.connection = connection
        self.armed = False

    def execute(self, sql, parameters=None):
        if self.armed and sql.lstrip().upper().startswith("INSERT") and "proof_entries" in sql.lower():
            self.armed = False
            raise RuntimeError("injected proof entry insertion failure")
        return self.connection.execute(sql) if parameters is None else self.connection.execute(sql, parameters)

    def __getattr__(self, name):
        return getattr(self.connection, name)


def test_failed_sql_overwrite_rolls_back_and_is_visible(sql_store):
    _, connection, _ = sql_store
    injected = _FailEntryInsert(connection)
    store = DuckDBProofStore(connection=injected, max_entries=16)
    original = _entry()
    replacement = _entry(original.key, tag="must-not-commit", created_at=101.0)
    store.put(original, now=100.0)
    before = store.stats()["writes"]
    injected.armed = True
    with pytest.raises(DuckDBProofStoreError, match="injected|SQL|persist|transaction"):
        store.put(replacement, now=101.0)
    assert store.stats()["writes"] == before
    assert _scalar(connection, "SELECT count(*) FROM proof_entries") == 1
    assert _scalar(connection, "SELECT count(*) FROM proof_evidence") == 1
    _assert_observation(store.get(original.key, now=101.0), original)
    _assert_observation(DuckDBProofStore(connection=connection).get(original.key, now=101.0), original)


def test_sql_schema_failure_does_not_return_memory_success(sql_store):
    _, connection, store = sql_store
    entry = _entry()
    store.put(entry, now=100.0)
    connection.execute("DROP TABLE proof_entries")
    with pytest.raises(DuckDBProofStoreError):
        store.lookup(entry.key, now=100.0)


def test_invalidate_from_cold_projected_key_cannot_resurrect(sql_store):
    _, connection, store = sql_store
    entry = _entry()
    store.put(entry, now=100.0)
    cold = DuckDBProofStore(connection=connection)
    assert cold.invalidate(entry.key.to_verification_cache_key()) is True
    assert cold.invalidate(entry.key.to_verification_cache_key()) is False
    for table in ("proof_keys", "proof_entries", "proof_key_dimensions", "premises", "proof_evidence"):
        assert _scalar(connection, "SELECT count(*) FROM " + table) == 0
    assert DuckDBProofStore(connection=connection).get(entry.key, now=100.0) is None


def test_clear_from_cold_store_cannot_resurrect_any_entry(sql_store):
    _, connection, store = sql_store
    first = _entry()
    second = _entry(_key(ir={"family": "tdfol"}), tag="tdfol")
    store.put(first, now=100.0)
    store.put(second, now=100.0)
    DuckDBProofStore(connection=connection).clear()
    reopened = DuckDBProofStore(connection=connection)
    assert reopened.get(first.key, now=100.0) is None
    assert reopened.get(second.key, now=100.0) is None
    for table in ("proof_keys", "proof_entries", "proof_key_dimensions", "premises", "proof_evidence"):
        assert _scalar(connection, "SELECT count(*) FROM " + table) == 0


def test_expired_negative_entry_is_deleted_durably(sql_store):
    _, connection, _ = sql_store
    store = DuckDBProofStore(connection=connection, positive_ttl_seconds=100, negative_ttl_seconds=2)
    entry = _entry()
    store.put(entry, now=100.0)
    result = store.lookup(entry.key, now=103.0)
    assert not result.usable and result.reason is CacheLookupReason.EXPIRED
    assert _scalar(connection, "SELECT count(*) FROM proof_entries") == 0
    assert DuckDBProofStore(connection=connection).get(entry.key, now=100.0) is None


def test_persisted_key_scan_respects_store_capacity(sql_store):
    _, connection, store = sql_store
    first = _entry()
    second = _entry(_key(ir={"family": "tdfol"}), tag="tdfol")
    store.put(first, now=100.0)
    store.put(second, now=100.0)
    bounded = DuckDBProofStore(connection=connection, max_entries=1)
    with pytest.raises(DuckDBProofStoreIntegrityError):
        bounded.lookup(first.key.to_verification_cache_key(), now=100.0)


def test_capacity_eviction_survives_real_file_reopen(duckdb_module, tmp_path):
    path = tmp_path / "capacity.duckdb"
    first = _entry(created_at=100.0)
    second = _entry(_key(ir={"family": "tdfol"}), tag="newer", created_at=101.0)
    connection = duckdb_module.connect(str(path))
    try:
        store = DuckDBProofStore(connection=connection, max_entries=1)
        store.put(first, now=100.0)
        store.put(second, now=101.0)
        assert _scalar(connection, "SELECT count(*) FROM proof_entries") == 1
        assert _scalar(connection, "SELECT count(*) FROM proof_keys") == 1
        assert _scalar(connection, "SELECT count(*) FROM proof_key_dimensions") == 15
        assert _scalar(connection, "SELECT count(*) FROM proof_evidence") == 1
    finally:
        connection.close()
    connection = duckdb_module.connect(str(path))
    try:
        reopened = DuckDBProofStore(connection=connection, max_entries=1)
        assert reopened.get(first.key, now=101.0) is None
        _assert_observation(reopened.get(second.key, now=101.0), second)
    finally:
        connection.close()


def test_already_expired_write_rolls_back_without_stored_claim(sql_store):
    _, connection, _ = sql_store
    store = DuckDBProofStore(connection=connection, positive_ttl_seconds=100, negative_ttl_seconds=2)
    original = _entry(created_at=100.0)
    expired = _entry(original.key, tag="expired", created_at=90.0)
    store.put(original, now=100.0)
    before = store.stats()["writes"]
    with pytest.raises(DuckDBProofStoreError):
        store.put(expired, now=101.0)
    assert store.stats()["writes"] == before
    assert _scalar(connection, "SELECT count(*) FROM proof_entries") == 1
    assert _scalar(connection, "SELECT count(*) FROM proof_key_dimensions") == 15
    assert _scalar(connection, "SELECT count(*) FROM proof_evidence") == 1
    _assert_observation(store.get(original.key, now=101.0), original)
    _assert_observation(DuckDBProofStore(connection=connection).get(original.key, now=101.0), original)


def test_active_caller_transaction_is_not_committed_by_store(sql_store):
    _, connection, store = sql_store
    connection.execute("BEGIN TRANSACTION")
    try:
        with pytest.raises(DuckDBProofStoreError):
            store.put(_entry(), now=100.0)
    finally:
        connection.execute("ROLLBACK")
    assert _scalar(connection, "SELECT count(*) FROM proof_entries") == 0
    assert store.stats()["writes"] == 0


def test_unknown_observation_never_satisfies_theorem_authority(sql_store):
    _, connection, store = sql_store
    entry = _entry()
    store.put(entry, now=100.0)
    reopened = DuckDBProofStore(connection=connection)
    observed = reopened.lookup(entry.key, require_result_authority=ResultAuthority.THEOREM, now=100.0)
    assert observed.hit and not observed.usable
    assert observed.reason is CacheLookupReason.AUTHORITY_MISMATCH
    assert observed.entry.status is ResultStatus.UNKNOWN
    assert observed.entry.result_authority is ResultAuthority.CANDIDATE
    assert observed.entry.evidence_authority is EvidenceAuthority.NONE
    assert reopened.get(entry.key, require_result_authority=ResultAuthority.THEOREM, now=100.0) is None
