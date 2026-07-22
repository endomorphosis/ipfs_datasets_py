"""Touched-row copy-on-write transactions for modal autoencoder training state.

The state is a collection of sparse tables.  Copying every table for each
line-search attempt made projection cost proportional to the complete model
instead of the update.  This module journals a table row immediately before
its first mutation and can therefore restore or preserve a candidate in time
and memory proportional to its write set.
"""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional


MODAL_AUTOENCODER_STATE_TRANSACTION_SCHEMA_VERSION = (
    "modal-autoencoder-touched-row-transaction-v1"
)


class StateTransactionError(RuntimeError):
    """Base error for invalid state-transaction use."""


class StateTransactionConflictError(StateTransactionError):
    """Raised when nested or concurrent writers target one state object."""


class StateTransactionClosedError(StateTransactionError):
    """Raised when a completed transaction is used again."""


class StaleStatePatchError(StateTransactionConflictError):
    """Raised when a candidate patch no longer targets its source revision."""


@dataclass(frozen=True)
class TouchedRow:
    """One row as it existed before and after a candidate mutation."""

    component: str
    key: Any
    before_exists: bool
    before_value: Any
    after_exists: bool
    after_value: Any
    prior_revision: int


@dataclass(frozen=True)
class TouchedComponent:
    """A non-table component (scalar or bounded metadata list) change."""

    component: str
    before_value: Any
    after_value: Any
    prior_revision: int


@dataclass(frozen=True)
class ModalAutoencoderStatePatch:
    """A revision-bound copy-on-write candidate that contains touched data only."""

    base_revision: int
    result_revision: int
    rows: tuple[TouchedRow, ...]
    components: tuple[TouchedComponent, ...]
    schema_version: str = MODAL_AUTOENCODER_STATE_TRANSACTION_SCHEMA_VERSION

    @property
    def touched_row_count(self) -> int:
        return len(self.rows)

    @property
    def inserted_key_count(self) -> int:
        return sum(1 for row in self.rows if not row.before_exists and row.after_exists)

    @property
    def deleted_key_count(self) -> int:
        return sum(1 for row in self.rows if row.before_exists and not row.after_exists)

    @property
    def touched_component_count(self) -> int:
        return len(self.components)

    @property
    def prior_revision(self) -> int:
        return self.base_revision

    def apply(self, transaction: "ModalAutoencoderStateTransaction") -> None:
        """Apply this candidate through an active transaction.

        Revision binding prevents a line-search result produced from one epoch
        from being committed after another writer has advanced the state.
        """

        transaction.apply_patch(self)

    def to_dict(self) -> Dict[str, Any]:
        """Return bounded diagnostics without serializing parameter values."""

        return {
            "base_revision": self.base_revision,
            "deleted_key_count": self.deleted_key_count,
            "inserted_key_count": self.inserted_key_count,
            "result_revision": self.result_revision,
            "schema_version": self.schema_version,
            "touched_component_count": self.touched_component_count,
            "touched_components": sorted(
                {row.component for row in self.rows}
                | {component.component for component in self.components}
            ),
            "touched_row_count": self.touched_row_count,
        }


