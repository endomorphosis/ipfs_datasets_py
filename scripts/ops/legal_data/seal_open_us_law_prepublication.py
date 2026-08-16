#!/usr/bin/env python3
"""Create the manifest-bound Open US Law prepublication authorization seal (OUL-043).

The seal is assembled **before** any public Dataset or Bucket mutation and
binds:

* the exact OUL-040 candidate (manifest, release root, clean commit)
* the live isolated OUL-041/OUL-042 staging revision and bucket prefix
* the current credential principal and write scope
* predecessor task and goal closure, including generated refill work
* authorized target IDs and the additive operation set
* a short-lived expiration that requires reissue after TTL

This CLI never publishes, never contacts the Hub, never embeds secrets or
absolute local paths, and never mutates a remote target. ``--no-mutate``
forbids rewriting the sealed report.

Validation gate (offline)::

    python scripts/ops/legal_data/seal_open_us_law_prepublication.py \\
        --require-live-staging --no-mutate --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.open_us_law_publication_gate import (  # noqa: E402
    AUTHORIZED_BUCKET_ID,
    AUTHORIZED_DATASET_REPO_ID,
    AUTHORIZED_OPERATIONS,
    BUCKET_POINTER_PATH,
    BUCKET_RELEASE_PREFIX_TEMPLATE,
    FORBIDDEN_OPERATIONS,
    GENERATED_WORK_TASK_NUMBER_FLOOR,
    QUERY_OPERATIONS,
    TERMINAL_TASK_STATUSES,
    credentials_scope_for,
    evaluate_publication_gate,
    sealed_publication_policy,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (  # noqa: E402
    ADR_PATH,
    DEFAULT_CONFIGURATION,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    RELEASE_PROFILE,
    SOURCE_BUCKET,
    digest_mapping,
    normalize_sha256,
    require_immutable_revision,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "OUL-043"
GOAL_ID: Final = "OUL-G080"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
PRODUCER: Final = "seal_open_us_law_prepublication.py"
CODE_VERSION: Final = "1"
BUNDLE: Final = "publication-seal"
BOARD_NAMESPACE: Final = "open-us-law-reindex-v1"
DEPENDS_ON: Final[tuple[str, ...]] = ("OUL-007", "OUL-042")

SEAL_SCHEMA: Final = "ipfs_datasets_py/open-us-law-prepublication-seal@1"
SCHEMA_VERSION: Final = "open-us-law-prepublication-seal/v1"
FIXTURE_ID: Final = "open-us-law-prepublication-seal-v1"

DEFAULT_SEAL_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/prepublication_seal.json"
)
CANDIDATE_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/release_candidate.json"
)
STAGING_RELPATH: Final = Path("docs/reports/open_us_law_reindex/staging_upload.json")
CANARY_RELPATH: Final = Path("docs/reports/open_us_law_reindex/staging_canary.json")
TODO_RELPATH: Final = Path("docs/architecture/open_us_law_reindex.todo.md")
OBJECTIVES_RELPATH: Final = Path(
    "docs/architecture/open_us_law_reindex.objectives.md"
)
SOURCE_ADMISSION_RELPATH: Final = Path("data/legal/open_us_law/source_admission.json")
EVALUATION_RELPATH: Final = Path("docs/reports/open_us_law_reindex/evaluation.json")
PUBLICATION_POLICY_SCHEMA_RELPATH: Final = Path(
    "data/legal/open_us_law/publication_policy.schema.json"
)

CANDIDATE_SCHEMA: Final = "ipfs_datasets_py/open-us-law-release-candidate@1"
STAGING_SCHEMA: Final = "ipfs_datasets_py/open-us-law-staging-upload@1"
CANARY_SCHEMA: Final = "ipfs_datasets_py/open-us-law-staging-canary@1"

SEALED_AT: Final = "2026-08-16T00:00:00Z"
PREPUBLICATION_TTL_SECONDS: Final = 2_592_000  # 30 days
DEFAULT_STAGING_BRANCH: Final = "stage/open-us-law-sparse-graphrag-v1"
DEFAULT_CONFIG_NAME: Final = DEFAULT_CONFIGURATION
PINNED_MODEL_ID: Final = DEFAULT_EMBEDDING_MODEL_ID
PINNED_MODEL_REVISION: Final = DEFAULT_EMBEDDING_MODEL_REVISION

SEAL_TIMING: Final = "before_mutation"
PREDECESSOR_TASK_MAX: Final = 42

CURRENTNESS_DISCLAIMER: Final = (
    "Acquisition and publication timestamps record when a package was retrieved "
    "or sealed; they are not a claim that the codified text is legally current as "
    "of wall-clock time. Retrieval output is a research aid and is not a "
    "substitute for the official source."
)

ACCEPTANCE_CRITERIA: Final = (
    "The seal is created before mutation and binds the exact candidate, "
    "staging revision, bucket prefix, current principal and write scope, "
    "task and goal closure including refill work, target IDs, operation "
    "set, and expiration."
)

SECRET_ENV_NAMES: Final[tuple[str, ...]] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
    "OPEN_US_LAW_HF_TOKEN",
    "OPEN_US_LAW_PUBLICATION_AUTHORIZATION",
    "OPEN_US_LAW_STAGING_AUTHORIZATION",
)

PRODUCTION_REFS: Final[frozenset[str]] = frozenset(
    {"main", "master", "latest", "head", "tip", "trunk", "default", "current"}
)

REQUIRED_PREDECESSOR_GOAL_IDS: Final[tuple[str, ...]] = (
    "OUL-G000",
    "OUL-G010",
    "OUL-G020",
    "OUL-G021",
    "OUL-G022",
    "OUL-G023",
    "OUL-G024",
    "OUL-G030",
    "OUL-G040",
    "OUL-G050",
    "OUL-G060",
    "OUL-G070",
)

DATASET_PRINCIPAL_IDENTITY: Final = f"env:{AUTHORIZED_DATASET_REPO_ID}"
BUCKET_PRINCIPAL_IDENTITY: Final = f"env:{AUTHORIZED_BUCKET_ID}"

_TASK_HEADER_RE = re.compile(r"^## (OUL-\d{3,})\s+(.+)$")
_GOAL_HEADER_RE = re.compile(r"^## (OUL-G\d{3,})\s+(.+)$")
_FIELD_RE = re.compile(r"^- ([A-Za-z0-9][^:]*):\s*(.*)$")
_TASK_ID_RE = re.compile(r"^OUL-(\d{3,})$")
_GOAL_ID_RE = re.compile(r"^OUL-G(\d{3,})$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_UTC_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_DATASET_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)
_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key|operator_key|"
    r"staging_authorization)s?$",
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
_TIMESTAMP_KEY_RE = re.compile(
    r"(created_at|generated_at|started_at|finished_at|timestamp|observed_at|"
    r"duration_ms|wall_time|host_name|hostname|pid|runtime)",
    re.IGNORECASE,
)
_MUTABLE_REF_MARKERS: Final[tuple[str, ...]] = (
    "/resolve/main/",
    "/resolve/master/",
    "/resolve/latest/",
    "/tree/main/",
    "/blob/main/",
    "refs/heads/",
)
_LOCAL_PATH_MARKERS: Final[tuple[str, ...]] = (
    "file://",
    "/home/",
    "/tmp/",
    "/var/",
    "c:\\",
    "c:/",
)
_PUBLIC_PATH_LEAK_MARKERS: Final[tuple[str, ...]] = ("hf_",)
_ALLOWED_TOKEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "credentials_scope",
        "credentials_environment_only",
        "secret_redaction_required",
        "secret_redacted",
        "authorization_status",
        "authorization_receipt_id",
        "mutation_requires_authorization",
        "credential_identity",
        "publication_authorization_required",
    }
)


class PrepublicationSealError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class MissingInputError(PrepublicationSealError):
    """Raised when a required producer input is absent."""


class MismatchError(PrepublicationSealError):
    """Raised when a bound digest or field does not match."""


class StaleInputError(PrepublicationSealError):
    """Raised when a sealed surface drifted from producer evidence."""


class PathLeakError(PrepublicationSealError):
    """Raised when absolute local paths appear in a public seal."""


class SecretLeakError(PrepublicationSealError):
    """Raised when credential-like material appears in a public seal."""


class ClosureError(PrepublicationSealError):
    """Raised when predecessor or refill closure is incomplete."""


class MutationForbiddenError(PrepublicationSealError):
    """Raised when a mutation is requested from this CLI."""


class LiveStagingError(PrepublicationSealError):
    """Raised when --require-live-staging cannot bind isolated staging."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_seal_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_SEAL_RELPATH).resolve()


