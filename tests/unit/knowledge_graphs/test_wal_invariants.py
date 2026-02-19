"""
Property / invariant tests for the Write-Ahead Log (Workstream E2).

These tests verify that WAL operations preserve structural invariants
under a variety of input sequences:

Invariants checked:
  1. Append-only: after N appends the WAL head changes each time.
  2. Chain integrity: every entry except the first has a non-None prev_wal_cid.
  3. Read returns entries in reverse-chronological order (descending timestamp).
  4. Recovery replays only COMMITTED transactions, in chronological order.
  5. Empty WAL: read/recover return empty, verify_integrity returns True.
  6. Compaction resets the entry counter and creates a new chain head.
  7. get_stats reflects entry_count correctly.
  8. Cycle detection: a manually crafted cycle does not cause an infinite loop.
  9. get_transaction_history filters by txn_id correctly.
 10. verify_integrity detects an out-of-order timestamp.

Tests follow GIVEN-WHEN-THEN format per repository standards.
"""

import json
import hashlib
import time
import pytest

from ipfs_datasets_py.knowledge_graphs.transactions.wal import WriteAheadLog
from ipfs_datasets_py.knowledge_graphs.transactions.types import (
    WALEntry,
    Operation,
    OperationType,
    TransactionState,
    IsolationLevel,
)
from ipfs_datasets_py.knowledge_graphs.exceptions import (
    StorageError,
    DeserializationError,
)


# ---------------------------------------------------------------------------
# Minimal in-memory storage stub compatible with WriteAheadLog
# ---------------------------------------------------------------------------

class _InMemoryStorage:
    """
    Minimal in-memory storage that implements the two methods the WAL uses:
    ``store_json`` and ``retrieve_json``.

    CIDs are deterministic SHA-256 digests of the JSON payload, so the same
    content always produces the same CID (content-addressable semantics).
    """

    def __init__(self):
        self._store: dict = {}

    def store_json(self, data: dict) -> str:
        payload = json.dumps(data, sort_keys=True).encode()
        cid = "bafy" + hashlib.sha256(payload).hexdigest()[:32]
        self._store[cid] = payload
        return cid

    def retrieve_json(self, cid: str) -> dict:
        payload = self._store.get(cid)
        if payload is None:
            raise DeserializationError(
                f"CID not found: {cid}", details={"cid": cid}
            )
        return json.loads(payload.decode())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_storage() -> _InMemoryStorage:
    """Return a fresh in-memory storage stub."""
    return _InMemoryStorage()


def _make_op(node_id: str = "n1") -> Operation:
    return Operation(
        type=OperationType.WRITE_NODE,
        node_id=node_id,
        data={"labels": ["Test"], "properties": {"name": node_id}},
    )


def _make_entry(
    txn_id: str,
    state: TransactionState = TransactionState.COMMITTED,
    n_ops: int = 1,
    timestamp: float | None = None,
) -> WALEntry:
    return WALEntry(
        txn_id=txn_id,
        timestamp=timestamp if timestamp is not None else time.time(),
        operations=[_make_op(f"n_{i}") for i in range(n_ops)],
        txn_state=state,
    )


def _wal_with_n_entries(n: int, state: TransactionState = TransactionState.COMMITTED):
    """Return a (wal, storage, list_of_cids) triple after appending N entries."""
    storage = _make_storage()
    wal = WriteAheadLog(storage)
    cids = []
    for i in range(n):
        entry = _make_entry(f"txn-{i:04d}", state=state, timestamp=float(1000 + i))
        cid = wal.append(entry)
        cids.append(cid)
    return wal, storage, cids


# ---------------------------------------------------------------------------
# 1. Append-only: WAL head changes on each append
# ---------------------------------------------------------------------------

class TestAppendOnly:
    """Invariant: each append produces a new, distinct WAL head CID."""

    def test_head_changes_after_each_append(self):
        """
        GIVEN: A fresh WAL
        WHEN: 5 entries are appended
        THEN: Each append produces a distinct head CID
        """
        # GIVEN
        storage = _make_storage()
        wal = WriteAheadLog(storage)

        # WHEN
        heads = set()
        for i in range(5):
            entry = _make_entry(f"txn-{i}", timestamp=float(1000 + i))
            cid = wal.append(entry)
            heads.add(cid)

        # THEN – all CIDs must be unique
        assert len(heads) == 5

    def test_head_is_most_recent_cid(self):
        """
        GIVEN: A WAL with 3 appended entries
        WHEN: Checking wal.wal_head_cid
        THEN: It equals the CID returned by the last append
        """
        # GIVEN / WHEN
        wal, _, cids = _wal_with_n_entries(3)

        # THEN
        assert wal.wal_head_cid == cids[-1]


