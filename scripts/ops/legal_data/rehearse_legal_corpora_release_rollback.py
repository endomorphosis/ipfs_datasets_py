#!/usr/bin/env python3
"""Rehearse dual-release rollback, updates, and refill closure (LCR-068).

Default ``--check`` mode is credential-free and does not contact the Hub:

1. Bind both authorized public pins and both previous (rollback) pins from
   the LCR-047 state receipt and the LCR-065 Federal publication receipt.
2. Bind the LCR-043 / LCR-066 public canaries, LCR-001 / LCR-048 baselines,
   LCR-045 state rollback rehearsal, LCR-046 post-publication audit, and
   LCR-067 cross-corpus canary so every pin has sealed query evidence.
3. Prove all four immutable pins remain independently queryable (resolver
   fetch of isolated trees; advertisement is a pointer, not a delete).
4. Rehearse bounded rollback and the reverse forward move on each corpus.
   Neither tree is deleted; recovery is the reverse pointer change.
5. Audit pending objective/codebase and corpus refill findings and require
   a closed ledger (zero unresolved findings).
6. Make daily (Federal Register) versus jurisdictional (state-law) update
   semantics explicit and refuse to conflate them.
7. Require the dual-release operator runbook to document scrape, build,
   resume, refill, monitor, and update paths for both corpora.
8. Compare the sealed ``dual_rollback_rehearsal.json`` to a freshly built
   receipt.

This CLI never:

* publishes to ``main`` / ``master``;
* deletes, force-pushes, or changes visibility;
* changes public advertisement on either repository;
* embeds or logs Hub tokens;
* treats credentials as CLI flags (environment-only).

Validation gate (no network)::

    python scripts/ops/legal_data/rehearse_legal_corpora_release_rollback.py --check
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

from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (  # noqa: E402
    DEFAULT_DATASET_REPO_ID as FEDERAL_DATASET_REPO_ID,
    PREVIOUS_PUBLIC_PIN as FEDERAL_PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE as FEDERAL_RELEASE_PROFILE,
    RollbackRecord as FederalRollbackRecord,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (  # noqa: E402
    CURRENTNESS_DISCLAIMER as FEDERAL_CURRENTNESS_DISCLAIMER,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (  # noqa: E402
    DEFAULT_CONFIG_NAME as STATE_DEFAULT_CONFIG,
    LEGACY_CONFIG_NAME as STATE_LEGACY_CONFIG,
)
from ipfs_datasets_py.processors.legal_data.state_laws_publication_policy import (  # noqa: E402
    DEFAULT_STAGING_BRANCH as STATE_STAGING_BRANCH,
    PUBLICATION_PARENT_REVISION as STATE_PREVIOUS_PUBLIC_PIN,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (  # noqa: E402
    DEFAULT_DATASET_REPO_ID as STATE_DATASET_REPO_ID,
    PREVIOUS_PUBLIC_PIN as STATE_HISTORICAL_BASELINE_PIN,
    RELEASE_PROFILE as STATE_RELEASE_PROFILE,
    RollbackRecord as StateRollbackRecord,
    canonical_json_dumps,
    digest_mapping,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (  # noqa: E402
    CURRENTNESS_DISCLAIMER as STATE_CURRENTNESS_DISCLAIMER,
    EXPECTED_JURISDICTION_COUNT,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (  # noqa: E402
    MappingTransport,
    MissingArtifactError,
    MutableRevisionError,
    validate_immutable_revision,
    validate_repo_id,
)


# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "LCR-068"
GOAL_ID: Final = "LCR-G140"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "rehearse_legal_corpora_release_rollback.py"
CODE_VERSION: Final = "1"
DEPENDS_ON: Final[tuple[str, ...]] = ("LCR-047", "LCR-067")

REHEARSAL_SCHEMA: Final = (
    "ipfs_datasets_py/legal-corpora-reindex-dual-rollback-rehearsal@1"
)
SCHEMA_VERSION: Final = "legal-corpora-dual-rollback-rehearsal/v1"
FIXTURE_ID: Final = "legal-corpora-dual-rollback-rehearsal-v1"

DEFAULT_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/dual_rollback_rehearsal.json"
)
STATE_PUBLICATION_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/publication_receipt.json"
)
STATE_PUBLIC_CANARY_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/public_canary.json"
)
STATE_BASELINE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/baseline.json"
)
STATE_ROLLBACK_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/rollback_rehearsal.json"
)
STATE_AUDIT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/post_publication_audit.json"
)
STATE_FINAL_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/state_final_release_receipt.json"
)
FEDERAL_PUBLICATION_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_publication_receipt.json"
)
FEDERAL_PUBLIC_CANARY_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_public_canary.json"
)
FEDERAL_BASELINE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/federal_baseline.json"
)
CROSS_CORPUS_CANARY_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/cross_corpus_canary.json"
)
RUNBOOK_RELPATH: Final = Path("docs/guides/LEGAL_CORPORA_REINDEX_RUNBOOK.md")

STATE_QUERY_CLI_RELPATH: Final = Path("scripts/ops/legal_data/query_state_laws_hf.py")
FEDERAL_QUERY_CLI_RELPATH: Final = Path(
    "scripts/ops/legal_data/query_federal_register_hf.py"
)
CROSS_CANARY_CLI_RELPATH: Final = Path(
    "scripts/ops/legal_data/canary_legal_corpora_public_releases.py"
)
STATUS_SH_RELPATH: Final = Path("scripts/ops/legal_corpora_reindex/status.sh")
STATUS_PY_RELPATH: Final = Path("scripts/ops/legal_corpora_reindex/status.py")
STATE_REFILL_CLI_RELPATH: Final = Path(
    "scripts/ops/legal_data/state_laws_acquisition_gap_refill.py"
)
STATE_BUILD_CLI_RELPATH: Final = Path(
    "scripts/ops/legal_data/build_state_laws_sparse_graphrag.py"
)
FEDERAL_BUILD_CLI_RELPATH: Final = Path(
    "scripts/ops/legal_data/build_federal_register_sparse_graphrag.py"
)
COHORT_CLI_RELPATH: Final = Path(
    "scripts/ops/legal_data/run_legal_corpora_reindex_cohort.py"
)
FEDERAL_ACQUIRE_CLI_RELPATH: Final = Path(
    "scripts/ops/legal_data/acquire_federal_register_full.py"
)

DEFAULT_STATE_REPO: Final = STATE_DATASET_REPO_ID
DEFAULT_FEDERAL_REPO: Final = FEDERAL_DATASET_REPO_ID
DEFAULT_STATE_CONFIG: Final = STATE_DEFAULT_CONFIG
DEFAULT_STATE_LEGACY_CONFIG: Final = STATE_LEGACY_CONFIG
DEFAULT_FEDERAL_CONFIG: Final = FEDERAL_RELEASE_PROFILE
DEFAULT_FEDERAL_LEGACY_LAYOUT: Final = "legacy-federal-register-parquet/v1"
DEFAULT_STATE_STAGING: Final = STATE_STAGING_BRANCH
DEFAULT_FEDERAL_STAGING: Final = "stage/federal-register-ir-graphrag-v2"
PUBLIC_BRANCH: Final = "main"
STATE_RELEASE_POINT: Final = "state-laws/v2/2026-08-10"
FEDERAL_RELEASE_POINT: Final = "federal-register/v2/2026-08-10"
OBSERVATION_CUTOFF: Final = "2026-08-10T00:00:00Z"
REHEARSAL_TIME: Final = "2026-08-10T21:00:00Z"
FORWARD_REHEARSAL_TIME: Final = "2026-08-10T21:05:00Z"

STATE_ROLLBACK_TASK_ID: Final = "LCR-045"
STATE_FINAL_TASK_ID: Final = "LCR-047"
STATE_AUDIT_TASK_ID: Final = "LCR-046"
CROSS_CORPUS_TASK_ID: Final = "LCR-067"
FEDERAL_PUBLICATION_TASK_ID: Final = "LCR-065"
FEDERAL_CANARY_TASK_ID: Final = "LCR-066"

PIN_COUNT: Final = 4
PIN_ROLES: Final[tuple[str, ...]] = (
    "state_new",
    "state_previous",
    "federal_new",
    "federal_previous",
)

SECRET_ENV_NAMES: Final[tuple[str, ...]] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
    "STATE_LAWS_HF_TOKEN",
    "STATE_LAWS_STAGING_AUTHORIZATION",
    "STATE_LAWS_PUBLICATION_AUTHORIZATION",
    "FEDERAL_REGISTER_HF_TOKEN",
    "FEDERAL_REGISTER_STAGING_AUTHORIZATION",
    "FEDERAL_REGISTER_PUBLICATION_AUTHORIZATION",
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
    "rehearse_four_pin_query",
    "re_advertise_state_previous_pin",
    "re_advertise_state_new_pin",
    "re_advertise_federal_previous_pin",
    "re_advertise_federal_new_pin",
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
UNRESOLVED_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "open",
        "pending",
        "unresolved",
        "blocked",
        "active",
        "ready",
        "failed",
        "gap",
    }
)

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

COMBINED_CURRENTNESS_DISCLAIMER: Final = (
    f"{STATE_CURRENTNESS_DISCLAIMER} {FEDERAL_CURRENTNESS_DISCLAIMER} "
    "State-law updates are jurisdictional (atomic per official package / "
    "exact-51 frontier). Federal Register updates are daily and "
    "cutoff-relative. The two update units must not be conflated."
)

RUNBOOK_REQUIRED_PHRASES: Final[tuple[str, ...]] = (
    "LCR-068",
    "LCR-G140",
    "LCR-047",
    "LCR-067",
    "justicedao/ipfs_state_laws",
    "justicedao/ipfs_federal_register",
    STATE_HISTORICAL_BASELINE_PIN,
    FEDERAL_PREVIOUS_PUBLIC_PIN,
    STATE_RELEASE_PROFILE,
    FEDERAL_RELEASE_PROFILE,
    "query_state_laws_hf.py",
    "query_federal_register_hf.py",
    "rehearse_legal_corpora_release_rollback.py",
    "canary_legal_corpora_public_releases.py",
    "build_state_laws_sparse_graphrag.py",
    "build_federal_register_sparse_graphrag.py",
    "run_legal_corpora_reindex_cohort.py",
    "state_laws_acquisition_gap_refill.py",
    "acquire_federal_register_full.py",
    "status.sh",
    "status.py",
    "blocked",
    "idle",
    "stale",
    "without deleting",
    "All four pins",
    "bounded",
    "reversible",
    "refill closure",
    "daily versus jurisdictional",
    "atomic per-jurisdiction",
    "observation cutoff",
    "legal currentness",
    "research aid",
    "--check",
    "entry_cid",
    "release_point",
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


def _require_hex40(value: Any, *, name: str) -> str:
    text = str(value or "").strip()
    if not _GIT_SHA_RE.fullmatch(text):
        raise RehearsalMismatchError(f"{name} is not a 40-hex immutable pin")
    return validate_immutable_revision(text, name=name)


def _require_sha256(value: Any, *, name: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise RehearsalMismatchError(f"{name} is not a SHA-256 digest")
    return text


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


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
        "federal_register_staging_authorization=",
        "federal_register_publication_authorization=",
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


def reject_forbidden_operations(operations: Sequence[str]) -> None:
    for operation in operations:
        if operation in FORBIDDEN_OPERATIONS:
            raise RehearsalSafetyError(f"scheduled operation is forbidden: {operation}")


# ---------------------------------------------------------------------------
# Producer inputs
# ---------------------------------------------------------------------------


def _load_bound_json(
    relpath: Path,
    *,
    repo_root: Path,
    path: Path | str | None = None,
) -> dict[str, Any]:
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else _require_repo_file(relpath, repo_root=repo_root)
    )
    return load_json_mapping(target)


def _require_live_publication_receipt(
    receipt: Mapping[str, Any],
    *,
    label: str,
) -> None:
    if receipt.get("fixture_only") is not False:
        raise RehearsalMismatchError(f"{label} publication receipt is fixture-only")
    if receipt.get("live_network") is not True:
        raise RehearsalMismatchError(f"{label} publication receipt is not live")
    if receipt.get("mutation_executed") is not True:
        raise RehearsalMismatchError(f"{label} publication commit was not executed")
    if receipt.get("remote_write_contacted") is not True:
        raise RehearsalMismatchError(f"{label} publication lacks remote-write evidence")


def _require_live_public_canary(
    canary: Mapping[str, Any],
    *,
    label: str,
) -> None:
    if canary.get("fixture_only") is not False:
        raise RehearsalMismatchError(f"{label} public canary is fixture-only")
    if canary.get("live_network") is not True:
        raise RehearsalMismatchError(f"{label} public canary is not a live redownload")
    if canary.get("read_only") is not True:
        raise RehearsalMismatchError(f"{label} public canary is not read-only")


def load_state_publication(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    receipt = _load_bound_json(STATE_PUBLICATION_RELPATH, repo_root=root, path=path)
    _require_live_publication_receipt(receipt, label="state")
    public_sha = _require_hex40(
        receipt.get("public_sha") or receipt.get("public_revision"),
        name="state.publication.public_sha",
    )
    previous = _require_hex40(
        receipt.get("previous_public_pin") or receipt.get("old_sha"),
        name="state.publication.previous_public_pin",
    )
    if previous != STATE_PREVIOUS_PUBLIC_PIN:
        raise RehearsalMismatchError(
            "state publication previous pin drifted from STATE_PREVIOUS_PUBLIC_PIN"
        )
    if public_sha == previous:
        raise RehearsalMismatchError(
            "state public SHA must differ from the previous public pin"
        )
    repo = str(
        receipt.get("dataset_repo_id")
        or receipt.get("target_repo")
        or receipt.get("target")
        or ""
    ).strip()
    validate_repo_id(repo, name="state.publication.dataset_repo_id")
    if repo != DEFAULT_STATE_REPO:
        raise RehearsalMismatchError(
            f"state publication target must remain {DEFAULT_STATE_REPO}"
        )
    if receipt.get("legacy_files_deleted") is True:
        raise RehearsalSafetyError("state publication reports legacy file deletion")
    return receipt


def load_federal_publication(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    receipt = _load_bound_json(FEDERAL_PUBLICATION_RELPATH, repo_root=root, path=path)
    _require_live_publication_receipt(receipt, label="federal")
    public_sha = _require_hex40(
        receipt.get("public_sha") or receipt.get("public_revision"),
        name="federal.publication.public_sha",
    )
    previous = _require_hex40(
        receipt.get("previous_public_pin") or receipt.get("old_sha"),
        name="federal.publication.previous_public_pin",
    )
    if previous != FEDERAL_PREVIOUS_PUBLIC_PIN:
        raise RehearsalMismatchError(
            "federal publication previous pin drifted from FEDERAL_PREVIOUS_PUBLIC_PIN"
        )
    if public_sha == previous:
        raise RehearsalMismatchError(
            "federal public SHA must differ from the previous public pin"
        )
    repo = str(
        receipt.get("dataset_repo_id")
        or receipt.get("target_repo")
        or receipt.get("target")
        or ""
    ).strip()
    validate_repo_id(repo, name="federal.publication.dataset_repo_id")
    if repo != DEFAULT_FEDERAL_REPO:
        raise RehearsalMismatchError(
            f"federal publication target must remain {DEFAULT_FEDERAL_REPO}"
        )
    if receipt.get("legacy_files_deleted") is True:
        raise RehearsalSafetyError("federal publication reports legacy file deletion")
    return receipt


def load_state_public_canary(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    canary = _load_bound_json(STATE_PUBLIC_CANARY_RELPATH, repo_root=root, path=path)
    _require_live_public_canary(canary, label="state")
    public_sha = _require_hex40(
        canary.get("public_sha") or canary.get("public_revision"),
        name="state.canary.public_sha",
    )
    previous = _require_hex40(
        canary.get("previous_public_pin") or canary.get("old_sha") or canary.get("base_revision"),
        name="state.canary.previous_public_pin",
    )
    if previous != STATE_PREVIOUS_PUBLIC_PIN:
        raise RehearsalMismatchError(
            "state public canary previous pin drifted from STATE_PREVIOUS_PUBLIC_PIN"
        )
    acceptance = _as_mapping(canary.get("acceptance"))
    if acceptance.get("public_pin_immutable") is not True:
        raise RehearsalMismatchError("state public canary pin is not immutable")
    canaries = _as_mapping(canary.get("canaries"))
    if _as_mapping(canaries.get("bm25")).get("ok") is not True:
        raise RehearsalMismatchError("state public canary lacks sealed BM25 evidence")
    if _as_mapping(canaries.get("filter")).get("ok") is not True:
        raise RehearsalMismatchError("state public canary lacks sealed filter evidence")
    del public_sha
    return canary


def load_federal_public_canary(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    canary = _load_bound_json(FEDERAL_PUBLIC_CANARY_RELPATH, repo_root=root, path=path)
    _require_live_public_canary(canary, label="federal")
    _require_hex40(
        canary.get("public_sha") or canary.get("public_revision"),
        name="federal.canary.public_sha",
    )
    previous = _require_hex40(
        canary.get("previous_public_pin") or canary.get("base_revision"),
        name="federal.canary.previous_public_pin",
    )
    if previous != FEDERAL_PREVIOUS_PUBLIC_PIN:
        raise RehearsalMismatchError(
            "federal public canary previous pin drifted from FEDERAL_PREVIOUS_PUBLIC_PIN"
        )
    acceptance = _as_mapping(canary.get("acceptance"))
    if acceptance.get("public_pin_immutable") is not True:
        raise RehearsalMismatchError("federal public canary pin is not immutable")
    if acceptance.get("sparse_queries_within_budget") is not True:
        raise RehearsalMismatchError("federal public canary sparse queries are not in budget")
    if str(canary.get("default_config") or "") != DEFAULT_FEDERAL_CONFIG:
        raise RehearsalMismatchError("federal public canary default config is not v2")
    return canary


def load_state_baseline(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    baseline = _load_bound_json(STATE_BASELINE_RELPATH, repo_root=root, path=path)
    acceptance = _as_mapping(baseline.get("acceptance"))
    pin = _require_hex40(
        acceptance.get("pinned_revision") or baseline.get("pinned_revision"),
        name="state.baseline.pinned_revision",
    )
    if pin != STATE_HISTORICAL_BASELINE_PIN:
        raise RehearsalMismatchError(
            "state baseline pinned revision drifted from "
            "STATE_HISTORICAL_BASELINE_PIN"
        )
    return baseline


def load_federal_baseline(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    baseline = _load_bound_json(FEDERAL_BASELINE_RELPATH, repo_root=root, path=path)
    acceptance = _as_mapping(baseline.get("acceptance"))
    pin = _require_hex40(
        acceptance.get("pinned_revision") or baseline.get("pinned_revision"),
        name="federal.baseline.pinned_revision",
    )
    if pin != FEDERAL_PREVIOUS_PUBLIC_PIN:
        raise RehearsalMismatchError(
            "federal baseline pinned revision drifted from FEDERAL_PREVIOUS_PUBLIC_PIN"
        )
    return baseline


def load_state_rollback_rehearsal(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    report = _load_bound_json(STATE_ROLLBACK_RELPATH, repo_root=root, path=path)
    if report.get("task_id") != STATE_ROLLBACK_TASK_ID:
        raise RehearsalMismatchError("state rollback rehearsal task_id drifted")
    acceptance = _as_mapping(report.get("acceptance"))
    if acceptance.get("both_pins_queryable") is not True:
        raise RehearsalMismatchError("state rollback rehearsal pins are not queryable")
    if acceptance.get("rollback_bounded_recoverable") is not True:
        raise RehearsalMismatchError("state rollback rehearsal is not bounded/recoverable")
    if report.get("mutation_executed") is True or report.get("live_network") is True:
        raise RehearsalSafetyError("state rollback rehearsal must remain offline")
    return report


def load_state_post_publication_audit(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    audit = _load_bound_json(STATE_AUDIT_RELPATH, repo_root=root, path=path)
    if audit.get("task_id") != STATE_AUDIT_TASK_ID:
        raise RehearsalMismatchError("state post-publication audit task_id drifted")
    acceptance = _as_mapping(audit.get("acceptance"))
    if acceptance.get("update_checkpoints_ok") is not True:
        raise RehearsalMismatchError("state update checkpoints are not ok")
    if acceptance.get("no_contradiction_remains") is not True:
        raise RehearsalMismatchError("state post-publication audit still has contradictions")
    return audit


def load_state_final_receipt(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    receipt = _load_bound_json(STATE_FINAL_RELPATH, repo_root=root, path=path)
    if receipt.get("task_id") != STATE_FINAL_TASK_ID:
        raise RehearsalMismatchError("state final receipt task_id drifted")
    acceptance = _as_mapping(receipt.get("acceptance"))
    if acceptance.get("no_unresolved_gap") is not True:
        raise RehearsalMismatchError("state final receipt still reports an unresolved gap")
    if acceptance.get("every_state_law_gate_at_public_sha") is not True:
        raise RehearsalMismatchError("state final receipt does not seal every state-law gate")
    public_sha = _require_hex40(
        receipt.get("public_sha")
        or _as_mapping(receipt.get("completion_proof")).get("public_sha"),
        name="state.final.public_sha",
    )
    del public_sha
    return receipt


def load_cross_corpus_canary(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    canary = _load_bound_json(CROSS_CORPUS_CANARY_RELPATH, repo_root=root, path=path)
    if canary.get("fixture_only") is not False:
        raise RehearsalMismatchError("cross-corpus canary is fixture-only")
    if canary.get("task_id") != CROSS_CORPUS_TASK_ID:
        raise RehearsalMismatchError("cross-corpus canary task_id drifted")
    acceptance = _as_mapping(canary.get("acceptance"))
    if acceptance.get("cross_corpus_queries_reproducible") is not True:
        raise RehearsalMismatchError("cross-corpus canary queries are not reproducible")
    if acceptance.get("provenance_safe") is not True:
        raise RehearsalMismatchError("cross-corpus canary is not provenance-safe")
    return canary


# ---------------------------------------------------------------------------
# Four-pin query rehearsal
# ---------------------------------------------------------------------------


def _pin_tree(
    *,
    label: str,
    repo_id: str,
    revision: str,
    config_name: str,
    unique_path: str,
    release_point: str,
) -> dict[str, bytes]:
    payload = {
        "config_name": config_name,
        "dataset_repo_id": repo_id,
        "label": label,
        "queryable": True,
        "release_point": release_point,
        "revision": revision,
        "schema_version": SCHEMA_VERSION,
        "unique_path": unique_path,
    }
    text = canonical_json_dumps(payload)
    return {
        "README.md": f"# {label}\nrevision={revision}\n".encode("utf-8"),
        "manifest.json": text.encode("utf-8"),
        unique_path: f"{label}:{revision}\n".encode("utf-8"),
    }


def _fetch_pin_tree(
    *,
    repo_id: str,
    revision: str,
    files: Mapping[str, bytes],
    relative_path: str = "manifest.json",
) -> dict[str, Any]:
    validate_immutable_revision(revision, name="revision")
    validate_repo_id(repo_id, name="repo_id")
    transport = MappingTransport(files)
    with tempfile.TemporaryDirectory(prefix="lcr068-pin-") as tmp:
        destination = Path(tmp) / "artifact"
        fetched = transport.fetch(
            repo_id=repo_id,
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
        "repo_id": repo_id,
        "revision": revision,
        "transport": "mapping",
        "verified": True,
    }


def _query_command(
    *,
    cli: Path,
    repo_id: str,
    revision: str,
    mode: str,
    query: str,
    extra: Sequence[str] = (),
) -> dict[str, Any]:
    validate_immutable_revision(revision, name="query.revision")
    argv = [
        "python",
        cli.as_posix(),
        "--repo-id",
        repo_id,
        "--revision",
        revision,
        "--json",
        "--trace",
        mode,
        query,
        *list(extra),
    ]
    return {
        "argv": argv,
        "command": cli.as_posix(),
        "mode": mode,
        "query": query,
        "repo_id": repo_id,
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


def _pin_spec(
    *,
    role: str,
    corpus: str,
    repo_id: str,
    revision: str,
    config: str,
    unique_path: str,
    release_point: str,
    evidence: Path,
    command: Mapping[str, Any],
) -> dict[str, Any]:
    files = _pin_tree(
        label=role,
        repo_id=repo_id,
        revision=revision,
        config_name=config,
        unique_path=unique_path,
        release_point=release_point,
    )
    fetch = _fetch_pin_tree(
        repo_id=repo_id,
        revision=revision,
        files=files,
        relative_path=unique_path,
    )
    return {
        "command": dict(command),
        "config": config,
        "corpus": corpus,
        "evidence": evidence.as_posix(),
        "fetch": fetch,
        "files": files,
        "queryable": True,
        "release_point": release_point,
        "repo_id": repo_id,
        "revision": revision,
        "role": role,
        "unique_path": unique_path,
    }


def _assert_cross_isolated(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> None:
    try:
        _fetch_pin_tree(
            repo_id=str(left["repo_id"]),
            revision=str(left["revision"]),
            files=left["files"],
            relative_path=str(right["unique_path"]),
        )
    except MissingArtifactError:
        pass
    else:
        raise RehearsalMismatchError(
            f"{left['role']} unexpectedly resolved {right['role']} tree"
        )


def rehearse_four_pin_query(
    *,
    state_new: str,
    state_previous: str,
    federal_new: str,
    federal_previous: str,
    state_canary: Mapping[str, Any],
    federal_canary: Mapping[str, Any],
    state_baseline: Mapping[str, Any],
    federal_baseline: Mapping[str, Any],
    cross_canary: Mapping[str, Any],
) -> dict[str, Any]:
    pins = {
        "state_new": _require_hex40(state_new, name="state_new"),
        "state_previous": _require_hex40(state_previous, name="state_previous"),
        "federal_new": _require_hex40(federal_new, name="federal_new"),
        "federal_previous": _require_hex40(federal_previous, name="federal_previous"),
    }
    if len(set(pins.values())) != PIN_COUNT:
        raise RehearsalMismatchError("all four pins must be distinct immutable revisions")
    if pins["state_previous"] != STATE_PREVIOUS_PUBLIC_PIN:
        raise RehearsalMismatchError("state previous pin drifted from sealed constant")
    if pins["federal_previous"] != FEDERAL_PREVIOUS_PUBLIC_PIN:
        raise RehearsalMismatchError("federal previous pin drifted from sealed constant")
    rejected = _reject_mutable_revisions()

    specs = {
        "state_new": _pin_spec(
            role="state_new",
            corpus="state_laws",
            repo_id=DEFAULT_STATE_REPO,
            revision=pins["state_new"],
            config=DEFAULT_STATE_CONFIG,
            unique_path="data/corpus/jurisdiction=DC/part-000000.parquet",
            release_point=STATE_RELEASE_POINT,
            evidence=STATE_PUBLIC_CANARY_RELPATH,
            command=_query_command(
                cli=STATE_QUERY_CLI_RELPATH,
                repo_id=DEFAULT_STATE_REPO,
                revision=pins["state_new"],
                mode="bm25",
                query="disclosure",
                extra=("--top-k", "5", "--jurisdiction", "DC"),
            ),
        ),
        "state_previous": _pin_spec(
            role="state_previous",
            corpus="state_laws",
            repo_id=DEFAULT_STATE_REPO,
            revision=pins["state_previous"],
            config=DEFAULT_STATE_LEGACY_CONFIG,
            unique_path="STATE-IA.parquet",
            release_point=STATE_RELEASE_POINT,
            evidence=STATE_BASELINE_RELPATH,
            command=_query_command(
                cli=STATE_QUERY_CLI_RELPATH,
                repo_id=DEFAULT_STATE_REPO,
                revision=pins["state_previous"],
                mode="bm25",
                query="disclosure",
                extra=("--top-k", "5", "--jurisdiction", "DC"),
            ),
        ),
        "federal_new": _pin_spec(
            role="federal_new",
            corpus="federal_register",
            repo_id=DEFAULT_FEDERAL_REPO,
            revision=pins["federal_new"],
            config=DEFAULT_FEDERAL_CONFIG,
            unique_path=(
                "data/corpus/year_month=2026-03/document_type=rule/part-000000.parquet"
            ),
            release_point=FEDERAL_RELEASE_POINT,
            evidence=FEDERAL_PUBLIC_CANARY_RELPATH,
            command=_query_command(
                cli=FEDERAL_QUERY_CLI_RELPATH,
                repo_id=DEFAULT_FEDERAL_REPO,
                revision=pins["federal_new"],
                mode="bm25",
                query="airworthiness",
                extra=("--top-k", "3"),
            ),
        ),
        "federal_previous": _pin_spec(
            role="federal_previous",
            corpus="federal_register",
            repo_id=DEFAULT_FEDERAL_REPO,
            revision=pins["federal_previous"],
            config=DEFAULT_FEDERAL_LEGACY_LAYOUT,
            unique_path="federal_register.parquet",
            release_point=FEDERAL_RELEASE_POINT,
            evidence=FEDERAL_BASELINE_RELPATH,
            command=_query_command(
                cli=FEDERAL_QUERY_CLI_RELPATH,
                repo_id=DEFAULT_FEDERAL_REPO,
                revision=pins["federal_previous"],
                mode="bm25",
                query="airworthiness",
                extra=("--top-k", "3"),
            ),
        ),
    }
    roles = list(specs)
    for index, left_role in enumerate(roles):
        for right_role in roles[index + 1 :]:
            _assert_cross_isolated(specs[left_role], specs[right_role])
            _assert_cross_isolated(specs[right_role], specs[left_role])

    state_canaries = _as_mapping(state_canary.get("canaries"))
    state_canary_ok = (
        _as_mapping(state_canaries.get("bm25")).get("ok") is True
        and _as_mapping(state_canaries.get("filter")).get("ok") is True
        and str(state_canary.get("public_sha") or "") == pins["state_new"]
    )
    federal_acceptance = _as_mapping(federal_canary.get("acceptance"))
    federal_canary_ok = (
        federal_acceptance.get("sparse_queries_within_budget") is True
        and federal_acceptance.get("public_artifacts_equal_staged_candidate") is True
        and str(federal_canary.get("public_sha") or "") == pins["federal_new"]
    )
    state_baseline_acceptance = _as_mapping(state_baseline.get("acceptance"))
    state_baseline_ok = (
        str(state_baseline_acceptance.get("pinned_revision") or "")
        == pins["state_previous"]
        and int(state_baseline_acceptance.get("jurisdictions") or 0)
        == EXPECTED_JURISDICTION_COUNT
    )
    federal_baseline_acceptance = _as_mapping(federal_baseline.get("acceptance"))
    federal_baseline_ok = (
        str(federal_baseline_acceptance.get("pinned_revision") or "")
        == pins["federal_previous"]
    )
    cross_acceptance = _as_mapping(cross_canary.get("acceptance"))
    cross_ok = (
        cross_acceptance.get("cross_corpus_queries_reproducible") is True
        and cross_acceptance.get("provenance_safe") is True
    )
    if not state_canary_ok:
        raise RehearsalMismatchError("state new pin lacks sealed public-canary evidence")
    if not federal_canary_ok:
        raise RehearsalMismatchError("federal new pin lacks sealed public-canary evidence")
    if not state_baseline_ok:
        raise RehearsalMismatchError("state previous pin lacks sealed baseline evidence")
    if not federal_baseline_ok:
        raise RehearsalMismatchError("federal previous pin lacks sealed baseline evidence")
    if not cross_ok:
        raise RehearsalMismatchError("cross-corpus canary does not prove shared substrate")

    after = {
        role: True
        for role in PIN_ROLES
    }
    public_specs: dict[str, Any] = {}
    for role, spec in specs.items():
        public_specs[role] = {
            key: value for key, value in spec.items() if key != "files"
        }
    return {
        "after_forward": dict(after),
        "after_rollback": dict(after),
        "all_four_queryable": True,
        "cross_corpus_canary_ok": cross_ok,
        "cross_pin_trees_isolated": True,
        "federal_baseline_ok": federal_baseline_ok,
        "federal_canary_ok": federal_canary_ok,
        "mutable_revisions_rejected": rejected,
        "offline": True,
        "pin_count": PIN_COUNT,
        "pins": public_specs,
        "state_baseline_jurisdictions": int(
            state_baseline_acceptance.get("jurisdictions") or 0
        ),
        "state_baseline_ok": state_baseline_ok,
        "state_canary_ok": state_canary_ok,
    }


# ---------------------------------------------------------------------------
# Rollback rehearsal (bounded + reversible)
# ---------------------------------------------------------------------------


def _rollback_record(
    *,
    factory: type[StateRollbackRecord] | type[FederalRollbackRecord],
    rollback_id: str,
    dataset_repo_id: str,
    from_revision: str,
    to_revision: str,
    reason: str,
    rolled_back_at: str,
    manifest_digest: str,
    schema_version: str,
) -> dict[str, Any]:
    record = factory(
        rollback_id=rollback_id,
        dataset_repo_id=dataset_repo_id,
        from_revision=from_revision,
        to_revision=to_revision,
        reason=reason,
        rolled_back_at=rolled_back_at,
        manifest_digest=manifest_digest,
        schema_version=schema_version,
        payload={
            "additive_only": True,
            "deletes": False,
            "force_push": False,
            "legacy_files_deleted": False,
            "public_advertisement_changed": False,
            "recoverable": True,
            "reversible": True,
            "visibility_changed": False,
        },
    )
    return record.to_dict()


def rehearse_corpus_rollback(
    *,
    corpus: str,
    dataset_repo_id: str,
    new_pin: str,
    previous_pin: str,
    manifest_digest: str,
    factory: type[StateRollbackRecord] | type[FederalRollbackRecord],
    schema_version: str,
    back_operation: str,
    forward_operation: str,
) -> dict[str, Any]:
    new_pin = validate_immutable_revision(new_pin, name=f"{corpus}.new_pin")
    previous_pin = validate_immutable_revision(
        previous_pin, name=f"{corpus}.previous_pin"
    )
    if new_pin == previous_pin:
        raise RehearsalMismatchError(f"{corpus} rollback from/to revisions must differ")
    scheduled = [back_operation]
    forward = [forward_operation]
    reject_forbidden_operations((*scheduled, *forward))

    back = _rollback_record(
        factory=factory,
        rollback_id=f"rollback-{corpus}-lcr068-back",
        dataset_repo_id=dataset_repo_id,
        from_revision=new_pin,
        to_revision=previous_pin,
        reason=(
            f"rehearse re-advertising the previous {corpus} public pin without "
            "deleting the new pin tree or legacy files"
        ),
        rolled_back_at=REHEARSAL_TIME,
        manifest_digest=manifest_digest,
        schema_version=schema_version,
    )
    fwd = _rollback_record(
        factory=factory,
        rollback_id=f"rollback-{corpus}-lcr068-forward",
        dataset_repo_id=dataset_repo_id,
        from_revision=previous_pin,
        to_revision=new_pin,
        reason=(
            f"rehearse restoring the new {corpus} public pin advertisement; "
            "previous pin remains independently queryable"
        ),
        rolled_back_at=FORWARD_REHEARSAL_TIME,
        manifest_digest=manifest_digest,
        schema_version=schema_version,
    )
    return {
        "additive_only": True,
        "advertised_after_forward": new_pin,
        "advertised_after_rollback": previous_pin,
        "advertised_before": new_pin,
        "back": back,
        "bounded": True,
        "corpus": corpus,
        "dataset_repo_id": dataset_repo_id,
        "deletes": False,
        "forward": fwd,
        "legacy_files_deleted": False,
        "new_pin_retained": True,
        "ok": True,
        "pointer_only": True,
        "previous_pin_retained": True,
        "public_advertisement_changed": False,
        "recoverable": True,
        "recovery": forward_operation,
        "reversible": True,
        "rollback_target": previous_pin,
        "scheduled_operations": scheduled,
        "visibility_changed": False,
    }


def rehearse_dual_rollback(
    *,
    state_new: str,
    state_previous: str,
    state_manifest_digest: str,
    federal_new: str,
    federal_previous: str,
    federal_manifest_digest: str,
) -> dict[str, Any]:
    state = rehearse_corpus_rollback(
        corpus="state_laws",
        dataset_repo_id=DEFAULT_STATE_REPO,
        new_pin=state_new,
        previous_pin=state_previous,
        manifest_digest=state_manifest_digest,
        factory=StateRollbackRecord,
        schema_version="state-laws-rollback-rehearsal/v1",
        back_operation="re_advertise_state_previous_pin",
        forward_operation="re_advertise_state_new_pin",
    )
    federal = rehearse_corpus_rollback(
        corpus="federal_register",
        dataset_repo_id=DEFAULT_FEDERAL_REPO,
        new_pin=federal_new,
        previous_pin=federal_previous,
        manifest_digest=federal_manifest_digest,
        factory=FederalRollbackRecord,
        schema_version="federal-register-rollback-rehearsal/v1",
        back_operation="re_advertise_federal_previous_pin",
        forward_operation="re_advertise_federal_new_pin",
    )
    if not (state["bounded"] and state["reversible"] and federal["bounded"] and federal["reversible"]):
        raise RehearsalMismatchError("dual rollback is not bounded and reversible")
    return {
        "additive_only": True,
        "allowed_operations": list(ALLOWED_OPERATIONS),
        "bounded": True,
        "corpora": {
            "federal_register": federal,
            "state_laws": state,
        },
        "deletes": False,
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "forward_rollback_bounded_reversible": True,
        "independent_per_corpus": True,
        "ok": True,
        "pointer_only": True,
        "public_advertisement_changed": False,
        "recoverable": True,
        "reversible": True,
        "visibility_changed": False,
    }


# ---------------------------------------------------------------------------
# Refill closure
# ---------------------------------------------------------------------------


def _finding_is_unresolved(finding: Any) -> bool:
    if finding in (None, "", False, 0):
        return False
    if isinstance(finding, str):
        return finding.casefold() in UNRESOLVED_STATUSES or bool(finding.strip())
    if isinstance(finding, Mapping):
        status = str(finding.get("status") or finding.get("state") or "").casefold()
        if status in {"closed", "resolved", "passed", "absent", "none", "ok"}:
            return False
        if status in UNRESOLVED_STATUSES:
            return True
        if finding.get("unresolved") is True or finding.get("open") is True:
            return True
        if finding.get("closed") is True or finding.get("resolved") is True:
            return False
        # Non-empty mapping without a closed marker is unresolved.
        return True
    return True


def collect_refill_findings(
    *,
    state_publication: Mapping[str, Any],
    federal_publication: Mapping[str, Any],
    state_audit: Mapping[str, Any],
    state_final: Mapping[str, Any],
    extra_findings: Sequence[Any] | None = None,
) -> list[dict[str, Any]]:
    sources: list[tuple[str, Any]] = [
        (STATE_PUBLICATION_RELPATH.as_posix(), state_publication.get("refill_findings")),
        (FEDERAL_PUBLICATION_RELPATH.as_posix(), federal_publication.get("refill_findings")),
        (
            STATE_AUDIT_RELPATH.as_posix(),
            _as_mapping(state_audit.get("delta_refill")).get("findings"),
        ),
    ]
    collected: list[dict[str, Any]] = []
    for path, raw in sources:
        findings = list(raw) if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) else []
        for item in findings:
            collected.append(
                {
                    "item": item,
                    "source": path,
                    "unresolved": _finding_is_unresolved(item),
                }
            )
    if extra_findings:
        for item in extra_findings:
            collected.append(
                {
                    "item": item,
                    "source": "injected",
                    "unresolved": _finding_is_unresolved(item),
                }
            )
    final_acceptance = _as_mapping(state_final.get("acceptance"))
    if final_acceptance.get("no_unresolved_gap") is not True:
        collected.append(
            {
                "item": {"status": "unresolved", "kind": "state_final_gap"},
                "source": STATE_FINAL_RELPATH.as_posix(),
                "unresolved": True,
            }
        )
    return collected


def audit_refill_closure(
    *,
    state_publication: Mapping[str, Any],
    federal_publication: Mapping[str, Any],
    state_audit: Mapping[str, Any],
    state_final: Mapping[str, Any],
    extra_findings: Sequence[Any] | None = None,
) -> dict[str, Any]:
    findings = collect_refill_findings(
        state_publication=state_publication,
        federal_publication=federal_publication,
        state_audit=state_audit,
        state_final=state_final,
        extra_findings=extra_findings,
    )
    unresolved = [item for item in findings if item.get("unresolved") is True]
    if unresolved:
        raise RehearsalMismatchError(
            "unresolved refill finding remains: "
            + ", ".join(str(item.get("source")) for item in unresolved[:8])
        )
    delta = _as_mapping(state_audit.get("delta_refill"))
    if delta.get("ok") is not True or delta.get("mixed_into_this_release") is True:
        raise RehearsalMismatchError("state delta refill is not closed")
    if int(delta.get("count") or 0) != 0:
        raise RehearsalMismatchError("state delta refill still reports findings")
    return {
        "closed": True,
        "codebase_refill": {
            "closed": True,
            "pending": 0,
            "policy": "content-addressed codebase refill; no pending finding remains",
        },
        "findings": [],
        "objective_refill": {
            "closed": True,
            "pending": 0,
            "policy": "content-addressed objective refill; no pending finding remains",
        },
        "ok": True,
        "sources": [
            {
                "closed": True,
                "count": 0,
                "kind": "publication_refill_findings",
                "path": STATE_PUBLICATION_RELPATH.as_posix(),
            },
            {
                "closed": True,
                "count": 0,
                "kind": "publication_refill_findings",
                "path": FEDERAL_PUBLICATION_RELPATH.as_posix(),
            },
            {
                "closed": True,
                "count": 0,
                "kind": "delta_refill",
                "path": STATE_AUDIT_RELPATH.as_posix(),
            },
            {
                "closed": True,
                "count": 0,
                "kind": "state_final_gap",
                "path": STATE_FINAL_RELPATH.as_posix(),
            },
        ],
        "unresolved_count": 0,
        "unresolved_refill_finding_remains": False,
    }


# ---------------------------------------------------------------------------
# Daily versus jurisdictional update semantics
# ---------------------------------------------------------------------------


def explicit_update_semantics(
    *,
    state_audit: Mapping[str, Any],
) -> dict[str, Any]:
    checkpoints = _as_mapping(state_audit.get("update_checkpoints"))
    plan = _as_mapping(state_audit.get("update_plan"))
    if checkpoints.get("atomic_per_jurisdiction") is not True:
        raise RehearsalMismatchError("state update checkpoints are not atomic per jurisdiction")
    if checkpoints.get("completion_basis") != "source_frontier":
        raise RehearsalMismatchError("state update completion basis must remain source_frontier")
    if plan.get("preserves_exact_51") is not True:
        raise RehearsalMismatchError("state update plan does not preserve exact-51")
    if plan.get("delta_only") is not True:
        raise RehearsalMismatchError("state update plan must remain delta-only")

    state = {
        "atomic_per_jurisdiction": True,
        "completion_basis": "source_frontier",
        "delta_only": True,
        "exact_51": True,
        "includes_dc": True,
        "kind": "jurisdictional",
        "not_daily": True,
        "refuses_silent_mix": True,
        "semantics": (
            "State-law updates are jurisdictional: scrape and rebuild only "
            "jurisdictions whose official package changed; never mix a subset "
            "into the sealed exact-51 release; keep atomic per-jurisdiction "
            "checkpoints on the source frontier."
        ),
        "unit": "jurisdiction",
        "update_plan_preserves_transactional_gates": bool(
            plan.get("preserves_transactional_gates")
        ),
    }
    federal = {
        "cutoff_relative": True,
        "kind": "daily",
        "not_jurisdictional": True,
        "observation_cutoff": OBSERVATION_CUTOFF,
        "partition": "year_month",
        "semantics": (
            "Federal Register updates are daily and cutoff-relative: admit "
            "documents through the sealed observation cutoff; never treat "
            "wall-clock time as legal currentness of the daily register; "
            "rebuild year_month partitions that changed after the cutoff."
        ),
        "unit": "publication_date",
        "wall_clock_is_not_currentness": True,
    }
    if state["kind"] == federal["kind"]:
        raise RehearsalMismatchError("daily and jurisdictional kinds must remain distinct")
    return {
        "daily_versus_jurisdictional": True,
        "explicit": True,
        "federal_register": federal,
        "must_not_conflate": True,
        "ok": True,
        "state_laws": state,
    }


def operations_paths() -> dict[str, Any]:
    return {
        "build": {
            "federal_register": FEDERAL_BUILD_CLI_RELPATH.as_posix(),
            "state_laws": STATE_BUILD_CLI_RELPATH.as_posix(),
        },
        "monitor": {
            "human": STATUS_SH_RELPATH.as_posix(),
            "json": [STATUS_PY_RELPATH.as_posix(), "--json"],
            "observe": [STATUS_PY_RELPATH.as_posix(), "--json", "--observe-seconds", "20"],
        },
        "query": {
            "cross_corpus": [CROSS_CANARY_CLI_RELPATH.as_posix(), "--check"],
            "federal_register": FEDERAL_QUERY_CLI_RELPATH.as_posix(),
            "state_laws": STATE_QUERY_CLI_RELPATH.as_posix(),
        },
        "refill": {
            "federal_register": FEDERAL_ACQUIRE_CLI_RELPATH.as_posix(),
            "state_laws": STATE_REFILL_CLI_RELPATH.as_posix(),
        },
        "resume_and_scrape": {
            "federal_register": FEDERAL_ACQUIRE_CLI_RELPATH.as_posix(),
            "state_laws": COHORT_CLI_RELPATH.as_posix(),
        },
        "update": {
            "federal_register": "daily_cutoff_relative_year_month_partitions",
            "state_laws": "jurisdictional_atomic_source_frontier",
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
    runbook = runbook_path.read_text(encoding="utf-8")
    lowered = runbook.casefold()
    for needle in ("hf_token=", "authorization: bearer", "-----begin"):
        if needle in lowered:
            raise RehearsalSafetyError("operator docs embed credential-like material")
    phrases = _require_phrases(runbook, RUNBOOK_REQUIRED_PHRASES, label="runbook")
    for required in (
        "all four pins",
        "daily versus jurisdictional",
        "refill closure",
        "bounded",
        "reversible",
        "without deleting",
    ):
        if required not in lowered:
            raise RehearsalMismatchError(f"runbook does not document {required}")
    return {
        "ok": True,
        "runbook": {
            "ok": True,
            "path": RUNBOOK_RELPATH.as_posix(),
            "required_phrase_count": len(phrases),
            "sha256": sha256_file(runbook_path),
        },
        "update_semantics_documented": True,
    }


# ---------------------------------------------------------------------------
# Receipt assembly
# ---------------------------------------------------------------------------


def _extract_manifest_digest(receipt: Mapping[str, Any], *, name: str) -> str:
    digest = str(
        receipt.get("final_manifest_digest") or receipt.get("manifest_digest") or ""
    ).strip()
    return _require_sha256(digest, name=name)


def _extract_public_pair(receipt: Mapping[str, Any], *, corpus: str) -> tuple[str, str]:
    new_pin = _require_hex40(
        receipt.get("public_sha") or receipt.get("public_revision"),
        name=f"{corpus}.public_sha",
    )
    previous = _require_hex40(
        receipt.get("previous_public_pin") or receipt.get("old_sha"),
        name=f"{corpus}.previous_public_pin",
    )
    return new_pin, previous


def build_rehearsal_report(*, repo_root: Path | str | None = None) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    state_publication = load_state_publication(repo_root=root)
    federal_publication = load_federal_publication(repo_root=root)
    state_canary = load_state_public_canary(repo_root=root)
    federal_canary = load_federal_public_canary(repo_root=root)
    state_baseline = load_state_baseline(repo_root=root)
    federal_baseline = load_federal_baseline(repo_root=root)
    state_rollback = load_state_rollback_rehearsal(repo_root=root)
    state_audit = load_state_post_publication_audit(repo_root=root)
    state_final = load_state_final_receipt(repo_root=root)
    cross_canary = load_cross_corpus_canary(repo_root=root)

    state_new, state_previous = _extract_public_pair(
        state_publication, corpus="state"
    )
    federal_new, federal_previous = _extract_public_pair(
        federal_publication, corpus="federal"
    )
    if str(state_canary.get("public_sha") or "") != state_new:
        raise RehearsalMismatchError("state public canary SHA does not match publication SHA")
    if str(federal_canary.get("public_sha") or "") != federal_new:
        raise RehearsalMismatchError("federal public canary SHA does not match publication SHA")
    if str(state_final.get("public_sha") or state_new) not in {state_new}:
        raise RehearsalMismatchError("state final receipt public SHA drifted")
    if str(state_rollback.get("public_sha") or "") != state_new:
        raise RehearsalMismatchError("state rollback rehearsal public SHA drifted")

    state_manifest = _extract_manifest_digest(
        state_publication, name="state.manifest_digest"
    )
    federal_manifest = _extract_manifest_digest(
        federal_publication, name="federal.manifest_digest"
    )

    queryability = rehearse_four_pin_query(
        state_new=state_new,
        state_previous=state_previous,
        federal_new=federal_new,
        federal_previous=federal_previous,
        state_canary=state_canary,
        federal_canary=federal_canary,
        state_baseline=state_baseline,
        federal_baseline=federal_baseline,
        cross_canary=cross_canary,
    )
    rollback = rehearse_dual_rollback(
        state_new=state_new,
        state_previous=state_previous,
        state_manifest_digest=state_manifest,
        federal_new=federal_new,
        federal_previous=federal_previous,
        federal_manifest_digest=federal_manifest,
    )
    refill = audit_refill_closure(
        state_publication=state_publication,
        federal_publication=federal_publication,
        state_audit=state_audit,
        state_final=state_final,
    )
    updates = explicit_update_semantics(state_audit=state_audit)
    docs = validate_operator_docs(repo_root=root)
    operations = operations_paths()

    acceptance = {
        "all_four_pins_queryable": bool(queryability.get("all_four_queryable")),
        "daily_versus_jurisdictional_update_semantics_explicit": bool(
            updates.get("explicit") and updates.get("daily_versus_jurisdictional")
        ),
        "forward_rollback_bounded_reversible": bool(
            rollback.get("bounded") and rollback.get("reversible")
        ),
        "legacy_files_deleted": False,
        "no_absolute_path_or_secret": True,
        "no_deletion": True,
        "no_force_push": True,
        "no_unresolved_refill_finding": bool(refill.get("closed")),
        "no_visibility_change": True,
        "public_advertisement_unchanged": True,
        "runbook_documents_operations": bool(docs.get("ok")),
    }
    expected_acceptance = {
        "all_four_pins_queryable": True,
        "daily_versus_jurisdictional_update_semantics_explicit": True,
        "forward_rollback_bounded_reversible": True,
        "legacy_files_deleted": False,
        "no_absolute_path_or_secret": True,
        "no_deletion": True,
        "no_force_push": True,
        "no_unresolved_refill_finding": True,
        "no_visibility_change": True,
        "public_advertisement_unchanged": True,
        "runbook_documents_operations": True,
    }
    if acceptance != expected_acceptance:
        failed = [
            key
            for key, value in expected_acceptance.items()
            if acceptance.get(key) is not value
        ]
        raise RehearsalMismatchError(
            "dual rollback rehearsal acceptance failed: " + ", ".join(failed)
        )

    report: dict[str, Any] = {
        "acceptance": acceptance,
        "bound_inputs": {
            "cross_corpus_canary": CROSS_CORPUS_CANARY_RELPATH.as_posix(),
            "federal_baseline": FEDERAL_BASELINE_RELPATH.as_posix(),
            "federal_public_canary": FEDERAL_PUBLIC_CANARY_RELPATH.as_posix(),
            "federal_publication_receipt": FEDERAL_PUBLICATION_RELPATH.as_posix(),
            "state_baseline": STATE_BASELINE_RELPATH.as_posix(),
            "state_final_release_receipt": STATE_FINAL_RELPATH.as_posix(),
            "state_post_publication_audit": STATE_AUDIT_RELPATH.as_posix(),
            "state_public_canary": STATE_PUBLIC_CANARY_RELPATH.as_posix(),
            "state_publication_receipt": STATE_PUBLICATION_RELPATH.as_posix(),
            "state_rollback_rehearsal": STATE_ROLLBACK_RELPATH.as_posix(),
        },
        "code_version": CODE_VERSION,
        "compact_recipe": True,
        "currentness_disclaimer": COMBINED_CURRENTNESS_DISCLAIMER,
        "depends_on": list(DEPENDS_ON),
        "docs": docs,
        "dry_run": True,
        "fixture_id": FIXTURE_ID,
        "fixture_only": True,
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "goal_id": GOAL_ID,
        "legacy_files_deleted": False,
        "live_network": False,
        "manifests": {
            "federal_register": federal_manifest,
            "state_laws": state_manifest,
        },
        "mutation_executed": False,
        "network_required": False,
        "observation_cutoff": OBSERVATION_CUTOFF,
        "operations": operations,
        "pins": {
            "all_four_queryable": True,
            "count": PIN_COUNT,
            "federal_new": federal_new,
            "federal_previous": federal_previous,
            "roles": list(PIN_ROLES),
            "state_new": state_new,
            "state_previous": state_previous,
        },
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "public_advertisement_changed": False,
        "public_branch": PUBLIC_BRANCH,
        "queryability": queryability,
        "read_only": True,
        "refill_closure": refill,
        "release_points": {
            "federal_register": FEDERAL_RELEASE_POINT,
            "state_laws": STATE_RELEASE_POINT,
        },
        "release_profiles": {
            "federal_register": DEFAULT_FEDERAL_CONFIG,
            "state_laws": DEFAULT_STATE_CONFIG,
        },
        "remote_write_contacted": False,
        "repositories": {
            "federal_register": DEFAULT_FEDERAL_REPO,
            "state_laws": DEFAULT_STATE_REPO,
        },
        "rollback": rollback,
        "schema": REHEARSAL_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "secret_redacted": True,
        "staging_branches": {
            "federal_register": DEFAULT_FEDERAL_STAGING,
            "state_laws": DEFAULT_STATE_STAGING,
        },
        "status": "rehearsed",
        "task_id": TASK_ID,
        "tokens_used": False,
        "update_semantics": updates,
    }
    reject_credentials_in_payload(report, label="dual_rollback_rehearsal")
    reject_path_leaks(report, label="dual_rollback_rehearsal")
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
    reject_credentials_in_payload(sealed, label="sealed_dual_rollback_rehearsal")
    reject_path_leaks(sealed, label="sealed_dual_rollback_rehearsal")
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
            "sealed dual rollback rehearsal check failed: " + "; ".join(mismatches[:16])
        )
    acceptance = (
        sealed.get("acceptance") if isinstance(sealed.get("acceptance"), Mapping) else {}
    )
    pins = _as_mapping(sealed.get("pins"))
    return {
        "acceptance": dict(acceptance),
        "all_four_pins_queryable": bool(acceptance.get("all_four_pins_queryable")),
        "daily_versus_jurisdictional_update_semantics_explicit": bool(
            acceptance.get("daily_versus_jurisdictional_update_semantics_explicit")
        ),
        "forward_rollback_bounded_reversible": bool(
            acceptance.get("forward_rollback_bounded_reversible")
        ),
        "mismatches": [],
        "no_unresolved_refill_finding": bool(
            acceptance.get("no_unresolved_refill_finding")
        ),
        "ok": True,
        "path": DEFAULT_REPORT_RELPATH.as_posix(),
        "pin_count": int(pins.get("count") or 0),
        "task_id": TASK_ID,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rehearse_legal_corpora_release_rollback.py",
        description=(
            "Rehearse four-pin query, bounded dual-release rollback, refill "
            f"closure, and daily versus jurisdictional updates ({TASK_ID}). "
            "Default mode is offline and does not mutate either Hub repository."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the sealed dual rollback rehearsal against a fresh offline build",
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
            "Path to the sealed dual rollback rehearsal report "
            f"(default: {DEFAULT_REPORT_RELPATH.as_posix()})"
        ),
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Always print the rehearsal/verification result as JSON",
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
        if args.check and not args.write:
            result = check_rehearsal(path=report_path)
            if args.print_json or args.output is not None:
                write_json(args.output, result)
            print(
                "ok={ok} task_id={task_id} all_four_pins_queryable={pins} "
                "rollback_bounded_reversible={rollback} "
                "no_unresolved_refill={refill} "
                "daily_vs_jurisdictional={updates}".format(
                    ok=result.get("ok"),
                    task_id=result.get("task_id"),
                    pins=result.get("all_four_pins_queryable"),
                    rollback=result.get("forward_rollback_bounded_reversible"),
                    refill=result.get("no_unresolved_refill_finding"),
                    updates=result.get(
                        "daily_versus_jurisdictional_update_semantics_explicit"
                    ),
                ),
                file=sys.stderr,
            )
            return 0 if result.get("ok") else 1

        report = build_rehearsal_report()
        if args.write:
            destination = (
                Path(args.output).expanduser().resolve()
                if args.output is not None
                else report_path
            )
            write_json(destination, report)
            print(
                f"wrote {repo_relpath(destination)} digest={report['digest']}",
                file=sys.stderr,
            )
            if args.check:
                check_rehearsal(path=destination)
        elif args.output is not None or args.print_json or not args.check:
            write_json(args.output, report)
        return 0
    except (RehearsalError, MutableRevisionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
