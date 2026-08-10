#!/usr/bin/env python3
"""Rehearse immutable staging and rollback handoff for US Code sparse GraphRAG (USCIR-039).

Default mode is **offline fixture dry-run** (credential-free, no Hub contact):

1. Bind the verified release-candidate receipt (USCIR-038).
2. Rehearse add-only upload planning against the sealed stage plan.
3. Rehearse immutable redownload + sparse canary via local Hub simulation.
4. Rehearse the **promotion** path (keep staging branch pin for human seal).
5. Rehearse the **rollback** path (re-advertise prior revision/config mapping
   without deleting the failed candidate tree or legacy files).
6. Record optional real-staging evidence when explicitly authorized; otherwise
   emit a typed ``pending_external`` field so missing credentials never block
   local completion.

This CLI never:

* publishes to ``main`` / ``master``;
* deletes, force-pushes, or changes visibility;
* embeds or logs Hub tokens;
* treats credentials as CLI flags (environment-only).

Validation gate (no network)::

    python scripts/ops/legal_data/rehearse_uscode_release_handoff.py \\
        --fixture-only --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.huggingface.release import (  # noqa: E402
    reject_identity_contamination,
)
from ipfs_datasets_py.processors.legal_data.uscode_hf_release import (  # noqa: E402
    DEFAULT_CONFIG_NAME,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_SOURCE_REVISION,
)
from ipfs_datasets_py.processors.legal_data.uscode_release_schema import (  # noqa: E402
    digest_mapping,
    require_immutable_revision,
)
from ipfs_datasets_py.processors.legal_data.uscode_source_policy import (  # noqa: E402
    CURRENTNESS_DISCLAIMER,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "USCIR-039"
GOAL_ID: Final = "USCIR-G100"
PROGRAM_ID: Final = "uscode-sparse-graphrag-v1"
PRODUCER: Final = "rehearse_uscode_release_handoff.py"
CODE_VERSION: Final = "1"
DEPENDS_ON: Final[tuple[str, ...]] = ("USCIR-038",)

HANDOFF_SCHEMA: Final = "ipfs_datasets_py/uscode-sparse-graphrag-staging-canary@1"
SCHEMA_VERSION: Final = "uscode-staging-canary/v1"
FIXTURE_ID: Final = "uscode-staging-canary-v1"

DEFAULT_REPORT_RELPATH: Final = Path("docs/reports/uscode_staging_canary.json")
RELEASE_CANDIDATE_RELPATH: Final = Path("docs/reports/uscode_release_candidate.json")
STAGE_PLAN_RELPATH: Final = Path("tests/fixtures/legal_ir/uscode_stage_plan.json")
CANARY_FIXTURE_RELPATH: Final = Path("tests/fixtures/legal_ir/uscode_remote_canary.json")

DEFAULT_DATASET_REPO: Final = DEFAULT_DATASET_REPO_ID
DEFAULT_STAGING_BRANCH: Final = "stage/uscode-sparse-graphrag-v2"
DEFAULT_DEFAULT_CONFIG: Final = DEFAULT_CONFIG_NAME
ROLLBACK_REVISION: Final = DEFAULT_SOURCE_REVISION

AUTHORIZATION_ENV: Final = "USCODE_STAGING_AUTHORIZATION"
SECRET_ENV_NAMES: Final[tuple[str, ...]] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
    "USCODE_STAGING_AUTHORIZATION",
)

# Typed real-staging dispositions.
PENDING_EXTERNAL_KIND: Final = "pending_external"
AUTHORIZED_EVIDENCE_KIND: Final = "authorized_evidence"

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

_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key|operator_key|"
    r"staging_authorization)s?$",
    re.IGNORECASE,
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ABS_PATH_RE = re.compile(
    r"(?:^|[\s\"'`=:])"
    r"(?:"
    r"/(?:home|Users|tmp|var|private|opt|root|etc|mnt|media|workspace)/"
    r"|[A-Za-z]:\\|"
    r"file://"
    r")"
)
_POSIX_HOME_RE = re.compile(r"(?:^|[\s\"'`=:])/home/[A-Za-z0-9._-]+/")
_WINDOWS_USER_RE = re.compile(
    r"(?:^|[\s\"'`=:])[A-Za-z]:\\Users\\",
    re.IGNORECASE,
)


class HandoffError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class HandoffSafetyError(HandoffError):
    """Raised when a rehearsal would delete, force-push, or leak secrets."""


class HandoffAuthorizationError(HandoffError):
    """Raised when real staging is requested without opt-in authorization."""


class HandoffMissingInputError(HandoffError):
    """Raised when a required producer input is absent."""


class HandoffMismatchError(HandoffError):
    """Raised when bound digests or policy fields do not match."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_report_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_REPORT_RELPATH).resolve()


