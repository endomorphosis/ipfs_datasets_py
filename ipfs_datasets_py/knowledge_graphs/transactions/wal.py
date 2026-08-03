"""
Write-Ahead Log (WAL) Implementation

Provides persistent transaction logging on IPLD for crash recovery
and ACID guarantees. Supports multi-phase durable commit
(INTENT → PREPARE → PUBLISH → COMPLETE) with bounded records and
deterministic recovery actions at every durable boundary.
"""

from ipfs_datasets_py.utils import anyio_compat as asyncio
import anyio
import json
import logging
from typing import Dict, Iterator, List, Optional, Any, Tuple
from datetime import datetime
from collections import defaultdict


def _cancelled_exc_class() -> type:
    """Return the current async framework's cancellation exception class.

    Falls back to asyncio.CancelledError when called outside an async context.
    """
    try:
        return anyio.get_cancelled_exc_class()
    except anyio.NoEventLoopError:
        return asyncio.CancelledError


from .types import (
    WALEntry,
    Operation,
    TransactionState,
    IsolationLevel,
    OperationType,
    WALPhase,
    RecoveryAction,
    RecoveryDecision,
    RECOVERY_ACTION_MATRIX,
    recovery_action_for_phase,
    phase_rank,
    phase_to_txn_state,
    MAX_WAL_OPERATIONS_PER_ENTRY,
    MAX_WAL_ENTRY_BYTES,
    MAX_WRITE_SET_SIZE,
    MAX_READ_SET_SIZE,
    WALBoundExceededError,
)

# Import custom exceptions
from ..exceptions import (
    TransactionError,
    StorageError,
    SerializationError,
    DeserializationError,
)

logger = logging.getLogger(__name__)