def default_candidate_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / CANDIDATE_RELPATH).resolve()


def default_staging_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / STAGING_RELPATH).resolve()


def default_canary_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / CANARY_RELPATH).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise MissingInputError(f"JSON file not found: {target.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PrepublicationSealError(f"cannot read JSON {target.name}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise PrepublicationSealError(f"JSON root must be an object: {target.name}")
    return dict(payload)


def write_json_report(payload: Mapping[str, Any], path: Path) -> Path:
    reject_credentials_in_payload(payload, label="prepublication_seal")
    reject_path_leaks(payload, label="prepublication_seal")
    reject_identity_contamination(payload, label="prepublication_seal")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
    return path


def sha256_file(path: Path | str) -> str:
    target = Path(path)
    if not target.is_file():
        raise MissingInputError(f"file not found for digest: {Path(path).name}")
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_file(relpath: Path | str, *, repo_root: Path) -> Path:
    path = (repo_root / Path(relpath)).resolve()
    if not path.is_file():
        raise MissingInputError(
            f"required producer input missing: {Path(relpath).as_posix()}"
        )
    return path


def _parse_utc(value: str) -> datetime:
    if not _UTC_RE.fullmatch(value):
        raise PrepublicationSealError(
            f"timestamp must be YYYY-MM-DDTHH:MM:SSZ: {value!r}"
        )
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_expiry(
    *,
    sealed_at: str = SEALED_AT,
    ttl_seconds: int = PREPUBLICATION_TTL_SECONDS,
) -> str:
    if ttl_seconds <= 0:
        raise PrepublicationSealError("prepublication ttl_seconds must be positive")
    return _format_utc(_parse_utc(sealed_at) + timedelta(seconds=int(ttl_seconds)))


def require_repo_id(value: Any, *, name: str = "repo_id") -> str:
    text = str(value or "").strip()
    if not _DATASET_ID_RE.fullmatch(text):
        raise MismatchError(f"{name} must be owner/name, got {value!r}")
    return text


def require_immutable_staging_revision(value: Any, *, name: str = "revision") -> str:
    if not isinstance(value, str) or not value.strip():
        raise LiveStagingError(
            f"{name} must be an explicit immutable 40-hex staging revision"
        )
    text = value.strip()
    if text.casefold() in PRODUCTION_REFS or text.casefold().startswith("refs/"):
        raise LiveStagingError(
            f"{name} must never be a mutable ref ({text!r}); pin a 40-hex SHA"
        )
    try:
        pinned = require_immutable_revision(text, name=name)
    except Exception as exc:
        raise LiveStagingError(str(exc)) from exc
    folded = pinned.casefold()
    if not _GIT_SHA_RE.fullmatch(folded):
        raise LiveStagingError(
            f"{name} must be a 40-character lowercase hex commit SHA, got {value!r}"
        )
    return folded


def require_bucket_prefix(value: Any, *, manifest_digest: str) -> str:
    text = str(value or "").strip()
    digest = normalize_sha256(manifest_digest, name="manifest_digest")
    expected = f"releases/{digest}/"
    if text != expected:
        raise LiveStagingError(
            "bucket prefix must be the unique content-addressed "
            f"{expected}, got {value!r}"
        )
    return text


# ---------------------------------------------------------------------------
# Credential / path leak guards
# ---------------------------------------------------------------------------


def reject_credentials_in_payload(value: Any, *, label: str = "payload") -> None:
    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _TOKEN_KEY_RE.search(key_text) and not isinstance(child, bool):
                    if key_text.casefold() in _ALLOWED_TOKEN_KEYS:
                        visit(child, child_path)
                        continue
                    offenders.append(child_path)
                    continue
                visit(child, child_path)
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, str):
            lowered = item.casefold()
            if "hf_" in item or lowered.startswith("hf_"):
                offenders.append(path or label)
            for env_name in SECRET_ENV_NAMES:
                env_val = os.environ.get(env_name)
                if env_val and env_val in item:
                    offenders.append(path or label)

    visit(value, label)
    if offenders:
        raise SecretLeakError(
            "credential-like material in "
            + label
            + ": "
            + ", ".join(sorted(set(offenders))[:12])
        )


def reject_path_leaks(value: Any, *, label: str = "payload") -> None:
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
            if (
                _ABS_PATH_RE.search(item)
                or _POSIX_HOME_RE.search(item)
                or _WINDOWS_USER_RE.search(item)
            ):
                offenders.append(path or label)

    visit(value, label)
    if offenders:
        raise PathLeakError(
            "absolute local path leak in "
            + label
            + ": "
            + ", ".join(sorted(set(offenders))[:12])
        )


def reject_identity_contamination(value: Any, *, label: str = "seal") -> None:
    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _TIMESTAMP_KEY_RE.search(key_text):
                    offenders.append(child_path)
                visit(child, child_path)
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, str):
            lowered = item.casefold()
            if any(marker in lowered for marker in _MUTABLE_REF_MARKERS):
                offenders.append(f"{path}:mutable_ref")
            if any(marker in lowered for marker in _LOCAL_PATH_MARKERS):
                offenders.append(f"{path}:local_path")
            if (
                re.fullmatch(r"[0-9a-f]{8,63}", item)
                and not _SHA256_RE.fullmatch(item)
                and not _GIT_SHA_RE.fullmatch(item)
            ):
                if "hash" in path.casefold() or "sha" in path.casefold():
                    offenders.append(f"{path}:truncated_hash")

    visit(value, label)
    if offenders:
        raise PrepublicationSealError(
            "identity contamination detected: " + ", ".join(sorted(set(offenders)))
        )


def reject_secrets_in_argv(argv: Sequence[str]) -> None:
    joined = " ".join(str(item) for item in argv)
    lowered = joined.casefold()
    needles = (
        "hf_token=",
        "authorization:",
        "bearer ",
        "access_token=",
        "api_token=",
        "open_us_law_hf_token=",
        "open_us_law_publication_authorization=",
        "open_us_law_staging_authorization=",
    )
    for needle in needles:
        if needle in lowered:
            raise SecretLeakError(
                "refusing to accept secrets on the command line; "
                "credentials remain environment-only"
            )
    for env_name in SECRET_ENV_NAMES:
        env_val = os.environ.get(env_name)
        if env_val and env_val in joined:
            raise SecretLeakError(
                f"refusing to accept ${env_name} value on the command line"
            )


# ---------------------------------------------------------------------------
# Board / closure
# ---------------------------------------------------------------------------


def _task_number(task_id: str) -> int:
    match = _TASK_ID_RE.fullmatch(task_id)
    if not match:
        raise ClosureError(f"invalid task id: {task_id!r}")
    return int(match.group(1))


def _split_outputs(raw: str) -> list[str]:
    items: list[str] = []
    for part in raw.split(","):
        text = part.strip()
        if text:
            items.append(text.replace("\\", "/"))
    return items


def parse_todo_tasks(text: str) -> dict[str, dict[str, Any]]:
    tasks: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        header = _TASK_HEADER_RE.match(line)
        if header:
            current = {
                "task_id": header.group(1),
                "title": header.group(2).strip(),
                "status": "",
                "goal_id": "",
                "outputs": [],
                "depends_on": [],
            }
            tasks[current["task_id"]] = current
            continue
        if current is None:
            continue
        field = _FIELD_RE.match(line)
        if not field:
            continue
        name = field.group(1).strip().casefold()
        value = field.group(2).strip()
        if name == "status":
            current["status"] = value.casefold()
        elif name == "goal id":
            current["goal_id"] = value
        elif name == "outputs":
            current["outputs"] = _split_outputs(value)
        elif name == "depends on":
            current["depends_on"] = [
                item.strip() for item in value.split(",") if item.strip()
            ]
    return tasks