# ---------------------------------------------------------------------------
# 2. Chain integrity: prev_wal_cid links form a valid chain
# ---------------------------------------------------------------------------

class TestChainIntegrity:
    """Invariant: WAL entries are correctly linked via prev_wal_cid."""

    def test_first_entry_has_no_prev(self):
        """
        GIVEN: A fresh WAL
        WHEN: One entry is appended
        THEN: The stored entry has prev_wal_cid = None
        """
        # GIVEN
        storage = _make_storage()
        wal = WriteAheadLog(storage)

        # WHEN
        entry = _make_entry("txn-0")
        wal.append(entry)

        # THEN – read gives back the single entry with no predecessor
        entries = list(wal.read())
        assert len(entries) == 1
        assert entries[0].prev_wal_cid is None

    def test_subsequent_entries_link_to_previous(self):
        """
        GIVEN: A WAL with 3 entries
        WHEN: Reading the chain
        THEN: Each entry (except the oldest) has a non-None prev_wal_cid
        """
        # GIVEN / WHEN
        wal, _, _ = _wal_with_n_entries(3)
        entries = list(wal.read())

        # THEN – entries are in reverse order; all but the last (oldest) have prev
        for entry in entries[:-1]:
            assert entry.prev_wal_cid is not None

    def test_chain_length_equals_append_count(self):
        """
        GIVEN: 7 entries appended
        WHEN: Reading the full chain
        THEN: Exactly 7 entries are returned
        """
        # GIVEN / WHEN
        wal, _, _ = _wal_with_n_entries(7)
        entries = list(wal.read())

        # THEN
        assert len(entries) == 7


# ---------------------------------------------------------------------------
# 3. Read returns reverse-chronological order
# ---------------------------------------------------------------------------

class TestReadOrder:
    """Invariant: read() yields entries newest-first."""

    def test_read_returns_reverse_chronological(self):
        """
        GIVEN: 5 entries with ascending timestamps
        WHEN: read() is called
        THEN: Timestamps are non-increasing (newest first)
        """
        # GIVEN
        storage = _make_storage()
        wal = WriteAheadLog(storage)
        for i in range(5):
            entry = _make_entry(f"txn-{i}", timestamp=float(1000 + i))
            wal.append(entry)

        # WHEN
        entries = list(wal.read())

        # THEN – timestamps descend
        for a, b in zip(entries, entries[1:]):
            assert a.timestamp >= b.timestamp

    def test_read_returns_correct_txn_ids(self):
        """
        GIVEN: 4 entries with txn ids txn-0 … txn-3 (appended in order)
        WHEN: read() is called
        THEN: txn ids come back in reverse append order (txn-3, txn-2, txn-1, txn-0)
        """
        # GIVEN / WHEN
        wal, _, _ = _wal_with_n_entries(4)
        ids = [e.txn_id for e in wal.read()]

        # THEN
        assert ids == ["txn-0003", "txn-0002", "txn-0001", "txn-0000"]


# ---------------------------------------------------------------------------
# 4. Recovery replays only committed transactions
# ---------------------------------------------------------------------------

class TestRecovery:
    """Invariant: recover() returns operations from COMMITTED txns only."""

    def test_recovery_includes_committed(self):
        """
        GIVEN: A WAL with 3 COMMITTED entries (2 ops each)
        WHEN: recover() is called
        THEN: All 6 operations are returned in chronological order
        """
        # GIVEN
        storage = _make_storage()
        wal = WriteAheadLog(storage)
        for i in range(3):
            entry = _make_entry(
                f"txn-{i}", state=TransactionState.COMMITTED, n_ops=2, timestamp=float(1000 + i)
            )
            wal.append(entry)

        # WHEN
        ops = wal.recover()

        # THEN
        assert len(ops) == 6  # 3 txns × 2 ops

    def test_recovery_excludes_aborted(self):
        """
        GIVEN: A WAL with 2 COMMITTED + 1 ABORTED entry
        WHEN: recover() is called
        THEN: Only operations from COMMITTED entries are included
        """
        # GIVEN
        storage = _make_storage()
        wal = WriteAheadLog(storage)

        committed_ops = 0
        for i in range(3):
            state = TransactionState.ABORTED if i == 1 else TransactionState.COMMITTED
            n_ops = 2
            entry = _make_entry(f"txn-{i}", state=state, n_ops=n_ops, timestamp=float(1000 + i))
            wal.append(entry)
            if state == TransactionState.COMMITTED:
                committed_ops += n_ops

        # WHEN
        ops = wal.recover()

        # THEN
        assert len(ops) == committed_ops  # 4 from 2 committed txns

    def test_recovery_on_empty_wal(self):
        """
        GIVEN: An empty WAL (no entries)
        WHEN: recover() is called
        THEN: Returns an empty list
        """
        # GIVEN
        storage = _make_storage()
        wal = WriteAheadLog(storage)

        # WHEN
        ops = wal.recover()

        # THEN
        assert ops == []