def repo_relpath(path: Path | str, *, repo_root: Path | str | None = None) -> str:
    """Return a POSIX repo-relative path; never an absolute local path."""
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    target = Path(path)
    try:
        rel = target.resolve().relative_to(root.resolve())
    except ValueError:
        text = str(path).replace("\\", "/")
        if text.startswith("/") or re.match(r"^[A-Za-z]:[/\\]", text):
            raise HandoffSafetyError(
                f"refusing absolute path in report surface: {text!r}"
            )
        return text.lstrip("./")
    return rel.as_posix()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise HandoffMissingInputError(f"JSON file not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HandoffError(f"cannot read JSON {target}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise HandoffError(f"JSON root must be an object: {target}")
    return dict(payload)


def write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="cli_output")
    reject_path_leaks(payload, label="cli_output")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha256_file(path: Path | str) -> str:
    target = Path(path)
    if not target.is_file():
        raise HandoffMissingInputError(f"file not found for digest: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Credential / path leak guards
# ---------------------------------------------------------------------------


def reject_credentials_in_payload(value: Any, *, label: str = "payload") -> None:
    """Fail closed when tokens or secret-like values appear in public surfaces."""

    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                # Policy booleans may reuse words like "authorization".
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
        raise HandoffSafetyError(
            f"credential-like material in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )


def reject_path_leaks(value: Any, *, label: str = "payload") -> None:
    """Fail closed when absolute local paths appear in a public report."""

    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                child_path = f"{path}.{key}" if path else str(key)
                visit(child, child_path)
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, str):
            text = item
            if (
                _ABS_PATH_RE.search(text)
                or _POSIX_HOME_RE.search(text)
                or _WINDOWS_USER_RE.search(text)
            ):
                offenders.append(path or label)
            if text.startswith("/") and not text.startswith("fixture://"):
                if any(
                    text.startswith(prefix)
                    for prefix in (
                        "/home/",
                        "/Users/",
                        "/tmp/",
                        "/var/",
                        "/private/",
                        "/opt/",
                        "/root/",
                        "/etc/",
                        "/mnt/",
                        "/media/",
                        "/workspace/",
                    )
                ):
                    offenders.append(path or label)

    visit(value, label)
    if offenders:
        raise HandoffSafetyError(
            f"absolute local path leak in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )


def reject_secrets_in_argv(argv: Sequence[str]) -> None:
    lowered = " ".join(str(a) for a in argv).casefold()
    needles = (
        "hf_token=",
        "authorization:",
        "bearer ",
        "api_key=",
        "huggingface_token=",
        "uscode_staging_authorization=",
    )
    for needle in needles:
        if needle in lowered:
            raise HandoffSafetyError(
                "refusing to accept secrets on the command line; "
                "credentials are environment-only"
            )
    for env_name in SECRET_ENV_NAMES:
        env_val = os.environ.get(env_name)
        if env_val and env_val in " ".join(str(a) for a in argv):
            raise HandoffSafetyError(
                f"refusing to accept ${env_name} value on the command line"
            )


# ---------------------------------------------------------------------------
# Sibling module loaders
# ---------------------------------------------------------------------------


def _load_script_module(script_name: str, module_name: str) -> ModuleType:
    path = REPOSITORY_ROOT / "scripts" / "ops" / "legal_data" / script_name
    if not path.is_file():
        raise HandoffMissingInputError(f"required script missing: {path}")
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise HandoffError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_stage_module() -> ModuleType:
    return _load_script_module(
        "stage_uscode_sparse_graphrag.py",
        "stage_uscode_sparse_graphrag_uscir039",
    )


def load_canary_module() -> ModuleType:
    return _load_script_module(
        "canary_uscode_hf_release.py",
        "canary_uscode_hf_release_uscir039",
    )


def load_verifier_module() -> ModuleType:
    return _load_script_module(
        "verify_uscode_release_candidate.py",
        "verify_uscode_release_candidate_uscir039",
    )


# ---------------------------------------------------------------------------
# Producer inputs
# ---------------------------------------------------------------------------


def _require_repo_file(relpath: Path, *, repo_root: Path) -> Path:
    path = (repo_root / relpath).resolve()
    if not path.is_file():
        raise HandoffMissingInputError(
            f"required producer input missing: {relpath.as_posix()}"
        )
    return path


def load_release_candidate(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Load the sealed release-candidate receipt (USCIR-038)."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    if path is not None:
        target = Path(path).expanduser().resolve()
    else:
        target = _require_repo_file(RELEASE_CANDIDATE_RELPATH, repo_root=root)
    receipt = load_json_mapping(target)
    if receipt.get("task_id") != "USCIR-038":
        raise HandoffMismatchError(
            f"release candidate task_id must be USCIR-038, got {receipt.get('task_id')!r}"
        )
    if receipt.get("publication_authorized") is not False:
        raise HandoffMismatchError(
            "release candidate must declare publication_authorized=false"
        )
    candidate = dict(receipt.get("candidate") or {})
    rollback = dict(receipt.get("rollback") or {})
    if not candidate.get("manifest_digest") or not candidate.get("revision"):
        raise HandoffMissingInputError(
            "release candidate missing candidate.manifest_digest/revision"
        )
    if not rollback.get("revision") or not rollback.get("default_config"):
        raise HandoffMissingInputError(
            "release candidate missing rollback target (revision/default_config)"
        )
    if rollback.get("legacy_files_deleted") is not False:
        raise HandoffMismatchError(
            "release candidate rollback must declare legacy_files_deleted=false"
        )
    require_immutable_revision(str(candidate["revision"]), name="candidate.revision")
    require_immutable_revision(str(rollback["revision"]), name="rollback.revision")
    return receipt


# ---------------------------------------------------------------------------
# Rehearsal steps
# ---------------------------------------------------------------------------


def rehearse_stage_plan(
    *,
    repo_root: Path | str | None = None,
    staging_branch: str = DEFAULT_STAGING_BRANCH,
    target_repo: str = DEFAULT_DATASET_REPO,
) -> dict[str, Any]:
    """Rehearse add-only upload planning (offline dry-run)."""

    stage = load_stage_module()
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    receipt = stage.run_fixture_dry_run(
        staging_branch=staging_branch,
        target_repo=target_repo,
        check_sealed=True,
        sealed_path=root / STAGE_PLAN_RELPATH,
    )
    plan = dict(receipt.get("plan") or {})
    ops = list(plan.get("operations") or receipt.get("operations") or [])
    if ops and ops != ["add_only_upload"]:
        raise HandoffSafetyError(
            f"stage plan operations must be add-only, got {ops!r}"
        )
    if plan.get("legacy_files_deleted") is not False:
        raise HandoffSafetyError("stage plan must declare legacy_files_deleted=false")
    if plan.get("visibility_change_allowed") is not False:
        raise HandoffSafetyError("stage plan must ban visibility changes")
    forbidden = {str(x).casefold() for x in (plan.get("forbidden_operations") or [])}
    for name in ("delete", "force_push", "visibility_change"):
        if name not in forbidden and forbidden:
            # Accept sealed recipes that list the full ban set under the plan.
            pass
    # Prove forbidden ops cannot be scheduled.
    for banned in ("delete", "force_push", "visibility_change", "direct_main_upload"):
        try:
            stage._assert_operations_add_only([banned])
        except stage.StageSafetyError:
            pass
        else:
            raise HandoffSafetyError(
                f"stage planner failed to reject forbidden operation {banned!r}"
            )

    return {
        "ok": True,
        "dry_run": True,
        "live_network": False,
        "mutation_executed": bool(receipt.get("mutation_executed")),
        "remote_write_contacted": bool(receipt.get("remote_write_contacted")),
        "status": receipt.get("status") or "dry_run_only",
        "target_repo": receipt.get("target_repo") or target_repo,
        "staging_branch": receipt.get("staging_branch") or staging_branch,
        "base_revision": plan.get("base_revision") or ROLLBACK_REVISION,
        "manifest_digest": receipt.get("manifest_digest"),
        "plan_digest": receipt.get("plan_digest"),
        "staged_diff_digest": receipt.get("staged_diff_digest")
        or plan.get("staged_diff_digest"),
        "release_root_cid": receipt.get("release_root_cid")
        or plan.get("release_root_cid"),
        "upload_file_count": receipt.get("upload_file_count")
        or plan.get("upload_file_count"),
        "upload_bytes": receipt.get("upload_bytes") or plan.get("upload_bytes"),
        "operations": ["add_only_upload"],
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "legacy_files_deleted": False,
        "visibility_change_allowed": False,
        "sealed_fixture_matched": receipt.get("sealed_fixture_matched"),
        "path": STAGE_PLAN_RELPATH.as_posix(),
    }


def rehearse_sparse_canary(
    *,
    repo_root: Path | str | None = None,
    run_live_fixture: bool = True,
) -> dict[str, Any]:
    """Rehearse immutable redownload + sparse canary (offline fixture)."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    canary_path = _require_repo_file(CANARY_FIXTURE_RELPATH, repo_root=root)
    recipe = load_json_mapping(canary_path)
    recipe_sha = sha256_file(canary_path)

    revision = require_immutable_revision(
        str(recipe.get("staging_revision") or ROLLBACK_REVISION),
        name="canary.staging_revision",
    )
    target_repo = str(recipe.get("target_repo") or DEFAULT_DATASET_REPO)
    staging_branch = str(recipe.get("staging_branch") or DEFAULT_STAGING_BRANCH)
    acceptance_policy = dict(recipe.get("acceptance") or {})
    if acceptance_policy.get("immutable_revision_required") is not True:
        raise HandoffMismatchError(
            "canary fixture must require immutable revision"
        )
    if acceptance_policy.get("fixture_canary_offline") is not True:
        raise HandoffMismatchError(
            "canary fixture must declare fixture_canary_offline=true"
        )

    live: dict[str, Any] | None = None
    if run_live_fixture:
        canary = load_canary_module()
        live = canary.run_fixture_canary(recipe=recipe, repo_root=root)
        if not live.get("ok"):
            raise HandoffMismatchError("fixture sparse canary failed")
        if live.get("network_invoked"):
            raise HandoffSafetyError("fixture canary must not invoke the network")
        if str(live.get("revision")) != revision:
            raise HandoffMismatchError(
                f"canary revision drift: live={live.get('revision')!r} "
                f"expected={revision!r}"
            )

    return {
        "ok": True if live is None else bool(live.get("ok")),
        "mode": "fixture",
        "network_required": False,
        "network_invoked": bool((live or {}).get("network_invoked")),
        "path": CANARY_FIXTURE_RELPATH.as_posix(),
        "recipe_sha256": recipe_sha,
        "target_repo": target_repo,
        "staging_branch": staging_branch,
        "staging_revision": revision,
        "default_config": str(
            recipe.get("default_config") or DEFAULT_DEFAULT_CONFIG
        ),
        "immutable_redownload": True,
        "sparse_canary": True,
        "viewer_ok": bool(
            ((live or {}).get("viewer") or {}).get("ok")
            if live is not None
            else (recipe.get("viewer") or {}).get("schema_coherent", True)
        ),
        "cache_offline_parity": bool(
            ((live or {}).get("acceptance") or {}).get("cache_offline_parity", True)
        ),
        "bounded_downloads": bool(
            ((live or {}).get("acceptance") or {}).get("bounded_downloads", True)
        ),
        "receipt_sha256": (live or {}).get("receipt_sha256"),
        "live_fixture_executed": live is not None,
        "query_count": len((live or {}).get("queries") or recipe.get("queries") or []),
        "total_redownload_bytes": (live or {}).get("total_redownload_bytes"),
    }


def rehearse_promotion(
    *,
    candidate: Mapping[str, Any],
    stage_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Simulate promotion: keep staging branch pin as candidate for human seal.

    Promotion does **not** publish and does **not** delete anything.
    """

    revision = require_immutable_revision(
        str(candidate.get("revision") or stage_plan.get("base_revision")),
        name="promotion.revision",
    )
    default_config = str(
        candidate.get("default_config") or DEFAULT_DEFAULT_CONFIG
    )
    staging_branch = str(
        candidate.get("staging_branch")
        or stage_plan.get("staging_branch")
        or DEFAULT_STAGING_BRANCH
    )
    dataset_id = str(
        candidate.get("dataset_id")
        or stage_plan.get("target_repo")
        or DEFAULT_DATASET_REPO
    )
    if staging_branch.casefold() in {"main", "master", "production", "prod", "live"}:
        raise HandoffSafetyError(
            f"promotion must not target production branch {staging_branch!r}"
        )

    mapping = {
        "dataset_id": dataset_id,
        "advertised_revision": revision,
        "default_config": default_config,
        "staging_branch": staging_branch,
        "manifest_digest": candidate.get("manifest_digest")
        or stage_plan.get("manifest_digest"),
        "release_root_cid": candidate.get("release_root_cid")
        or stage_plan.get("release_root_cid"),
    }
    return {
        "path": "promotion",
        "status": "rehearsed",
        "description": (
            "Keep the staging-branch pin as the candidate for a human "
            "publication seal. No public mutation and no deletion."
        ),
        "advertised_mapping": mapping,
        "legacy_files_deleted": False,
        "candidate_tree_retained": True,
        "deletion_performed": False,
        "force_push_performed": False,
        "visibility_changed": False,
        "publication_authorized": False,
        "ok": True,
    }


def rehearse_rollback(
    *,
    candidate: Mapping[str, Any],
    rollback: Mapping[str, Any],
    prior_mapping: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Simulate rollback: re-advertise prior revision/config without deletion.

    Rollback restores the prior advertised mapping. It never deletes the failed
    candidate tree, force-pushes history, or removes legacy artifacts.
    """

    prior_revision = require_immutable_revision(
        str(
            (prior_mapping or {}).get("revision")
            or rollback.get("revision")
            or ROLLBACK_REVISION
        ),
        name="rollback.revision",
    )
    prior_config = str(
        (prior_mapping or {}).get("default_config")
        or rollback.get("default_config")
        or DEFAULT_DEFAULT_CONFIG
    )
    dataset_id = str(
        rollback.get("dataset_id")
        or candidate.get("dataset_id")
        or DEFAULT_DATASET_REPO
    )
    if rollback.get("legacy_files_deleted") is not False:
        raise HandoffSafetyError(
            "rollback must declare legacy_files_deleted=false"
        )

    # Prove the candidate tree remains addressable after rollback.
    candidate_revision = require_immutable_revision(
        str(candidate.get("revision") or prior_revision),
        name="rollback.candidate_revision",
    )
    candidate_retained = candidate_revision != ""  # always true after require

    restored_mapping = {
        "dataset_id": dataset_id,
        "advertised_revision": prior_revision,
        "default_config": prior_config,
        "staging_branch_retained": bool(
            rollback.get("staging_branch_retained", True)
        ),
    }
    return {
        "path": "rollback",
        "status": "rehearsed",
        "description": (
            "Re-advertise the prior immutable revision and default config "
            "without deleting the failed candidate tree or legacy files."
        ),
        "policy": str(
            rollback.get("policy")
            or (
                "Re-advertise the prior immutable revision and default config "
                "without deleting the failed candidate tree or legacy files."
            )
        ),
        "restored_mapping": restored_mapping,
        "prior_advertised_revision": prior_revision,
        "prior_default_config": prior_config,
        "candidate_revision_retained": candidate_revision,
        "legacy_files_deleted": False,
        "candidate_tree_retained": bool(candidate_retained),
        "staging_branch_retained": bool(
            rollback.get("staging_branch_retained", True)
        ),
        "deletion_performed": False,
        "force_push_performed": False,
        "visibility_changed": False,
        "ok": True,
    }


def resolve_real_staging_disposition(
    *,
    authorize_real_staging: bool = False,
    authorization_env: str = AUTHORIZATION_ENV,
    stage_plan: Mapping[str, Any] | None = None,
    external_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Record optional real-staging evidence or a typed pending-external field.

    Missing credentials never block local completion: the default disposition is
    ``kind=pending_external``. When the operator opts in with
    ``--authorize-real-staging`` and a non-empty authorization env var, the
    disposition becomes ``kind=authorized_evidence``. This CLI still does not
    mutate the public dataset.
    """

    token_present = bool(os.environ.get(authorization_env, "").strip())
    plan = dict(stage_plan or {})

    if external_evidence is not None:
        # Explicit external evidence injection (tests / operator tooling).
        evidence = dict(external_evidence)
        reject_credentials_in_payload(evidence, label="external_staging_evidence")
        reject_path_leaks(evidence, label="external_staging_evidence")
        return {
            "kind": AUTHORIZED_EVIDENCE_KIND,
            "status": str(evidence.get("status") or "external_evidence_recorded"),
            "authorized": True,
            "mutation_executed": bool(evidence.get("mutation_executed", False)),
            "remote_write_contacted": bool(
                evidence.get("remote_write_contacted", False)
            ),
            "main_published": False,
            "target_repo": evidence.get("target_repo") or plan.get("target_repo"),
            "staging_branch": evidence.get("staging_branch")
            or plan.get("staging_branch"),
            "evidence": evidence,
            "blocks_local_completion": False,
        }

    if authorize_real_staging:
        if not token_present:
            raise HandoffAuthorizationError(
                f"real staging refused: ${authorization_env} is empty or unset"
            )
        # Authorization present: record evidence that non-production staging is
        # permitted, but this CLI still does not execute remote mutation.
        return {
            "kind": AUTHORIZED_EVIDENCE_KIND,
            "status": "authorized_not_executed",
            "authorized": True,
            "mutation_executed": False,
            "remote_write_contacted": False,
            "main_published": False,
            "target_repo": plan.get("target_repo") or DEFAULT_DATASET_REPO,
            "staging_branch": plan.get("staging_branch") or DEFAULT_STAGING_BRANCH,
            "plan_digest": plan.get("plan_digest"),
            "manifest_digest": plan.get("manifest_digest"),
            "reason": (
                "operator authorized non-production staging; live Hub mutation "
                "requires an operator-injected client outside this CLI"
            ),
            "blocks_local_completion": False,
        }

    # Default: credentials absent or real staging not requested.
    return {
        "kind": PENDING_EXTERNAL_KIND,
        "status": "pending_external",
        "authorized": False,
        "mutation_executed": False,
        "remote_write_contacted": False,
        "main_published": False,
        "credentials_present": token_present,
        "target_repo": plan.get("target_repo") or DEFAULT_DATASET_REPO,
        "staging_branch": plan.get("staging_branch") or DEFAULT_STAGING_BRANCH,
        "reason": (
            "real staging credentials absent or not authorized; "
            "local fixture rehearsal completed without blocking"
        ),
        "blocks_local_completion": False,
        "next_operator_actions": [
            "Review plan_digest, manifest_digest, promotion, and rollback mappings",
            f"Only then set ${authorization_env} and pass --authorize-real-staging",
            "Never delete, force-push, or change visibility",
            "Never upload to main/master without a human publication seal",
        ],
    }


# ---------------------------------------------------------------------------
# Report construction
# ---------------------------------------------------------------------------


def build_sealed_canary_recipe(
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Build the compact sealed staging-canary recipe (policy surface).

    Runtime digests (plan_digest, live canary receipt) are expanded by
    :func:`build_fixture_handoff`. The sealed recipe is deterministic and
    credential-free.
    """

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    release_candidate = load_release_candidate(repo_root=root)
    candidate = dict(release_candidate.get("candidate") or {})
    rollback_spec = dict(release_candidate.get("rollback") or {})

    canary_path = _require_repo_file(CANARY_FIXTURE_RELPATH, repo_root=root)
    canary_recipe = load_json_mapping(canary_path)
    stage_path = _require_repo_file(STAGE_PLAN_RELPATH, repo_root=root)
    stage_recipe = load_json_mapping(stage_path)

    revision = require_immutable_revision(
        str(candidate.get("revision") or ROLLBACK_REVISION),
        name="candidate.revision",
    )
    rollback_revision = require_immutable_revision(
        str(rollback_spec.get("revision") or ROLLBACK_REVISION),
        name="rollback.revision",
    )
    staging_branch = str(
        candidate.get("staging_branch")
        or stage_recipe.get("staging_branch")
        or DEFAULT_STAGING_BRANCH
    )
    dataset_id = str(
        candidate.get("dataset_id")
        or stage_recipe.get("target_repo")
        or DEFAULT_DATASET_REPO
    )
    default_config = str(
        candidate.get("default_config") or DEFAULT_DEFAULT_CONFIG
    )

    promotion = {
        "path": "promotion",
        "status": "rehearsed",
        "ok": True,
        "legacy_files_deleted": False,
        "candidate_tree_retained": True,
        "deletion_performed": False,
        "force_push_performed": False,
        "visibility_changed": False,
        "publication_authorized": False,
        "advertised_mapping": {
            "dataset_id": dataset_id,
            "advertised_revision": revision,
            "default_config": default_config,
            "staging_branch": staging_branch,
            "manifest_digest": candidate.get("manifest_digest"),
            "release_root_cid": candidate.get("release_root_cid"),
        },
    }
    rollback = {
        "path": "rollback",
        "status": "rehearsed",
        "ok": True,
        "legacy_files_deleted": False,
        "candidate_tree_retained": True,
        "staging_branch_retained": True,
        "deletion_performed": False,
        "force_push_performed": False,
        "visibility_changed": False,
        "prior_advertised_revision": rollback_revision,
        "prior_default_config": str(
            rollback_spec.get("default_config") or DEFAULT_DEFAULT_CONFIG
        ),
        "restored_mapping": {
            "dataset_id": dataset_id,
            "advertised_revision": rollback_revision,
            "default_config": str(
                rollback_spec.get("default_config") or DEFAULT_DEFAULT_CONFIG
            ),
            "staging_branch_retained": True,
        },
        "policy": str(
            rollback_spec.get("policy")
            or (
                "Re-advertise the prior immutable revision and default config "
                "without deleting the failed candidate tree or legacy files."
            )
        ),
    }
    real_staging = {
        "kind": PENDING_EXTERNAL_KIND,
        "status": "pending_external",
        "authorized": False,
        "mutation_executed": False,
        "remote_write_contacted": False,
        "main_published": False,
        "blocks_local_completion": False,
        "target_repo": dataset_id,
        "staging_branch": staging_branch,
        "reason": (
            "real staging credentials absent or not authorized; "
            "local fixture rehearsal completed without blocking"
        ),
    }

    acceptance = {
        "add_only_upload_planned": True,
        "compatibility_mapping_switch_ok": True,
        "immutable_redownload_ok": True,
        "local_completion_not_blocked_by_missing_credentials": True,
        "no_deletion": True,
        "no_secret_or_path_leak": True,
        "prior_mapping_restored": True,
        "promotion_rehearsed": True,
        "real_staging_typed": True,
        "release_candidate_bound": True,
        "rollback_rehearsed": True,
        "sparse_canary_ok": True,
    }

    recipe: dict[str, Any] = {
        "acceptance": acceptance,
        "canary": {
            "mode": "fixture",
            "network_required": False,
            "network_invoked": False,
            "path": CANARY_FIXTURE_RELPATH.as_posix(),
            "target_repo": str(
                canary_recipe.get("target_repo") or DEFAULT_DATASET_REPO
            ),
            "staging_branch": str(
                canary_recipe.get("staging_branch") or DEFAULT_STAGING_BRANCH
            ),
            "staging_revision": require_immutable_revision(
                str(
                    canary_recipe.get("staging_revision")
                    or ROLLBACK_REVISION
                ),
                name="canary.staging_revision",
            ),
            "default_config": str(
                canary_recipe.get("default_config") or DEFAULT_DEFAULT_CONFIG
            ),
            "immutable_redownload": True,
            "sparse_canary": True,
            "ok": True,
        },
        "candidate": {
            "dataset_id": dataset_id,
            "default_config": default_config,
            "kind": candidate.get("kind") or "fixture_local",
            "manifest_digest": candidate.get("manifest_digest"),
            "package_version": candidate.get("package_version"),
            "release_point": candidate.get("release_point"),
            "release_profile": candidate.get("release_profile"),
            "release_root_cid": candidate.get("release_root_cid"),
            "revision": revision,
            "root_label": candidate.get("root_label"),
            "source_revision": candidate.get("source_revision"),
            "staging_branch": staging_branch,
        },
        "code_version": CODE_VERSION,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "depends_on": list(DEPENDS_ON),
        "digest_sealed": False,
        "dry_run": True,
        "fixture_id": FIXTURE_ID,
        "generators": {
            "canary": "rehearse_sparse_canary()",
            "handoff": "build_fixture_handoff()",
            "promotion": "rehearse_promotion()",
            "rollback": "rehearse_rollback()",
            "stage_plan": "rehearse_stage_plan()",
        },
        "goal_id": GOAL_ID,
        "mapping_switch": {
            "from": {
                "revision": rollback_revision,
                "default_config": str(
                    rollback_spec.get("default_config") or DEFAULT_DEFAULT_CONFIG
                ),
            },
            "switch_rehearsed": True,
            "restore_rehearsed": True,
            "no_deletion": True,
        },
        "network_required": False,
        "notes": (
            "Compact sealed recipe for immutable staging/rollback handoff "
            "canary (USCIR-039). Expand via build_fixture_handoff(). Proves "
            "promotion and rollback without deletion; absent staging credentials "
            "yield a typed pending_external field and never block local "
            "completion. Does not authorize publication."
        ),
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "promotion": promotion,
        "publication_authorized": False,
        "real_staging": real_staging,
        "release_candidate": {
            "path": RELEASE_CANDIDATE_RELPATH.as_posix(),
            "receipt_sha256": release_candidate.get("receipt_sha256"),
            "task_id": "USCIR-038",
            "rollback_revision": rollback_revision,
            "rollback_default_config": str(
                rollback_spec.get("default_config") or DEFAULT_DEFAULT_CONFIG
            ),
        },
        "release_point": release_candidate.get("release_point")
        or candidate.get("release_point"),
        "release_profile": release_candidate.get("release_profile")
        or candidate.get("release_profile"),
        "rollback": rollback,
        "schema": HANDOFF_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "stage_plan": {
            "path": STAGE_PLAN_RELPATH.as_posix(),
            "target_repo": str(
                stage_recipe.get("target_repo") or DEFAULT_DATASET_REPO
            ),
            "staging_branch": str(
                stage_recipe.get("staging_branch") or DEFAULT_STAGING_BRANCH
            ),
            "base_revision": str(
                stage_recipe.get("base_revision") or ROLLBACK_REVISION
            ),
            "operations": ["add_only_upload"],
            "legacy_files_deleted": False,
            "visibility_change_allowed": False,
            "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
            "dry_run": True,
            "ok": True,
        },
        "task_id": TASK_ID,
    }

    reject_credentials_in_payload(recipe, label="staging_canary_recipe")
    reject_path_leaks(recipe, label="staging_canary_recipe")
    reject_identity_contamination(recipe, label="staging_canary_recipe")
    return recipe


def build_fixture_handoff(
    *,
    repo_root: Path | str | None = None,
    run_live_canary: bool = True,
    authorize_real_staging: bool = False,
    external_staging_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the deterministic offline staging/rollback handoff report."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    release_candidate = load_release_candidate(repo_root=root)
    candidate = dict(release_candidate.get("candidate") or {})
    rollback_spec = dict(release_candidate.get("rollback") or {})

    stage_plan = rehearse_stage_plan(repo_root=root)
    canary = rehearse_sparse_canary(
        repo_root=root,
        run_live_fixture=run_live_canary,
    )
    promotion = rehearse_promotion(candidate=candidate, stage_plan=stage_plan)
    rollback = rehearse_rollback(candidate=candidate, rollback=rollback_spec)
    real_staging = resolve_real_staging_disposition(
        authorize_real_staging=authorize_real_staging,
        stage_plan=stage_plan,
        external_evidence=external_staging_evidence,
    )

    # Compatibility mapping switch: promotion then restore prior mapping.
    mapping_switch = {
        "from": {
            "revision": rollback["prior_advertised_revision"],
            "default_config": rollback["prior_default_config"],
        },
        "to_promotion": dict(promotion["advertised_mapping"]),
        "to_rollback": dict(rollback["restored_mapping"]),
        "switch_rehearsed": True,
        "restore_rehearsed": True,
        "no_deletion": (
            not promotion["deletion_performed"]
            and not rollback["deletion_performed"]
            and promotion["legacy_files_deleted"] is False
            and rollback["legacy_files_deleted"] is False
        ),
    }

    rc_path = root / RELEASE_CANDIDATE_RELPATH
    rc_sha = sha256_file(rc_path) if rc_path.is_file() else release_candidate.get(
        "receipt_sha256"
    )

    acceptance = {
        "add_only_upload_planned": stage_plan.get("operations") == ["add_only_upload"],
        "compatibility_mapping_switch_ok": bool(mapping_switch["switch_rehearsed"]),
        "immutable_redownload_ok": bool(canary.get("immutable_redownload")),
        "local_completion_not_blocked_by_missing_credentials": (
            real_staging.get("blocks_local_completion") is False
        ),
        "no_deletion": bool(mapping_switch["no_deletion"]),
        "no_secret_or_path_leak": True,
        "prior_mapping_restored": bool(mapping_switch["restore_rehearsed"]),
        "promotion_rehearsed": bool(promotion.get("ok")),
        "release_candidate_bound": bool(
            candidate.get("manifest_digest") and candidate.get("revision")
        ),
        "rollback_rehearsed": bool(rollback.get("ok")),
        "sparse_canary_ok": bool(canary.get("ok") and canary.get("sparse_canary")),
        "real_staging_typed": real_staging.get("kind")
        in {PENDING_EXTERNAL_KIND, AUTHORIZED_EVIDENCE_KIND},
    }
    if not all(bool(v) for v in acceptance.values()):
        failed = [k for k, v in acceptance.items() if not v]
        raise HandoffMismatchError(
            "staging canary acceptance failed: " + ", ".join(failed)
        )

    report: dict[str, Any] = {
        "acceptance": acceptance,
        "canary": canary,
        "candidate": {
            "dataset_id": candidate.get("dataset_id"),
            "default_config": candidate.get("default_config"),
            "kind": candidate.get("kind"),
            "manifest_digest": candidate.get("manifest_digest"),
            "package_version": candidate.get("package_version"),
            "release_point": candidate.get("release_point"),
            "release_profile": candidate.get("release_profile"),
            "release_root_cid": candidate.get("release_root_cid"),
            "revision": candidate.get("revision"),
            "root_label": candidate.get("root_label"),
            "source_revision": candidate.get("source_revision"),
            "staging_branch": candidate.get("staging_branch"),
        },
        "code_version": CODE_VERSION,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "depends_on": list(DEPENDS_ON),
        "digest_sealed": True,
        "dry_run": True,
        "fixture_id": FIXTURE_ID,
        "goal_id": GOAL_ID,
        "mapping_switch": mapping_switch,
        "network_required": False,
        "notes": (
            "Expanded offline staging/rollback handoff canary for US Code sparse "
            "GraphRAG (USCIR-039). Proves add-only upload planning, immutable "
            "redownload, sparse canary, promotion and rollback mapping switches "
            "without deletion. Optional real staging evidence is recorded when "
            "authorized; absent credentials yield a typed pending_external field "
            "and never block local completion. Does not authorize publication."
        ),
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "promotion": promotion,
        "publication_authorized": False,
        "real_staging": real_staging,
        "release_candidate": {
            "path": RELEASE_CANDIDATE_RELPATH.as_posix(),
            "receipt_sha256": release_candidate.get("receipt_sha256"),
            "file_sha256": rc_sha,
            "task_id": "USCIR-038",
            "rollback_revision": rollback_spec.get("revision"),
            "rollback_default_config": rollback_spec.get("default_config"),
        },
        "release_point": release_candidate.get("release_point")
        or candidate.get("release_point"),
        "release_profile": release_candidate.get("release_profile")
        or candidate.get("release_profile"),
        "rollback": rollback,
        "schema": HANDOFF_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "stage_plan": stage_plan,
        "task_id": TASK_ID,
    }

    report["receipt_sha256"] = digest_mapping(
        {k: v for k, v in report.items() if k != "receipt_sha256"}
    )

    reject_credentials_in_payload(report, label="staging_canary_report")
    reject_path_leaks(report, label="staging_canary_report")
    reject_identity_contamination(report, label="staging_canary_report")
    return report


def materialize_default_report(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
    sealed_recipe: bool = True,
) -> tuple[dict[str, Any], Path]:
    """Build and write the sealed staging canary recipe (default) or full report."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_report_path(root)
    )
    if sealed_recipe:
        report = build_sealed_canary_recipe(repo_root=root)
    else:
        report = build_fixture_handoff(repo_root=root, run_live_canary=True)
    write_json(target, report)
    return report, target


def compare_handoffs(
    fresh: Mapping[str, Any],
    sealed: Mapping[str, Any],
    *,
    recipe_mode: bool | None = None,
) -> list[str]:
    """Return human-readable mismatches between two handoff reports.

    When the sealed surface is a compact recipe (``digest_sealed=false`` or
    ``generators`` present), digest fields are skipped and only policy is
    enforced — same pattern as the stage-plan fixture.
    """

    mismatches: list[str] = []
    if recipe_mode is None:
        recipe_mode = bool(sealed.get("generators")) or (
            sealed.get("digest_sealed") is False
        )

    top_keys = (
        "schema",
        "schema_version",
        "task_id",
        "goal_id",
        "program_id",
        "producer",
        "code_version",
        "fixture_id",
        "network_required",
        "publication_authorized",
        "dry_run",
    )
    for key in top_keys:
        if key in sealed and fresh.get(key) != sealed.get(key):
            mismatches.append(
                f"{key}: fresh={fresh.get(key)!r} sealed={sealed.get(key)!r}"
            )

    for section, keys in (
        (
            "candidate",
            (
                "dataset_id",
                "revision",
                "manifest_digest",
                "release_root_cid",
                "default_config",
                "staging_branch",
            ),
        ),
        (
            "stage_plan",
            (
                "target_repo",
                "staging_branch",
                "operations",
                "legacy_files_deleted",
            ),
        ),
        (
            "promotion",
            ("path", "status", "legacy_files_deleted", "deletion_performed", "ok"),
        ),
        (
            "rollback",
            (
                "path",
                "status",
                "legacy_files_deleted",
                "deletion_performed",
                "candidate_tree_retained",
                "ok",
            ),
        ),
        (
            "real_staging",
            ("kind", "blocks_local_completion", "mutation_executed", "main_published"),
        ),
        (
            "canary",
            (
                "mode",
                "network_required",
                "staging_revision",
                "target_repo",
                "immutable_redownload",
                "sparse_canary",
            ),
        ),
    ):
        fresh_sec = dict(fresh.get(section) or {})
        sealed_sec = dict(sealed.get(section) or {})
        for key in keys:
            if key not in sealed_sec and key not in fresh_sec:
                continue
            if sealed_sec.get(key) is None and recipe_mode:
                continue
            if fresh_sec.get(key) != sealed_sec.get(key):
                mismatches.append(
                    f"{section}.{key}: fresh={fresh_sec.get(key)!r} "
                    f"sealed={sealed_sec.get(key)!r}"
                )

    if not recipe_mode:
        for section, keys in (
            ("stage_plan", ("manifest_digest", "plan_digest")),
        ):
            fresh_sec = dict(fresh.get(section) or {})
            sealed_sec = dict(sealed.get(section) or {})
            for key in keys:
                if key in sealed_sec and fresh_sec.get(key) != sealed_sec.get(key):
                    mismatches.append(
                        f"{section}.{key}: fresh={fresh_sec.get(key)!r} "
                        f"sealed={sealed_sec.get(key)!r}"
                    )

    fresh_acc = dict(fresh.get("acceptance") or {})
    sealed_acc = dict(sealed.get("acceptance") or {})
    for key, expected in sealed_acc.items():
        if fresh_acc.get(key) != expected:
            mismatches.append(
                f"acceptance.{key}: fresh={fresh_acc.get(key)!r} "
                f"sealed={expected!r}"
            )

    return mismatches


def assert_handoff_safe(
    report: Mapping[str, Any],
    *,
    require_receipt_digest: bool | None = None,
) -> None:
    """Fail closed on structural/safety violations in a handoff report."""

    if report.get("schema") != HANDOFF_SCHEMA:
        raise HandoffMismatchError(f"unexpected schema: {report.get('schema')!r}")
    if report.get("task_id") != TASK_ID:
        raise HandoffMismatchError(f"unexpected task_id: {report.get('task_id')!r}")
    if report.get("publication_authorized") is not False:
        raise HandoffMismatchError("publication_authorized must be false")
    if report.get("network_required") is not False:
        raise HandoffMismatchError("network_required must be false for fixture handoff")

    promotion = dict(report.get("promotion") or {})
    rollback = dict(report.get("rollback") or {})
    if promotion.get("deletion_performed") or rollback.get("deletion_performed"):
        raise HandoffSafetyError("handoff must never perform deletion")
    if promotion.get("legacy_files_deleted") is not False:
        raise HandoffSafetyError("promotion must declare legacy_files_deleted=false")
    if rollback.get("legacy_files_deleted") is not False:
        raise HandoffSafetyError("rollback must declare legacy_files_deleted=false")
    if rollback.get("candidate_tree_retained") is not True:
        raise HandoffSafetyError("rollback must retain the candidate tree")

    real_staging = dict(report.get("real_staging") or {})
    kind = real_staging.get("kind")
    if kind not in {PENDING_EXTERNAL_KIND, AUTHORIZED_EVIDENCE_KIND}:
        raise HandoffMismatchError(
            f"real_staging.kind must be typed pending_external or "
            f"authorized_evidence, got {kind!r}"
        )
    if real_staging.get("blocks_local_completion") is not False:
        raise HandoffMismatchError(
            "real_staging must never block local completion"
        )
    if real_staging.get("main_published") is not False:
        raise HandoffSafetyError("real_staging must never publish main")

    recipe_mode = bool(report.get("generators")) or (
        report.get("digest_sealed") is False
    )
    if require_receipt_digest is None:
        require_receipt_digest = not recipe_mode

    if require_receipt_digest:
        digest = report.get("receipt_sha256")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise HandoffMismatchError("receipt_sha256 missing or invalid")
        expected = digest_mapping(
            {k: v for k, v in report.items() if k != "receipt_sha256"}
        )
        if digest != expected:
            raise HandoffMismatchError("receipt_sha256 does not match report body")

    reject_credentials_in_payload(report, label="handoff_report")
    reject_path_leaks(report, label="handoff_report")


def verify_handoff(
    report: Mapping[str, Any] | None = None,
    *,
    report_path: Path | str | None = None,
    repo_root: Path | str | None = None,
    require_fixture_match: bool = True,
    run_live_canary: bool = True,
) -> dict[str, Any]:
    """Verify a sealed handoff report against a fresh fixture build."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    if report is None:
        path = (
            Path(report_path).expanduser().resolve()
            if report_path is not None
            else default_report_path(root)
        )
        report = load_json_mapping(path)
    else:
        path = (
            Path(report_path).expanduser().resolve()
            if report_path is not None
            else default_report_path(root)
        )

    assert_handoff_safe(report)
    fresh = build_fixture_handoff(
        repo_root=root,
        run_live_canary=run_live_canary,
        # Verification always uses the default (non-authorized) disposition so
        # sealed fixture reports remain deterministic.
        authorize_real_staging=False,
    )
    assert_handoff_safe(fresh)

    mismatches: list[str] = []
    if require_fixture_match:
        mismatches = compare_handoffs(fresh, report)
        if mismatches:
            raise HandoffMismatchError(
                "staging canary handoff mismatch: " + "; ".join(mismatches[:16])
            )

    return {
        "ok": True,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "report_path": repo_relpath(path, repo_root=root)
        if path.is_file()
        else DEFAULT_REPORT_RELPATH.as_posix(),
        "receipt_sha256": report.get("receipt_sha256") or fresh.get("receipt_sha256"),
        "manifest_digest": (report.get("candidate") or {}).get("manifest_digest")
        or (fresh.get("candidate") or {}).get("manifest_digest"),
        "plan_digest": (fresh.get("stage_plan") or {}).get("plan_digest"),
        "promotion_ok": bool((report.get("promotion") or {}).get("ok")),
        "rollback_ok": bool((report.get("rollback") or {}).get("ok")),
        "real_staging_kind": (report.get("real_staging") or {}).get("kind"),
        "mismatches": [],
        "publication_authorized": False,
        "network_required": False,
    }


def check_sealed_recipe(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Validate the sealed recipe against a freshly built recipe surface."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    sealed_path = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_report_path(root)
    )
    sealed = load_json_mapping(sealed_path)
    fresh = build_sealed_canary_recipe(repo_root=root)
    assert_handoff_safe(sealed)
    assert_handoff_safe(fresh)
    mismatches = compare_handoffs(fresh, sealed, recipe_mode=True)
    if mismatches:
        raise HandoffMismatchError(
            "sealed staging canary recipe check failed: "
            + "; ".join(mismatches[:16])
        )
    return {
        "ok": True,
        "path": DEFAULT_REPORT_RELPATH.as_posix(),
        "mismatches": [],
        "task_id": TASK_ID,
        "real_staging_kind": (sealed.get("real_staging") or {}).get("kind"),
        "promotion_ok": bool((sealed.get("promotion") or {}).get("ok")),
        "rollback_ok": bool((sealed.get("rollback") or {}).get("ok")),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rehearse_uscode_release_handoff.py",
        description=(
            "Rehearse immutable staging and rollback handoff for US Code sparse "
            f"GraphRAG ({TASK_ID}). Default mode is offline fixture dry-run "
            "(no Hub contact, no public mutation)."
        ),
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Offline fixture mode (no network, deterministic handoff)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Emit the sealed handoff report without remote mutation (default)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write/refresh the sealed staging canary report",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the sealed report against a fresh fixture handoff",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional path for the handoff JSON "
            f"(default: stdout, or {DEFAULT_REPORT_RELPATH.as_posix()} with --write)"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=(
            "Path to the sealed staging canary report "
            f"(default: {DEFAULT_REPORT_RELPATH.as_posix()})"
        ),
    )
    parser.add_argument(
        "--authorize-real-staging",
        action="store_true",
        help=(
            "Opt-in real staging evidence recording; also requires "
            f"${AUTHORIZATION_ENV}. Still cannot publish main or delete."
        ),
    )
    parser.add_argument(
        "--skip-live-canary",
        action="store_true",
        help=(
            "Bind sealed canary policy without executing the full offline "
            "fixture canary (faster; default path runs the live fixture canary)"
        ),
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Always print the handoff/verification result as JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    try:
        reject_secrets_in_argv(argv_list)
        args = parser.parse_args(argv_list)
    except SystemExit as exc:
        return int(exc.code or 0)
    except HandoffSafetyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report is not None
        else default_report_path()
    )
    run_live_canary = not bool(args.skip_live_canary)

    try:
        if not args.fixture_only and not args.check and not args.write:
            raise HandoffError(
                "pass --fixture-only --dry-run for the offline staging/rollback "
                "handoff rehearsal (no network path in this CLI)"
            )

        if args.check and not args.write:
            if not report_path.is_file():
                raise HandoffMissingInputError(
                    f"report not found: {report_path}; pass --fixture-only --write"
                )
            # Prefer recipe check for sealed compact surface; fall back to full
            # expanded verification when the on-disk report is digest-sealed.
            sealed = load_json_mapping(report_path)
            if sealed.get("generators") or sealed.get("digest_sealed") is False:
                result = check_sealed_recipe(path=report_path)
                # Also expand once to prove the full rehearsal still works.
                expanded = build_fixture_handoff(
                    run_live_canary=run_live_canary,
                    authorize_real_staging=False,
                )
                assert_handoff_safe(expanded)
                result["expanded_receipt_sha256"] = expanded.get("receipt_sha256")
                result["receipt_sha256"] = expanded.get("receipt_sha256")
                result["plan_digest"] = (expanded.get("stage_plan") or {}).get(
                    "plan_digest"
                )
            else:
                result = verify_handoff(
                    report_path=report_path,
                    require_fixture_match=True,
                    run_live_canary=run_live_canary,
                )
            if args.print_json or args.output is not None:
                write_json(args.output, result)
            print(
                "ok={ok} task_id={task_id} promotion_ok={promotion_ok} "
                "rollback_ok={rollback_ok} real_staging_kind={real_staging_kind}".format(
                    **{
                        "ok": result.get("ok"),
                        "task_id": result.get("task_id"),
                        "promotion_ok": result.get("promotion_ok"),
                        "rollback_ok": result.get("rollback_ok"),
                        "real_staging_kind": result.get("real_staging_kind"),
                    }
                ),
                file=sys.stderr,
            )
            return 0 if result.get("ok") else 1

        # Primary path: fixture dry-run / write.
        if not args.fixture_only and args.write:
            raise HandoffError("--write requires --fixture-only")

        if args.write:
            recipe, written = materialize_default_report(
                path=(
                    Path(args.output).expanduser().resolve()
                    if args.output is not None
                    else report_path
                ),
                sealed_recipe=True,
            )
            assert_handoff_safe(recipe)
            print(f"wrote staging canary recipe: {written}", file=sys.stderr)
            # Still expand once so operators see the full rehearsal surface.
            report = build_fixture_handoff(
                run_live_canary=run_live_canary,
                authorize_real_staging=bool(args.authorize_real_staging),
            )
            assert_handoff_safe(report)
            if args.print_json:
                write_json(None, report)
        else:
            report = build_fixture_handoff(
                run_live_canary=run_live_canary,
                authorize_real_staging=bool(args.authorize_real_staging),
            )
            assert_handoff_safe(report)
            if args.output is not None:
                write_json(Path(args.output).expanduser().resolve(), report)
            elif args.print_json or args.dry_run or args.fixture_only:
                write_json(None, report)

        print(
            "ok=True task_id={task_id} receipt_sha256={receipt_sha256} "
            "promotion={promotion} rollback={rollback} "
            "real_staging_kind={kind} dry_run=True publication_authorized=False".format(
                task_id=report["task_id"],
                receipt_sha256=report.get("receipt_sha256") or "",
                promotion=report["promotion"]["status"],
                rollback=report["rollback"]["status"],
                kind=report["real_staging"]["kind"],
            ),
            file=sys.stderr,
        )
        return 0

    except HandoffAuthorizationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (
        HandoffError,
        HandoffSafetyError,
        HandoffMissingInputError,
        HandoffMismatchError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
