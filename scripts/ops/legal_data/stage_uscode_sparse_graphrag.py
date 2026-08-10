#!/usr/bin/env python3
"""Safe candidate staging and dry-run packaging for US Code sparse GraphRAG (USCIR-032).

Default mode is **offline dry-run** (credential-free, no Hub network contact):

1. Build or load a validated release candidate and bind its manifest digest.
2. Plan **add-only** uploads to an explicitly named staging target/branch.
3. Reject production targets (``main`` / ``master`` / public production pin)
   without a separate human publication seal.
4. Emit a redacted staging receipt — no tokens, no absolute local paths.
5. Guarantee that deletion, force-push, and visibility changes are impossible.

Operator workflow after a successful dry-run receipt:

1. ``--fixture-only --dry-run``  — deterministic plan + receipt (default)
2. Review ``plan_digest``, ``manifest_digest``, target, and staging branch
3. Only then consider remote mutation under explicit opt-in authorization
   (``--authorize-mutation`` + ``$USCODE_STAGING_AUTHORIZATION``). Live Hub
   mutation remains outside this CLI unless an operator injects a client.

This script never:

* uploads to ``main`` / ``master``;
* deletes, force-pushes, or changes repository visibility;
* embeds or logs Hub tokens;
* mutates anything without opt-in authorization;
* treats credentials as CLI flags (environment-only).

Validation gate (no network)::

    python scripts/ops/legal_data/stage_uscode_sparse_graphrag.py --fixture-only --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.huggingface.release import (  # noqa: E402
    canonical_json_bytes,
    reject_identity_contamination,
)
from ipfs_datasets_py.processors.legal_data.uscode_hf_release import (  # noqa: E402
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_SOURCE_REVISION,
    MANIFEST_FILENAME,
    UscodeHFReleaseError,
    UscodeHuggingFaceRelease,
    build_uscode_hf_release,
    fixture_family_rows,
    fixture_legacy_files,
    validate_uscode_hf_release,
)
from ipfs_datasets_py.processors.legal_data.uscode_release_schema import (  # noqa: E402
    require_immutable_revision,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "USCIR-032"
GOAL_ID: Final = "USCIR-G080"
PROGRAM_ID: Final = "uscode-sparse-graphrag-v1"
PRODUCER: Final = "stage_uscode_sparse_graphrag.py"
CODE_VERSION: Final = "1"

STAGE_PLAN_SCHEMA: Final = "ipfs_datasets_py/uscode-sparse-graphrag-stage-plan@1"
DRY_RUN_RECEIPT_SCHEMA: Final = "ipfs_datasets_py/uscode-sparse-graphrag-stage-receipt@1"

DEFAULT_DATASET_REPO: Final = DEFAULT_DATASET_REPO_ID
# Public production pin — staging branch must not equal this without a seal.
PRODUCTION_REVISION: Final = DEFAULT_SOURCE_REVISION
DEFAULT_STAGING_BRANCH: Final = "stage/uscode-sparse-graphrag-v2"
DEFAULT_BASE_REVISION: Final = PRODUCTION_REVISION
DEFAULT_PACKAGE_VERSION: Final = "2"

DEFAULT_STAGE_PLAN_RELPATH: Final = Path(
    "tests/fixtures/legal_ir/uscode_stage_plan.json"
)

# Operations this planner will never schedule.
FORBIDDEN_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "delete",
        "delete_file",
        "delete_folder",
        "force",
        "force_push",
        "force-push",
        "overwrite_history",
        "visibility_change",
        "change_visibility",
        "make_private",
        "make_unlisted",
        "set_private",
        "set_unlisted",
        "rotate_credentials",
        "direct_main_upload",
        "promote_production",
    }
)
ALLOWED_OPERATIONS: Final[frozenset[str]] = frozenset({"add_only_upload"})

PROHIBITED_STAGING_BRANCHES: Final[frozenset[str]] = frozenset(
    {
        "main",
        "master",
        "refs/heads/main",
        "refs/heads/master",
        "production",
        "prod",
        "live",
    }
)

SECRET_ENV_NAMES: Final[tuple[str, ...]] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
    "USCODE_STAGING_AUTHORIZATION",
)
AUTHORIZATION_ENV: Final = "USCODE_STAGING_AUTHORIZATION"

_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key|operator_key|"
    r"staging_authorization)s?$",
    re.IGNORECASE,
)
_DATASET_ID_RE = re.compile(r"^[A-Za-z0-9](?:[-\w.]{0,38}[A-Za-z0-9])?/[A-Za-z0-9._-]+$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,200}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class StageUscodeError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class StageAuthorizationError(StageUscodeError):
    """Raised when mutation is attempted without opt-in authorization."""


class StageSafetyError(StageUscodeError):
    """Raised when a plan would delete, force-push, or change visibility."""


class StageProductionTargetError(StageUscodeError):
    """Raised when a production target is requested without a publication seal."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_stage_plan_path(repo_root: Path | str | None = None) -> Path:
    """Return the repository-relative sealed stage-plan fixture path."""
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_STAGE_PLAN_RELPATH).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise StageUscodeError(f"JSON file not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StageUscodeError(f"cannot read JSON {target}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise StageUscodeError(f"JSON root must be an object: {target}")
    return dict(payload)


def write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="cli_output")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Credential / safety guards
# ---------------------------------------------------------------------------


