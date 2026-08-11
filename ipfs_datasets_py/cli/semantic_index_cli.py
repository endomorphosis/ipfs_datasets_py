#!/usr/bin/env python3
"""Deterministic local CLI for the incremental semantic index.

State references accepted by ``diff`` and ``--state`` are either a structured
state CID in the selected ``--store`` or a JSON file written by ``scan``.  A
store defaults to ``<repo>/.semantic-index`` for repository commands and to
``./.semantic-index`` for ``diff``.  The default is entirely local; it does
not require IPFS, a daemon, or a network connection.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable

from ipfs_datasets_py.logic.software_contracts.semantic_index import (
    diff_repository_states,
    explain_impact,
    explain_symbol,
    scan_repository,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import RepositoryState
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import repository_identity


__all__ = ["create_parser", "main"]


class SemanticIndexCLIError(ValueError):
    """A stable, user-facing semantic-index CLI failure."""


def _store_path(repository: str | None, requested: str | None) -> Path:
    if requested:
        return Path(requested).expanduser().resolve()
    base = Path(repository).expanduser().resolve() if repository else Path.cwd()
    return base / ".semantic-index"


def _require_repository(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise SemanticIndexCLIError("repository must be an existing directory")
    return path


def _store(repository: str | None, requested: str | None) -> Any:
    # Keep persistence out of import and help paths.  LocalSemanticIndexStore
    # is deliberately the only CLI default; optional backends are injected by
    # API users, never guessed by a command invocation.
    from ipfs_datasets_py.logic.software_contracts.semantic_index.persistence import LocalSemanticIndexStore

    return LocalSemanticIndexStore(_store_path(repository, requested))


def _state_from_file(path: Path) -> RepositoryState:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SemanticIndexCLIError("state file is unavailable or invalid") from exc
    if isinstance(raw, dict) and isinstance(raw.get("state"), dict):
        raw = raw["state"]
    if not isinstance(raw, dict):
        raise SemanticIndexCLIError("state file must contain a JSON object")
    try:
        return RepositoryState.from_dict(raw)
    except (TypeError, ValueError, KeyError) as exc:
        raise SemanticIndexCLIError("state file does not contain a verified repository state") from exc


def _load_state(reference: str, store: Any) -> RepositoryState:
    candidate = Path(reference).expanduser()
    if candidate.is_file():
        return _state_from_file(candidate)
    # A missing path must remain a missing file error rather than being treated
    # as a malformed CID.  CIDs never contain path separators.
    if candidate.exists() or os.sep in reference or reference.startswith("."):
        raise SemanticIndexCLIError("state file is unavailable or invalid")
    try:
        return store.load_state(reference)
    except Exception as exc:
        raise SemanticIndexCLIError("state CID is unavailable or invalid") from exc


def _emit(value: Any, output: str | None = None) -> None:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    if output is not None:
        target = Path(output).expanduser()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(payload, encoding="utf-8")
        except OSError as exc:
            raise SemanticIndexCLIError("cannot write output state file") from exc
    sys.stdout.write(payload)


def _publish_scan(repository: str, store_location: str | None) -> RepositoryState:
    repo = _require_repository(repository)
    store = _store(str(repo), store_location)
    try:
        old_cid = store.current_root(repository_identity(repo))
    except Exception as exc:
        raise SemanticIndexCLIError("semantic-index root is unavailable or invalid") from exc
    state = scan_repository(repo)
    try:
        store.store_state(state)
        store.compare_and_swap_root(state.repository_id, old_cid, state.state_cid)
    except Exception as exc:
        raise SemanticIndexCLIError("cannot publish semantic-index state") from exc
    return state


def _current_state(repository: str, store_location: str | None, reference: str | None) -> RepositoryState:
    repo = _require_repository(repository)
    store = _store(str(repo), store_location)
    if reference:
        return _load_state(reference, store)
    try:
        cid = store.current_root(repository_identity(repo))
    except Exception as exc:
        raise SemanticIndexCLIError("semantic-index root is unavailable or invalid") from exc
    if cid is not None:
        return _load_state(cid, store)
    return _publish_scan(str(repo), store_location)


def _command_scan(args: argparse.Namespace) -> None:
    state = _publish_scan(args.repository, args.store)
    _emit(state.to_dict(), args.output)


def _command_diff(args: argparse.Namespace) -> None:
    store = _store(None, args.store)
    previous = _load_state(args.old_state, store)
    current = _load_state(args.new_state, store)
    _emit(diff_repository_states(previous, current).to_dict())


def _command_impact(args: argparse.Namespace) -> None:
    state = _current_state(args.repository, args.store, args.state)
    _emit(explain_impact(state, args.symbol_or_file).to_dict())


def _command_explain(args: argparse.Namespace) -> None:
    state = _current_state(args.repository, args.store, args.state)
    _emit(explain_symbol(state, args.symbol).to_dict())


def _command_state_root(args: argparse.Namespace) -> None:
    repo = _require_repository(args.repository)
    store = _store(str(repo), args.store)
    try:
        repository_id = repository_identity(repo)
        cid = store.current_root(repository_id)
    except Exception as exc:
        raise SemanticIndexCLIError("semantic-index root is unavailable or invalid") from exc
    _emit({"repository_id": repository_id, "state_cid": cid})


def _command_watch(args: argparse.Namespace) -> None:
    repo = _require_repository(args.repository)
    state = _current_state(str(repo), args.store, args.state)
    if args.once:
        _emit({"event": "baseline", "state": state.to_dict()})
        return

    # Watch dependencies stay lazy and are only imported after argument
    # validation.  Notifications are emitted in the same canonical JSON form.
    from ipfs_datasets_py.logic.software_contracts.semantic_index import watch_repository

    def notify(notification: Any) -> None:
        _emit({"event": "changed", "previous_state_cid": notification.previous_state_cid, "state": notification.state.to_dict()})

    watch = watch_repository(repo, notify, debounce_ms=args.debounce_ms)
    try:
        _emit({"event": "baseline", "state": state.to_dict()})
        while watch.is_running:
            time.sleep(0.1)
    except KeyboardInterrupt:
        return
    finally:
        watch.stop()


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, prog="semantic-index")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def command(name: str, help_text: str, handler: Callable[[argparse.Namespace], None]) -> argparse.ArgumentParser:
        item = subparsers.add_parser(name, help=help_text)
        item.set_defaults(handler=handler)
        return item

    scan = command("scan", "scan and publish a repository state", _command_scan)
    scan.add_argument("repository")
    scan.add_argument("--store", help="local store directory (default: <repo>/.semantic-index)")
    scan.add_argument("--output", help="also write the verified state JSON to this file")

    diff = command("diff", "diff two state CIDs or scan JSON files", _command_diff)
    diff.add_argument("old_state", help="CID in --store or a state JSON file")
    diff.add_argument("new_state", help="CID in --store or a state JSON file")
    diff.add_argument("--store", help="local store directory for CID references (default: ./.semantic-index)")

    for name, help_text, handler, argument, argument_help in (
        ("impact", "explain reverse impact of a symbol, artifact, or file", _command_impact, "symbol_or_file", "stable symbol ID, artifact ID, or repository-relative file"),
        ("explain", "explain one symbol", _command_explain, "symbol", "stable symbol ID"),
    ):
        item = command(name, help_text, handler)
        item.add_argument("repository")
        item.add_argument(argument, help=argument_help)
        item.add_argument("--store", help="local store directory (default: <repo>/.semantic-index)")
        item.add_argument("--state", help="CID in --store or a state JSON file; defaults to current root")

    watch = command("watch", "watch a repository and emit changed states", _command_watch)
    watch.add_argument("repository")
    watch.add_argument("--store", help="local store directory (default: <repo>/.semantic-index)")
    watch.add_argument("--state", help="CID in --store or a state JSON file for the initial state")
    watch.add_argument("--debounce-ms", type=int, default=250, help="nonnegative debounce interval (default: 250)")
    watch.add_argument("--once", action="store_true", help="emit the baseline state and exit")

    root = command("state-root", "show the current published state CID", _command_state_root)
    root.add_argument("repository")
    root.add_argument("--store", help="local store directory (default: <repo>/.semantic-index)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    try:
        args = parser.parse_args(argv)
        args.handler(args)
    except SemanticIndexCLIError as exc:
        sys.stderr.write(f"semantic-index: error: {exc}\n")
        return 1
    except Exception:
        sys.stderr.write("semantic-index: error: request could not be completed\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