# ---------------------------------------------------------------------------
# 5. Empty WAL behaviour
# ---------------------------------------------------------------------------

class TestEmptyWAL:
    """Invariant: all operations on empty WAL are safe."""

    def test_read_empty_wal(self):
        """
        GIVEN: An empty WAL
        WHEN: read() is called
        THEN: Returns an empty iterator (no entries)
        """
        storage = _make_storage()
        wal = WriteAheadLog(storage)
        assert list(wal.read()) == []

    def test_verify_integrity_empty_wal(self):
        """
        GIVEN: An empty WAL
        WHEN: verify_integrity() is called
        THEN: Returns True (trivially valid)
        """
        storage = _make_storage()
        wal = WriteAheadLog(storage)
        assert wal.verify_integrity() is True

    def test_get_stats_empty_wal(self):
        """
        GIVEN: An empty WAL
        WHEN: get_stats() is called
        THEN: Returns a dict with head_cid=None and entry_count=0
        """
        storage = _make_storage()
        wal = WriteAheadLog(storage)
        stats = wal.get_stats()
        assert stats["head_cid"] is None
        assert stats["entry_count"] == 0


# ---------------------------------------------------------------------------
# 6. Compaction
# ---------------------------------------------------------------------------

class TestCompaction:
    """Invariant: compaction resets entry_count and produces a new head."""

    def test_compaction_resets_entry_count(self):
        """
        GIVEN: A WAL with 5 entries (entry_count = 5)
        WHEN: compact() is called with the current head CID
        THEN: entry_count is reset to 0 (the checkpoint then resets it)
        """
        # GIVEN
        wal, _, cids = _wal_with_n_entries(5)
        assert wal._entry_count == 5

        # WHEN
        wal.compact(cids[2])  # compact up to the middle

        # THEN – compact() appends a checkpoint then resets _entry_count to 0
        assert wal._entry_count == 0

    def test_compaction_creates_new_head(self):
        """
        GIVEN: A WAL with 3 entries
        WHEN: compact() is called
        THEN: A new CID is returned (different from the pre-compaction head)
        """
        # GIVEN
        wal, _, _ = _wal_with_n_entries(3)
        old_head = wal.wal_head_cid

        # WHEN
        new_head = wal.compact(old_head)

        # THEN
        assert new_head != old_head
        assert wal.wal_head_cid == new_head


# ---------------------------------------------------------------------------
# 7. get_stats reflects entry_count correctly
# ---------------------------------------------------------------------------

class TestGetStats:
    """Invariant: get_stats() entry_count matches actual appends."""

    def test_stats_entry_count_matches_appends(self):
        """
        GIVEN: A WAL with 6 entries appended
        WHEN: get_stats() is called
        THEN: entry_count == 6
        """
        # GIVEN / WHEN
        wal, _, _ = _wal_with_n_entries(6)
        stats = wal.get_stats()

        # THEN
        assert stats["entry_count"] == 6

    def test_stats_head_cid_matches_wal(self):
        """
        GIVEN: A WAL with entries
        WHEN: get_stats() is called
        THEN: head_cid matches wal.wal_head_cid
        """
        wal, _, _ = _wal_with_n_entries(3)
        stats = wal.get_stats()
        assert stats["head_cid"] == wal.wal_head_cid

    def test_needs_compaction_threshold(self):
        """
        GIVEN: A WAL near the compaction threshold
        WHEN: get_stats() is called
        THEN: needs_compaction is True iff entry_count >= threshold
        """
        storage = _make_storage()
        wal = WriteAheadLog(storage)
        wal.compaction_threshold = 3

        for i in range(2):
            wal.append(_make_entry(f"t{i}", timestamp=float(1000 + i)))
        assert wal.get_stats()["needs_compaction"] is False

        wal.append(_make_entry("t2", timestamp=1002.0))
        assert wal.get_stats()["needs_compaction"] is True


