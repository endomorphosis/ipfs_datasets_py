"""Deterministic command-line interface for the incremental semantic index.

State arguments accepted by ``diff`` are either a state CID (with ``--store``)
or a UTF-8 JSON file containing a ``RepositoryState.to_dict()`` document.  All
successful command output is canonical, machine-readable JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

from ipfs_datasets_py.logic.software_contracts.semantic_index import (
    diff_repository_states,
    explain_impact,
    explain_symbol,
    scan_repository,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import RepositoryState
from ipfs_datasets_py.logic.software_contracts.semantic_index.persistence import (
    LocalSemanticIndexStore,
    RootConflictError,
    SemanticIndexPersistenceError,
)


class SemanticIndexCLIError(ValueError):
    """A stable, user-facing semantic-index CLI error."""


def _error(message: str) -> NoReturn:
    raise SemanticIndexCLIError(message)


def _repository(path: str) -> Path:
    candidate = Path(path).expanduser().resolve()
    if not candidate.is_dir():
        _error("repository must be an existing directory")
    return candidate


def _store_path(repository: Path | None, configured: str | None) -> Path:
    if configured:
        return Path(configured).expanduser().resolve()
    if repository is not None:
        return repository / ".semantic-index"
    _error("--store is required when resolving a state CID")


def _store(repository: Path | None, configured: str | None) -> LocalSemanticIndexStore:
    try:
        return LocalSemanticIndexStore(_store_path(repository, configured))
    except (OSError, ValueError) as exc:
        _error("cannot open local semantic-index store")


def _state_file(path: Path) -> RepositoryState:
    if not path.is_file():
        _error("state file must be a regular file")
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
        # Accept either a raw ``RepositoryState.to_dict()`` document or the
        # JSON emitted by ``semantic-index scan`` saved directly to a file.
        if isinstance(value, dict) and "state" in value:
            value = value["state"]
        if not isinstance(value, dict):
            _error("state file must contain a RepositoryState JSON object")
        return RepositoryState.from_dict(value)
    except SemanticIndexCLIError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        _error("state file is malformed or corrupt")


def _load_state(reference: str, store: LocalSemanticIndexStore | None) -> RepositoryState:
    candidate = Path(reference).expanduser()
    if candidate.exists():
        return _state_file(candidate)
    if store is None:
        _error("state CID requires --store")
    try:
        return store.load_state(reference)
    except (SemanticIndexPersistenceError, TypeError, ValueError):
        _error("state CID is unavailable or corrupt")


def _publish(store: LocalSemanticIndexStore, state: RepositoryState) -> str:
    try:
        state_cid = store.store_state(state)
        return store.compare_and_swap_root(state.repository_id, store.current_root(state.repository_id), state_cid)
    except RootConflictError:
        _error("semantic-index root conflict")
    except (SemanticIndexPersistenceError, OSError, ValueError, TypeError):
        _error("cannot persist semantic-index state")


def _json(value: Any) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def _scan(args: argparse.Namespace) -> int:
    repository = _repository(args.repo)
    try:
        state = scan_repository(repository)
    except (OSError, ValueError, TypeError):
        _error("repository scan failed")
    store = _store(repository, args.store)
    state_cid = _publish(store, state)
    _json({"command": "scan", "state": state.to_dict(), "state_cid": state_cid, "store": str(store.root)})
    return 0


def _diff(args: argparse.Namespace) -> int:
    store = _store(None, args.store) if args.store else None
    previous = _load_state(args.old_state, store)
    current = _load_state(args.new_state, store)
    try:
        delta = diff_repository_states(previous, current)
    except (TypeError, ValueError):
        _error("states cannot be compared")
    _json({"command": "diff", "delta": delta.to_dict()})
    return 0


def _current_state(repository: Path, configured_store: str | None) -> tuple[RepositoryState, LocalSemanticIndexStore]:
    store = _store(repository, configured_store)
    try:
        # Repository IDs are deterministic content identities, not filesystem
        # paths.  Scan once to derive that identity; a root may then avoid any
        # need to use this freshly scanned state below.
        scanned = scan_repository(repository)
        root = store.current_root(scanned.repository_id)
    except (SemanticIndexPersistenceError, OSError, ValueError):
        _error("semantic-index root is unavailable or corrupt")
    if root is not None:
        try:
            return store.load_state(root), store
        except SemanticIndexPersistenceError:
            _error("semantic-index root is unavailable or corrupt")
    _publish(store, scanned)
    return scanned, store


def _impact(args: argparse.Namespace) -> int:
    state, _ = _current_state(_repository(args.repo), args.store)
    try:
        result = explain_impact(state, args.symbol_or_file)
    except (LookupError, TypeError, ValueError):
        _error("symbol or file is unknown")
    _json({"command": "impact", "impact": result.to_dict()})
    return 0


def _explain(args: argparse.Namespace) -> int:
    state, _ = _current_state(_repository(args.repo), args.store)
    try:
        result = explain_symbol(state, args.symbol)
    except (LookupError, TypeError, ValueError):
        _error("symbol is unknown")
    _json({"command": "explain", "explanation": result.to_dict()})
    return 0


def _state_root(args: argparse.Namespace) -> int:
    repository = _repository(args.repo)
    store = _store(repository, args.store)
    try:
        repository_id = scan_repository(repository).repository_id
        state_cid = store.current_root(repository_id)
    except (SemanticIndexPersistenceError, OSError, ValueError):
        _error("semantic-index root is unavailable or corrupt")
    if state_cid is None:
        _error("semantic-index root does not exist")
    _json({"command": "state-root", "repository_id": repository_id, "state_cid": state_cid, "store": str(store.root)})
    return 0


def _watch(args: argparse.Namespace) -> int:
    repository = _repository(args.repo)
    if args.once:
        state, store = _current_state(repository, args.store)
        _json({"command": "watch", "event": "baseline", "state_cid": state.state_cid, "store": str(store.root)})
        return 0
    # Importing the watcher is deferred until this command is selected.
    from ipfs_datasets_py.logic.software_contracts.semantic_index import watch_repository

    store = _store(repository, args.store)

    def callback(notification: Any) -> None:
        state_cid = _publish(store, notification.state)
        _json({"command": "watch", "event": "changed", "previous_state_cid": notification.previous_state_cid, "state_cid": state_cid})

    try:
        watcher = watch_repository(repository, callback, debounce_ms=args.debounce_ms)
        _json({"command": "watch", "event": "baseline", "state_cid": watcher.current_state.state_cid, "store": str(store.root)})
        try:
            while True:
                watcher._stopped.wait(1.0)
        finally:
            watcher.stop()
    except KeyboardInterrupt:
        return 0
    except (OSError, TypeError, ValueError):
        _error("repository watch failed")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="semantic-index", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def repository_command(name: str, help_text: str) -> argparse.ArgumentParser:
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("repo", help="Repository directory")
        command.add_argument("--store", help="Local semantic-index store (default: <repo>/.semantic-index)")
        return command

    scan = repository_command("scan", "Scan, store, and publish a repository state")
    scan.set_defaults(handler=_scan)
    diff = subparsers.add_parser("diff", help="Diff two state CIDs or state JSON files")
    diff.add_argument("old_state", help="State CID (with --store) or RepositoryState JSON file")
    diff.add_argument("new_state", help="State CID (with --store) or RepositoryState JSON file")
    diff.add_argument("--store", help="Local semantic-index store used for CID references")
    diff.set_defaults(handler=_diff)
    impact = repository_command("impact", "Explain reverse impact for a symbol, artifact, or file")
    impact.add_argument("symbol_or_file")
    impact.set_defaults(handler=_impact)
    explain = repository_command("explain", "Explain a declared stable symbol")
    explain.add_argument("symbol")
    explain.set_defaults(handler=_explain)
    watch = repository_command("watch", "Watch a repository and emit changed state CIDs")
    watch.add_argument("--debounce-ms", type=int, default=250)
    watch.add_argument("--once", action="store_true", help="Emit the current baseline and exit")
    watch.set_defaults(handler=_watch)
    root = repository_command("state-root", "Print the currently published repository state CID")
    root.set_defaults(handler=_state_root)
    return parser


def main(args: list[str] | None = None) -> int:
    parser = create_parser()
    try:
        parsed = parser.parse_args(args)
        return int(parsed.handler(parsed))
    except SemanticIndexCLIError as exc:
        print(f"semantic-index: error: {exc}", file=sys.stderr)
        return 2
    except (SemanticIndexPersistenceError, OSError, TypeError, ValueError) as exc:
        # Keep library implementation details and tracebacks out of the CLI contract.
        print("semantic-index: error: operation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["create_parser", "main"]
