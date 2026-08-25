#!/usr/bin/env python3
"""Rehearse rollback, quarterly updates, and refill closure (OUL-047).

Offline, credential-free, no-mutate rehearsal of post-publication operations
against the sealed OUL-044 public pin:

1. Rollback repoints ``LATEST.json`` / the recommended Dataset revision
   without deleting any immutable Dataset commit or Bucket prefix.
2. Quarterly delta builds admit new official observations, preserve
   unchanged statute identities, rebuild only affected indexes, and mint
   a new manifest digest, Dataset commit, and Bucket prefix.
3. Interrupted add-only uploads resume by skipping already-present
   content-addressed objects; the pointer stays on the prior pin until
   the new prefix is complete and redownload-verified.
4. Every OUL-023 refill finding is terminal (completed repair or typed
   quarantine) and both the prior and new public pins remain queryable.

This CLI never:

* contacts the Hub;
* deletes, force-pushes, or overwrites a raw bucket-root object;
* updates the pointer before the new prefix is complete;
* embeds or logs Hub tokens.

Validation gate (no network)::

    python scripts/ops/legal_data/rehearse_open_us_law_operations.py --no-mutate --check
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.open_us_law_corpus import (  # noqa: E402
    CURRENTNESS_DISCLAIMER,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (  # noqa: E402
    ADR_PATH,
    DEFAULT_CONFIGURATION,
    DEFAULT_DATASET_REPO_ID,
    REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS,
    REQUIRED_SERIALIZED_IDENTITY_FIELDS,
    SOURCE_BUCKET,
    digest_mapping,
    normalize_sha256,
    reject_positional_durable_identity,
    require_immutable_revision,
    validate_entry_cid,
    validate_source_cid,
    validate_text_hash,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_sparse_graphrag import (  # noqa: E402
    QUERY_MODES,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "OUL-047"
GOAL_ID: Final = "OUL-G090"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
PRODUCER: Final = "rehearse_open_us_law_operations.py"
CODE_VERSION: Final = "1"
BUNDLE: Final = "operations"
BOARD_NAMESPACE: Final = "open-us-law-reindex-v1"
DEPENDS_ON: Final[tuple[str, ...]] = ("OUL-045", "OUL-046")

RECEIPT_SCHEMA: Final = "ipfs_datasets_py/open-us-law-operations-rehearsal@1"
SCHEMA_VERSION: Final = "open-us-law-operations-rehearsal/v1"
FIXTURE_ID: Final = "open-us-law-operations-rehearsal-v1"
POINTER_SCHEMA: Final = "ipfs_datasets_py/open-us-law-release-pointer@1"
PUBLICATION_SCHEMA: Final = "ipfs_datasets_py/open-us-law-publication-receipt@1"
REFILL_SCHEMA_VERSION: Final = "open-us-law-acquisition-refill-closure-v1"

DEFAULT_RECEIPT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/operations_rehearsal.json"
)
PUBLICATION_RECEIPT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/publication_receipt.json"
)
PUBLIC_CANARY_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/public_canary.json"
)
PUBLIC_BENCHMARK_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/public_benchmark.json"
)
REFILL_CLOSURE_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/acquisition_refill_closure.json"
)
COVERAGE_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/exact_51_coverage.json"
)

DEFAULT_DATASET_REPO: Final = DEFAULT_DATASET_REPO_ID
DEFAULT_BUCKET_ID: Final = SOURCE_BUCKET
BUCKET_POINTER_PATH: Final = "LATEST.json"
BUCKET_RELEASE_PREFIX_TEMPLATE: Final = "releases/<manifest_sha256>/"
QUARTERLY_WINDOW: Final = "2026-Q3"
AFFECTED_JURISDICTIONS: Final[tuple[str, ...]] = ("CA",)
UNCHANGED_JURISDICTIONS: Final[tuple[str, ...]] = ("AL", "DC")
REBUILT_INDEX_FAMILIES: Final[tuple[str, ...]] = ("bm25", "vectors", "graph")
REUSED_INDEX_FAMILIES: Final[tuple[str, ...]] = ("corpus",)
INTERRUPT_AFTER: Final = 3
MAX_POINTER_BYTES: Final = 2048

AUTHORIZATION_ENV: Final = "OPEN_US_LAW_PUBLICATION_AUTHORIZATION"
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

ACCEPTANCE_CRITERIA: Final = (
    "Rollback repoints without deleting immutable releases; quarterly "
    "delta builds preserve identities and rebuild affected indexes; "
    "interrupted uploads resume safely; all refill findings are "
    "completed and prior public pins remain queryable."
)

ACCEPTANCE_FLAGS: Final[tuple[str, ...]] = (
    "rollback_repoints_without_deleting_immutable_releases",
    "quarterly_delta_preserves_identities",
    "quarterly_delta_rebuilds_affected_indexes",
    "interrupted_uploads_resume_safely",
    "all_refill_findings_completed",
    "prior_public_pins_remain_queryable",
    "no_deletion",
    "no_secret_or_path_leak",
    "all_expected_outputs_required",
    "pointer_updated_last",
    "no_root_raw_object_overwritten",
    "mutation_not_executed",
)

TERMINAL_REFILL_DISPOSITIONS: Final[frozenset[str]] = frozenset(
    {"completed_repair", "typed_terminal_quarantine"}
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
        "overwrite_raw_root",
        "overwrite_prior_prefix",
        "pointer_before_prefix_complete",
        "direct_main_upload",
    }
)

QUARTERLY_RELATIVE_PATHS: Final[tuple[str, ...]] = (
    "manifest.json",
    "corpus/root",
    "bm25/index_root",
    "vectors/index_root",
    "graph/adjacency",
    "evidence/embeddings",
    "evidence/exact_51_coverage",
    "evidence/delta_admission",
)

AFFECTED_RELATIVE_PATHS: Final[frozenset[str]] = frozenset(
    {
        "bm25/index_root",
        "vectors/index_root",
        "graph/adjacency",
        "evidence/embeddings",
        "evidence/delta_admission",
    }
)

PRODUCTION_REFS: Final[frozenset[str]] = frozenset(
    {
        "main",
        "master",
        "refs/heads/main",
        "refs/heads/master",
        "production",
        "prod",
        "live",
        "latest",
        "head",
        "default",
        "current",
        "staging",
        "canary",
    }
)

_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key|operator_key|"
    r"staging_authorization|publication_authorization)s?$",
    re.IGNORECASE,
)
_ALLOWED_POLICY_TOKEN_KEYS: Final = frozenset(
    {
        "credentials_environment_only",
        "secret_redaction_required",
        "secret_redacted",
        "authorization_status",
        "mutation_requires_authorization",
        "publication_authorization_required",
        "publication_authorized",
        "public_mutation_authorized",
        "require_public_pin",
        "credentials_scope",
        "credential_identity",
        "authorization_receipt_id",
    }
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
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DATASET_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
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


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OperationsRehearsalError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class OperationsSafetyError(OperationsRehearsalError):
    """Raised when a rehearsal would delete, overwrite, or leak secrets."""


class OperationsAuthorizationError(OperationsRehearsalError):
    """Raised when a live mutation is requested."""


class MissingInputError(OperationsRehearsalError):
    """Raised when a required producer input is absent."""


class MismatchError(OperationsRehearsalError):
    """Raised when bound digests or policy fields do not match."""


class StaleInputError(OperationsRehearsalError):
    """Raised when a sealed receipt drifted from a fresh rebuild."""


class PathLeakError(OperationsRehearsalError):
    """Raised when absolute local paths appear in a public receipt."""


class SecretLeakError(OperationsRehearsalError):
    """Raised when credential-like material appears in a public receipt."""


class RefillClosureError(OperationsRehearsalError):
    """Raised when a refill finding is nonterminal."""


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
            raise PathLeakError(f"refusing absolute path in report surface: {text!r}")
        return text.lstrip("./")
    return rel.as_posix()


def _require_repo_file(relpath: Path, *, repo_root: Path) -> Path:
    path = (repo_root / relpath).resolve()
    if not path.is_file():
        raise MissingInputError(
            f"required producer input missing: {relpath.as_posix()}"
        )
    return path


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise MissingInputError(f"JSON file not found: {target.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OperationsRehearsalError(
            f"cannot read JSON {target.name}: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise OperationsRehearsalError(f"JSON root must be an object: {target.name}")
    return dict(payload)


def write_json_report(payload: Mapping[str, Any], path: Path) -> Path:
    reject_credentials_in_payload(payload, label="operations_rehearsal")
    reject_path_leaks(payload, label="operations_rehearsal")
    reject_identity_contamination(payload, label="operations_rehearsal")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
    return path


def write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="cli_output")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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
                if (
                    _TOKEN_KEY_RE.search(key_text)
                    and key_text.casefold() not in _ALLOWED_POLICY_TOKEN_KEYS
                    and not isinstance(child, bool)
                ):
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
        raise PathLeakError(
            f"absolute local path leak in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )


def reject_identity_contamination(value: Any, *, label: str = "operations") -> None:
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
        raise OperationsRehearsalError(
            "identity contamination detected: " + ", ".join(sorted(set(offenders)))
        )


def reject_secrets_in_argv(argv: Sequence[str]) -> None:
    lowered = " ".join(str(item) for item in argv).casefold()
    needles = (
        "hf_token=",
        "authorization:",
        "bearer ",
        "api_key=",
        "huggingface_token=",
        "open_us_law_publication_authorization=",
        "open_us_law_staging_authorization=",
    )
    for needle in needles:
        if needle in lowered:
            raise SecretLeakError(
                "refusing to accept secrets on the command line; "
                "credentials are environment-only"
            )
    joined = " ".join(str(item) for item in argv)
    for env_name in SECRET_ENV_NAMES:
        env_val = os.environ.get(env_name)
        if env_val and env_val in joined:
            raise SecretLeakError(
                f"refusing to accept ${env_name} value on the command line"
            )


def refuse_live_mutation() -> None:
    raise OperationsAuthorizationError(
        "this CLI is no-mutate only; live Hub publication is owned by OUL-044"
    )


# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------


def content_cid_for(digest: str) -> str:
    return f"sha256:{normalize_sha256(digest, name='content_cid')}"


def dataset_object_id(*, repo_id: str, revision: str, path: str, sha256: str) -> str:
    return f"dataset:{repo_id}@{revision}:{path}#{sha256}"


def bucket_object_id(*, bucket_id: str, path: str, sha256: str) -> str:
    return f"bucket:{bucket_id}:{path}#{sha256}"


def require_dataset_id(value: Any, *, name: str = "dataset_id") -> str:
    text = str(value or "").strip()
    if not _DATASET_ID_RE.fullmatch(text):
        raise MismatchError(f"{name} is not an authorized Dataset id: {text!r}")
    if text != DEFAULT_DATASET_REPO:
        raise MismatchError(f"{name} must be {DEFAULT_DATASET_REPO!r}")
    return text


def require_bucket_id(value: Any, *, name: str = "bucket_id") -> str:
    text = str(value or "").strip()
    if text != DEFAULT_BUCKET_ID:
        raise MismatchError(f"{name} must be {DEFAULT_BUCKET_ID!r}")
    return text


def require_bucket_content_root(value: Any, *, manifest_digest: str) -> str:
    digest = normalize_sha256(manifest_digest, name="manifest_digest")
    expected = f"releases/{digest}/"
    text = str(value or "")
    if text != expected:
        raise MismatchError(
            f"bucket content root must be {expected!r}; got {text!r}"
        )
    return text


def require_immutable_public_revision(value: Any, *, name: str = "revision") -> str:
    revision = require_immutable_revision(value, name=name)
    if revision.casefold() in PRODUCTION_REFS:
        raise MismatchError(f"{name} is a production ref: {revision!r}")
    if not _GIT_SHA_RE.fullmatch(revision):
        raise MismatchError(f"{name} must be a 40-hex Dataset commit: {revision!r}")
    return revision


def _hex_digest(label: str, *parts: str) -> str:
    return digest_mapping({"kind": label, "parts": list(parts), "task_id": TASK_ID})


# ---------------------------------------------------------------------------
# Isolated additive operations store
# ---------------------------------------------------------------------------


class IsolatedOperationsStore:
    """In-process Dataset + Bucket store for no-mutate operations rehearsal.

    Additive only. Prior release prefixes and raw-root objects are immutable.
    ``LATEST.json`` may change only after the active prefix is complete.
    Deletion is impossible.
    """

    def __init__(self) -> None:
        self.dataset: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.bucket: dict[tuple[str, str], dict[str, Any]] = {}
        self.raw_root: dict[str, str] = {}
        self.protected_prefixes: set[str] = set()
        self.pointer: dict[str, Any] | None = None
        self.pointer_updated = False
        self.pointer_updated_last = False
        self.deletion_occurred = False
        self.operation_sequence: list[str] = []
        self.active_prefix: str | None = None
        self.prefix_complete = False
        self.prefix_redownload_verified = False

    def refuse_delete(self, target: str = "object") -> None:
        self.deletion_occurred = False
        raise OperationsSafetyError(
            f"deletion of {target} is forbidden; immutable releases are retained"
        )

    def seed_raw_root(self, objects: Mapping[str, str] | None = None) -> None:
        snapshot = {str(key): str(value) for key, value in dict(objects or {}).items()}
        if not snapshot:
            snapshot = {f"raw-root-{index:03d}": "seeded" for index in range(107)}
            snapshot["README.md"] = "seeded"
            snapshot["SHA256SUMS.json"] = "seeded"
        self.raw_root = snapshot

    def seed_dataset(
        self,
        *,
        repo_id: str,
        revision: str,
        path: str,
        sha256: str,
        size_bytes: int | None = None,
    ) -> dict[str, Any]:
        repo = require_dataset_id(repo_id)
        rev = require_immutable_public_revision(revision, name="seed.revision")
        digest = normalize_sha256(sha256, name="seed.sha256")
        record = {
            "content_cid": content_cid_for(digest),
            "object_id": dataset_object_id(
                repo_id=repo, revision=rev, path=path, sha256=digest
            ),
            "operation": "seed_prior_dataset",
            "path": path,
            "repo_id": repo,
            "revision": rev,
            "sha256": digest,
            "size_bytes": size_bytes,
        }
        self.dataset[(repo, rev, path)] = record
        return dict(record)

    def seed_bucket(
        self,
        *,
        bucket_id: str,
        path: str,
        sha256: str,
        size_bytes: int | None = None,
    ) -> dict[str, Any]:
        bucket = require_bucket_id(bucket_id)
        posix = path.strip().lstrip("/")
        digest = normalize_sha256(sha256, name="seed.sha256")
        if posix == BUCKET_POINTER_PATH:
            raise OperationsSafetyError(
                "pointer seeding must go through seed_pointer()"
            )
        record = {
            "bucket_id": bucket,
            "content_cid": content_cid_for(digest),
            "object_id": bucket_object_id(bucket_id=bucket, path=posix, sha256=digest),
            "operation": "seed_prior_bucket",
            "path": posix,
            "sha256": digest,
            "size_bytes": size_bytes,
        }
        self.bucket[(bucket, posix)] = record
        if posix.startswith("releases/") and posix.count("/") >= 1:
            prefix = posix.split("/", 2)
            if len(prefix) >= 2:
                self.protected_prefixes.add(f"releases/{prefix[1]}/")
        return dict(record)

    def seed_pointer(self, pointer: Mapping[str, Any]) -> dict[str, Any]:
        document = dict(pointer)
        revision = require_immutable_public_revision(
            document.get("dataset_revision"), name="pointer.dataset_revision"
        )
        digest = normalize_sha256(
            document.get("manifest_sha256") or document.get("manifest_digest"),
            name="pointer.manifest_sha256",
        )
        prefix = require_bucket_content_root(
            document.get("bucket_prefix") or f"releases/{digest}/",
            manifest_digest=digest,
        )
        document["dataset_revision"] = revision
        document["manifest_sha256"] = digest
        document["bucket_prefix"] = prefix
        document["dataset_repo_id"] = require_dataset_id(
            document.get("dataset_repo_id") or DEFAULT_DATASET_REPO
        )
        document["source_bucket"] = require_bucket_id(
            document.get("source_bucket") or DEFAULT_BUCKET_ID
        )
        document["kind"] = "open-us-law-release-pointer"
        document["schema"] = POINTER_SCHEMA
        self.pointer = document
        self.protected_prefixes.add(prefix)
        return dict(document)

    def begin_prefix(self, *, prefix: str) -> None:
        if prefix in self.protected_prefixes:
            raise OperationsSafetyError(
                f"refusing to mutate protected prior prefix {prefix!r}"
            )
        if not prefix.startswith("releases/") or not prefix.endswith("/"):
            raise OperationsSafetyError(f"invalid release prefix {prefix!r}")
        self.active_prefix = prefix
        self.prefix_complete = False
        self.prefix_redownload_verified = False
        self.pointer_updated = False
        self.pointer_updated_last = False

    def add_dataset(
        self,
        *,
        repo_id: str,
        revision: str,
        path: str,
        sha256: str,
        size_bytes: int | None = None,
    ) -> dict[str, Any]:
        if self.pointer_updated:
            raise OperationsSafetyError(
                "dataset write after pointer update is forbidden; pointer is last"
            )
        repo = require_dataset_id(repo_id)
        rev = require_immutable_public_revision(revision, name="dataset_revision")
        digest = normalize_sha256(sha256, name="sha256")
        key = (repo, rev, path)
        record = {
            "content_cid": content_cid_for(digest),
            "object_id": dataset_object_id(
                repo_id=repo, revision=rev, path=path, sha256=digest
            ),
            "operation": "dataset_additive_commit",
            "path": path,
            "repo_id": repo,
            "revision": rev,
            "sha256": digest,
            "size_bytes": size_bytes,
        }
        existing = self.dataset.get(key)
        if existing is not None:
            if existing["sha256"] != digest:
                raise OperationsSafetyError(
                    f"additive dataset upload refused: {path} already exists "
                    "with different bytes"
                )
            record["already_present"] = True
            record["skipped"] = True
            return record
        self.dataset[key] = record
        self.operation_sequence.append("dataset_additive_commit")
        return {**record, "already_present": False, "skipped": False}

    def add_bucket(
        self,
        *,
        bucket_id: str,
        path: str,
        sha256: str,
        size_bytes: int | None = None,
    ) -> dict[str, Any]:
        if self.pointer_updated:
            raise OperationsSafetyError(
                "bucket write after pointer update is forbidden; pointer is last"
            )
        bucket = require_bucket_id(bucket_id)
        posix = path.strip().lstrip("/")
        if posix == BUCKET_POINTER_PATH:
            raise OperationsSafetyError(
                "pointer updates must go through update_pointer(), not add_bucket()"
            )
        if posix in self.raw_root:
            raise OperationsSafetyError(
                f"refusing to mutate raw bucket-root object {posix!r}"
            )
        if not posix.startswith("releases/"):
            raise OperationsSafetyError(
                f"bucket writes must stay under {BUCKET_RELEASE_PREFIX_TEMPLATE}"
            )
        for prefix in self.protected_prefixes:
            if posix.startswith(prefix):
                raise OperationsSafetyError(
                    f"refusing to mutate protected prior prefix {prefix!r}"
                )
        if self.active_prefix and not posix.startswith(self.active_prefix):
            raise OperationsSafetyError(
                f"bucket write {posix!r} is outside active prefix "
                f"{self.active_prefix!r}"
            )
        digest = normalize_sha256(sha256, name="sha256")
        key = (bucket, posix)
        record = {
            "bucket_id": bucket,
            "content_cid": content_cid_for(digest),
            "object_id": bucket_object_id(
                bucket_id=bucket, path=posix, sha256=digest
            ),
            "operation": "bucket_release_prefix_write",
            "path": posix,
            "sha256": digest,
            "size_bytes": size_bytes,
        }
        existing = self.bucket.get(key)
        if existing is not None:
            if existing["sha256"] != digest:
                raise OperationsSafetyError(
                    f"additive bucket upload refused: {posix} already exists "
                    "with different bytes"
                )
            record["already_present"] = True
            record["skipped"] = True
            return record
        self.bucket[key] = record
        self.operation_sequence.append("bucket_release_prefix_write")
        return {**record, "already_present": False, "skipped": False}

    def upload_objects(
        self,
        artifacts: Sequence[Mapping[str, Any]],
        *,
        interrupt_after: int | None = None,
    ) -> dict[str, Any]:
        uploaded: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        remaining: list[dict[str, Any]] = []
        interrupted = False
        for index, artifact in enumerate(artifacts):
            if interrupt_after is not None and index >= interrupt_after:
                remaining = [dict(item) for item in artifacts[index:]]
                interrupted = True
                break
            dataset_row = self.add_dataset(
                repo_id=str(artifact["repo_id"]),
                revision=str(artifact["revision"]),
                path=str(artifact["relative_path"]),
                sha256=str(artifact["sha256"]),
                size_bytes=int(artifact.get("size_bytes") or 0),
            )
            bucket_row = self.add_bucket(
                bucket_id=str(artifact["bucket_id"]),
                path=str(artifact["bucket_path"]),
                sha256=str(artifact["sha256"]),
                size_bytes=int(artifact.get("size_bytes") or 0),
            )
            row = {
                "already_present": bool(
                    dataset_row.get("skipped") or bucket_row.get("skipped")
                ),
                "bucket_path": bucket_row["path"],
                "relative_path": dataset_row["path"],
                "sha256": dataset_row["sha256"],
                "skipped": bool(
                    dataset_row.get("skipped") and bucket_row.get("skipped")
                ),
            }
            if row["skipped"]:
                skipped.append(row)
            else:
                uploaded.append(row)
        return {
            "interrupted": interrupted,
            "remaining": remaining,
            "skipped": skipped,
            "uploaded": uploaded,
            "pointer_still_prior": self.pointer_updated is False,
        }

    def mark_prefix_complete(self, *, expected_paths: Sequence[str]) -> None:
        present = {path for (_bucket, path) in self.bucket}
        missing = [path for path in expected_paths if path not in present]
        if missing:
            raise OperationsSafetyError(
                "release prefix is incomplete; missing " + ", ".join(missing[:8])
            )
        self.prefix_complete = True

    def redownload_verify_prefix(
        self, *, expected: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        if not self.prefix_complete:
            raise OperationsSafetyError(
                "prefix redownload is refused until the prefix is complete"
            )
        verified: list[dict[str, Any]] = []
        for item in expected:
            path = str(item["bucket_path"])
            digest = normalize_sha256(item["sha256"], name="redownload.sha256")
            record = self.bucket.get((DEFAULT_BUCKET_ID, path))
            if record is None or record["sha256"] != digest:
                raise OperationsSafetyError(
                    f"prefix redownload mismatch for {path}"
                )
            verified.append(
                {
                    "path": path,
                    "sha256": digest,
                    "verified": True,
                }
            )
        self.prefix_redownload_verified = True
        return {
            "ok": True,
            "verified_count": len(verified),
            "verified": True,
        }

    def update_pointer(self, pointer: Mapping[str, Any]) -> dict[str, Any]:
        if not self.prefix_complete or not self.prefix_redownload_verified:
            raise OperationsSafetyError(
                "pointer update refused until the prefix is complete and "
                "redownload-verified"
            )
        document = self.seed_pointer(pointer)
        encoded = json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        if len(encoded.encode("utf-8")) > MAX_POINTER_BYTES:
            raise OperationsSafetyError("pointer document is not tiny")
        digest = digest_mapping(document)
        record = {
            "bucket_id": DEFAULT_BUCKET_ID,
            "content_cid": content_cid_for(digest),
            "object_id": bucket_object_id(
                bucket_id=DEFAULT_BUCKET_ID,
                path=BUCKET_POINTER_PATH,
                sha256=digest,
            ),
            "operation": "bucket_pointer_update_last",
            "path": BUCKET_POINTER_PATH,
            "sha256": digest,
            "size_bytes": len(encoded.encode("utf-8")),
        }
        self.bucket[(DEFAULT_BUCKET_ID, BUCKET_POINTER_PATH)] = record
        self.operation_sequence.append("bucket_pointer_update_last")
        self.pointer_updated = True
        self.pointer_updated_last = True
        return {
            "document": document,
            "object": record,
            "pointer_updated_last": True,
            "size_bytes": record["size_bytes"],
        }

    def rollback_pointer(self, prior_pointer: Mapping[str, Any]) -> dict[str, Any]:
        """Repoint LATEST.json at a prior immutable pin. Never delete."""

        # Rollback is a pointer-only mutation. Prefix completeness is not
        # required because no new prefix is being advertised.
        document = dict(prior_pointer)
        revision = require_immutable_public_revision(
            document.get("dataset_revision"), name="rollback.dataset_revision"
        )
        digest = normalize_sha256(
            document.get("manifest_sha256") or document.get("manifest_digest"),
            name="rollback.manifest_sha256",
        )
        prefix = require_bucket_content_root(
            document.get("bucket_prefix") or f"releases/{digest}/",
            manifest_digest=digest,
        )
        if prefix not in self.protected_prefixes and not any(
            path.startswith(prefix) for (_bucket, path) in self.bucket
        ):
            raise OperationsSafetyError(
                "rollback target prefix is not present; refusing to invent a pin"
            )
        document["dataset_revision"] = revision
        document["manifest_sha256"] = digest
        document["bucket_prefix"] = prefix
        document["dataset_repo_id"] = require_dataset_id(
            document.get("dataset_repo_id") or DEFAULT_DATASET_REPO
        )
        document["source_bucket"] = require_bucket_id(
            document.get("source_bucket") or DEFAULT_BUCKET_ID
        )
        document["kind"] = "open-us-law-release-pointer"
        document["schema"] = POINTER_SCHEMA
        encoded = json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        pointer_digest = digest_mapping(document)
        record = {
            "bucket_id": DEFAULT_BUCKET_ID,
            "content_cid": content_cid_for(pointer_digest),
            "object_id": bucket_object_id(
                bucket_id=DEFAULT_BUCKET_ID,
                path=BUCKET_POINTER_PATH,
                sha256=pointer_digest,
            ),
            "operation": "bucket_pointer_update_last",
            "path": BUCKET_POINTER_PATH,
            "sha256": pointer_digest,
            "size_bytes": len(encoded.encode("utf-8")),
        }
        previous = dict(self.pointer or {})
        self.pointer = document
        self.bucket[(DEFAULT_BUCKET_ID, BUCKET_POINTER_PATH)] = record
        self.operation_sequence.append("bucket_pointer_update_last")
        return {
            "deleted_prefixes": [],
            "deleted_revisions": [],
            "deletion_performed": False,
            "document": document,
            "object": record,
            "pointer_updated_last": True,
            "previous_pointer": previous,
            "retained_prefixes": sorted(self.protected_prefixes | {prefix}),
        }

    def prefix_exists(self, prefix: str) -> bool:
        return any(path.startswith(prefix) for (_bucket, path) in self.bucket)

    def revision_exists(self, revision: str) -> bool:
        return any(key[1] == revision for key in self.dataset)

    def query_pin(
        self,
        *,
        dataset_revision: str,
        bucket_prefix: str,
        manifest_digest: str,
    ) -> dict[str, Any]:
        revision = require_immutable_public_revision(
            dataset_revision, name="query.dataset_revision"
        )
        prefix = require_bucket_content_root(
            bucket_prefix, manifest_digest=manifest_digest
        )
        if not self.revision_exists(revision):
            raise MismatchError(f"dataset revision {revision} is not queryable")
        if not self.prefix_exists(prefix):
            raise MismatchError(f"bucket prefix {prefix} is not queryable")
        queries = [
            {
                "id": f"{mode.replace('-', '_')}_pin",
                "mode": mode,
                "pin": {
                    "bucket_prefix": prefix,
                    "dataset_revision": revision,
                    "manifest_digest": normalize_sha256(
                        manifest_digest, name="query.manifest_digest"
                    ),
                },
                "queryable": True,
                "sparse_io": True,
                "used_mutable_pointer": False,
            }
            for mode in QUERY_MODES
        ]
        return {
            "bucket_prefix": prefix,
            "dataset_revision": revision,
            "manifest_digest": normalize_sha256(
                manifest_digest, name="query.manifest_digest"
            ),
            "modes": list(QUERY_MODES),
            "ok": True,
            "queries": queries,
            "queryable": True,
            "used_mutable_pointer": False,
        }


# ---------------------------------------------------------------------------
# Producer inputs
# ---------------------------------------------------------------------------


def load_publication_receipt(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else _require_repo_file(PUBLICATION_RECEIPT_RELPATH, repo_root=root)
    )
    receipt = load_json_mapping(target)
    if receipt.get("schema") not in {PUBLICATION_SCHEMA, None} and not str(
        receipt.get("schema") or ""
    ).startswith("ipfs_datasets_py/open-us-law-publication"):
        # Accept the sealed OUL-044 receipt even when schema is implicit.
        if receipt.get("task_id") != "OUL-044":
            raise MismatchError("publication receipt is not the OUL-044 pin")
    if receipt.get("task_id") != "OUL-044":
        raise MismatchError(
            f"publication receipt task_id must be OUL-044, got "
            f"{receipt.get('task_id')!r}"
        )
    require_immutable_public_revision(
        receipt.get("dataset_revision"), name="publication.dataset_revision"
    )
    require_bucket_content_root(
        receipt.get("bucket_release_prefix"),
        manifest_digest=str(receipt.get("manifest_digest")),
    )
    if receipt.get("deletion_occurred") is not False:
        raise MismatchError("publication receipt reports a deletion")
    if receipt.get("pointer_updated_last") is not True:
        raise MismatchError("publication receipt did not update the pointer last")
    return receipt


def load_public_canary(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else _require_repo_file(PUBLIC_CANARY_RELPATH, repo_root=root)
    )
    receipt = load_json_mapping(target)
    if receipt.get("task_id") != "OUL-045":
        raise MismatchError(
            f"public canary task_id must be OUL-045, got {receipt.get('task_id')!r}"
        )
    if receipt.get("require_public_pin") is not True:
        raise MismatchError("public canary is not bound to the public pin")
    return receipt


def load_refill_closure(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else _require_repo_file(REFILL_CLOSURE_RELPATH, repo_root=root)
    )
    receipt = load_json_mapping(target)
    if receipt.get("task_id") != "OUL-023":
        raise MismatchError(
            f"refill closure task_id must be OUL-023, got {receipt.get('task_id')!r}"
        )
    if receipt.get("schema_version") != REFILL_SCHEMA_VERSION:
        raise MismatchError("refill closure schema_version drifted")
    return receipt


def seed_store_from_publication(
    store: IsolatedOperationsStore,
    publication: Mapping[str, Any],
) -> dict[str, Any]:
    store.seed_raw_root()
    objects = list(publication.get("remote_objects") or [])
    if not objects:
        raise MissingInputError("publication receipt has no remote_objects")
    for row in objects:
        if not isinstance(row, Mapping):
            continue
        dataset = dict(row.get("dataset_object") or {})
        bucket = dict(row.get("bucket_object") or {})
        if dataset:
            store.seed_dataset(
                repo_id=str(dataset.get("repo_id") or publication.get("dataset_id")),
                revision=str(
                    dataset.get("revision") or publication.get("dataset_revision")
                ),
                path=str(dataset.get("path")),
                sha256=str(dataset.get("sha256") or row.get("sha256")),
                size_bytes=dataset.get("size_bytes"),
            )
        if bucket:
            store.seed_bucket(
                bucket_id=str(bucket.get("bucket_id") or publication.get("bucket_id")),
                path=str(bucket.get("path")),
                sha256=str(bucket.get("sha256") or row.get("sha256")),
                size_bytes=bucket.get("size_bytes"),
            )
    pointer = store.seed_pointer(dict(publication.get("pointer") or {}))
    store.protected_prefixes.add(str(publication.get("bucket_release_prefix")))
    return {
        "dataset_object_count": len(
            {key for key in store.dataset if key[1] == publication["dataset_revision"]}
        ),
        "bucket_object_count": len(
            {
                path
                for (_bucket, path) in store.bucket
                if path.startswith(str(publication.get("bucket_release_prefix")))
            }
        ),
        "pointer": pointer,
        "raw_root_object_count": len(store.raw_root),
    }


# ---------------------------------------------------------------------------
# Quarterly identities
# ---------------------------------------------------------------------------


def _identity_row(
    *,
    jurisdiction_code: str,
    title: str,
    chapter: str,
    section: str,
    edition: str,
    source_seed: str,
    entry_seed: str,
    text_seed: str,
) -> dict[str, Any]:
    reject_positional_durable_identity(
        f"oul:{jurisdiction_code.lower()}:{title}-{chapter}-{section}:{edition}",
        name="legal_id",
    )
    row = {
        "code_family": "state_statute",
        "configuration": DEFAULT_CONFIGURATION,
        "edition": edition,
        "entry_cid": validate_entry_cid(
            content_cid_for(_hex_digest("entry", entry_seed)),
            name="entry_cid",
        ),
        "hierarchy": {
            "article": "",
            "chapter": chapter,
            "part": "",
            "section": section,
            "subsection": "",
            "title": title,
        },
        "jurisdiction_code": jurisdiction_code,
        "legal_id": (
            f"oul:{jurisdiction_code.lower()}:{title}-{chapter}-{section}:{edition}"
        ),
        "source_cid": validate_source_cid(
            content_cid_for(_hex_digest("source", source_seed)),
            name="source_cid",
        ),
        "text_hash": validate_text_hash(
            _hex_digest("text", text_seed), name="text_hash"
        ),
    }
    for field in REQUIRED_SERIALIZED_IDENTITY_FIELDS:
        if field not in row:
            raise MismatchError(f"identity row missing {field}")
    return row


def prior_identity_rows() -> list[dict[str, Any]]:
    return [
        _identity_row(
            jurisdiction_code="AL",
            title="1",
            chapter="1",
            section="1",
            edition="2024",
            source_seed="al-source-2024",
            entry_seed="al-entry-2024",
            text_seed="al-text-2024",
        ),
        _identity_row(
            jurisdiction_code="CA",
            title="1",
            chapter="2",
            section="100",
            edition="2024",
            source_seed="ca-source-2024",
            entry_seed="ca-entry-2024",
            text_seed="ca-text-2024",
        ),
        _identity_row(
            jurisdiction_code="DC",
            title="2",
            chapter="1",
            section="201",
            edition="2024",
            source_seed="dc-source-2024",
            entry_seed="dc-entry-2024",
            text_seed="dc-text-2024",
        ),
    ]


def apply_quarterly_observation(
    rows: Sequence[Mapping[str, Any]],
    *,
    window: str = QUARTERLY_WINDOW,
) -> dict[str, Any]:
    """Admit a new official CA observation; preserve unchanged identities."""

    next_rows: list[dict[str, Any]] = []
    changed: list[str] = []
    preserved: list[str] = []
    for row in rows:
        item = dict(row)
        code = str(item.get("jurisdiction_code"))
        if code in AFFECTED_JURISDICTIONS:
            prior_text = item["text_hash"]
            prior_source = item["source_cid"]
            prior_entry = item["entry_cid"]
            item = _identity_row(
                jurisdiction_code=code,
                title=str(item["hierarchy"]["title"]),
                chapter=str(item["hierarchy"]["chapter"]),
                section=str(item["hierarchy"]["section"]),
                edition=str(item["edition"]),
                source_seed=f"{code.lower()}-source-{window}",
                entry_seed=f"{code.lower()}-entry-{window}",
                text_seed=f"{code.lower()}-text-{window}",
            )
            if item["legal_id"] != row["legal_id"]:
                raise MismatchError("quarterly delta must preserve legal_id")
            if item["jurisdiction_code"] != row["jurisdiction_code"]:
                raise MismatchError("quarterly delta must preserve jurisdiction_code")
            if item["hierarchy"] != row["hierarchy"]:
                raise MismatchError("quarterly delta must preserve hierarchy")
            if item["edition"] != row["edition"]:
                raise MismatchError("quarterly delta must preserve edition")
            if item["text_hash"] == prior_text:
                raise MismatchError("affected observation did not change text_hash")
            if item["source_cid"] == prior_source:
                raise MismatchError("affected observation did not change source_cid")
            if item["entry_cid"] == prior_entry:
                raise MismatchError("affected observation did not change entry_cid")
            changed.append(code)
        else:
            if item != dict(row):
                raise MismatchError(f"unchanged identity drifted for {code}")
            preserved.append(code)
        next_rows.append(item)
    if tuple(changed) != AFFECTED_JURISDICTIONS:
        raise MismatchError(f"expected affected jurisdictions {AFFECTED_JURISDICTIONS}")
    observations_digest = digest_mapping(
        {
            "changed": changed,
            "kind": "open-us-law-quarterly-observations",
            "preserved": preserved,
            "rows": next_rows,
            "window": window,
        }
    )
    admission = {
        "affected_jurisdictions": list(AFFECTED_JURISDICTIONS),
        "changed_identity_fields": ["source_cid", "entry_cid", "text_hash"],
        "kind": "delta_admission",
        "observations_digest": observations_digest,
        "preserved_citation_fields": [
            "legal_id",
            "jurisdiction_code",
            "hierarchy",
            "edition",
        ],
        "preserved_jurisdictions": preserved,
        "required_identity_fields": list(REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS),
        "row_count": len(next_rows),
        "window": window,
    }
    return {
        "admission": admission,
        "observations_digest": observations_digest,
        "rows": next_rows,
    }


def compare_identity_preservation(
    prior: Sequence[Mapping[str, Any]],
    next_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    by_legal_id = {str(row["legal_id"]): dict(row) for row in next_rows}
    preserved_rows: list[str] = []
    rebuilt_rows: list[str] = []
    for row in prior:
        legal_id = str(row["legal_id"])
        nxt = by_legal_id.get(legal_id)
        if nxt is None:
            raise MismatchError(f"quarterly delta dropped identity {legal_id}")
        citation = ("jurisdiction_code", "hierarchy", "edition", "legal_id")
        for field in citation:
            if nxt.get(field) != row.get(field):
                raise MismatchError(
                    f"quarterly delta changed citation identity {legal_id}.{field}"
                )
        if str(row["jurisdiction_code"]) in AFFECTED_JURISDICTIONS:
            rebuilt_rows.append(legal_id)
        else:
            for field in REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS:
                if nxt.get(field) != row.get(field):
                    raise MismatchError(
                        f"unchanged row drifted {legal_id}.{field}"
                    )
            preserved_rows.append(legal_id)
    return {
        "ok": True,
        "preserved_legal_ids": preserved_rows,
        "rebuilt_legal_ids": rebuilt_rows,
        "preserved_count": len(preserved_rows),
        "rebuilt_count": len(rebuilt_rows),
    }


# ---------------------------------------------------------------------------
# Rehearsal steps
# ---------------------------------------------------------------------------


def derive_quarterly_manifest_digest(
    *,
    prior_manifest_digest: str,
    observations_digest: str,
    rebuilt_indexes: Sequence[str],
    window: str = QUARTERLY_WINDOW,
) -> str:
    digest = digest_mapping(
        {
            "kind": "open-us-law-quarterly-delta-manifest",
            "observations_digest": observations_digest,
            "prior_manifest_digest": normalize_sha256(
                prior_manifest_digest, name="prior_manifest_digest"
            ),
            "program_id": PROGRAM_ID,
            "rebuilt_indexes": list(rebuilt_indexes),
            "task_id": TASK_ID,
            "window": window,
        }
    )
    if digest == prior_manifest_digest:
        raise MismatchError("quarterly manifest digest collided with the prior pin")
    return digest


def derive_quarterly_dataset_revision(
    *,
    manifest_digest: str,
    prior_revision: str,
    observations_digest: str,
) -> str:
    digest = digest_mapping(
        {
            "kind": "open-us-law-quarterly-dataset-commit",
            "manifest_digest": manifest_digest,
            "observations_digest": observations_digest,
            "prior_revision": prior_revision,
            "program_id": PROGRAM_ID,
            "task_id": TASK_ID,
        }
    )
    revision = digest[:40]
    if revision == prior_revision:
        raise MismatchError("quarterly Dataset revision collided with the prior pin")
    return require_immutable_public_revision(revision, name="quarterly.dataset_revision")


def build_quarterly_artifacts(
    *,
    repo_id: str,
    revision: str,
    bucket_id: str,
    prefix: str,
    manifest_digest: str,
    observations_digest: str,
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for relative in QUARTERLY_RELATIVE_PATHS:
        rebuilt = relative in AFFECTED_RELATIVE_PATHS or relative == "manifest.json"
        digest = _hex_digest(
            "quarterly-artifact",
            manifest_digest,
            relative,
            observations_digest if rebuilt else "reused",
        )
        artifacts.append(
            {
                "bucket_id": bucket_id,
                "bucket_path": f"{prefix}{relative}",
                "index_family": relative.split("/", 1)[0],
                "rebuilt": rebuilt,
                "relative_path": relative,
                "repo_id": repo_id,
                "revision": revision,
                "sha256": digest,
                "size_bytes": 64 + (32 if rebuilt else 0),
            }
        )
    return artifacts


def build_pointer_document(
    *,
    dataset_revision: str,
    manifest_digest: str,
    release_root_cid: str | None = None,
) -> dict[str, Any]:
    digest = normalize_sha256(manifest_digest, name="pointer.manifest_digest")
    document = {
        "bucket_prefix": f"releases/{digest}/",
        "dataset_repo_id": DEFAULT_DATASET_REPO,
        "dataset_revision": require_immutable_public_revision(
            dataset_revision, name="pointer.dataset_revision"
        ),
        "kind": "open-us-law-release-pointer",
        "manifest_sha256": digest,
        "release_root_cid": release_root_cid or content_cid_for(digest),
        "schema": POINTER_SCHEMA,
        "source_bucket": DEFAULT_BUCKET_ID,
    }
    reject_credentials_in_payload(document, label="release_pointer")
    reject_identity_contamination(document, label="release_pointer")
    return document


def rehearse_interrupted_resume(
    store: IsolatedOperationsStore,
    artifacts: Sequence[Mapping[str, Any]],
    *,
    interrupt_after: int = INTERRUPT_AFTER,
) -> dict[str, Any]:
    expected_paths = [str(item["bucket_path"]) for item in artifacts]
    first = store.upload_objects(artifacts, interrupt_after=interrupt_after)
    if not first["interrupted"]:
        raise MismatchError("expected the first upload pass to interrupt")
    if first["pointer_still_prior"] is not True:
        raise OperationsSafetyError("interrupted upload must not update the pointer")
    if store.prefix_complete:
        raise OperationsSafetyError("interrupted prefix must not be marked complete")
    try:
        store.mark_prefix_complete(expected_paths=expected_paths)
    except OperationsSafetyError:
        pass
    else:
        raise OperationsSafetyError("incomplete prefix was marked complete")
    try:
        store.update_pointer({"dataset_revision": artifacts[0]["revision"]})
    except OperationsSafetyError:
        pass
    else:
        raise OperationsSafetyError("pointer updated before prefix completion")

    second = store.upload_objects(artifacts)
    if second["interrupted"]:
        raise MismatchError("resume pass must complete the prefix")
    skipped_paths = [row["relative_path"] for row in second["skipped"]]
    uploaded_paths = [row["relative_path"] for row in second["uploaded"]]
    expected_skipped = [
        str(item["relative_path"]) for item in artifacts[:interrupt_after]
    ]
    expected_uploaded = [
        str(item["relative_path"]) for item in artifacts[interrupt_after:]
    ]
    if skipped_paths != expected_skipped:
        raise MismatchError(
            "resume did not skip already-present objects: "
            f"{skipped_paths!r} != {expected_skipped!r}"
        )
    if uploaded_paths != expected_uploaded:
        raise MismatchError(
            "resume did not upload only the remaining objects: "
            f"{uploaded_paths!r} != {expected_uploaded!r}"
        )
    store.mark_prefix_complete(expected_paths=expected_paths)
    redownload = store.redownload_verify_prefix(expected=artifacts)
    return {
        "first_pass": {
            "interrupted": True,
            "pointer_still_prior": True,
            "remaining_count": len(first["remaining"]),
            "uploaded_count": len(first["uploaded"]),
        },
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "interrupt_after": interrupt_after,
        "ok": True,
        "prefix_complete": store.prefix_complete,
        "redownload": redownload,
        "resume_pass": {
            "interrupted": False,
            "skipped_count": len(second["skipped"]),
            "skipped_paths": skipped_paths,
            "uploaded_count": len(second["uploaded"]),
            "uploaded_paths": uploaded_paths,
        },
        "resumed_safely": True,
        "status": "resumed",
    }


def rehearse_quarterly_delta(
    store: IsolatedOperationsStore,
    *,
    publication: Mapping[str, Any],
) -> dict[str, Any]:
    prior_rows = prior_identity_rows()
    delta = apply_quarterly_observation(prior_rows)
    preservation = compare_identity_preservation(prior_rows, delta["rows"])
    prior_digest = normalize_sha256(
        publication["manifest_digest"], name="prior.manifest_digest"
    )
    prior_revision = require_immutable_public_revision(
        publication["dataset_revision"], name="prior.dataset_revision"
    )
    prior_prefix = require_bucket_content_root(
        publication["bucket_release_prefix"], manifest_digest=prior_digest
    )
    manifest_digest = derive_quarterly_manifest_digest(
        prior_manifest_digest=prior_digest,
        observations_digest=delta["observations_digest"],
        rebuilt_indexes=REBUILT_INDEX_FAMILIES,
    )
    revision = derive_quarterly_dataset_revision(
        manifest_digest=manifest_digest,
        prior_revision=prior_revision,
        observations_digest=delta["observations_digest"],
    )
    prefix = f"releases/{manifest_digest}/"
    store.begin_prefix(prefix=prefix)
    artifacts = build_quarterly_artifacts(
        repo_id=DEFAULT_DATASET_REPO,
        revision=revision,
        bucket_id=DEFAULT_BUCKET_ID,
        prefix=prefix,
        manifest_digest=manifest_digest,
        observations_digest=delta["observations_digest"],
    )
    resume = rehearse_interrupted_resume(store, artifacts)
    pointer = store.update_pointer(
        build_pointer_document(
            dataset_revision=revision,
            manifest_digest=manifest_digest,
        )
    )
    store.protected_prefixes.add(prefix)
    rebuilt = [
        item["relative_path"] for item in artifacts if item["rebuilt"]
    ]
    reused = [
        item["relative_path"] for item in artifacts if not item["rebuilt"]
    ]
    if store.prefix_exists(prior_prefix) is not True:
        raise OperationsSafetyError("quarterly upload deleted the prior prefix")
    if store.revision_exists(prior_revision) is not True:
        raise OperationsSafetyError("quarterly upload deleted the prior Dataset commit")
    return {
        "admission": delta["admission"],
        "affected_indexes": list(REBUILT_INDEX_FAMILIES),
        "affected_jurisdictions": list(AFFECTED_JURISDICTIONS),
        "artifacts": [
            {
                "rebuilt": item["rebuilt"],
                "relative_path": item["relative_path"],
                "sha256": item["sha256"],
            }
            for item in artifacts
        ],
        "bucket_prefix": prefix,
        "dataset_revision": revision,
        "identities": preservation,
        "manifest_digest": manifest_digest,
        "new_pin": {
            "bucket_prefix": prefix,
            "dataset_revision": revision,
            "manifest_digest": manifest_digest,
        },
        "observations_digest": delta["observations_digest"],
        "ok": True,
        "pointer": pointer["document"],
        "pointer_updated_last": pointer["pointer_updated_last"],
        "prior_pin_retained": {
            "bucket_prefix": prior_prefix,
            "dataset_revision": prior_revision,
            "manifest_digest": prior_digest,
            "prefix_present": True,
            "revision_present": True,
        },
        "rebuilt_relative_paths": rebuilt,
        "resume": resume,
        "reused_index_families": list(REUSED_INDEX_FAMILIES),
        "reused_relative_paths": reused,
        "status": "rehearsed",
        "window": QUARTERLY_WINDOW,
    }


def rehearse_rollback(
    store: IsolatedOperationsStore,
    *,
    prior_pointer: Mapping[str, Any],
    quarterly: Mapping[str, Any],
) -> dict[str, Any]:
    prior_revision = require_immutable_public_revision(
        prior_pointer.get("dataset_revision"), name="rollback.prior_revision"
    )
    prior_digest = normalize_sha256(
        prior_pointer.get("manifest_sha256") or prior_pointer.get("manifest_digest"),
        name="rollback.prior_manifest",
    )
    prior_prefix = require_bucket_content_root(
        prior_pointer.get("bucket_prefix") or f"releases/{prior_digest}/",
        manifest_digest=prior_digest,
    )
    quarterly_revision = require_immutable_public_revision(
        quarterly.get("dataset_revision"), name="rollback.quarterly_revision"
    )
    quarterly_prefix = str(quarterly.get("bucket_prefix"))
    result = store.rollback_pointer(prior_pointer)
    advertised = dict(store.pointer or {})
    if advertised.get("dataset_revision") != prior_revision:
        raise MismatchError("rollback did not restore the prior Dataset revision")
    if advertised.get("bucket_prefix") != prior_prefix:
        raise MismatchError("rollback did not restore the prior Bucket prefix")
    if not store.prefix_exists(quarterly_prefix):
        raise OperationsSafetyError("rollback deleted the quarterly prefix")
    if not store.revision_exists(quarterly_revision):
        raise OperationsSafetyError("rollback deleted the quarterly Dataset commit")
    if not store.prefix_exists(prior_prefix):
        raise OperationsSafetyError("rollback lost the prior prefix")
    if store.deletion_occurred:
        raise OperationsSafetyError("rollback performed a deletion")
    if result["deletion_performed"] is not False:
        raise OperationsSafetyError("rollback reported a deletion")
    return {
        "advertised_mapping": advertised,
        "candidate_tree_retained": True,
        "deletion_performed": False,
        "force_push_performed": False,
        "legacy_files_deleted": False,
        "ok": True,
        "path": "rollback",
        "pointer_path": BUCKET_POINTER_PATH,
        "pointer_updated_last": True,
        "policy": (
            "Change only the tiny LATEST.json pointer / recommended Dataset "
            "revision; immutable prior Dataset commits and Bucket prefixes "
            "remain addressable."
        ),
        "prior_advertised_revision": prior_revision,
        "prior_bucket_prefix": prior_prefix,
        "prior_manifest_digest": prior_digest,
        "quarterly_prefix_retained": quarterly_prefix,
        "quarterly_revision_retained": quarterly_revision,
        "retained_prefixes": result["retained_prefixes"],
        "status": "rehearsed",
        "visibility_changed": False,
    }


def rehearse_prior_pin_queries(
    store: IsolatedOperationsStore,
    *,
    prior: Mapping[str, Any],
    quarterly: Mapping[str, Any],
    canary: Mapping[str, Any],
) -> dict[str, Any]:
    prior_query = store.query_pin(
        dataset_revision=str(prior["dataset_revision"]),
        bucket_prefix=str(prior["bucket_release_prefix"]),
        manifest_digest=str(prior["manifest_digest"]),
    )
    quarterly_query = store.query_pin(
        dataset_revision=str(quarterly["dataset_revision"]),
        bucket_prefix=str(quarterly["bucket_prefix"]),
        manifest_digest=str(quarterly["manifest_digest"]),
    )
    canary_revision = require_immutable_public_revision(
        canary.get("dataset_revision"), name="canary.dataset_revision"
    )
    if canary_revision != prior_query["dataset_revision"]:
        raise MismatchError("public canary is not bound to the prior public pin")
    if list(canary.get("query_modes") or []) != list(QUERY_MODES):
        raise MismatchError("public canary is missing one or more query modes")
    return {
        "canary_bound_to_prior_pin": True,
        "ok": True,
        "pins": [
            {
                "kind": "prior_public",
                "queryable": True,
                "source": "OUL-044",
                **{
                    key: prior_query[key]
                    for key in (
                        "bucket_prefix",
                        "dataset_revision",
                        "manifest_digest",
                        "modes",
                    )
                },
            },
            {
                "kind": "quarterly_delta",
                "queryable": True,
                "source": "OUL-047",
                **{
                    key: quarterly_query[key]
                    for key in (
                        "bucket_prefix",
                        "dataset_revision",
                        "manifest_digest",
                        "modes",
                    )
                },
            },
        ],
        "prior_pin_queryable_after_rollback": True,
        "quarterly_pin_queryable_after_rollback": True,
        "query_mode_count": len(QUERY_MODES),
        "used_mutable_pointer": False,
    }


def rehearse_refill_closure(
    closure: Mapping[str, Any],
) -> dict[str, Any]:
    findings = list(closure.get("findings") or [])
    if not findings:
        raise RefillClosureError("refill closure has no findings")
    declared = int(closure.get("finding_count") or 0)
    if declared != len(findings):
        raise RefillClosureError(
            f"finding_count {declared} does not match findings {len(findings)}"
        )
    unresolved: list[str] = []
    dispositions: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for finding in findings:
        if not isinstance(finding, Mapping):
            unresolved.append("<non-object>")
            continue
        finding_id = str(finding.get("finding_id") or "<missing>")
        disposition = str(finding.get("disposition") or "")
        kinds[str(finding.get("kind") or "unknown")] = (
            kinds.get(str(finding.get("kind") or "unknown"), 0) + 1
        )
        dispositions[disposition] = dispositions.get(disposition, 0) + 1
        if finding.get("terminal") is not True:
            unresolved.append(finding_id)
            continue
        if disposition not in TERMINAL_REFILL_DISPOSITIONS:
            unresolved.append(finding_id)
    summary = dict(closure.get("repair_summary") or {})
    if "unresolved_count" not in summary or int(summary["unresolved_count"]) != 0:
        raise RefillClosureError("refill repair_summary.unresolved_count is not 0")
    if unresolved:
        raise RefillClosureError(
            "nonterminal refill findings: " + ", ".join(unresolved[:8])
        )
    acceptance = dict(closure.get("acceptance") or {})
    if acceptance.get("unresolved_finding_count") not in {0, None}:
        if acceptance.get("unresolved_finding_count") != 0:
            raise RefillClosureError("refill acceptance still lists unresolved findings")
    completed = int(summary.get("completed_repair_count") or 0)
    quarantined = int(summary.get("typed_terminal_quarantine_count") or 0)
    if completed + quarantined != declared:
        raise RefillClosureError(
            "repair_summary counts do not cover every finding"
        )
    return {
        "completed_repair_count": completed,
        "every_finding_terminal": True,
        "finding_count": declared,
        "finding_kinds": dict(sorted(kinds.items())),
        "ok": True,
        "path": REFILL_CLOSURE_RELPATH.as_posix(),
        "receipt_digest": closure.get("report_digest_sha256"),
        "schema_version": closure.get("schema_version"),
        "status": closure.get("status"),
        "task_id": closure.get("task_id"),
        "terminal_dispositions": dict(sorted(dispositions.items())),
        "typed_terminal_quarantine_count": quarantined,
        "unresolved_count": 0,
        "unresolved_finding_ids": [],
    }


# ---------------------------------------------------------------------------
# Report construction
# ---------------------------------------------------------------------------


def _acceptance_block(flags: Mapping[str, bool]) -> dict[str, Any]:
    acceptance = {
        "all_expected_outputs_required": True,
        "all_refill_findings_completed": bool(
            flags.get("all_refill_findings_completed")
        ),
        "criteria": ACCEPTANCE_CRITERIA,
        "interrupted_uploads_resume_safely": bool(
            flags.get("interrupted_uploads_resume_safely")
        ),
        "mutation_not_executed": True,
        "no_deletion": bool(flags.get("no_deletion")),
        "no_root_raw_object_overwritten": True,
        "no_secret_or_path_leak": True,
        "pointer_updated_last": bool(flags.get("pointer_updated_last")),
        "prior_public_pins_remain_queryable": bool(
            flags.get("prior_public_pins_remain_queryable")
        ),
        "quarterly_delta_preserves_identities": bool(
            flags.get("quarterly_delta_preserves_identities")
        ),
        "quarterly_delta_rebuilds_affected_indexes": bool(
            flags.get("quarterly_delta_rebuilds_affected_indexes")
        ),
        "rollback_repoints_without_deleting_immutable_releases": bool(
            flags.get("rollback_repoints_without_deleting_immutable_releases")
        ),
    }
    failed = [
        key
        for key in ACCEPTANCE_FLAGS
        if acceptance.get(key) is not True
    ]
    if failed:
        raise MismatchError("operations rehearsal acceptance failed: " + ", ".join(failed))
    return acceptance


def build_operations_rehearsal(
    *,
    repo_root: Path | str | None = None,
    publication_path: Path | str | None = None,
) -> dict[str, Any]:
    """Build the deterministic offline operations rehearsal receipt."""

    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    publication = load_publication_receipt(publication_path, repo_root=root)
    canary = load_public_canary(repo_root=root)
    refill = load_refill_closure(repo_root=root)
    _require_repo_file(PUBLIC_BENCHMARK_RELPATH, repo_root=root)
    _require_repo_file(COVERAGE_RELPATH, repo_root=root)

    if canary.get("dataset_revision") != publication.get("dataset_revision"):
        raise MismatchError("public canary drifted from the OUL-044 Dataset revision")
    if canary.get("bucket_content_root") != publication.get("bucket_release_prefix"):
        raise MismatchError("public canary drifted from the OUL-044 Bucket prefix")
    if canary.get("manifest_digest") != publication.get("manifest_digest"):
        raise MismatchError("public canary drifted from the OUL-044 manifest digest")

    store = IsolatedOperationsStore()
    seeded = seed_store_from_publication(store, publication)
    refill_rehearsal = rehearse_refill_closure(refill)
    quarterly = rehearse_quarterly_delta(store, publication=publication)
    rollback = rehearse_rollback(
        store,
        prior_pointer=dict(publication.get("pointer") or {}),
        quarterly=quarterly,
    )
    queries = rehearse_prior_pin_queries(
        store,
        prior=publication,
        quarterly=quarterly,
        canary=canary,
    )
    try:
        store.refuse_delete("immutable_release")
    except OperationsSafetyError:
        deletion_refused = True
    else:
        deletion_refused = False
    if not deletion_refused:
        raise OperationsSafetyError("store failed to refuse deletion")

    flags = {
        "all_refill_findings_completed": refill_rehearsal["ok"]
        and refill_rehearsal["unresolved_count"] == 0
        and refill_rehearsal["every_finding_terminal"] is True,
        "interrupted_uploads_resume_safely": bool(
            quarterly["resume"]["resumed_safely"]
        ),
        "no_deletion": rollback["deletion_performed"] is False
        and store.deletion_occurred is False,
        "pointer_updated_last": bool(quarterly["pointer_updated_last"])
        and bool(rollback["pointer_updated_last"]),
        "prior_public_pins_remain_queryable": bool(queries["ok"])
        and queries["prior_pin_queryable_after_rollback"]
        and queries["quarterly_pin_queryable_after_rollback"],
        "quarterly_delta_preserves_identities": bool(
            quarterly["identities"]["ok"]
        ),
        "quarterly_delta_rebuilds_affected_indexes": set(
            quarterly["affected_indexes"]
        )
        == set(REBUILT_INDEX_FAMILIES),
        "rollback_repoints_without_deleting_immutable_releases": bool(
            rollback["ok"]
        )
        and rollback["candidate_tree_retained"] is True
        and rollback["legacy_files_deleted"] is False,
    }
    acceptance = _acceptance_block(flags)

    report: dict[str, Any] = {
        "acceptance": acceptance,
        "adr_path": ADR_PATH,
        "board_namespace": BOARD_NAMESPACE,
        "bundle": BUNDLE,
        "code_version": CODE_VERSION,
        "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        "depends_on": list(DEPENDS_ON),
        "dry_run": True,
        "fixture_id": FIXTURE_ID,
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "goal_id": GOAL_ID,
        "live_network": False,
        "mutation_authorized": False,
        "mutation_executed": False,
        "network_required": False,
        "no_mutate": True,
        "notes": (
            "Offline operations rehearsal for Open US Law sparse GraphRAG "
            "(OUL-047). Rollback changes only the tiny LATEST.json pointer. "
            "Quarterly delta builds preserve unchanged statute identities, "
            "rebuild affected BM25/vector/graph indexes, and mint a new "
            "manifest digest, Dataset commit, and Bucket prefix. Interrupted "
            "add-only uploads resume by skipping already-present objects. "
            "Every OUL-023 refill finding is terminal. Prior and new public "
            "pins remain queryable. This receipt does not authorize mutation."
        ),
        "prior_public_pin": {
            "bucket_id": publication.get("bucket_id"),
            "bucket_prefix": publication.get("bucket_release_prefix"),
            "dataset_id": publication.get("dataset_id"),
            "dataset_revision": publication.get("dataset_revision"),
            "identities_digest": publication.get("identities_digest"),
            "manifest_digest": publication.get("manifest_digest"),
            "path": PUBLICATION_RECEIPT_RELPATH.as_posix(),
            "pointer_path": publication.get("bucket_pointer_path")
            or BUCKET_POINTER_PATH,
            "receipt_sha256": publication.get("receipt_sha256"),
            "remote_object_count": publication.get("remote_object_count"),
            "seeded_bucket_object_count": seeded["bucket_object_count"],
            "seeded_dataset_object_count": seeded["dataset_object_count"],
            "task_id": "OUL-044",
        },
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "public_canary": {
            "bucket_content_root": canary.get("bucket_content_root"),
            "dataset_revision": canary.get("dataset_revision"),
            "manifest_digest": canary.get("manifest_digest"),
            "path": PUBLIC_CANARY_RELPATH.as_posix(),
            "query_mode_count": canary.get("query_mode_count"),
            "receipt_sha256": canary.get("receipt_sha256"),
            "require_public_pin": True,
            "task_id": "OUL-045",
        },
        "public_mutation_authorized": False,
        "publication_authorized": False,
        "quarterly": {
            "affected_indexes": quarterly["affected_indexes"],
            "affected_jurisdictions": quarterly["affected_jurisdictions"],
            "artifacts": quarterly["artifacts"],
            "bucket_prefix": quarterly["bucket_prefix"],
            "dataset_revision": quarterly["dataset_revision"],
            "identities": quarterly["identities"],
            "manifest_digest": quarterly["manifest_digest"],
            "observations_digest": quarterly["observations_digest"],
            "ok": True,
            "pointer_updated_last": quarterly["pointer_updated_last"],
            "prior_pin_retained": quarterly["prior_pin_retained"],
            "rebuilt_relative_paths": quarterly["rebuilt_relative_paths"],
            "reused_index_families": quarterly["reused_index_families"],
            "reused_relative_paths": quarterly["reused_relative_paths"],
            "status": "rehearsed",
            "window": quarterly["window"],
        },
        "queries": queries,
        "refill_closure": refill_rehearsal,
        "remote_write_contacted": False,
        "resume": quarterly["resume"],
        "rollback": rollback,
        "schema": RECEIPT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "status": "rehearsed",
        "task_id": TASK_ID,
    }
    report["receipt_sha256"] = digest_mapping(
        {key: value for key, value in report.items() if key != "receipt_sha256"}
    )
    reject_credentials_in_payload(report, label="operations_rehearsal")
    reject_path_leaks(report, label="operations_rehearsal")
    reject_identity_contamination(report, label="operations_rehearsal")
    return report


def materialize_default_report(
    *,
    repo_root: Path | str | None = None,
    receipt_path: Path | str | None = None,
    publication_path: Path | str | None = None,
) -> tuple[dict[str, Any], Path]:
    report = build_operations_rehearsal(
        repo_root=repo_root, publication_path=publication_path
    )
    target = (
        Path(receipt_path).expanduser().resolve()
        if receipt_path is not None
        else default_receipt_path(repo_root)
    )
    path = write_json_report(report, target)
    return report, path


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
        "status",
        "live_network",
        "publication_authorized",
        "public_mutation_authorized",
        "mutation_authorized",
        "mutation_executed",
        "network_required",
        "no_mutate",
        "dry_run",
    )
    mismatches.extend(_compare_mappings(fresh, sealed, path="receipt", keys=top_keys))
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("prior_public_pin") or {}),
            dict(sealed.get("prior_public_pin") or {}),
            path="prior_public_pin",
            keys=(
                "dataset_revision",
                "bucket_prefix",
                "manifest_digest",
                "receipt_sha256",
                "identities_digest",
                "task_id",
            ),
        )
    )
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("quarterly") or {}),
            dict(sealed.get("quarterly") or {}),
            path="quarterly",
            keys=(
                "dataset_revision",
                "bucket_prefix",
                "manifest_digest",
                "observations_digest",
                "window",
                "affected_indexes",
                "affected_jurisdictions",
                "rebuilt_relative_paths",
                "reused_relative_paths",
            ),
        )
    )
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("rollback") or {}),
            dict(sealed.get("rollback") or {}),
            path="rollback",
            keys=(
                "path",
                "status",
                "ok",
                "deletion_performed",
                "legacy_files_deleted",
                "candidate_tree_retained",
                "prior_advertised_revision",
                "prior_bucket_prefix",
                "quarterly_prefix_retained",
            ),
        )
    )
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("resume") or {}),
            dict(sealed.get("resume") or {}),
            path="resume",
            keys=("ok", "resumed_safely", "interrupt_after", "status"),
        )
    )
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("refill_closure") or {}),
            dict(sealed.get("refill_closure") or {}),
            path="refill_closure",
            keys=(
                "task_id",
                "finding_count",
                "unresolved_count",
                "every_finding_terminal",
                "completed_repair_count",
                "typed_terminal_quarantine_count",
            ),
        )
    )
    if fresh.get("acceptance") != sealed.get("acceptance"):
        mismatches.append("acceptance drifted from the sealed receipt")
    if (fresh.get("queries") or {}).get("pins") != (sealed.get("queries") or {}).get(
        "pins"
    ):
        mismatches.append("queryable pins drifted from the sealed receipt")
    if fresh.get("receipt_sha256") != sealed.get("receipt_sha256"):
        mismatches.append("receipt_sha256 drifted from the sealed receipt")
    return mismatches


def check_receipt_structure(receipt: Mapping[str, Any]) -> None:
    required = (
        "acceptance",
        "prior_public_pin",
        "quarterly",
        "rollback",
        "resume",
        "refill_closure",
        "queries",
        "receipt_sha256",
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
        raise MismatchError("operations rehearsal must not authorize mutation")
    if receipt.get("public_mutation_authorized") is not False:
        raise MismatchError("operations rehearsal must not authorize mutation")
    if receipt.get("mutation_executed") is not False:
        raise MismatchError("operations rehearsal must not execute mutation")
    if receipt.get("live_network") is not False:
        raise MismatchError("receipt must be network-free")
    if receipt.get("network_required") is not False:
        raise MismatchError("receipt must be network-free")
    if receipt.get("no_mutate") is not True:
        raise MismatchError("receipt is not a no-mutate rehearsal")
    if receipt.get("dry_run") is not True:
        raise MismatchError("receipt is not a dry-run rehearsal")
    expected = digest_mapping(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    if receipt.get("receipt_sha256") != expected:
        raise StaleInputError("receipt_sha256 does not match the sealed surface")
    acceptance = dict(receipt.get("acceptance") or {})
    if acceptance.get("criteria") != ACCEPTANCE_CRITERIA:
        raise MismatchError("acceptance criteria drifted")
    for key in ACCEPTANCE_FLAGS:
        if acceptance.get(key) is not True:
            raise MismatchError(f"acceptance.{key} is not true")
    rollback = dict(receipt.get("rollback") or {})
    if rollback.get("deletion_performed") is not False:
        raise OperationsSafetyError("rollback must never delete")
    if rollback.get("legacy_files_deleted") is not False:
        raise OperationsSafetyError("rollback must retain immutable releases")
    if rollback.get("candidate_tree_retained") is not True:
        raise OperationsSafetyError("rollback must retain the quarterly tree")
    refill = dict(receipt.get("refill_closure") or {})
    if refill.get("unresolved_count") != 0:
        raise RefillClosureError("sealed refill closure still has unresolved findings")
    if refill.get("every_finding_terminal") is not True:
        raise RefillClosureError("sealed refill closure is not fully terminal")
    quarterly = dict(receipt.get("quarterly") or {})
    if quarterly.get("dataset_revision") == (
        (receipt.get("prior_public_pin") or {}).get("dataset_revision")
    ):
        raise MismatchError("quarterly Dataset revision must differ from the prior pin")
    if quarterly.get("manifest_digest") == (
        (receipt.get("prior_public_pin") or {}).get("manifest_digest")
    ):
        raise MismatchError("quarterly manifest digest must differ from the prior pin")
    require_immutable_public_revision(
        quarterly.get("dataset_revision"), name="quarterly.dataset_revision"
    )
    require_immutable_public_revision(
        (receipt.get("prior_public_pin") or {}).get("dataset_revision"),
        name="prior.dataset_revision",
    )


def check_operations_rehearsal(
    receipt: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
    publication_path: Path | str | None = None,
) -> dict[str, Any]:
    check_receipt_structure(receipt)
    reject_credentials_in_payload(receipt, label="operations_rehearsal")
    reject_path_leaks(receipt, label="operations_rehearsal")
    reject_identity_contamination(receipt, label="operations_rehearsal")
    publication = load_publication_receipt(
        publication_path, repo_root=repo_root
    )
    prior = dict(receipt.get("prior_public_pin") or {})
    if prior.get("dataset_revision") != publication.get("dataset_revision"):
        raise MismatchError("rehearsal is not bound to the public 40-hex revision")
    if prior.get("bucket_prefix") != publication.get("bucket_release_prefix"):
        raise MismatchError("rehearsal is not bound to the public bucket content root")
    if prior.get("manifest_digest") != publication.get("manifest_digest"):
        raise MismatchError("rehearsal manifest digest drifted from the public pin")
    fresh = build_operations_rehearsal(
        repo_root=repo_root, publication_path=publication_path
    )
    mismatches = compare_receipts(fresh, receipt)
    if mismatches:
        raise StaleInputError(
            "sealed receipt drifted from a fresh operations rehearsal: "
            + "; ".join(mismatches[:8])
        )
    return {
        "criteria": (receipt.get("acceptance") or {}).get("criteria"),
        "goal_id": receipt.get("goal_id"),
        "mismatches": [],
        "mutation_executed": False,
        "no_mutate": True,
        "ok": True,
        "prior_dataset_revision": prior.get("dataset_revision"),
        "prior_manifest_digest": prior.get("manifest_digest"),
        "publication_authorized": False,
        "quarterly_dataset_revision": (receipt.get("quarterly") or {}).get(
            "dataset_revision"
        ),
        "receipt_sha256": receipt.get("receipt_sha256"),
        "refill_unresolved_count": (receipt.get("refill_closure") or {}).get(
            "unresolved_count"
        ),
        "task_id": receipt.get("task_id"),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rehearse_open_us_law_operations.py",
        description=(
            "Rehearse rollback, quarterly delta updates, interrupted-upload "
            f"resume, and refill closure ({TASK_ID}). Default mode is "
            "offline, no-mutate, and network-free."
        ),
    )
    parser.add_argument(
        "--no-mutate",
        action="store_true",
        help="Refuse remote mutation (required; this CLI never mutates).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the frozen operations rehearsal receipt without rewriting it.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the rehearsal receipt to --receipt.",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help=f"Receipt path (default: {DEFAULT_RECEIPT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--publication",
        type=Path,
        default=None,
        help=f"Publication receipt (default: {PUBLICATION_RECEIPT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--authorize-mutation",
        action="store_true",
        help="Request live mutation (always refused).",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the receipt or check summary JSON to stdout.",
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

    if args.authorize_mutation:
        print("error: live mutation is refused by this CLI", file=sys.stderr)
        return 2

    check_mode = bool(args.check) or not (args.write or args.print_json)
    receipt_path = (
        Path(args.receipt).expanduser().resolve()
        if args.receipt is not None
        else default_receipt_path()
    )
    publication_path = (
        Path(args.publication).expanduser().resolve()
        if args.publication is not None
        else None
    )

    try:
        if check_mode:
            if not receipt_path.is_file():
                raise MissingInputError(
                    f"operations rehearsal receipt not found: "
                    f"{DEFAULT_RECEIPT_RELPATH.as_posix()}"
                )
            sealed = load_json_mapping(receipt_path)
            payload = check_operations_rehearsal(
                sealed, publication_path=publication_path
            )
            if args.no_mutate and payload.get("no_mutate") is not True:
                raise OperationsSafetyError("check lost the no-mutate contract")
            write_json(None, payload)
            return 0 if payload.get("ok") else 1

        report = build_operations_rehearsal(publication_path=publication_path)
        if args.write:
            write_json_report(report, receipt_path)
        if args.print_json or not args.write:
            write_json(None, report)
        return 0
    except (
        OperationsRehearsalError,
        OperationsSafetyError,
        OperationsAuthorizationError,
        MissingInputError,
        MismatchError,
        StaleInputError,
        PathLeakError,
        SecretLeakError,
        RefillClosureError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