class ModalAutoencoderStateTransaction:
    """Journal mutations to one training state using row-level copy-on-write.

    A state allows exactly one active writer.  The owning thread may read and
    mutate it; another thread and nested transactions fail before mutation.
    Clean context-manager exit commits, while exceptional exit rolls back.
    Call :meth:`rollback` explicitly for speculative candidates.
    """

    def __init__(self, state: Any, *, label: str = "") -> None:
        self.state = state
        self.label = str(label or "")
        self.owner_thread_id = threading.get_ident()
        self.base_revision = int(state.state_revision)
        self._tracker_checkpoint: Optional[Mapping[str, Any]] = None
        self._rows: Dict[tuple[str, Any], tuple[bool, Any]] = {}
        self._components: Dict[str, Any] = {}
        self._active = False
        self._restoring = False
        self._committed = False
        self._rolled_back = False
        self._patch: Optional[ModalAutoencoderStatePatch] = None

    @property
    def active(self) -> bool:
        return self._active

    @property
    def committed(self) -> bool:
        return self._committed

    @property
    def rolled_back(self) -> bool:
        return self._rolled_back

    @property
    def touched_row_count(self) -> int:
        return len(self._rows)

    @property
    def touched_component_count(self) -> int:
        return len(self._components)

    @property
    def inserted_key_count(self) -> int:
        return sum(1 for existed, _value in self._rows.values() if not existed)

    @property
    def touched_components(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {component for component, _key in self._rows}
                | set(self._components)
            )
        )

    @property
    def patch(self) -> Optional[ModalAutoencoderStatePatch]:
        """Return the patch captured by commit or rollback, when completed."""

        return self._patch

    def __enter__(self) -> "ModalAutoencoderStateTransaction":
        return self.begin()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if not self._active:
            return False
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    def begin(self) -> "ModalAutoencoderStateTransaction":
        if self._active or self._committed or self._rolled_back:
            raise StateTransactionClosedError("transaction has already been used")
        if threading.get_ident() != self.owner_thread_id:
            raise StateTransactionConflictError(
                "transaction must begin on the thread that created it"
            )
        self.state._begin_state_transaction(self)
        try:
            self.base_revision = int(self.state.state_revision)
            self._tracker_checkpoint = (
                self.state._state_identity_tracker.transaction_checkpoint()
            )
            self._active = True
        except BaseException:
            self.state._end_state_transaction(self)
            raise
        return self

    def _require_owner(self) -> None:
        if not self._active:
            raise StateTransactionClosedError("state transaction is not active")
        if threading.get_ident() != self.owner_thread_id:
            raise StateTransactionConflictError(
                "state transaction writer thread does not own the transaction"
            )
        if getattr(self.state, "_active_state_transaction", None) is not self:
            raise StateTransactionConflictError(
                "state transaction lost exclusive writer ownership"
            )

    def before_mutation(
        self,
        component: str,
        path: tuple[Any, ...],
        operation: str,
    ) -> None:
        """Snapshot the enclosing sparse-table row before its first mutation."""

        del operation
        self._require_owner()
        if self._restoring:
            return
        value = getattr(self.state, component)
        if isinstance(value, Mapping):
            if not path:
                self.before_component_replacement(component)
                return
            key = path[0]
            marker = (component, key)
            if marker in self._rows:
                return
            existed = key in value
            self._rows[marker] = (
                existed,
                copy.deepcopy(value[key]) if existed else None,
            )
            return
        self.before_component_replacement(component)

    def before_component_replacement(self, component: str) -> None:
        """Snapshot bounded scalar/list metadata before replacement or mutation."""

        self._require_owner()
        if self._restoring or component in self._components:
            return
        value = getattr(self.state, component)
        if isinstance(value, Mapping):
            # Replacing a table is supported for completeness, but callers on
            # hot paths should mutate individual rows to retain COW scaling.
            self._components[component] = copy.deepcopy(value)
        else:
            self._components[component] = copy.deepcopy(value)

    def capture_patch(self) -> ModalAutoencoderStatePatch:
        """Copy only current values in the transaction write set."""

        self._require_owner()
        rows = []
        for (component, key), (before_exists, before_value) in sorted(
            self._rows.items(),
            key=lambda item: (item[0][0], repr(item[0][1])),
        ):
            mapping = getattr(self.state, component)
            after_exists = key in mapping
            rows.append(
                TouchedRow(
                    component=component,
                    key=copy.deepcopy(key),
                    before_exists=before_exists,
                    before_value=copy.deepcopy(before_value),
                    after_exists=after_exists,
                    after_value=(
                        copy.deepcopy(mapping[key]) if after_exists else None
                    ),
                    prior_revision=self.base_revision,
                )
            )
        components = tuple(
            TouchedComponent(
                component=component,
                before_value=copy.deepcopy(before_value),
                after_value=copy.deepcopy(getattr(self.state, component)),
                prior_revision=self.base_revision,
            )
            for component, before_value in sorted(self._components.items())
        )
        return ModalAutoencoderStatePatch(
            base_revision=self.base_revision,
            result_revision=int(self.state.state_revision),
            rows=tuple(rows),
            components=components,
        )

    def iter_row_deltas(self) -> Iterable[TouchedRow]:
        """Yield current row deltas for sparse update-norm accounting."""

        return self.capture_patch().rows

    def apply_patch(self, patch: ModalAutoencoderStatePatch) -> None:
        self._require_owner()
        if self.touched_row_count or self.touched_component_count:
            raise StateTransactionConflictError(
                "candidate patch must be applied before other transaction writes"
            )
        if int(self.state.state_revision) != int(patch.base_revision):
            raise StaleStatePatchError(
                "candidate patch revision conflict: "
                f"state={self.state.state_revision}, patch={patch.base_revision}"
            )
        for component in patch.components:
            setattr(
                self.state,
                component.component,
                copy.deepcopy(component.after_value),
            )
        for row in patch.rows:
            mapping = getattr(self.state, row.component)
            if row.after_exists:
                mapping[copy.deepcopy(row.key)] = copy.deepcopy(row.after_value)
            else:
                mapping.pop(row.key, None)
        # A candidate can perform several nested scalar writes within one row.
        # Row replay deliberately collapses those writes, so restore the exact
        # candidate revision after its values have been applied.
        self.state._state_identity_tracker.restore_revision(
            patch.result_revision
        )

    def commit(self) -> ModalAutoencoderStatePatch:
        """Keep current values and release the exclusive writer."""

        self._require_owner()
        patch = self.capture_patch()
        self._patch = patch
        self._active = False
        self._committed = True
        self.state._end_state_transaction(self)
        return patch

    def rollback(self) -> ModalAutoencoderStatePatch:
        """Restore every touched row and all prior identity bookkeeping exactly."""

        self._require_owner()
        patch = self.capture_patch()
        checkpoint = self._tracker_checkpoint
        if checkpoint is None:
            raise StateTransactionError("transaction identity checkpoint is missing")
        self._restoring = True
        try:
            for component, before_value in self._components.items():
                setattr(self.state, component, copy.deepcopy(before_value))
            for (component, key), (before_exists, before_value) in reversed(
                tuple(self._rows.items())
            ):
                # A full-component snapshot already restored this row.
                if component in self._components:
                    continue
                mapping = getattr(self.state, component)
                if before_exists:
                    mapping[key] = copy.deepcopy(before_value)
                else:
                    mapping.pop(key, None)
            self.state._state_identity_tracker.restore_transaction_checkpoint(
                checkpoint
            )
        finally:
            self._restoring = False
            self._patch = patch
            self._active = False
            self._rolled_back = True
            self.state._end_state_transaction(self)
        return patch

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "active": self.active,
            "base_revision": self.base_revision,
            "committed": self.committed,
            "inserted_key_count": self.inserted_key_count,
            "label": self.label,
            "rolled_back": self.rolled_back,
            "schema_version": MODAL_AUTOENCODER_STATE_TRANSACTION_SCHEMA_VERSION,
            "touched_component_count": self.touched_component_count,
            "touched_components": list(self.touched_components),
            "touched_row_count": self.touched_row_count,
        }


# Concise aliases make the public API convenient while retaining a specific
# class name for diagnostics and imports in older integration code.
StateTransaction = ModalAutoencoderStateTransaction
StatePatch = ModalAutoencoderStatePatch


__all__ = [
    "MODAL_AUTOENCODER_STATE_TRANSACTION_SCHEMA_VERSION",
    "ModalAutoencoderStatePatch",
    "ModalAutoencoderStateTransaction",
    "StaleStatePatchError",
    "StatePatch",
    "StateTransaction",
    "StateTransactionClosedError",
    "StateTransactionConflictError",
    "StateTransactionError",
    "TouchedComponent",
    "TouchedRow",
]
