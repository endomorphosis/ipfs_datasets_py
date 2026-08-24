#!/usr/bin/env python3
"""Assemble the descriptor-complete Federal Register HF release (LCR-062).

Consumes immutable LCR-061 family outputs and the LCR-079 source-rights
receipt. Writes additive v2 paths, Viewer configs, a rights-aware card,
compact lineage, rollback metadata, and the candidate evidence root.

Fixture-only default. No Hub upload. Unknown or prohibited rights cannot
enter the default release.

Examples
--------
Hermetic CI gate::

    python scripts/ops/legal_data/build_federal_register_hf_release.py \\
        --fixture-only --check

Stage a local candidate tree::

    python scripts/ops/legal_data/build_federal_register_hf_release.py \\
        --fixture-only --output-dir /tmp/fr-hf-release
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.federal_register_hf_release import (  # noqa: E402
    AUTHORIZES_HUB_UPLOAD,
    AUTHORIZES_PUBLICATION,
    CANDIDATE_EVIDENCE_RELPATH,
    GOAL_ID,
    PROGRAM_ID,
    SCHEMA_VERSION,
    TASK_ID,
    FederalRegisterHFReleaseError,
    HubUploadForbiddenError,
    build_federal_candidate_evidence,
    build_federal_register_hf_release,
    consume_lcr061_family_outputs,
    fixture_family_rows,
    fixture_legacy_files,
    reject_hub_upload,
    run_hermetic_check,
    stage_federal_register_hf_release,
    write_federal_candidate_evidence,
)

PRODUCER: Final = "build_federal_register_hf_release.py"


class CliError(SystemExit):
    """CLI-level failure with a non-zero exit code."""

    def __init__(self, message: str, *, code: int = 2) -> None:
        super().__init__(code)
        self.message = message
        print(f"error: {message}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_federal_register_hf_release.py",
        description=(
            "Assemble the descriptor-complete Federal Register Hugging Face "
            "release and dataset card (LCR-062). Fixture-only default; no Hub "
            "upload. Unknown or prohibited rights cannot enter the default "
            "release."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build/federal-register-hf-release"),
        help="Local additive staging root (ignored by --check)",
    )
    parser.add_argument(
        "--fixture-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Offline fixture assembly (default: true; no network, no Hub)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run the hermetic fixture self-check and exit (no Hub)",
    )
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Keep the candidate in memory (default: true)",
    )
    parser.add_argument(
        "--write-candidate",
        action="store_true",
        help=f"Write {CANDIDATE_EVIDENCE_RELPATH} from the fixture release",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON result on stdout",
    )
    parser.add_argument(
        "--hub-upload",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def _emit(payload: Mapping[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
        )
        return
    print(f"task_id: {payload.get('task_id')}")
    print(f"goal_id: {payload.get('goal_id')}")
    print(f"ok: {payload.get('ok', True)}")
    print(f"manifest_digest: {payload.get('manifest_digest')}")
    print(f"release_root_cid: {payload.get('release_root_cid') or payload.get('candidate_root')}")
    print(f"source_rights_receipt_digest: {payload.get('source_rights_receipt_digest')}")
    print(f"authorizing_for_publication: {payload.get('authorizing_for_publication')}")
    print(f"hub_upload: {payload.get('authorizing_hub_upload')}")
    proofs = payload.get("proofs") or ()
    if proofs:
        print(f"proofs: {', '.join(proofs)}")
    staged = payload.get("staged_root")
    if staged:
        print(f"staged_root: {staged}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if getattr(args, "hub_upload", False):
        raise CliError("Hub upload is forbidden in LCR-062")
    if not args.fixture_only:
        raise CliError("this CLI is fixture-only; live/Hub builds are out of scope")

    try:
        reject_hub_upload(False)
        if args.check:
            payload = run_hermetic_check(write_candidate=bool(args.write_candidate))
            payload["producer"] = PRODUCER
            _emit(payload, as_json=args.json)
            return 0 if payload.get("ok") else 1

        consumption = consume_lcr061_family_outputs()
        release = build_federal_register_hf_release(
            fixture_family_rows(),
            legacy_files=fixture_legacy_files(),
            dry_run=True,
            lcr061_consumption=consumption,
        )
        staged_root = None
        if not args.dry_run:
            staged = stage_federal_register_hf_release(
                release,
                args.output_dir,
                dry_run=False,
            )
            staged_root = staged.staged_root
            release = staged
        evidence = build_federal_candidate_evidence(
            release,
            consumption=consumption,
        )
        if args.write_candidate:
            write_federal_candidate_evidence(evidence)

        payload = {
            "authorizing_for_publication": AUTHORIZES_PUBLICATION,
            "authorizing_hub_upload": AUTHORIZES_HUB_UPLOAD,
            "candidate_root": release.release_root_cid,
            "content_digest": evidence["content_digest"],
            "dry_run": release.dry_run,
            "fixture_only": True,
            "goal_id": GOAL_ID,
            "lcr061_family_outputs": evidence["lcr061_family_outputs"],
            "manifest_digest": release.manifest_digest,
            "ok": True,
            "producer": PRODUCER,
            "program_id": PROGRAM_ID,
            "release_root_cid": release.release_root_cid,
            "schema_version": SCHEMA_VERSION,
            "source_rights_receipt_digest": release.source_rights_receipt_digest,
            "staged_root": staged_root,
            "task_id": TASK_ID,
        }
        _emit(payload, as_json=args.json)
        return 0
    except HubUploadForbiddenError as exc:
        raise CliError(str(exc)) from exc
    except FederalRegisterHFReleaseError as exc:
        raise CliError(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
