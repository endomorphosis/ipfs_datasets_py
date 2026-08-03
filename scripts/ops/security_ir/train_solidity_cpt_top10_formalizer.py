#!/usr/bin/env python3
"""Preflight a bounded Solidity CPT formal-learning request offline.

The command is dry-run only unless ``--tiny-offline`` is supplied.  That flag
uses the repository's deterministic fixture backend; it does not load a base
model, use a GPU, or create production weights.  This command has no options
for credentials, networking, external tracking, publication, or upload.
Those operations require separate resource and release authority and belong
outside this offline runner.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes  # noqa: E402
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.training import (  # noqa: E402
    DeterministicTinyOfflineBackend,
    FormalTrainingRequest,
    FormalTrainingRunner,
    TrainingAuthorityError,
    TrainingContractError,
    TrainingMode,
    TrainingStatus,
    build_offline_fixture_request,
)

MAX_REQUEST_BYTES: Final = 2 * 1024 * 1024
MAX_RECORDS_BYTES: Final = 16 * 1024 * 1024
MAX_RECORDS: Final = 100_000


class TrainingCommandError(RuntimeError):
    """Safe user-facing command failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a content-addressed Solidity CPT formal-learning request "
            "without network access or model download (dry-run by default)."
        )
    )
    parser.add_argument(
        "--request",
        type=Path,
        help=("Canonical JSON FormalTrainingRequest. When omitted, use the deterministic tiny fixture request."),
    )
    parser.add_argument(
        "--records",
        type=Path,
        help=("Optional bounded JSON array of already-local training records. Evaluation-only records are rejected."),
    )
    parser.add_argument(
        "--tiny-offline",
        action="store_true",
        help=(
            "Run the deterministic CPU fixture backend. This validates "
            "checkpoint/receipt handling and does not train a model."
        ),
    )
    parser.add_argument(
        "--receipt-out",
        type=Path,
        help="Atomically write the terminal receipt as canonical JSON.",
    )
    return parser


def _bounded_regular_file(path: Path, *, maximum: int, label: str) -> bytes:
    try:
        stat = path.stat()
    except OSError as exc:
        raise TrainingCommandError(f"cannot inspect {label}") from exc
    if path.is_symlink() or not path.is_file():
        raise TrainingCommandError(f"{label} must be a regular non-symlink file")
    if stat.st_size > maximum:
        raise TrainingCommandError(f"{label} exceeds its byte budget")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise TrainingCommandError(f"cannot read {label}") from exc


def _json_value(content: bytes, label: str) -> Any:
    try:
        return json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TrainingCommandError(f"{label} must be UTF-8 JSON") from exc


def _load_request(path: Path | None) -> FormalTrainingRequest:
    if path is None:
        return build_offline_fixture_request()
    value = _json_value(
        _bounded_regular_file(path, maximum=MAX_REQUEST_BYTES, label="request file"),
        "request file",
    )
    if not isinstance(value, Mapping):
        raise TrainingCommandError("request file must contain a JSON object")
    try:
        return FormalTrainingRequest.from_dict(value)
    except (TrainingContractError, TrainingAuthorityError) as exc:
        raise TrainingCommandError(f"request rejected: {exc}") from exc


def _load_records(path: Path | None) -> tuple[Mapping[str, Any], ...]:
    if path is None:
        return ()
    value = _json_value(
        _bounded_regular_file(path, maximum=MAX_RECORDS_BYTES, label="records file"),
        "records file",
    )
    if not isinstance(value, list):
        raise TrainingCommandError("records file must contain a JSON array")
    if len(value) > MAX_RECORDS:
        raise TrainingCommandError("records file exceeds its record-count budget")
    result: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise TrainingCommandError(f"records file item {index} must be a JSON object")
        result.append(item)
    return tuple(result)


def _with_mode(request: FormalTrainingRequest, mode: TrainingMode) -> FormalTrainingRequest:
    value = request.to_dict()
    value.pop("request_id", None)
    value["mode"] = mode.value
    return FormalTrainingRequest.from_dict(value)


def _safe_cli_request(request: FormalTrainingRequest, *, tiny_offline: bool) -> FormalTrainingRequest:
    desired = TrainingMode.TINY_OFFLINE if tiny_offline else TrainingMode.DRY_RUN
    if request.mode is not desired:
        request = _with_mode(request, desired)
    # The offline command deliberately refuses grants and every separately
    # governed action even when a caller supplies a structurally valid request.
    if request.authority_grant is not None:
        raise TrainingCommandError("the offline command does not consume operator authority grants")
    if (
        request.hardware.accelerator != "cpu"
        or request.hardware.network_access
        or request.hardware.full_gpu_execution
        or request.output_policy.requested_gated_actions
    ):
        raise TrainingCommandError("the offline command admits only CPU-local, non-publishing requests")
    if tiny_offline and (
        request.backend_id != DeterministicTinyOfflineBackend.backend_id
        or request.backend_capability != DeterministicTinyOfflineBackend.capability
    ):
        raise TrainingCommandError("--tiny-offline requires the deterministic fixture backend binding")
    return request


def _atomic_write(path: Path, content: bytes) -> None:
    parent = path.parent
    if not parent.is_dir():
        raise TrainingCommandError("receipt output parent must already exist")
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise TrainingCommandError("receipt output must be absent or a regular non-symlink file")
    temporary_name = ""
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=parent)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = ""
    except OSError as exc:
        raise TrainingCommandError("cannot atomically write receipt") from exc
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        request = _safe_cli_request(_load_request(args.request), tiny_offline=args.tiny_offline)
        records = _load_records(args.records)
        backend = DeterministicTinyOfflineBackend() if args.tiny_offline else None
        receipt = FormalTrainingRunner(backend).run(request, records)
        content = canonical_json_bytes(receipt.to_dict()) + b"\n"
        if args.receipt_out is not None:
            _atomic_write(args.receipt_out, content)
        sys.stdout.buffer.write(content)
        sys.stdout.buffer.flush()
        return 0 if receipt.status in {TrainingStatus.DRY_RUN, TrainingStatus.SUCCEEDED} else 2
    except (TrainingCommandError, TrainingContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
