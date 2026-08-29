#!/usr/bin/env python3
"""Local-only state-law prepublication seal (LCR-072).

Never uploads, deletes, force-pushes, or changes visibility. ``--no-mutate``
is required. ``--require-live-staging-pin`` fails closed until LCR-041 has
produced an immutable staging SHA.

``--generate`` is the explicit, standalone local control-materialization
path.  It rebuilds the exact main publication plan from an existing release
tree, verifies the LCR-084 candidate and a bounded human approval for that
plan, seals the policy proof, and atomically materializes the candidate/card/
seal controls.  It does not construct or receive a Hub transport and cannot
perform a remote mutation.

Validation::

    python scripts/ops/legal_data/seal_state_laws_prepublication.py \\
        --require-live-staging-pin --no-mutate --check
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
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

from ipfs_datasets_py.huggingface.publisher import PublicationApproval
from ipfs_datasets_py.processors.legal_data.state_laws_publication_package import (
    materialize_state_laws_canonical_controls,
    plan_state_laws_publication_dry_run,
    require_state_laws_policy_binding,
)
from ipfs_datasets_py.processors.legal_data.state_laws_publication_policy import (
    DEFAULT_CREDENTIALS_SCOPE,
    example_authorized_main_request,
)

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
    unresolved = Path(path).expanduser()
    if unresolved.is_symlink():
        raise SealEvidenceError(
            f"required receipt must not be a symlink: {unresolved.as_posix()}"
        )
    path = unresolved.resolve()
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


def load_publication_approval(
    path: Path | str,
    *,
    expected_plan_digest: str,
    expected_upload_bytes: int,
    expected_cost_usd: float,
) -> PublicationApproval:
    """Load one bounded approval for the exact rebuilt main plan."""

    unresolved = Path(path).expanduser()
    if unresolved.is_symlink():
        raise SealEvidenceError("publication approval is missing or unsafe")
    target = unresolved.resolve()
    if not target.is_file():
        raise SealEvidenceError("publication approval is missing or unsafe")
    payload = load_json_mapping(target)
    allowed = {
        "approval_id",
        "approver",
        "credentials_scope",
        "max_cost_usd",
        "max_upload_bytes",
        "notes",
        "plan_digest",
    }
    if set(payload) - allowed:
        raise SealBindingError("publication approval has unexpected fields")
    try:
        approval = PublicationApproval(
            approval_id=payload["approval_id"],
            approver=payload["approver"],
            credentials_scope=payload["credentials_scope"],
            max_cost_usd=payload["max_cost_usd"],
            max_upload_bytes=payload["max_upload_bytes"],
            notes=payload.get("notes", ""),
            plan_digest=payload["plan_digest"],
        )
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        raise SealBindingError("publication approval failed validation") from exc
    if approval.plan_digest != _sha256(
        expected_plan_digest, label="expected_plan_digest"
    ):
        raise SealBindingError("publication approval binds another plan")
    if approval.credentials_scope != DEFAULT_CREDENTIALS_SCOPE:
        raise SealBindingError("publication approval credential scope drifted")
    if approval.max_upload_bytes < expected_upload_bytes:
        raise SealBindingError("publication approval upload-byte bound is too small")
    if approval.max_cost_usd < expected_cost_usd:
        raise SealBindingError("publication approval cost bound is too small")
    return approval


def _load_verified_production_candidate(
    *,
    repo_root: Path,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    """Validate the exact LCR-084 candidate without live remeasurement."""

    candidate = load_json_mapping(repo_root / CANDIDATE_RELPATH)
    try:
        script_path = Path(__file__).resolve().with_name(
            "build_state_laws_hf_release.py"
        )
        if script_path.is_symlink() or not script_path.is_file():
            raise SealEvidenceError(
                "exact LCR-084 candidate validator is missing or unsafe"
            )
        source_sha256 = hashlib.sha256(script_path.read_bytes()).hexdigest()
        spec = importlib.util.spec_from_file_location(
            "_state_laws_exact_local_candidate_builder_for_seal",
            script_path,
        )
        if spec is None or spec.loader is None:
            raise SealEvidenceError("exact LCR-084 validator has no file loader")
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        if (
            Path(str(getattr(builder, "__file__", ""))).resolve()
            != script_path
            or hashlib.sha256(script_path.read_bytes()).hexdigest()
            != source_sha256
        ):
            raise SealEvidenceError(
                "exact LCR-084 candidate validator identity changed"
            )

        checked = builder.check_production_candidate_report(
            candidate,
            repo_root=repo_root,
            remeasure_production_evidence=False,
        )
        binding = builder.check_production_candidate_publication_binding(candidate)
    except Exception as exc:
        raise SealEvidenceError(
            f"LCR-084 production candidate validation failed: {exc}"
        ) from exc
    if checked.get("valid") is not True:
        raise SealEvidenceError("LCR-084 production candidate did not pass")
    return candidate, binding


def generate_state_prepublication_seal(
    *,
    release_root: Path | str,
    approval_path: Path | str,
    sealed_at: str,
    repository_root: Path | str = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Materialize the canonical LCR-072 controls with no remote mutation.

    All inputs are reopened and bound before the existing atomic local control
    writer runs.  This function deliberately has no API/transport parameter.
    """

    root = Path(repository_root).expanduser().resolve()
    canary = load_staging_canary(root)
    candidate, existing_binding = _load_verified_production_candidate(
        repo_root=root
    )
    try:
        dry_run = plan_state_laws_publication_dry_run(
            Path(release_root).expanduser().resolve(),
            audited_parent_commit=PREVIOUS_PUBLIC_PIN,
        )
        package = dry_run.package
        plan = dry_run.plan
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise SealEvidenceError(
            f"exact State Laws main plan failed validation: {exc}"
        ) from exc
    if (
        plan.repository_id != TARGET_REPO
        or plan.target_revision != "main"
        or plan.audited_parent_commit != PREVIOUS_PUBLIC_PIN
        or plan.release_sha256 != package.manifest_digest
        or candidate.get("manifest_digest") != package.manifest_digest
        or canary.get("release_manifest_digest") != package.manifest_digest
    ):
        raise SealBindingError(
            "candidate, staging canary, release package, or main plan drifted"
        )
    if existing_binding is not None and (
        existing_binding.get("plan_digest") != plan.plan_digest
        or existing_binding.get("release_manifest_digest")
        != package.manifest_digest
    ):
        raise SealBindingError("existing main candidate binds another plan")
    cost = dict(plan.cost_receipt)
    try:
        expected_upload_bytes = int(cost["upload_bytes"])
        expected_cost_usd = float(cost["estimated_cost_usd"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SealBindingError("main plan cost receipt is malformed") from exc
    approval = load_publication_approval(
        approval_path,
        expected_plan_digest=plan.plan_digest,
        expected_upload_bytes=expected_upload_bytes,
        expected_cost_usd=expected_cost_usd,
    )
    request = example_authorized_main_request(
        manifest_digest=package.manifest_digest,
        staging_revision=canary["staging_revision"],
    )
    try:
        proof = require_state_laws_policy_binding(
            package,
            request,
            plan=plan,
            environ={},
        )
        controls = materialize_state_laws_canonical_controls(
            package,
            plan,
            proof,
            repository_root=root,
            sealed_at=sealed_at,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise SealBindingError(
            f"local prepublication control materialization failed: {exc}"
        ) from exc
    if (
        controls.release_manifest_digest != package.manifest_digest
        or controls.staging_revision != canary["staging_revision"]
    ):
        raise SealBindingError("materialized controls drifted from sealed inputs")
    checked = check_state_prepublication_seal(
        repo_root=root,
        require_live_staging_pin=True,
    )
    seal = load_json_mapping(root / SEAL_RELPATH)
    return {
        **checked,
        "approval_id": approval.approval_id,
        "candidate_file_sha256": controls.candidate_file_sha256,
        "generated": True,
        "hub_mutation_performed": False,
        "network_io_performed": False,
        "seal_content_digest": controls.seal_content_digest,
        "seal_file_sha256": controls.seal_file_sha256,
        "seal": seal,
    }


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
    parser = argparse.ArgumentParser(
        description="LCR-072 local-only state prepublication seal"
    )
    parser.add_argument("--require-live-staging-pin", action="store_true")
    parser.add_argument("--no-mutate", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--generate",
        action="store_true",
        help=(
            "Explicitly materialize the local candidate/card/seal controls; "
            "never contacts or mutates the Hub."
        ),
    )
    parser.add_argument(
        "--release-root",
        type=Path,
        default=None,
        help="Existing verified State Laws release root for --generate.",
    )
    parser.add_argument(
        "--approval",
        type=Path,
        default=None,
        help="Bounded human approval JSON for the exact rebuilt main plan.",
    )
    parser.add_argument(
        "--sealed-at",
        default=None,
        help="Strict UTC-Z seal time for local control materialization.",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.check == args.generate:
        sys.stderr.write(
            "seal_state_laws_prepublication: FAILED: choose exactly one of "
            "--check or --generate\n"
        )
        return 2
    if not args.no_mutate:
        sys.stderr.write(
            "seal_state_laws_prepublication: FAILED: --no-mutate is required\n"
        )
        return 2
    if args.generate and (
        args.release_root is None
        or args.approval is None
        or not str(args.sealed_at or "").strip()
    ):
        sys.stderr.write(
            "seal_state_laws_prepublication: FAILED: --generate requires "
            "--release-root, --approval, and --sealed-at\n"
        )
        return 2
    try:
        if args.generate:
            if not args.require_live_staging_pin:
                raise SealLiveStagingError(
                    "--generate requires --require-live-staging-pin"
                )
            report = generate_state_prepublication_seal(
                release_root=args.release_root,
                approval_path=args.approval,
                sealed_at=str(args.sealed_at),
            )
            report = {**report, "no_mutate": True, "status": "passed"}
        else:
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
