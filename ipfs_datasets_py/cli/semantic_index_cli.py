"""Command line interface for the incremental semantic index.

State arguments accepted by ``diff`` are either a CID stored in ``--store`` or
a JSON file produced by ``semantic-index scan``.  A file containing only a CID
is also accepted, which is convenient for shell workflows.  The CLI emits
canonical, sorted JSON and intentionally has no IPFS daemon dependency.

The default local store is ``<repository>/.semantic-index``.  That path is a
canonical scanner exclusion, so publishing roots and lock files there cannot
enter the indexed snapshot or alter a second scan of the same repository
bytes.  ``impact``, ``explain``, and ``watch --once`` always scan current
repository bytes; they never silently return a previously stored root.
``watch --once`` additionally CAS-publishes the accepted state so
``state-root`` can observe it.  A missing published root is a nonzero exit.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any, Sequence


class SemanticIndexCLIError(RuntimeError):
    """An expected user-facing CLI failure."""


def _emit(value: Any) -> None:
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def _store_path(repository: str | Path, configured: str | None) -> Path:
    """Return the explicit store or the private, repository-local default."""
    if configured:
        return Path(configured).expanduser()
    return Path(repository).expanduser() / ".semantic-index"


def _checked_repository(repository: str) -> Path:
    path = Path(repository).expanduser()
    if not path.is_dir():
        raise SemanticIndexCLIError("repository must be an existing directory")
    return path


def _store(path: str | Path):
    from ipfs_datasets_py.logic.software_contracts.semantic_index.persistence import (
        LocalSemanticIndexStore,
    )

    return LocalSemanticIndexStore(path)


def _state_from_file(path: Path):
    from ipfs_datasets_py.logic.software_contracts.semantic_index.models import RepositoryState

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SemanticIndexCLIError(f"cannot read state file: {path}") from exc
    try:
        value = json.loads(text)
    except (TypeError, ValueError) as exc:
        # A one-line CID file is deliberately accepted as documented above.
        candidate = text.strip()
        if candidate and "\n" not in candidate and "\r" not in candidate:
            return candidate
        raise SemanticIndexCLIError(f"state file is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SemanticIndexCLIError(f"state file must contain a JSON object: {path}")
    try:
        return RepositoryState.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise SemanticIndexCLIError(f"state file is invalid or corrupt: {path}") from exc


def _load_state_reference(reference: str, store_path: str | None):
    """Resolve a verified state JSON file, CID file, or a stored state CID."""
    candidate = Path(reference).expanduser()
    if candidate.is_file():
        loaded = _state_from_file(candidate)
        if not isinstance(loaded, str):
            return loaded
        reference = loaded
    elif candidate.exists():
        raise SemanticIndexCLIError(f"state reference is not a file: {candidate}")

    if not store_path:
        raise SemanticIndexCLIError("a state CID requires --store; JSON state files need no store")
    try:
        return _store(store_path).load_state(reference)
    except Exception as exc:
        raise SemanticIndexCLIError("state CID is unavailable or corrupt") from exc


def _load_previous_state(repository_path: Path, store_path: str | None):
    """Load the published root as a verified previous state, if any.

    A missing root is not an error (callers scan cold).  A corrupt root or
    store failure is a stable nonzero CLI error.
    """
    from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import repository_identity

    store = _store(_store_path(repository_path, store_path))
    try:
        root = store.current_root(repository_identity(repository_path))
        if root is None:
            return None, store
        return store.load_state(root), store
    except SemanticIndexCLIError:
        raise
    except Exception as exc:
        raise SemanticIndexCLIError("repository state is unavailable or corrupt") from exc


def _scan_current(repository: str, store_path: str | None):
    """Scan the repository's current bytes.

    A published local root is only a verified reuse optimization for the
    scanner; it is never returned in place of a fresh scan.
    """
    from ipfs_datasets_py.logic.software_contracts.semantic_index import scan_repository

    repository_path = _checked_repository(repository)
    previous, _store_obj = _load_previous_state(repository_path, store_path)
    try:
        return scan_repository(repository_path, previous_state=previous)
    except Exception as exc:
        raise SemanticIndexCLIError("scan failed") from exc


def _publish_state(state, store_path: str | None, repository_path: Path):
    """Store ``state`` and CAS-publish it as the current root for its repository."""
    from ipfs_datasets_py.logic.software_contracts.semantic_index.persistence import (
        RootConflictError,
    )

    store = _store(_store_path(repository_path, store_path))
    try:
        old = store.current_root(state.repository_id)
        cid = store.store_state(state)
        return store.compare_and_swap_root(state.repository_id, old, cid)
    except RootConflictError as exc:
        raise SemanticIndexCLIError("root conflict") from exc
    except SemanticIndexCLIError:
        raise
    except Exception as exc:
        raise SemanticIndexCLIError("state publication failed") from exc


def _scan(args: argparse.Namespace) -> int:
    from ipfs_datasets_py.logic.software_contracts.semantic_index import scan_repository
    from ipfs_datasets_py.logic.software_contracts.semantic_index.persistence import (
        RootConflictError,
    )
    from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import repository_identity

    repository = _checked_repository(args.repository)
    store = _store(_store_path(repository, args.store))
    try:
        repository_id = repository_identity(repository)
        old = store.current_root(repository_id)
        previous = store.load_state(old) if old else None
        state = scan_repository(repository, previous_state=previous)
        cid = store.store_state(state)
        store.compare_and_swap_root(state.repository_id, old, cid)
    except RootConflictError as exc:
        raise SemanticIndexCLIError("root conflict") from exc
    except SemanticIndexCLIError:
        raise
    except Exception as exc:
        raise SemanticIndexCLIError("scan failed") from exc
    _emit(state.to_dict())
    return 0


def _diff(args: argparse.Namespace) -> int:
    from ipfs_datasets_py.logic.software_contracts.semantic_index import diff_repository_states

    old = _load_state_reference(args.old_state, args.store)
    new = _load_state_reference(args.new_state, args.store)
    try:
        delta = diff_repository_states(old, new)
    except Exception as exc:
        raise SemanticIndexCLIError("state diff failed") from exc
    _emit(delta.to_dict())
    return 0


def _impact(args: argparse.Namespace) -> int:
    from ipfs_datasets_py.logic.software_contracts.semantic_index import explain_impact

    state = _scan_current(args.repository, args.store)
    try:
        result = explain_impact(state, args.symbol_or_file)
    except Exception as exc:
        raise SemanticIndexCLIError("symbol or file is not present in repository state") from exc
    _emit(result.to_dict())
    return 0


def _explain(args: argparse.Namespace) -> int:
    from ipfs_datasets_py.logic.software_contracts.semantic_index import explain_symbol

    state = _scan_current(args.repository, args.store)
    try:
        result = explain_symbol(state, args.symbol)
    except Exception as exc:
        raise SemanticIndexCLIError("symbol is not present in repository state") from exc
    _emit(result.to_dict())
    return 0


def _state_root(args: argparse.Namespace) -> int:
    from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import repository_identity

    try:
        repository = _checked_repository(args.repository)
        repository_id = repository_identity(repository)
        cid = _store(_store_path(repository, args.store)).current_root(repository_id)
    except SemanticIndexCLIError:
        raise
    except Exception as exc:
        raise SemanticIndexCLIError("state root is unavailable or corrupt") from exc
    if cid is None:
        raise SemanticIndexCLIError("no published state root")
    _emit({"repository_id": repository_id, "state_cid": cid})
    return 0


def _watch(args: argparse.Namespace) -> int:
    # ``--once`` scans current truth, CAS-publishes the accepted state, emits
    # JSON, and exits.  It does not start a thread or import the watcher backend.
    if args.once:
        repository = _checked_repository(args.repository)
        state = _scan_current(args.repository, args.store)
        _publish_state(state, args.store, repository)
        _emit(state.to_dict())
        return 0

    from ipfs_datasets_py.logic.software_contracts.semantic_index import watch_repository

    def callback(notification: Any) -> None:
        _emit({"previous_state_cid": notification.previous_state_cid, "state_cid": notification.state_cid})

    try:
        watch = watch_repository(args.repository, callback, debounce_ms=args.debounce_ms)
        while True:
            # Thread ownership remains in the semantic-index watcher; this
            # loop only keeps the command alive until the user interrupts it.
            time.sleep(1.0)
    except KeyboardInterrupt:
        if "watch" in locals():
            watch.stop()
        return 0
    except Exception as exc:
        raise SemanticIndexCLIError("watch failed") from exc


def _add_store_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--store",
        help="Local semantic-index store (defaults to <repo>/.semantic-index, a scanner exclusion)",
    )


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="semantic-index", description="Deterministic incremental semantic-index operations")
    subcommands = parser.add_subparsers(dest="command", required=True)

    scan = subcommands.add_parser("scan", help="Scan a repository and publish its local state root")
    scan.add_argument("repository")
    _add_store_option(scan)
    scan.set_defaults(handler=_scan)

    diff = subcommands.add_parser("diff", help="Diff two state JSON files or stored CIDs")
    diff.add_argument("old_state")
    diff.add_argument("new_state")
    _add_store_option(diff)
    diff.set_defaults(handler=_diff)

    impact = subcommands.add_parser("impact", help="Explain reverse impact for a stable symbol ID, artifact ID, or repository-relative file")
    impact.add_argument("repository")
    impact.add_argument("symbol_or_file")
    _add_store_option(impact)
    impact.set_defaults(handler=_impact)

    explain = subcommands.add_parser("explain", help="Explain one stable symbol ID")
    explain.add_argument("repository")
    explain.add_argument("symbol")
    _add_store_option(explain)
    explain.set_defaults(handler=_explain)

    watch = subcommands.add_parser("watch", help="Watch a repository and emit state-root changes")
    watch.add_argument("repository")
    watch.add_argument("--debounce-ms", type=int, default=250)
    watch.add_argument("--once", action="store_true", help="Scan once, publish the accepted root, and exit")
    _add_store_option(watch)
    watch.set_defaults(handler=_watch)

    root = subcommands.add_parser("state-root", help="Print the published local state root")
    root.add_argument("repository")
    _add_store_option(root)
    root.set_defaults(handler=_state_root)
    return parser


def main(args: Sequence[str] | None = None) -> int:
    """Run the CLI and return a stable process exit status."""
    parser = create_parser()
    parsed = parser.parse_args(args)
    try:
        return int(parsed.handler(parsed))
    except SemanticIndexCLIError as exc:
        print(f"semantic-index: error: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("semantic-index: error: invalid input or semantic-index state", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