class WriteAheadLog:
    """
    Write-Ahead Log stored on IPLD.

    WAL entries are immutable and linked by CIDs, forming an append-only
    log of all transactions. Enables crash recovery and provides durability.

    Features:
    - Append-only log structure
    - CID-based linking (prev_wal_cid)
    - Multi-phase durable records (INTENT/PREPARE/PUBLISH/COMPLETE/ABORT)
    - Hard bounds on operations, payload size, and set sizes
    - Compaction for old entries
    - Recovery with exact per-boundary actions
    - Idempotent replay tracking
    - IPLD-native storage

    Attributes:
        storage: IPLDBackend for storing WAL entries
        wal_head_cid: CID of most recent WAL entry
        compaction_threshold: Number of entries before compaction
        max_operations_per_entry: Bound on inline ops
        max_entry_bytes: Bound on serialized entry size
    """

    def __init__(
        self,
        storage,
        wal_head_cid: Optional[str] = None,
        *,
        max_operations_per_entry: int = MAX_WAL_OPERATIONS_PER_ENTRY,
        max_entry_bytes: int = MAX_WAL_ENTRY_BYTES,
        max_write_set_size: int = MAX_WRITE_SET_SIZE,
        max_read_set_size: int = MAX_READ_SET_SIZE,
    ):
        """
        Initialize Write-Ahead Log.

        Args:
            storage: IPLDBackend instance for persistence
            wal_head_cid: CID of current WAL head (None for empty log)
            max_operations_per_entry: Hard bound on ops per record
            max_entry_bytes: Hard bound on serialized JSON bytes
            max_write_set_size: Hard bound on write_set length
            max_read_set_size: Hard bound on read_set length
        """
        self.storage = storage
        self.wal_head_cid = wal_head_cid
        self.compaction_threshold = 1000  # Entries before compaction
        self._entry_count = 0
        self.max_operations_per_entry = int(max_operations_per_entry)
        self.max_entry_bytes = int(max_entry_bytes)
        self.max_write_set_size = int(max_write_set_size)
        self.max_read_set_size = int(max_read_set_size)
        # Idempotent replay: (idempotency_key or txn_id+phase) → wal cid
        self._applied_keys: Dict[str, str] = {}

        logger.info(f"WriteAheadLog initialized with head: {wal_head_cid}")

    # ------------------------------------------------------------------
    # Bounds enforcement
    # ------------------------------------------------------------------

    def _check_bounds(self, entry: WALEntry) -> bytes:
        """
        Validate WAL entry against hard bounds.

        Returns the serialized UTF-8 payload used for the size check
        (caller may re-serialize; this is only for validation).

        Raises:
            WALBoundExceededError: if any bound is violated
            SerializationError: if the entry cannot be serialized
        """
        ops = getattr(entry, "operations", None) or []
        if len(ops) > self.max_operations_per_entry:
            raise WALBoundExceededError(
                f"WAL entry operations exceed bound "
                f"{self.max_operations_per_entry}",
                details={
                    "bound": self.max_operations_per_entry,
                    "actual": len(ops),
                    "txn_id": str(entry.txn_id),
                    "bound_kind": "operations",
                },
            )
        write_set = getattr(entry, "write_set", None) or []
        if len(write_set) > self.max_write_set_size:
            raise WALBoundExceededError(
                f"WAL write_set exceeds bound {self.max_write_set_size}",
                details={
                    "bound": self.max_write_set_size,
                    "actual": len(write_set),
                    "txn_id": str(entry.txn_id),
                    "bound_kind": "write_set",
                },
            )
        read_set = getattr(entry, "read_set", None) or []
        if len(read_set) > self.max_read_set_size:
            raise WALBoundExceededError(
                f"WAL read_set exceeds bound {self.max_read_set_size}",
                details={
                    "bound": self.max_read_set_size,
                    "actual": len(read_set),
                    "txn_id": str(entry.txn_id),
                    "bound_kind": "read_set",
                },
            )
        try:
            payload = json.dumps(entry.to_dict(), sort_keys=True).encode("utf-8")
        except (TypeError, ValueError) as e:
            raise SerializationError(
                f"Failed to serialize WAL entry for bound check: {e}",
                details={"txn_id": str(entry.txn_id)},
            ) from e
        if len(payload) > self.max_entry_bytes:
            raise WALBoundExceededError(
                f"WAL entry size exceeds bound {self.max_entry_bytes} bytes",
                details={
                    "bound": self.max_entry_bytes,
                    "actual": len(payload),
                    "txn_id": str(entry.txn_id),
                    "bound_kind": "entry_bytes",
                },
            )
        return payload

    def _replay_key(self, entry: WALEntry) -> Optional[str]:
        """
        Stable key for idempotent phase application.

        Only entries with an explicit ``idempotency_key`` participate in
        idempotent replay. Bare multi-entry histories for the same txn_id
        (e.g. PREPARE then COMPLETE, or two ACTIVE records) always append.
        """
        if entry.idempotency_key:
            phase = entry.resolved_phase().value
            return f"idem:{entry.idempotency_key}:{phase}:{entry.record_seq}"
        return None

    # ------------------------------------------------------------------
    # Append / multi-phase helpers
    # ------------------------------------------------------------------

    def append(self, entry: WALEntry) -> str:
        """
        Append WAL entry to log and return its CID.

        Creates an immutable entry on IPLD linked to previous entry.
        Enforces hard bounds and idempotent phase replay: re-appending
        the same phase for the same idempotency key returns the prior CID.

        Args:
            entry: WALEntry to append

        Returns:
            CID of the appended entry (new WAL head), or prior CID if
            this phase was already applied (idempotent replay)

        Raises:
            WALBoundExceededError: if entry exceeds configured bounds
            SerializationError / TransactionError: on storage failures
        """
        try:
            # Idempotent replay of an already-applied phase (keyed only)
            key = self._replay_key(entry)
            if key is not None and key in self._applied_keys:
                prior = self._applied_keys[key]
                logger.debug(
                    "Idempotent WAL append skip: key=%s cid=%s", key, prior
                )
                return prior

            # Bound check before linking/storing
            self._check_bounds(entry)

            # Set previous WAL CID to current head
            entry.prev_wal_cid = self.wal_head_cid

            # Convert to dictionary for IPLD storage
            entry_dict = entry.to_dict()

            # Store on IPLD
            cid = self.storage.store_json(entry_dict)

            # Update WAL head
            self.wal_head_cid = cid
            self._entry_count += 1
            if key is not None:
                self._applied_keys[key] = cid

            logger.debug(f"WAL entry appended: {cid} (txn: {entry.txn_id})")

            # Check if compaction needed
            if self._entry_count >= self.compaction_threshold:
                logger.info(
                    f"Compaction threshold reached: {self._entry_count} entries"
                )

            return cid

        except WALBoundExceededError:
            raise
        except SerializationError:
            raise
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize WAL entry: {e}")
            operation_types = []
            for op in getattr(entry, "operations", []) or []:
                op_type = getattr(op, "type", None)
                operation_types.append(
                    getattr(op_type, "value", str(op_type) if op_type is not None else str(op))
                )
            raise SerializationError(
                f"Failed to serialize WAL entry: {e}",
                details={
                    "txn_id": str(entry.txn_id),
                    "operation_count": len(getattr(entry, "operations", []) or []),
                    "operation_types": operation_types,
                },
            ) from e
        except StorageError as e:
            logger.error(f"Storage failure appending WAL entry: {e}")
            raise TransactionError(
                f"Failed to append WAL entry due to storage error: {e}",
                details={"txn_id": str(entry.txn_id)},
            ) from e
        except _cancelled_exc_class():
            raise
        except Exception as e:
            logger.error(f"Failed to append WAL entry: {e}")
            raise TransactionError(
                f"Failed to append WAL entry: {e}",
                details={
                    "txn_id": str(entry.txn_id),
                    "error": str(e),
                    "error_class": type(e).__name__,
                },
            ) from e

    def append_phase(
        self,
        *,
        txn_id: str,
        phase: WALPhase,
        operations: Optional[List[Operation]] = None,
        isolation_level: IsolationLevel = IsolationLevel.REPEATABLE_READ,
        read_set: Optional[List[str]] = None,
        write_set: Optional[List[str]] = None,
        tenant: Optional[str] = None,
        graph_id: Optional[str] = None,
        branch: Optional[str] = None,
        base_revision: Optional[str] = None,
        new_revision: Optional[str] = None,
        staged_root_cid: Optional[str] = None,
        lease_id: Optional[str] = None,
        lease_epoch: Optional[int] = None,
        idempotency_key: Optional[str] = None,
        record_seq: int = 0,
        timestamp: Optional[float] = None,
    ) -> str:
        """
        Append a multi-phase durable WAL record.

        Convenience wrapper around :meth:`append` that sets
        ``phase`` and corresponding ``txn_state``.
        """
        entry = WALEntry(
            txn_id=txn_id,
            timestamp=timestamp if timestamp is not None else datetime.now().timestamp(),
            operations=list(operations or []),
            txn_state=phase_to_txn_state(phase),
            isolation_level=isolation_level,
            read_set=list(read_set or []),
            write_set=list(write_set or []),
            phase=phase,
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            base_revision=base_revision,
            new_revision=new_revision,
            staged_root_cid=staged_root_cid,
            lease_id=lease_id,
            lease_epoch=lease_epoch,
            idempotency_key=idempotency_key,
            record_seq=record_seq,
        )
        return self.append(entry)

    def read(self, from_cid: Optional[str] = None) -> Iterator[WALEntry]:
        """
        Read WAL entries from specified CID backwards through the chain.

        Follows prev_wal_cid links to traverse the log.

        Args:
            from_cid: CID to start reading from (defaults to current head)

        Yields:
            WALEntry instances in reverse chronological order
        """
        current_cid = from_cid or self.wal_head_cid

        if not current_cid:
            logger.debug("WAL is empty, no entries to read")
            return

        visited = set()  # Prevent infinite loops

        while current_cid:
            # Prevent loops in WAL chain
            if current_cid in visited:
                logger.warning(f"Cycle detected in WAL chain at: {current_cid}")
                break
            visited.add(current_cid)

            try:
                # Retrieve entry from IPLD
                entry_dict = self.storage.retrieve_json(current_cid)
                entry = WALEntry.from_dict(entry_dict)

                yield entry

                # Move to previous entry
                current_cid = entry.prev_wal_cid

            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
                logger.warning(
                    f"Failed to read WAL entry {current_cid} (continuing): {e}"
                )
                break
            except DeserializationError:
                raise
            except StorageError as e:
                logger.error(f"Storage failure reading WAL entry {current_cid}: {e}")
                raise DeserializationError(
                    f"Failed to deserialize WAL entry due to storage error: {e}",
                    details={"cid": str(current_cid)},
                ) from e
            except _cancelled_exc_class():
                raise
            except Exception as e:
                logger.error(f"Failed to read WAL entry {current_cid}: {e}")
                raise TransactionError(
                    f"Failed to read WAL entry: {e}",
                    details={
                        "cid": str(current_cid),
                        "error": str(e),
                        "error_class": type(e).__name__,
                    },
                ) from e

    def compact(self, checkpoint_cid: str) -> str:
        """
        Compact WAL by creating checkpoint and pruning old entries.

        Creates a new checkpoint entry that consolidates state up to
        the specified CID, allowing old entries to be garbage collected.

        Args:
            checkpoint_cid: CID to compact up to

        Returns:
            CID of the new checkpoint entry
        """
        try:
            logger.info(f"Compacting WAL up to: {checkpoint_cid}")

            # Create checkpoint entry
            checkpoint_entry = WALEntry(
                txn_id=f"checkpoint-{datetime.now().timestamp()}",
                timestamp=datetime.now().timestamp(),
                operations=[],  # No operations in checkpoint
                prev_wal_cid=checkpoint_cid,
                txn_state=TransactionState.COMMITTED,
                phase=WALPhase.COMPLETE,
            )

            # Store checkpoint
            checkpoint_entry_cid = self.append(checkpoint_entry)

            # Reset entry count after compaction
            self._entry_count = 0

            logger.info(f"WAL compacted, checkpoint: {checkpoint_entry_cid}")

            return checkpoint_entry_cid

        except SerializationError:
            raise
        except WALBoundExceededError:
            raise
        except TransactionError:
            raise
        except _cancelled_exc_class():
            raise
        except Exception as e:
            logger.error(f"Failed to compact WAL: {e}")
            raise TransactionError(
                f"Failed to compact WAL: {e}",
                details={
                    "entry_count": self._entry_count,
                    "threshold": self.compaction_threshold,
                    "error": str(e),
                    "error_class": type(e).__name__,
                },
            ) from e

    def recover(self, wal_head_cid: Optional[str] = None) -> List[Operation]:
        """
        Recover operations from WAL for crash recovery.

        Replays all operations from committed / complete transactions to
        restore graph state after a crash. PREPARE/PUBLISH-without-COMPLETE
        transactions are intentionally excluded (see :meth:`plan_recovery`).

        Args:
            wal_head_cid: CID to recover from (defaults to current head)

        Returns:
            List of operations to replay in chronological order
        """
        try:
            start_cid = wal_head_cid or self.wal_head_cid

            if not start_cid:
                logger.info("No WAL head, nothing to recover")
                return []

            logger.info(f"Starting recovery from WAL head: {start_cid}")

            # Collect all committed operations
            operations_to_replay = []
            entries_processed = 0
            committed_states = {
                TransactionState.COMMITTED,
                TransactionState.COMPLETE,
            }

            for entry in self.read(start_cid):
                entries_processed += 1
                phase = entry.resolved_phase()

                # Only recover fully complete / legacy committed transactions
                if (
                    entry.txn_state in committed_states
                    or phase == WALPhase.COMPLETE
                ):
                    operations_to_replay.extend(entry.operations)
                    logger.debug(
                        f"Recovered {len(entry.operations)} ops from txn: {entry.txn_id}"
                    )
                else:
                    logger.debug(
                        f"Skipping non-committed txn: {entry.txn_id} "
                        f"(state: {entry.txn_state}, phase: {phase})"
                    )

            # Reverse to get chronological order (read returns reverse)
            operations_to_replay.reverse()

            logger.info(
                f"Recovery complete: {len(operations_to_replay)} operations "
                f"from {entries_processed} entries"
            )

            return operations_to_replay

        except DeserializationError:
            raise
        except TransactionError:
            raise
        except _cancelled_exc_class():
            raise
        except Exception as e:
            logger.error(f"Failed to recover from WAL: {e}")
            raise TransactionError(
                f"Failed to recover from WAL: {e}",
                details={
                    "wal_head": str(self.wal_head_cid) if self.wal_head_cid else None,
                    "error": str(e),
                    "error_class": type(e).__name__,
                },
            ) from e

    def plan_recovery(
        self, wal_head_cid: Optional[str] = None
    ) -> List[RecoveryDecision]:
        """
        Plan exact recovery actions at every durable boundary.

        Groups WAL entries by ``txn_id``, finds the terminal durable phase
        for each transaction, and maps it through ``RECOVERY_ACTION_MATRIX``.

        Recovery rules (exact):
        - INTENT only          → DISCARD_STAGED  (never expose partial head)
        - PREPARE (no publish) → DISCARD_STAGED  (staged objects unreachable)
        - PUBLISH (no complete)→ FINISH_PUBLICATION (idempotent complete)
        - COMPLETE / COMMITTED → IDEMPOTENT_SKIP
        - ABORT                → ABORT_CLEANUP

        Args:
            wal_head_cid: Optional head override

        Returns:
            List of RecoveryDecision (one per distinct txn_id), chronological
            by first-seen timestamp.
        """
        start_cid = wal_head_cid or self.wal_head_cid
        if not start_cid:
            return []

        # Collect per-txn terminal phase + metadata (scan newest→oldest)
        by_txn: Dict[str, Dict[str, Any]] = {}
        first_ts: Dict[str, float] = {}

        for entry in self.read(start_cid):
            txn_id = entry.txn_id
            # Skip pure checkpoint markers
            if str(txn_id).startswith("checkpoint-"):
                continue
            phase = entry.resolved_phase()
            if txn_id not in by_txn:
                by_txn[txn_id] = {
                    "phase": phase,
                    "base_revision": entry.base_revision,
                    "new_revision": entry.new_revision,
                    "staged_root_cid": entry.staged_root_cid,
                }
                first_ts[txn_id] = entry.timestamp
            else:
                # Keep the terminal durable phase.
                # ABORT always wins (explicit cancel). Otherwise keep the
                # highest-rank phase on the commit path.
                cur = by_txn[txn_id]
                if phase == WALPhase.ABORT or cur["phase"] == WALPhase.ABORT:
                    cur["phase"] = WALPhase.ABORT
                elif phase_rank(phase) > phase_rank(cur["phase"]):
                    cur["phase"] = phase
                if entry.base_revision and not cur.get("base_revision"):
                    cur["base_revision"] = entry.base_revision
                if entry.new_revision and not cur.get("new_revision"):
                    cur["new_revision"] = entry.new_revision
                if entry.staged_root_cid and not cur.get("staged_root_cid"):
                    cur["staged_root_cid"] = entry.staged_root_cid
                # earliest timestamp for ordering
                if entry.timestamp < first_ts[txn_id]:
                    first_ts[txn_id] = entry.timestamp

        decisions: List[RecoveryDecision] = []
        for txn_id, meta in by_txn.items():
            phase: WALPhase = meta["phase"]
            action = recovery_action_for_phase(phase)
            reason = {
                RecoveryAction.DISCARD_STAGED: (
                    f"terminal phase {phase.value}: discard unstaged/unpublished write; "
                    "readers must only see old or fully committed heads"
                ),
                RecoveryAction.FINISH_PUBLICATION: (
                    f"terminal phase {phase.value}: head publication durable but "
                    "COMPLETE missing; finish complete marker idempotently"
                ),
                RecoveryAction.IDEMPOTENT_SKIP: (
                    f"terminal phase {phase.value}: already complete; "
                    "idempotent replay is a no-op"
                ),
                RecoveryAction.ABORT_CLEANUP: (
                    f"terminal phase {phase.value}: ensure staged objects remain "
                    "unreachable"
                ),
                RecoveryAction.NOOP: "no action required",
            }[action]
            decisions.append(
                RecoveryDecision(
                    txn_id=txn_id,
                    terminal_phase=phase,
                    action=action,
                    base_revision=meta.get("base_revision"),
                    new_revision=meta.get("new_revision"),
                    staged_root_cid=meta.get("staged_root_cid"),
                    reason=reason,
                )
            )

        # Chronological by first appearance
        decisions.sort(key=lambda d: first_ts.get(d.txn_id, 0.0))
        return decisions

    def apply_recovery(
        self,
        decisions: Optional[List[RecoveryDecision]] = None,
        *,
        complete_callback=None,
        discard_callback=None,
    ) -> List[RecoveryDecision]:
        """
        Execute planned recovery actions.

        For FINISH_PUBLICATION, appends an idempotent COMPLETE record.
        For DISCARD_STAGED / ABORT_CLEANUP, optionally invokes callbacks
        to drop staged objects (callbacks receive the RecoveryDecision).

        Args:
            decisions: Precomputed plan; if None, computed via plan_recovery()
            complete_callback: Optional callable(decision) after finish
            discard_callback: Optional callable(decision) for discard/abort

        Returns:
            The decisions that were applied
        """
        if decisions is None:
            decisions = self.plan_recovery()

        for decision in decisions:
            if decision.action == RecoveryAction.FINISH_PUBLICATION:
                # Idempotent COMPLETE marker so next recovery is a skip
                self.append_phase(
                    txn_id=decision.txn_id,
                    phase=WALPhase.COMPLETE,
                    operations=[],
                    base_revision=decision.base_revision,
                    new_revision=decision.new_revision,
                    staged_root_cid=decision.staged_root_cid,
                    record_seq=99,
                )
                if complete_callback is not None:
                    complete_callback(decision)
            elif decision.action in (
                RecoveryAction.DISCARD_STAGED,
                RecoveryAction.ABORT_CLEANUP,
            ):
                if discard_callback is not None:
                    discard_callback(decision)
            # IDEMPOTENT_SKIP / NOOP: nothing
        return decisions

    def get_transaction_history(self, txn_id: str) -> List[WALEntry]:
        """
        Get all WAL entries for a specific transaction.

        Args:
            txn_id: Transaction ID to search for

        Returns:
            List of WAL entries for the transaction
        """
        try:
            entries: List[WALEntry] = []

            for entry in self.read():
                if entry.txn_id == txn_id:
                    entries.append(entry)

            logger.debug(f"Found {len(entries)} WAL entries for txn: {txn_id}")

            return entries

        except DeserializationError as e:
            logger.warning(
                f"Deserialization error in transaction history (returning partial): {e}"
            )
            return entries  # Return what we have so far
        except _cancelled_exc_class():
            raise
        except Exception as e:
            logger.error(f"Failed to get transaction history: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """
        Get WAL statistics.

        Returns:
            Dictionary with WAL stats
        """
        return {
            "head_cid": self.wal_head_cid,
            "entry_count": self._entry_count,
            "compaction_threshold": self.compaction_threshold,
            "needs_compaction": self._entry_count >= self.compaction_threshold,
            "max_operations_per_entry": self.max_operations_per_entry,
            "max_entry_bytes": self.max_entry_bytes,
            "max_write_set_size": self.max_write_set_size,
            "max_read_set_size": self.max_read_set_size,
            "applied_keys": len(self._applied_keys),
            "recovery_matrix": {
                phase.value: action.value
                for phase, action in RECOVERY_ACTION_MATRIX.items()
            },
        }

    def verify_integrity(self) -> bool:
        """
        Verify WAL chain integrity.

        Checks that all entries are reachable and properly linked.
        Empty operations are allowed (phase markers / checkpoints).

        Returns:
            True if WAL is valid, False otherwise
        """
        try:
            if not self.wal_head_cid:
                logger.info("Empty WAL, verification passed")
                return True

            entry_count = 0
            prev_timestamp = float("inf")

            for entry in self.read():
                entry_count += 1

                # Check timestamp ordering (entries should be reverse chronological)
                if entry.timestamp > prev_timestamp:
                    logger.error(f"Timestamp out of order at entry {entry_count}")
                    return False
                prev_timestamp = entry.timestamp

                # Verify entry has required identity field.
                # Empty operations are valid for COMPLETE/checkpoint markers.
                if not entry.txn_id:
                    logger.error(f"Invalid entry structure at {entry_count}")
                    return False

            logger.info(f"WAL verification passed: {entry_count} entries")
            return True

        except DeserializationError as e:
            logger.error(f"WAL verification failed (deserialization): {e}")
            return False
        except _cancelled_exc_class():
            raise
        except Exception as e:
            logger.error(f"WAL verification failed: {e}")
            return False
