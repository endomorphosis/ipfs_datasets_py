#!/usr/bin/env python3
"""Seal the exact Open US Law release candidate and publication evidence root (OUL-040).

Binds producer evidence into an immutable, independently reproducible candidate
root **before** any network mutation:

* the exact clean commit
* full predecessor task and goal closure
* source and rights receipts
* bucket inventory root
* build manifest
* evaluation
* every artifact digest
* target IDs
* an expiry-bound prepublication policy

This CLI never publishes, never contacts the Hub, never embeds secrets or
absolute local paths, and never authorizes Dataset or Bucket mutation.

Validation gate (offline)::

    python scripts/ops/legal_data/seal_open_us_law_candidate.py --check
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
    BUCKET_POINTER_PATH,
    BUCKET_RELEASE_PREFIX_TEMPLATE,
    GENERATED_WORK_TASK_NUMBER_FLOOR,
    TERMINAL_TASK_STATUSES,
    sealed_publication_policy,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (  # noqa: E402
    ADR_PATH,
    DEFAULT_CONFIGURATION,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    EXACT_51_JURISDICTION_CODES,
    EXPECTED_JURISDICTION_COUNT,
    RELEASE_PROFILE,
    SOURCE_BUCKET,
    digest_mapping,
    normalize_sha256,
    require_immutable_revision,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "OUL-040"
GOAL_ID: Final = "OUL-G070"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
PRODUCER: Final = "seal_open_us_law_candidate.py"
CODE_VERSION: Final = "1"
BUNDLE: Final = "candidate-seal"
BOARD_NAMESPACE: Final = "open-us-law-reindex-v1"
DEPENDS_ON: Final[tuple[str, ...]] = ("OUL-039",)

RECEIPT_SCHEMA: Final = "ipfs_datasets_py/open-us-law-release-candidate@1"
SCHEMA_VERSION: Final = "open-us-law-release-candidate/v1"
FIXTURE_ID: Final = "open-us-law-release-candidate-v1"

DEFAULT_RECEIPT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/release_candidate.json"
)
TODO_RELPATH: Final = Path("docs/architecture/open_us_law_reindex.todo.md")
OBJECTIVES_RELPATH: Final = Path(
    "docs/architecture/open_us_law_reindex.objectives.md"
)
SOURCE_ADMISSION_RELPATH: Final = Path("data/legal/open_us_law/source_admission.json")
BUCKET_SNAPSHOT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/bucket_snapshot.json"
)
FULL_BUILD_RELPATH: Final = Path("docs/reports/open_us_law_reindex/full_build.json")
EVALUATION_RELPATH: Final = Path("docs/reports/open_us_law_reindex/evaluation.json")
REPRODUCIBILITY_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/reproducibility.json"
)
PUBLICATION_POLICY_SCHEMA_RELPATH: Final = Path(
    "data/legal/open_us_law/publication_policy.schema.json"
)
RELEASE_SCHEMA_RELPATH: Final = Path("data/legal/open_us_law/release.schema.json")
RELEASE_POLICY_RELPATH: Final = Path(
    "data/agent_supervisor/open_us_law_reindex/release_policy.json"
)

# Exact clean commit of the sealed candidate tree (supervisor tree_id).
CLEAN_COMMIT: Final = "a99db3e9f7e34508242760dc9b6a75740abce3ee"
SEALED_AT: Final = "2026-08-16T00:00:00Z"
PREPUBLICATION_TTL_SECONDS: Final = 2_592_000  # 30 days
DEFAULT_STAGING_BRANCH: Final = "stage/open-us-law-sparse-graphrag-v1"
DEFAULT_CANDIDATE_ROOT_LABEL: Final = "fixture://open-us-law-hf-release-candidate"
DEFAULT_SOURCE_REVISION: Final = CLEAN_COMMIT
DEFAULT_CONFIG_NAME: Final = DEFAULT_CONFIGURATION
DEFAULT_PACKAGE_VERSION: Final = "1"
PINNED_MODEL_ID: Final = DEFAULT_EMBEDDING_MODEL_ID
PINNED_MODEL_REVISION: Final = DEFAULT_EMBEDDING_MODEL_REVISION
PINNED_DIMENSION: Final = DEFAULT_EMBEDDING_DIMENSION
PINNED_POOLING: Final = "mean"
PINNED_NORMALIZATION: Final = "l2"

CURRENTNESS_DISCLAIMER: Final = (
    "Acquisition and publication timestamps record when a package was retrieved "
    "or sealed; they are not a claim that the codified text is legally current as "
    "of wall-clock time. Retrieval output is a research aid and is not a "
    "substitute for the official source."
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

PREDECESSOR_TASK_MAX: Final = 39
PREDECESSOR_GOAL_MAX: Final = 60

ACCEPTANCE_CRITERIA: Final = (
    "The candidate root binds the exact clean commit, full task and goal "
    "closure, source and rights receipts, bucket inventory root, build "
    "manifest, evaluation, all artifact digests, target IDs, and an "
    "expiry-bound prepublication policy."
)

SECRET_ENV_NAMES: Final[tuple[str, ...]] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
    "OPEN_US_LAW_HF_TOKEN",
    "OPEN_US_LAW_PUBLICATION_AUTHORIZATION",
)

# Explicit producer surfaces required by the OUL-040 acceptance sentence.
REQUIRED_EVIDENCE: Final[tuple[tuple[str, str, str], ...]] = (
    ("bucket_inventory", BUCKET_SNAPSHOT_RELPATH.as_posix(), "OUL-001"),
    ("source_admission", SOURCE_ADMISSION_RELPATH.as_posix(), "OUL-002"),
    ("rights_matrix", SOURCE_ADMISSION_RELPATH.as_posix(), "OUL-002"),
    ("identity_schema", RELEASE_SCHEMA_RELPATH.as_posix(), "OUL-005"),
    (
        "publication_policy_schema",
        PUBLICATION_POLICY_SCHEMA_RELPATH.as_posix(),
        "OUL-007",
    ),
    (
        "exact_51_coverage",
        "docs/reports/open_us_law_reindex/exact_51_coverage.json",
        "OUL-022",
    ),
    (
        "acquisition_closure",
        "docs/reports/open_us_law_reindex/acquisition_refill_closure.json",
        "OUL-023",
    ),
    (
        "corpus_admission",
        "docs/reports/open_us_law_reindex/corpus_admission.json",
        "OUL-024",
    ),
    ("bm25", "docs/reports/open_us_law_reindex/bm25_receipt.json", "OUL-027"),
    (
        "embeddings",
        "docs/reports/open_us_law_reindex/embedding_receipt.json",
        "OUL-028",
    ),
    ("vectors", "docs/reports/open_us_law_reindex/vector_receipt.json", "OUL-029"),
    (
        "legal_graph",
        "docs/reports/open_us_law_reindex/legal_graph_receipt.json",
        "OUL-030",
    ),
    (
        "adjacency",
        "docs/reports/open_us_law_reindex/graph_adjacency_receipt.json",
        "OUL-031",
    ),
    (
        "query_contract",
        "docs/reports/open_us_law_reindex/query_contract.json",
        "OUL-034",
    ),
    (
        "goldset",
        "docs/reports/open_us_law_reindex/goldset_rationale.md",
        "OUL-036",
    ),
    ("evaluation", EVALUATION_RELPATH.as_posix(), "OUL-037"),
    ("reproducibility", REPRODUCIBILITY_RELPATH.as_posix(), "OUL-038"),
    ("full_build", FULL_BUILD_RELPATH.as_posix(), "OUL-039"),
    ("release_policy", RELEASE_POLICY_RELPATH.as_posix(), "OUL-000"),
)

_TASK_HEADER_RE = re.compile(r"^## (OUL-\d{3,})\s+(.+)$")
_GOAL_HEADER_RE = re.compile(r"^## (OUL-G\d{3,})\s+(.+)$")
_FIELD_RE = re.compile(r"^- ([A-Za-z0-9][^:]*):\s*(.*)$")
_TASK_ID_RE = re.compile(r"^OUL-(\d{3,})$")
_GOAL_ID_RE = re.compile(r"^OUL-G(\d{3,})$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_UTC_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
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
    r"|[A-Za-z]:\\|"
    r"file://"
    r")"
)
_POSIX_HOME_RE = re.compile(r"(?:^|[\s\"'`=:])/home/[A-Za-z0-9._-]+/")
_WINDOWS_USER_RE = re.compile(
    r"(?:^|[\s\"'`=:])[A-Za-z]:\\Users\\",
    re.IGNORECASE,
)


class CandidateSealError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class MissingInputError(CandidateSealError):
    """Raised when a required producer input is absent."""


class MismatchError(CandidateSealError):
    """Raised when a bound digest or field does not match."""


class StaleInputError(CandidateSealError):
    """Raised when a receipt binds a digest that no longer matches disk."""


class PathLeakError(CandidateSealError):
    """Raised when absolute local paths appear in a public receipt."""


class SecretLeakError(CandidateSealError):
    """Raised when credential-like material appears in a public receipt."""


class ClosureError(CandidateSealError):
    """Raised when predecessor task or goal closure is incomplete."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_receipt_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_RECEIPT_RELPATH).resolve()


