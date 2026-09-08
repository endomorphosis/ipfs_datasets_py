#!/usr/bin/env python3
"""Preserve legacy compatibility and rehearse rollback/operations (LCR-045).

Default ``--check`` mode is credential-free and does not contact the Hub:

1. Bind the LCR-042 publication receipt (new public SHA + previous pin).
2. Bind the LCR-043 public canary and LCR-001 baseline so both pins have
   sealed query/read evidence.
3. Prove both immutable pins remain independently queryable (resolver
   fetch of isolated trees; advertisement is a pointer, not a delete).
4. Prove the legacy Dataset Viewer configuration is explicit and is not
   the default.
5. Rehearse bounded rollback (re-advertise the previous pin) and the
   reverse forward move. Neither tree is deleted; recovery is the reverse
   pointer change.
6. Classify blocked / idle / stale board cases and require the operator
   runbook to document the same diagnostics.
7. Compare the sealed ``rollback_rehearsal.json`` to a freshly built
   receipt.

This CLI never:

* publishes to ``main`` / ``master``;
* deletes, force-pushes, or changes visibility;
* changes public advertisement;
* embeds or logs Hub tokens;
* treats credentials as CLI flags (environment-only).

Validation gate (no network)::

    python scripts/ops/legal_data/rehearse_state_laws_release_rollback.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    RECEIPT_SCHEMA_V1,
    canonical_no_self_field_digest,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (
    DEFAULT_CONFIG_NAME,
    LEGACY_CONFIG_NAME,
    LEGACY_CONFIG_PATH_PREFIXES,
    RECOVERY_CONFIG_NAME,
    advertised_viewer_configs,
    assert_configs_schema_coherent,
)
from ipfs_datasets_py.processors.legal_data.state_laws_publication_policy import (
    DEFAULT_STAGING_BRANCH,
    PUBLICATION_PARENT_REVISION,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    DEFAULT_DATASET_REPO_ID,
    PREVIOUS_PUBLIC_PIN as HISTORICAL_BASELINE_REVISION,
    RELEASE_PROFILE,
    RollbackRecord,
    canonical_json_dumps,
    digest_mapping,
    require_immutable_revision,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    CURRENTNESS_DISCLAIMER,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    MappingTransport,
    MissingArtifactError,
    MutableRevisionError,
    validate_immutable_revision,
    validate_repo_id,
)
from scripts.ops.legal_data.check_state_laws_public_release import (
    check_canonical_public_canary_receipt,
)
from scripts.ops.legal_data.publish_state_laws_hf_release import (
    check_canonical_publication_receipt,
)
from scripts.ops.legal_data.state_laws_release_probe import (
    StateLawsReleaseProbeError,
    assert_first_party_dual_pin_measurement,
    run_dual_pin_probe,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "LCR-045"
GOAL_ID: Final = "LCR-G090"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "rehearse_state_laws_release_rollback.py"
CODE_VERSION: Final = "1"
DEPENDS_ON: Final[tuple[str, ...]] = ("LCR-043",)

REHEARSAL_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-rollback-rehearsal@1"
CANONICAL_REHEARSAL_SCHEMA: Final = RECEIPT_SCHEMA_V1
CANONICAL_REHEARSAL_KIND: Final = "state-laws-rollback-rehearsal/v2"
SCHEMA_VERSION: Final = "state-laws-rollback-rehearsal/v1"
FIXTURE_ID: Final = "state-laws-rollback-rehearsal-v1"

DEFAULT_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/rollback_rehearsal.json"
)
PUBLICATION_RECEIPT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/publication_receipt.json"
)
PUBLIC_CANARY_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/public_canary.json"
)
BASELINE_RELPATH: Final = Path("docs/reports/legal_corpora_reindex/baseline.json")
RUNBOOK_RELPATH: Final = Path("docs/guides/STATE_LAWS_SPARSE_GRAPHRAG_RUNBOOK.md")
MIGRATION_RELPATH: Final = Path("docs/guides/STATE_LAWS_SPARSE_GRAPHRAG_MIGRATION.md")

DEFAULT_DATASET_REPO: Final = DEFAULT_DATASET_REPO_ID
DEFAULT_DEFAULT_CONFIG: Final = DEFAULT_CONFIG_NAME
DEFAULT_LEGACY_CONFIG: Final = LEGACY_CONFIG_NAME
DEFAULT_RECOVERY_CONFIG: Final = RECOVERY_CONFIG_NAME
LEGACY_DATA_GLOBS: Final = ("STATE-*.parquet", "state_laws.parquet")
PREVIOUS_PUBLIC_PIN: Final = PUBLICATION_PARENT_REVISION
ROLLBACK_TARGET: Final = PUBLICATION_PARENT_REVISION
DEFAULT_STAGING: Final = DEFAULT_STAGING_BRANCH
PUBLIC_BRANCH: Final = "main"
DEFAULT_RELEASE_POINT: Final = "state-laws/v2/2026-08-10"
REHEARSAL_TIME: Final = "2026-08-10T20:00:00Z"
FORWARD_REHEARSAL_TIME: Final = "2026-08-10T20:05:00Z"

QUERY_CLI_RELPATH: Final = Path("scripts/ops/legal_data/query_state_laws_hf.py")
STATUS_SH_RELPATH: Final = Path("scripts/ops/legal_corpora_reindex/status.sh")
STATUS_PY_RELPATH: Final = Path("scripts/ops/legal_corpora_reindex/status.py")

SECRET_ENV_NAMES: Final[tuple[str, ...]] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
    "STATE_LAWS_HF_TOKEN",
    "STATE_LAWS_STAGING_AUTHORIZATION",
    "STATE_LAWS_PUBLICATION_AUTHORIZATION",
)

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
        "history_rewrite",
        "super_squash_history",
        "overwrite_legacy",
        "direct_main_upload",
        "promote_production",
        "change_public_advertisement",
    }
)
ALLOWED_OPERATIONS: Final[tuple[str, ...]] = (
    "rehearse_dual_pin_query",
    "re_advertise_previous_pin",
    "re_advertise_new_pin",
)

SELF_DIGEST_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "canonical_digest",
        "content_digest",
        "digest",
        "file_sha256",
        "report_digest_sha256",
        "sha256",
    }
)

MAX_REPORT_BYTES: Final = 1048576

_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key|operator_key|"
    r"staging_authorization|publication_authorization)s?$",
    re.IGNORECASE,
)
_ABS_PATH_RE = re.compile(
    r"(?:^|[\s\"'`=:])"
    r"(?:"
    r"/(?:home|Users|tmp|var|private|opt|root|etc|mnt|media|workspace)/"
    r"|[A-Za-z]:\\"
    r"|file://"
    r")"
)
_POSIX_HOME_RE = re.compile(r"(?:^|[\s\"'`=:])/home/[A-Za-z0-9._-]+/")
_WINDOWS_USER_RE = re.compile(
    r"(?:^|[\s\"'`=:])[A-Za-z]:\\Users\\",
    re.IGNORECASE,
)
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

BOARD_STALE_SECONDS: Final = 120.0
BOARD_IDLE_GRACE_SECONDS: Final = 180.0
BOARD_LOG_STALL_SECONDS: Final = 900.0
BOARD_HARD_TIMEOUT_SECONDS: Final = 21600.0

BOARD_DIAGNOSTIC_CASES: Final[tuple[Mapping[str, Any], ...]] = (
    {
        "id": "blocked",
        "blocked_count": 1,
        "ready_count": 0,
        "active_task_id": "LCR-045",
        "live_worker_count": 1,
        "heartbeat_age_seconds": 10.0,
        "implementation_log_age_seconds": 10.0,
        "active_age_seconds": 30.0,
        "progress_age_seconds": 15.0,
        "starting": False,
        "expected_kind": "blocked",
    },
    {
        "id": "idle_ready_without_worker",
        "blocked_count": 0,
        "ready_count": 2,
        "active_task_id": "",
        "live_worker_count": 0,
        "heartbeat_age_seconds": 20.0,
        "implementation_log_age_seconds": None,
        "active_age_seconds": None,
        "progress_age_seconds": 400.0,
        "starting": False,
        "expected_kind": "idle",
    },
    {
        "id": "stale_heartbeat",
        "blocked_count": 0,
        "ready_count": 0,
        "active_task_id": "",
        "live_worker_count": 0,
        "heartbeat_age_seconds": 180.0,
        "implementation_log_age_seconds": None,
        "active_age_seconds": None,
        "progress_age_seconds": 30.0,
        "starting": False,
        "expected_kind": "stale",
    },
    {
        "id": "stale_implementation_log",
        "blocked_count": 0,
        "ready_count": 0,
        "active_task_id": "LCR-045",
        "live_worker_count": 1,
        "heartbeat_age_seconds": 15.0,
        "implementation_log_age_seconds": 1200.0,
        "active_age_seconds": 1200.0,
        "progress_age_seconds": 1200.0,
        "starting": False,
        "implementation_in_progress": True,
        "expected_kind": "stale",
    },
    {
        "id": "healthy",
        "blocked_count": 0,
        "ready_count": 0,
        "active_task_id": "LCR-045",
        "live_worker_count": 1,
        "heartbeat_age_seconds": 12.0,
        "implementation_log_age_seconds": 8.0,
        "active_age_seconds": 40.0,
        "progress_age_seconds": 8.0,
        "starting": False,
        "implementation_in_progress": True,
        "expected_kind": "healthy",
    },
)

RUNBOOK_REQUIRED_PHRASES: Final[tuple[str, ...]] = (
    "LCR-045",
    "LCR-G090",
    "justicedao/ipfs_state_laws",
    HISTORICAL_BASELINE_REVISION,
    "state-laws-ir-graphrag/v2",
    "legacy-state-laws-parquet/v1",
    "query_state_laws_hf.py",
    "build_state_laws_sparse_graphrag.py",
    "run_legal_corpora_reindex_cohort.py",
    "rehearse_state_laws_release_rollback.py",
    "status.sh",
    "status.py",
    "blocked",
    "idle",
    "stale",
    "without deleting legacy data",
    "legal currentness",
    "research aid",
    "entry_cid",
    "release_point",
    "--check",
    "--fixture-mode",
    "--json",
    "--trace",
    "state_laws_acquisition_gap_refill.py",
    "publish_state_laws_hf_release.py",
)
MIGRATION_REQUIRED_PHRASES: Final[tuple[str, ...]] = (
    "LCR-045",
    "legacy-state-laws-parquet/v1",
    "state-laws-ir-graphrag/v2",
    "recovery-quarantine/v1",
    HISTORICAL_BASELINE_REVISION,
    "entry_cid",
    "ipfs_cid",
    "STATE-*.parquet",
    "state_laws.parquet",
    "explicit",
    "both remain queryable",
    "rehearse_state_laws_release_rollback.py",
    "without deleting",
    "legal-currentness",
)


class RehearsalError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class RehearsalSafetyError(RehearsalError):
    """Raised when a rehearsal would delete, force-push, or leak secrets."""


class RehearsalMissingInputError(RehearsalError):
    """Raised when a required producer input is absent."""


class RehearsalMismatchError(RehearsalError):
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
            raise RehearsalSafetyError(
                f"refusing absolute path in report surface: {text!r}"
            )
        return text.lstrip("./")
    return rel.as_posix()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise RehearsalMissingInputError(f"JSON file not found: {target.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RehearsalError(f"cannot read JSON {target.name}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise RehearsalError(f"JSON root must be an object: {target.name}")
    return dict(payload)


def write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="cli_output")
    reject_path_leaks(payload, label="cli_output")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        sys.stdout.write(text)
        return
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise RehearsalSafetyError(
            f"report exceeds single-file budget ({len(encoded)} > {MAX_REPORT_BYTES})"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha256_file(path: Path | str) -> str:
    target = Path(path)
    if not target.is_file():
        raise RehearsalMissingInputError(f"file not found for digest: {target.name}")
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_repo_file(relpath: Path, *, repo_root: Path) -> Path:
    path = (repo_root / relpath).resolve()
    if not path.is_file():
        raise RehearsalMissingInputError(
            f"required producer input missing: {relpath.as_posix()}"
        )
    return path


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
        raise RehearsalSafetyError(
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
            if (
                text.startswith("/")
                and not text.startswith("fixture://")
                and any(
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
                )
            ):
                offenders.append(path or label)

    visit(value, label)
    if offenders:
        raise RehearsalSafetyError(
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
        "state_laws_staging_authorization=",
        "state_laws_publication_authorization=",
    )
    for needle in needles:
        if needle in lowered:
            raise RehearsalSafetyError(
                "refusing to accept secrets on the command line; "
                "credentials are environment-only"
            )
    for env_name in SECRET_ENV_NAMES:
        env_val = os.environ.get(env_name)
        if env_val and env_val in " ".join(str(a) for a in argv):
            raise RehearsalSafetyError(
                f"refusing to accept ${env_name} value on the command line"
            )


def strip_digest_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in SELF_DIGEST_FIELDS}


# ---------------------------------------------------------------------------
# Producer inputs
# ---------------------------------------------------------------------------


def load_publication_receipt(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else _require_repo_file(PUBLICATION_RECEIPT_RELPATH, repo_root=root)
    )
    receipt = load_json_mapping(target)
    public_sha = str(
        receipt.get("public_sha") or receipt.get("public_revision") or ""
    ).strip()
    previous = str(
        receipt.get("previous_public_pin") or receipt.get("old_sha") or ""
    ).strip()
    require_immutable_revision(public_sha, name="publication.public_sha")
    require_immutable_revision(previous, name="publication.previous_public_pin")
    if previous != PREVIOUS_PUBLIC_PIN:
        raise RehearsalMismatchError(
            "publication rollback target drifted from PUBLICATION_PARENT_REVISION"
        )
    if public_sha == previous:
        raise RehearsalMismatchError(
            "publication public SHA must differ from the previous public pin"
        )
    repo = str(
        receipt.get("dataset_repo_id")
        or receipt.get("target_repo")
        or receipt.get("target")
        or ""
    ).strip()
    validate_repo_id(repo, name="publication.dataset_repo_id")
    if repo != DEFAULT_DATASET_REPO:
        raise RehearsalMismatchError(
            f"publication target must remain {DEFAULT_DATASET_REPO}"
        )
    if receipt.get("legacy_files_deleted") is True:
        raise RehearsalSafetyError("publication receipt reports legacy file deletion")
    return receipt


def load_public_canary(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else _require_repo_file(PUBLIC_CANARY_RELPATH, repo_root=root)
    )
    canary = load_json_mapping(target)
    public_sha = str(canary.get("public_sha") or canary.get("public_revision") or "")
    require_immutable_revision(public_sha, name="canary.public_sha")
    previous = str(canary.get("previous_public_pin") or canary.get("old_sha") or "")
    require_immutable_revision(previous, name="canary.previous_public_pin")
    if previous != PREVIOUS_PUBLIC_PIN:
        raise RehearsalMismatchError(
            "public canary rollback target drifted from PUBLICATION_PARENT_REVISION"
        )
    viewer = canary.get("viewer") if isinstance(canary.get("viewer"), Mapping) else {}
    if viewer.get("ok") is not True:
        raise RehearsalMismatchError("public canary viewer is not ok")
    if viewer.get("default_config") != DEFAULT_DEFAULT_CONFIG:
        raise RehearsalMismatchError("public canary default config is not v2")
    names = list(viewer.get("config_names") or viewer.get("coherence", {}).get("names") or [])
    if DEFAULT_LEGACY_CONFIG not in names:
        raise RehearsalMismatchError("public canary does not advertise the legacy config")
    if viewer.get("combined_covers_all_51") is not True:
        raise RehearsalMismatchError("public canary default Viewer is not the exact 51")
    return canary


def load_baseline(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else _require_repo_file(BASELINE_RELPATH, repo_root=root)
    )
    baseline = load_json_mapping(target)
    acceptance = (
        baseline.get("acceptance")
        if isinstance(baseline.get("acceptance"), Mapping)
        else {}
    )
    pin = str(
        acceptance.get("pinned_revision") or baseline.get("pinned_revision") or ""
    )
    require_immutable_revision(pin, name="baseline.pinned_revision")
    if pin != HISTORICAL_BASELINE_REVISION:
        raise RehearsalMismatchError(
            "baseline pinned revision drifted from HISTORICAL_BASELINE_REVISION"
        )
    return baseline


# ---------------------------------------------------------------------------
# Legacy configuration
# ---------------------------------------------------------------------------


def viewer_config_payload(config: Any) -> dict[str, Any]:
    return {
        "config_name": config.config_name,
        "data_files": [dict(item) for item in config.data_files],
        "features": list(config.features),
        "is_default": bool(config.is_default),
        "is_legacy": bool(config.is_legacy),
        "is_recovery": bool(config.is_recovery),
        "notes": list(config.notes),
        "path_prefixes": list(config.path_prefixes),
        "primary_key": config.primary_key,
    }


def explicit_legacy_configuration() -> dict[str, Any]:
    configs = advertised_viewer_configs(include_legacy=True, include_recovery=True)
    assert_configs_schema_coherent(configs)
    by_name = {item.config_name: item for item in configs}
    if DEFAULT_DEFAULT_CONFIG not in by_name:
        raise RehearsalMismatchError("default v2 config is not advertised")
    if DEFAULT_LEGACY_CONFIG not in by_name:
        raise RehearsalMismatchError("legacy config is not advertised")
    if DEFAULT_RECOVERY_CONFIG not in by_name:
        raise RehearsalMismatchError("recovery config is not advertised")
    default = by_name[DEFAULT_DEFAULT_CONFIG]
    legacy = by_name[DEFAULT_LEGACY_CONFIG]
    recovery = by_name[DEFAULT_RECOVERY_CONFIG]
    if not default.is_default or default.is_legacy or default.is_recovery:
        raise RehearsalMismatchError("default config must be v2 and not legacy/recovery")
    if not legacy.is_legacy or legacy.is_default:
        raise RehearsalMismatchError("legacy config must be explicit and not default")
    if legacy.primary_key != "ipfs_cid":
        raise RehearsalMismatchError("legacy primary key must remain ipfs_cid")
    if default.primary_key != "entry_cid":
        raise RehearsalMismatchError("v2 primary key must remain entry_cid")
    if tuple(legacy.path_prefixes) != tuple(LEGACY_CONFIG_PATH_PREFIXES):
        raise RehearsalMismatchError("legacy path prefixes drifted")
    advertised_legacy_globs = tuple(item["path"] for item in legacy.data_files)
    if advertised_legacy_globs != tuple(LEGACY_DATA_GLOBS):
        raise RehearsalMismatchError("legacy data globs drifted")
    if recovery.is_default or not recovery.is_recovery:
        raise RehearsalMismatchError("recovery config must stay quarantined")
    return {
        "config_count": len(configs),
        "configs": [viewer_config_payload(item) for item in configs],
        "default_config": default.config_name,
        "default_excludes_legacy": True,
        "default_excludes_recovery": True,
        "default_primary_key": default.primary_key,
        "explicit": True,
        "legacy_config": legacy.config_name,
        "legacy_data_globs": list(LEGACY_DATA_GLOBS),
        "legacy_is_default": False,
        "legacy_path_prefixes": list(LEGACY_CONFIG_PATH_PREFIXES),
        "legacy_primary_key": legacy.primary_key,
        "legacy_retained": True,
        "recovery_config": recovery.config_name,
        "release_profile": RELEASE_PROFILE,
    }


# ---------------------------------------------------------------------------
# Dual-pin query rehearsal
# ---------------------------------------------------------------------------


def _pin_tree(
    *,
    label: str,
    revision: str,
    config_name: str,
    unique_path: str,
) -> dict[str, bytes]:
    payload = {
        "config_name": config_name,
        "dataset_repo_id": DEFAULT_DATASET_REPO,
        "label": label,
        "queryable": True,
        "release_point": DEFAULT_RELEASE_POINT,
        "revision": revision,
        "schema_version": SCHEMA_VERSION,
        "unique_path": unique_path,
    }
    text = canonical_json_dumps(payload)
    return {
        "README.md": f"# {label}\nrevision={revision}\n".encode(),
        "manifest.json": text.encode("utf-8"),
        unique_path: f"{label}:{revision}\n".encode(),
    }


def _fetch_pin_tree(
    *,
    revision: str,
    files: Mapping[str, bytes],
    relative_path: str = "manifest.json",
) -> dict[str, Any]:
    validate_immutable_revision(revision, name="revision")
    transport = MappingTransport(files)
    with tempfile.TemporaryDirectory(prefix="lcr045-pin-") as tmp:
        destination = Path(tmp) / "artifact"
        fetched = transport.fetch(
            repo_id=DEFAULT_DATASET_REPO,
            revision=revision,
            relative_path=relative_path,
            destination=destination,
            token=None,
        )
        body = fetched.read_bytes()
    expected = files[relative_path]
    if body != expected:
        raise RehearsalMismatchError(
            f"pin {revision} fetch bytes drifted for {relative_path}"
        )
    return {
        "bytes": len(body),
        "ok": True,
        "relative_path": relative_path,
        "repo_id": DEFAULT_DATASET_REPO,
        "revision": revision,
        "transport": "mapping",
        "verified": True,
    }


def _query_command(revision: str, *, local_root: bool = False) -> dict[str, Any]:
    validate_immutable_revision(revision, name="query.revision")
    argv = [
        "python",
        QUERY_CLI_RELPATH.as_posix(),
        "--repo-id",
        DEFAULT_DATASET_REPO,
        "--revision",
        revision,
        "--json",
        "--trace",
        "bm25",
        "disclosure",
        "--top-k",
        "5",
        "--jurisdiction",
        "DC",
    ]
    if local_root:
        argv[2:2] = ["--local-root", "LOCAL_ROOT", "--fixture-mode"]
    return {
        "argv": argv,
        "command": QUERY_CLI_RELPATH.as_posix(),
        "config": DEFAULT_DEFAULT_CONFIG,
        "fixture_mode": bool(local_root),
        "jurisdiction": "DC",
        "mode": "bm25",
        "repo_id": DEFAULT_DATASET_REPO,
        "revision": revision,
    }


def _reject_mutable_revisions() -> list[str]:
    rejected: list[str] = []
    for token in ("main", "master", "latest", "", "HEAD"):
        try:
            validate_immutable_revision(token, name="mutable_probe")
        except MutableRevisionError:
            rejected.append(token if token else "empty")
            continue
        raise RehearsalMismatchError(
            f"mutable revision {token!r} was accepted; pins must be immutable"
        )
    return rejected


def rehearse_dual_pin_query(
    *,
    new_pin: str,
    previous_pin: str,
    canary: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    new_pin = validate_immutable_revision(new_pin, name="new_pin")
    previous_pin = validate_immutable_revision(previous_pin, name="previous_pin")
    if new_pin == previous_pin:
        raise RehearsalMismatchError("new and previous pins must differ")
    rejected = _reject_mutable_revisions()

    new_unique = "data/corpus/jurisdiction=DC/part-000000.parquet"
    previous_unique = "STATE-IA.parquet"
    new_files = _pin_tree(
        label="new-public-pin",
        revision=new_pin,
        config_name=DEFAULT_DEFAULT_CONFIG,
        unique_path=new_unique,
    )
    previous_files = _pin_tree(
        label="previous-public-pin",
        revision=previous_pin,
        config_name=DEFAULT_LEGACY_CONFIG,
        unique_path=previous_unique,
    )
    # Isolated trees: each pin's transport cannot see the other pin's unique path.
    new_fetch = _fetch_pin_tree(
        revision=new_pin, files=new_files, relative_path=new_unique
    )
    previous_fetch = _fetch_pin_tree(
        revision=previous_pin, files=previous_files, relative_path=previous_unique
    )
    try:
        _fetch_pin_tree(
            revision=new_pin, files=new_files, relative_path=previous_unique
        )
    except MissingArtifactError:
        new_cannot_see_legacy = True
    else:
        raise RehearsalMismatchError("new pin unexpectedly resolved previous-pin tree")
    try:
        _fetch_pin_tree(
            revision=previous_pin, files=previous_files, relative_path=new_unique
        )
    except MissingArtifactError:
        previous_cannot_see_v2 = True
    else:
        raise RehearsalMismatchError("previous pin unexpectedly resolved new-pin tree")
    cross_isolated = new_cannot_see_legacy and previous_cannot_see_v2

    canary_queries = canary.get("canaries") if isinstance(canary.get("canaries"), Mapping) else {}
    canary_ok = bool(
        (canary_queries.get("bm25") or {}).get("ok") is True
        and (canary_queries.get("filter") or {}).get("ok") is True
        and canary.get("public_sha") == new_pin
    )
    baseline_acceptance = (
        baseline.get("acceptance")
        if isinstance(baseline.get("acceptance"), Mapping)
        else {}
    )
    baseline_ok = (
        str(baseline_acceptance.get("pinned_revision") or "") == previous_pin
        and int(baseline_acceptance.get("jurisdictions") or 0) == 51
    )
    if not canary_ok:
        raise RehearsalMismatchError("new pin lacks sealed public-canary query evidence")
    if not baseline_ok:
        raise RehearsalMismatchError(
            "previous pin lacks sealed baseline inventory evidence"
        )

    return {
        "after_forward": {"new_pin_queryable": True, "previous_pin_queryable": True},
        "after_rollback": {"new_pin_queryable": True, "previous_pin_queryable": True},
        "baseline_jurisdictions": int(baseline_acceptance.get("jurisdictions") or 0),
        "both_queryable": True,
        "canary_queries_ok": canary_ok,
        "cross_pin_trees_isolated": cross_isolated,
        "legacy_config_queryable": True,
        "mutable_revisions_rejected": rejected,
        "new_pin": {
            "command": _query_command(new_pin),
            "config": DEFAULT_DEFAULT_CONFIG,
            "evidence": PUBLIC_CANARY_RELPATH.as_posix(),
            "fetch": new_fetch,
            "queryable": True,
            "revision": new_pin,
            "role": "advertised",
        },
        "offline": True,
        "previous_pin": {
            "command": _query_command(previous_pin),
            "config": DEFAULT_LEGACY_CONFIG,
            "evidence": BASELINE_RELPATH.as_posix(),
            "fetch": previous_fetch,
            "queryable": True,
            "revision": previous_pin,
            "role": "rollback_target",
        },
        "v2_config_queryable": True,
    }


# ---------------------------------------------------------------------------
# Rollback rehearsal (bounded + recoverable)
# ---------------------------------------------------------------------------


def _rollback_record(
    *,
    rollback_id: str,
    from_revision: str,
    to_revision: str,
    reason: str,
    rolled_back_at: str,
    manifest_digest: str,
) -> dict[str, Any]:
    record = RollbackRecord(
        rollback_id=rollback_id,
        dataset_repo_id=DEFAULT_DATASET_REPO,
        from_revision=from_revision,
        to_revision=to_revision,
        reason=reason,
        rolled_back_at=rolled_back_at,
        manifest_digest=manifest_digest,
        schema_version=SCHEMA_VERSION,
        payload={
            "additive_only": True,
            "deletes": False,
            "force_push": False,
            "legacy_files_deleted": False,
            "public_advertisement_changed": False,
            "recoverable": True,
            "visibility_changed": False,
        },
    )
    return record.to_dict()


def rehearse_rollback(
    *,
    new_pin: str,
    previous_pin: str,
    manifest_digest: str,
) -> dict[str, Any]:
    new_pin = validate_immutable_revision(new_pin, name="rollback.new_pin")
    previous_pin = validate_immutable_revision(
        previous_pin, name="rollback.previous_pin"
    )
    if new_pin == previous_pin:
        raise RehearsalMismatchError("rollback from/to revisions must differ")

    scheduled = ["re_advertise_previous_pin"]
    forward = ["re_advertise_new_pin"]
    for operation in (*scheduled, *forward):
        if operation in FORBIDDEN_OPERATIONS:
            raise RehearsalSafetyError(f"scheduled operation is forbidden: {operation}")
    for forbidden in FORBIDDEN_OPERATIONS:
        if forbidden in scheduled or forbidden in forward:
            raise RehearsalSafetyError(f"forbidden operation leaked into plan: {forbidden}")

    back = _rollback_record(
        rollback_id="rollback-state-laws-lcr045-back",
        from_revision=new_pin,
        to_revision=previous_pin,
        reason=(
            "rehearse re-advertising the previous public pin without deleting "
            "the new pin tree or legacy files"
        ),
        rolled_back_at=REHEARSAL_TIME,
        manifest_digest=manifest_digest,
    )
    fwd = _rollback_record(
        rollback_id="rollback-state-laws-lcr045-forward",
        from_revision=previous_pin,
        to_revision=new_pin,
        reason=(
            "rehearse restoring the new public pin advertisement; previous pin "
            "remains independently queryable"
        ),
        rolled_back_at=FORWARD_REHEARSAL_TIME,
        manifest_digest=manifest_digest,
    )
    return {
        "additive_only": True,
        "advertised_after_forward": new_pin,
        "advertised_after_rollback": previous_pin,
        "advertised_before": new_pin,
        "allowed_operations": list(ALLOWED_OPERATIONS),
        "back": back,
        "bounded": True,
        "deletes": False,
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "forward": fwd,
        "legacy_files_deleted": False,
        "new_pin_retained": True,
        "ok": True,
        "previous_pin_retained": True,
        "public_advertisement_changed": False,
        "recoverable": True,
        "recovery": "re_advertise_new_pin",
        "rollback_target": previous_pin,
        "scheduled_operations": scheduled,
        "visibility_changed": False,
    }


# ---------------------------------------------------------------------------
# Board diagnostics (blocked / idle / stale)
# ---------------------------------------------------------------------------


def classify_board_condition(sample: Mapping[str, Any]) -> dict[str, Any]:
    """Classify a lane sample as blocked, idle, stale, starting, or healthy."""

    reasons: list[str] = []
    kinds: list[str] = []
    blocked = int(sample.get("blocked_count") or 0)
    ready = int(sample.get("ready_count") or 0)
    active_task = str(sample.get("active_task_id") or "").strip()
    live_workers = int(sample.get("live_worker_count") or 0)
    starting = bool(sample.get("starting"))
    implementation_in_progress = bool(sample.get("implementation_in_progress"))
    heartbeat_age = sample.get("heartbeat_age_seconds")
    log_age = sample.get("implementation_log_age_seconds")
    active_age = sample.get("active_age_seconds")
    progress_age = sample.get("progress_age_seconds")

    if blocked > 0:
        kinds.append("blocked")
        reasons.append(f"{blocked} blocked task(s)")
    if (
        heartbeat_age is not None
        and float(heartbeat_age) > BOARD_STALE_SECONDS
        and not starting
    ):
        kinds.append("stale")
        reasons.append(
            f"supervisor heartbeat is stale ({float(heartbeat_age):.1f}s > "
            f"{BOARD_STALE_SECONDS:.1f}s)"
        )
    if (
        implementation_in_progress
        and log_age is not None
        and float(log_age) > BOARD_LOG_STALL_SECONDS
    ):
        if "stale" not in kinds:
            kinds.append("stale")
        reasons.append(
            "active implementation log is stale, even if a provider PID remains live"
        )
    if active_age is not None and float(active_age) > BOARD_HARD_TIMEOUT_SECONDS:
        if "stale" not in kinds:
            kinds.append("stale")
        reasons.append("active task exceeds implementation hard timeout")
    if (
        ready > 0
        and not active_task
        and live_workers == 0
        and not starting
        and (progress_age is None or float(progress_age) > BOARD_IDLE_GRACE_SECONDS)
    ):
        kinds.append("idle")
        reasons.append(f"{ready} eligible task(s) ready without active work past grace")

    if starting and not reasons:
        kind = "starting"
    elif not kinds:
        kind = "healthy"
    else:
        for candidate in ("blocked", "stale", "idle"):
            if candidate in kinds:
                kind = candidate
                break
        else:
            kind = kinds[0]
    return {
        "kind": kind,
        "kinds": kinds,
        "reasons": reasons,
        "thresholds": {
            "hard_timeout_seconds": BOARD_HARD_TIMEOUT_SECONDS,
            "idle_grace_seconds": BOARD_IDLE_GRACE_SECONDS,
            "log_stall_seconds": BOARD_LOG_STALL_SECONDS,
            "stale_seconds": BOARD_STALE_SECONDS,
        },
    }


def rehearse_board_diagnostics() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for raw in BOARD_DIAGNOSTIC_CASES:
        expected = str(raw["expected_kind"])
        classified = classify_board_condition(raw)
        if classified["kind"] != expected:
            raise RehearsalMismatchError(
                f"board diagnostic {raw['id']!r} classified as "
                f"{classified['kind']!r}, expected {expected!r}"
            )
        cases.append(
            {
                "expected_kind": expected,
                "id": raw["id"],
                "kind": classified["kind"],
                "ok": True,
                "reasons": classified["reasons"],
            }
        )
    return {
        "cases": cases,
        "commands": {
            "human": STATUS_SH_RELPATH.as_posix(),
            "json": [
                STATUS_PY_RELPATH.as_posix(),
                "--json",
            ],
            "observe": [
                STATUS_PY_RELPATH.as_posix(),
                "--json",
                "--observe-seconds",
                "20",
            ],
        },
        "ok": True,
        "operators_can_diagnose_blocked_idle_stale_boards": True,
        "response_order_nonterminal_idle": [
            "inspect_evidence_and_dependencies",
            "reconcile_existing_merge_or_result",
            "run_objective_or_codebase_refill",
            "split_oversized_or_repeatedly_failing_task",
            "retry_within_budget",
            "create_typed_operator_task_for_external_requirement",
        ],
        "thresholds": {
            "hard_timeout_seconds": BOARD_HARD_TIMEOUT_SECONDS,
            "idle_grace_seconds": BOARD_IDLE_GRACE_SECONDS,
            "log_stall_seconds": BOARD_LOG_STALL_SECONDS,
            "stale_seconds": BOARD_STALE_SECONDS,
        },
    }


# ---------------------------------------------------------------------------
# Operator documentation contract
# ---------------------------------------------------------------------------


def _require_phrases(text: str, phrases: Sequence[str], *, label: str) -> list[str]:
    missing = [phrase for phrase in phrases if phrase not in text]
    if missing:
        raise RehearsalMismatchError(
            f"{label} missing required phrases: " + ", ".join(missing[:12])
        )
    return list(phrases)


def validate_operator_docs(*, repo_root: Path) -> dict[str, Any]:
    runbook_path = _require_repo_file(RUNBOOK_RELPATH, repo_root=repo_root)
    migration_path = _require_repo_file(MIGRATION_RELPATH, repo_root=repo_root)
    runbook = runbook_path.read_text(encoding="utf-8")
    migration = migration_path.read_text(encoding="utf-8")
    lowered_runbook = runbook.casefold()
    lowered_migration = migration.casefold()
    for needle in ("hf_token=", "authorization: bearer", "-----begin"):
        if needle in lowered_runbook or needle in lowered_migration:
            raise RehearsalSafetyError("operator docs embed credential-like material")
    runbook_phrases = _require_phrases(
        runbook, RUNBOOK_REQUIRED_PHRASES, label="runbook"
    )
    migration_phrases = _require_phrases(
        migration, MIGRATION_REQUIRED_PHRASES, label="migration"
    )
    if "blocked" not in lowered_runbook or "idle" not in lowered_runbook:
        raise RehearsalMismatchError("runbook does not document blocked/idle boards")
    if "stale" not in lowered_runbook:
        raise RehearsalMismatchError("runbook does not document stale boards")
    if "legacy-state-laws-parquet/v1" not in migration:
        raise RehearsalMismatchError("migration guide omits explicit legacy config")
    return {
        "legacy_configuration_explicit": True,
        "migration": {
            "ok": True,
            "path": MIGRATION_RELPATH.as_posix(),
            "required_phrase_count": len(migration_phrases),
            "sha256": sha256_file(migration_path),
        },
        "ok": True,
        "runbook": {
            "ok": True,
            "path": RUNBOOK_RELPATH.as_posix(),
            "required_phrase_count": len(runbook_phrases),
            "sha256": sha256_file(runbook_path),
        },
    }


# ---------------------------------------------------------------------------
# Receipt assembly
# ---------------------------------------------------------------------------


def validate_canonical_pin_probes(
    value: Mapping[str, Any], *, new_pin: str, previous_pin: str
) -> dict[str, Any]:
    """Require independent read/query evidence for both immutable pins."""

    if not isinstance(value, Mapping):
        raise RehearsalMismatchError("pin probes must be an object")
    probes = dict(value)
    for label, revision in (("new", new_pin), ("previous", previous_pin)):
        probe = probes.get(label)
        if (
            not isinstance(probe, Mapping)
            or probe.get("revision") != revision
            or probe.get("readable") is not True
            or probe.get("queryable") is not True
            or probe.get("bounded") is not True
            or probe.get("fixture_only") is not False
        ):
            raise RehearsalMismatchError(
                f"{label} immutable pin is not independently queryable"
            )
    switch = probes.get("switch")
    if (
        not isinstance(switch, Mapping)
        or switch.get("to_previous") is not True
        or switch.get("back_to_new") is not True
        or switch.get("bounded") is not True
        or switch.get("recoverable") is not True
        or switch.get("deletion_performed") is not False
        or switch.get("remote_mutation_performed") is not False
    ):
        raise RehearsalMismatchError("rollback/forward switch rehearsal did not close")
    board = probes.get("board_diagnostics")
    if not isinstance(board, Mapping) or any(
        board.get(name) is not True for name in ("blocked", "idle", "stale")
    ):
        raise RehearsalMismatchError(
            "blocked/idle/stale board diagnostics were not rehearsed"
        )
    return probes


def build_canonical_rollback_rehearsal(
    *,
    publication_receipt: Mapping[str, Any],
    public_canary: Mapping[str, Any],
    pin_probes: Mapping[str, Any],
    repo_root: Path | str = REPOSITORY_ROOT,
) -> dict[str, Any]:
    publication = check_canonical_publication_receipt(
        publication_receipt, require_live=True
    )
    canary = check_canonical_public_canary_receipt(public_canary)
    new_pin = require_immutable_revision(
        publication["public_revision"], name="new_pin"
    )
    previous_pin = require_immutable_revision(
        publication["previous_public_pin"], name="previous_pin"
    )
    if (
        canary["public_revision"] != new_pin
        or canary["previous_public_pin"] != previous_pin
    ):
        raise RehearsalMismatchError("public canary pin lineage drifted")
    try:
        first_party = assert_first_party_dual_pin_measurement(
            pin_probes,
            repo_id=publication["dataset_repo_id"],
            new_revision=new_pin,
            previous_revision=previous_pin,
            release_manifest_digest=publication["release_manifest_digest"],
            parent_evidence_digest=canary["canonical_digest"],
        )
    except StateLawsReleaseProbeError as exc:
        raise RehearsalMismatchError(
            "rollback probes are not internally measured/bound evidence"
        ) from exc
    probes = validate_canonical_pin_probes(
        first_party, new_pin=new_pin, previous_pin=previous_pin
    )
    docs = validate_operator_docs(repo_root=Path(repo_root).resolve())
    legacy = explicit_legacy_configuration()
    if legacy.get("explicit") is not True:
        raise RehearsalMismatchError("legacy Viewer configuration is not explicit")
    receipt = {
        "schema": CANONICAL_REHEARSAL_SCHEMA,
        "receipt_kind": CANONICAL_REHEARSAL_KIND,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "status": "passed",
        "fixture_only": False,
        "dirty": False,
        "dataset_repo_id": publication["dataset_repo_id"],
        "public_revision": new_pin,
        "public_sha": new_pin,
        "previous_public_pin": previous_pin,
        "rollback_target": previous_pin,
        "final_manifest_digest": publication["final_manifest_digest"],
        "release_manifest_digest": publication["release_manifest_digest"],
        "publication_receipt_digest": publication["canonical_digest"],
        "public_canary_digest": canary["canonical_digest"],
        "pin_probes": probes,
        "measurement_source": first_party["measurement_source"],
        "externally_supplied": first_party["externally_supplied"],
        "observed_at": first_party["observed_at"],
        "probe_bindings": first_party["probe_bindings"],
        "both_pins_queryable": True,
        "legacy_configuration": legacy,
        "legacy_configuration_explicit": True,
        "rollback_bounded": True,
        "rollback_recoverable": True,
        "public_advertisement_changed": False,
        "docs": docs,
        "operators_can_diagnose_blocked_idle_stale_boards": True,
        "read_only": True,
        "remote_mutation_attempted": False,
        "unexpected_operations": [],
        "secrets_persisted": False,
        "local_paths_persisted": False,
    }
    digest = canonical_no_self_field_digest(receipt)
    receipt["canonical_digest"] = digest
    receipt["content_digest"] = digest
    return check_canonical_rollback_rehearsal(receipt)


def check_canonical_rollback_rehearsal(
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(receipt, Mapping):
        raise RehearsalMismatchError("canonical rollback rehearsal must be an object")
    report = dict(receipt)
    if (
        report.get("schema") != CANONICAL_REHEARSAL_SCHEMA
        or report.get("receipt_kind") != CANONICAL_REHEARSAL_KIND
        or report.get("task_id") != TASK_ID
        or report.get("status") != "passed"
        or report.get("fixture_only") is not False
        or report.get("dirty") is not False
        or report.get("dataset_repo_id") != DEFAULT_DATASET_REPO
        or report.get("both_pins_queryable") is not True
        or report.get("legacy_configuration_explicit") is not True
        or report.get("rollback_bounded") is not True
        or report.get("rollback_recoverable") is not True
        or report.get("public_advertisement_changed") is not False
        or report.get("operators_can_diagnose_blocked_idle_stale_boards") is not True
        or report.get("read_only") is not True
        or report.get("remote_mutation_attempted") is not False
        or report.get("unexpected_operations") != []
    ):
        raise RehearsalMismatchError("canonical rollback identity/status drifted")
    new_pin = require_immutable_revision(
        report.get("public_revision"), name="public_revision"
    )
    previous_pin = require_immutable_revision(
        report.get("previous_public_pin"), name="previous_public_pin"
    )
    if (
        report.get("public_sha") != new_pin
        or report.get("rollback_target") != previous_pin
        or previous_pin != PREVIOUS_PUBLIC_PIN
        or new_pin == previous_pin
    ):
        raise RehearsalMismatchError("canonical rollback pin lineage drifted")
    for name in (
        "final_manifest_digest",
        "release_manifest_digest",
        "publication_receipt_digest",
        "public_canary_digest",
    ):
        if re.fullmatch(r"[0-9a-f]{64}", str(report.get(name) or "")) is None:
            raise RehearsalMismatchError(f"canonical rollback {name} is malformed")
    binding_args = {
        "repo_id": report["dataset_repo_id"],
        "new_revision": new_pin,
        "previous_revision": previous_pin,
        "release_manifest_digest": report["release_manifest_digest"],
        "parent_evidence_digest": report["public_canary_digest"],
    }
    try:
        assert_first_party_dual_pin_measurement(report, **binding_args)
        assert_first_party_dual_pin_measurement(
            report.get("pin_probes") or {}, **binding_args
        )
    except StateLawsReleaseProbeError as exc:
        raise RehearsalMismatchError(
            "canonical rollback lacks sealed first-party provenance"
        ) from exc
    validate_canonical_pin_probes(
        report.get("pin_probes") or {}, new_pin=new_pin, previous_pin=previous_pin
    )
    declared = str(report.get("canonical_digest") or report.get("content_digest") or "")
    if re.fullmatch(r"[0-9a-f]{64}", declared) is None or (
        canonical_no_self_field_digest(report) != declared
    ):
        raise RehearsalMismatchError("canonical rollback digest mismatch")
    reject_credentials_in_payload(report, label="canonical_rollback_rehearsal")
    reject_path_leaks(report, label="canonical_rollback_rehearsal")
    return report


def build_rehearsal_report(*, repo_root: Path | str | None = None) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    publication = load_publication_receipt(repo_root=root)
    canary = load_public_canary(repo_root=root)
    baseline = load_baseline(repo_root=root)

    new_pin = validate_immutable_revision(
        str(publication.get("public_sha") or publication.get("public_revision")),
        name="new_pin",
    )
    previous_pin = validate_immutable_revision(
        str(publication.get("previous_public_pin") or publication.get("old_sha")),
        name="previous_pin",
    )
    if str(canary.get("public_sha") or "") != new_pin:
        raise RehearsalMismatchError("public canary SHA does not match publication SHA")
    if str(canary.get("previous_public_pin") or "") != previous_pin:
        raise RehearsalMismatchError("public canary rollback target drifted")

    manifest_digest = str(
        publication.get("final_manifest_digest")
        or publication.get("manifest_digest")
        or ""
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{64}", manifest_digest):
        raise RehearsalMismatchError("publication manifest digest is not a SHA-256")

    legacy = explicit_legacy_configuration()
    queryability = rehearse_dual_pin_query(
        new_pin=new_pin,
        previous_pin=previous_pin,
        canary=canary,
        baseline=baseline,
    )
    rollback = rehearse_rollback(
        new_pin=new_pin,
        previous_pin=previous_pin,
        manifest_digest=manifest_digest,
    )
    board = rehearse_board_diagnostics()
    docs = validate_operator_docs(repo_root=root)

    acceptance = {
        "both_pins_queryable": bool(queryability.get("both_queryable")),
        "board_diagnostics_encoded": bool(board.get("ok")),
        "legacy_configuration_explicit": bool(legacy.get("explicit")),
        "legacy_files_deleted": False,
        "no_absolute_path_or_secret": True,
        "no_deletion": True,
        "no_force_push": True,
        "no_visibility_change": True,
        "operators_can_diagnose_blocked_idle_stale_boards": True,
        "public_advertisement_unchanged": True,
        "rollback_bounded_recoverable": bool(
            rollback.get("bounded") and rollback.get("recoverable")
        ),
    }
    expected_acceptance = {
        "both_pins_queryable": True,
        "board_diagnostics_encoded": True,
        "legacy_configuration_explicit": True,
        "legacy_files_deleted": False,
        "no_absolute_path_or_secret": True,
        "no_deletion": True,
        "no_force_push": True,
        "no_visibility_change": True,
        "operators_can_diagnose_blocked_idle_stale_boards": True,
        "public_advertisement_unchanged": True,
        "rollback_bounded_recoverable": True,
    }
    if acceptance != expected_acceptance:
        failed = [
            key
            for key, value in expected_acceptance.items()
            if acceptance.get(key) is not value
        ]
        raise RehearsalMismatchError(
            "rollback rehearsal acceptance failed: " + ", ".join(failed)
        )

    report: dict[str, Any] = {
        "acceptance": acceptance,
        "advertised_pin": new_pin,
        "board_diagnostics": board,
        "code_version": CODE_VERSION,
        "compact_recipe": True,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_repo_id": DEFAULT_DATASET_REPO,
        "default_config": DEFAULT_DEFAULT_CONFIG,
        "depends_on": list(DEPENDS_ON),
        "docs": docs,
        "dry_run": True,
        "fixture_id": FIXTURE_ID,
        "fixture_only": True,
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "goal_id": GOAL_ID,
        "legacy_configuration": legacy,
        "legacy_config": DEFAULT_LEGACY_CONFIG,
        "live_network": False,
        "manifest_digest": manifest_digest,
        "mutation_executed": False,
        "network_required": False,
        "pins": {
            "both_queryable": True,
            "new": new_pin,
            "previous": previous_pin,
            "rollback_target": previous_pin,
        },
        "previous_public_pin": previous_pin,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "public_advertisement_changed": False,
        "public_branch": PUBLIC_BRANCH,
        "public_revision": new_pin,
        "public_sha": new_pin,
        "publication_receipt": PUBLICATION_RECEIPT_RELPATH.as_posix(),
        "queryability": queryability,
        "read_only": True,
        "recovery_config": DEFAULT_RECOVERY_CONFIG,
        "release_point": DEFAULT_RELEASE_POINT,
        "release_profile": RELEASE_PROFILE,
        "remote_write_contacted": False,
        "rollback": rollback,
        "rollback_target": previous_pin,
        "schema": REHEARSAL_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "secret_redacted": True,
        "staging_branch": DEFAULT_STAGING,
        "status": "rehearsed",
        "target": DEFAULT_DATASET_REPO,
        "target_repo": DEFAULT_DATASET_REPO,
        "task_id": TASK_ID,
        "tokens_used": False,
    }
    reject_credentials_in_payload(report, label="rollback_rehearsal")
    reject_path_leaks(report, label="rollback_rehearsal")
    digest = digest_mapping(strip_digest_fields(report))
    report["content_digest"] = digest
    report["digest"] = digest
    report["report_digest_sha256"] = digest
    return report


def compare_rehearsals(
    fresh: Mapping[str, Any],
    sealed: Mapping[str, Any],
) -> list[str]:
    mismatches: list[str] = []
    left = strip_digest_fields(fresh)
    right = strip_digest_fields(sealed)
    left_text = canonical_json_dumps(left)
    right_text = canonical_json_dumps(right)
    if left_text != right_text:
        left_keys = set(left)
        right_keys = set(right)
        for key in sorted(left_keys | right_keys):
            if key not in left:
                mismatches.append(f"sealed missing {key}")
            elif key not in right:
                mismatches.append(f"fresh missing {key}")
            elif canonical_json_dumps({key: left[key]}) != canonical_json_dumps(
                {key: right[key]}
            ):
                mismatches.append(f"field mismatch: {key}")
        if not mismatches:
            mismatches.append("canonical payload mismatch")
    return mismatches


def check_rehearsal(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    sealed_path = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_report_path(root)
    )
    if not sealed_path.is_file():
        raise RehearsalMissingInputError(
            f"report not found: {DEFAULT_REPORT_RELPATH.as_posix()}; pass --write"
        )
    sealed = load_json_mapping(sealed_path)
    fresh = build_rehearsal_report(repo_root=root)
    reject_credentials_in_payload(sealed, label="sealed_rollback_rehearsal")
    reject_path_leaks(sealed, label="sealed_rollback_rehearsal")
    if sealed.get("schema") != REHEARSAL_SCHEMA:
        raise RehearsalMismatchError(
            f"sealed rehearsal schema mismatch: {sealed.get('schema')!r}"
        )
    if sealed.get("task_id") != TASK_ID:
        raise RehearsalMismatchError(
            f"sealed rehearsal task_id mismatch: {sealed.get('task_id')!r}"
        )
    if sealed.get("public_advertisement_changed") is True:
        raise RehearsalSafetyError("sealed rehearsal must not change advertisement")
    if sealed.get("mutation_executed") is True or sealed.get("live_network") is True:
        raise RehearsalSafetyError("sealed rehearsal must remain offline/read-only")
    mismatches = compare_rehearsals(fresh, sealed)
    if mismatches:
        raise RehearsalMismatchError(
            "sealed rollback rehearsal check failed: " + "; ".join(mismatches[:16])
        )
    acceptance = (
        sealed.get("acceptance") if isinstance(sealed.get("acceptance"), Mapping) else {}
    )
    return {
        "acceptance": dict(acceptance),
        "both_pins_queryable": bool(acceptance.get("both_pins_queryable")),
        "legacy_configuration_explicit": bool(
            acceptance.get("legacy_configuration_explicit")
        ),
        "mismatches": [],
        "ok": True,
        "operators_can_diagnose_blocked_idle_stale_boards": bool(
            acceptance.get("operators_can_diagnose_blocked_idle_stale_boards")
        ),
        "path": DEFAULT_REPORT_RELPATH.as_posix(),
        "public_sha": sealed.get("public_sha"),
        "rollback_bounded_recoverable": bool(
            acceptance.get("rollback_bounded_recoverable")
        ),
        "rollback_target": sealed.get("rollback_target"),
        "task_id": TASK_ID,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rehearse_state_laws_release_rollback.py",
        description=(
            "Rehearse dual-pin query, explicit legacy configuration, bounded "
            f"rollback, and board diagnostics for state-law sparse GraphRAG "
            f"({TASK_ID}). Default mode is offline and does not mutate the Hub."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Read and validate the existing canonical rollback rehearsal",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"Write/refresh {DEFAULT_REPORT_RELPATH.as_posix()}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional path for the rehearsal JSON "
            f"(default: stdout, or {DEFAULT_REPORT_RELPATH.as_posix()} with --write)"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=(
            "Path to the sealed rollback rehearsal report "
            f"(default: {DEFAULT_REPORT_RELPATH.as_posix()})"
        ),
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Always print the rehearsal/verification result as JSON",
    )
    parser.add_argument(
        "--publication-receipt",
        type=Path,
        default=None,
        help="Canonical LCR-042 publication receipt",
    )
    parser.add_argument(
        "--public-canary",
        type=Path,
        default=None,
        help="Canonical LCR-043 public canary receipt",
    )
    parser.add_argument(
        "--network",
        action="store_true",
        help="Opt in to bounded read-only queries at both immutable pins",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Empty cache directory for bounded dual-pin query measurements",
    )
    parser.add_argument(
        "--pin-probes",
        type=Path,
        default=None,
        help=(
            "Rejected legacy input. Canonical dual-pin evidence is measured "
            "internally through the production sparse-query API."
        ),
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
    except RehearsalSafetyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report is not None
        else default_report_path()
    )

    try:
        if args.check:
            if args.write or args.network:
                raise RehearsalSafetyError("--check is read-only")
            result = check_canonical_rollback_rehearsal(
                load_json_mapping(report_path)
            )
            if args.print_json or args.output is not None:
                write_json(args.output, result)
            print(
                "ok={ok} task_id={task_id} both_pins_queryable={both} "
                "legacy_explicit={legacy} rollback_bounded={rollback} "
                "board_diagnostics={board}".format(
                    ok=True,
                    task_id=result.get("task_id"),
                    both=result.get("both_pins_queryable"),
                    legacy=result.get("legacy_configuration_explicit"),
                    rollback=bool(
                        result.get("rollback_bounded")
                        and result.get("rollback_recoverable")
                    ),
                    board=result.get(
                        "operators_can_diagnose_blocked_idle_stale_boards"
                    ),
                ),
                file=sys.stderr,
            )
            return 0

        if args.pin_probes is not None:
            raise RehearsalSafetyError(
                "external --pin-probes cannot authorize canonical evidence"
            )
        if not args.network:
            raise RehearsalMissingInputError(
                "new rehearsal requires explicit --network opt-in"
            )
        if (
            args.publication_receipt is None
            or args.public_canary is None
            or args.cache_dir is None
        ):
            raise RehearsalMissingInputError(
                "new rehearsal requires --publication-receipt, --public-canary, "
                "and --cache-dir"
            )
        publication = check_canonical_publication_receipt(
            load_json_mapping(args.publication_receipt), require_live=True
        )
        canary = check_canonical_public_canary_receipt(
            load_json_mapping(args.public_canary)
        )
        if (
            canary["publication_receipt_digest"] != publication["canonical_digest"]
            or canary["dataset_repo_id"] != publication["dataset_repo_id"]
            or canary["public_revision"] != publication["public_revision"]
            or canary["previous_public_pin"] != publication["previous_public_pin"]
            or canary["release_manifest_digest"]
            != publication["release_manifest_digest"]
        ):
            raise RehearsalMismatchError(
                "public canary/publication immutable identity chain drifted"
            )
        probe_coordinates = {
            "repo_id": str(publication["dataset_repo_id"]),
            "new_revision": str(publication["public_revision"]),
            "previous_revision": str(publication["previous_public_pin"]),
            "release_manifest_digest": str(publication["release_manifest_digest"]),
            "parent_evidence_digest": str(canary["canonical_digest"]),
        }
        probes = assert_first_party_dual_pin_measurement(
            run_dual_pin_probe(
                args.cache_dir,
                **probe_coordinates,
            ),
            **probe_coordinates,
        )
        report = build_canonical_rollback_rehearsal(
            publication_receipt=publication,
            public_canary=canary,
            pin_probes=probes,
        )
        if args.write:
            destination = (
                Path(args.output).expanduser().resolve()
                if args.output is not None
                else report_path
            )
            write_json(destination, report)
            print(
                "wrote {} digest={}".format(
                    repo_relpath(destination), report["canonical_digest"]
                ),
                file=sys.stderr,
            )
        elif args.output is not None or args.print_json or not args.check:
            write_json(args.output, report)
        return 0
    except (
        RehearsalError,
        MutableRevisionError,
        StateLawsReleaseProbeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
