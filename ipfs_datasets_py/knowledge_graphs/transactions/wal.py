"""
Write-Ahead Log (WAL) Implementation

Provides persistent transaction logging on IPLD for crash recovery
and ACID guarantees.
"""

import json
import logging
from typing import Iterator, List, Optional, Dict, Any
from datetime import datetime

from .types import (
    WALEntry, Operation, TransactionState,
    IsolationLevel, OperationType
)

# Import custom exceptions
from ..exceptions import (
    TransactionError,
    StorageError,
    SerializationError,
    DeserializationError
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
    - Compaction for old entries
    - Recovery from any WAL head
    - IPLD-native storage
    
    Attributes:
        storage: IPLDBackend for storing WAL entries
        wal_head_cid: CID of most recent WAL entry
        compaction_threshold: Number of entries before compaction
    """
    
    def __init__(self, storage, wal_head_cid: Optional[str] = None):
        """
        Initialize Write-Ahead Log.
        
        Args:
            storage: IPLDBackend instance for persistence
            wal_head_cid: CID of current WAL head (None for empty log)
        """
        self.storage = storage
        self.wal_head_cid = wal_head_cid
        self.compaction_threshold = 1000  # Entries before compaction
        self._entry_count = 0
        
        logger.info(f"WriteAheadLog initialized with head: {wal_head_cid}")
    
    def append(self, entry: WALEntry) -> str:
        """
        Append WAL entry to log and return its CID.
        
        Creates an immutable entry on IPLD linked to previous entry.
        
        Args:
            entry: WALEntry to append
            
        Returns:
            CID of the appended entry (new WAL head)
            
        Example:
            >>> entry = WALEntry(
            ...     txn_id="txn-123",
            ...     timestamp=time.time(),
            ...     operations=[op1, op2],
            ...     prev_wal_cid=current_head
            ... )
            >>> cid = wal.append(entry)
            >>> print(f"WAL entry stored at: {cid}")
        """
        try:
            # Set previous WAL CID to current head
            entry.prev_wal_cid = self.wal_head_cid
            
            # Convert to dictionary for IPLD storage
            entry_dict = entry.to_dict()
            
            # Store on IPLD
            cid = self.storage.store_json(entry_dict)
            
            # Update WAL head
            self.wal_head_cid = cid
            self._entry_count += 1
            
            logger.debug(f"WAL entry appended: {cid} (txn: {entry.txn_id})")
            
            # Check if compaction needed
            if self._entry_count >= self.compaction_threshold:
                logger.info(f"Compaction threshold reached: {self._entry_count} entries")
            
            return cid
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to serialize WAL entry: {e}")
            raise SerializationError(
                f"Failed to serialize WAL entry: {e}",
                details={'txn_id': str(entry.txn_id), 'operation': entry.operation.operation_type.value}
            ) from e
        except Exception as e:
            logger.error(f"Failed to append WAL entry: {e}")
            raise TransactionError(
                f"Failed to append WAL entry: {e}",
                details={'txn_id': str(entry.txn_id)}
            ) from e
    
    def read(self, from_cid: Optional[str] = None) -> Iterator[WALEntry]:
        """
        Read WAL entries from specified CID backwards through the chain.
        
        Follows prev_wal_cid links to traverse the log.
        
        Args:
            from_cid: CID to start reading from (defaults to current head)
            
        Yields:
            WALEntry instances in reverse chronological order
            
        Example:
            >>> for entry in wal.read():
            ...     print(f"Transaction: {entry.txn_id}")
            ...     for op in entry.operations:
            ...         print(f"  Operation: {op.type}")
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
                
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"Failed to read WAL entry {current_cid} (continuing): {e}")
                break
            except Exception as e:
                logger.error(f"Failed to read WAL entry {current_cid}: {e}")
                raise DeserializationError(
                    f"Failed to deserialize WAL entry: {e}",
                    details={'cid': str(current_cid)}
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
            
        Note:
            Actual pruning requires IPFS garbage collection.
            This method creates the checkpoint reference.
            
        Example:
            >>> # Compact entries older than checkpoint
            >>> new_head = wal.compact(checkpoint_cid)
            >>> print(f"Compacted WAL, new head: {new_head}")
        """
        try:
            logger.info(f"Compacting WAL up to: {checkpoint_cid}")
            
            # Create checkpoint entry
            checkpoint_entry = WALEntry(
                txn_id=f"checkpoint-{datetime.now().timestamp()}",
                timestamp=datetime.now().timestamp(),
                operations=[],  # No operations in checkpoint
                prev_wal_cid=checkpoint_cid,
                txn_state=TransactionState.COMMITTED
            )
            
            # Store checkpoint
            checkpoint_entry_cid = self.append(checkpoint_entry)
            
            # Reset entry count after compaction
            self._entry_count = 0
            
            logger.info(f"WAL compacted, checkpoint: {checkpoint_entry_cid}")
            
            return checkpoint_entry_cid
            
        except SerializationError:
            # Re-raise serialization errors
            raise
        except Exception as e:
            logger.error(f"Failed to compact WAL: {e}")
            raise TransactionError(
                f"Failed to compact WAL: {e}",
                details={'entry_count': self._entry_count, 'threshold': self.compaction_threshold}
            ) from e
    
    def recover(self, wal_head_cid: Optional[str] = None) -> List[Operation]:
        """
        Recover operations from WAL for crash recovery.
        
        Replays all operations from committed transactions to restore
        graph state after a crash.
        
        Args:
            wal_head_cid: CID to recover from (defaults to current head)
            
        Returns:
            List of operations to replay in order
            
        Example:
            >>> operations = wal.recover()
            >>> print(f"Recovering {len(operations)} operations")
            >>> for op in operations:
            ...     # Apply operation to graph
            ...     apply_operation(op)
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
            
            for entry in self.read(start_cid):
                entries_processed += 1
                
                # Only recover committed transactions
                if entry.txn_state == TransactionState.COMMITTED:
                    # Add operations in order
                    operations_to_replay.extend(entry.operations)
                    logger.debug(f"Recovered {len(entry.operations)} ops from txn: {entry.txn_id}")
                else:
                    logger.debug(f"Skipping non-committed txn: {entry.txn_id} (state: {entry.txn_state})")
            
            # Reverse to get chronological order (read returns reverse)
            operations_to_replay.reverse()
            
            logger.info(f"Recovery complete: {len(operations_to_replay)} operations from {entries_processed} entries")
            
            return operations_to_replay
            
        except DeserializationError:
            # Re-raise deserialization errors
            raise
        except Exception as e:
            logger.error(f"Failed to recover from WAL: {e}")
            raise TransactionError(
                f"Failed to recover from WAL: {e}",
                details={'wal_head': str(self.wal_head_cid) if self.wal_head_cid else None}
            ) from e
    
    def get_transaction_history(self, txn_id: str) -> List[WALEntry]:
        """
        Get all WAL entries for a specific transaction.
        
        Args:
            txn_id: Transaction ID to search for
            
        Returns:
            List of WAL entries for the transaction
            
        Example:
            >>> entries = wal.get_transaction_history("txn-123")
            >>> for entry in entries:
            ...     print(f"State: {entry.txn_state}, Ops: {len(entry.operations)}")
        """
        try:
            entries = []
            
            for entry in self.read():
                if entry.txn_id == txn_id:
                    entries.append(entry)
            
            logger.debug(f"Found {len(entries)} WAL entries for txn: {txn_id}")
            
            return entries
            
        except DeserializationError as e:
            logger.warning(f"Deserialization error in transaction history (returning partial): {e}")
            return entries  # Return what we have so far
        except Exception as e:
            logger.error(f"Failed to get transaction history: {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get WAL statistics.
        
        Returns:
            Dictionary with WAL stats
            
        Example:
            >>> stats = wal.get_stats()
            >>> print(f"WAL head: {stats['head_cid']}")
            >>> print(f"Entries: {stats['entry_count']}")
        """
        return {
            "head_cid": self.wal_head_cid,
            "entry_count": self._entry_count,
            "compaction_threshold": self.compaction_threshold,
            "needs_compaction": self._entry_count >= self.compaction_threshold
        }
    
    def verify_integrity(self) -> bool:
        """
        Verify WAL chain integrity.
        
        Checks that all entries are reachable and properly linked.
        
        Returns:
            True if WAL is valid, False otherwise
            
        Example:
            >>> if wal.verify_integrity():
            ...     print("WAL is valid")
            ... else:
            ...     print("WAL corruption detected!")
        """
        try:
            if not self.wal_head_cid:
                logger.info("Empty WAL, verification passed")
                return True
            
            entry_count = 0
            prev_timestamp = float('inf')
            
            for entry in self.read():
                entry_count += 1
                
                # Check timestamp ordering (entries should be reverse chronological)
                if entry.timestamp > prev_timestamp:
                    logger.error(f"Timestamp out of order at entry {entry_count}")
                    return False
                prev_timestamp = entry.timestamp
                
                # Verify entry has required fields
                if not entry.txn_id or not entry.operations:
                    logger.error(f"Invalid entry structure at {entry_count}")
                    return False
            
            logger.info(f"WAL verification passed: {entry_count} entries")
            return True
            
        except DeserializationError as e:
            logger.error(f"WAL verification failed (deserialization): {e}")
            return False
        except Exception as e:
            logger.error(f"WAL verification failed: {e}")
            return False
