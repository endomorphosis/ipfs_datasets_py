#!/usr/bin/env python3
"""Read-only Federal Register prepublication seal (LCR-073).

Never uploads, deletes, force-pushes, or changes visibility. ``--no-mutate``
is required. ``--require-live-staging-pin`` fails closed until LCR-064 has
produced an immutable staging SHA.

Validation::

    python scripts/ops/legal_data/seal_federal_register_prepublication.py \\
        --require-live-staging-pin --no-mutate --check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

TASK_ID = "LCR-073"
GOAL_ID = "LCR-G140"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "seal_federal_register_prepublication.py"
SCHEMA = "ipfs_datasets_py/federal-register-prepublication-seal@1"
TARGET_REPO = "justicedao/ipfs_federal_register"
CANDIDATE_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_candidate.json")
STAGING_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_staging.json")
SEAL_RELPATH = Path("docs/reports/legal_corpora_reindex/federal_prepublication_seal.json")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class PrepublicationSealError(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PrepublicationSealError(f"required receipt is missing: {path.as_posix()}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if type(payload) is not dict:
        raise PrepublicationSealError(f"receipt root must be an object: {path.as_posix()}")
    return payload


def inspect_federal_prepublication_seal(
    *,
    require_live_staging_pin: bool,
    no_mutate: bool,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    if not no_mutate:
        raise PrepublicationSealError("--no-mutate is required; this seal cannot write Hub state")
    reasons: list[str] = []
    candidate = _load(repository_root / CANDIDATE_RELPATH)
    if candidate.get("authorizing_hub_upload") is True:
        reasons.append("candidate authorizing_hub_upload is forbidden")
    staging_path = repository_root / STAGING_RELPATH
    staging_sha = ""
    if staging_path.is_file():
        staging = _load(staging_path)
        staging_sha = str(
            staging.get("staging_sha")
            or staging.get("commit_sha")
            or (staging.get("revision") or "")
        )
        if SHA_RE.fullmatch(staging_sha) is None:
            reasons.append("staging receipt does not bind an exact 40-hex SHA")
    else:
        reasons.append(f"live staging receipt missing: {STAGING_RELPATH.as_posix()}")
    if require_live_staging_pin and reasons:
        raise PrepublicationSealError("; ".join(reasons))
    return {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "target_repo": TARGET_REPO,
        "no_mutate": True,
        "authorizing_hub_upload": False,
        "authorizing_for_publication": False,
        "status": "passed" if not reasons else "blocked",
        "reasons": reasons,
        "staging_sha": staging_sha,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LCR-073 read-only Federal Register prepublication seal"
    )
    parser.add_argument("--require-live-staging-pin", action="store_true")
    parser.add_argument("--no-mutate", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not args.check:
        sys.stderr.write(
            "seal_federal_register_prepublication: FAILED: --check is required\n"
        )
        return 2
    try:
        report = inspect_federal_prepublication_seal(
            require_live_staging_pin=bool(args.require_live_staging_pin),
            no_mutate=bool(args.no_mutate),
        )
    except PrepublicationSealError as exc:
        sys.stderr.write(f"seal_federal_register_prepublication: FAILED: {exc}\n")
        return 1
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            f"seal_federal_register_prepublication: {report['status'].upper()}\n"
        )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
