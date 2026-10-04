#!/usr/bin/env python3
"""Build or verify a deterministic local Solidity CPT source-free release.

This command is offline and local-only.  It has no credential, network,
upload, publication, proof-execution, signing, or transaction options.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes  # noqa: E402
from ipfs_datasets_py.logic.ir_core.identity import cid_v1  # noqa: E402
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.evaluation import (  # noqa: E402
    build_offline_fixture_evaluation,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.hf_release import (  # noqa: E402
    SolidityCPTReleaseError,
    build_solidity_cpt_release,
    validate_solidity_cpt_release,
)

MAX_EVALUATION_BYTES: Final = 32 * 1024 * 1024
MAX_CANDIDATE_BYTES: Final = 16 * 1024 * 1024
DEFAULT_CONFIG_CID: Final = cid_v1(
    b"solidity-cpt-source-free-release-config-v1"
)


class ReleaseCommandError(RuntimeError):
    """Safe command-line failure."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Stage a deterministic source-free Solidity CPT release locally, "
            "or verify an existing local release."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "Absent or empty local directory for staging. Required unless "
            "--verify-only is supplied."
        ),
    )
    parser.add_argument(
        "--evaluation",
        type=Path,
        help=(
            "Optional local CID-bound evaluation receipt. When omitted, use "
            "the deterministic offline fixture receipt."
        ),
    )
    parser.add_argument(
        "--candidate-metadata",
        type=Path,
        help=(
            "Optional local JSON array of source-free reviewed candidate "
            "metadata. Raw Solidity bodies are rejected."
        ),
    )
    parser.add_argument(
        "--config-cid",
        default=DEFAULT_CONFIG_CID,
        help="Exact local release configuration CID.",
    )
    parser.add_argument(
        "--verify-only",
        type=Path,
        help="Verify an existing local release directory without writing.",
    )
    return parser


def _bounded_regular_file(path: Path, *, maximum: int, label: str) -> bytes:
    try:
        stat = path.stat()
    except OSError as exc:
        raise ReleaseCommandError(f"cannot inspect {label}") from exc
    if path.is_symlink() or not path.is_file():
        raise ReleaseCommandError(f"{label} must be a regular non-symlink file")
    if stat.st_size > maximum:
        raise ReleaseCommandError(f"{label} exceeds its byte budget")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ReleaseCommandError(f"cannot read {label}") from exc


def _json_value(path: Path, *, maximum: int, label: str) -> Any:
    try:
        return json.loads(
            _bounded_regular_file(path, maximum=maximum, label=label)
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseCommandError(f"{label} must be UTF-8 JSON") from exc


def _load_evaluation(path: Path | None) -> Mapping[str, Any]:
    if path is None:
        return build_offline_fixture_evaluation().to_dict()
    value = _json_value(
        path, maximum=MAX_EVALUATION_BYTES, label="evaluation file"
    )
    if not isinstance(value, Mapping):
        raise ReleaseCommandError(
            "evaluation file must contain a JSON object"
        )
    return value


def _load_candidates(path: Path | None) -> tuple[Mapping[str, Any], ...]:
    if path is None:
        return ()
    value = _json_value(
        path, maximum=MAX_CANDIDATE_BYTES, label="candidate metadata file"
    )
    if not isinstance(value, list):
        raise ReleaseCommandError(
            "candidate metadata file must contain a JSON array"
        )
    result: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ReleaseCommandError(
                f"candidate metadata item {index} must be a JSON object"
            )
        result.append(item)
    return tuple(result)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.verify_only is not None:
            if (
                args.output_dir is not None
                or args.evaluation is not None
                or args.candidate_metadata is not None
            ):
                raise ReleaseCommandError(
                    "--verify-only cannot be combined with build inputs"
                )
            manifest = validate_solidity_cpt_release(args.verify_only)
            output = {
                "manifest": manifest.to_dict(),
                "verified": True,
            }
        else:
            if args.output_dir is None:
                raise ReleaseCommandError(
                    "--output-dir is required for a local build"
                )
            result = build_solidity_cpt_release(
                args.output_dir,
                evaluation=_load_evaluation(args.evaluation),
                config_cid=args.config_cid,
                candidates=_load_candidates(args.candidate_metadata),
            )
            output = result.to_dict()
        sys.stdout.buffer.write(canonical_json_bytes(output) + b"\n")
        return 0
    except (ReleaseCommandError, SolidityCPTReleaseError) as exc:
        print(f"release rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