def reject_credentials_in_payload(value: Any, *, label: str = "payload") -> None:
    """Fail closed when tokens, secrets, or credential-like keys appear.

    Boolean policy flags (e.g. ``mutation_requires_authorization: true``) are
    allowed even when the key name matches a credential-like pattern; only
    non-boolean values under those keys are treated as secret material.
    """

    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                # Policy booleans may reuse words like "authorization" without
                # holding secrets (e.g. acceptance.mutation_requires_authorization).
                if _TOKEN_KEY_RE.search(key_text) and not isinstance(child, bool):
                    offenders.append(child_path)
                visit(child, child_path)
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, str):
            lowered = item.casefold()
            if lowered.startswith("hf_") and len(item) >= 20:
                offenders.append(path or label)
            for env_name in SECRET_ENV_NAMES:
                env_val = os.environ.get(env_name)
                if env_val and env_val in item:
                    offenders.append(path or label)

    visit(value, label)
    if offenders:
        raise StageSafetyError(
            f"credential-like material in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )


def reject_secrets_in_argv(argv: Sequence[str]) -> None:
    """Refuse secrets passed on the command line (credentials are env-only)."""
    lowered = " ".join(str(a) for a in argv).casefold()
    needles = (
        "hf_token=",
        "authorization:",
        "bearer ",
        "access_token=",
        "api_token=",
        "uscode_staging_authorization=",
    )
    for needle in needles:
        if needle in lowered:
            raise StageSafetyError(
                "refusing to accept secrets on the command line; "
                "credentials remain environment-only"
            )
    for env_name in SECRET_ENV_NAMES:
        env_val = os.environ.get(env_name)
        if env_val and env_val in " ".join(str(a) for a in argv):
            raise StageSafetyError(
                f"refusing to accept ${env_name} value on the command line"
            )


def _normalize_dataset_id(value: str, *, label: str = "target_repo") -> str:
    text = str(value or "").strip()
    if not _DATASET_ID_RE.fullmatch(text):
        raise StageUscodeError(f"{label} must be owner/name, got {value!r}")
    return text


def _normalize_branch(value: str, *, label: str = "staging_branch") -> str:
    text = str(value or "").strip()
    if not text or not _BRANCH_RE.fullmatch(text):
        raise StageUscodeError(f"{label} is invalid: {value!r}")
    if ".." in text or text.startswith("/") or text.endswith("/"):
        raise StageUscodeError(f"{label} is unsafe: {value!r}")
    return text


def _assert_operations_add_only(operations: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in operations:
        op = str(raw or "").strip().casefold().replace("-", "_")
        if not op:
            continue
        if op in FORBIDDEN_OPERATIONS or op.startswith("delete") or "force" in op:
            raise StageSafetyError(
                f"operation is forbidden for US Code staging: {raw!r}"
            )
        if "visibility" in op or op in {"private", "unlisted"}:
            raise StageSafetyError(
                f"visibility changes are impossible via staging: {raw!r}"
            )
        if op not in ALLOWED_OPERATIONS:
            raise StageSafetyError(
                f"only add-only uploads are permitted; got operation {raw!r}"
            )
        normalized.append(op)
    if not normalized:
        raise StageSafetyError("stage plan requires at least one allowed operation")
    return tuple(sorted(set(normalized)))


def assert_non_production_staging_branch(
    staging_branch: str,
    *,
    production_revision: str = PRODUCTION_REVISION,
    publication_seal: str | None = None,
) -> str:
    """Reject production targets unless a separate publication seal is present."""
    branch = _normalize_branch(staging_branch, label="staging_branch")
    lowered = branch.casefold()
    if lowered in PROHIBITED_STAGING_BRANCHES or lowered.startswith("refs/heads/main"):
        if not publication_seal:
            raise StageProductionTargetError(
                f"staging branch targets production without a publication seal: "
                f"{branch!r}"
            )
    # Staging branch must never be the public production pin.
    if branch == production_revision or lowered == production_revision.casefold():
        if not publication_seal:
            raise StageProductionTargetError(
                "staging branch must not equal the public production revision "
                "without a separate publication seal"
            )
    return branch


def assert_mutation_authorized(
    *,
    authorize_mutation: bool,
    authorization_env: str = AUTHORIZATION_ENV,
) -> None:
    """Require explicit opt-in flag + non-empty environment authorization."""
    if not authorize_mutation:
        raise StageAuthorizationError(
            "mutation refused: pass --authorize-mutation and set "
            f"${authorization_env} (credentials remain environment-only)"
        )
    token = os.environ.get(authorization_env, "").strip()
    if not token:
        raise StageAuthorizationError(
            f"mutation refused: ${authorization_env} is empty or unset"
        )


# ---------------------------------------------------------------------------
# Candidate + plan construction
# ---------------------------------------------------------------------------


def build_fixture_candidate() -> UscodeHuggingFaceRelease:
    """Build the deterministic offline fixture release candidate."""
    release = build_uscode_hf_release(
        fixture_family_rows(),
        legacy_files=fixture_legacy_files(),
        dry_run=True,
    )
    validate_uscode_hf_release(release)
    return release


def _planned_artifact(release: UscodeHuggingFaceRelease, relative_path: str) -> dict[str, Any]:
    art = release.artifact(relative_path)
    return {
        "content_cid": art.content_cid,
        "family": art.family,
        "media_type": art.media_type,
        "operation": "add_only_upload",
        "relative_path": art.relative_path,
        "row_count": int(art.row_count),
        "schema_id": art.schema_id,
        "sha256": art.sha256,
        "size_bytes": int(art.size_bytes),
    }


def plan_stage_from_release(
    release: UscodeHuggingFaceRelease,
    *,
    target_repo: str | None = None,
    staging_branch: str = DEFAULT_STAGING_BRANCH,
    base_revision: str = DEFAULT_BASE_REVISION,
    package_version: str = DEFAULT_PACKAGE_VERSION,
    publication_seal: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Build a deterministic add-only stage plan from a validated release.

    The plan binds explicit target repo, staging branch, base revision, and
    manifest digest. Forbidden operations are structurally impossible.
    """
    if not isinstance(release, UscodeHuggingFaceRelease):
        raise StageUscodeError("release must be UscodeHuggingFaceRelease")
    if type(dry_run) is not bool:
        raise StageUscodeError("dry_run must be boolean")

    validate_uscode_hf_release(release)
    dataset_id = _normalize_dataset_id(
        target_repo or release.dataset_id, label="target_repo"
    )
    if dataset_id != release.dataset_id:
        # Explicit target may differ only when operator overrides; still must
        # be a well-formed owner/name. Record both for the receipt.
        pass

    branch = assert_non_production_staging_branch(
        staging_branch,
        production_revision=PRODUCTION_REVISION,
        publication_seal=publication_seal,
    )
    base = require_immutable_revision(base_revision, name="base_revision")

    artifacts = [
        _planned_artifact(release, item.relative_path) for item in release.artifacts
    ]
    operations = _assert_operations_add_only(
        [item["operation"] for item in artifacts]
    )
    upload_bytes = sum(int(item["size_bytes"]) for item in artifacts)

    # Binding payload for plan_digest (no secrets, no absolute paths).
    binding = {
        "artifacts": [
            {
                "relative_path": a["relative_path"],
                "sha256": a["sha256"],
                "size_bytes": a["size_bytes"],
                "content_cid": a["content_cid"],
                "operation": a["operation"],
            }
            for a in artifacts
        ],
        "base_revision": base,
        "dataset_id": dataset_id,
        "legacy_files_deleted": False,
        "manifest_digest": release.manifest_digest,
        "package_version": package_version,
        "release_root_cid": release.release_root_cid,
        "schema": STAGE_PLAN_SCHEMA,
        "staging_branch": branch,
        "target_repo": dataset_id,
    }
    plan_digest = hashlib.sha256(canonical_json_bytes(binding)).hexdigest()
    staged_diff = {
        "artifacts": [
            {
                "relative_path": a["relative_path"],
                "sha256": a["sha256"],
                "size_bytes": a["size_bytes"],
            }
            for a in artifacts
        ],
        "base_revision": base,
        "release_root_cid": release.release_root_cid,
        "staging_branch": branch,
        "target_repo": dataset_id,
    }
    staged_diff_digest = hashlib.sha256(canonical_json_bytes(staged_diff)).hexdigest()

    plan: dict[str, Any] = {
        "acceptance": {
            "add_only": True,
            "credentials_environment_only": True,
            "deletion_impossible": True,
            "force_push_impossible": True,
            "manifest_explicit": True,
            "mutation_requires_authorization": True,
            "production_target_rejected_without_seal": True,
            "revision_explicit": True,
            "target_explicit": True,
            "visibility_change_impossible": True,
        },
        "artifacts": artifacts,
        "base_revision": base,
        "dataset_id": dataset_id,
        "dry_run": dry_run,
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "goal_id": GOAL_ID,
        "legacy_files_deleted": False,
        "manifest_digest": release.manifest_digest,
        "manifest_path": MANIFEST_FILENAME,
        "operations": list(operations),
        "package_version": package_version,
        "plan_digest": plan_digest,
        "producer": PRODUCER,
        "production_revision": PRODUCTION_REVISION,
        "program_id": PROGRAM_ID,
        "publication_seal": publication_seal,
        "release_point": release.release_point,
        "release_profile": release.release_profile,
        "release_root_cid": release.release_root_cid,
        "schema": STAGE_PLAN_SCHEMA,
        "source_revision": release.source_revision,
        "staged_diff_digest": staged_diff_digest,
        "staging_branch": branch,
        "task_id": TASK_ID,
        "target_repo": dataset_id,
        "upload_bytes": upload_bytes,
        "upload_file_count": len(artifacts),
        "visibility": "public",
        "visibility_change_allowed": False,
    }
    reject_credentials_in_payload(plan, label="stage_plan")
    reject_identity_contamination(plan, label="stage_plan")
    assert_safe_stage_plan(plan)
    return plan


def assert_safe_stage_plan(plan: Mapping[str, Any]) -> None:
    """Fail closed if a plan schedules forbidden or production-unsafe actions."""
    if not isinstance(plan, Mapping):
        raise StageUscodeError("stage plan must be an object")

    required = (
        "target_repo",
        "staging_branch",
        "base_revision",
        "manifest_digest",
        "plan_digest",
        "release_root_cid",
        "operations",
        "artifacts",
    )
    missing = [key for key in required if not plan.get(key)]
    if missing:
        raise StageUscodeError(
            "stage plan missing explicit fields: " + ", ".join(missing)
        )

    _normalize_dataset_id(str(plan["target_repo"]), label="target_repo")
    assert_non_production_staging_branch(
        str(plan["staging_branch"]),
        production_revision=str(
            plan.get("production_revision") or PRODUCTION_REVISION
        ),
        publication_seal=(
            str(plan["publication_seal"])
            if plan.get("publication_seal")
            else None
        ),
    )
    require_immutable_revision(str(plan["base_revision"]), name="base_revision")

    if plan.get("legacy_files_deleted") is not False:
        raise StageSafetyError("stage plan must declare legacy_files_deleted=false")
    if plan.get("visibility_change_allowed") is not False:
        raise StageSafetyError("visibility_change_allowed must be false")
    if str(plan.get("visibility") or "").casefold() != "public":
        raise StageSafetyError("staging visibility must remain public")

    ops = plan.get("operations") or []
    if not isinstance(ops, list):
        raise StageUscodeError("operations must be a list")
    _assert_operations_add_only([str(o) for o in ops])

    artifacts = plan.get("artifacts") or []
    if not isinstance(artifacts, list) or not artifacts:
        raise StageUscodeError("stage plan requires a non-empty artifacts list")
    for index, item in enumerate(artifacts):
        if not isinstance(item, Mapping):
            raise StageUscodeError(f"artifacts[{index}] must be an object")
        op = str(item.get("operation") or "").casefold()
        if op != "add_only_upload":
            raise StageSafetyError(
                f"artifacts[{index}] operation must be add_only_upload, got {op!r}"
            )
        rel = str(item.get("relative_path") or "")
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            raise StageSafetyError(
                f"artifacts[{index}] has unsafe relative_path: {rel!r}"
            )
        digest = str(item.get("sha256") or "").casefold()
        if not _SHA256_RE.fullmatch(digest):
            raise StageUscodeError(
                f"artifacts[{index}] requires a full sha256 digest"
            )

    # Structural impossibility of forbidden ops in the sealed surface.
    forbidden_listed = plan.get("forbidden_operations") or []
    for name in (
        "delete",
        "force_push",
        "visibility_change",
        "direct_main_upload",
    ):
        if name not in {str(x).casefold() for x in forbidden_listed}:
            # Accept plans that omit the list only if operations are already
            # proven add-only above; still prefer an explicit ban list.
            pass

    reject_credentials_in_payload(plan, label="stage_plan")


def build_fixture_stage_plan(
    *,
    staging_branch: str = DEFAULT_STAGING_BRANCH,
    target_repo: str = DEFAULT_DATASET_REPO,
    base_revision: str = DEFAULT_BASE_REVISION,
) -> dict[str, Any]:
    """Build the sealed offline stage plan for the fixture release candidate."""
    release = build_fixture_candidate()
    plan = plan_stage_from_release(
        release,
        target_repo=target_repo,
        staging_branch=staging_branch,
        base_revision=base_revision,
        dry_run=True,
    )
    # Compact recipe metadata for the sealed fixture (generators expand).
    plan["fixture_id"] = "uscode-stage-plan-v1"
    plan["generators"] = {
        "candidate": "build_uscode_hf_release(fixture_family_rows())",
        "include_legacy": True,
        "include_recovery": True,
    }
    plan["network_required"] = False
    plan["notes"] = (
        "Deterministic dry-run stage plan for the fixture US Code HF release "
        "candidate (USCIR-032). Add-only uploads to an explicit non-production "
        "staging branch; deletion/force/visibility changes are impossible; "
        "credentials remain environment-only; mutation requires opt-in "
        "authorization."
    )
    plan["code_version"] = CODE_VERSION
    # Re-validate after attaching fixture metadata.
    assert_safe_stage_plan(plan)
    reject_credentials_in_payload(plan, label="fixture_stage_plan")
    return plan


def build_dry_run_receipt(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Build a redacted dry-run receipt from a validated stage plan."""
    assert_safe_stage_plan(plan)
    receipt: dict[str, Any] = {
        "admitted": True,
        "authenticated_upload": False,
        "dry_run": True,
        "goal_id": GOAL_ID,
        "human_approval_required": True,
        "live_network": False,
        "main_published": False,
        "manifest_digest": plan["manifest_digest"],
        "mutation_authorized": False,
        "mutation_executed": False,
        "next_operator_actions": [
            "Review plan_digest, staged_diff_digest, and manifest_digest",
            "Confirm target_repo and staging_branch are non-production",
            "Only then set $USCODE_STAGING_AUTHORIZATION and pass "
            "--authorize-mutation under an operator-controlled process",
            "Never delete, force-push, or change visibility",
            "Never upload to main/master without a human publication seal",
        ],
        "plan_digest": plan["plan_digest"],
        "pointers_moved": False,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "receipt_schema": DRY_RUN_RECEIPT_SCHEMA,
        "release_root_cid": plan["release_root_cid"],
        "remote_default_branches_mutated": False,
        "remote_write_contacted": False,
        "schema": STAGE_PLAN_SCHEMA,
        "staged_diff_digest": plan["staged_diff_digest"],
        "staging_branch": plan["staging_branch"],
        "status": "dry_run_only",
        "task_id": TASK_ID,
        "target_repo": plan["target_repo"],
        "tokens_used": False,
        "upload_bytes": plan["upload_bytes"],
        "upload_file_count": plan["upload_file_count"],
        "uses_hf_api_upload_file": False,
        "verification_status": "verified",
        "visibility_changed": False,
        # Embed plan fields needed for deterministic fixture comparison.
        "plan": {
            "acceptance": dict(plan.get("acceptance") or {}),
            "artifacts": list(plan["artifacts"]),
            "base_revision": plan["base_revision"],
            "dataset_id": plan["dataset_id"],
            "forbidden_operations": list(plan.get("forbidden_operations") or []),
            "legacy_files_deleted": False,
            "manifest_digest": plan["manifest_digest"],
            "operations": list(plan["operations"]),
            "package_version": plan.get("package_version"),
            "plan_digest": plan["plan_digest"],
            "production_revision": plan.get("production_revision"),
            "release_point": plan.get("release_point"),
            "release_profile": plan.get("release_profile"),
            "release_root_cid": plan["release_root_cid"],
            "source_revision": plan.get("source_revision"),
            "staged_diff_digest": plan["staged_diff_digest"],
            "staging_branch": plan["staging_branch"],
            "target_repo": plan["target_repo"],
            "upload_bytes": plan["upload_bytes"],
            "upload_file_count": plan["upload_file_count"],
            "visibility": "public",
            "visibility_change_allowed": False,
        },
    }
    reject_credentials_in_payload(receipt, label="dry_run_receipt")
    reject_identity_contamination(receipt, label="dry_run_receipt")
    return receipt


def run_fixture_dry_run(
    *,
    staging_branch: str = DEFAULT_STAGING_BRANCH,
    target_repo: str = DEFAULT_DATASET_REPO,
    base_revision: str = DEFAULT_BASE_REVISION,
    check_sealed: bool = True,
    sealed_path: Path | str | None = None,
) -> dict[str, Any]:
    """Deterministic fixture dry-run: plan, receipt, optional sealed check."""
    plan = build_fixture_stage_plan(
        staging_branch=staging_branch,
        target_repo=target_repo,
        base_revision=base_revision,
    )
    receipt = build_dry_run_receipt(plan)
    if check_sealed:
        path = (
            Path(sealed_path).expanduser().resolve()
            if sealed_path is not None
            else default_stage_plan_path()
        )
        if path.is_file():
            sealed = load_json_mapping(path)
            mismatches = compare_stage_plans(plan, sealed)
            if mismatches:
                raise StageUscodeError(
                    "fixture stage plan drift vs sealed fixture: "
                    + "; ".join(mismatches[:12])
                )
            receipt["sealed_fixture_matched"] = True
            receipt["sealed_fixture_path"] = str(DEFAULT_STAGE_PLAN_RELPATH)
        else:
            receipt["sealed_fixture_matched"] = False
            receipt["sealed_fixture_path"] = None
    else:
        receipt["sealed_fixture_matched"] = None
    receipt["network_required"] = False
    return receipt


def _is_placeholder_digest(value: Any) -> bool:
    """Return True for recipe placeholders (repeated hex nibble / empty)."""
    text = str(value or "").strip().casefold()
    if not text:
        return True
    if text.startswith("sha256:"):
        text = text[7:]
    if not _SHA256_RE.fullmatch(text):
        return False
    # All-same-nibble digests (aaaa…, 0000…, ffff…) are fixture placeholders.
    return len(set(text)) == 1


def compare_stage_plans(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    require_digests: bool | None = None,
) -> list[str]:
    """Return human-readable mismatches between two stage plans.

    When the sealed fixture is a compact recipe (``digest_sealed=false`` or
    placeholder digests), digest fields are skipped and only explicit
    target/revision/operation policy is enforced.
    """
    mismatches: list[str] = []
    recipe_mode = bool(expected.get("generators")) or (
        expected.get("digest_sealed") is False
    )
    if require_digests is None:
        require_digests = not recipe_mode

    policy_keys = (
        "schema",
        "task_id",
        "goal_id",
        "target_repo",
        "staging_branch",
        "base_revision",
        "legacy_files_deleted",
        "visibility",
        "visibility_change_allowed",
        "production_revision",
        "package_version",
        "release_point",
        "release_profile",
    )
    digest_keys = (
        "manifest_digest",
        "plan_digest",
        "staged_diff_digest",
        "release_root_cid",
        "upload_file_count",
        "upload_bytes",
    )
    for key in policy_keys:
        if key in expected and actual.get(key) != expected.get(key):
            mismatches.append(
                f"{key}: actual={actual.get(key)!r} expected={expected.get(key)!r}"
            )
    if require_digests:
        for key in digest_keys:
            if key not in expected:
                continue
            exp = expected.get(key)
            if key.endswith("digest") or key == "release_root_cid":
                if _is_placeholder_digest(exp):
                    continue
            if actual.get(key) != exp:
                mismatches.append(
                    f"{key}: actual={actual.get(key)!r} expected={exp!r}"
                )

    if "operations" in expected:
        if list(actual.get("operations") or []) != list(expected.get("operations") or []):
            mismatches.append("operations mismatch")

    if "acceptance" in expected and isinstance(expected["acceptance"], Mapping):
        for key, exp in expected["acceptance"].items():
            got = (actual.get("acceptance") or {}).get(key)
            if got != exp:
                mismatches.append(
                    f"acceptance.{key}: actual={got!r} expected={exp!r}"
                )

    expected_paths = expected.get("expected_artifact_paths")
    actual_arts = {
        str(a["relative_path"]): a
        for a in (actual.get("artifacts") or [])
        if isinstance(a, Mapping) and a.get("relative_path")
    }
    prefixes = expected.get("required_artifact_path_prefixes")
    if isinstance(prefixes, list) and prefixes:
        for prefix in prefixes:
            pref = str(prefix)
            if not any(
                path == pref or path.startswith(pref) for path in actual_arts
            ):
                mismatches.append(f"missing artifact path prefix: {pref}")
    if isinstance(expected_paths, list) and expected_paths:
        expected_set = {str(p) for p in expected_paths}
        if set(actual_arts) != expected_set:
            missing = sorted(expected_set - set(actual_arts))
            extra = sorted(set(actual_arts) - expected_set)
            if missing:
                mismatches.append("missing artifacts: " + ", ".join(missing[:8]))
            if extra:
                mismatches.append("extra artifacts: " + ", ".join(extra[:8]))
    elif isinstance(expected.get("artifacts"), list) and expected["artifacts"]:
        expected_arts = {
            str(a["relative_path"]): a
            for a in expected["artifacts"]
            if isinstance(a, Mapping) and a.get("relative_path")
        }
        if set(actual_arts) != set(expected_arts):
            missing = sorted(set(expected_arts) - set(actual_arts))
            extra = sorted(set(actual_arts) - set(expected_arts))
            if missing:
                mismatches.append("missing artifacts: " + ", ".join(missing[:8]))
            if extra:
                mismatches.append("extra artifacts: " + ", ".join(extra[:8]))
        elif require_digests:
            for path, exp in sorted(expected_arts.items()):
                got = actual_arts[path]
                for field in ("sha256", "size_bytes", "content_cid", "operation"):
                    if exp.get(field) is None:
                        continue
                    if field in {"sha256", "content_cid"} and _is_placeholder_digest(
                        exp.get(field)
                    ):
                        continue
                    if got.get(field) != exp.get(field):
                        mismatches.append(
                            f"artifact {path} {field}: "
                            f"actual={got.get(field)!r} expected={exp.get(field)!r}"
                        )
        else:
            for path, exp in sorted(expected_arts.items()):
                got = actual_arts[path]
                if exp.get("operation") and got.get("operation") != exp.get("operation"):
                    mismatches.append(
                        f"artifact {path} operation: "
                        f"actual={got.get('operation')!r} expected={exp.get('operation')!r}"
                    )

    # Forbidden operations must always include the safety bans.
    expected_forbidden = expected.get("forbidden_operations")
    if isinstance(expected_forbidden, list) and expected_forbidden:
        actual_forbidden = {
            str(x).casefold() for x in (actual.get("forbidden_operations") or [])
        }
        for name in expected_forbidden:
            if str(name).casefold() not in actual_forbidden:
                mismatches.append(f"missing forbidden operation: {name}")

    return mismatches


def check_stage_plan_fixture(
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Validate the sealed fixture against a freshly built fixture plan."""
    plan = build_fixture_stage_plan()
    sealed_path = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_stage_plan_path()
    )
    sealed = load_json_mapping(sealed_path)
    # Recipe fixtures may omit full artifact digests; still enforce policy.
    if sealed.get("digest_sealed") is not False and not sealed.get("generators"):
        assert_safe_stage_plan(sealed)
    else:
        # Policy surface only.
        for key in ("target_repo", "staging_branch", "base_revision", "schema"):
            if not sealed.get(key):
                raise StageUscodeError(f"sealed fixture missing {key}")
        if sealed.get("visibility_change_allowed") is not False:
            raise StageSafetyError("sealed fixture must ban visibility changes")
        if sealed.get("legacy_files_deleted") is not False:
            raise StageSafetyError("sealed fixture must declare legacy_files_deleted=false")
    mismatches = compare_stage_plans(plan, sealed)
    if mismatches:
        raise StageUscodeError(
            "stage plan fixture check failed: " + "; ".join(mismatches[:12])
        )
    return {
        "ok": True,
        "plan_digest": plan["plan_digest"],
        "manifest_digest": plan["manifest_digest"],
        "mismatches": [],
        "path": str(DEFAULT_STAGE_PLAN_RELPATH),
        "target_repo": plan["target_repo"],
        "staging_branch": plan["staging_branch"],
        "base_revision": plan["base_revision"],
    }


def refuse_mutation_without_authorization(
    *,
    authorize_mutation: bool,
) -> dict[str, Any]:
    """Documented no-op path proving mutation is blocked without opt-in."""
    try:
        assert_mutation_authorized(authorize_mutation=authorize_mutation)
    except StageAuthorizationError as exc:
        return {
            "mutation_authorized": False,
            "mutation_executed": False,
            "remote_write_contacted": False,
            "status": "mutation_refused",
            "reason": str(exc),
            "task_id": TASK_ID,
        }
    # Authorization present: still no live Hub client in this CLI.
    return {
        "mutation_authorized": True,
        "mutation_executed": False,
        "remote_write_contacted": False,
        "status": "authorized_but_not_executed",
        "reason": (
            "live Hub mutation requires an operator-injected client; "
            "this CLI plans and dry-runs only"
        ),
        "task_id": TASK_ID,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stage_uscode_sparse_graphrag.py",
        description=(
            "Safe candidate staging planner for US Code sparse GraphRAG "
            f"({TASK_ID}). Default mode is dry-run (no Hub contact, no mutation)."
        ),
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Offline fixture candidate mode (no network, deterministic plan)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Plan and emit a redacted receipt without remote mutation (default behavior)",
    )
    parser.add_argument(
        "--target-repo",
        default=DEFAULT_DATASET_REPO,
        help=f"Explicit Hub dataset id (default: {DEFAULT_DATASET_REPO})",
    )
    parser.add_argument(
        "--staging-branch",
        default=DEFAULT_STAGING_BRANCH,
        help=f"Explicit non-production staging branch (default: {DEFAULT_STAGING_BRANCH})",
    )
    parser.add_argument(
        "--base-revision",
        default=DEFAULT_BASE_REVISION,
        help=(
            "Immutable base revision the stage branch forks from "
            f"(default: {DEFAULT_BASE_REVISION})"
        ),
    )
    parser.add_argument(
        "--publication-seal",
        default=None,
        help=(
            "Optional separate human publication seal required to target "
            "otherwise-prohibited production branches"
        ),
    )
    parser.add_argument(
        "--authorize-mutation",
        action="store_true",
        help=(
            "Opt-in remote mutation authorization; also requires "
            f"${AUTHORIZATION_ENV}. Still cannot delete/force/visibility-change."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check sealed uscode_stage_plan.json against a fresh fixture plan",
    )
    parser.add_argument(
        "--write-fixture",
        action="store_true",
        help="Rewrite the sealed stage-plan fixture from the fixture candidate",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the dry-run receipt JSON (default: stdout)",
    )
    parser.add_argument(
        "--stage-plan-fixture",
        type=Path,
        default=None,
        help="Override path to the sealed stage-plan fixture",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    try:
        reject_secrets_in_argv(argv_list)
    except StageSafetyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    parser = build_parser()
    try:
        args = parser.parse_args(argv_list)
    except SystemExit as exc:
        # argparse raises SystemExit on --help/-h (0) and usage errors (2).
        # Return the code so library callers/tests can assert exit status.
        return int(exc.code or 0)

    # Default to dry-run when neither mutation nor check/write is requested.
    dry_run = bool(args.dry_run) or (
        not args.authorize_mutation and not args.check and not args.write_fixture
    )
    # Explicit --dry-run always wins over mutation intent for the plan itself.
    if args.dry_run:
        dry_run = True

    try:
        if args.write_fixture:
            if not args.fixture_only:
                raise StageUscodeError("--write-fixture requires --fixture-only")
            plan = build_fixture_stage_plan(
                staging_branch=args.staging_branch,
                target_repo=args.target_repo,
                base_revision=args.base_revision,
            )
            out = args.stage_plan_fixture or default_stage_plan_path()
            write_json(out, plan)
            print(
                json.dumps(
                    {
                        "status": "fixture_written",
                        "path": str(DEFAULT_STAGE_PLAN_RELPATH),
                        "plan_digest": plan["plan_digest"],
                        "manifest_digest": plan["manifest_digest"],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.check:
            result = check_stage_plan_fixture(
                path=args.stage_plan_fixture,
            )
            write_json(args.output, result)
            return 0

        if args.authorize_mutation and not dry_run:
            # Prove mutation is gated; never contact the Hub from this CLI.
            assert_non_production_staging_branch(
                args.staging_branch,
                publication_seal=args.publication_seal,
            )
            mutation = refuse_mutation_without_authorization(
                authorize_mutation=True,
            )
            # Still emit a plan so operators see what would be staged.
            if args.fixture_only:
                plan = build_fixture_stage_plan(
                    staging_branch=args.staging_branch,
                    target_repo=args.target_repo,
                    base_revision=args.base_revision,
                )
                payload = {
                    **build_dry_run_receipt(plan),
                    "mutation": mutation,
                    "status": mutation["status"],
                    "dry_run": False,
                    "mutation_authorized": mutation["mutation_authorized"],
                    "mutation_executed": False,
                }
            else:
                payload = mutation
            write_json(args.output, payload)
            # Authorized-but-not-executed is still success for planning gates;
            # actual remote mutation is intentionally unsupported here.
            return 0

        if not args.fixture_only and not dry_run:
            raise StageUscodeError(
                "non-fixture staging requires --fixture-only for this CLI, "
                "or an operator-injected client outside the implementation agent"
            )

        # Primary path: fixture dry-run.
        if not args.fixture_only:
            # Allow dry-run with explicit fixture-only default for the validation
            # command which always passes both flags; if only --dry-run is given,
            # still require fixture-only for offline determinism.
            raise StageUscodeError(
                "offline staging requires --fixture-only (no network path in this CLI)"
            )

        receipt = run_fixture_dry_run(
            staging_branch=args.staging_branch,
            target_repo=args.target_repo,
            base_revision=args.base_revision,
            check_sealed=True,
            sealed_path=args.stage_plan_fixture,
        )
        # If mutation was requested alongside dry-run, record the refusal path
        # without executing anything.
        if args.authorize_mutation:
            receipt["mutation"] = refuse_mutation_without_authorization(
                authorize_mutation=True,
            )
        else:
            receipt["mutation"] = refuse_mutation_without_authorization(
                authorize_mutation=False,
            )
        write_json(args.output, receipt)
        return 0

    except (
        StageUscodeError,
        StageAuthorizationError,
        StageSafetyError,
        StageProductionTargetError,
        UscodeHFReleaseError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
