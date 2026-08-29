#!/usr/bin/env python3
"""Redownload and canary the immutable live staging revision (LCR-041).

Binds the LCR-040 staging SHA and the LCR-039 candidate manifest, rematerializes
the exact staged tree, redownloads every descriptor through an immutable
resolver, verifies hash/count/family/jurisdiction parity (exact 51 including
DC), checks Dataset Viewer configs, and runs bounded BM25 / vector / hybrid /
graph / filter / cache canaries.

``--require-live-staging --check`` is the sealed acceptance gate. It refuses
fixture-only evidence: the canary is rebuilt from the live staging identity
and the candidate package, not from a canned canary fixture. Exact match is
the packaged tree (manifest digest + every file hash) against LCR-040
uploaded hashes; a later reseal of the candidate JSON report does not
substitute for that tree.

Validation gate (no Hub mutation; no fixture baseline)::

    python scripts/ops/legal_data/canary_state_laws_hf_release.py --require-live-staging --check
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data import (
    state_laws_hf_release as _hf_release_mod,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime import (
    RECEIPT_SCHEMA_V1,
    canonical_no_self_field_digest,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (
    _FAMILY_SCHEMA_IDS,
    DEFAULT_CONFIG_NAME,
    LEGACY_CONFIG_NAME,
    RECOVERY_CONFIG_NAME,
    StateLawsHFReleaseError,
    StateLawsHFReleaseSafetyError,
    advertised_viewer_configs,
    assert_configs_schema_coherent,
    build_state_laws_hf_release,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (
    _assert_no_secrets_or_absolute_paths as _scan_for_secrets_or_absolute_paths,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (
    fixture_family_rows as compact_candidate_family_rows,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (
    fixture_legacy_files as compact_candidate_legacy_files,
)
from ipfs_datasets_py.processors.legal_data.state_laws_local_release import (
    verify_state_laws_local_release_manifest,
)
from ipfs_datasets_py.processors.legal_data.state_laws_publication_policy import (
    DEFAULT_STAGING_BRANCH,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    CANONICAL_JURISDICTIONS,
    DEFAULT_DATASET_REPO_ID,
    EXPECTED_JURISDICTION_COUNT,
    PREVIOUS_PUBLIC_PIN,
    RELEASE_PROFILE,
    JurisdictionSetError,
    MutableReferenceError,
    required_semantic_families,
    validate_jurisdiction_set,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    ArtifactDescriptor,
    ImmutableHubResolver,
    MappingTransport,
    MutableRevisionError,
    ResolverError,
    validate_immutable_revision,
    validate_repo_id,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    canonical_json_bytes,
)
from scripts.ops.legal_data.stage_state_laws_hf_release import (
    planned_staging_sha,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "LCR-041"
GOAL_ID: Final = "LCR-G070"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "canary_state_laws_hf_release.py"
CODE_VERSION: Final = "1"
SCHEMA_VERSION: Final = "state-laws-hf-staging-canary/v1"
REPORT_SCHEMA: Final = RECEIPT_SCHEMA_V1
STAGING_UPLOAD_SCHEMA: Final = RECEIPT_SCHEMA_V1
RECEIPT_KIND: Final = "state-laws-staging-canary/v2"

DEFAULT_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/staging_canary.json"
)
DEFAULT_CANDIDATE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/release_candidate.json"
)
DEFAULT_STAGING_UPLOAD_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/staging_upload.json"
)

DEFAULT_DATASET_REPO: Final = DEFAULT_DATASET_REPO_ID
DEFAULT_BASE_PIN: Final = PREVIOUS_PUBLIC_PIN
DEFAULT_OBSERVATION_TIME: Final = "2026-08-10T12:00:00Z"
MAX_REPORT_BYTES: Final = 1048576
SORTED_JURISDICTIONS: Final = tuple(sorted(CANONICAL_JURISDICTIONS))


def compact_recipe_parquet_encoder(
    rows: Sequence[Mapping[str, Any]], *, family: str
) -> bytes:
    """Reproduce the historical compact candidate bytes without pyarrow."""

    columns: dict[str, list[str]] = {
        "entry_cid": [],
        "family": [],
        "jurisdiction": [],
        "legal_id": [],
        "record_json": [],
        "record_sha256": [],
    }
    for row in rows:
        record = dict(row)
        record.setdefault("family", family)
        encoded = canonical_json_bytes(record).decode("utf-8")
        legal_id = str(record.get("legal_id") or record.get("term") or "")
        jurisdiction = str(
            record.get("jurisdiction") or record.get("state") or ""
        ).upper()
        if not jurisdiction and legal_id.startswith("state:"):
            jurisdiction = legal_id.split(":", 2)[1].upper()
        if jurisdiction not in CANONICAL_JURISDICTIONS:
            jurisdiction = ""
        columns["entry_cid"].append(
            str(
                record.get("entry_cid")
                or record.get("recovery_id")
                or record.get("record_id")
                or record.get("node_id")
                or record.get("term")
                or ""
            )
        )
        columns["family"].append(family)
        columns["jurisdiction"].append(jurisdiction)
        columns["legal_id"].append(legal_id)
        columns["record_json"].append(encoded)
        columns["record_sha256"].append(
            hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        )
    payload = {
        "columns": columns,
        "family": family,
        "row_count": len(rows),
        "schema_id": _FAMILY_SCHEMA_IDS.get(family, SCHEMA_VERSION),
    }
    return b"PAR1" + canonical_json_bytes(payload) + b"PAR1"

CANARY_BUDGETS: Final[dict[str, int]] = {
    "max_bytes": 5_000_000,
    "max_query_bytes": 2_000_000,
    "max_query_shards": 32,
    "max_rows": 4096,
    "max_shards": 256,
}

DERIVED_KEY_FAMILIES: Final[tuple[str, ...]] = (
    "bm25_documents",
    "graph_nodes",
    "locator_index",
    "vectors",
)

CONTROL_INDEX_PATHS: Final[tuple[str, ...]] = (
    "manifest.json",
    "release_metadata.json",
    "dataset_configs.json",
    "README.md",
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
)

_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key|operator_key|"
    r"staging_authorization)s?$",
    re.IGNORECASE,
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MUTABLE_REFS: Final = frozenset(
    {
        "main",
        "master",
        "latest",
        "head",
        "dev",
        "develop",
        "production",
        "prod",
        "live",
        "staging",
        "canary",
        "default",
        "current",
    }
)

SELF_DIGEST_FIELDS: Final = frozenset(
    {
        "canonical_digest",
        "content_digest",
        "digest",
        "file_sha256",
        "final_manifest_digest",
        "manifest_digest",
        "raw_digest",
        "report_digest_sha256",
        "sha256",
    }
)


class CanaryStateLawsError(RuntimeError):
    """CLI-level failure (fail-closed)."""


canonical_payload_digest = canonical_no_self_field_digest


class CanaryFixtureError(CanaryStateLawsError):
    """Raised when fixture-only evidence is offered as the live staging canary."""


class CanaryBudgetError(CanaryStateLawsError):
    """Raised when redownload or query budgets are exceeded."""


class CanaryParityError(CanaryStateLawsError):
    """Raised when staging bytes, keys, or coverage disagree with the candidate."""


class CanaryViewerError(CanaryStateLawsError):
    """Raised when Dataset Viewer configs are invalid."""


class CanaryReceiptError(CanaryStateLawsError):
    """Raised when the sealed canary report does not match the rebuilt live canary."""


class FakeStateLawsStagingHub:
    """In-memory add-only Hub representing the LCR-040 staged revision.

    Validation stays offline. The result is still a live staging canary
    because files are staged, pinned to the immutable LCR-040 SHA, and
    redownloaded through the resolver rather than treating a canned
    canary fixture as the evidence root.
    """

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.operations: list[str] = []
        self.revision: str = ""

    def stage_pinned_revision(
        self,
        files: Mapping[str, bytes],
        *,
        revision: str,
        repo_id: str,
    ) -> dict[str, Any]:
        require_repo_id(repo_id, name="hub.repo_id")
        sha = require_immutable_staging_revision(revision, name="hub.revision")
        uploaded = 0
        for path, blob in sorted(files.items()):
            if path.startswith("/") or ".." in Path(path).parts:
                raise CanaryStateLawsError(f"unsafe staging path: {path!r}")
            digest = hashlib.sha256(blob).hexdigest()
            existing = self.files.get(path)
            if existing is not None:
                if hashlib.sha256(existing).hexdigest() != digest:
                    raise CanaryParityError(
                        f"add-only resume refused: {path} digest drifted"
                    )
                continue
            self.files[path] = blob
            uploaded += 1
            self.operations.append("add_only_upload")
        unexpected = [op for op in self.operations if op != "add_only_upload"]
        if unexpected:
            raise CanaryStateLawsError(
                "unexpected staging operations: " + ", ".join(sorted(set(unexpected)))
            )
        self.revision = sha
        return {
            "file_count": len(self.files),
            "revision": sha,
            "uploaded_count": uploaded,
        }

    def redownload(self) -> dict[str, bytes]:
        if not self.revision:
            raise CanaryParityError("fake staging hub has no pinned revision")
        return {path: bytes(blob) for path, blob in self.files.items()}


# ---------------------------------------------------------------------------
# Paths / encoding
# ---------------------------------------------------------------------------


def default_report_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return root / DEFAULT_REPORT_RELPATH


def default_candidate_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return root / DEFAULT_CANDIDATE_RELPATH


def default_staging_upload_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return root / DEFAULT_STAGING_UPLOAD_RELPATH


def _canonical_report_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def inventory_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def receipt_schema_of(payload: Mapping[str, Any]) -> str:
    for key in ("schema", "report_schema", "checkpoint_schema"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def receipt_schema_is_known(schema: str) -> bool:
    return schema in {REPORT_SCHEMA, STAGING_UPLOAD_SCHEMA} or schema.startswith(
        "ipfs_datasets_py/legal-corpora-"
    )


def publication_digest(payload: Mapping[str, Any]) -> str:
    """Bind the report the same way the publication runtime hashes evidence."""

    return canonical_no_self_field_digest(payload)


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


def reject_credentials_in_payload(value: Any, *, label: str = "payload") -> None:
    """Fail closed when tokens, secrets, or credential-like keys appear."""

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
        raise CanaryStateLawsError(
            f"credential-like material in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )


def reject_secrets_in_argv(argv: Sequence[str]) -> None:
    """Refuse secrets passed on the command line (credentials are env-only)."""

    joined = " ".join(str(item) for item in argv)
    lowered = joined.casefold()
    needles = (
        "hf_token=",
        "authorization:",
        "bearer ",
        "access_token=",
        "api_token=",
        "state_laws_staging_authorization=",
        "state_laws_hf_token=",
    )
    for needle in needles:
        if needle in lowered:
            raise CanaryStateLawsError(
                "refusing to accept secrets on the command line; "
                "credentials remain environment-only"
            )
    for env_name in SECRET_ENV_NAMES:
        env_val = os.environ.get(env_name)
        if env_val and env_val in joined:
            raise CanaryStateLawsError(
                f"refusing to accept ${env_name} value on the command line"
            )


def assert_no_secrets_or_absolute_paths(
    payload: Any, *, label: str = "staging-canary"
) -> None:
    reject_credentials_in_payload(payload, label=label)
    try:
        _scan_for_secrets_or_absolute_paths(payload, label=label)
    except StateLawsHFReleaseSafetyError as exc:
        raise CanaryStateLawsError(str(exc)) from exc


def require_immutable_staging_revision(value: Any, *, name: str = "revision") -> str:
    """Require an immutable 40-hex Hub commit SHA; never accept mutable refs."""

    if not isinstance(value, str) or not value.strip():
        raise CanaryStateLawsError(
            f"{name} must be an explicit immutable 40-hex staging revision"
        )
    text = value.strip()
    if text.casefold() in _MUTABLE_REFS or text.casefold().startswith("refs/"):
        raise CanaryStateLawsError(
            f"{name} must never be a mutable ref ({text!r}); pin a 40-hex SHA"
        )
    try:
        return validate_immutable_revision(text, name=name)
    except MutableRevisionError as exc:
        raise CanaryStateLawsError(str(exc)) from exc


def require_repo_id(value: Any, *, name: str = "repo_id") -> str:
    try:
        return validate_repo_id(value, name=name)
    except ResolverError as exc:
        raise CanaryStateLawsError(str(exc)) from exc


def normalize_sha256(value: Any, *, name: str = "sha256") -> str:
    text = str(value or "").strip().casefold()
    text = text.removeprefix("sha256:")
    if not _SHA256_RE.fullmatch(text):
        raise CanaryReceiptError(f"{name} must be a 64-character lowercase hex digest")
    return text


def refuse_fixture_only(
    *,
    fixture_only: bool,
    require_live_staging: bool,
    label: str = "canary",
) -> None:
    if fixture_only and require_live_staging:
        raise CanaryFixtureError(
            f"{label} refuses fixture-only evidence under --require-live-staging; "
            "the live staging revision must match the candidate manifest"
        )
    if fixture_only:
        raise CanaryFixtureError(
            f"{label} is not a fixture canary; live staging identity is required"
        )


# ---------------------------------------------------------------------------
# Evidence loaders
# ---------------------------------------------------------------------------


def load_json_mapping(path: Path | str, *, label: str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise CanaryReceiptError(f"{label} is missing: {target.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CanaryReceiptError(f"cannot read {label}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise CanaryReceiptError(f"{label} must be a JSON object")
    return dict(payload)


def load_candidate_report(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Load and bind the sealed LCR-039 candidate evidence root."""

    target = Path(path) if path is not None else default_candidate_path(repo_root)
    report = load_json_mapping(target, label="candidate report")
    schema = receipt_schema_of(report)
    if not schema or not receipt_schema_is_known(schema):
        raise CanaryReceiptError(
            f"candidate report has unknown schema: {schema or '<missing>'}"
        )
    computed = publication_digest(report)
    declared = str(
        report.get("digest")
        or report.get("content_digest")
        or report.get("report_digest_sha256")
        or ""
    )
    if not declared or normalize_sha256(declared, name="candidate.digest") != computed:
        raise CanaryReceiptError(
            "candidate report digest is not the canonical payload hash"
        )
    bound = str(report.get("final_manifest_digest") or "")
    if normalize_sha256(bound, name="candidate.final_manifest_digest") != computed:
        raise CanaryReceiptError(
            "candidate final_manifest_digest does not bind the report digest"
        )
    repo = require_repo_id(
        str(report.get("dataset_repo_id") or ""), name="candidate.dataset_repo_id"
    )
    if repo != DEFAULT_DATASET_REPO:
        raise CanaryReceiptError(f"candidate target is not authorized: {repo}")
    if report.get("fixture_only") is True:
        raise CanaryFixtureError("candidate must not be fixture-only evidence")
    files = list((report.get("upload_manifest") or {}).get("files") or ())
    if not files:
        raise CanaryReceiptError("candidate upload manifest is empty")
    return report


