"""Public, side-effect-free facade for the incremental semantic index.

The module-level functions are the interoperable API and directly delegate to
the deterministic component implementations.  :class:`IncrementalSemanticIndex`
is intentionally only a convenience owner for a scanner, a last scanned state,
and an *explicitly injected* persistence store.  Constructing or importing it
does not create storage, start a watch, or contact an external service.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import TYPE_CHECKING, Callable

from ipfs_datasets_py.logic.software_contracts.semantic_index.delta import (
    diff_repository_states as _diff_repository_states,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.explain import (
    explain_impact as _explain_impact,
    explain_symbol as _explain_symbol,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.invalidation import (
    calculate_invalidation as _calculate_invalidation,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    ImpactExplanation,
    InvalidationPlan,
    RepositoryState,
    RepositoryStateDelta,
    SymbolExplanation,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.scanner import (
    RepositoryScanner,
)

if TYPE_CHECKING:
    from ipfs_datasets_py.logic.software_contracts.semantic_index.persistence import (
        SemanticIndexStore,
    )
    from ipfs_datasets_py.logic.software_contracts.semantic_index.watch import (
        RepositoryWatch,
        WatchNotification,
    )


def scan_repository(
    repo_path: str | os.PathLike[str],
    previous_state: RepositoryState | None = None,
) -> RepositoryState:
    """Scan ``repo_path`` into a deterministic repository state.

    ``previous_state`` is only a verified reuse optimization; it cannot alter
    the state produced for the current repository bytes.
    """
    return RepositoryScanner().scan(repo_path, previous_state=previous_state)


def diff_repository_states(
    previous_state: RepositoryState,
    current_state: RepositoryState,
) -> RepositoryStateDelta:
    """Return the deterministic semantic delta between two repository states."""
    return _diff_repository_states(previous_state, current_state)


def calculate_invalidation(
    previous_state: RepositoryState,
    current_state: RepositoryState,
    delta: RepositoryStateDelta,
) -> InvalidationPlan:
    """Calculate bounded invalidation obligations for an exact state delta."""
    return _calculate_invalidation(previous_state, current_state, delta)


def explain_symbol(
    repository_state: RepositoryState,
    symbol_id: str,
) -> SymbolExplanation:
    """Explain one declared stable symbol identity."""
    return _explain_symbol(repository_state, symbol_id)


def explain_impact(
    repository_state: RepositoryState,
    changed_symbol_ids: Iterable[str],
) -> ImpactExplanation:
    """Explain bounded reverse dependency impact for symbols, artifacts, or paths."""
    return _explain_impact(repository_state, changed_symbol_ids)


def watch_repository(
    repo_path: str | os.PathLike[str],
    callback: Callable[["WatchNotification"], object],
    *,
    debounce_ms: int = 250,
) -> "RepositoryWatch":
    """Start a watcher only when explicitly requested.

    The watcher implementation is imported here, rather than at package
    import time, because creating a watch is the sole API operation that may
    create a worker thread.
    """
    from ipfs_datasets_py.logic.software_contracts.semantic_index.watch import (
        watch_repository as _watch_repository,
    )

    return _watch_repository(repo_path, callback, debounce_ms=debounce_ms)


class IncrementalSemanticIndex:
    """Small stateful convenience facade over the public functional API.

    ``scanner`` and ``store`` are injected capabilities.  In particular, no
    local store is inferred from a repository path: persistence occurs only
    through :meth:`store_state` or :meth:`publish_state` when a caller supplied
    a compatible store.
    """

    def __init__(
        self,
        *,
        scanner: RepositoryScanner | None = None,
        store: "SemanticIndexStore | None" = None,
    ) -> None:
        if scanner is not None and not isinstance(scanner, RepositoryScanner):
            raise TypeError("scanner must be a RepositoryScanner or None")
        self.scanner = scanner or RepositoryScanner()
        self.store = store
        self.current_state: RepositoryState | None = None

    def scan_repository(
        self,
        repo_path: str | os.PathLike[str],
        previous_state: RepositoryState | None = None,
    ) -> RepositoryState:
        """Scan and retain the resulting state without persisting it."""
        state = self.scanner.scan(repo_path, previous_state=previous_state)
        self.current_state = state
        return state

    scan = scan_repository

    def diff_repository_states(
        self, previous_state: RepositoryState, current_state: RepositoryState
    ) -> RepositoryStateDelta:
        """Delegate to :func:`diff_repository_states`."""
        return diff_repository_states(previous_state, current_state)

    def calculate_invalidation(
        self,
        previous_state: RepositoryState,
        current_state: RepositoryState,
        delta: RepositoryStateDelta,
    ) -> InvalidationPlan:
        """Delegate to :func:`calculate_invalidation`."""
        return calculate_invalidation(previous_state, current_state, delta)

    def explain_symbol(self, repository_state: RepositoryState, symbol_id: str) -> SymbolExplanation:
        """Delegate to :func:`explain_symbol`."""
        return explain_symbol(repository_state, symbol_id)

    def explain_impact(self, repository_state: RepositoryState, changed_symbol_ids: Iterable[str]) -> ImpactExplanation:
        """Delegate to :func:`explain_impact`."""
        return explain_impact(repository_state, changed_symbol_ids)

    def watch_repository(
        self,
        repo_path: str | os.PathLike[str],
        callback: Callable[["WatchNotification"], object],
        *,
        debounce_ms: int = 250,
    ) -> "RepositoryWatch":
        """Start an explicit watch using this facade's scanner capability."""
        from ipfs_datasets_py.logic.software_contracts.semantic_index.watch import RepositoryWatch

        return RepositoryWatch(repo_path, callback, debounce_ms=debounce_ms, scanner=self.scanner).start()

    def _store(self) -> "SemanticIndexStore":
        if self.store is None:
            raise RuntimeError("persistence requires an explicitly injected SemanticIndexStore")
        return self.store

    def store_state(self, state: RepositoryState) -> str:
        """Store an immutable state through the injected store, without publishing it."""
        return self._store().store_state(state)

    def load_state(self, state_cid: str) -> RepositoryState:
        """Load and verify a state through the injected store."""
        return self._store().load_state(state_cid)

    def current_root(self, repository_id: str) -> str | None:
        """Return the injected store's current verified root, if any."""
        return self._store().current_root(repository_id)

    def publish_state(
        self,
        state: RepositoryState,
        *,
        expected_old_cid: str | None = None,
    ) -> str:
        """Store ``state`` then atomically publish its root with explicit CAS."""
        store = self._store()
        state_cid = store.store_state(state)
        return store.compare_and_swap_root(state.repository_id, expected_old_cid, state_cid)


__all__ = [
    "IncrementalSemanticIndex",
    "scan_repository",
    "diff_repository_states",
    "calculate_invalidation",
    "explain_symbol",
    "explain_impact",
    "watch_repository",
]
