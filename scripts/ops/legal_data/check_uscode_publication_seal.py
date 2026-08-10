#!/usr/bin/env python3
"""Assemble and validate the human publication-seal request for US Code sparse GraphRAG (USCIR-040).

Terminal gate for production publication of ``justicedao/ipfs_uscode``.

This CLI:

* assembles a complete authorization request binding production repo/branch,
  immutable candidate revision, manifest and validation digests, rollback
  mapping, and requested mutations;
* validates a **pending** seal as a complete request (``--allow-pending``);
* accepts an **approved** seal only with an external human identity + signature
  bound to the exact digests;
* never publishes, never contacts the Hub, never embeds tokens, and never
  treats agent/supervisor identity as human approval.

Validation gate (offline)::

    python scripts/ops/legal_data/check_uscode_publication_seal.py \\
        --seal docs/reports/uscode_publication_seal.json --allow-pending
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
    reject_identity_contamination,
)
from ipfs_datasets_py.processors.legal_data.uscode_hf_release import (  # noqa: E402
    DEFAULT_CONFIG_NAME,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_SOURCE_REVISION,
)
from ipfs_datasets_py.processors.legal_data.uscode_release_schema import (  # noqa: E402
    digest_mapping,
    normalize_sha256,
    require_immutable_revision,
)
from ipfs_datasets_py.processors.legal_data.uscode_source_policy import (  # noqa: E402
    CURRENTNESS_DISCLAIMER,
    DEFAULT_APPROVED_RELEASE_POINT,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "USCIR-040"
GOAL_ID: Final = "USCIR-G100"
PROGRAM_ID: Final = "uscode-sparse-graphrag-v1"
PRODUCER: Final = "check_uscode_publication_seal.py"
CODE_VERSION: Final = "1"
DEPENDS_ON: Final[tuple[str, ...]] = ("USCIR-039",)

SEAL_SCHEMA: Final = "ipfs_datasets_py/uscode-sparse-graphrag-publication-seal@1"
SCHEMA_VERSION: Final = "uscode-publication-seal/v1"
FIXTURE_ID: Final = "uscode-publication-seal-v1"

DEFAULT_SEAL_RELPATH: Final = Path("docs/reports/uscode_publication_seal.json")
RELEASE_CANDIDATE_RELPATH: Final = Path("docs/reports/uscode_release_candidate.json")
STAGING_CANARY_RELPATH: Final = Path("docs/reports/uscode_staging_canary.json")

DEFAULT_DATASET_REPO: Final = DEFAULT_DATASET_REPO_ID
DEFAULT_PRODUCTION_BRANCH: Final = "main"
DEFAULT_DEFAULT_CONFIG: Final = DEFAULT_CONFIG_NAME
DEFAULT_STAGING_BRANCH: Final = "stage/uscode-sparse-graphrag-v2"
ROLLBACK_REVISION: Final = DEFAULT_SOURCE_REVISION

STATUS_PENDING: Final = "pending"
STATUS_APPROVED: Final = "approved"
VALID_STATUSES: Final[frozenset[str]] = frozenset({STATUS_PENDING, STATUS_APPROVED})

# Identities that may never approve a production seal (agents / automation).
_AGENT_IDENTITY_RE = re.compile(
    r"(?i)\b("
    r"agent|supervisor|implementation[_-]?supervisor|codex|grok|"
    r"uscir|autonomous|bot|ci[_-]?runner|github[_-]?actions|"
    r"service[_-]?account|machine[_-]?user"
    r")\b"
)

SECRET_ENV_NAMES: Final[tuple[str, ...]] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
    "USCODE_STAGING_AUTHORIZATION",
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

# Allowed mutation kinds on a production seal request (mapping switch only).
ALLOWED_MUTATION_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "advertise_revision",
        "switch_default_config",
        "add_only_upload",
    }
)

FORBIDDEN_MUTATION_OPERATIONS: Final[frozenset[str]] = frozenset(
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
    }
)


class PublicationSealError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class MissingInputError(PublicationSealError):
    """Raised when a required producer input is absent."""


class MismatchError(PublicationSealError):
    """Raised when a bound digest or field does not match."""


class SealStateError(PublicationSealError):
    """Raised when seal status/authorization is inconsistent."""


class ApprovalError(PublicationSealError):
    """Raised when approved-state human authorization is incomplete or invalid."""


class PathLeakError(PublicationSealError):
    """Raised when absolute local paths appear in a public seal."""


class SecretLeakError(PublicationSealError):
    """Raised when credential-like material appears in a public seal."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_seal_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_SEAL_RELPATH).resolve()