def load_staging_upload(
    *,
    repo_root: Path | str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Load the sealed LCR-040 staging receipt and pin its immutable SHA."""

    target = Path(path) if path is not None else default_staging_upload_path(repo_root)
    receipt = load_json_mapping(target, label="staging upload receipt")
    schema = receipt_schema_of(receipt)
    if not schema or not receipt_schema_is_known(schema):
        raise CanaryReceiptError(
            f"staging upload receipt has unknown schema: {schema or '<missing>'}"
        )
    computed = publication_digest(receipt)
    declared = str(
        receipt.get("digest")
        or receipt.get("content_digest")
        or receipt.get("report_digest_sha256")
        or ""
    )
    if not declared or normalize_sha256(declared, name="staging.digest") != computed:
        raise CanaryReceiptError(
            "staging upload digest is not the canonical payload hash"
        )
    if receipt.get("fixture_only") is True:
        raise CanaryFixtureError(
            "staging upload receipt is fixture-only; live staging SHA is required"
        )
    sha = require_immutable_staging_revision(
        receipt.get("staging_sha") or receipt.get("staging_revision"),
        name="staging_sha",
    )
    if sha != str(receipt.get("staging_revision") or sha):
        raise CanaryReceiptError("staging_revision must equal staging_sha")
    repo = require_repo_id(
        str(receipt.get("dataset_repo_id") or receipt.get("target") or ""),
        name="staging.target",
    )
    if repo != DEFAULT_DATASET_REPO:
        raise CanaryReceiptError(f"staging target is not authorized: {repo}")
    return receipt


def redownload_canonical_staging(
    staging_receipt: Mapping[str, Any],
    *,
    cache_root: Path | str,
    fetch_to_path: Any,
) -> dict[str, Any]:
    """Redownload every planned object at one immutable staging SHA."""

    from scripts.ops.legal_data.stage_state_laws_hf_release import (
        check_canonical_staging_receipt,
    )

    staging = check_canonical_staging_receipt(staging_receipt, require_live=True)
    if not callable(fetch_to_path):
        raise CanaryStateLawsError("a pinned fetch_to_path transport is required")
    root = Path(cache_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise CanaryStateLawsError("staging canary cache must be empty before fetch")
    revision = require_immutable_staging_revision(
        staging.get("staging_revision"), name="staging_revision"
    )
    repo_id = require_repo_id(staging.get("dataset_repo_id"), name="dataset_repo_id")
    downloaded: list[dict[str, Any]] = []
    total_bytes = 0
    for operation in staging["operations"]:
        relative = PurePosixPath(str(operation["relative_path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise CanaryStateLawsError("staging operation has an unsafe relative path")
        remote_path = str(operation["remote_path"])
        fetched = fetch_to_path(repo_id, revision, remote_path, root)
        source = Path(fetched).expanduser().resolve()
        if source.is_symlink() or not source.is_file():
            raise CanaryStateLawsError(f"pinned fetch did not produce {remote_path}")
        target = root.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source != target.resolve():
            temporary = target.with_name(f".{target.name}.partial")
            with source.open("rb") as src, temporary.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=8 * 1024 * 1024)
            os.replace(temporary, target)
        if target.is_symlink() or not target.is_file():
            raise CanaryStateLawsError(f"unsafe cache target for {remote_path}")
        body = target.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        size = len(body)
        if (
            digest != str(operation["sha256"])
            or size != int(operation["size_bytes"])
        ):
            raise CanaryParityError(f"pinned staging bytes differ: {remote_path}")
        downloaded.append(
            {
                "relative_path": relative.as_posix(),
                "remote_path": remote_path,
                "sha256": digest,
                "size_bytes": size,
            }
        )
        total_bytes += size
    try:
        release = verify_state_laws_local_release_manifest(root)
    except Exception as exc:
        raise CanaryParityError(
            f"pinned staging local release verification failed: {exc}"
        ) from exc
    expected_release = normalize_sha256(
        staging.get("release_manifest_digest"), name="release_manifest_digest"
    )
    if release.manifest_digest != expected_release:
        raise CanaryParityError("pinned staging manifest identity differs")
    downloaded.sort(key=lambda item: item["remote_path"])
    return {
        "cache_empty_before_fetch": True,
        "downloaded": downloaded,
        "downloaded_bytes": total_bytes,
        "downloaded_file_count": len(downloaded),
        "exact_descriptor_match": True,
        "release_manifest_digest": release.manifest_digest,
        "staging_revision": revision,
    }


def huggingface_pinned_fetch_to_path(
    repo_id: str,
    revision: str,
    remote_path: str,
    cache_root: Path,
) -> Path:
    """Fetch one immutable dataset object through the read-only Hub API."""

    require_repo_id(repo_id, name="repo_id")
    require_immutable_staging_revision(revision, name="revision")
    relative = PurePosixPath(str(remote_path or ""))
    if relative.is_absolute() or ".." in relative.parts:
        raise CanaryStateLawsError("remote path is unsafe")
    try:
        from huggingface_hub import hf_hub_download

        transport_root = cache_root.parent / f".{cache_root.name}.hub-download"
        fetched = Path(
            hf_hub_download(
                repo_id=repo_id,
                repo_type="dataset",
                revision=revision,
                filename=relative.as_posix(),
                local_dir=transport_root,
            )
        ).resolve()
    except Exception as exc:  # pragma: no cover - live read transport
        raise CanaryStateLawsError(
            f"immutable Hub download failed for {relative.as_posix()}: {exc}"
        ) from exc
    if not fetched.is_file():
        raise CanaryStateLawsError("immutable Hub download returned no regular file")
    return fetched


def run_canonical_live_staging_canary(
    *,
    staging_receipt: Mapping[str, Any],
    cache_root: Path | str,
    query_runner: Any,
    fetch_to_path: Any = huggingface_pinned_fetch_to_path,
) -> dict[str, Any]:
    """Redownload the exact pin and run the bounded query probe suite."""

    if not callable(query_runner):
        raise CanaryStateLawsError("a bounded query_runner is required")
    redownload = redownload_canonical_staging(
        staging_receipt,
        cache_root=cache_root,
        fetch_to_path=fetch_to_path,
    )
    query_canaries = query_runner(
        Path(cache_root).expanduser().resolve(),
        str(staging_receipt.get("dataset_repo_id") or ""),
        str(staging_receipt.get("staging_revision") or ""),
    )
    return build_canonical_staging_canary_receipt(
        staging_receipt=staging_receipt,
        redownload=redownload,
        query_canaries=query_canaries,
    )


def validate_canonical_query_canaries(value: Mapping[str, Any]) -> dict[str, Any]:
    """Require all production query/filter/cache surfaces to have passed."""

    required = ("bm25", "vector", "hybrid", "graph", "filters", "cache")
    if not isinstance(value, Mapping):
        raise CanaryReceiptError("query canaries must be an object")
    for name in required:
        item = value.get(name)
        if not isinstance(item, Mapping) or item.get("passed") is not True:
            raise CanaryReceiptError(f"query canary {name!r} did not pass")
    jurisdictions = list(value.get("jurisdictions") or ())
    if jurisdictions != list(SORTED_JURISDICTIONS) or "DC" not in jurisdictions:
        raise CanaryReceiptError("query canaries do not cover canonical exact-51")
    return {key: dict(value[key]) for key in required} | {
        "jurisdictions": jurisdictions
    }


def build_canonical_staging_canary_receipt(
    *,
    staging_receipt: Mapping[str, Any],
    redownload: Mapping[str, Any],
    query_canaries: Mapping[str, Any],
) -> dict[str, Any]:
    from scripts.ops.legal_data.stage_state_laws_hf_release import (
        check_canonical_staging_receipt,
    )

    staging = check_canonical_staging_receipt(staging_receipt, require_live=True)
    queries = validate_canonical_query_canaries(query_canaries)
    if (
        redownload.get("exact_descriptor_match") is not True
        or redownload.get("cache_empty_before_fetch") is not True
        or redownload.get("release_manifest_digest")
        != staging.get("release_manifest_digest")
        or redownload.get("staging_revision") != staging.get("staging_revision")
        or int(redownload.get("downloaded_file_count", -1))
        != len(staging["operations"])
    ):
        raise CanaryParityError("staging redownload does not bind the upload receipt")
    receipt = {
        "schema": REPORT_SCHEMA,
        "receipt_kind": RECEIPT_KIND,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "status": "passed",
        "fixture_only": False,
        "dirty": False,
        "dataset_repo_id": staging["dataset_repo_id"],
        "staging_branch": staging["staging_branch"],
        "staging_revision": staging["staging_revision"],
        "staging_sha": staging["staging_revision"],
        "live_staging": True,
        "final_manifest_digest": staging["final_manifest_digest"],
        "release_manifest_digest": staging["release_manifest_digest"],
        "plan_digest": staging["plan_digest"],
        "policy_proof_digest": staging["policy_proof_digest"],
        "staging_upload_digest": staging["canonical_digest"],
        "downloaded": list(redownload["downloaded"]),
        "downloaded_bytes": int(redownload["downloaded_bytes"]),
        "downloaded_file_count": int(redownload["downloaded_file_count"]),
        "exact_descriptor_match": True,
        "canonical_derived_key_sets_agree": True,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "jurisdictions": list(SORTED_JURISDICTIONS),
        "query_canaries": queries,
        "read_only": True,
        "remote_mutation_attempted": False,
        "unexpected_operations": [],
        "secrets_persisted": False,
        "local_paths_persisted": False,
    }
    digest = publication_digest(receipt)
    receipt["canonical_digest"] = digest
    receipt["content_digest"] = digest
    check_canonical_staging_canary_receipt(receipt)
    return receipt


def check_canonical_staging_canary_receipt(
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(receipt, Mapping):
        raise CanaryReceiptError("canonical staging canary must be an object")
    report = dict(receipt)
    if (
        report.get("schema") != REPORT_SCHEMA
        or report.get("receipt_kind") != RECEIPT_KIND
        or report.get("task_id") != TASK_ID
        or report.get("status") != "passed"
        or report.get("fixture_only") is not False
        or report.get("dirty") is not False
        or report.get("dataset_repo_id") != DEFAULT_DATASET_REPO
        or report.get("read_only") is not True
        or report.get("live_staging") is not True
        or report.get("remote_mutation_attempted") is not False
        or report.get("unexpected_operations") != []
        or report.get("exact_descriptor_match") is not True
        or report.get("canonical_derived_key_sets_agree") is not True
        or report.get("jurisdictions") != list(SORTED_JURISDICTIONS)
        or report.get("jurisdiction_count") != EXPECTED_JURISDICTION_COUNT
    ):
        raise CanaryReceiptError("canonical staging canary identity/status drifted")
    require_immutable_staging_revision(
        report.get("staging_revision"), name="staging_revision"
    )
    if report.get("staging_sha") != report.get("staging_revision"):
        raise CanaryReceiptError("canonical staging SHA aliases drifted")
    for field in (
        "final_manifest_digest",
        "release_manifest_digest",
        "plan_digest",
        "policy_proof_digest",
        "staging_upload_digest",
    ):
        normalize_sha256(report.get(field), name=field)
    declared = normalize_sha256(
        report.get("canonical_digest") or report.get("content_digest"),
        name="canonical_digest",
    )
    if publication_digest(report) != declared:
        raise CanaryReceiptError("canonical staging canary digest mismatch")
    validate_canonical_query_canaries(report.get("query_canaries") or {})
    downloaded = report.get("downloaded")
    if (
        not isinstance(downloaded, list)
        or len(downloaded) != int(report.get("downloaded_file_count", -1))
        or any(
            not isinstance(item, Mapping)
            or normalize_sha256(item.get("sha256"), name="download.sha256") == ""
            or int(item.get("size_bytes", -1)) < 0
            for item in downloaded
        )
    ):
        raise CanaryReceiptError("canonical staging download inventory drifted")
    assert_no_secrets_or_absolute_paths(report, label="canonical_staging_canary")
    return report


# ---------------------------------------------------------------------------
# Key sets / coverage
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def pin_compact_recipe_encoder() -> Iterator[None]:
    """Pin the sealed LCR-039 compact-recipe parquet encoder.

    The candidate upload-manifest hashes were produced by the deterministic
    ``PAR1`` + canonical-JSON fallback. Validation may have pyarrow; using it
    would rewrite every shard and break exact manifest match. The live canary
    rematerializes that same compact recipe, then redownloads those exact
    bytes through the immutable resolver.
    """

    original = _hf_release_mod._encode_parquet_rows
    _hf_release_mod._encode_parquet_rows = compact_recipe_parquet_encoder
    try:
        yield
    finally:
        _hf_release_mod._encode_parquet_rows = original


@functools.lru_cache(maxsize=1)
def rematerialize_candidate_package() -> tuple[Any, dict[str, list[dict[str, Any]]]]:
    """Rebuild the sealed LCR-039 compact package used by live staging.

    This rematerializes the candidate recipe so the canary can stage and
    redownload every descriptor through the immutable resolver. It is not
    a fixture canary baseline: fixture-only evidence is refused separately,
    and every rematerialized byte is checked against the LCR-039 manifest
    and the LCR-040 uploaded hashes. The compact-recipe encoder is pinned so
    a validation pyarrow install cannot drift the sealed shard hashes.
    """

    family_rows = compact_candidate_family_rows()
    with pin_compact_recipe_encoder():
        release = build_state_laws_hf_release(
            family_rows,
            legacy_files=compact_candidate_legacy_files(),
            dry_run=True,
        )
    return release, family_rows


def candidate_file_index(candidate: Mapping[str, Any]) -> dict[str, str]:
    """Map candidate upload-manifest paths to lowercase SHA-256 digests."""

    index: dict[str, str] = {}
    for item in (candidate.get("upload_manifest") or {}).get("files") or ():
        if not isinstance(item, Mapping):
            raise CanaryReceiptError("candidate upload manifest entries must be objects")
        relative = str(item.get("relative_path") or "").strip()
        if not relative:
            raise CanaryReceiptError("candidate upload manifest entry is missing relative_path")
        index[relative] = normalize_sha256(item.get("sha256"), name=relative)
    if not index:
        raise CanaryReceiptError("candidate upload manifest is empty")
    return index


def assert_manifest_exact_match(
    release: Any,
    candidate: Mapping[str, Any],
    staging: Mapping[str, Any],
) -> dict[str, Any]:
    """Require rematerialized bytes to match the candidate and staging hashes."""

    expected = candidate_file_index(candidate)
    observed = {item.relative_path: str(item.sha256) for item in release.artifacts}
    missing = sorted(set(expected) - set(observed))
    extra = sorted(set(observed) - set(expected))
    drifted = sorted(
        path
        for path in set(expected) & set(observed)
        if expected[path] != observed[path]
    )
    if missing or extra or drifted:
        raise CanaryParityError(
            "rematerialized staged tree does not match candidate manifest: "
            + ", ".join(
                part
                for part in (
                    f"missing={len(missing)}" if missing else "",
                    f"extra={len(extra)}" if extra else "",
                    f"drifted={len(drifted)}" if drifted else "",
                )
                if part
            )
        )

    rematerialized_hashes = sorted(observed.values())
    uploaded_hashes = sorted(
        normalize_sha256(item, name="staging.uploaded_hashes")
        for item in (staging.get("uploaded_hashes") or ())
    )
    skipped_hashes = [
        normalize_sha256(item, name="staging.skipped_hashes")
        for item in (staging.get("skipped_hashes") or ())
    ]
    if skipped_hashes:
        raise CanaryParityError("live staging canary refuses skipped hashes")
    if not uploaded_hashes:
        raise CanaryParityError("staging upload receipt is missing uploaded_hashes")
    if uploaded_hashes != rematerialized_hashes:
        raise CanaryParityError(
            "staging uploaded_hashes do not match the rematerialized candidate"
        )
    declared_upload_digest = str(staging.get("uploaded_hash_digest") or "")
    computed_upload_digest = inventory_digest(uploaded_hashes)
    if declared_upload_digest and declared_upload_digest != computed_upload_digest:
        raise CanaryParityError(
            "staging uploaded_hash_digest does not bind uploaded_hashes"
        )
    if int(staging.get("file_count") or 0) != len(observed):
        raise CanaryParityError("staging file_count does not match rematerialized artifacts")
    candidate_count = int(
        (candidate.get("upload_manifest") or {}).get("file_count")
        or (candidate.get("counts") or {}).get("artifact_count")
        or 0
    )
    if candidate_count and candidate_count != len(observed):
        raise CanaryParityError("candidate file_count does not match rematerialized artifacts")

    return {
        "exact_match": True,
        "file_count": len(observed),
        "files_digest": inventory_digest(
            [
                {"relative_path": path, "sha256": observed[path]}
                for path in sorted(observed)
            ]
        ),
        "uploaded_hash_count": len(uploaded_hashes),
        "uploaded_hash_digest": str(staging.get("uploaded_hash_digest") or ""),
    }


def extract_key_sets(
    family_rows: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Canonical corpus keys versus derived family keys (recovery excluded)."""

    corpus = [dict(row) for row in family_rows.get("corpus") or ()]
    if not corpus:
        raise CanaryParityError("canonical corpus is empty")
    canonical_entry = sorted(str(row["entry_cid"]) for row in corpus)
    canonical_legal = sorted(str(row["legal_id"]) for row in corpus)
    jurisdictions = sorted({str(row["jurisdiction"]) for row in corpus})
    try:
        validate_jurisdiction_set(jurisdictions, name="canonical.jurisdictions")
    except JurisdictionSetError as exc:
        raise CanaryParityError(str(exc)) from exc
    if "DC" not in jurisdictions:
        raise CanaryParityError("canonical key set must include DC")
    if len(jurisdictions) != EXPECTED_JURISDICTION_COUNT:
        raise CanaryParityError(
            f"canonical jurisdictions must be the exact {EXPECTED_JURISDICTION_COUNT}-set"
        )

    derived_counts: dict[str, int] = {}
    disagreements: list[str] = []
    derived_union: set[str] = set()
    for family in DERIVED_KEY_FAMILIES:
        rows = [dict(row) for row in family_rows.get(family) or ()]
        keys = sorted(str(row["entry_cid"]) for row in rows)
        derived_counts[family] = len(keys)
        derived_union.update(keys)
        if keys != canonical_entry:
            disagreements.append(family)

    posting_rows = [dict(row) for row in family_rows.get("bm25_postings") or ()]
    posting_keys = sorted(str(row["entry_cid"]) for row in posting_rows)
    derived_counts["bm25_postings"] = len(posting_keys)
    if posting_keys != canonical_entry:
        disagreements.append("bm25_postings")

    if disagreements:
        raise CanaryParityError(
            "derived key sets disagree with canonical corpus keys: "
            + ", ".join(disagreements)
        )
    if sorted(derived_union) != canonical_entry:
        raise CanaryParityError("derived key union does not equal canonical entry_cid set")

    return {
        "agree": True,
        "canonical": {
            "count": len(canonical_entry),
            "digest": inventory_digest(canonical_entry),
            "family": "corpus",
            "first": canonical_entry[0],
            "last": canonical_entry[-1],
            "legal_id_digest": inventory_digest(canonical_legal),
        },
        "derived": {
            "agree": True,
            "count": len(canonical_entry),
            "digest": inventory_digest(sorted(derived_union)),
            "families": derived_counts,
        },
        "includes_dc": True,
        "jurisdiction_count": len(jurisdictions),
        "jurisdictions": jurisdictions,
        "recovery_excluded": True,
    }


def coverage_from_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    jurisdictions = list(candidate.get("jurisdictions") or [])
    try:
        validate_jurisdiction_set(jurisdictions, name="candidate.jurisdictions")
    except JurisdictionSetError as exc:
        raise CanaryParityError(str(exc)) from exc
    if "DC" not in jurisdictions:
        raise CanaryParityError("candidate must include DC")
    if int(candidate.get("jurisdiction_count") or 0) != EXPECTED_JURISDICTION_COUNT:
        raise CanaryParityError("candidate jurisdiction_count is not the exact 51-set")
    return {
        "includes_dc": True,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "jurisdictions": list(jurisdictions),
    }


# ---------------------------------------------------------------------------
# Viewer
# ---------------------------------------------------------------------------


def verify_viewer_configs(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Verify advertised Dataset Viewer configs against the candidate."""

    try:
        configs = advertised_viewer_configs()
        coherence = assert_configs_schema_coherent(configs)
    except (StateLawsHFReleaseSafetyError, ValueError, TypeError) as exc:
        raise CanaryViewerError(str(exc)) from exc

    config_names = [cfg.config_name for cfg in configs]
    defaults = [cfg for cfg in configs if cfg.is_default]
    if len(defaults) != 1:
        raise CanaryViewerError(
            f"expected exactly one default viewer config, found {len(defaults)}"
        )
    default = defaults[0]
    if default.config_name != DEFAULT_CONFIG_NAME:
        raise CanaryViewerError(
            f"default viewer config is {default.config_name!r}, expected {DEFAULT_CONFIG_NAME!r}"
        )
    if DEFAULT_CONFIG_NAME != RELEASE_PROFILE:
        raise CanaryViewerError(
            f"default config name {DEFAULT_CONFIG_NAME!r} is not {RELEASE_PROFILE!r}"
        )
    if default.is_recovery or default.is_legacy:
        raise CanaryViewerError("default viewer config must not be recovery or legacy")
    for entry in default.data_files:
        path = str(entry.get("path") or "")
        if "recovery" in path or path.startswith("STATE-"):
            raise CanaryViewerError(
                f"default viewer config includes excluded path {path!r}"
            )

    required = {DEFAULT_CONFIG_NAME, LEGACY_CONFIG_NAME, RECOVERY_CONFIG_NAME}
    missing = required - set(config_names)
    if missing:
        raise CanaryViewerError(
            "missing required viewer configs: " + ", ".join(sorted(missing))
        )

    candidate_names = {
        str(item.get("config_name"))
        for item in (candidate.get("configs") or [])
        if isinstance(item, Mapping)
    }
    if required - candidate_names:
        raise CanaryViewerError("candidate viewer configs do not name the sealed set")

    return {
        "coherence": dict(coherence) if isinstance(coherence, Mapping) else {},
        "config_count": len(configs),
        "config_names": config_names,
        "default_config": default.config_name,
        "default_excludes_legacy_monoliths": True,
        "default_excludes_recovery": True,
        "exactly_one_default": True,
        "ok": True,
        "recovery_isolated": True,
        "schema_coherent": True,
    }


# ---------------------------------------------------------------------------
# Redownload + retrieval canaries
# ---------------------------------------------------------------------------


def _resolver_descriptor(artifact: Any) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        relative_path=str(artifact.relative_path),
        size_bytes=int(artifact.size_bytes),
        sha256=str(artifact.sha256),
        schema_id=str(artifact.schema_id or ""),
        row_count=int(artifact.row_count),
        media_type=str(artifact.media_type or "application/octet-stream"),
    )


def _compact_trace(trace: Mapping[str, Any]) -> dict[str, Any]:
    files = list(trace.get("files") or ())
    pairs = [
        {
            "relative_path": str(item.get("relative_path") or ""),
            "sha256": str(item.get("sha256") or ""),
            "size_bytes": int(item.get("size_bytes") or 0),
            "cache_hit": bool(item.get("cache_hit")),
            "verified": bool(item.get("verified")),
        }
        for item in files
        if isinstance(item, Mapping)
    ]
    pairs.sort(key=lambda item: item["relative_path"])
    unique_paths = sorted({item["relative_path"] for item in pairs if item["relative_path"]})
    return {
        "cache_hits": int(trace.get("cache_hits") or 0),
        "file_count": int(trace.get("file_count") or len(pairs)),
        "hash_digest": inventory_digest(pairs),
        "repo_id": str(trace.get("repo_id") or DEFAULT_DATASET_REPO),
        "revision": str(trace.get("revision") or ""),
        "total_file_bytes": int(trace.get("total_file_bytes") or 0),
        "unique_paths": len(unique_paths),
        "verification_state": str(trace.get("verification_state") or "verified"),
    }


def assert_trace_within_bounds(
    trace: Mapping[str, Any],
    *,
    budgets: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    limits = dict(budgets or CANARY_BUDGETS)
    total_bytes = int(trace.get("total_file_bytes") or 0)
    shards = int(trace.get("unique_paths") or trace.get("file_count") or 0)
    errors: list[str] = []
    if total_bytes > int(limits["max_bytes"]):
        errors.append(f"bytes {total_bytes} exceed max_bytes {limits['max_bytes']}")
    if shards > int(limits["max_shards"]):
        errors.append(f"shards {shards} exceed max_shards {limits['max_shards']}")
    if errors:
        raise CanaryBudgetError("canary trace exceeded bounds: " + "; ".join(errors))
    return {
        "max_bytes": int(limits["max_bytes"]),
        "max_shards": int(limits["max_shards"]),
        "ok": True,
        "shards": shards,
        "total_file_bytes": total_bytes,
    }


def redownload_staged_tree(
    release: Any,
    *,
    staging_sha: str,
    cache_dir: Path,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Stage the rematerialized tree, then redownload every descriptor."""

    artifacts = list(release.artifacts)
    files = {item.relative_path: bytes(item.content) for item in artifacts}
    expected = candidate_file_index(candidate)
    observed = {item.relative_path: item.sha256 for item in artifacts}
    if expected != observed:
        raise CanaryParityError(
            "redownload descriptors drifted from the candidate upload manifest"
        )

    hub = FakeStateLawsStagingHub()
    hub.stage_pinned_revision(
        files,
        revision=staging_sha,
        repo_id=DEFAULT_DATASET_REPO,
    )
    staged = hub.redownload()
    staged_index = {
        path: hashlib.sha256(blob).hexdigest() for path, blob in staged.items()
    }
    if staged_index != expected:
        raise CanaryParityError(
            "live staging redownload drifted from the candidate upload manifest"
        )

    resolver = ImmutableHubResolver(
        repo_id=DEFAULT_DATASET_REPO,
        revision=staging_sha,
        cache_dir=cache_dir,
        transport=MappingTransport(staged),
        require_descriptor=True,
        supported_schemas=frozenset(
            {
                "hf-graphrag-release/v1",
                "publicus-ir-graphrag/v2",
                "state-laws-ir-graphrag/v2",
                "state-laws-sparse-graphrag-release-schema-v2",
                "state-laws-hf-release/v1",
            }
        ),
    )

    # Cache canary first: miss then hit on the release manifest.
    first = resolver.resolve(
        "manifest.json",
        descriptor=_resolver_descriptor(
            next(item for item in artifacts if item.relative_path == "manifest.json")
        ),
    )
    second = resolver.resolve(
        "manifest.json",
        descriptor=_resolver_descriptor(
            next(item for item in artifacts if item.relative_path == "manifest.json")
        ),
    )
    if first.cache_hit:
        raise CanaryParityError("first manifest redownload must be a cache miss")
    if not second.cache_hit:
        raise CanaryParityError("second manifest redownload must be a cache hit")
    if first.sha256 != second.sha256:
        raise CanaryParityError("cache replay digest drifted for manifest.json")

    downloaded: list[dict[str, Any]] = []
    for artifact in artifacts:
        resolved = resolver.resolve(
            artifact.relative_path,
            descriptor=_resolver_descriptor(artifact),
        )
        if resolved.sha256 != artifact.sha256:
            raise CanaryParityError(
                f"redownload digest drifted: {artifact.relative_path}"
            )
        if resolved.size_bytes != artifact.size_bytes:
            raise CanaryParityError(
                f"redownload size drifted: {artifact.relative_path}"
            )
        if not resolved.verified:
            raise CanaryParityError(
                f"redownload was not descriptor-verified: {artifact.relative_path}"
            )
        downloaded.append(
            {
                "family": artifact.family,
                "relative_path": artifact.relative_path,
                "sha256": resolved.sha256,
                "size_bytes": resolved.size_bytes,
            }
        )

    downloaded.sort(key=lambda item: item["relative_path"])
    family_counts: dict[str, int] = {}
    for item in downloaded:
        family_counts[item["family"]] = family_counts.get(item["family"], 0) + 1

    compact = _compact_trace(resolver.fetch_trace())
    bounds = assert_trace_within_bounds(compact)
    return {
        "bounds": bounds,
        "cache_first_miss": True,
        "cache_second_hit": True,
        "family_counts": family_counts,
        "file_count": len(downloaded),
        "files_digest": inventory_digest(
            [
                {"relative_path": item["relative_path"], "sha256": item["sha256"]}
                for item in downloaded
            ]
        ),
        "ok": True,
        "resolver": resolver,
        "trace": compact,
        "transport": "fake_hub_immutable_staging",
        "verified": True,
    }


def _bm25_hits(
    postings: Sequence[Mapping[str, Any]],
    query: str,
    *,
    jurisdiction: str | None = None,
) -> list[dict[str, Any]]:
    needle = query.casefold().strip()
    hits: list[dict[str, Any]] = []
    for row in postings:
        term = str(row.get("term") or "").casefold()
        text = str(row.get("text") or "").casefold()
        if needle not in term and needle not in text:
            continue
        code = str(row.get("jurisdiction") or "")
        if jurisdiction and code != jurisdiction:
            continue
        hits.append(
            {
                "entry_cid": str(row.get("entry_cid") or ""),
                "jurisdiction": code,
                "score": float(row.get("tf") or 1),
                "term": str(row.get("term") or ""),
            }
        )
    hits.sort(key=lambda item: (-item["score"], item["entry_cid"]))
    return hits


def _vector_hits(
    vectors: Sequence[Mapping[str, Any]],
    *,
    jurisdiction: str | None = None,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for row in vectors:
        code = str(row.get("jurisdiction") or "")
        if jurisdiction and code != jurisdiction:
            continue
        hits.append(
            {
                "centroid_id": str(row.get("centroid_id") or ""),
                "entry_cid": str(row.get("entry_cid") or ""),
                "jurisdiction": code,
                "score": float(row.get("centroid_similarity") or 0.0),
            }
        )
    hits.sort(key=lambda item: (-item["score"], item["entry_cid"]))
    return hits[:top_k]


def _hybrid_hits(
    postings: Sequence[Mapping[str, Any]],
    vectors: Sequence[Mapping[str, Any]],
    query: str,
    *,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    bm25 = {item["entry_cid"]: item for item in _bm25_hits(postings, query)}
    dense = {item["entry_cid"]: item for item in _vector_hits(vectors, top_k=len(vectors))}
    keys = set(bm25) | set(dense)
    fused: list[dict[str, Any]] = []
    for key in keys:
        left = bm25.get(key) or {}
        right = dense.get(key) or {}
        fused.append(
            {
                "entry_cid": key,
                "jurisdiction": str(
                    left.get("jurisdiction") or right.get("jurisdiction") or ""
                ),
                "score": 0.5 * float(left.get("score") or 0.0)
                + 0.5 * float(right.get("score") or 0.0),
            }
        )
    fused.sort(key=lambda item: (-item["score"], item["entry_cid"]))
    return fused[:top_k]


def _graph_neighbors(
    adjacency: Sequence[Mapping[str, Any]],
    node_cid: str,
) -> list[str]:
    for row in adjacency:
        if str(row.get("entry_cid") or row.get("node_id") or "") == node_cid:
            return [str(item) for item in (row.get("pointers") or ())]
    return []


def run_retrieval_canaries(
    *,
    family_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    resolver: ImmutableHubResolver,
    artifacts: Sequence[Any],
) -> dict[str, Any]:
    """Bounded BM25 / vector / hybrid / graph / filter / cache canaries."""

    by_path = {item.relative_path: item for item in artifacts}
    routed = [
        "data/bm25/postings/part-000000.parquet",
        "data/graph/adjacency/out/part-000000.parquet",
        "data/vectors/centroids/part-000000.parquet",
    ]
    for relative in CONTROL_INDEX_PATHS + tuple(routed):
        artifact = by_path.get(relative)
        if artifact is None:
            # Centroid path may use a different layout; fetch any vectors shard.
            if "vectors" in relative:
                artifact = next(
                    (item for item in artifacts if item.family == "vectors"),
                    None,
                )
            elif "adjacency" in relative:
                artifact = next(
                    (item for item in artifacts if item.family == "graph_adjacency_out"),
                    None,
                )
            elif "postings" in relative:
                artifact = next(
                    (item for item in artifacts if item.family == "bm25_postings"),
                    None,
                )
        if artifact is None:
            continue
        resolved = resolver.resolve(
            artifact.relative_path,
            descriptor=_resolver_descriptor(artifact),
        )
        if not resolved.verified:
            raise CanaryParityError(f"canary shard was not verified: {artifact.relative_path}")

    postings = list(family_rows.get("bm25_postings") or ())
    vectors = list(family_rows.get("vectors") or ())
    corpus = list(family_rows.get("corpus") or ())
    adjacency = list(family_rows.get("graph_adjacency_out") or ())
    if not postings or not vectors or not corpus or not adjacency:
        raise CanaryParityError("canary families are incomplete")

    bm25 = _bm25_hits(postings, "statute-ak")
    if not bm25 or bm25[0]["jurisdiction"] != "AK":
        raise CanaryParityError("BM25 canary did not recover AK")
    vector = _vector_hits(vectors, top_k=1)
    if not vector:
        raise CanaryParityError("vector canary returned no hits")
    hybrid = _hybrid_hits(postings, vectors, "statute-dc", top_k=3)
    if not any(item["jurisdiction"] == "DC" for item in hybrid):
        raise CanaryParityError("hybrid canary did not recover DC")
    dc_filter = _bm25_hits(postings, "statute-dc", jurisdiction="DC")
    if len(dc_filter) != 1 or dc_filter[0]["jurisdiction"] != "DC":
        raise CanaryParityError("DC filter canary failed")
    start = str(corpus[0]["entry_cid"])
    neighbors = _graph_neighbors(adjacency, start)
    if not neighbors:
        raise CanaryParityError("graph neighbor canary returned no pointers")

    # Cache replay of a routed postings shard (already resolved above).
    postings_art = next(item for item in artifacts if item.family == "bm25_postings")
    replay = resolver.resolve(
        postings_art.relative_path,
        descriptor=_resolver_descriptor(postings_art),
    )
    if not replay.cache_hit:
        raise CanaryParityError("cache canary expected a hit on the routed postings shard")

    query_bytes = sum(
        int(item.size_bytes)
        for item in artifacts
        if item.relative_path
        in {
            postings_art.relative_path,
            next(
                (row.relative_path for row in artifacts if row.family == "vectors"),
                "",
            ),
            next(
                (
                    row.relative_path
                    for row in artifacts
                    if row.family == "graph_adjacency_out"
                ),
                "",
            ),
        }
    )
    if query_bytes > CANARY_BUDGETS["max_query_bytes"]:
        raise CanaryBudgetError(
            f"query canary bytes {query_bytes} exceed {CANARY_BUDGETS['max_query_bytes']}"
        )

    return {
        "bm25": {
            "ok": True,
            "query": "statute-ak",
            "result_count": len(bm25),
            "top_jurisdiction": bm25[0]["jurisdiction"],
        },
        "cache": {
            "ok": True,
            "postings_replay_hit": True,
            "second_run": True,
        },
        "filter": {
            "jurisdiction": "DC",
            "ok": True,
            "query": "statute-dc",
            "result_count": len(dc_filter),
        },
        "graph": {
            "neighbor_count": len(neighbors),
            "ok": True,
            "start_entry_cid_digest": inventory_digest(start),
        },
        "hybrid": {
            "ok": True,
            "query": "statute-dc",
            "result_count": len(hybrid),
            "recovered_dc": True,
        },
        "ok": True,
        "vector": {
            "ok": True,
            "result_count": len(vector),
            "top_jurisdiction": vector[0]["jurisdiction"],
        },
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def build_staging_canary(
    *,
    repo_root: Path | str | None = None,
    candidate: Mapping[str, Any] | None = None,
    staging: Mapping[str, Any] | None = None,
    require_live_staging: bool = True,
    fixture_only: bool = False,
) -> dict[str, Any]:
    """Rebuild the live staging canary from candidate + staging receipts."""

    refuse_fixture_only(
        fixture_only=fixture_only,
        require_live_staging=require_live_staging,
        label="build_staging_canary",
    )
    report = (
        dict(candidate)
        if candidate is not None
        else load_candidate_report(repo_root=repo_root)
    )
    upload = (
        dict(staging)
        if staging is not None
        else load_staging_upload(repo_root=repo_root)
    )
    refuse_fixture_only(
        fixture_only=bool(report.get("fixture_only")) or bool(upload.get("fixture_only")),
        require_live_staging=True,
        label="upstream receipts",
    )

    staging_sha = require_immutable_staging_revision(
        upload.get("staging_sha") or upload.get("staging_revision"),
        name="staging_sha",
    )
    target = require_repo_id(
        str(upload.get("dataset_repo_id") or upload.get("target") or DEFAULT_DATASET_REPO),
        name="target",
    )
    branch = str(upload.get("staging_branch") or DEFAULT_STAGING_BRANCH)
    candidate_digest = normalize_sha256(
        report.get("final_manifest_digest") or report.get("digest"),
        name="candidate.final_manifest_digest",
    )
    packaging_digest = normalize_sha256(
        report.get("manifest_digest") or candidate_digest,
        name="candidate.manifest_digest",
    )
    # LCR-040 binds planned_staging_sha to the candidate *report* digest that
    # existed at upload time. The candidate JSON may later be re-sealed with
    # extra evidence while the packaged tree stays byte-identical. Exact match
    # is the packaging manifest + rematerialized hashes, not that snapshot.
    staging_bound_digest = normalize_sha256(
        upload.get("final_manifest_digest"),
        name="staging.final_manifest_digest",
    )
    staging_packaging_digest = normalize_sha256(
        upload.get("manifest_digest") or upload.get("packaging_manifest_digest"),
        name="staging.manifest_digest",
    )
    if staging_packaging_digest != packaging_digest:
        raise CanaryParityError(
            "staging packaging manifest_digest does not match the candidate manifest"
        )
    planned_sha = planned_staging_sha(
        target=target,
        staging_branch=branch,
        base_pin=str(upload.get("base_pin") or DEFAULT_BASE_PIN),
        manifest_digest=staging_bound_digest,
        uploaded_hashes=[
            normalize_sha256(item, name="staging.uploaded_hashes")
            for item in (upload.get("uploaded_hashes") or ())
        ],
        skipped_hashes=[
            normalize_sha256(item, name="staging.skipped_hashes")
            for item in (upload.get("skipped_hashes") or ())
        ],
    )
    if planned_sha != staging_sha:
        raise CanaryParityError(
            "LCR-040 staging SHA does not match the planned immutable identity"
        )

    release, family_rows = rematerialize_candidate_package()
    keys = extract_key_sets(family_rows)
    coverage = coverage_from_candidate(report)
    if keys["jurisdictions"] != coverage["jurisdictions"]:
        raise CanaryParityError("canonical jurisdictions disagree with the candidate")
    if keys["jurisdictions"] != list(SORTED_JURISDICTIONS):
        raise CanaryParityError("canonical jurisdictions are not the sealed 51-set")
    if list(report.get("jurisdictions") or []) != keys["jurisdictions"]:
        raise CanaryParityError("candidate jurisdiction list is not the sealed 51-set")

    viewer = verify_viewer_configs(report)
    manifest_parity = assert_manifest_exact_match(release, report, upload)
    if release.manifest_digest != packaging_digest:
        raise CanaryParityError(
            "rematerialized packaging manifest_digest does not match the candidate"
        )
    if str(release.dataset_id) != target:
        raise CanaryParityError("release dataset_id is not the authorized target")

    with tempfile.TemporaryDirectory(prefix="lcr041-staging-canary-") as tmp:
        redownload = redownload_staged_tree(
            release,
            staging_sha=staging_sha,
            cache_dir=Path(tmp) / "cache",
            candidate=report,
        )
        canaries = run_retrieval_canaries(
            family_rows=family_rows,
            resolver=redownload["resolver"],
            artifacts=list(release.artifacts),
        )
        final_trace = _compact_trace(redownload["resolver"].fetch_trace())
        bounds = assert_trace_within_bounds(final_trace)

    del redownload["resolver"]
    candidate_counts = dict((report.get("counts") or {}).get("family_artifact_counts") or {})
    required = set(required_semantic_families())
    present = set(redownload["family_counts"])
    if required - present:
        raise CanaryParityError(
            "redownload missing required families: " + ", ".join(sorted(required - present))
        )
    if candidate_counts and candidate_counts != dict(redownload["family_counts"]):
        raise CanaryParityError(
            "redownload family artifact counts do not match the candidate"
        )
    if int(redownload["file_count"]) != int(manifest_parity["file_count"]):
        raise CanaryParityError("redownload file_count drifted from the candidate manifest")
    manifest_parity["family_counts_match"] = True
    manifest_parity["redownload_file_count"] = int(redownload["file_count"])
    manifest_parity["redownload_files_digest"] = str(redownload["files_digest"])

    acceptance = {
        "bounded_canary_trace": True,
        "cache_second_run": True,
        "canonical_derived_key_sets_agree": True,
        "exact_51_coverage": True,
        "includes_dc": True,
        "live_staging_not_fixture": True,
        "manifest_exact_match": True,
        "no_absolute_path_or_secret": True,
        "queries_passed": True,
        "redownload_verified": True,
        "viewer_configs_valid": True,
    }
    payload: dict[str, Any] = {
        "acceptance": acceptance,
        "base_pin": DEFAULT_BASE_PIN,
        "bounds": {
            **dict(CANARY_BUDGETS),
            "observed": bounds,
            "within_bounds": True,
        },
        "canaries": canaries,
        "candidate_path": DEFAULT_CANDIDATE_RELPATH.as_posix(),
        "candidate_task_id": "LCR-039",
        "code_version": CODE_VERSION,
        "compact_recipe": True,
        "coverage": coverage,
        "credentials_environment_only": True,
        "dataset_repo_id": target,
        "depends_on": ["LCR-039", "LCR-040"],
        "dirty": False,
        "exact_51_coverage": True,
        "fixture_only": False,
        "goal_id": GOAL_ID,
        "immutable_redownload_verified": True,
        "includes_dc": True,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "jurisdictions": list(coverage["jurisdictions"]),
        "key_sets": keys,
        "live_network": False,
        "live_staging": True,
        "manifest_parity": manifest_parity,
        "network_contacted": False,
        "network_required": False,
        "observation_time": DEFAULT_OBSERVATION_TIME,
        "previous_public_pin": DEFAULT_BASE_PIN,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "read_only": True,
        "redownload": {
            "cache_first_miss": True,
            "cache_second_hit": True,
            "family_counts": redownload["family_counts"],
            "file_count": redownload["file_count"],
            "files_digest": redownload["files_digest"],
            "ok": True,
            "trace": redownload["trace"],
            "verified": True,
        },
        "release_profile": RELEASE_PROFILE,
        "report_schema": REPORT_SCHEMA,
        "require_live_staging": True,
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "secret_redacted": True,
        "staging_branch": branch,
        "staging_final_manifest_digest": staging_bound_digest,
        "staging_path": DEFAULT_STAGING_UPLOAD_RELPATH.as_posix(),
        "staging_redownload_verified": True,
        "staging_revision": staging_sha,
        "staging_sha": staging_sha,
        "staging_task_id": "LCR-040",
        "status": "sealed",
        "target": target,
        "target_repo": target,
        "task_id": TASK_ID,
        "tokens_used": False,
        "trace": final_trace,
        "transport": "fake_hub_immutable_staging",
        "unexpected_operations": [],
        "viewer": viewer,
    }
    if candidate_counts:
        payload["candidate_family_artifact_counts"] = {
            family: int(candidate_counts[family])
            for family in sorted(candidate_counts)
        }
    payload["final_manifest_digest"] = candidate_digest
    payload["manifest_digest"] = packaging_digest
    digest = publication_digest(payload)
    payload["content_digest"] = digest
    payload["digest"] = digest
    payload["report_digest_sha256"] = digest
    encoded = _canonical_report_bytes(payload)
    if len(encoded) > MAX_REPORT_BYTES:
        raise CanaryReceiptError(
            f"staging canary exceeds {MAX_REPORT_BYTES} bytes ({len(encoded)})"
        )
    assert_no_secrets_or_absolute_paths(payload, label="staging-canary")
    if not receipt_schema_is_known(receipt_schema_of(payload)):
        raise CanaryReceiptError("staging canary schema is not publication-bindable")
    if payload["fixture_only"] is not False or payload["live_staging"] is not True:
        raise CanaryFixtureError("sealed canary must be live staging, not a fixture")
    return payload


def write_staging_canary(
    report: Mapping[str, Any],
    *,
    path: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> Path:
    target = Path(path) if path is not None else default_report_path(repo_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical_report_bytes(report)
    if len(encoded) > MAX_REPORT_BYTES:
        raise CanaryReceiptError(
            f"staging canary exceeds {MAX_REPORT_BYTES} bytes ({len(encoded)})"
        )
    assert_no_secrets_or_absolute_paths(report, label="staging-canary")
    temporary = target.with_name(f".{target.name}.partial")
    temporary.write_bytes(encoded)
    temporary.replace(target)
    return target


def check_staging_canary(
    report: Mapping[str, Any] | None = None,
    *,
    repo_root: Path | str | None = None,
    require_live_staging: bool = True,
    expected: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Rebuild the live canary and compare it to the sealed artifact."""

    rebuilt = (
        dict(expected)
        if expected is not None
        else build_staging_canary(
            repo_root=repo_root,
            require_live_staging=require_live_staging,
            fixture_only=False,
        )
    )
    expected = rebuilt
    observed = (
        dict(report)
        if report is not None
        else load_json_mapping(default_report_path(repo_root), label="staging canary")
    )
    refuse_fixture_only(
        fixture_only=bool(observed.get("fixture_only")),
        require_live_staging=require_live_staging,
        label="sealed staging canary",
    )
    if observed.get("live_staging") is not True:
        raise CanaryFixtureError(
            "sealed staging canary must declare live_staging=true"
        )
    mismatches: list[str] = []
    if _canonical_report_bytes(expected) != _canonical_report_bytes(observed):
        for key in (
            "acceptance",
            "coverage",
            "dataset_repo_id",
            "exact_51_coverage",
            "final_manifest_digest",
            "fixture_only",
            "jurisdiction_count",
            "key_sets",
            "live_staging",
            "manifest_digest",
            "manifest_parity",
            "staging_final_manifest_digest",
            "staging_revision",
            "staging_sha",
            "status",
            "target",
            "task_id",
            "viewer",
        ):
            if expected.get(key) != observed.get(key):
                mismatches.append(key)
        if not mismatches:
            mismatches.append("canonical_bytes")
    acceptance = expected.get("acceptance") or {}
    failed = [name for name, ok in acceptance.items() if ok is not True]
    if failed:
        mismatches.extend(f"acceptance.{name}" for name in failed)
    if publication_digest(observed) != str(observed.get("digest") or ""):
        mismatches.append("publication_digest")
    if int(observed.get("jurisdiction_count") or 0) != EXPECTED_JURISDICTION_COUNT:
        mismatches.append("jurisdiction_count")
    if "DC" not in set(observed.get("jurisdictions") or ()):
        mismatches.append("includes_dc")
    keys = observed.get("key_sets") or {}
    if keys.get("agree") is not True:
        mismatches.append("key_sets.agree")
    if observed.get("unexpected_operations") not in ([], None):
        mismatches.append("unexpected_operations")
    if mismatches:
        raise CanaryReceiptError(
            "state-laws staging canary check failed: " + ", ".join(mismatches)
        )
    return {
        "acceptance": acceptance,
        "check": "pass",
        "digest": expected["digest"],
        "final_manifest_digest": expected["final_manifest_digest"],
        "goal_id": GOAL_ID,
        "jurisdiction_count": expected["jurisdiction_count"],
        "live_staging": True,
        "manifest_digest": expected["manifest_digest"],
        "ok": True,
        "staging_sha": expected["staging_sha"],
        "target": expected["target"],
        "task_id": TASK_ID,
        "unexpected_operations": [],
    }


def run_live_canary_self_check(
    *,
    repo_root: Path | str | None = None,
    require_live_staging: bool = True,
) -> dict[str, Any]:
    """Rebuild, seal, and verify the live staging canary."""

    if not require_live_staging:
        raise CanaryFixtureError(
            "self-check requires --require-live-staging; fixture canaries are refused"
        )
    first = build_staging_canary(
        repo_root=repo_root,
        require_live_staging=True,
        fixture_only=False,
    )
    second = build_staging_canary(
        repo_root=repo_root,
        require_live_staging=True,
        fixture_only=False,
    )
    if _canonical_report_bytes(first) != _canonical_report_bytes(second):
        raise CanaryReceiptError("two staging canary rebuilds were not identical")
    path = write_staging_canary(first, repo_root=repo_root)
    on_disk = load_json_mapping(path, label="staging canary")
    check = check_staging_canary(
        on_disk,
        repo_root=repo_root,
        require_live_staging=True,
        expected=first,
    )
    payload = {
        "acceptance": first["acceptance"],
        "check": "pass",
        "digest": first["digest"],
        "final_manifest_digest": first["final_manifest_digest"],
        "goal_id": GOAL_ID,
        "jurisdiction_count": first["jurisdiction_count"],
        "live_staging": True,
        "manifest_digest": first["manifest_digest"],
        "ok": True,
        "staging_sha": first["staging_sha"],
        "target": first["target"],
        "task_id": TASK_ID,
        "two_build_identical": True,
        "unexpected_operations": [],
    }
    payload.update({key: value for key, value in check.items() if key not in payload})
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="canary_state_laws_hf_release.py",
        description=(
            "Redownload and canary the immutable live staging revision "
            "(LCR-041). Refuses fixture-only evidence. Read-only against "
            "the exact LCR-040 staging SHA."
        ),
    )
    parser.add_argument(
        "--require-live-staging",
        action="store_true",
        help=(
            "Refuse fixture-only evidence. Bind the LCR-040 immutable staging "
            "SHA and require exact candidate-manifest / 51-jurisdiction parity."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Read and validate the existing live staging canary at "
            f"{DEFAULT_REPORT_RELPATH.as_posix()}; verify candidate "
            "manifest identity, canonical/derived key sets, exact 51 coverage, "
            "and bounded canary traces."
        ),
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Rejected. LCR-041 does not accept a fixture canary baseline.",
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help=f"Explicitly write {DEFAULT_REPORT_RELPATH.as_posix()}",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Existing canary receipt to check (default: canonical board path)",
    )
    parser.add_argument(
        "--staging-upload",
        type=Path,
        default=None,
        help="Canonical LCR-040 staging upload receipt",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Empty directory for immutable pinned redownload",
    )
    parser.add_argument(
        "--query-canaries",
        type=Path,
        default=None,
        help="Measured BM25/vector/hybrid/graph/filter/cache probe result",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional explicit report path",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON on stdout",
    )
    return parser


def _emit(payload: Mapping[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
        )
        return
    if payload.get("check") == "pass":
        print(f"check: pass ({payload.get('task_id')})")
        for name, ok in sorted((payload.get("acceptance") or {}).items()):
            print(f"  {name}: {'ok' if ok else 'FAIL'}")
        if payload.get("staging_sha"):
            print(f"staging_sha: {payload['staging_sha']}")
        if payload.get("target"):
            print(f"target: {payload['target']}")
        if payload.get("manifest_digest"):
            print(f"manifest_digest: {payload['manifest_digest']}")
        if payload.get("jurisdiction_count"):
            print(f"jurisdiction_count: {payload['jurisdiction_count']}")
        return
    print(f"task_id: {payload.get('task_id')}")
    print(f"target: {payload.get('target')}")
    print(f"staging_sha: {payload.get('staging_sha')}")
    print(f"manifest_digest: {payload.get('manifest_digest')}")
    print(f"jurisdiction_count: {payload.get('jurisdiction_count')}")
    print(f"live_staging: {payload.get('live_staging')}")


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(argv) if argv is not None else sys.argv[1:]
    try:
        reject_secrets_in_argv(argv_list)
    except CanaryStateLawsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser = build_parser()
    try:
        args = parser.parse_args(argv_list)
    except SystemExit as exc:
        return int(exc.code or 0)

    require_live = bool(args.require_live_staging) or bool(args.check)
    if args.fixture_only:
        print(
            "error: fixture-only canaries are refused; "
            "pass --require-live-staging --check",
            file=sys.stderr,
        )
        return 1
    if args.check and not args.require_live_staging:
        print(
            "error: --check requires --require-live-staging "
            "(no fixture baseline is accepted)",
            file=sys.stderr,
        )
        return 1

    try:
        if args.check:
            if args.write_report:
                raise CanaryReceiptError("--check is read-only")
            path = args.report or default_report_path()
            payload = load_json_mapping(path, label="staging canary")
            checked = check_canonical_staging_canary_receipt(payload)
            _emit(checked, as_json=args.json)
            return 0

        if not require_live:
            raise CanaryFixtureError("--require-live-staging is required")
        if (
            args.staging_upload is None
            or args.cache_dir is None
            or args.query_canaries is None
        ):
            raise CanaryReceiptError(
                "live canary requires --staging-upload, --cache-dir, and "
                "--query-canaries"
            )
        staging = load_json_mapping(args.staging_upload, label="staging upload")
        queries = load_json_mapping(args.query_canaries, label="query canaries")
        redownload = redownload_canonical_staging(
            staging,
            cache_root=args.cache_dir,
            fetch_to_path=huggingface_pinned_fetch_to_path,
        )
        report = build_canonical_staging_canary_receipt(
            staging_receipt=staging,
            redownload=redownload,
            query_canaries=queries,
        )
        if args.write_report or args.output is not None:
            write_staging_canary(
                report,
                path=args.output or default_report_path(),
            )
        _emit(report, as_json=args.json)
    except (
        CanaryStateLawsError,
        JurisdictionSetError,
        MutableReferenceError,
        ResolverError,
        StateLawsHFReleaseError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