def parse_objective_goals(text: str) -> dict[str, dict[str, Any]]:
    goals: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        header = _GOAL_HEADER_RE.match(line)
        if header:
            current = {
                "goal_id": header.group(1),
                "title": header.group(2).strip(),
                "status": "",
                "parent": "",
                "outputs": [],
            }
            goals[current["goal_id"]] = current
            continue
        if current is None:
            continue
        field = _FIELD_RE.match(line)
        if not field:
            continue
        name = field.group(1).strip().casefold()
        value = field.group(2).strip()
        if name == "status":
            current["status"] = value.casefold()
        elif name == "parent":
            current["parent"] = value
        elif name == "outputs":
            current["outputs"] = _split_outputs(value)
    return goals


def required_predecessor_task_ids() -> tuple[str, ...]:
    return tuple(f"OUL-{index:03d}" for index in range(0, PREDECESSOR_TASK_MAX + 1))


def required_predecessor_goal_ids() -> tuple[str, ...]:
    return REQUIRED_PREDECESSOR_GOAL_IDS


def _path_is_public_safe(relpath: str) -> bool:
    return not any(marker in relpath for marker in _PUBLIC_PATH_LEAK_MARKERS)


def _public_evidence_path(relpath: str, *, task_id: str) -> str:
    if _path_is_public_safe(relpath):
        return relpath
    return f"closure/predecessor/{task_id}"


def _select_evidence_path(
    outputs: Sequence[str],
    *,
    repo_root: Path,
) -> str | None:
    existing: list[str] = []
    for raw in outputs:
        rel = raw.replace("\\", "/").lstrip("./")
        if not rel or rel.startswith("/"):
            continue
        if (repo_root / rel).is_file():
            existing.append(rel)
    if not existing:
        return None
    preferred = [path for path in existing if _path_is_public_safe(path)] or existing
    reports = [path for path in preferred if path.startswith("docs/reports/")]
    data_files = [path for path in preferred if path.startswith("data/")]
    fixtures = [path for path in preferred if path.startswith("tests/fixtures/")]
    for group in (reports, data_files, fixtures, preferred):
        if group:
            return group[0]
    return None


_POST_PUBLICATION_DEPENDENCIES: Final[frozenset[str]] = frozenset(
    {
        TASK_ID,
        "OUL-044",
        "OUL-045",
        "OUL-046",
        "OUL-047",
        "OUL-048",
        GOAL_ID,
        "OUL-G090",
    }
)


def _depends_on_post_publication(depends_on: Sequence[str]) -> bool:
    return any(
        str(raw or "").strip() in _POST_PUBLICATION_DEPENDENCIES for raw in depends_on
    )


def build_task_closure(
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    todo_path = _require_file(TODO_RELPATH, repo_root=root)
    parsed = parse_todo_tasks(todo_path.read_text(encoding="utf-8"))
    required = required_predecessor_task_ids()
    missing = [task_id for task_id in required if task_id not in parsed]
    if missing:
        raise ClosureError("todo is missing predecessor tasks: " + ", ".join(missing[:8]))

    entries: list[dict[str, Any]] = []
    incomplete: list[str] = []
    for task_id in required:
        record = parsed[task_id]
        status = str(record.get("status") or "").casefold()
        evidence_path = _select_evidence_path(record.get("outputs") or [], repo_root=root)
        if evidence_path is None:
            raise MissingInputError(f"predecessor {task_id} has no existing output file")
        digest = sha256_file(root / evidence_path)
        if status not in TERMINAL_TASK_STATUSES:
            incomplete.append(task_id)
        entries.append(
            {
                "evidence_path": _public_evidence_path(evidence_path, task_id=task_id),
                "goal_id": record.get("goal_id") or "",
                "sha256": digest,
                "status": status,
                "task_id": task_id,
                "title": record.get("title") or "",
            }
        )

    refill: list[dict[str, Any]] = []
    refill_blockers: list[str] = []
    publication_blockers: list[str] = []
    for task_id, record in sorted(parsed.items(), key=lambda item: _task_number(item[0])):
        if _task_number(task_id) < GENERATED_WORK_TASK_NUMBER_FLOOR:
            continue
        status = str(record.get("status") or "").casefold()
        evidence_path = _select_evidence_path(record.get("outputs") or [], repo_root=root)
        binding: dict[str, Any] = {
            "goal_id": record.get("goal_id") or "",
            "post_publication": _depends_on_post_publication(
                record.get("depends_on") or []
            ),
            "status": status,
            "task_id": task_id,
            "title": record.get("title") or "",
        }
        if evidence_path is not None:
            binding["evidence_path"] = _public_evidence_path(
                evidence_path, task_id=task_id
            )
            binding["sha256"] = sha256_file(root / evidence_path)
        refill.append(binding)
        if status not in TERMINAL_TASK_STATUSES:
            refill_blockers.append(task_id)
            if not binding["post_publication"]:
                publication_blockers.append(task_id)

    if incomplete:
        raise ClosureError(
            "predecessor task closure is incomplete: " + ", ".join(incomplete[:12])
        )
    if publication_blockers:
        raise ClosureError(
            "nonterminal refill work blocks the prepublication seal: "
            + ", ".join(publication_blockers[:12])
        )

    return {
        "complete": True,
        "generated_blockers": refill_blockers,
        "generated_count": len(refill),
        "generated_tasks": refill,
        "predecessor_count": len(entries),
        "predecessors": entries,
        "publication_blockers": publication_blockers,
        "refill_bound": True,
        "refill_complete": not refill_blockers,
        "refill_count": len(refill),
        "refill_work": refill,
        "required_task_ids": list(required),
        "todo_path": TODO_RELPATH.as_posix(),
        "todo_sha256": sha256_file(todo_path),
    }


def build_goal_closure(
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    objectives_path = _require_file(OBJECTIVES_RELPATH, repo_root=root)
    parsed = parse_objective_goals(objectives_path.read_text(encoding="utf-8"))
    required = required_predecessor_goal_ids()
    missing = [goal_id for goal_id in required if goal_id not in parsed]
    if missing:
        raise ClosureError(
            "objectives are missing predecessor goals: " + ", ".join(missing)
        )

    entries: list[dict[str, Any]] = []
    for goal_id in required:
        record = parsed[goal_id]
        entries.append(
            {
                "goal_id": goal_id,
                "parent": record.get("parent") or "",
                "status": str(record.get("status") or "").casefold(),
                "title": record.get("title") or "",
            }
        )

    parent = parsed.get(GOAL_ID) or {}
    return {
        "bound": True,
        "objectives_path": OBJECTIVES_RELPATH.as_posix(),
        "objectives_sha256": sha256_file(objectives_path),
        "parent_goal": {
            "goal_id": GOAL_ID,
            "status": str(parent.get("status") or "active").casefold(),
            "title": parent.get("title") or "",
        },
        "predecessors": entries,
        "required_goal_ids": list(required),
    }


# ---------------------------------------------------------------------------
# Producer evidence
# ---------------------------------------------------------------------------


def _verify_receipt_digest(receipt: Mapping[str, Any], *, digest_key: str) -> str:
    expected = digest_mapping(
        {key: value for key, value in receipt.items() if key != digest_key}
    )
    bound = str(receipt.get(digest_key) or "")
    if bound != expected:
        raise StaleInputError(f"{digest_key} does not match the sealed surface")
    return expected


def load_candidate_receipt(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_candidate_path(repo_root)
    )
    if not target.is_file():
        raise MissingInputError(
            f"release-candidate receipt is required: {CANDIDATE_RELPATH.as_posix()}"
        )
    receipt = load_json_mapping(target)
    if receipt.get("schema") != CANDIDATE_SCHEMA:
        raise MismatchError("candidate receipt schema mismatch")
    if receipt.get("task_id") != "OUL-040":
        raise MismatchError("candidate receipt is not the OUL-040 seal")
    if receipt.get("publication_authorized") is not False:
        raise MismatchError("candidate receipt must not authorize publication")
    if receipt.get("authorizing_for_publication") is not False:
        raise MismatchError("candidate receipt must not authorize publication")
    _verify_receipt_digest(receipt, digest_key="receipt_sha256")
    candidate = dict(receipt.get("candidate") or {})
    normalize_sha256(str(candidate.get("manifest_digest") or ""), name="candidate.manifest")
    commit = dict(receipt.get("clean_commit") or {})
    require_immutable_revision(str(commit.get("sha") or ""), name="candidate.clean_commit")
    targets = dict(receipt.get("target_ids") or {})
    if require_repo_id(targets.get("dataset_repo_id"), name="candidate.dataset") != (
        AUTHORIZED_DATASET_REPO_ID
    ):
        raise MismatchError("candidate dataset is not the authorized Dataset")
    if require_repo_id(targets.get("source_bucket"), name="candidate.bucket") != (
        AUTHORIZED_BUCKET_ID
    ):
        raise MismatchError("candidate bucket is not the authorized Bucket")
    return receipt


def load_staging_receipt(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
    require_live_staging: bool = True,
) -> dict[str, Any]:
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_staging_path(repo_root)
    )
    if not target.is_file():
        raise MissingInputError(
            f"live staging receipt is required: {STAGING_RELPATH.as_posix()}"
        )
    receipt = load_json_mapping(target)
    if receipt.get("schema") != STAGING_SCHEMA:
        raise MismatchError("staging receipt schema mismatch")
    if receipt.get("task_id") != "OUL-041":
        raise MismatchError("staging receipt is not the OUL-041 upload")
    if receipt.get("publication_authorized") is not False:
        raise LiveStagingError("staging receipt must not authorize public mutation")
    if receipt.get("public_mutation_authorized") is not False:
        raise LiveStagingError("staging receipt must not authorize public mutation")
    revision = require_immutable_staging_revision(
        receipt.get("dataset_revision"), name="staging.dataset_revision"
    )
    prefix = require_bucket_prefix(
        receipt.get("bucket_staging_prefix"),
        manifest_digest=str(receipt.get("manifest_digest") or ""),
    )
    repo = require_repo_id(
        receipt.get("target_repo") or receipt.get("dataset_id"),
        name="staging.dataset_id",
    )
    if repo != AUTHORIZED_DATASET_REPO_ID:
        raise LiveStagingError(f"staging target is not the authorized Dataset: {repo}")
    bucket = require_repo_id(
        receipt.get("bucket_id") or SOURCE_BUCKET, name="staging.bucket_id"
    )
    if bucket != AUTHORIZED_BUCKET_ID:
        raise LiveStagingError(f"staging bucket is not the authorized Bucket: {bucket}")
    _verify_receipt_digest(receipt, digest_key="receipt_sha256")
    if require_live_staging:
        if not revision or not prefix:
            raise LiveStagingError(
                "--require-live-staging needs the exact 40-hex Dataset revision "
                "and content-addressed Bucket prefix from OUL-041"
            )
        if receipt.get("status") != "staged_isolated":
            raise LiveStagingError(
                "live staging requires an applied isolated upload "
                f"(status={receipt.get('status')!r})"
            )
        if receipt.get("mutation_executed") is not True:
            raise LiveStagingError(
                "live staging receipt did not execute the isolated apply"
            )
        if not receipt.get("remote_objects"):
            raise LiveStagingError(
                "live staging receipt is missing remote object identities"
            )
        if receipt.get("remote_default_branches_mutated") is True:
            raise LiveStagingError("staging must not mutate a default branch")
    return receipt


def load_canary_receipt(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
    require_live_staging: bool = True,
) -> dict[str, Any]:
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_canary_path(repo_root)
    )
    if not target.is_file():
        raise MissingInputError(
            f"staging canary receipt is required: {CANARY_RELPATH.as_posix()}"
        )
    receipt = load_json_mapping(target)
    if receipt.get("schema") != CANARY_SCHEMA:
        raise MismatchError("staging canary schema mismatch")
    if receipt.get("task_id") != "OUL-042":
        raise MismatchError("staging canary is not the OUL-042 receipt")
    if receipt.get("publication_authorized") is not False:
        raise LiveStagingError("canary receipt must not authorize public mutation")
    if receipt.get("public_mutation_authorized") is not False:
        raise LiveStagingError("canary receipt must not authorize public mutation")
    require_immutable_staging_revision(
        receipt.get("dataset_revision"), name="canary.dataset_revision"
    )
    require_bucket_prefix(
        receipt.get("bucket_staging_prefix"),
        manifest_digest=str(receipt.get("manifest_digest") or ""),
    )
    _verify_receipt_digest(receipt, digest_key="receipt_sha256")
    if require_live_staging:
        if receipt.get("require_live_staging") is not True:
            raise LiveStagingError("canary did not bind live isolated staging")
        if receipt.get("local_artifact_fallback") is True:
            raise LiveStagingError("canary used a local artifact fallback")
        if receipt.get("status") != "canaried_isolated":
            raise LiveStagingError(
                "live staging canary must be canaried_isolated "
                f"(status={receipt.get('status')!r})"
            )
        redownload = dict(receipt.get("redownload") or {})
        staged = dict(redownload.get("staged_identities") or {})
        if staged.get("bytes_verified") is not True:
            raise LiveStagingError("canary did not verify staged bytes")
    return receipt