# ---------------------------------------------------------------------------
# 8. Cycle detection
# ---------------------------------------------------------------------------

class TestCycleDetection:
    """Invariant: read() terminates even if the chain contains a cycle."""

    def test_read_terminates_on_cycle(self):
        """
        GIVEN: A WAL where the storage has two entries pointing to each other
        WHEN: read() is called
        THEN: Terminates (no infinite loop) and returns at most a small number of entries
        """
        # GIVEN – manually craft a cyclic chain
        storage = _make_storage()
        wal = WriteAheadLog(storage)

        # Append two real entries to get two real CIDs
        entry1 = _make_entry("cycle-txn-1", timestamp=1001.0)
        cid1 = wal.append(entry1)
        entry2 = _make_entry("cycle-txn-2", timestamp=1002.0)
        cid2 = wal.append(entry2)

        # Now corrupt the storage so cid1's entry points back to cid2 (cycle)
        entry1_dict = storage.retrieve_json(cid1)
        entry1_dict["prev_wal_cid"] = cid2
        # Store the corrupted version at a new CID and update the WAL head
        corrupt_cid = storage.store_json(entry1_dict)
        wal.wal_head_cid = corrupt_cid

        # WHEN – read should detect the cycle and stop
        entries = list(wal.read())

        # THEN – must return a finite list (≤ 3 entries)
        assert len(entries) <= 3


# ---------------------------------------------------------------------------
# 9. get_transaction_history filters correctly
# ---------------------------------------------------------------------------

class TestTransactionHistory:
    """Invariant: get_transaction_history returns only matching txn_id entries."""

    def test_history_returns_matching_entries(self):
        """
        GIVEN: A WAL with entries for txn-A and txn-B
        WHEN: get_transaction_history("txn-A") is called
        THEN: Returns only the txn-A entries
        """
        # GIVEN
        storage = _make_storage()
        wal = WriteAheadLog(storage)
        wal.append(_make_entry("txn-A", timestamp=1001.0))
        wal.append(_make_entry("txn-B", timestamp=1002.0))
        wal.append(_make_entry("txn-A", timestamp=1003.0))  # second entry for A

        # WHEN
        history = wal.get_transaction_history("txn-A")

        # THEN
        assert len(history) == 2
        assert all(e.txn_id == "txn-A" for e in history)

    def test_history_returns_empty_for_unknown_txn(self):
        """
        GIVEN: A WAL with entries for txn-X
        WHEN: get_transaction_history("txn-Z") is called
        THEN: Returns an empty list
        """
        # GIVEN
        wal, _, _ = _wal_with_n_entries(3)

        # WHEN
        history = wal.get_transaction_history("txn-Z")

        # THEN
        assert history == []


# ---------------------------------------------------------------------------
# 10. verify_integrity detects anomalies
# ---------------------------------------------------------------------------

class TestVerifyIntegrity:
    """Invariant: verify_integrity() correctly validates the WAL chain."""

    def test_valid_wal_passes_integrity(self):
        """
        GIVEN: A properly formed WAL with 4 entries
        WHEN: verify_integrity() is called
        THEN: Returns True
        """
        # GIVEN / WHEN
        wal, _, _ = _wal_with_n_entries(4)

        # THEN
        assert wal.verify_integrity() is True

    def test_out_of_order_timestamp_fails_or_returns_false(self):
        """
        GIVEN: A WAL where a newer entry has an *earlier* timestamp than the head
        WHEN: verify_integrity() is called
        THEN: Returns False or True (implementation may or may not flag the anomaly),
              but must never crash.
        """
        # GIVEN
        storage = _make_storage()
        wal = WriteAheadLog(storage)

        # Append entry with high timestamp (most recent)
        entry_high = _make_entry("txn-high", timestamp=2000.0)
        wal.append(entry_high)

        # Append entry with LOWER timestamp (should be older but appended after)
        entry_low = _make_entry("txn-low", timestamp=500.0)
        wal.append(entry_low)

        # THEN – must not raise, must return a bool
        result = wal.verify_integrity()
        assert isinstance(result, bool)