def repo_relpath(path: Path | str, *, repo_root: Path | str | None = None) -> str:
    """Return a POSIX repo-relative path; never an absolute local path."""
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    target = Path(path)
    try:
        rel = target.resolve().relative_to(root.resolve())
    except ValueError:
        text = str(path).replace("\\", "/")
        if text.startswith("/") or re.match(r"^[A-Za-z]:[/\\]", text):
            raise PathLeakError(
                f"refusing absolute path in seal surface: {text!r}"
            )
        return text.lstrip("./")
    return rel.as_posix()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise MissingInputError(f"JSON file not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublicationSealError(f"cannot read JSON {target}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise PublicationSealError(f"JSON root must be an object: {target}")
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
        raise MissingInputError(f"file not found for digest: {target}")
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
        raise SecretLeakError(
            f"credential-like material in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )


def reject_path_leaks(value: Any, *, label: str = "payload") -> None:
    """Fail closed when absolute local paths appear in a public seal."""

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
            if text.startswith("/") and any(
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
        raise PathLeakError(
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
            raise SecretLeakError(
                "refusing to accept secrets on the command line; "
                "credentials are environment-only"
            )


# ---------------------------------------------------------------------------
# Producer inputs
# ---------------------------------------------------------------------------


def load_release_candidate(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else (root / RELEASE_CANDIDATE_RELPATH).resolve()
    )
    receipt = load_json_mapping(target)
    if receipt.get("task_id") != "USCIR-038":
        raise MismatchError(
            f"release candidate task_id must be USCIR-038, got {receipt.get('task_id')!r}"
        )
    if receipt.get("publication_authorized") is not False:
        raise MismatchError(
            "release candidate must declare publication_authorized=false"
        )
    candidate = dict(receipt.get("candidate") or {})
    if not candidate.get("manifest_digest") or not candidate.get("revision"):
        raise MissingInputError("release candidate missing revision/manifest_digest")
    require_immutable_revision(str(candidate["revision"]), name="candidate.revision")
    normalize_sha256(
        candidate["manifest_digest"], name="candidate.manifest_digest"
    )
    return receipt


def load_staging_canary(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else (root / STAGING_CANARY_RELPATH).resolve()
    )
    report = load_json_mapping(target)
    if report.get("task_id") != "USCIR-039":
        raise MismatchError(
            f"staging canary task_id must be USCIR-039, got {report.get('task_id')!r}"
        )
    if report.get("publication_authorized") is not False:
        raise MismatchError(
            "staging canary must declare publication_authorized=false"
        )
    return report


# ---------------------------------------------------------------------------
# Approver / signature policy
# ---------------------------------------------------------------------------


def is_agent_identity(identity: Any) -> bool:
    text = str(identity or "").strip()
    if not text:
        return False
    return bool(_AGENT_IDENTITY_RE.search(text))


def assert_human_identity(identity: Any, *, label: str = "approver.identity") -> str:
    text = str(identity or "").strip()
    if not text:
        raise ApprovalError(f"{label} is required for an approved seal")
    if is_agent_identity(text):
        raise ApprovalError(
            f"{label} rejects agent/supervisor identity {text!r}; "
            "publication seal requires an external human approver"
        )
    if len(text) < 3:
        raise ApprovalError(f"{label} is too short to identify a human approver")
    return text


def signature_payload(
    *,
    digests: Mapping[str, Any],
    candidate_revision: str,
    production_repo: str,
    production_branch: str,
    identity: str,
) -> dict[str, Any]:
    """Canonical fields covered by the human approval signature."""

    return {
        "candidate_revision": require_immutable_revision(
            candidate_revision, name="candidate_revision"
        ),
        "digests": {
            key: normalize_sha256(value, name=f"digests.{key}")
            if _SHA256_RE.fullmatch(str(value).casefold().removeprefix("sha256:"))
            or str(value).casefold().startswith("sha256:")
            else str(value)
            for key, value in sorted(digests.items())
            if value
        },
        "identity": identity,
        "production_branch": production_branch,
        "production_repo": production_repo,
        "schema": SEAL_SCHEMA,
        "task_id": TASK_ID,
    }


def compute_approval_signature(
    *,
    digests: Mapping[str, Any],
    candidate_revision: str,
    production_repo: str,
    production_branch: str,
    identity: str,
) -> str:
    """Deterministic content-bound signature digest (not a live crypto key).

    Humans (or offline tooling they control) bind identity to exact digests by
    producing this digest. Agents cannot self-authorize because agent identities
    are rejected before signature verification.
    """

    human = assert_human_identity(identity)
    body = signature_payload(
        digests=digests,
        candidate_revision=candidate_revision,
        production_repo=production_repo,
        production_branch=production_branch,
        identity=human,
    )
    return digest_mapping(body)


# ---------------------------------------------------------------------------
# Seal construction
# ---------------------------------------------------------------------------


def _requested_mutations(
    *,
    production_repo: str,
    production_branch: str,
    candidate: Mapping[str, Any],
    rollback: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            "from_default_config": rollback.get("default_config") or DEFAULT_DEFAULT_CONFIG,
            "from_revision": rollback.get("revision") or ROLLBACK_REVISION,
            "operation": "advertise_revision",
            "target_branch": production_branch,
            "target_repo": production_repo,
            "to_default_config": candidate.get("default_config") or DEFAULT_DEFAULT_CONFIG,
            "to_revision": candidate.get("revision"),
        },
        {
            "default_config": candidate.get("default_config") or DEFAULT_DEFAULT_CONFIG,
            "operation": "switch_default_config",
            "target_branch": production_branch,
            "target_repo": production_repo,
        },
    ]


def build_pending_seal(
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Build the deterministic offline pending publication-seal request."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    release_candidate = load_release_candidate(repo_root=root)
    staging_canary = load_staging_canary(repo_root=root)

    candidate_src = dict(release_candidate.get("candidate") or {})
    rollback_src = dict(release_candidate.get("rollback") or {})
    digests_src = dict(release_candidate.get("digests") or {})

    production_repo = str(
        candidate_src.get("dataset_id") or DEFAULT_DATASET_REPO
    ).strip()
    if production_repo != DEFAULT_DATASET_REPO:
        # Still allow exact advertised dataset_id from the candidate, but it
        # must be non-empty and not a floating label.
        if not production_repo or "/" not in production_repo:
            raise MismatchError(
                f"production dataset_id must be org/name, got {production_repo!r}"
            )

    candidate_revision = require_immutable_revision(
        str(candidate_src.get("revision") or ROLLBACK_REVISION),
        name="candidate.revision",
    )
    manifest_digest = normalize_sha256(
        candidate_src.get("manifest_digest") or digests_src.get("manifest"),
        name="manifest_digest",
    )
    validation_receipt_digest = normalize_sha256(
        release_candidate.get("receipt_sha256"),
        name="validation_receipt_digest",
    )

    rc_path = root / RELEASE_CANDIDATE_RELPATH
    canary_path = root / STAGING_CANARY_RELPATH
    rc_file_sha = sha256_file(rc_path) if rc_path.is_file() else validation_receipt_digest
    canary_file_sha = sha256_file(canary_path) if canary_path.is_file() else None

    digests: dict[str, Any] = {
        "code": digests_src.get("code"),
        "config": digests_src.get("config"),
        "manifest": manifest_digest,
        "model": digests_src.get("model"),
        "release_candidate_file_sha256": rc_file_sha,
        "release_root_cid": digests_src.get("release_root_cid")
        or candidate_src.get("release_root_cid"),
        "staging_canary_file_sha256": canary_file_sha,
        "validation_receipt": validation_receipt_digest,
    }
    # Drop empty optional digests so the surface stays tight.
    digests = {k: v for k, v in digests.items() if v}

    for key in ("manifest", "validation_receipt"):
        if key not in digests:
            raise MissingInputError(f"digests.{key} missing")
        if key in ("manifest", "validation_receipt", "code", "config", "model"):
            if digests.get(key):
                normalize_sha256(digests[key], name=f"digests.{key}")

    rollback = {
        "dataset_id": rollback_src.get("dataset_id") or production_repo,
        "default_config": rollback_src.get("default_config") or DEFAULT_DEFAULT_CONFIG,
        "legacy_files_deleted": False,
        "policy": rollback_src.get("policy")
        or (
            "Re-advertise the prior immutable revision and default config "
            "without deleting the failed candidate tree or legacy files."
        ),
        "revision": require_immutable_revision(
            str(rollback_src.get("revision") or ROLLBACK_REVISION),
            name="rollback.revision",
        ),
        "staging_branch_retained": True,
    }

    candidate = {
        "dataset_id": production_repo,
        "default_config": candidate_src.get("default_config") or DEFAULT_DEFAULT_CONFIG,
        "kind": candidate_src.get("kind") or "fixture_local",
        "manifest_digest": manifest_digest,
        "package_version": candidate_src.get("package_version"),
        "release_point": candidate_src.get("release_point")
        or release_candidate.get("release_point")
        or DEFAULT_APPROVED_RELEASE_POINT,
        "release_profile": candidate_src.get("release_profile")
        or release_candidate.get("release_profile"),
        "release_root_cid": candidate_src.get("release_root_cid")
        or digests.get("release_root_cid"),
        "revision": candidate_revision,
        "root_label": candidate_src.get("root_label"),
        "source_revision": candidate_src.get("source_revision"),
        "staging_branch": candidate_src.get("staging_branch")
        or DEFAULT_STAGING_BRANCH,
    }

    production = {
        "branch": DEFAULT_PRODUCTION_BRANCH,
        "dataset_id": production_repo,
        "default_config": candidate["default_config"],
        "publication_requires_human_seal": True,
    }

    requested_mutations = _requested_mutations(
        production_repo=production_repo,
        production_branch=DEFAULT_PRODUCTION_BRANCH,
        candidate=candidate,
        rollback=rollback,
    )

    for mutation in requested_mutations:
        op = str(mutation.get("operation") or "")
        if op in FORBIDDEN_MUTATION_OPERATIONS:
            raise MismatchError(f"forbidden mutation operation: {op}")
        if op not in ALLOWED_MUTATION_OPERATIONS:
            raise MismatchError(f"unknown mutation operation: {op}")

    evidence = {
        "release_candidate": {
            "path": RELEASE_CANDIDATE_RELPATH.as_posix(),
            "receipt_sha256": validation_receipt_digest,
            "task_id": "USCIR-038",
        },
        "staging_canary": {
            "path": STAGING_CANARY_RELPATH.as_posix(),
            "promotion_status": (staging_canary.get("promotion") or {}).get("status"),
            "rollback_status": (staging_canary.get("rollback") or {}).get("status"),
            "task_id": "USCIR-039",
        },
    }
    if canary_file_sha:
        evidence["staging_canary"]["file_sha256"] = canary_file_sha

    acceptance = {
        "approver_fields_present": True,
        "complete_authorization_request": True,
        "exact_digests_bound": bool(
            digests.get("manifest") and digests.get("validation_receipt")
        ),
        "human_approval_required": True,
        "legacy_rollback_mapping_named": bool(
            rollback.get("revision") and rollback.get("default_config")
        ),
        "main_not_mutated_by_this_tool": True,
        "no_agent_self_authorization": True,
        "no_secret_or_path_leak": True,
        "pending_valid_as_request": True,
        "production_repo_branch_named": bool(
            production.get("dataset_id") and production.get("branch")
        ),
        "requested_mutations_enumerated": bool(requested_mutations),
    }
    if not all(bool(v) for v in acceptance.values()):
        failed = [k for k, v in acceptance.items() if not v]
        raise MismatchError(
            "publication-seal acceptance failed: " + ", ".join(failed)
        )

    seal: dict[str, Any] = {
        "acceptance": acceptance,
        "approver": {
            "approved_at": None,
            "identity": None,
            "kind": "external_human",
            "signature": None,
            "status": STATUS_PENDING,
        },
        "candidate": candidate,
        "code_version": CODE_VERSION,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "depends_on": list(DEPENDS_ON),
        "digests": digests,
        "evidence": evidence,
        "fixture_id": FIXTURE_ID,
        "goal_id": GOAL_ID,
        "main_published": False,
        "network_required": False,
        "notes": (
            "Pending human publication-seal request for US Code sparse GraphRAG "
            f"({TASK_ID}). Binds production repo/branch, immutable candidate "
            "revision, manifest and validation digests, legacy/rollback mapping, "
            "and requested mutations. Agents assemble and validate this request "
            "only; they cannot self-authorize or publish. Approve by attaching an "
            "external human identity and digest-bound signature."
        ),
        "producer": PRODUCER,
        "production": production,
        "program_id": PROGRAM_ID,
        "publication_authorized": False,
        "release_point": candidate.get("release_point") or DEFAULT_APPROVED_RELEASE_POINT,
        "release_profile": candidate.get("release_profile"),
        "requested_mutations": requested_mutations,
        "rollback": rollback,
        "schema": SEAL_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "status": STATUS_PENDING,
        "task_id": TASK_ID,
    }

    seal["seal_sha256"] = digest_mapping(
        {k: v for k, v in seal.items() if k != "seal_sha256"}
    )

    reject_credentials_in_payload(seal, label="publication_seal")
    reject_path_leaks(seal, label="publication_seal")
    reject_identity_contamination(seal, label="publication_seal")
    return seal


def materialize_default_seal(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> tuple[dict[str, Any], Path]:
    """Build and write the sealed pending publication-seal request."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_seal_path(root)
    )
    seal = build_pending_seal(repo_root=root)
    write_json(target, seal)
    return seal, target


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def assert_seal_structure(seal: Mapping[str, Any]) -> None:
    """Structural + safety checks common to pending and approved seals."""

    if not isinstance(seal, Mapping):
        raise PublicationSealError("seal must be an object")
    if seal.get("schema") != SEAL_SCHEMA:
        raise MismatchError(f"seal schema mismatch: {seal.get('schema')!r}")
    if seal.get("schema_version") != SCHEMA_VERSION:
        raise MismatchError(
            f"seal schema_version mismatch: {seal.get('schema_version')!r}"
        )
    if seal.get("task_id") != TASK_ID:
        raise MismatchError(f"seal task_id mismatch: {seal.get('task_id')!r}")
    if seal.get("goal_id") != GOAL_ID:
        raise MismatchError(f"seal goal_id mismatch: {seal.get('goal_id')!r}")
    if seal.get("program_id") != PROGRAM_ID:
        raise MismatchError(f"seal program_id mismatch: {seal.get('program_id')!r}")
    if seal.get("producer") != PRODUCER:
        raise MismatchError(f"seal producer mismatch: {seal.get('producer')!r}")
    if seal.get("network_required") is not False:
        raise MismatchError("seal must declare network_required=false")
    if seal.get("main_published") is not False:
        raise MismatchError(
            "seal checker must not claim main_published; this tool never publishes"
        )

    status = str(seal.get("status") or "").strip().casefold()
    if status not in VALID_STATUSES:
        raise SealStateError(
            f"seal status must be one of {sorted(VALID_STATUSES)}, got {status!r}"
        )

    production = dict(seal.get("production") or {})
    for field in ("dataset_id", "branch", "default_config"):
        if not production.get(field):
            raise MissingInputError(f"production.{field} missing")
    if production.get("publication_requires_human_seal") is not True:
        raise MismatchError(
            "production.publication_requires_human_seal must be true"
        )
    if str(production.get("branch")).casefold() not in {"main", "master"}:
        # Seal requests production; staging branches belong to earlier tasks.
        raise MismatchError(
            "production.branch must name the production branch (main/master)"
        )

    candidate = dict(seal.get("candidate") or {})
    for field in (
        "dataset_id",
        "revision",
        "manifest_digest",
        "release_root_cid",
        "release_point",
        "default_config",
        "staging_branch",
    ):
        if not candidate.get(field):
            raise MissingInputError(f"candidate.{field} missing")
    require_immutable_revision(str(candidate["revision"]), name="candidate.revision")
    normalize_sha256(candidate["manifest_digest"], name="candidate.manifest_digest")
    staging_branch = str(candidate["staging_branch"]).casefold()
    if staging_branch in {"main", "master", "latest", "head"}:
        raise MismatchError(
            "candidate.staging_branch must not be a production/mutable token"
        )

    rollback = dict(seal.get("rollback") or {})
    if not rollback.get("revision") or not rollback.get("default_config"):
        raise MissingInputError("rollback target incomplete")
    require_immutable_revision(str(rollback["revision"]), name="rollback.revision")
    if rollback.get("legacy_files_deleted") is not False:
        raise MismatchError("rollback must declare legacy_files_deleted=false")

    digests = dict(seal.get("digests") or {})
    for key in ("manifest", "validation_receipt"):
        value = digests.get(key)
        if not value:
            raise MissingInputError(f"digests.{key} missing")
        normalize_sha256(value, name=f"digests.{key}")
    if digests.get("manifest") != candidate.get("manifest_digest"):
        raise MismatchError(
            "digests.manifest must equal candidate.manifest_digest"
        )

    mutations = seal.get("requested_mutations")
    if not isinstance(mutations, list) or not mutations:
        raise MissingInputError("requested_mutations must be a non-empty list")
    for index, mutation in enumerate(mutations):
        if not isinstance(mutation, Mapping):
            raise MismatchError(f"requested_mutations[{index}] must be an object")
        op = str(mutation.get("operation") or "")
        if op in FORBIDDEN_MUTATION_OPERATIONS:
            raise MismatchError(
                f"requested_mutations[{index}] forbids operation {op!r}"
            )
        if op not in ALLOWED_MUTATION_OPERATIONS:
            raise MismatchError(
                f"requested_mutations[{index}] unknown operation {op!r}"
            )

    approver = dict(seal.get("approver") or {})
    if "identity" not in approver or "signature" not in approver:
        raise MissingInputError("approver.identity and approver.signature required")
    if approver.get("kind") not in (None, "external_human"):
        # Only external human approvers are accepted for this gate.
        if is_agent_identity(approver.get("kind")):
            raise ApprovalError("approver.kind rejects agent automation")

    acceptance = dict(seal.get("acceptance") or {})
    for key, expected in (
        ("complete_authorization_request", True),
        ("exact_digests_bound", True),
        ("human_approval_required", True),
        ("main_not_mutated_by_this_tool", True),
        ("no_agent_self_authorization", True),
        ("no_secret_or_path_leak", True),
        ("production_repo_branch_named", True),
        ("requested_mutations_enumerated", True),
        ("legacy_rollback_mapping_named", True),
    ):
        if acceptance.get(key) is not expected:
            raise MismatchError(f"acceptance.{key} must be {expected!r}")

    bound = str(seal.get("seal_sha256") or "").casefold()
    if not _SHA256_RE.fullmatch(bound):
        raise MismatchError("seal_sha256 must be a 64-hex digest")
    recomputed = digest_mapping(
        {k: v for k, v in seal.items() if k != "seal_sha256"}
    )
    if recomputed != bound:
        raise MismatchError(
            f"seal_sha256 mismatch: bound={bound} recomputed={recomputed}"
        )

    reject_credentials_in_payload(seal, label="seal")
    reject_path_leaks(seal, label="seal")
    reject_identity_contamination(seal, label="seal")


def assert_pending_seal(seal: Mapping[str, Any]) -> None:
    """Pending seals are complete requests but not production authorizations."""

    if str(seal.get("status") or "").casefold() != STATUS_PENDING:
        raise SealStateError("expected pending seal")
    if seal.get("publication_authorized") is not False:
        raise SealStateError(
            "pending seal must declare publication_authorized=false"
        )
    if seal.get("main_published") is not False:
        raise SealStateError("pending seal must declare main_published=false")

    approver = dict(seal.get("approver") or {})
    if approver.get("identity") not in (None, ""):
        raise SealStateError(
            "pending seal must leave approver.identity empty "
            "(human fills this on approval)"
        )
    if approver.get("signature") not in (None, ""):
        raise SealStateError(
            "pending seal must leave approver.signature empty"
        )
    if str(approver.get("status") or STATUS_PENDING).casefold() != STATUS_PENDING:
        raise SealStateError("approver.status must be pending for a pending seal")

    acceptance = dict(seal.get("acceptance") or {})
    if acceptance.get("pending_valid_as_request") is not True:
        raise MismatchError("acceptance.pending_valid_as_request must be true")


def assert_approved_seal(seal: Mapping[str, Any]) -> None:
    """Approved seals require external human identity + exact digest signature."""

    if str(seal.get("status") or "").casefold() != STATUS_APPROVED:
        raise SealStateError("expected approved seal")
    if seal.get("publication_authorized") is not True:
        raise SealStateError(
            "approved seal must declare publication_authorized=true"
        )
    # Even when approved, this checker never claims the Hub was mutated.
    if seal.get("main_published") is not False:
        raise SealStateError(
            "seal checker never sets main_published; publish is out of band"
        )

    production = dict(seal.get("production") or {})
    candidate = dict(seal.get("candidate") or {})
    digests = dict(seal.get("digests") or {})
    approver = dict(seal.get("approver") or {})

    identity = assert_human_identity(approver.get("identity"))
    signature = str(approver.get("signature") or "").strip().casefold()
    if not _SHA256_RE.fullmatch(signature):
        raise ApprovalError(
            "approver.signature must be a 64-hex digest bound to exact digests"
        )

    expected = compute_approval_signature(
        digests=digests,
        candidate_revision=str(candidate.get("revision")),
        production_repo=str(production.get("dataset_id")),
        production_branch=str(production.get("branch")),
        identity=identity,
    )
    if signature != expected:
        raise ApprovalError(
            "approver.signature does not match identity + exact digests "
            f"(expected {expected})"
        )

    if str(approver.get("status") or "").casefold() != STATUS_APPROVED:
        raise ApprovalError("approver.status must be approved")
    if not approver.get("approved_at"):
        raise ApprovalError("approver.approved_at is required for an approved seal")


def check_seal(
    seal: Mapping[str, Any] | None = None,
    *,
    seal_path: Path | str | None = None,
    repo_root: Path | str | None = None,
    allow_pending: bool = False,
    require_fixture_match: bool = True,
) -> dict[str, Any]:
    """Validate a publication seal request (pending or approved)."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    path = (
        Path(seal_path).expanduser().resolve()
        if seal_path is not None
        else default_seal_path(root)
    )
    if seal is None:
        seal = load_json_mapping(path)

    assert_seal_structure(seal)

    status = str(seal.get("status") or "").casefold()
    if status == STATUS_PENDING:
        if not allow_pending:
            raise SealStateError(
                "seal is pending human approval; pass --allow-pending to "
                "validate it as a complete authorization request, or supply an "
                "approved seal with external human identity and signature"
            )
        assert_pending_seal(seal)
    elif status == STATUS_APPROVED:
        assert_approved_seal(seal)
    else:
        raise SealStateError(f"unsupported seal status: {status!r}")

    mismatches: list[str] = []
    if require_fixture_match and status == STATUS_PENDING:
        fresh = build_pending_seal(repo_root=root)
        assert_seal_structure(fresh)
        assert_pending_seal(fresh)
        mismatches = compare_seals(fresh, seal)
        if mismatches:
            raise MismatchError(
                "publication seal mismatch: " + "; ".join(mismatches[:16])
            )

    return {
        "ok": True,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "seal_path": repo_relpath(path, repo_root=root)
        if path.is_file()
        else DEFAULT_SEAL_RELPATH.as_posix(),
        "seal_sha256": seal.get("seal_sha256"),
        "status": status,
        "publication_authorized": bool(seal.get("publication_authorized")),
        "main_published": False,
        "production_repo": (seal.get("production") or {}).get("dataset_id"),
        "production_branch": (seal.get("production") or {}).get("branch"),
        "candidate_revision": (seal.get("candidate") or {}).get("revision"),
        "manifest_digest": (seal.get("digests") or {}).get("manifest"),
        "validation_receipt_digest": (seal.get("digests") or {}).get(
            "validation_receipt"
        ),
        "rollback_revision": (seal.get("rollback") or {}).get("revision"),
        "allow_pending": allow_pending,
        "mismatches": [],
        "network_required": False,
    }


def compare_seals(
    fresh: Mapping[str, Any],
    sealed: Mapping[str, Any],
) -> list[str]:
    """Return human-readable mismatches between two pending seals."""

    mismatches: list[str] = []
    top_keys = (
        "schema",
        "schema_version",
        "task_id",
        "goal_id",
        "program_id",
        "producer",
        "status",
        "publication_authorized",
        "main_published",
        "network_required",
        "fixture_id",
        "release_point",
        "release_profile",
        "seal_sha256",
    )
    for key in top_keys:
        if fresh.get(key) != sealed.get(key):
            mismatches.append(
                f"{key}: fresh={fresh.get(key)!r} sealed={sealed.get(key)!r}"
            )

    for section, keys in (
        (
            "production",
            ("dataset_id", "branch", "default_config", "publication_requires_human_seal"),
        ),
        (
            "candidate",
            (
                "dataset_id",
                "revision",
                "manifest_digest",
                "release_root_cid",
                "release_point",
                "default_config",
                "staging_branch",
            ),
        ),
        (
            "rollback",
            ("dataset_id", "revision", "default_config", "legacy_files_deleted"),
        ),
    ):
        fresh_section = dict(fresh.get(section) or {})
        sealed_section = dict(sealed.get(section) or {})
        for key in keys:
            if fresh_section.get(key) != sealed_section.get(key):
                mismatches.append(
                    f"{section}.{key}: fresh={fresh_section.get(key)!r} "
                    f"sealed={sealed_section.get(key)!r}"
                )

    for key in ("manifest", "validation_receipt", "code", "config", "model"):
        fresh_d = (fresh.get("digests") or {}).get(key)
        sealed_d = (sealed.get("digests") or {}).get(key)
        if fresh_d != sealed_d:
            mismatches.append(
                f"digests.{key}: fresh={fresh_d!r} sealed={sealed_d!r}"
            )

    if fresh.get("requested_mutations") != sealed.get("requested_mutations"):
        mismatches.append("requested_mutations differ")

    return mismatches


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_uscode_publication_seal.py",
        description=(
            "Assemble and validate the human publication-seal request for US "
            f"Code sparse GraphRAG ({TASK_ID}). Agents may only assemble and "
            "validate; they cannot self-authorize or publish."
        ),
    )
    parser.add_argument(
        "--seal",
        type=Path,
        default=None,
        help=(
            "Path to the publication seal "
            f"(default: {DEFAULT_SEAL_RELPATH.as_posix()})"
        ),
    )
    parser.add_argument(
        "--allow-pending",
        action="store_true",
        help=(
            "Accept a pending seal as a complete authorization request "
            "(default sealed artifact is pending; approval is human-only)"
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write/refresh the sealed pending publication-seal request",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the sealed request (default when --seal is provided)",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the check result (or seal with --write) as JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for JSON output",
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
    except SecretLeakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    seal_path = (
        Path(args.seal).expanduser().resolve()
        if args.seal is not None
        else default_seal_path()
    )

    try:
        if args.write:
            seal, written = materialize_default_seal(path=seal_path)
            assert_seal_structure(seal)
            assert_pending_seal(seal)
            print(f"wrote pending publication seal: {written}", file=sys.stderr)
            if args.print_json:
                write_json(
                    Path(args.output).expanduser().resolve()
                    if args.output is not None
                    else None,
                    seal,
                )
            # Still run the check path when both --write and --check/--allow-pending.
            if not (args.check or args.allow_pending or args.seal is not None):
                print(
                    "ok=True task_id={task_id} status=pending "
                    "publication_authorized=False main_published=False "
                    "seal_sha256={seal_sha256}".format(
                        task_id=seal["task_id"],
                        seal_sha256=seal.get("seal_sha256") or "",
                    ),
                    file=sys.stderr,
                )
                return 0

        # Default when --seal is provided: check the seal.
        if not seal_path.is_file():
            raise MissingInputError(
                f"seal not found: {seal_path}; pass --write to materialize "
                "a pending request"
            )

        result = check_seal(
            seal_path=seal_path,
            allow_pending=bool(args.allow_pending),
            require_fixture_match=True,
        )

        if args.print_json or args.output is not None:
            write_json(
                Path(args.output).expanduser().resolve()
                if args.output is not None
                else None,
                result,
            )

        print(
            "ok={ok} task_id={task_id} status={status} "
            "publication_authorized={publication_authorized} "
            "main_published={main_published} "
            "production_repo={production_repo} "
            "candidate_revision={candidate_revision} "
            "seal_sha256={seal_sha256}".format(
                ok=result.get("ok"),
                task_id=result.get("task_id"),
                status=result.get("status"),
                publication_authorized=result.get("publication_authorized"),
                main_published=result.get("main_published"),
                production_repo=result.get("production_repo"),
                candidate_revision=result.get("candidate_revision"),
                seal_sha256=result.get("seal_sha256") or "",
            ),
            file=sys.stderr,
        )
        return 0 if result.get("ok") else 1

    except (
        PublicationSealError,
        MissingInputError,
        MismatchError,
        SealStateError,
        ApprovalError,
        PathLeakError,
        SecretLeakError,
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
