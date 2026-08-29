#!/usr/bin/env python3
"""Read-only state-law prepublication seal (LCR-072).

Never uploads, deletes, force-pushes, or changes visibility. ``--no-mutate``
is required. ``--require-live-staging-pin`` fails closed until LCR-041 has
produced an immutable staging SHA.

Validation::

    python scripts/ops/legal_data/seal_state_laws_prepublication.py \\
        --require-live-staging-pin --no-mutate --check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

TASK_ID = "LCR-072"
GOAL_ID = "LCR-G080"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "seal_state_laws_prepublication.py"
SCHEMA = "ipfs_datasets_py/state-laws-prepublication-seal@1"
CANONICAL_SCHEMA = "ipfs_datasets_py/legal-corpora-prepublication-seal@1"
TARGET_REPO = "justicedao/ipfs_state_laws"
PREVIOUS_PUBLIC_PIN = "42f0546acc7c6cd55627eaf51fb820d5613b9021"
CANDIDATE_RELPATH = Path("docs/reports/legal_corpora_reindex/release_candidate.json")
STAGING_RELPATH = Path("docs/reports/legal_corpora_reindex/staging_canary.json")
SEAL_RELPATH = Path("docs/reports/legal_corpora_reindex/state_prepublication_seal.json")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SELF_DIGEST_FIELDS = frozenset(
    {
        "canonical_digest",
        "content_digest",
        "digest",
        "final_manifest_digest",
        "manifest_digest",
        "no_self_field_digest",
        "raw_sha256",
        "receipt_sha256",
        "sha256",
    }
)


class SealStateLawsError(RuntimeError):
    pass


class SealEvidenceError(SealStateLawsError):
    pass


class SealLiveStagingError(SealStateLawsError):
    pass


class SealBindingError(SealStateLawsError):
    pass


PrepublicationSealError = SealStateLawsError


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise SealEvidenceError(f"required receipt is missing: {path.as_posix()}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SealEvidenceError(f"receipt is malformed: {path.as_posix()}") from exc
    if type(payload) is not dict:
        raise SealEvidenceError(f"receipt root must be an object: {path.as_posix()}")
    return payload


_load = load_json_mapping


def default_seal_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / SEAL_RELPATH).resolve()


def default_canary_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / STAGING_RELPATH).resolve()


def load_staging_canary(
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    canary = load_json_mapping(path or default_canary_path(repo_root))
    revision = str(
        canary.get("staging_revision")
        or canary.get("commit_sha")
        or ""
    ).strip().casefold()
    if SHA_RE.fullmatch(revision) is None:
        raise SealLiveStagingError(
            "State staging canary does not bind an exact 40-hex revision"
        )
    if (
        canary.get("status") not in {"pass", "passed", "verified"}
        or canary.get("fixture_only") is not False
        or canary.get("dirty") is not False
        or canary.get("live_staging") is not True
    ):
        raise SealLiveStagingError(
            "State staging canary is not clean passed live evidence"
        )
    result = dict(canary)
    result["staging_revision"] = revision
    return result


def _sha256(value: Any, *, label: str) -> str:
    text = str(value or "").strip().casefold()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise SealBindingError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _verify_content_digest(seal: Mapping[str, Any]) -> None:
    declared = seal.get("content_digest")
    if declared is None:
        return
    body = {
        key: value
        for key, value in seal.items()
        if key not in SELF_DIGEST_FIELDS
    }
    if _sha256(declared, label="seal.content_digest") != sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest():
        raise SealBindingError("State seal content digest does not match its body")


def check_state_prepublication_seal(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
    require_live_staging_pin: bool = True,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    # Resolve the immutable live pin first so a missing LCR-041 dependency is
    # reported as such even when the later main seal has not been issued yet.
    canary = load_staging_canary(root)
    seal = load_json_mapping(path or default_seal_path(root))
    candidate = load_json_mapping(root / CANDIDATE_RELPATH)
    candidate_digest = _sha256(
        candidate.get("report_digest_sha256")
        or candidate.get("final_manifest_digest")
        or candidate.get("content_digest"),
        label="candidate.final_manifest_digest",
    )
    seal_digest = _sha256(
        seal.get("final_manifest_digest") or seal.get("manifest_digest"),
        label="seal.final_manifest_digest",
    )
    seal_revision = str(seal.get("staging_revision") or "").strip().casefold()
    if SHA_RE.fullmatch(seal_revision) is None:
        raise SealBindingError("State seal staging_revision must be exact 40-hex")
    binding = candidate.get("publication_binding")
    if not isinstance(binding, Mapping):
        raise SealBindingError(
            "State candidate lacks its exact main publication binding"
        )
    if candidate.get("schema") == (
        "ipfs_datasets_py/legal-corpora-reindex-release-candidate@2"
    ):
        body = {
            key: value
            for key, value in candidate.items()
            if key != "report_digest_sha256"
        }
        if sha256(
            json.dumps(
                body,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest() != candidate_digest:
            raise SealBindingError(
                "State candidate report digest does not match its body"
            )
    if (
        seal.get("schema") not in {SCHEMA, CANONICAL_SCHEMA}
        or seal.get("task_id") != TASK_ID
        or seal.get("dataset_repo_id", seal.get("target_repo")) != TARGET_REPO
        or seal.get("phase") != "state_main"
        or seal.get("operation") != "additive_main_upload"
        or seal.get("status") != "sealed"
        or seal.get("present") is not True
        or seal.get("timing") != "before_mutation"
        or seal.get("created_after_mutation") is not False
        or seal.get("post_hoc") is not False
        or seal.get("fixture_only") is not False
        or seal.get("dirty") is not False
        or seal.get("no_mutation") is not True
        or seal.get("mutation_executed") is not False
        or seal.get("network_mutation") is not False
        or seal.get("previous_public_pin") != PREVIOUS_PUBLIC_PIN
        or candidate_digest != seal_digest
        or seal_revision != canary["staging_revision"]
    ):
        raise SealBindingError(
            "State prepublication seal is stale, unsafe, or candidate/canary-unbound"
        )
    for field in ("plan_digest", "policy_proof_digest", "release_manifest_digest"):
        value = _sha256(seal.get(field), label=f"seal.{field}")
        if binding.get(field) != value:
            raise SealBindingError(
                f"State seal {field} differs from the candidate binding"
            )
        if (
            field == "release_manifest_digest"
            and canary.get(field) != value
        ):
            raise SealBindingError(
                "State seal release digest differs from the staging canary"
            )
    staging_candidate_digest = _sha256(
        binding.get("staging_candidate_digest"),
        label="candidate.publication_binding.staging_candidate_digest",
    )
    if canary.get("final_manifest_digest") != staging_candidate_digest:
        raise SealBindingError(
            "State staging canary does not bind candidate identity A"
        )
    if require_live_staging_pin and canary.get("fixture_only") is not False:
        raise SealLiveStagingError("State seal requires a live staging pin")
    _verify_content_digest(seal)
    return {
        "dataset_repo_id": TARGET_REPO,
        "final_manifest_digest": seal_digest,
        "live_staging": True,
        "manifest_digest": seal_digest,
        "ok": True,
        "path": SEAL_RELPATH.as_posix(),
        "plan_digest": seal["plan_digest"],
        "policy_proof_digest": seal["policy_proof_digest"],
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "release_manifest_digest": seal["release_manifest_digest"],
        "staging_revision": seal_revision,
        "task_id": TASK_ID,
    }


def inspect_state_prepublication_seal(
    *,
    require_live_staging_pin: bool,
    no_mutate: bool,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    if not no_mutate:
        raise SealStateLawsError("--no-mutate is required; this seal cannot write Hub state")
    checked = check_state_prepublication_seal(
        repo_root=repository_root,
        require_live_staging_pin=require_live_staging_pin,
    )
    return {**checked, "no_mutate": True, "status": "passed"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LCR-072 read-only state prepublication seal")
    parser.add_argument("--require-live-staging-pin", action="store_true")
    parser.add_argument("--no-mutate", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not args.check:
        sys.stderr.write("seal_state_laws_prepublication: FAILED: --check is required\n")
        return 2
    try:
        report = inspect_state_prepublication_seal(
            require_live_staging_pin=bool(args.require_live_staging_pin),
            no_mutate=bool(args.no_mutate),
        )
    except PrepublicationSealError as exc:
        sys.stderr.write(f"seal_state_laws_prepublication: FAILED: {exc}\n")
        return 1
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            f"seal_state_laws_prepublication: {report['status'].upper()}\n"
        )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
