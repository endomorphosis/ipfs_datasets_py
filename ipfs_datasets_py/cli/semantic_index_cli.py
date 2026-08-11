#!/usr/bin/env python3
"""Inspect deterministic incremental semantic-index states.

State references accepted by ``diff`` are either structured state CIDs stored
in ``--store`` or JSON files produced by ``scan --output``.  ``impact`` and
``explain`` use the current state root for their repository's local store.
The default store is ``<repo>/.semantic_index`` (or ``.semantic_index`` for
``diff``), so no IPFS daemon or optional storage backend is needed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

from ipfs_datasets_py.logic.software_contracts.semantic_index import (
    diff_repository_states,
    explain_impact,
    explain_symbol,
    scan_repository,
    watch_repository,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import RepositoryState
from ipfs_datasets_py.logic.software_contracts.semantic_index.persistence import LocalSemanticIndexStore
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import repository_identity

__all__ = ["create_parser", "main"]


def _json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _store_path(repository: str | None, supplied: str | None) -> Path:
    if supplied:
        return Path(supplied).expanduser()
    base = Path(repository).resolve() if repository is not None else Path.cwd()
    return base / ".semantic_index"


def _store(repository: str | None, supplied: str | None) -> LocalSemanticIndexStore:
    return LocalSemanticIndexStore(_store_path(repository, supplied))


def _read_state_file(path: Path) -> RepositoryState:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("state file is unavailable or invalid JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("state file must contain a semantic-index state object")
    try:
        return RepositoryState.from_dict(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("state file is not a valid semantic-index state") from exc


def _state_reference(reference: str, store: LocalSemanticIndexStore) -> RepositoryState:
    path = Path(reference).expanduser()
    # A CID cannot be a valid existing file name in normal CLI use. Prefer a
    # real path so a missing JSON file gets a useful file-specific failure.
    if path.is_file():
        return _read_state_file(path)
    if reference.endswith(".json") or os.sep in reference or reference.startswith("."):
        raise ValueError("state file does not exist")
    try:
        return store.load_state(reference)
    except Exception as exc:
        raise ValueError("state CID is unavailable or invalid in this store") from exc


def _current_state(repository: str, store: LocalSemanticIndexStore) -> RepositoryState:
    repository_id = repository_identity(repository)
    cid = store.current_root(repository_id)
    if cid is None:
        raise ValueError("no indexed state exists for this repository; run 'semantic-index scan <repo>' first")
    return store.load_state(cid)


def _write_state(path: str, state: RepositoryState) -> None:
    target = Path(path).expanduser()
    if target.exists() and target.is_dir():
        raise ValueError("--output must name a file")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        temporary.write_text(json.dumps(state.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def _publish(state: RepositoryState, store: LocalSemanticIndexStore) -> None:
    previous = store.current_root(state.repository_id)
    store.store_state(state)
    store.compare_and_swap_root(state.repository_id, previous, state.state_cid)


def _scan(args: argparse.Namespace) -> int:
    store = _store(args.repo, args.store)
    state = scan_repository(args.repo)
    _publish(state, store)
    if args.output:
        _write_state(args.output, state)
    _json(state.to_dict())
    return 0


def _diff(args: argparse.Namespace) -> int:
    store = _store(None, args.store)
    old = _state_reference(args.old_state, store)
    new = _state_reference(args.new_state, store)
    _json(diff_repository_states(old, new).to_dict())
    return 0


def _impact(args: argparse.Namespace) -> int:
    state = _current_state(args.repo, _store(args.repo, args.store))
    _json(explain_impact(state, args.symbol_or_file, max_depth=args.max_depth, max_nodes=args.max_nodes).to_dict())
    return 0


def _explain(args: argparse.Namespace) -> int:
    state = _current_state(args.repo, _store(args.repo, args.store))
    _json(explain_symbol(state, args.symbol).to_dict())
    return 0


def _state_root(args: argparse.Namespace) -> int:
    store = _store(args.repo, args.store)
    repository_id = repository_identity(args.repo)
    cid = store.current_root(repository_id)
    _json({"repository_id": repository_id, "state_cid": cid})
    return 0 if cid is not None else 1


def _watch(args: argparse.Namespace) -> int:
    store = _store(args.repo, args.store)
    if args.once:
        state = scan_repository(args.repo)
        _publish(state, store)
        _json(state.to_dict())
        return 0

    def callback(notification: Any) -> None:
        _publish(notification.current_state, store)
        _json(notification.current_state.to_dict())

    watcher = watch_repository(args.repo, callback, debounce_ms=args.debounce_ms)
    try:
        _publish(watcher.current_state, store)
        _json(watcher.current_state.to_dict())
        while watcher.is_running:
            time.sleep(0.25)
    except KeyboardInterrupt:
        return 0
    finally:
        watcher.stop()
    return 0


def _add_store_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--store", help="Local semantic-index store directory (default is repository/.semantic_index)")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="semantic-index", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="scan and publish a repository state")
    scan.add_argument("repo")
    _add_store_option(scan)
    scan.add_argument("--output", metavar="FILE", help="write the verified state JSON for later diff use")
    scan.set_defaults(handler=_scan)

    diff = subparsers.add_parser("diff", help="diff state CIDs or JSON state files")
    diff.add_argument("old_state", metavar="old-state")
    diff.add_argument("new_state", metavar="new-state")
    _add_store_option(diff)
    diff.set_defaults(handler=_diff)

    impact = subparsers.add_parser("impact", help="explain reverse impact of a symbol, artifact, or repository-relative file")
    impact.add_argument("repo")
    impact.add_argument("symbol_or_file", metavar="symbol-or-file")
    _add_store_option(impact)
    impact.add_argument("--max-depth", type=int, default=8)
    impact.add_argument("--max-nodes", type=int, default=1000)
    impact.set_defaults(handler=_impact)

    explain = subparsers.add_parser("explain", help="explain a symbol in the repository's current state")
    explain.add_argument("repo")
    explain.add_argument("symbol")
    _add_store_option(explain)
    explain.set_defaults(handler=_explain)

    watch = subparsers.add_parser("watch", help="watch a repository using the local polling backend")
    watch.add_argument("repo")
    _add_store_option(watch)
    watch.add_argument("--debounce-ms", type=int, default=250)
    watch.add_argument("--once", action="store_true", help="scan once and exit (useful for automation)")
    watch.set_defaults(handler=_watch)

    root = subparsers.add_parser("state-root", help="print the current repository state CID")
    root.add_argument("repo")
    _add_store_option(root)
    root.set_defaults(handler=_state_root)
    return parser


def main(args: list[str] | None = None) -> int:
    parser = create_parser()
    try:
        parsed = parser.parse_args(args)
        return parsed.handler(parsed)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"semantic-index: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