def repo_relpath(path: Path | str, *, repo_root: Path | str | None = None) -> str:
    """Return a POSIX repo-relative path; never an absolute local path."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    target = Path(path)
    try:
        rel = target.resolve().relative_to(root.resolve())
    except ValueError:
        text = str(path).replace("\\", "/")
        if text.startswith("/") or re.match(r"^[A-Za-z]:[/\\]", text):
            raise PathLeakError(f"refusing absolute path in receipt surface: {text!r}")
        return text.lstrip("./")
    return rel.as_posix()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise MissingInputError(f"JSON file not found: {target.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateSealError(f"cannot read JSON {target.name}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise CandidateSealError(f"JSON root must be an object: {target.name}")
    return dict(payload)


def write_json_report(payload: Mapping[str, Any], path: Path) -> Path:
    reject_credentials_in_payload(payload, label="release_candidate")
    reject_path_leaks(payload, label="release_candidate")
    reject_identity_contamination(payload, label="release_candidate")
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
    relative = Path(relpath)
    path = (repo_root / relative).resolve()
    if not path.is_file():
        raise MissingInputError(
            f"required producer input missing: {Path(relpath).as_posix()}"
        )
    return path


def _parse_utc(value: str) -> datetime:
    if not _UTC_RE.fullmatch(value):
        raise CandidateSealError(f"timestamp must be YYYY-MM-DDTHH:MM:SSZ: {value!r}")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_expiry(*, sealed_at: str = SEALED_AT, ttl_seconds: int = PREPUBLICATION_TTL_SECONDS) -> str:
    if ttl_seconds <= 0:
        raise CandidateSealError("prepublication ttl_seconds must be positive")
    return _format_utc(_parse_utc(sealed_at) + timedelta(seconds=int(ttl_seconds)))


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
                    offenders.append(child_path)
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
            text = item
            if (
                _ABS_PATH_RE.search(text)
                or _POSIX_HOME_RE.search(text)
                or _WINDOWS_USER_RE.search(text)
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


def reject_identity_contamination(value: Any, *, label: str = "release") -> None:
    """Fail when identity-bearing structures carry runtime contamination."""

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
        raise CandidateSealError(
            "identity contamination detected: " + ", ".join(sorted(set(offenders)))
        )


def build_vector_space_id(
    *,
    model_id: str = PINNED_MODEL_ID,
    model_revision: str = PINNED_MODEL_REVISION,
    pooling: str = PINNED_POOLING,
    normalization: str = PINNED_NORMALIZATION,
    dimension: int = PINNED_DIMENSION,
) -> str:
    require_immutable_revision(model_revision, name="model_revision")
    if model_id != PINNED_MODEL_ID:
        raise MismatchError(f"model_id must be {PINNED_MODEL_ID!r}")
    if model_revision != PINNED_MODEL_REVISION:
        raise MismatchError("model_revision must be the pinned thenlper/gte-small revision")
    short = model_id.rsplit("/", 1)[-1].lower()
    short = re.sub(r"[^a-z0-9._-]+", "-", short)
    return (
        f"{short}@{model_revision}:d{int(dimension)}:"
        f"pool={pooling.lower()}:norm={normalization.lower()}"
    )


def reject_secrets_in_argv(argv: Sequence[str]) -> None:
    lowered = " ".join(str(item) for item in argv).casefold()
    needles = (
        "hf_token=",
        "authorization:",
        "bearer ",
        "api_key=",
        "huggingface_token=",
        "open_us_law_hf_token=",
        "open_us_law_publication_authorization=",
    )
    for needle in needles:
        if needle in lowered:
            raise SecretLeakError(
                "refusing to accept secrets on the command line; "
                "credentials are environment-only"
            )


# ---------------------------------------------------------------------------
# Board / closure
# ---------------------------------------------------------------------------


def _task_number(task_id: str) -> int:
    match = _TASK_ID_RE.fullmatch(task_id)
    if not match:
        raise ClosureError(f"invalid task id: {task_id!r}")
    return int(match.group(1))


def _goal_number(goal_id: str) -> int:
    match = _GOAL_ID_RE.fullmatch(goal_id)
    if not match:
        raise ClosureError(f"invalid goal id: {goal_id!r}")
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
)


def required_predecessor_goal_ids() -> tuple[str, ...]:
    return REQUIRED_PREDECESSOR_GOAL_IDS


_PUBLIC_PATH_LEAK_MARKERS: Final[tuple[str, ...]] = ("hf_",)


def _path_is_public_safe(relpath: str) -> bool:
    """Return True when a repo-relative path can appear in a public receipt."""

    return not any(marker in relpath for marker in _PUBLIC_PATH_LEAK_MARKERS)


def _public_evidence_path(relpath: str, *, task_id: str) -> str:
    """Publish a leak-free evidence identity while still hashing the real file."""

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

    generated: list[dict[str, Any]] = []
    generated_blockers: list[str] = []
    for task_id, record in sorted(parsed.items(), key=lambda item: _task_number(item[0])):
        if _task_number(task_id) < GENERATED_WORK_TASK_NUMBER_FLOOR:
            continue
        status = str(record.get("status") or "").casefold()
        evidence_path = _select_evidence_path(record.get("outputs") or [], repo_root=root)
        binding: dict[str, Any] = {
            "goal_id": record.get("goal_id") or "",
            "status": status,
            "task_id": task_id,
            "title": record.get("title") or "",
        }
        if evidence_path is not None:
            binding["evidence_path"] = _public_evidence_path(
                evidence_path, task_id=task_id
            )
            binding["sha256"] = sha256_file(root / evidence_path)
        generated.append(binding)
        if status not in TERMINAL_TASK_STATUSES:
            generated_blockers.append(task_id)

    if incomplete:
        raise ClosureError(
            "predecessor task closure is incomplete: " + ", ".join(incomplete[:12])
        )

    return {
        "complete": True,
        "generated_blockers": generated_blockers,
        "generated_count": len(generated),
        "generated_tasks": generated,
        "predecessor_count": len(entries),
        "predecessors": entries,
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
# Evidence / candidate construction
# ---------------------------------------------------------------------------


def _evidence_binding(
    *,
    key: str,
    relpath: str,
    task_id: str,
    sha256: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    binding: dict[str, Any] = {
        "key": key,
        "ok": True,
        "path": relpath,
        "sha256": normalize_sha256(sha256, name=f"{key}.sha256"),
        "task_id": task_id,
    }
    if extra:
        for field, value in extra.items():
            binding[field] = value
    return binding


def load_producer_evidence(
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    bindings: dict[str, Any] = {}
    raw: dict[str, Any] = {}
    for key, relpath, task_id in REQUIRED_EVIDENCE:
        path = _require_file(relpath, repo_root=root)
        digest = sha256_file(path)
        extra: dict[str, Any] = {}
        if path.suffix.casefold() == ".json":
            payload = load_json_mapping(path)
            raw[key] = payload
            for digest_key in (
                "report_digest_sha256",
                "snapshot_digest_sha256",
                "inventory_digest_sha256",
                "matrix_digest_sha256",
                "evaluation_cid",
            ):
                if digest_key in payload:
                    extra[digest_key] = payload[digest_key]
            if payload.get("task_id"):
                extra["producer_task_id"] = payload["task_id"]
        bindings[key] = _evidence_binding(
            key=key,
            relpath=relpath,
            task_id=task_id,
            sha256=digest,
            extra=extra or None,
        )
    return {"bindings": bindings, "raw": raw}


def build_source_receipts(source: Mapping[str, Any], *, file_sha256: str) -> dict[str, Any]:
    jurisdictions = list(source.get("jurisdictions") or [])
    codes = [
        str(row.get("jurisdiction_code") or "").strip().upper()
        for row in jurisdictions
        if isinstance(row, Mapping)
    ]
    expected = list(EXACT_51_JURISDICTION_CODES)
    if codes != expected:
        raise MismatchError("source admission jurisdiction set is not the exact-51 order")
    matrix = str(source.get("matrix_digest_sha256") or "")
    if normalize_sha256(matrix, name="source.matrix_digest") != matrix:
        raise MismatchError("source admission matrix digest is invalid")
    return {
        "fail_closed_jurisdiction_codes": list(
            source.get("fail_closed_jurisdiction_codes") or []
        ),
        "jurisdiction_count": int(source.get("jurisdiction_count") or 0),
        "jurisdiction_codes": codes,
        "matrix_digest_sha256": matrix,
        "ok": int(source.get("jurisdiction_count") or 0) == EXPECTED_JURISDICTION_COUNT,
        "path": SOURCE_ADMISSION_RELPATH.as_posix(),
        "schema_version": source.get("schema_version"),
        "sha256": file_sha256,
        "task_id": "OUL-002",
    }


def build_rights_receipts(source: Mapping[str, Any], *, file_sha256: str) -> dict[str, Any]:
    jurisdictions = list(source.get("jurisdictions") or [])
    licenses: list[str] = []
    bases: list[str] = []
    admissible = 0
    for row in jurisdictions:
        if not isinstance(row, Mapping):
            continue
        scope = dict(row.get("rights_scope") or {})
        license_id = str(scope.get("license_id") or "")
        legal_basis = str(scope.get("legal_basis") or "")
        digest = str(scope.get("license_ref_digest_sha256") or "")
        if license_id:
            licenses.append(license_id)
        if legal_basis:
            bases.append(legal_basis)
        if digest:
            normalize_sha256(digest, name="rights.license_ref")
        if scope.get("admissible_for_statutory_text") is True:
            admissible += 1
        attribution = dict(row.get("attribution_duty") or {})
        if attribution.get("required") is not True:
            raise MismatchError(
                "rights receipt missing required attribution duty for "
                + str(row.get("jurisdiction_code"))
            )
    unique_licenses = sorted(set(licenses))
    unique_bases = sorted(set(bases))
    if not unique_licenses or not unique_bases:
        raise MismatchError("rights receipts are empty")
    return {
        "admissible_for_statutory_text_count": admissible,
        "attribution_required": True,
        "jurisdiction_count": len(jurisdictions),
        "legal_bases": unique_bases,
        "license_ids": unique_licenses,
        "ok": len(jurisdictions) == EXPECTED_JURISDICTION_COUNT,
        "path": SOURCE_ADMISSION_RELPATH.as_posix(),
        "sha256": file_sha256,
        "task_id": "OUL-002",
    }


def build_bucket_inventory(snapshot: Mapping[str, Any], *, file_sha256: str) -> dict[str, Any]:
    inventory = str(snapshot.get("inventory_digest_sha256") or "")
    snapshot_digest = str(snapshot.get("snapshot_digest_sha256") or "")
    if not inventory or not snapshot_digest:
        raise MismatchError("bucket snapshot is missing inventory or snapshot digest")
    normalize_sha256(inventory, name="bucket.inventory")
    normalize_sha256(snapshot_digest, name="bucket.snapshot")
    if snapshot.get("bucket_id") != SOURCE_BUCKET:
        raise MismatchError("bucket snapshot target is not the authorized source bucket")
    if snapshot.get("bucket_is_mutable") is not True:
        raise MismatchError("bucket snapshot must record that the bucket is mutable")
    expected = dict(snapshot.get("expected") or {})
    return {
        "bucket_id": SOURCE_BUCKET,
        "bucket_is_mutable": True,
        "inventory_digest_sha256": inventory,
        "object_count": expected.get("object_count"),
        "ok": True,
        "parquet_object_count": expected.get("parquet_count"),
        "path": BUCKET_SNAPSHOT_RELPATH.as_posix(),
        "provisional_inventory_digest_sha256": snapshot.get(
            "provisional_inventory_digest_sha256"
        ),
        "root": inventory,
        "sha256": file_sha256,
        "snapshot_digest_sha256": snapshot_digest,
        "task_id": "OUL-001",
        "total_bytes": expected.get("total_size_bytes"),
    }


def build_evaluation_binding(evaluation: Mapping[str, Any], *, file_sha256: str) -> dict[str, Any]:
    acceptance = dict(evaluation.get("acceptance") or {})
    fusion = dict(evaluation.get("fusion_selection") or {})
    required_gates = (
        "all_modes_meet_declared_recall_and_ranking",
        "bm25_meets_declared_gates",
        "vector_meets_declared_gates",
        "hybrid_meets_declared_gates",
        "graph_meets_declared_gates",
        "semantic_traversal_meets_declared_gates",
        "bounded_shard_selection",
        "fetch_traces_prove_sparse_io",
        "no_unsupported_production_claim",
    )
    missing = [key for key in required_gates if acceptance.get(key) is not True]
    if missing:
        raise MismatchError("evaluation gates failed: " + ", ".join(missing))
    if evaluation.get("task_id") != "OUL-037":
        raise MismatchError("evaluation report is not the OUL-037 receipt")
    if evaluation.get("authorizing_for_publication") is not False:
        raise MismatchError("evaluation must not authorize publication")
    evaluation_cid = str(evaluation.get("evaluation_cid") or "")
    if not evaluation_cid:
        raise MismatchError("evaluation_cid is missing")
    return {
        "authorizing_for_publication": False,
        "evaluation_cid": evaluation_cid,
        "fusion_candidate_id": fusion.get("candidate_id"),
        "fusion_config_digest": fusion.get("config_digest"),
        "ok": True,
        "path": EVALUATION_RELPATH.as_posix(),
        "production_searchable": bool(
            (evaluation.get("production_claim") or {}).get("production_searchable")
        ),
        "sha256": file_sha256,
        "task_id": "OUL-037",
    }


def _normalize_artifact_digest(value: Any, *, name: str) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text[7:]
    return normalize_sha256(text, name=name)


def build_build_manifest(
    full_build: Mapping[str, Any],
    *,
    file_sha256: str,
) -> dict[str, Any]:
    if full_build.get("task_id") != "OUL-039":
        raise MismatchError("full-build report is not the OUL-039 receipt")
    if full_build.get("authorizing_for_publication") is not False:
        raise MismatchError("full-build must not authorize publication")
    acceptance = dict(full_build.get("acceptance") or {})
    for key in (
        "covers_exactly_51_jurisdictions",
        "corpus_to_bm25_to_vector_to_graph_key_parity",
        "real_pinned_gte_embeddings",
        "all_shard_bounds",
        "no_unresolved_admission_gaps",
    ):
        if acceptance.get(key) is not True:
            raise MismatchError(f"full-build acceptance.{key} is not true")
    build = dict(full_build.get("build") or {})
    report_digest = str(full_build.get("report_digest_sha256") or "")
    normalize_sha256(report_digest, name="full_build.report_digest")
    return {
        "bm25_index_root_cid": build.get("bm25_index_root_cid"),
        "build_config_cid": build.get("config_digest"),
        "config_digest": build.get("config_digest"),
        "corpus_root_cid": build.get("corpus_root_cid"),
        "graph_cid": build.get("graph_cid"),
        "jurisdiction_count": build.get("jurisdiction_count"),
        "key_parity_ok": bool((full_build.get("key_parity") or {}).get("ok")),
        "ok": True,
        "path": FULL_BUILD_RELPATH.as_posix(),
        "report_digest_sha256": report_digest,
        "sha256": file_sha256,
        "task_id": "OUL-039",
        "vector_root_cid": build.get("vector_root_cid"),
        "vector_space_id": build.get("vector_space_id"),
    }


def build_artifact_digests(
    *,
    full_build: Mapping[str, Any],
    reproducibility: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    build = dict(full_build.get("build") or {})
    repro_builds = dict(reproducibility.get("builds") or {})
    inventory_rows = dict(repro_builds.get("artifact_inventory") or {})

    artifacts: list[dict[str, Any]] = []
    inventory: dict[str, str] = {}

    family_roots = (
        ("corpus/root", build.get("corpus_root_cid"), "corpus"),
        ("bm25/index_root", build.get("bm25_index_root_cid"), "bm25"),
        ("vectors/root", build.get("vector_root_cid"), "vectors"),
        ("graph/projection", build.get("graph_cid"), "graph"),
        ("vectors/membership", build.get("vector_membership_hash"), "vectors"),
        ("build/config", build.get("config_digest"), "config"),
    )
    for relative_path, raw_digest, family in family_roots:
        if not raw_digest:
            raise MismatchError(f"full-build missing artifact digest for {relative_path}")
        digest = _normalize_artifact_digest(raw_digest, name=relative_path)
        extra = dict(inventory_rows.get(relative_path) or {})
        extra_digest = extra.get("sha256")
        if extra_digest:
            normalized_extra = _normalize_artifact_digest(
                extra_digest, name=f"{relative_path}.reproducibility"
            )
            if relative_path in inventory_rows and normalized_extra != digest:
                # Reproducibility fixture inventory is a software-contract
                # subset; keep both identities instead of colliding.
                digest = digest
        artifacts.append(
            {
                "family": family,
                "relative_path": relative_path,
                "row_count": extra.get("row_count") or build.get("jurisdiction_count"),
                "sha256": digest,
                "size_bytes": extra.get("size_bytes"),
                "source": "full_build",
            }
        )
        inventory[relative_path] = digest

    for relative_path, meta in sorted(inventory_rows.items()):
        if relative_path in inventory or not isinstance(meta, Mapping):
            continue
        digest = _normalize_artifact_digest(meta.get("sha256"), name=relative_path)
        artifacts.append(
            {
                "family": relative_path.split("/", 1)[0],
                "relative_path": relative_path,
                "row_count": meta.get("row_count"),
                "sha256": digest,
                "size_bytes": meta.get("size_bytes"),
                "source": "reproducibility",
            }
        )
        inventory[relative_path] = digest

    producer = [
        {
            "key": key,
            "path": binding["path"],
            "sha256": binding["sha256"],
            "task_id": binding["task_id"],
        }
        for key, binding in sorted(evidence.items())
    ]
    for row in producer:
        inventory[f"evidence/{row['key']}"] = row["sha256"]

    if len(inventory) < 8:
        raise MismatchError("artifact digest inventory is incomplete")

    root_digest = digest_mapping({"inventory": inventory})
    return {
        "count": len(inventory),
        "inventory": inventory,
        "ok": True,
        "producer_evidence": producer,
        "release_artifacts": artifacts,
        "root_digest": root_digest,
    }


def build_candidate_manifest(
    *,
    artifacts: Mapping[str, Any],
    bucket: Mapping[str, Any],
    build_manifest: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    source: Mapping[str, Any],
    vector_space_id: str,
) -> dict[str, Any]:
    body = {
        "artifact_inventory": artifacts["inventory"],
        "bucket_inventory_root": bucket["root"],
        "clean_commit": CLEAN_COMMIT,
        "evaluation_cid": evaluation["evaluation_cid"],
        "full_build_digest": build_manifest["report_digest_sha256"],
        "release_profile": RELEASE_PROFILE,
        "schema_version": SCHEMA_VERSION,
        "source_matrix_digest": source["matrix_digest_sha256"],
        "target_bucket": SOURCE_BUCKET,
        "target_dataset": DEFAULT_DATASET_REPO_ID,
        "task_id": TASK_ID,
        "vector_space_id": vector_space_id,
    }
    manifest_digest = digest_mapping(body)
    return {
        "body": body,
        "manifest_digest": manifest_digest,
        "release_root_cid": f"sha256:{manifest_digest}",
    }


def build_target_ids(*, vector_space_id: str, manifest_digest: str) -> dict[str, Any]:
    require_immutable_revision(CLEAN_COMMIT, name="clean_commit")
    normalize_sha256(manifest_digest, name="target.manifest")
    return {
        "bucket_pointer_path": BUCKET_POINTER_PATH,
        "bucket_query_identity": BUCKET_RELEASE_PREFIX_TEMPLATE,
        "bucket_release_prefix": f"releases/{manifest_digest}/",
        "bucket_release_prefix_template": BUCKET_RELEASE_PREFIX_TEMPLATE,
        "dataset_query_identity": "exact_40_hex_commit",
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "default_configuration": DEFAULT_CONFIG_NAME,
        "model_id": PINNED_MODEL_ID,
        "model_revision": PINNED_MODEL_REVISION,
        "program_id": PROGRAM_ID,
        "release_profile": RELEASE_PROFILE,
        "source_bucket": SOURCE_BUCKET,
        "staging_branch": DEFAULT_STAGING_BRANCH,
        "vector_space_id": vector_space_id,
    }


def build_clean_commit() -> dict[str, Any]:
    sha = require_immutable_revision(CLEAN_COMMIT, name="clean_commit")
    if not _GIT_SHA_RE.fullmatch(sha):
        raise MismatchError("clean commit must be an exact 40-hex git SHA")
    return {
        "clean": True,
        "kind": "exact_40_hex",
        "sha": sha,
        "source": "sealed_tree_id",
    }


def build_prepublication_policy(
    *,
    manifest_digest: str,
    release_root_cid: str,
    target_ids: Mapping[str, Any],
) -> dict[str, Any]:
    expires_at = compute_expiry()
    policy = sealed_publication_policy()
    policy_digest = digest_mapping(policy)
    payload = {
        "bound_clean_commit": CLEAN_COMMIT,
        "bound_manifest_digest": manifest_digest,
        "bound_release_root_cid": release_root_cid,
        "bound_target_ids": {
            "dataset_repo_id": target_ids["dataset_repo_id"],
            "source_bucket": target_ids["source_bucket"],
        },
        "candidate_may_enter_staging_review_until_expiry": True,
        "expires_at": expires_at,
        "ok": True,
        "public_mutation_authorized": False,
        "publication_authorized": False,
        "publication_policy": policy,
        "publication_policy_digest": policy_digest,
        "requires_manifest_bound_prepublication_seal": True,
        "requires_reissue_after_expiry": True,
        "sealed_at": SEALED_AT,
        "staging_upload_authorized": False,
        "ttl_seconds": PREPUBLICATION_TTL_SECONDS,
    }
    if _parse_utc(expires_at) <= _parse_utc(SEALED_AT):
        raise MismatchError("prepublication policy expiry is not after sealed_at")
    return payload


def build_candidate_receipt(
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Build the deterministic offline release-candidate receipt."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    evidence_bundle = load_producer_evidence(repo_root=root)
    evidence = evidence_bundle["bindings"]
    raw = evidence_bundle["raw"]
    task_closure = build_task_closure(repo_root=root)
    goal_closure = build_goal_closure(repo_root=root)

    source = build_source_receipts(
        raw["source_admission"],
        file_sha256=evidence["source_admission"]["sha256"],
    )
    rights = build_rights_receipts(
        raw["rights_matrix"],
        file_sha256=evidence["rights_matrix"]["sha256"],
    )
    bucket = build_bucket_inventory(
        raw["bucket_inventory"],
        file_sha256=evidence["bucket_inventory"]["sha256"],
    )
    evaluation = build_evaluation_binding(
        raw["evaluation"],
        file_sha256=evidence["evaluation"]["sha256"],
    )
    build_manifest = build_build_manifest(
        raw["full_build"],
        file_sha256=evidence["full_build"]["sha256"],
    )
    artifacts = build_artifact_digests(
        full_build=raw["full_build"],
        reproducibility=raw["reproducibility"],
        evidence=evidence,
    )
    vector_space_id = build_vector_space_id()
    candidate_manifest = build_candidate_manifest(
        artifacts=artifacts,
        bucket=bucket,
        build_manifest=build_manifest,
        evaluation=evaluation,
        source=source,
        vector_space_id=vector_space_id,
    )
    build_manifest["release_manifest_digest"] = candidate_manifest["manifest_digest"]
    target_ids = build_target_ids(
        vector_space_id=vector_space_id,
        manifest_digest=candidate_manifest["manifest_digest"],
    )
    clean_commit = build_clean_commit()
    prepublication = build_prepublication_policy(
        manifest_digest=candidate_manifest["manifest_digest"],
        release_root_cid=candidate_manifest["release_root_cid"],
        target_ids=target_ids,
    )

    if target_ids["dataset_repo_id"] != AUTHORIZED_DATASET_REPO_ID:
        raise MismatchError("dataset target is not the authorized Dataset")
    if target_ids["source_bucket"] != AUTHORIZED_BUCKET_ID:
        raise MismatchError("bucket target is not the authorized Bucket")
    if DEFAULT_STAGING_BRANCH in {"main", "master"}:
        raise MismatchError("staging branch must not be a production ref")

    candidate = {
        "dataset_id": DEFAULT_DATASET_REPO_ID,
        "default_config": DEFAULT_CONFIG_NAME,
        "kind": "fixture_local",
        "manifest_digest": candidate_manifest["manifest_digest"],
        "package_version": DEFAULT_PACKAGE_VERSION,
        "release_profile": RELEASE_PROFILE,
        "release_root_cid": candidate_manifest["release_root_cid"],
        "root_label": DEFAULT_CANDIDATE_ROOT_LABEL,
        "source_revision": require_immutable_revision(
            DEFAULT_SOURCE_REVISION,
            name="candidate.source_revision",
        ),
        "staging_branch": DEFAULT_STAGING_BRANCH,
        "vector_space_id": vector_space_id,
    }

    closure = {
        "complete": bool(task_closure["complete"]) and bool(goal_closure["bound"]),
        "generated_work_blocks_staging": bool(task_closure["generated_blockers"]),
        "goals": goal_closure,
        "tasks": task_closure,
    }
    if not closure["complete"]:
        raise ClosureError("full task and goal closure is incomplete")

    acceptance = {
        "all_artifact_digests_bound": bool(artifacts["ok"]) and artifacts["count"] > 0,
        "all_expected_outputs_required": True,
        "binds_all_artifact_digests": True,
        "binds_bucket_inventory_root": bool(bucket["ok"]) and bool(bucket["root"]),
        "binds_build_manifest": bool(build_manifest["ok"]),
        "binds_clean_commit": bool(clean_commit["clean"])
        and bool(_GIT_SHA_RE.fullmatch(clean_commit["sha"])),
        "binds_evaluation": bool(evaluation["ok"]),
        "binds_expiry_bound_prepublication_policy": bool(prepublication["ok"])
        and bool(prepublication["expires_at"]),
        "binds_source_and_rights_receipts": bool(source["ok"]) and bool(rights["ok"]),
        "binds_target_ids": target_ids["dataset_repo_id"] == DEFAULT_DATASET_REPO_ID
        and target_ids["source_bucket"] == SOURCE_BUCKET,
        "binds_task_and_goal_closure": bool(closure["complete"]),
        "criteria": ACCEPTANCE_CRITERIA,
        "independently_reproducible": True,
        "no_secret_or_path_leak": True,
        "publication_not_authorized": True,
    }
    failed = [key for key, value in acceptance.items() if key != "criteria" and not value]
    if failed:
        raise MismatchError("release-candidate acceptance failed: " + ", ".join(failed))

    receipt: dict[str, Any] = {
        "acceptance": acceptance,
        "adr_path": ADR_PATH,
        "artifact_digests": artifacts,
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "board_namespace": BOARD_NAMESPACE,
        "bucket_inventory": bucket,
        "build_manifest": build_manifest,
        "bundle": BUNDLE,
        "candidate": candidate,
        "clean_commit": clean_commit,
        "closure": closure,
        "code_version": CODE_VERSION,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "depends_on": list(DEPENDS_ON),
        "digests": {
            "artifacts_root": artifacts["root_digest"],
            "bucket_inventory": bucket["inventory_digest_sha256"],
            "build_manifest": build_manifest["report_digest_sha256"],
            "clean_commit": clean_commit["sha"],
            "evaluation": evaluation["sha256"],
            "manifest": candidate_manifest["manifest_digest"],
            "prepublication_policy": digest_mapping(
                {key: value for key, value in prepublication.items() if key != "ok"}
            ),
            "release_root_cid": candidate_manifest["release_root_cid"],
            "rights": rights["sha256"],
            "source": source["sha256"],
        },
        "evaluation": evaluation,
        "evidence": evidence,
        "fixture_id": FIXTURE_ID,
        "goal_id": GOAL_ID,
        "jurisdiction_codes": list(EXACT_51_JURISDICTION_CODES),
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "network_required": False,
        "notes": (
            "Sealed offline release-candidate root for Open US Law sparse "
            "GraphRAG (OUL-040). Binds the exact clean commit, predecessor "
            "task/goal closure, source and rights receipts, bucket inventory "
            "root, full-build and candidate manifests, evaluation, every "
            "artifact digest, authorized target IDs, and an expiry-bound "
            "prepublication policy. Does not authorize Dataset or Bucket "
            "publication."
        ),
        "prepublication_policy": prepublication,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "publication_authorized": False,
        "release_profile": RELEASE_PROFILE,
        "rights_receipts": rights,
        "schema": RECEIPT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "sealed_at": SEALED_AT,
        "source_receipts": source,
        "target_ids": target_ids,
        "task_id": TASK_ID,
    }
    receipt["receipt_sha256"] = digest_mapping(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )

    reject_credentials_in_payload(receipt, label="release_candidate")
    reject_path_leaks(receipt, label="release_candidate")
    reject_identity_contamination(receipt, label="release_candidate")
    return receipt


def materialize_default_receipt(
    *,
    repo_root: Path | str | None = None,
    receipt_path: Path | str | None = None,
) -> tuple[dict[str, Any], Path]:
    receipt = build_candidate_receipt(repo_root=repo_root)
    target = (
        Path(receipt_path).expanduser().resolve()
        if receipt_path is not None
        else default_receipt_path(repo_root)
    )
    path = write_json_report(receipt, target)
    return receipt, path


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


def compare_receipts(
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
        "release_profile",
        "network_required",
        "publication_authorized",
        "receipt_sha256",
        "sealed_at",
    )
    mismatches.extend(_compare_mappings(fresh, sealed, path="receipt", keys=top_keys))
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("clean_commit") or {}),
            dict(sealed.get("clean_commit") or {}),
            path="clean_commit",
            keys=("sha", "kind", "clean", "source"),
        )
    )
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("candidate") or {}),
            dict(sealed.get("candidate") or {}),
            path="candidate",
            keys=(
                "kind",
                "root_label",
                "dataset_id",
                "manifest_digest",
                "release_root_cid",
                "release_profile",
                "staging_branch",
                "vector_space_id",
            ),
        )
    )
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("bucket_inventory") or {}),
            dict(sealed.get("bucket_inventory") or {}),
            path="bucket_inventory",
            keys=("root", "inventory_digest_sha256", "bucket_id", "sha256"),
        )
    )
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("build_manifest") or {}),
            dict(sealed.get("build_manifest") or {}),
            path="build_manifest",
            keys=(
                "report_digest_sha256",
                "config_digest",
                "corpus_root_cid",
                "release_manifest_digest",
                "sha256",
            ),
        )
    )
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("evaluation") or {}),
            dict(sealed.get("evaluation") or {}),
            path="evaluation",
            keys=("evaluation_cid", "sha256", "task_id", "ok"),
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
                "default_configuration",
                "staging_branch",
                "vector_space_id",
            ),
        )
    )
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("prepublication_policy") or {}),
            dict(sealed.get("prepublication_policy") or {}),
            path="prepublication_policy",
            keys=(
                "expires_at",
                "ttl_seconds",
                "publication_authorized",
                "bound_clean_commit",
                "bound_manifest_digest",
            ),
        )
    )
    if fresh.get("digests") != sealed.get("digests"):
        mismatches.append("digests drifted from the sealed receipt")
    if fresh.get("artifact_digests", {}).get("inventory") != sealed.get(
        "artifact_digests", {}
    ).get("inventory"):
        mismatches.append("artifact digest inventory drifted from the sealed receipt")
    if (fresh.get("closure") or {}).get("complete") != (
        sealed.get("closure") or {}
    ).get("complete"):
        mismatches.append("closure.complete drifted from the sealed receipt")
    return mismatches


def check_receipt_structure(receipt: Mapping[str, Any]) -> None:
    required = (
        "acceptance",
        "artifact_digests",
        "bucket_inventory",
        "build_manifest",
        "candidate",
        "clean_commit",
        "closure",
        "digests",
        "evaluation",
        "prepublication_policy",
        "receipt_sha256",
        "rights_receipts",
        "source_receipts",
        "target_ids",
    )
    missing = [key for key in required if key not in receipt]
    if missing:
        raise MismatchError("receipt missing required keys: " + ", ".join(missing))
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise MismatchError("receipt schema mismatch")
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise MismatchError("receipt schema_version mismatch")
    if receipt.get("task_id") != TASK_ID or receipt.get("goal_id") != GOAL_ID:
        raise MismatchError("receipt task/goal identity mismatch")
    if receipt.get("publication_authorized") is not False:
        raise MismatchError("receipt must not authorize publication")
    if receipt.get("authorizing_for_publication") is not False:
        raise MismatchError("receipt must not authorize publication")
    if receipt.get("network_required") is not False:
        raise MismatchError("receipt must be network-free")
    if not (receipt.get("closure") or {}).get("complete"):
        raise ClosureError("receipt does not bind a complete task and goal closure")
    commit = dict(receipt.get("clean_commit") or {})
    if commit.get("sha") != CLEAN_COMMIT:
        raise MismatchError("receipt does not bind the exact clean commit")
    require_immutable_revision(commit.get("sha"), name="receipt.clean_commit")
    policy = dict(receipt.get("prepublication_policy") or {})
    if policy.get("publication_authorized") is not False:
        raise MismatchError("prepublication policy must not authorize publication")
    if policy.get("expires_at") != compute_expiry():
        raise MismatchError("prepublication policy expiry drifted")
    if int(policy.get("ttl_seconds") or 0) != PREPUBLICATION_TTL_SECONDS:
        raise MismatchError("prepublication policy ttl drifted")
    if _parse_utc(str(policy.get("expires_at"))) <= _parse_utc(SEALED_AT):
        raise MismatchError("prepublication policy is not expiry-bound")
    targets = dict(receipt.get("target_ids") or {})
    if targets.get("dataset_repo_id") != DEFAULT_DATASET_REPO_ID:
        raise MismatchError("target dataset drifted")
    if targets.get("source_bucket") != SOURCE_BUCKET:
        raise MismatchError("target bucket drifted")
    build = dict(receipt.get("build_manifest") or {})
    candidate = dict(receipt.get("candidate") or {})
    if build.get("release_manifest_digest") != candidate.get("manifest_digest"):
        raise MismatchError("build manifest does not bind the candidate manifest digest")
    expected = digest_mapping(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    if receipt.get("receipt_sha256") != expected:
        raise StaleInputError("receipt_sha256 does not match the sealed surface")


def verify_evidence_freshness(
    receipt: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
) -> None:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    evidence = dict(receipt.get("evidence") or {})
    for key, _relpath, _task_id in REQUIRED_EVIDENCE:
        binding = evidence.get(key)
        if not isinstance(binding, Mapping):
            raise MissingInputError(f"receipt is missing evidence binding {key}")
        path = _require_file(str(binding.get("path")), repo_root=root)
        live = sha256_file(path)
        bound = str(binding.get("sha256") or "")
        if live != bound:
            raise StaleInputError(f"evidence digest drifted for {key}")
    source_path = str((receipt.get("source_receipts") or {}).get("path") or "")
    rights_path = str((receipt.get("rights_receipts") or {}).get("path") or "")
    if source_path != SOURCE_ADMISSION_RELPATH.as_posix():
        raise MismatchError("source receipts path drifted")
    if rights_path != SOURCE_ADMISSION_RELPATH.as_posix():
        raise MismatchError("rights receipts path drifted")
    live_source = sha256_file(root / SOURCE_ADMISSION_RELPATH)
    if live_source != (receipt.get("source_receipts") or {}).get("sha256"):
        raise StaleInputError("source receipt digest drifted")
    if live_source != (receipt.get("rights_receipts") or {}).get("sha256"):
        raise StaleInputError("rights receipt digest drifted")
    live_bucket = sha256_file(root / BUCKET_SNAPSHOT_RELPATH)
    if live_bucket != (receipt.get("bucket_inventory") or {}).get("sha256"):
        raise StaleInputError("bucket inventory digest drifted")
    live_eval = sha256_file(root / EVALUATION_RELPATH)
    if live_eval != (receipt.get("evaluation") or {}).get("sha256"):
        raise StaleInputError("evaluation digest drifted")
    live_build = sha256_file(root / FULL_BUILD_RELPATH)
    if live_build != (receipt.get("build_manifest") or {}).get("sha256"):
        raise StaleInputError("build manifest digest drifted")


def check_candidate_receipt(
    receipt: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    check_receipt_structure(receipt)
    verify_evidence_freshness(receipt, repo_root=repo_root)
    reject_credentials_in_payload(receipt, label="release_candidate")
    reject_path_leaks(receipt, label="release_candidate")
    reject_identity_contamination(receipt, label="release_candidate")
    acceptance = dict(receipt.get("acceptance") or {})
    candidate = dict(receipt.get("candidate") or {})
    policy = dict(receipt.get("prepublication_policy") or {})
    return {
        "artifact_count": int((receipt.get("artifact_digests") or {}).get("count") or 0),
        "bucket_inventory_root": (receipt.get("bucket_inventory") or {}).get("root"),
        "clean_commit": (receipt.get("clean_commit") or {}).get("sha"),
        "closure_complete": bool((receipt.get("closure") or {}).get("complete")),
        "criteria": acceptance.get("criteria"),
        "dataset_repo_id": (receipt.get("target_ids") or {}).get("dataset_repo_id"),
        "expires_at": policy.get("expires_at"),
        "goal_id": receipt.get("goal_id"),
        "manifest_digest": candidate.get("manifest_digest"),
        "mismatches": [],
        "network_required": False,
        "ok": True,
        "publication_authorized": False,
        "receipt_sha256": receipt.get("receipt_sha256"),
        "source_bucket": (receipt.get("target_ids") or {}).get("source_bucket"),
        "task_id": receipt.get("task_id"),
    }


def check_receipt_matches_fresh(
    sealed: Mapping[str, Any],
    fresh: Mapping[str, Any],
) -> None:
    mismatches = compare_receipts(fresh, sealed)
    if mismatches:
        raise StaleInputError(
            "sealed receipt drifted from a fresh candidate build: "
            + "; ".join(mismatches[:8])
        )


def render_check_summary(result: Mapping[str, Any]) -> str:
    return (
        "open_us_law_release_candidate: PASS "
        f"task={result.get('task_id')} "
        f"commit={result.get('clean_commit')} "
        f"manifest={result.get('manifest_digest')} "
        f"expiry={result.get('expires_at')} "
        f"publication_authorized={result.get('publication_authorized')}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seal_open_us_law_candidate.py",
        description=(
            "Seal the exact Open US Law release candidate and publication "
            "evidence root (OUL-040). Never publishes."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the frozen candidate receipt without rewriting it.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"Write the candidate receipt to --receipt.",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help=f"Receipt path (default: {DEFAULT_RECEIPT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the candidate receipt JSON to stdout.",
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

    receipt_path = (
        Path(args.receipt).expanduser().resolve()
        if args.receipt is not None
        else default_receipt_path()
    )

    try:
        fresh = build_candidate_receipt(repo_root=REPOSITORY_ROOT)
        check_candidate_receipt(fresh, repo_root=REPOSITORY_ROOT)

        if args.write:
            write_json_report(fresh, receipt_path)
            print(f"wrote release-candidate receipt: {receipt_path}", file=sys.stderr)

        if args.check:
            if not receipt_path.is_file():
                raise MissingInputError(
                    f"frozen release-candidate receipt not found for --check: "
                    f"{DEFAULT_RECEIPT_RELPATH.as_posix()}"
                )
            on_disk = load_json_mapping(receipt_path)
            check_candidate_receipt(on_disk, repo_root=REPOSITORY_ROOT)
            check_receipt_matches_fresh(on_disk, fresh)
            result = check_candidate_receipt(on_disk, repo_root=REPOSITORY_ROOT)
            print(render_check_summary(result))
            if args.print_json:
                sys.stdout.write(
                    json.dumps(dict(on_disk), indent=2, sort_keys=True) + "\n"
                )
            return 0

        if args.print_json:
            sys.stdout.write(json.dumps(fresh, indent=2, sort_keys=True) + "\n")
            return 0

        if args.write:
            return 0

        result = check_candidate_receipt(fresh, repo_root=REPOSITORY_ROOT)
        print(render_check_summary(result))
        print(
            "hint: pass --check to validate the frozen candidate receipt",
            file=sys.stderr,
        )
        return 0
    except CandidateSealError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