def bind_staging_coordinates(
    *,
    candidate: Mapping[str, Any],
    staging: Mapping[str, Any],
    canary: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = normalize_sha256(
        str((candidate.get("candidate") or {}).get("manifest_digest") or ""),
        name="candidate.manifest",
    )
    if staging.get("manifest_digest") != manifest:
        raise StaleInputError("staging manifest digest drifted from the candidate")
    if canary.get("manifest_digest") != manifest:
        raise StaleInputError("canary manifest digest drifted from the candidate")
    revision = require_immutable_staging_revision(
        staging.get("dataset_revision"), name="staging.dataset_revision"
    )
    if canary.get("dataset_revision") != revision:
        raise StaleInputError("canary dataset revision drifted from staging")
    prefix = require_bucket_prefix(
        staging.get("bucket_staging_prefix"), manifest_digest=manifest
    )
    if canary.get("bucket_staging_prefix") != prefix:
        raise StaleInputError("canary bucket prefix drifted from staging")
    if (canary.get("staging") or {}).get("receipt_sha256") != staging.get(
        "receipt_sha256"
    ):
        raise StaleInputError("canary is not bound to the sealed staging receipt")
    return {
        "bucket_id": AUTHORIZED_BUCKET_ID,
        "bucket_staging_prefix": prefix,
        "canary_receipt_sha256": canary.get("receipt_sha256"),
        "canary_status": canary.get("status"),
        "dataset_id": AUTHORIZED_DATASET_REPO_ID,
        "dataset_revision": revision,
        "identities_digest": staging.get("identities_digest"),
        "isolated_transport": True,
        "live_network": False,
        "manifest_digest": manifest,
        "remote_object_count": int(staging.get("remote_object_count") or 0),
        "require_live_staging": True,
        "staging_receipt_sha256": staging.get("receipt_sha256"),
        "staging_status": staging.get("status"),
    }


# ---------------------------------------------------------------------------
# Seal construction
# ---------------------------------------------------------------------------


def build_principal() -> dict[str, Any]:
    return {
        "bucket_identity": BUCKET_PRINCIPAL_IDENTITY,
        "credentials_environment_only": True,
        "dataset_identity": DATASET_PRINCIPAL_IDENTITY,
        "identity": DATASET_PRINCIPAL_IDENTITY,
        "kind": "environment_credential",
        "secret_redacted": True,
    }


def build_write_scope() -> dict[str, Any]:
    dataset_scope = credentials_scope_for(dataset_repo_id=AUTHORIZED_DATASET_REPO_ID)
    bucket_scope = credentials_scope_for(bucket_id=AUTHORIZED_BUCKET_ID)
    return {
        "bucket": bucket_scope,
        "dataset": dataset_scope,
        "scopes": sorted({dataset_scope, bucket_scope}),
    }


def build_operation_set() -> dict[str, Any]:
    return {
        "authorized": sorted(AUTHORIZED_OPERATIONS),
        "forbidden": sorted(FORBIDDEN_OPERATIONS),
        "query": sorted(QUERY_OPERATIONS),
    }


def build_target_ids(
    *,
    candidate: Mapping[str, Any],
    staging_revision: str,
    bucket_prefix: str,
) -> dict[str, Any]:
    bound = dict(candidate.get("target_ids") or {})
    manifest = normalize_sha256(
        str((candidate.get("candidate") or {}).get("manifest_digest") or ""),
        name="target.manifest",
    )
    if bound.get("dataset_repo_id") != AUTHORIZED_DATASET_REPO_ID:
        raise MismatchError("target dataset drifted from the authorized Dataset")
    if bound.get("source_bucket") != AUTHORIZED_BUCKET_ID:
        raise MismatchError("target bucket drifted from the authorized Bucket")
    if bound.get("bucket_release_prefix") != bucket_prefix:
        raise MismatchError("target bucket prefix drifted from staging")
    if bound.get("staging_branch") in {"main", "master"}:
        raise MismatchError("staging branch must not be a production ref")
    return {
        "bucket_pointer_path": bound.get("bucket_pointer_path") or BUCKET_POINTER_PATH,
        "bucket_query_identity": bound.get("bucket_query_identity")
        or BUCKET_RELEASE_PREFIX_TEMPLATE,
        "bucket_release_prefix": bucket_prefix,
        "bucket_release_prefix_template": BUCKET_RELEASE_PREFIX_TEMPLATE,
        "dataset_query_identity": bound.get("dataset_query_identity")
        or "exact_40_hex_commit",
        "dataset_repo_id": AUTHORIZED_DATASET_REPO_ID,
        "dataset_revision": staging_revision,
        "default_configuration": bound.get("default_configuration")
        or DEFAULT_CONFIG_NAME,
        "model_id": bound.get("model_id") or PINNED_MODEL_ID,
        "model_revision": bound.get("model_revision") or PINNED_MODEL_REVISION,
        "program_id": PROGRAM_ID,
        "release_profile": bound.get("release_profile") or RELEASE_PROFILE,
        "source_bucket": AUTHORIZED_BUCKET_ID,
        "staging_branch": bound.get("staging_branch") or DEFAULT_STAGING_BRANCH,
        "vector_space_id": bound.get("vector_space_id")
        or str((candidate.get("candidate") or {}).get("vector_space_id") or ""),
        "manifest_digest": manifest,
    }


def build_expiration() -> dict[str, Any]:
    expires_at = compute_expiry()
    if _parse_utc(expires_at) <= _parse_utc(SEALED_AT):
        raise MismatchError("prepublication seal expiry is not after sealed_at")
    return {
        "expires_at": expires_at,
        "requires_reissue_after_expiry": True,
        "sealed_at": SEALED_AT,
        "ttl_seconds": PREPUBLICATION_TTL_SECONDS,
    }


def build_gate_seal(
    *,
    manifest_digest: str,
    staging_revision: str,
    bucket_prefix: str,
) -> dict[str, Any]:
    return {
        "bucket_prefix": bucket_prefix,
        "created_after_mutation": False,
        "created_before_mutation": True,
        "dataset_revision": staging_revision,
        "final_manifest_digest": manifest_digest,
        "future": False,
        "manifest_digest": manifest_digest,
        "post_hoc": False,
        "present": True,
        "required_for_staging": False,
        "seal_timing": SEAL_TIMING,
        "substitutes_for_phase_evidence": False,
        "timing": SEAL_TIMING,
    }


def as_gate_seal(seal: Mapping[str, Any]) -> dict[str, Any]:
    """Return the compact publication-gate view of a sealed document."""

    nested = dict(seal.get("gate_seal") or {})
    if nested:
        return nested
    manifest = str(
        seal.get("manifest_digest")
        or seal.get("final_manifest_digest")
        or (seal.get("candidate") or {}).get("manifest_digest")
        or ""
    )
    return build_gate_seal(
        manifest_digest=normalize_sha256(manifest, name="gate.manifest"),
        staging_revision=str(
            seal.get("staging_revision")
            or (seal.get("staging") or {}).get("dataset_revision")
            or ""
        ),
        bucket_prefix=str(
            seal.get("bucket_prefix")
            or (seal.get("staging") or {}).get("bucket_staging_prefix")
            or ""
        ),
    )


def bind_source_rights_evaluation(
    candidate: Mapping[str, Any],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    source = dict(candidate.get("source_receipts") or {})
    rights = dict(candidate.get("rights_receipts") or {})
    evaluation = dict(candidate.get("evaluation") or {})
    if source.get("path") != SOURCE_ADMISSION_RELPATH.as_posix():
        raise MismatchError("source receipts path drifted")
    if rights.get("path") != SOURCE_ADMISSION_RELPATH.as_posix():
        raise MismatchError("rights receipts path drifted")
    if evaluation.get("path") != EVALUATION_RELPATH.as_posix():
        raise MismatchError("evaluation path drifted")
    live_source = sha256_file(repo_root / SOURCE_ADMISSION_RELPATH)
    live_eval = sha256_file(repo_root / EVALUATION_RELPATH)
    if live_source != source.get("sha256"):
        raise StaleInputError("source receipt digest drifted")
    if live_source != rights.get("sha256"):
        raise StaleInputError("rights receipt digest drifted")
    if live_eval != evaluation.get("sha256"):
        raise StaleInputError("evaluation digest drifted")
    return {
        "evaluation": {
            "evaluation_cid": evaluation.get("evaluation_cid"),
            "ok": bool(evaluation.get("ok")),
            "path": EVALUATION_RELPATH.as_posix(),
            "sha256": live_eval,
            "task_id": evaluation.get("task_id") or "OUL-037",
        },
        "rights": {
            "attribution_required": bool(rights.get("attribution_required")),
            "jurisdiction_count": int(rights.get("jurisdiction_count") or 0),
            "ok": bool(rights.get("ok")),
            "path": SOURCE_ADMISSION_RELPATH.as_posix(),
            "sha256": live_source,
            "task_id": rights.get("task_id") or "OUL-002",
        },
        "source": {
            "jurisdiction_count": int(source.get("jurisdiction_count") or 0),
            "ok": bool(source.get("ok")),
            "path": SOURCE_ADMISSION_RELPATH.as_posix(),
            "sha256": live_source,
            "task_id": source.get("task_id") or "OUL-002",
        },
    }


def build_prepublication_seal(
    *,
    repo_root: Path | str | None = None,
    require_live_staging: bool = True,
) -> dict[str, Any]:
    """Build the deterministic offline prepublication authorization seal."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    candidate = load_candidate_receipt(repo_root=root)
    staging = load_staging_receipt(
        repo_root=root, require_live_staging=require_live_staging
    )
    canary = load_canary_receipt(
        repo_root=root, require_live_staging=require_live_staging
    )
    coordinates = bind_staging_coordinates(
        candidate=candidate, staging=staging, canary=canary
    )
    task_closure = build_task_closure(repo_root=root)
    goal_closure = build_goal_closure(repo_root=root)
    receipts = bind_source_rights_evaluation(candidate, repo_root=root)
    principal = build_principal()
    write_scope = build_write_scope()
    operation_set = build_operation_set()
    expiration = build_expiration()
    target_ids = build_target_ids(
        candidate=candidate,
        staging_revision=str(coordinates["dataset_revision"]),
        bucket_prefix=str(coordinates["bucket_staging_prefix"]),
    )
    clean_commit = dict(candidate.get("clean_commit") or {})
    require_immutable_revision(str(clean_commit.get("sha") or ""), name="clean_commit")
    candidate_body = dict(candidate.get("candidate") or {})
    manifest_digest = str(coordinates["manifest_digest"])
    gate_seal = build_gate_seal(
        manifest_digest=manifest_digest,
        staging_revision=str(coordinates["dataset_revision"]),
        bucket_prefix=str(coordinates["bucket_staging_prefix"]),
    )
    policy = sealed_publication_policy()
    policy_digest = digest_mapping(policy)
    policy_schema_sha = sha256_file(root / PUBLICATION_POLICY_SCHEMA_RELPATH)

    closure = {
        "complete": bool(task_closure["complete"]) and bool(goal_closure["bound"]),
        "generated_work_blocks_publication": bool(task_closure["publication_blockers"]),
        "goals": goal_closure,
        "includes_refill_work": True,
        "refill_bound": bool(task_closure["refill_bound"]),
        "refill_complete": bool(task_closure["refill_complete"]),
        "tasks": task_closure,
    }
    if not closure["complete"]:
        raise ClosureError("full task and goal closure is incomplete")
    if not closure["includes_refill_work"] or not task_closure["generated_tasks"]:
        raise ClosureError("seal must bind generated refill work")

    bound_candidate = {
        "dataset_id": candidate_body.get("dataset_id"),
        "kind": candidate_body.get("kind"),
        "manifest_digest": manifest_digest,
        "receipt_sha256": candidate.get("receipt_sha256"),
        "release_root_cid": candidate_body.get("release_root_cid"),
        "source_revision": candidate_body.get("source_revision"),
        "staging_branch": candidate_body.get("staging_branch"),
        "task_id": candidate.get("task_id"),
        "vector_space_id": candidate_body.get("vector_space_id"),
    }

    acceptance = {
        "all_expected_outputs_required": True,
        "binds_bucket_prefix": coordinates["bucket_staging_prefix"]
        == f"releases/{manifest_digest}/",
        "binds_exact_candidate": bound_candidate["receipt_sha256"]
        == candidate.get("receipt_sha256")
        and bound_candidate["manifest_digest"] == manifest_digest,
        "binds_expiration": bool(expiration["expires_at"])
        and expiration["ttl_seconds"] == PREPUBLICATION_TTL_SECONDS,
        "binds_operation_set": set(operation_set["authorized"]) == set(AUTHORIZED_OPERATIONS),
        "binds_principal_and_write_scope": principal["identity"]
        == DATASET_PRINCIPAL_IDENTITY
        and write_scope["dataset"]
        == credentials_scope_for(dataset_repo_id=AUTHORIZED_DATASET_REPO_ID)
        and write_scope["bucket"]
        == credentials_scope_for(bucket_id=AUTHORIZED_BUCKET_ID),
        "binds_staging_revision": _GIT_SHA_RE.fullmatch(
            str(coordinates["dataset_revision"])
        )
        is not None,
        "binds_target_ids": target_ids["dataset_repo_id"] == AUTHORIZED_DATASET_REPO_ID
        and target_ids["source_bucket"] == AUTHORIZED_BUCKET_ID,
        "binds_task_and_goal_closure_including_refill_work": bool(closure["complete"])
        and bool(closure["includes_refill_work"]),
        "created_before_mutation": True,
        "criteria": ACCEPTANCE_CRITERIA,
        "independently_reproducible": True,
        "no_secret_or_path_leak": True,
        "public_mutation_not_executed": True,
    }
    failed = [key for key, value in acceptance.items() if key != "criteria" and not value]
    if failed:
        raise MismatchError("prepublication-seal acceptance failed: " + ", ".join(failed))

    seal: dict[str, Any] = {
        "acceptance": acceptance,
        "adr_path": ADR_PATH,
        "authorizing_for_publication": True,
        "board_namespace": BOARD_NAMESPACE,
        "bucket_id": AUTHORIZED_BUCKET_ID,
        "bucket_prefix": coordinates["bucket_staging_prefix"],
        "bundle": BUNDLE,
        "candidate": bound_candidate,
        "clean_commit": clean_commit,
        "closure": closure,
        "code_version": CODE_VERSION,
        "created_after_mutation": False,
        "created_before_mutation": True,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "dataset_id": AUTHORIZED_DATASET_REPO_ID,
        "depends_on": list(DEPENDS_ON),
        "digests": {
            "canary": canary.get("receipt_sha256"),
            "candidate": candidate.get("receipt_sha256"),
            "clean_commit": clean_commit.get("sha"),
            "evaluation": receipts["evaluation"]["sha256"],
            "manifest": manifest_digest,
            "publication_policy": policy_digest,
            "publication_policy_schema": policy_schema_sha,
            "rights": receipts["rights"]["sha256"],
            "source": receipts["source"]["sha256"],
            "staging": staging.get("receipt_sha256"),
        },
        "evaluation": receipts["evaluation"],
        "expiration": expiration,
        "expires_at": expiration["expires_at"],
        "final_manifest_digest": manifest_digest,
        "fixture_id": FIXTURE_ID,
        "future": False,
        "gate_seal": gate_seal,
        "goal_id": GOAL_ID,
        "live_network": False,
        "manifest_digest": manifest_digest,
        "mutation_executed": False,
        "network_required": False,
        "notes": (
            "Manifest-bound prepublication authorization seal for Open US Law "
            "sparse GraphRAG (OUL-043). Created before any public Dataset or "
            "Bucket mutation. Binds the exact OUL-040 candidate, the isolated "
            "OUL-041/OUL-042 staging revision and content-addressed bucket "
            "prefix, the environment-only principal and write scope, "
            "predecessor task/goal closure including generated refill work, "
            "authorized target IDs, the additive operation set, and a "
            "short-lived expiration. This CLI does not mutate a remote target."
        ),
        "operation_set": operation_set,
        "post_hoc": False,
        "present": True,
        "principal": principal,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "public_mutation_executed": False,
        "publication_authorized": True,
        "publication_policy": policy,
        "publication_policy_digest": policy_digest,
        "required_for_staging": False,
        "require_live_staging": bool(require_live_staging),
        "rights_receipts": receipts["rights"],
        "schema": SEAL_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "sealed_at": SEALED_AT,
        "seal_timing": SEAL_TIMING,
        "source_receipts": receipts["source"],
        "staging": coordinates,
        "staging_revision": coordinates["dataset_revision"],
        "substitutes_for_phase_evidence": False,
        "target_ids": target_ids,
        "task_id": TASK_ID,
        "timing": SEAL_TIMING,
        "ttl_seconds": PREPUBLICATION_TTL_SECONDS,
        "write_scope": write_scope,
    }
    seal["seal_sha256"] = digest_mapping(
        {key: value for key, value in seal.items() if key != "seal_sha256"}
    )

    reject_credentials_in_payload(seal, label="prepublication_seal")
    reject_path_leaks(seal, label="prepublication_seal")
    reject_identity_contamination(seal, label="prepublication_seal")
    return seal


def materialize_default_seal(
    *,
    repo_root: Path | str | None = None,
    seal_path: Path | str | None = None,
    require_live_staging: bool = True,
) -> tuple[dict[str, Any], Path]:
    seal = build_prepublication_seal(
        repo_root=repo_root, require_live_staging=require_live_staging
    )
    target = (
        Path(seal_path).expanduser().resolve()
        if seal_path is not None
        else default_seal_path(repo_root)
    )
    path = write_json_report(seal, target)
    return seal, path


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _compare_mappings(
    fresh: Mapping[str, Any],
    sealed: Mapping[str, Any],
    *,
    path: str,
    keys: Sequence[str],
) -> list[str]:
    mismatches: list[str] = []
    for key in keys:
        if fresh.get(key) != sealed.get(key):
            mismatches.append(
                f"{path}.{key}: fresh={fresh.get(key)!r} sealed={sealed.get(key)!r}"
            )
    return mismatches


def compare_seals(
    fresh: Mapping[str, Any],
    sealed: Mapping[str, Any],
) -> list[str]:
    mismatches: list[str] = []
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
        "seal_sha256",
        "sealed_at",
        "timing",
        "manifest_digest",
        "staging_revision",
        "bucket_prefix",
        "expires_at",
    )
    mismatches.extend(_compare_mappings(fresh, sealed, path="seal", keys=top_keys))
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("candidate") or {}),
            dict(sealed.get("candidate") or {}),
            path="candidate",
            keys=(
                "manifest_digest",
                "receipt_sha256",
                "release_root_cid",
                "dataset_id",
                "task_id",
            ),
        )
    )
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("staging") or {}),
            dict(sealed.get("staging") or {}),
            path="staging",
            keys=(
                "dataset_revision",
                "bucket_staging_prefix",
                "manifest_digest",
                "staging_receipt_sha256",
            ),
        )
    )
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("principal") or {}),
            dict(sealed.get("principal") or {}),
            path="principal",
            keys=("identity", "kind", "dataset_identity", "bucket_identity"),
        )
    )
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("write_scope") or {}),
            dict(sealed.get("write_scope") or {}),
            path="write_scope",
            keys=("dataset", "bucket"),
        )
    )
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("target_ids") or {}),
            dict(sealed.get("target_ids") or {}),
            path="target_ids",
            keys=(
                "dataset_repo_id",
                "source_bucket",
                "dataset_revision",
                "bucket_release_prefix",
            ),
        )
    )
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("expiration") or {}),
            dict(sealed.get("expiration") or {}),
            path="expiration",
            keys=("expires_at", "ttl_seconds", "sealed_at"),
        )
    )
    if fresh.get("operation_set") != sealed.get("operation_set"):
        mismatches.append("operation_set drifted from the sealed document")
    if fresh.get("digests") != sealed.get("digests"):
        mismatches.append("digests drifted from the sealed document")
    if (fresh.get("closure") or {}).get("complete") != (
        sealed.get("closure") or {}
    ).get("complete"):
        mismatches.append("closure.complete drifted from the sealed document")
    if (fresh.get("closure") or {}).get("includes_refill_work") != (
        sealed.get("closure") or {}
    ).get("includes_refill_work"):
        mismatches.append("closure refill binding drifted from the sealed document")
    return mismatches


def check_seal_structure(seal: Mapping[str, Any]) -> None:
    required = (
        "acceptance",
        "bucket_prefix",
        "candidate",
        "clean_commit",
        "closure",
        "digests",
        "expiration",
        "gate_seal",
        "manifest_digest",
        "operation_set",
        "principal",
        "seal_sha256",
        "staging",
        "staging_revision",
        "target_ids",
        "write_scope",
    )
    missing = [key for key in required if key not in seal]
    if missing:
        raise MismatchError("seal missing required keys: " + ", ".join(missing))
    if seal.get("schema") != SEAL_SCHEMA:
        raise MismatchError("seal schema mismatch")
    if seal.get("schema_version") != SCHEMA_VERSION:
        raise MismatchError("seal schema_version mismatch")
    if seal.get("task_id") != TASK_ID or seal.get("goal_id") != GOAL_ID:
        raise MismatchError("seal task/goal identity mismatch")
    if seal.get("created_before_mutation") is not True:
        raise MismatchError("seal must be created before mutation")
    if seal.get("timing") != SEAL_TIMING or seal.get("seal_timing") != SEAL_TIMING:
        raise MismatchError("seal timing must be before_mutation")
    if seal.get("created_after_mutation") is True or seal.get("post_hoc") is True:
        raise MismatchError("seal must not be post-hoc")
    if seal.get("mutation_executed") is not False:
        raise MismatchError("prepublication seal must not execute mutation")
    if seal.get("public_mutation_executed") is not False:
        raise MismatchError("prepublication seal must not execute public mutation")
    if seal.get("publication_authorized") is not True:
        raise MismatchError("prepublication seal must authorize the bound public mutation")
    if seal.get("authorizing_for_publication") is not True:
        raise MismatchError("prepublication seal must authorize publication of bound identities")
    if seal.get("network_required") is not False:
        raise MismatchError("seal must be network-free")
    if seal.get("live_network") is not False:
        raise MismatchError("seal must not require live Hub contact")
    if not (seal.get("closure") or {}).get("complete"):
        raise ClosureError("seal does not bind a complete task and goal closure")
    if not (seal.get("closure") or {}).get("includes_refill_work"):
        raise ClosureError("seal does not bind refill work")
    refill = ((seal.get("closure") or {}).get("tasks") or {}).get("refill_work") or (
        (seal.get("closure") or {}).get("tasks") or {}
    ).get("generated_tasks")
    if not isinstance(refill, list) or not refill:
        raise ClosureError("seal refill work inventory is empty")
    commit = dict(seal.get("clean_commit") or {})
    require_immutable_revision(commit.get("sha"), name="seal.clean_commit")
    if not _GIT_SHA_RE.fullmatch(str(commit.get("sha") or "")):
        raise MismatchError("seal clean commit must be an exact 40-hex SHA")
    expiration = dict(seal.get("expiration") or {})
    if expiration.get("expires_at") != compute_expiry():
        raise MismatchError("seal expiry drifted")
    if int(expiration.get("ttl_seconds") or 0) != PREPUBLICATION_TTL_SECONDS:
        raise MismatchError("seal ttl drifted")
    if _parse_utc(str(expiration.get("expires_at"))) <= _parse_utc(SEALED_AT):
        raise MismatchError("seal is not expiry-bound")
    if seal.get("expires_at") != expiration.get("expires_at"):
        raise MismatchError("top-level expires_at drifted from expiration.expires_at")
    targets = dict(seal.get("target_ids") or {})
    if targets.get("dataset_repo_id") != AUTHORIZED_DATASET_REPO_ID:
        raise MismatchError("target dataset drifted")
    if targets.get("source_bucket") != AUTHORIZED_BUCKET_ID:
        raise MismatchError("target bucket drifted")
    manifest = normalize_sha256(str(seal.get("manifest_digest") or ""), name="seal.manifest")
    prefix = require_bucket_prefix(seal.get("bucket_prefix"), manifest_digest=manifest)
    revision = require_immutable_staging_revision(
        seal.get("staging_revision"), name="seal.staging_revision"
    )
    if targets.get("bucket_release_prefix") != prefix:
        raise MismatchError("target bucket prefix drifted from seal.bucket_prefix")
    if targets.get("dataset_revision") != revision:
        raise MismatchError("target dataset revision drifted from seal.staging_revision")
    principal = dict(seal.get("principal") or {})
    if principal.get("identity") != DATASET_PRINCIPAL_IDENTITY:
        raise MismatchError("principal identity drifted")
    if principal.get("credentials_environment_only") is not True:
        raise MismatchError("principal must be environment-only")
    write_scope = dict(seal.get("write_scope") or {})
    if write_scope.get("dataset") != credentials_scope_for(
        dataset_repo_id=AUTHORIZED_DATASET_REPO_ID
    ):
        raise MismatchError("dataset write scope drifted")
    if write_scope.get("bucket") != credentials_scope_for(bucket_id=AUTHORIZED_BUCKET_ID):
        raise MismatchError("bucket write scope drifted")
    ops = dict(seal.get("operation_set") or {})
    if set(ops.get("authorized") or ()) != set(AUTHORIZED_OPERATIONS):
        raise MismatchError("authorized operation set drifted")
    forbidden = set(ops.get("forbidden") or ())
    if not {"delete", "force_push", "history_rewrite", "visibility_change"} <= forbidden:
        raise MismatchError("forbidden operation set is incomplete")
    gate = dict(seal.get("gate_seal") or {})
    if gate.get("timing") != SEAL_TIMING or gate.get("present") is not True:
        raise MismatchError("gate_seal timing/presence is invalid")
    if gate.get("final_manifest_digest") != manifest:
        raise MismatchError("gate_seal manifest digest drifted")
    expected = digest_mapping(
        {key: value for key, value in seal.items() if key != "seal_sha256"}
    )
    if seal.get("seal_sha256") != expected:
        raise StaleInputError("seal_sha256 does not match the sealed surface")


def verify_producer_freshness(
    seal: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
    require_live_staging: bool = True,
) -> None:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    candidate = load_candidate_receipt(repo_root=root)
    staging = load_staging_receipt(
        repo_root=root, require_live_staging=require_live_staging
    )
    canary = load_canary_receipt(
        repo_root=root, require_live_staging=require_live_staging
    )
    coordinates = bind_staging_coordinates(
        candidate=candidate, staging=staging, canary=canary
    )
    if seal.get("manifest_digest") != coordinates["manifest_digest"]:
        raise StaleInputError("seal manifest digest drifted from the candidate")
    if seal.get("staging_revision") != coordinates["dataset_revision"]:
        raise StaleInputError("seal staging revision drifted from live staging")
    if seal.get("bucket_prefix") != coordinates["bucket_staging_prefix"]:
        raise StaleInputError("seal bucket prefix drifted from live staging")
    if (seal.get("candidate") or {}).get("receipt_sha256") != candidate.get(
        "receipt_sha256"
    ):
        raise StaleInputError("seal is not bound to the current candidate receipt")
    if (seal.get("staging") or {}).get("staging_receipt_sha256") != staging.get(
        "receipt_sha256"
    ):
        raise StaleInputError("seal is not bound to the current staging receipt")
    if (seal.get("staging") or {}).get("canary_receipt_sha256") != canary.get(
        "receipt_sha256"
    ):
        raise StaleInputError("seal is not bound to the current canary receipt")
    live_source = sha256_file(root / SOURCE_ADMISSION_RELPATH)
    if (seal.get("source_receipts") or {}).get("sha256") != live_source:
        raise StaleInputError("source receipt digest drifted")
    if (seal.get("rights_receipts") or {}).get("sha256") != live_source:
        raise StaleInputError("rights receipt digest drifted")
    live_eval = sha256_file(root / EVALUATION_RELPATH)
    if (seal.get("evaluation") or {}).get("sha256") != live_eval:
        raise StaleInputError("evaluation digest drifted")


def check_prepublication_seal(
    seal: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
    require_live_staging: bool = True,
) -> dict[str, Any]:
    check_seal_structure(seal)
    verify_producer_freshness(
        seal, repo_root=repo_root, require_live_staging=require_live_staging
    )
    reject_credentials_in_payload(seal, label="prepublication_seal")
    reject_path_leaks(seal, label="prepublication_seal")
    reject_identity_contamination(seal, label="prepublication_seal")
    acceptance = dict(seal.get("acceptance") or {})
    return {
        "bucket_prefix": seal.get("bucket_prefix"),
        "closure_complete": bool((seal.get("closure") or {}).get("complete")),
        "criteria": acceptance.get("criteria"),
        "dataset_repo_id": (seal.get("target_ids") or {}).get("dataset_repo_id"),
        "expires_at": seal.get("expires_at"),
        "goal_id": seal.get("goal_id"),
        "manifest_digest": seal.get("manifest_digest"),
        "mismatches": [],
        "mutation_executed": False,
        "network_required": False,
        "ok": True,
        "principal": (seal.get("principal") or {}).get("identity"),
        "publication_authorized": True,
        "refill_bound": bool((seal.get("closure") or {}).get("includes_refill_work")),
        "require_live_staging": bool(require_live_staging),
        "seal_sha256": seal.get("seal_sha256"),
        "source_bucket": (seal.get("target_ids") or {}).get("source_bucket"),
        "staging_revision": seal.get("staging_revision"),
        "task_id": seal.get("task_id"),
        "timing": seal.get("timing"),
        "write_scope": (seal.get("write_scope") or {}).get("scopes"),
    }


def check_seal_matches_fresh(
    sealed: Mapping[str, Any],
    fresh: Mapping[str, Any],
) -> None:
    mismatches = compare_seals(fresh, sealed)
    if mismatches:
        raise StaleInputError(
            "sealed document drifted from a fresh prepublication build: "
            + "; ".join(mismatches[:8])
        )


def assert_gate_accepts_seal(seal: Mapping[str, Any]) -> None:
    """The bound seal must satisfy the OUL-007 public mutation gate."""

    digest = normalize_sha256(str(seal.get("manifest_digest") or ""), name="gate.manifest")
    request = {
        "authorize_mutation": True,
        "argv": ["publish-open-us-law", "--phase", "public", "--authorize-mutation"],
        "bucket_id": AUTHORIZED_BUCKET_ID,
        "credential_identity": DATASET_PRINCIPAL_IDENTITY,
        "credentials_environment_only": True,
        "credentials_scope": credentials_scope_for(
            dataset_repo_id=AUTHORIZED_DATASET_REPO_ID
        ),
        "dataset_repo_id": AUTHORIZED_DATASET_REPO_ID,
        "delete_requested": False,
        "final_manifest_digest": digest,
        "force_push": False,
        "history_rewrite": False,
        "operation": "dataset_additive_commit",
        "overwrite_existing_prefix": False,
        "overwrite_raw_root": False,
        "payload": {
            "credentials_environment_only": True,
            "release_mode": "additive",
            "secret_redacted": True,
        },
        "phase": "public",
        "prepublication_seal": as_gate_seal(seal),
        "sealed": True,
        "secret_redacted": True,
        "visibility": "public",
        "visibility_change": False,
    }
    decision = evaluate_publication_gate(request)
    if not decision.authorized:
        raise MismatchError(
            "publication gate refused the sealed prepublication document: "
            + decision.message
        )


def render_check_summary(result: Mapping[str, Any]) -> str:
    return (
        "open_us_law_prepublication_seal: PASS "
        f"task={result.get('task_id')} "
        f"manifest={result.get('manifest_digest')} "
        f"staging={result.get('staging_revision')} "
        f"prefix={result.get('bucket_prefix')} "
        f"expiry={result.get('expires_at')} "
        f"timing={result.get('timing')} "
        f"publication_authorized={result.get('publication_authorized')} "
        f"mutation_executed={result.get('mutation_executed')}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seal_open_us_law_prepublication.py",
        description=(
            "Create the manifest-bound Open US Law prepublication "
            f"authorization seal ({TASK_ID}). Never mutates a remote target."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the frozen prepublication seal without rewriting it.",
    )
    parser.add_argument(
        "--require-live-staging",
        action="store_true",
        help=(
            "Require the OUL-041 isolated staging receipt and the OUL-042 "
            "canary, and bind the seal to their exact 40-hex Dataset revision "
            "and content-addressed Bucket prefix."
        ),
    )
    parser.add_argument(
        "--no-mutate",
        action="store_true",
        help="Forbid writing the seal report or any remote mutation.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the prepublication seal to --seal.",
    )
    parser.add_argument(
        "--seal",
        type=Path,
        default=None,
        help=f"Seal path (default: {DEFAULT_SEAL_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the seal or check summary JSON to stdout.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Request live Hub mutation (always refused).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    try:
        reject_secrets_in_argv(raw_argv)
        args = parser.parse_args(raw_argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    except SecretLeakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.live:
        print(
            "error: live Hub mutation is forbidden from the prepublication sealer",
            file=sys.stderr,
        )
        return 2
    if args.write and args.no_mutate:
        print(
            "error: --write is incompatible with --no-mutate",
            file=sys.stderr,
        )
        return 2

    check_mode = bool(args.check) or not (args.write or args.print_json)
    require_live = bool(args.require_live_staging) or check_mode
    seal_path = (
        Path(args.seal).expanduser().resolve()
        if args.seal is not None
        else default_seal_path()
    )

    try:
        if args.write and not args.no_mutate:
            fresh = build_prepublication_seal(
                repo_root=REPOSITORY_ROOT, require_live_staging=require_live
            )
            check_prepublication_seal(
                fresh, repo_root=REPOSITORY_ROOT, require_live_staging=require_live
            )
            assert_gate_accepts_seal(fresh)
            write_json_report(fresh, seal_path)
            print(f"wrote prepublication seal: {seal_path}", file=sys.stderr)
            if args.print_json:
                sys.stdout.write(
                    json.dumps(dict(fresh), indent=2, sort_keys=True) + "\n"
                )
            return 0

        fresh = build_prepublication_seal(
            repo_root=REPOSITORY_ROOT, require_live_staging=require_live
        )
        check_prepublication_seal(
            fresh, repo_root=REPOSITORY_ROOT, require_live_staging=require_live
        )
        assert_gate_accepts_seal(fresh)

        if check_mode:
            if not seal_path.is_file():
                raise MissingInputError(
                    "frozen prepublication seal not found for --check: "
                    f"{DEFAULT_SEAL_RELPATH.as_posix()}"
                )
            on_disk = load_json_mapping(seal_path)
            check_prepublication_seal(
                on_disk, repo_root=REPOSITORY_ROOT, require_live_staging=require_live
            )
            check_seal_matches_fresh(on_disk, fresh)
            assert_gate_accepts_seal(on_disk)
            result = check_prepublication_seal(
                on_disk, repo_root=REPOSITORY_ROOT, require_live_staging=require_live
            )
            print(render_check_summary(result))
            if args.print_json:
                sys.stdout.write(
                    json.dumps(dict(on_disk), indent=2, sort_keys=True) + "\n"
                )
            return 0

        if args.print_json:
            sys.stdout.write(json.dumps(fresh, indent=2, sort_keys=True) + "\n")
            return 0

        result = check_prepublication_seal(
            fresh, repo_root=REPOSITORY_ROOT, require_live_staging=require_live
        )
        print(render_check_summary(result))
        print(
            "hint: pass --require-live-staging --no-mutate --check to validate "
            "the frozen prepublication seal",
            file=sys.stderr,
        )
        return 0
    except MutationForbiddenError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (
        PrepublicationSealError,
        LiveStagingError,
        MissingInputError,
        MismatchError,
        StaleInputError,
        PathLeakError,
        SecretLeakError,
        ClosureError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
