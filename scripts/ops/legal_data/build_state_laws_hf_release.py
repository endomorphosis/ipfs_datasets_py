#!/usr/bin/env python3
"""Assemble the exact-51 state-law Hugging Face release candidate (LCR-039).

Consumes the LCR-038 local e2e software contract and the LCR-032 additive
assembler. Writes a descriptor-complete candidate evidence root. Fixture-only
default. No Hub upload. Unknown or prohibited rights cannot enter the default
release.

Validation gate::

    python scripts/ops/legal_data/build_state_laws_hf_release.py --check

``--check`` re-assembles the compact exact-51 candidate and validates the
frozen ``release_candidate.json`` without rewriting it. ``--write`` is the
only flag that materializes the receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import pwd
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

# Pin the repository's regular ``scripts`` package before the sealed
# dependency directory is prepended below.  Some validation environments also
# ship a top-level package with this name; allowing it to populate
# ``sys.modules`` first makes literal script execution resolve the wrong
# ``scripts.ops.legal_data`` namespace.
import scripts as _repository_scripts_package  # noqa: E402
from scripts import ops as _repository_scripts_ops_package  # noqa: E402

if (
    Path(str(getattr(_repository_scripts_package, "__file__", ""))).resolve()
    != (REPOSITORY_ROOT / "scripts/__init__.py").resolve()
    or Path(
        str(getattr(_repository_scripts_ops_package, "__file__", ""))
    ).resolve()
    != (REPOSITORY_ROOT / "scripts/ops/__init__.py").resolve()
):
    raise ImportError("repository scripts package identity is shadowed")

_SEALED_VALIDATION_SITE_PACKAGES = Path(
    "/opt/ipfs-accelerate-legal-validation-7ffe92439767/site-packages"
)
if _SEALED_VALIDATION_SITE_PACKAGES.is_dir():
    _sealed_site = str(_SEALED_VALIDATION_SITE_PACKAGES)
    if _sealed_site not in sys.path:
        # Repository code is the verifier authority.  The sealed directory
        # supplies third-party dependencies only and must never shadow the
        # detached repository source root selected by the caller.
        sys.path.insert(1, _sealed_site)

from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    CANONICAL_JURISDICTION_ORDER,
    EXPECTED_JURISDICTION_COUNT,
)
from ipfs_datasets_py.processors.legal_data.state_laws_corpus import (
    assert_no_secrets_or_home_paths,
)
from ipfs_datasets_py.processors.legal_data.state_laws_corpus_physical import (
    CORPUS_DATA_DIR,
    CORPUS_ROW_SCHEMA_VERSION,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embeddings import (
    write_json_atomic,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (
    DEFAULT_CONFIG_NAME,
    DEFAULT_DATASET_REPO_ID,
    LEGACY_CONFIG_NAME,
    LINEAGE_REPORT_PATH,
    PREVIOUS_PUBLIC_PIN,
    QUARANTINE_CONFIG_NAME,
    RECOVERY_CONFIG_NAME,
    RELEASE_PROFILE,
    REQUIRED_MANIFEST_BINDINGS,
    SOURCE_RIGHTS_RECEIPT_RELPATH,
    assemble_state_laws_hf_release,
    fixture_legacy_files,
    fixture_source_receipts,
    load_source_rights_receipt,
    validate_state_laws_hf_release,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (
    GOAL_ID as ASSEMBLER_GOAL_ID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (
    SCHEMA_VERSION as ASSEMBLER_SCHEMA_VERSION,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (
    TASK_ID as ASSEMBLER_TASK_ID,
)
from ipfs_datasets_py.processors.legal_data.state_laws_local_release import (
    verify_state_laws_local_release_manifest,
)
from ipfs_datasets_py.processors.legal_data.state_laws_legacy_v2_adapter import (
    LegacyInputError,
    _canonical_source_identity,
    _merge_legacy_row,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    content_sha256,
    example_corpus_payload,
)
from scripts.ops.legal_data import (
    audit_legal_corpora_live_baseline as live_baseline_audit,
)
from scripts.ops.legal_data import (
    run_state_laws_production_release as production_runner,
)


def _load_repository_mutation_audit_module() -> Any:
    """Load this checkout's audit even when sealed deps shadow ``scripts``."""

    module_name = "_lcr084_repository_mutation_path_audit"
    source_path = (
        REPOSITORY_ROOT
        / "scripts/ops/legal_data/"
        "audit_legal_corpora_hugging_face_mutation_paths.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load repository mutation audit: {source_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    if Path(str(getattr(module, "__file__", ""))).resolve() != source_path.resolve():
        raise ImportError("repository mutation audit resolved to a shadow module")
    return module


mutation_path_audit = _load_repository_mutation_audit_module()

SCHEMA_VERSION: Final = "state-laws-release-candidate-v1"
REPORT_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-reindex-release-candidate@1"
PRODUCTION_REPORT_SCHEMA: Final = (
    "ipfs_datasets_py/legal-corpora-reindex-release-candidate@2"
)
PRODUCTION_SCHEMA_VERSION: Final = "state-laws-release-candidate-v2"
PRODUCTION_TASK_ID: Final = "LCR-084"
PRODUCTION_GOAL_ID: Final = "LCR-G146"
PRODUCTION_KIND: Final = "exact-51-live-official-local-production"
BASELINE_SOURCE_IDENTITY_CLOSURE_SCHEMA: Final = (
    "state-laws-baseline-source-identity-multiset-v1"
)
PRODUCTION_ACCEPTANCE_SCHEMA: Final = (
    "ipfs_datasets_py/state-laws-full-scrape-acceptance@2"
)
TASK_ID: Final = "LCR-039"
GOAL_ID: Final = "LCR-G070"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "build_state_laws_hf_release.py"
BOARD_NAMESPACE: Final = "legal-corpora-reindex-v1"
BUNDLE: Final = "release-candidate"
CODE_VERSION: Final = "1"
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True
AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_RELEASE: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
DEFAULT_REPORT_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/release_candidate.json"
)
PRODUCTION_ACCEPTANCE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/full_scrape_acceptance.json"
)
PRODUCTION_MUTATION_AUDIT_RELPATH: Final = mutation_path_audit.REPORT_RELPATH
DEFAULT_LIVE_BASELINE_RELPATH: Final = Path(
    "docs/reports/legal_corpora_reindex/live_baseline_provenance_receipt.json"
)
LOCAL_E2E_RELPATH: Final = Path("docs/reports/legal_corpora_reindex/local_e2e.json")
REQUIRED_FAMILIES: Final = (
    "corpus",
    "bm25",
    "vectors",
    "centroids",
    "vector_locator",
    "graph",
    "two_way_adjacency",
    "source_receipts",
)
ACCEPTANCE_CRITERIA: Final = (
    "Candidate is byte/descriptor complete, has no stale model/revision/canary "
    "values, contains exact 51 coverage and required semantic families, and is "
    "ready for transactional staging. The compact receipt does not authorize "
    "Hub upload or publication."
)
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")
PRODUCTION_MAX_EVIDENCE_AGE: Final = timedelta(days=30)
PRODUCTION_MAX_EVIDENCE_AGE_SECONDS: Final = int(
    PRODUCTION_MAX_EVIDENCE_AGE.total_seconds()
)
_RETAINED_REPLAY_TIMEOUT_SECONDS: Final = 2 * 60 * 60
_RETAINED_REPLAY_OUTPUT_LIMIT_BYTES: Final = 32 * 1024 * 1024


class CandidateError(RuntimeError):
    """Fail-closed release-candidate error."""


def _lexical_absolute(path: Path | str, *, base: Path | None = None) -> Path:
    """Return an absolute lexical path without erasing symlink identity."""

    selected = Path(path).expanduser()
    if not selected.is_absolute():
        selected = (base or Path.cwd()) / selected
    return selected.absolute()


@contextmanager
def _open_regular_file_nofollow(
    path: Path | str, *, label: str
) -> Iterator[BinaryIO]:
    """Open one file through no-follow dirfds and pin its inode while in use."""

    selected = _lexical_absolute(path)
    parts = selected.parts
    if len(parts) < 2 or parts[0] != selected.anchor or not parts[-1]:
        raise CandidateError(f"{label} must be an absolute regular-file path")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    directory_fd = -1
    directory_fds: list[int] = []
    directory_identities: list[tuple[int, int]] = []
    file_fd = -1
    handle: BinaryIO | None = None
    try:
        directory_fd = os.open(selected.anchor, directory_flags)
        directory_fds.append(directory_fd)
        root_stat = os.fstat(directory_fd)
        directory_identities.append((root_stat.st_dev, root_stat.st_ino))
        for component in parts[1:-1]:
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            directory_fd = next_fd
            directory_fds.append(directory_fd)
            component_stat = os.fstat(directory_fd)
            directory_identities.append(
                (component_stat.st_dev, component_stat.st_ino)
            )
        file_fd = os.open(parts[-1], file_flags, dir_fd=directory_fd)
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            raise CandidateError(f"{label} must be a regular file: {selected}")
        handle = os.fdopen(file_fd, "rb", closefd=True)
        file_fd = -1
        yield handle
        after = os.fstat(handle.fileno())
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(getattr(before, name) != getattr(after, name) for name in stable_fields):
            raise CandidateError(f"{label} changed while it was being verified")
        # Reopen the same lexical name through a fresh no-follow chain.  This
        # catches a parent-directory rename/replacement while the original fd
        # remained pinned and therefore unchanged.
        reopened_directories: list[int] = []
        reopened_file = -1
        try:
            reopened_directory = os.open(selected.anchor, directory_flags)
            reopened_directories.append(reopened_directory)
            reopened_root = os.fstat(reopened_directory)
            if (reopened_root.st_dev, reopened_root.st_ino) != directory_identities[0]:
                raise CandidateError(
                    f"{label} directory path was replaced while it was being verified"
                )
            for component_index, component in enumerate(parts[1:-1], start=1):
                reopened_directory = os.open(
                    component, directory_flags, dir_fd=reopened_directory
                )
                reopened_directories.append(reopened_directory)
                reopened_component = os.fstat(reopened_directory)
                if (
                    reopened_component.st_dev,
                    reopened_component.st_ino,
                ) != directory_identities[component_index]:
                    raise CandidateError(
                        f"{label} directory path was replaced while it was being verified"
                    )
            reopened_file = os.open(
                parts[-1], file_flags, dir_fd=reopened_directories[-1]
            )
            reopened = os.fstat(reopened_file)
            if (
                reopened.st_dev != before.st_dev
                or reopened.st_ino != before.st_ino
                or not stat.S_ISREG(reopened.st_mode)
            ):
                raise CandidateError(
                    f"{label} pathname was replaced while it was being verified"
                )
        finally:
            if reopened_file >= 0:
                os.close(reopened_file)
            for reopened_directory in reversed(reopened_directories):
                os.close(reopened_directory)
    except CandidateError:
        raise
    except (OSError, UnicodeError) as exc:
        raise CandidateError(f"{label} is missing, unsafe, or unreadable: {selected}") from exc
    finally:
        if handle is not None:
            handle.close()
        elif file_fd >= 0:
            os.close(file_fd)
        for pinned_directory in reversed(directory_fds):
            os.close(pinned_directory)


def read_regular_file_bytes(path: Path | str, *, label: str) -> bytes:
    """Read exact bytes from a no-follow, inode-pinned regular file."""

    with _open_regular_file_nofollow(path, label=label) as handle:
        return handle.read()


def _safe_existing_directory(path: Path | str, *, label: str) -> Path:
    """Resolve a directory only after rejecting every lexical symlink component."""

    selected = _lexical_absolute(path)
    try:
        cursor = Path(selected.anchor)
        for component in selected.parts[1:]:
            cursor /= component
            if cursor.is_symlink():
                raise CandidateError(f"{label} must not traverse a symlink: {cursor}")
        resolved = selected.resolve(strict=True)
    except CandidateError:
        raise
    except OSError as exc:
        raise CandidateError(f"{label} does not exist: {selected}") from exc
    if not resolved.is_dir():
        raise CandidateError(f"{label} must be a directory: {resolved}")
    return resolved


def _require_canonical_repo_path(
    path: Path | str,
    *,
    repo_root: Path,
    relative_path: Path,
    label: str,
    must_exist: bool,
) -> Path:
    """Require exact lexical identity to one canonical repository path."""

    root = _safe_existing_directory(repo_root, label="repository root")
    expected = _lexical_absolute(root / relative_path)
    selected = _lexical_absolute(path, base=root)
    if selected != expected:
        raise CandidateError(
            f"{label} must be the canonical path {relative_path.as_posix()!r}"
        )
    if must_exist:
        return resolve_evidence_path(
            str(selected), repo_root=root, label=label
        )
    parent = _safe_existing_directory(selected.parent, label=f"{label} parent")
    if parent != expected.parent:
        raise CandidateError(f"{label} parent path identity drifted")
    if selected.exists() or selected.is_symlink():
        with _open_regular_file_nofollow(selected, label=label):
            pass
    return selected


def default_report_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return root / DEFAULT_REPORT_RELPATH


def _json_value_without_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise CandidateError(f"production JSON contains duplicate key {key!r}")
        payload[key] = value
    return payload


def load_json_value_bytes(
    serialized: bytes, *, label: str = "production JSON"
) -> Any:
    """Parse one captured UTF-8 JSON snapshot, rejecting duplicate keys."""

    try:
        return json.loads(
            serialized.decode("utf-8", errors="strict"),
            object_pairs_hook=_json_value_without_duplicate_keys,
        )
    except CandidateError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateError(f"{label} is not strict UTF-8 JSON") from exc


def load_json_mapping_bytes(
    serialized: bytes, *, label: str = "production JSON object"
) -> dict[str, Any]:
    """Parse one captured JSON-object snapshot without reopening its path."""

    payload = load_json_value_bytes(serialized, label=label)
    if not isinstance(payload, dict):
        raise CandidateError(f"{label} must be a JSON object")
    return payload


def iter_json_lines_mappings_bytes(
    serialized: bytes, *, label: str
) -> Iterator[dict[str, Any]]:
    """Yield strict JSON-Lines objects from one retained byte snapshot."""

    line_number = 0
    row_count = 0
    start = 0
    while start <= len(serialized):
        line_number += 1
        newline = serialized.find(b"\n", start)
        if newline < 0:
            line = serialized[start:]
            start = len(serialized) + 1
        else:
            line = serialized[start:newline]
            start = newline + 1
        if not line.strip():
            continue
        row = load_json_value_bytes(line, label=f"{label} line {line_number}")
        if not isinstance(row, dict):
            raise CandidateError(
                f"{label} line {line_number} must be a JSON object"
            )
        row_count += 1
        yield row
    if row_count == 0:
        raise CandidateError(f"{label} contains no JSON object rows")


def load_json_lines_mappings_bytes(
    serialized: bytes, *, label: str
) -> list[dict[str, Any]]:
    """Materialize strict JSON-Lines objects; tests and small callers only."""

    return list(iter_json_lines_mappings_bytes(serialized, label=label))


def load_json_value(path: Path | str, *, label: str = "production JSON") -> Any:
    """Load UTF-8 JSON while rejecting duplicate keys at every nesting level."""

    target = _lexical_absolute(path)
    try:
        return load_json_value_bytes(
            read_regular_file_bytes(target, label=label), label=label
        )
    except CandidateError:
        raise
    except OSError as exc:
        raise CandidateError(f"{label} is not strict UTF-8 JSON: {target}") from exc


def load_json_mapping(
    path: Path | str, *, label: str = "production JSON object"
) -> dict[str, Any]:
    payload = load_json_value(path, label=label)
    if not isinstance(payload, dict):
        raise CandidateError(f"{label} must be a JSON object: {path}")
    return payload


def load_json_mapping_snapshot(
    path: Path | str, *, label: str = "production JSON object"
) -> tuple[dict[str, Any], bytes, str]:
    """Parse and hash one no-follow byte snapshot, rejecting duplicate keys."""

    serialized = read_regular_file_bytes(path, label=label)
    payload = load_json_mapping_bytes(serialized, label=label)
    return payload, serialized, hashlib.sha256(serialized).hexdigest()


def load_bound_json_mapping_snapshot(
    path: Path | str, *, expected_sha256: Any, label: str
) -> tuple[dict[str, Any], bytes, str]:
    """Strict-parse one snapshot and require its declared byte digest."""

    expected = str(expected_sha256 or "").strip()
    if _SHA256_RE.fullmatch(expected) is None:
        raise CandidateError(f"{label} expected digest is malformed")
    payload, serialized, observed = load_json_mapping_snapshot(path, label=label)
    if observed != expected:
        raise CandidateError(f"{label} digest drifted")
    return payload, serialized, observed


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _strict_canonical_source_identity(row: Mapping[str, Any]) -> str:
    merged = _merge_legacy_row(row)
    identity, error = _canonical_source_identity(merged)
    if error or identity is None:
        raise LegacyInputError(
            f"canonical source identity is invalid: {error or 'missing'}"
        )
    return identity


def _validated_source_identity_counter(
    value: Mapping[str, int], *, label: str
) -> Counter[str]:
    if not isinstance(value, Mapping):
        raise CandidateError(f"{label} is not a source-identity multiset")
    result: Counter[str] = Counter()
    for raw_identity, raw_count in value.items():
        identity = str(raw_identity or "")
        if (
            not isinstance(raw_identity, str)
            or not identity.strip()
            or identity != identity.strip()
            or "\x00" in identity
        ):
            raise CandidateError(f"{label} contains a malformed source identity")
        if (
            isinstance(raw_count, bool)
            or not isinstance(raw_count, int)
            or raw_count <= 0
        ):
            raise CandidateError(f"{label} contains a malformed multiplicity")
        result[identity] = raw_count
    return result


def _source_identity_multiset_digest(value: Mapping[str, int]) -> str:
    counter = _validated_source_identity_counter(
        value, label="source-identity digest input"
    )
    return digest_payload(sorted(counter.elements()))


def _empty_source_identity_multiset_digest() -> str:
    return digest_payload([])


def _empty_legacy_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, Mapping):
        return not value or all(_empty_legacy_value(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return not value or all(_empty_legacy_value(item) for item in value)
    return False


_RECOVERY_MANIFEST_ROW_KEYS: Final = frozenset(
    {
        "archived_count",
        "archived_source_urls",
        "candidate_count",
        "candidate_urls",
        "cid_field",
        "citation_text",
        "corpus_key",
        "generated_at",
        "hf_dataset_id",
        "identifier",
        "ipfs_cid",
        "jsonld",
        "legislation_jurisdiction",
        "legislation_type",
        "manifest_directory",
        "manifest_path",
        "name",
        "normalized_citation",
        "preferred_parquet_names",
        "primary_candidate_score",
        "primary_candidate_source",
        "primary_candidate_source_type",
        "primary_candidate_title",
        "primary_candidate_url",
        "promotion_json_path",
        "promotion_output_dir",
        "promotion_parquet_path",
        "search_query",
        "source_id",
        "source_type",
        "source_url",
        "state_code",
        "state_field",
        "target_local_parquet_path",
        "target_parquet_file",
        "target_parquet_path",
        "text",
    }
)
_RECOVERY_MANIFEST_EMPTY_LAW_FIELDS: Final = frozenset(
    {
        "identifier",
        "ipfs_cid",
        "jsonld",
        "legislation_jurisdiction",
        "legislation_type",
        "name",
        "source_id",
        "source_url",
        "text",
    }
)


def _nonempty_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        return None
    return value.strip()


def _http_url_list(value: Any, *, allow_empty: bool) -> list[str] | None:
    if not isinstance(value, list) or (not allow_empty and not value):
        return None
    result: list[str] = []
    for item in value:
        text = _nonempty_text(item)
        if text is None:
            return None
        parsed = urllib.parse.urlsplit(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        result.append(text)
    if len(result) != len(set(result)):
        return None
    return result


def _absolute_recovery_path(value: Any) -> str | None:
    text = _nonempty_text(value)
    if text is None or not Path(text).is_absolute() or ".." in Path(text).parts:
        return None
    return text.rstrip("/")


def _authenticated_recovery_manifest(
    row: Mapping[str, Any], *, jurisdiction: str
) -> bool:
    code = str(jurisdiction or "").strip().upper()
    parquet_name = f"STATE-{code}.parquet"
    if set(row) != _RECOVERY_MANIFEST_ROW_KEYS:
        return False
    if any(not _empty_legacy_value(row.get(key)) for key in _RECOVERY_MANIFEST_EMPTY_LAW_FIELDS):
        return False
    exact = {
        "cid_field": "ipfs_cid",
        "corpus_key": "state_laws",
        "hf_dataset_id": "justicedao/ipfs_state_laws",
        "primary_candidate_source": "citation_url_hint",
        "primary_candidate_source_type": "current",
        "source_type": "legal_source_recovery_manifest",
        "state_code": code,
        "state_field": "state_code",
        "target_parquet_file": parquet_name,
        "target_parquet_path": f"state_laws_parquet_cid/{parquet_name}",
    }
    if any(row.get(key) != value for key, value in exact.items()):
        return False
    if row.get("preferred_parquet_names") != [
        parquet_name,
        "state_laws_all_states.parquet",
    ]:
        return False
    citation = _nonempty_text(row.get("citation_text"))
    if citation is None or row.get("normalized_citation") != citation:
        return False
    generated_at = _nonempty_text(row.get("generated_at"))
    try:
        datetime.fromisoformat(str(generated_at))
    except ValueError:
        return False
    candidates = _http_url_list(row.get("candidate_urls"), allow_empty=False)
    archived = _http_url_list(row.get("archived_source_urls"), allow_empty=True)
    candidate_count = row.get("candidate_count")
    archived_count = row.get("archived_count")
    if (
        candidates is None
        or archived is None
        or isinstance(candidate_count, bool)
        or not isinstance(candidate_count, int)
        or candidate_count != len(candidates)
        or isinstance(archived_count, bool)
        or not isinstance(archived_count, int)
        or archived_count != len(archived)
        or not set(archived).issubset(candidates)
        or row.get("primary_candidate_url") != candidates[0]
    ):
        return False
    score = row.get("primary_candidate_score")
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or score <= 0
        or _nonempty_text(row.get("primary_candidate_title")) is None
        or _nonempty_text(row.get("search_query")) is None
    ):
        return False
    manifest_dir = _absolute_recovery_path(row.get("manifest_directory"))
    manifest_path = _absolute_recovery_path(row.get("manifest_path"))
    promotion_dir = _absolute_recovery_path(row.get("promotion_output_dir"))
    promotion_json = _absolute_recovery_path(row.get("promotion_json_path"))
    promotion_parquet = _absolute_recovery_path(row.get("promotion_parquet_path"))
    target_local = _absolute_recovery_path(row.get("target_local_parquet_path"))
    if None in {
        manifest_dir,
        manifest_path,
        promotion_dir,
        promotion_json,
        promotion_parquet,
        target_local,
    }:
        return False
    assert manifest_dir is not None and promotion_dir is not None
    return (
        manifest_path == f"{manifest_dir}/recovery_manifest.json"
        and promotion_dir == f"{manifest_dir}/canonical_promotion"
        and promotion_json == f"{promotion_dir}/promotion_rows.json"
        and promotion_parquet == f"{promotion_dir}/promotion_rows.parquet"
        and str(target_local).endswith(
            f"/state_laws_parquet_cid/{parquet_name}"
        )
    )


def _recovery_manifest_multiset_digest(row_digests: Sequence[str]) -> str:
    if any(_SHA256_RE.fullmatch(str(item or "")) is None for item in row_digests):
        raise CandidateError("authenticated recovery-manifest row digest is malformed")
    return digest_payload(sorted(str(item) for item in row_digests))


def _baseline_source_identity_observer_factory(
    jurisdiction: str,
) -> Any:
    code = str(jurisdiction or "").strip().upper()
    if code not in CANONICAL_JURISDICTION_ORDER:
        raise CandidateError(f"invalid baseline observer jurisdiction {code!r}")

    def observe(serialized: bytes) -> Mapping[str, Any]:
        if not isinstance(serialized, bytes) or not serialized:
            raise CandidateError(f"{code} baseline partition bytes are empty")
        try:
            import pyarrow.parquet as pq

            parquet = pq.ParquetFile(io.BytesIO(serialized))
            required_columns = {"state_code", "source_id", "jsonld"}
            if not required_columns.issubset(parquet.schema_arrow.names):
                raise CandidateError(
                    f"{code} authenticated baseline partition lacks required "
                    "state_code/source_id/jsonld columns"
                )
        except Exception as exc:
            raise CandidateError(
                f"{code} authenticated baseline partition is not readable Parquet"
            ) from exc
        identities: Counter[str] = Counter()
        recovery_manifest_row_digests: list[str] = []
        observed_rows = 0
        try:
            for batch in parquet.iter_batches(batch_size=8192):
                for raw_row in batch.to_pylist():
                    if not isinstance(raw_row, Mapping):
                        raise CandidateError(
                            f"{code} baseline partition contains a non-object row"
                        )
                    row = dict(raw_row)
                    row_index = observed_rows
                    observed_rows += 1
                    labels = [
                        str(row.get(key) or "").strip().upper()
                        for key in ("jurisdiction", "stateCode", "state_code")
                        if not _empty_legacy_value(row.get(key))
                    ]
                    if not labels or any(label != code for label in labels):
                        raise CandidateError(
                            f"{code} baseline row {row_index} has a conflicting jurisdiction"
                        )
                    if _authenticated_recovery_manifest(row, jurisdiction=code):
                        try:
                            row_digest = hashlib.sha256(
                                canonical_json_bytes(row)
                            ).hexdigest()
                        except (TypeError, ValueError) as exc:
                            raise CandidateError(
                                f"{code} recovery-manifest row {row_index} is not "
                                "canonical JSON"
                            ) from exc
                        recovery_manifest_row_digests.append(row_digest)
                        continue
                    raw_source_id = row.get("source_id")
                    if (
                        not isinstance(raw_source_id, str)
                        or not raw_source_id.strip()
                        or raw_source_id != raw_source_id.strip()
                        or "\x00" in raw_source_id
                    ):
                        raise CandidateError(
                            f"{code} substantive baseline row {row_index} lacks "
                            "an exact nonblank source_id"
                        )
                    raw_jsonld = row.get("jsonld")
                    if isinstance(raw_jsonld, str) and raw_jsonld.strip():
                        try:
                            parsed_jsonld = json.loads(
                                raw_jsonld,
                                object_pairs_hook=_json_value_without_duplicate_keys,
                            )
                        except (UnicodeError, json.JSONDecodeError, CandidateError) as exc:
                            raise CandidateError(
                                f"{code} substantive baseline row {row_index} "
                                "contains malformed or duplicate-key JSON-LD"
                            ) from exc
                        if not isinstance(parsed_jsonld, Mapping):
                            raise CandidateError(
                                f"{code} substantive baseline row {row_index} "
                                "contains non-object JSON-LD"
                            )
                        if parsed_jsonld.get("@id") != raw_source_id:
                            raise CandidateError(
                                f"{code} substantive baseline row {row_index} "
                                "source_id/JSON-LD @id mirrors disagree"
                            )
                        identity_row = {**row, "jsonld": dict(parsed_jsonld)}
                    else:
                        raise CandidateError(
                            f"{code} substantive baseline row {row_index} "
                            "lacks exact JSON-LD identity evidence"
                        )
                    try:
                        identity = _strict_canonical_source_identity(identity_row)
                    except LegacyInputError as exc:
                        raise CandidateError(
                            f"{code} substantive baseline row {row_index} lacks one "
                            "unambiguous canonical source identity"
                        ) from exc
                    identities[identity] += 1
        except CandidateError:
            raise
        except Exception as exc:
            raise CandidateError(
                f"{code} authenticated baseline partition scan failed"
            ) from exc
        ordered_identities = sorted(identities.elements())
        ordered_recovery_digests = sorted(recovery_manifest_row_digests)
        return {
            "jurisdiction": code,
            "noncomparable_recovery_manifest_count": len(
                ordered_recovery_digests
            ),
            "noncomparable_recovery_manifest_multiset_sha256": (
                _recovery_manifest_multiset_digest(ordered_recovery_digests)
            ),
            "noncomparable_recovery_manifest_row_digests": (
                ordered_recovery_digests
            ),
            "observed_row_count": observed_rows,
            "schema_version": BASELINE_SOURCE_IDENTITY_CLOSURE_SCHEMA,
            "source_identities": ordered_identities,
            "source_identity_count": len(ordered_identities),
            "source_identity_multiset_sha256": digest_payload(
                ordered_identities
            ),
        }

    return observe


def file_sha256(path: Path | str) -> str:
    return hashlib.sha256(
        read_regular_file_bytes(path, label="digest input")
    ).hexdigest()


def _open_handle_sha256(handle: BinaryIO) -> str:
    """Hash a pinned handle and rewind it for a parser using the same inode."""

    digest = hashlib.sha256()
    handle.seek(0)
    while chunk := handle.read(1024 * 1024):
        digest.update(chunk)
    handle.seek(0)
    return digest.hexdigest()


def _require_sha256(value: Any, *, label: str) -> str:
    digest = str(value or "").strip()
    if _SHA256_RE.fullmatch(digest) is None:
        raise CandidateError(f"{label} must be a lowercase SHA-256 digest")
    return digest


def _require_git_revision(value: Any, *, label: str = "source_revision") -> str:
    revision = str(value or "").strip()
    if _GIT_SHA_RE.fullmatch(revision) is None:
        raise CandidateError(f"{label} must be an exact lowercase 40-hex Git commit")
    return revision


def _display_path(path: Path | str, *, repo_root: Path) -> str:
    target = Path(path).expanduser().resolve()
    try:
        return target.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(target)


def resolve_evidence_path(value: Any, *, repo_root: Path, label: str) -> Path:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CandidateError(f"{label} must be a non-empty path")
    path = _lexical_absolute(value.strip(), base=repo_root)
    try:
        cursor = Path(path.anchor)
        for component in path.parts[1:]:
            cursor /= component
            if cursor.is_symlink():
                raise CandidateError(f"{label} must not traverse a symlink: {cursor}")
        target = path.resolve(strict=True)
    except CandidateError:
        raise
    except OSError as exc:
        raise CandidateError(f"{label} does not exist: {path}") from exc
    if not target.is_file():
        raise CandidateError(f"{label} must be a safe regular file: {target}")
    # Pin/open it now as well; this catches special files and replacement races
    # before a caller receives the normalized path.
    with _open_regular_file_nofollow(path, label=label):
        pass
    return target


def resolve_evidence_directory(value: Any, *, repo_root: Path, label: str) -> Path:
    """Resolve one report-declared directory relative to its repository root."""

    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CandidateError(f"{label} must be a non-empty path")
    return _safe_existing_directory(
        _lexical_absolute(value.strip(), base=repo_root), label=label
    )


def _git_stdout(repo_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CandidateError(f"cannot verify source-control binding: git {' '.join(args)}") from exc
    return completed.stdout.strip()


def source_control_binding(
    *,
    repo_root: Path | str,
    source_revision: str,
    require_clean: bool,
) -> dict[str, Any]:
    """Bind an immutable Git commit/tree and, while sealing, a clean checkout."""

    root = Path(repo_root).expanduser().resolve()
    revision = _require_git_revision(source_revision)
    resolved = _git_stdout(root, "rev-parse", f"{revision}^{{commit}}")
    if resolved != revision:
        raise CandidateError(
            f"source_revision resolved to {resolved!r}, expected {revision!r}"
        )
    tree = _git_stdout(root, "rev-parse", f"{revision}^{{tree}}")
    if _GIT_SHA_RE.fullmatch(tree) is None:
        raise CandidateError("source revision did not resolve to an exact Git tree")
    if require_clean:
        head = _git_stdout(root, "rev-parse", "HEAD")
        if head != revision:
            raise CandidateError(
                "production evidence must be sealed at the exact source revision"
            )
        require_only_expected_dirty_paths(
            repo_root=root,
            source_revision=revision,
            allowed_paths=(),
        )
    return {
        "clean_at_seal": bool(require_clean),
        "revision": revision,
        "tree": tree,
    }


def require_only_expected_dirty_paths(
    *,
    repo_root: Path | str,
    source_revision: str,
    allowed_paths: Sequence[Path | str],
) -> None:
    """Allow only byte-bound reports after the source revision.

    ``source_revision`` is the executable-source commit recorded in the
    non-self-referential report.  Verification accepts either that exact HEAD
    with controlled report files dirty, or a clean descendant whose commits
    changed only those same regular report paths.  Source-changing descendants,
    deletes, mode/symlink changes, renames, copies, and unrelated worktree
    changes fail closed.
    """

    root = Path(repo_root).expanduser().resolve()
    revision = _require_git_revision(source_revision)
    head = _git_stdout(root, "rev-parse", "HEAD")
    allowed: set[str] = set()
    for value in allowed_paths:
        target = _lexical_absolute(value)
        try:
            allowed.add(target.relative_to(root.absolute()).as_posix())
        except ValueError:
            # An external evidence file cannot appear in this Git worktree's
            # porcelain status, so it grants no additional dirty-path scope.
            continue
    if head != revision:
        ancestor = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", revision, head],
            check=False,
            capture_output=True,
            timeout=30,
        )
        if ancestor.returncode != 0:
            raise CandidateError(
                "current HEAD is not a report-only descendant of the evidence revision"
            )
        try:
            committed = subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "diff",
                    "--name-status",
                    "-z",
                    "--no-renames",
                    f"{revision}..{head}",
                ],
                check=True,
                capture_output=True,
                timeout=30,
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise CandidateError("cannot verify report-only descendant commits") from exc
        fields = committed.split(b"\0")
        if fields and fields[-1] == b"":
            fields.pop()
        if len(fields) % 2:
            raise CandidateError("cannot parse report-only descendant commit diff")
        for position in range(0, len(fields), 2):
            status_code = fields[position].decode("ascii", errors="strict")
            path_text = fields[position + 1].decode(
                "utf-8", errors="surrogateescape"
            )
            if status_code not in {"A", "M"} or path_text not in allowed:
                raise CandidateError(
                    "source revision descendant contains non-report drift: "
                    f"{status_code} {path_text}"
                )
            tree_row = _git_stdout(root, "ls-tree", head, "--", path_text)
            mode = tree_row.split(None, 1)[0] if tree_row else ""
            if mode != "100644":
                raise CandidateError(
                    "report-only descendant path changed mode or is not a "
                    f"non-executable regular blob: {path_text}"
                )
    try:
        status = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                "--ignore-submodules=none",
            ],
            check=True,
            capture_output=True,
            text=False,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise CandidateError("cannot inspect source worktree while sealing") from exc
    observed: set[str] = set()
    records = status.split(b"\0")
    position = 0
    while position < len(records) - 1:
        record = records[position]
        position += 1
        if len(record) < 4 or record[2:3] != b" ":
            raise CandidateError("cannot parse source worktree status while sealing")
        xy = record[:2].decode("ascii", errors="strict")
        if "U" in xy or xy in {"AA", "DD"}:
            raise CandidateError("unmerged source state cannot be production evidence")
        path_text = record[3:].decode("utf-8", errors="surrogateescape")
        if not path_text:
            raise CandidateError("source worktree status contains an empty path")
        observed.add(path_text)
        if "R" in xy or "C" in xy:
            if position >= len(records) - 1 or not records[position]:
                raise CandidateError("rename/copy source status is truncated")
            source_text = records[position].decode(
                "utf-8", errors="surrogateescape"
            )
            position += 1
            observed.add(source_text)
            raise CandidateError(
                "rename/copy source state cannot be production evidence: "
                f"{xy} {source_text} -> {path_text}"
            )
        if xy != "??" and any(code not in {" ", "A", "M"} for code in xy):
            raise CandidateError(
                "only added or modified report bytes may differ from the "
                f"source revision: {xy} {path_text}"
            )
        report_path = root / path_text
        try:
            report_stat = report_path.lstat()
        except OSError as exc:
            raise CandidateError(
                f"dirty report path is not an accessible regular file: {path_text}"
            ) from exc
        if not stat.S_ISREG(report_stat.st_mode) or report_stat.st_mode & 0o111:
            raise CandidateError(
                "dirty report path must remain a non-executable regular file: "
                f"{path_text}"
            )
        try:
            indexed_output = subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "ls-files",
                    "--stage",
                    "-z",
                    "--",
                    path_text,
                ],
                check=True,
                capture_output=True,
                timeout=30,
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise CandidateError(
                f"cannot verify dirty report index mode: {path_text}"
            ) from exc
        index_rows = [row for row in indexed_output.split(b"\0") if row]
        if xy == "??":
            if index_rows:
                raise CandidateError(
                    f"untracked report unexpectedly has an index entry: {path_text}"
                )
            continue
        if len(index_rows) != 1 or b"\t" not in index_rows[0]:
            raise CandidateError(
                f"dirty report lacks one canonical index entry: {path_text}"
            )
        index_metadata, indexed_path_bytes = index_rows[0].split(b"\t", 1)
        index_fields = index_metadata.split()
        indexed_path = indexed_path_bytes.decode(
            "utf-8", errors="surrogateescape"
        )
        if (
            len(index_fields) != 3
            or index_fields[0] != b"100644"
            or index_fields[2] != b"0"
            or indexed_path != path_text
        ):
            raise CandidateError(
                "dirty report index entry must remain one stage-0 100644 blob: "
                f"{path_text}"
            )
    unexpected = sorted(observed.difference(allowed))
    if unexpected:
        raise CandidateError(
            f"candidate sealing found source drift beyond acceptance output: {unexpected}"
        )


def _artifact_projection(value: Mapping[str, Any], *, position: int) -> dict[str, Any]:
    relative_path = str(value.get("relative_path") or value.get("path") or "").strip()
    family = str(value.get("family") or "").strip()
    if not relative_path or not family:
        raise CandidateError(
            f"production manifest artifact {position} lacks path/family identity"
        )
    try:
        size_bytes = int(value.get("size_bytes"))
        row_count = int(value.get("row_count"))
    except (TypeError, ValueError) as exc:
        raise CandidateError(
            f"production manifest artifact {position} has malformed counts"
        ) from exc
    if size_bytes < 0 or row_count < 0:
        raise CandidateError(
            f"production manifest artifact {position} has negative counts"
        )
    return {
        "family": family,
        "relative_path": relative_path,
        "row_count": row_count,
        "sha256": _require_sha256(
            value.get("sha256"), label=f"artifacts[{position}].sha256"
        ),
        "size_bytes": size_bytes,
    }


def _manifest_counts(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("counts")
    if not isinstance(raw, Mapping) or not raw:
        raise CandidateError("verified production manifest lacks counts")
    counts: list[dict[str, Any]] = []
    for name in sorted(raw):
        value = raw[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CandidateError(f"production manifest count {name!r} is malformed")
        counts.append({"name": str(name), "value": value})
    return counts


def _manifest_key_parity(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = payload.get("key_parity")
    if not isinstance(raw, Mapping):
        raise CandidateError("verified production manifest lacks key_parity")
    required = (
        "parent_entry_cid_count",
        "parent_entry_cids_sha256",
        "chunk_cid_count",
        "chunk_cids_sha256",
        "document_chunk_mapping_sha256",
    )
    missing = [name for name in required if name not in raw]
    if missing:
        raise CandidateError(f"production manifest key_parity lacks {missing}")
    for flag in ("exact", "chunk_cids_exact", "document_chunk_mapping_exact"):
        if raw.get(flag) is not True:
            raise CandidateError(f"production manifest key_parity.{flag} is not true")
    return {
        "chunk_cid_count": int(raw["chunk_cid_count"]),
        "chunk_cids_exact": True,
        "chunk_cids_sha256": _require_sha256(
            raw["chunk_cids_sha256"], label="key_parity.chunk_cids_sha256"
        ),
        "document_chunk_mapping_exact": True,
        "document_chunk_mapping_sha256": _require_sha256(
            raw["document_chunk_mapping_sha256"],
            label="key_parity.document_chunk_mapping_sha256",
        ),
        "exact": True,
        "parent_entry_cid_count": int(raw["parent_entry_cid_count"]),
        "parent_entry_cids_sha256": _require_sha256(
            raw["parent_entry_cids_sha256"],
            label="key_parity.parent_entry_cids_sha256",
        ),
    }


def _live_baseline_remote_projection(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Project every authenticated remote byte/count claim for live replay."""

    identity = receipt.get("authenticated_identity")
    pins = receipt.get("pins")
    requests = receipt.get("requests")
    state = receipt.get("state_laws")
    federal = receipt.get("federal_register")
    if (
        not isinstance(identity, Mapping)
        or not isinstance(pins, Mapping)
        or not isinstance(requests, list)
        or not isinstance(state, Mapping)
        or not isinstance(federal, Mapping)
    ):
        raise CandidateError("LCR-081 receipt lacks remote replay surfaces")
    # Token discovery location is local process metadata, not remote identity.
    # Every other safe identity field, request response hash/length, repository
    # inventory, Parquet byte/footer digest, and recomputed count must match.
    projected_identity = {
        key: value for key, value in identity.items() if key != "token_source"
    }
    projected_state = dict(state)
    raw_partitions = state.get("partitions")
    if not isinstance(raw_partitions, Mapping):
        raise CandidateError("LCR-081 receipt lacks state-law partitions")
    projected_state["partitions"] = {
        str(code): {
            key: value
            for key, value in part.items()
            if key != "partition_body_observation"
        }
        if isinstance(part, Mapping)
        else part
        for code, part in raw_partitions.items()
    }
    return {
        "authenticated_identity": projected_identity,
        "federal_register": dict(federal),
        "pins": dict(pins),
        "requests": requests,
        "state_laws": projected_state,
    }


def _baseline_source_identity_closures_from_replay(
    replay: Mapping[str, Any], stored: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    replay_state = replay.get("state_laws")
    stored_state = stored.get("state_laws")
    replay_partitions = (
        replay_state.get("partitions")
        if isinstance(replay_state, Mapping)
        else None
    )
    stored_partitions = (
        stored_state.get("partitions")
        if isinstance(stored_state, Mapping)
        else None
    )
    expected = tuple(CANONICAL_JURISDICTION_ORDER)
    if (
        not isinstance(replay_partitions, Mapping)
        or not isinstance(stored_partitions, Mapping)
        or len(replay_partitions) != len(expected)
        or len(stored_partitions) != len(expected)
        or set(replay_partitions) != set(expected)
        or set(stored_partitions) != set(expected)
    ):
        raise CandidateError(
            "LCR-081 source-identity observation is not canonical exact-51"
        )
    closures: dict[str, dict[str, Any]] = {}
    expected_observation_fields = {
        "jurisdiction",
        "noncomparable_recovery_manifest_count",
        "noncomparable_recovery_manifest_multiset_sha256",
        "noncomparable_recovery_manifest_row_digests",
        "observed_row_count",
        "schema_version",
        "source_identities",
        "source_identity_count",
        "source_identity_multiset_sha256",
    }
    for code in expected:
        replay_part = replay_partitions.get(code)
        stored_part = stored_partitions.get(code)
        if not isinstance(replay_part, Mapping) or not isinstance(
            stored_part, Mapping
        ):
            raise CandidateError(f"{code} LCR-081 baseline partition is malformed")
        observation = replay_part.get("partition_body_observation")
        if not isinstance(observation, Mapping) or set(observation) != (
            expected_observation_fields
        ):
            raise CandidateError(
                f"{code} baseline source-identity observation is malformed"
            )
        if (
            observation.get("schema_version")
            != BASELINE_SOURCE_IDENTITY_CLOSURE_SCHEMA
            or observation.get("jurisdiction") != code
        ):
            raise CandidateError(
                f"{code} baseline source-identity observation identity drifted"
            )
        raw_identities = observation.get("source_identities")
        if not isinstance(raw_identities, list) or any(
            not isinstance(identity, str)
            or not identity.strip()
            or identity != identity.strip()
            or "\x00" in identity
            for identity in raw_identities
        ):
            raise CandidateError(
                f"{code} baseline source-identity multiset is malformed"
            )
        if raw_identities != sorted(raw_identities):
            raise CandidateError(
                f"{code} baseline source-identity multiset is not canonical"
            )
        source_identity_count = observation.get("source_identity_count")
        if (
            isinstance(source_identity_count, bool)
            or not isinstance(source_identity_count, int)
            or source_identity_count != len(raw_identities)
        ):
            raise CandidateError(
                f"{code} baseline source-identity count drifted"
            )
        source_identity_digest = _require_sha256(
            observation.get("source_identity_multiset_sha256"),
            label=f"{code} baseline source-identity multiset digest",
        )
        if source_identity_digest != digest_payload(raw_identities):
            raise CandidateError(
                f"{code} baseline source-identity multiset digest drifted"
            )
        recovery_row_digests = observation.get(
            "noncomparable_recovery_manifest_row_digests"
        )
        if not isinstance(recovery_row_digests, list) or any(
            _SHA256_RE.fullmatch(str(item or "")) is None
            for item in recovery_row_digests
        ):
            raise CandidateError(
                f"{code} baseline recovery-manifest projection is malformed"
            )
        if recovery_row_digests != sorted(recovery_row_digests):
            raise CandidateError(
                f"{code} baseline recovery-manifest multiset is not canonical"
            )
        recovery_manifest_count = observation.get(
            "noncomparable_recovery_manifest_count"
        )
        if (
            isinstance(recovery_manifest_count, bool)
            or not isinstance(recovery_manifest_count, int)
            or recovery_manifest_count != len(recovery_row_digests)
        ):
            raise CandidateError(
                f"{code} baseline recovery-manifest count drifted"
            )
        recovery_manifest_digest = _require_sha256(
            observation.get(
                "noncomparable_recovery_manifest_multiset_sha256"
            ),
            label=f"{code} baseline recovery-manifest multiset digest",
        )
        if recovery_manifest_digest != _recovery_manifest_multiset_digest(
            recovery_row_digests
        ):
            raise CandidateError(
                f"{code} baseline recovery-manifest multiset digest drifted"
            )
        observed_row_count = observation.get("observed_row_count")
        replay_row_count = replay_part.get("num_rows")
        stored_row_count = stored_part.get("num_rows")
        if (
            isinstance(observed_row_count, bool)
            or not isinstance(observed_row_count, int)
            or observed_row_count
            != source_identity_count + recovery_manifest_count
            or replay_row_count != observed_row_count
            or stored_row_count != observed_row_count
        ):
            raise CandidateError(
                f"{code} baseline source identities/recovery manifests do not close rows"
            )
        counter = _validated_source_identity_counter(
            Counter(raw_identities), label=f"{code} baseline source identities"
        )
        closures[code] = {
            "counter": counter,
            "noncomparable_recovery_manifest_count": recovery_manifest_count,
            "noncomparable_recovery_manifest_multiset_sha256": (
                recovery_manifest_digest
            ),
            "source_identity_count": source_identity_count,
            "source_identity_multiset_sha256": source_identity_digest,
        }
    return closures


def _verifier_owned_live_baseline_replay(
    stored: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Perform an unavoidable read-only Hub replay and bind its exact result."""

    try:
        replay = live_baseline_audit.observe_with_live_hub(
            state_partition_body_observer_factory=(
                _baseline_source_identity_observer_factory
            )
        )
        live_baseline_audit.validate_receipt(
            replay,
            require_live_hub=True,
            require_local_salvage_inventory=True,
            require_fresh_observation=True,
        )
    except CandidateError:
        raise
    except (
        ImportError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        raise CandidateError(
            f"verifier-owned LCR-081 live Hub replay failed: {exc}"
        ) from exc
    stored_projection = _live_baseline_remote_projection(stored)
    replay_projection = _live_baseline_remote_projection(replay)
    if replay_projection != stored_projection:
        raise CandidateError(
            "stored LCR-081 baseline differs from verifier-owned live Hub bytes/counts"
        )
    requests = replay.get("requests")
    if not isinstance(requests, list) or not requests:
        raise CandidateError("verifier-owned live replay recorded no Hub requests")
    projection_digest = digest_payload(replay_projection)
    if projection_digest != digest_payload(stored_projection):
        raise CandidateError("LCR-081 live replay projection digest drifted")
    source_identity_closures = _baseline_source_identity_closures_from_replay(
        replay, stored
    )
    return (
        {
            "live_replay_request_count": len(requests),
            "remote_projection_digest_sha256": projection_digest,
            "verifier_owned_live_reobservation": True,
        },
        source_identity_closures,
    )


def _validated_live_baseline(
    path: Path | str,
    *,
    repo_root: Path,
) -> tuple[
    Path,
    dict[str, Any],
    dict[str, Any],
    dict[str, dict[str, Any]],
    str,
]:
    baseline_path = resolve_evidence_path(
        str(_lexical_absolute(path)),
        repo_root=repo_root,
        label="fresh LCR-081 live-baseline receipt",
    )
    try:
        baseline, _, baseline_sha256 = load_json_mapping_snapshot(
            baseline_path, label="LCR-081 baseline"
        )
        schema_path = repo_root / live_baseline_audit.SCHEMA_RELPATH
        schema = load_json_mapping(schema_path)
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(baseline),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
        if errors:
            first = errors[0]
            location = ".".join(str(part) for part in first.absolute_path) or "<root>"
            raise CandidateError(
                f"LCR-081 baseline schema failed at {location}: {first.message}"
            )
        live_baseline_audit.validate_receipt(
            baseline,
            require_live_hub=True,
            require_local_salvage_inventory=True,
            # This stored receipt is the byte/count projection anchor.  A
            # verifier-owned live replay below supplies the unavoidable
            # current observation on every seal and check.  Requiring the
            # anchor's 30-minute LCR-081 timestamp here would let a bounded
            # exact-51 replay expire its own otherwise-current verification.
            require_fresh_observation=False,
        )
    except CandidateError:
        raise
    except (
        ImportError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        raise CandidateError(f"fresh LCR-081 live baseline is invalid: {exc}") from exc
    replay_binding, source_identity_closures = (
        _verifier_owned_live_baseline_replay(baseline)
    )
    return (
        baseline_path,
        baseline,
        replay_binding,
        source_identity_closures,
        baseline_sha256,
    )


def _normalized_corpus_row(value: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    """Remove only the physical writer's two derived positional columns."""

    if not isinstance(value, Mapping):
        raise CandidateError(f"{label} is not a corpus row object")
    row = dict(value)
    if "document_index" not in row:
        raise CandidateError(f"{label} lacks document_index")
    row.pop("document_index")
    row.pop("jurisdiction_code", None)
    entry_cid = str(row.get("entry_cid") or "")
    code = str(row.get("jurisdiction") or "").strip().upper()
    if not entry_cid or code not in CANONICAL_JURISDICTION_ORDER:
        raise CandidateError(f"{label} lacks a canonical jurisdiction/key")
    return row


def _strict_adapter_snapshot_rows(
    *, adapter: Any, binding: Any, code: str
) -> Iterator[dict[str, Any]]:
    """Capture, bind, and strict-parse the one snapshot fed to an adapter."""

    canonical_bytes = read_regular_file_bytes(
        binding.canonical_jsonld_path, label=f"{code} canonical JSON-LD"
    )
    canonical_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
    if (
        canonical_sha256 != binding.canonical_jsonld_sha256
        or canonical_sha256 != adapter.source_receipt.input_sha256
        or _lexical_absolute(adapter.input_path)
        != _lexical_absolute(binding.canonical_jsonld_path)
    ):
        raise CandidateError(
            f"{code} canonical adapter snapshot differs from its prepared binding"
        )
    return iter_json_lines_mappings_bytes(
        canonical_bytes, label=f"{code} canonical JSON-LD"
    )


def _derive_input_corpus_closure(prepared: Any) -> dict[str, dict[str, Any]]:
    """Replay every selected canonical JSON-LD row and derive exact outcomes."""

    bindings = {item.jurisdiction: item for item in prepared.bindings}
    receipts = {item.jurisdiction: item for item in prepared.source_receipts}
    adapters = {item.jurisdiction: item for item in prepared.adapters}
    expected = tuple(CANONICAL_JURISDICTION_ORDER)
    if tuple(bindings) != expected or tuple(receipts) != expected or tuple(adapters) != expected:
        raise CandidateError("prepared corpus closure is not canonical exact-51")
    result: dict[str, dict[str, Any]] = {}
    union_keys: set[str] = set()
    for code in expected:
        binding = bindings[code]
        adapter = adapters[code]
        # Drive the current adapter semantics from the exact no-follow byte
        # snapshot that was strict-parsed here.  Calling iter_events() would
        # reopen the path after the duplicate-key scan and create a swap race.
        source_rows = _strict_adapter_snapshot_rows(
            adapter=adapter, binding=binding, code=code
        )
        checkpoint = adapter.new_checkpoint()
        rows: list[dict[str, Any]] = []
        source_identities: Counter[str] = Counter()
        dispositions = {"admitted": 0, "quarantined": 0, "rejected": 0}
        for expected_source_index, source_row in enumerate(source_rows):
            try:
                source_identity = _strict_canonical_source_identity(source_row)
            except LegacyInputError as exc:
                raise CandidateError(
                    f"{code} selected source row {expected_source_index} lacks one "
                    "unambiguous canonical source identity"
                ) from exc
            source_identities[source_identity] += 1
            event = adapter.adapt_row(
                source_row, source_index=expected_source_index
            )
            if int(event.source_index) != expected_source_index:
                raise CandidateError(f"{code} adapter source indexes are not dense")
            raw_disposition = getattr(event.disposition, "value", event.disposition)
            disposition = str(raw_disposition).strip().lower()
            if disposition not in dispositions:
                raise CandidateError(f"{code} adapter emitted unknown disposition {disposition!r}")
            dispositions[disposition] += 1
            checkpoint = checkpoint.advance(event)
            if disposition != "admitted" or event.record is None:
                raise CandidateError(
                    f"{code} selected canonical input emitted non-admitted disposition"
                )
            row = _normalized_corpus_row(
                event.record.to_dict(), label=f"{code} input row {event.source_index}"
            )
            if row["jurisdiction"] != code:
                raise CandidateError(f"{code} input row is mislabeled as {row['jurisdiction']!r}")
            if row.get("acquisition_receipt_id") != receipts[code].receipt_id:
                raise CandidateError(f"{code} input row does not bind its selected receipt")
            rows.append(row)
        checkpoint = adapter.finalize_checkpoint(checkpoint)
        if checkpoint.complete is not True:
            raise CandidateError(f"{code} adapter did not close its input frontier")
        rows.sort(key=lambda item: str(item["entry_cid"]))
        keys = [str(item["entry_cid"]) for item in rows]
        if (
            len(rows) != adapter.source_receipt.input_row_count
            or len(keys) != len(set(keys))
            or sum(source_identities.values()) != len(rows)
        ):
            raise CandidateError(f"{code} input corpus row/key closure failed")
        overlap = union_keys.intersection(keys)
        if overlap:
            raise CandidateError(
                f"selected exact-51 input contains cross-jurisdiction duplicate keys: "
                f"{sorted(overlap)[:3]}"
            )
        union_keys.update(keys)
        result[code] = {
            "adapter_dispositions": dispositions,
            "entry_cids": keys,
            "rows": rows,
            "source_identity_counter": source_identities,
            "source_receipt": receipts[code].to_dict(),
        }
    return result


def _reconcile_baseline_source_identities(
    *,
    jurisdiction: str,
    baseline_counter: Mapping[str, int],
    acquired_counter: Mapping[str, int],
    baseline_row_count: int,
    acquired_row_count: int,
    noncomparable_recovery_manifest_count: int,
    noncomparable_recovery_manifest_multiset_sha256: str,
    duplicate_count: int,
    excluded_count: int,
    quarantined_count: int,
) -> dict[str, Any]:
    """Require multiset retention of every authenticated comparable source row."""

    code = str(jurisdiction or "").strip().upper()
    if code not in CANONICAL_JURISDICTION_ORDER:
        raise CandidateError(f"invalid baseline reconciliation jurisdiction {code!r}")
    baseline = _validated_source_identity_counter(
        baseline_counter, label=f"{code} baseline source identities"
    )
    acquired = _validated_source_identity_counter(
        acquired_counter, label=f"{code} acquired source identities"
    )
    baseline_identity_count = sum(baseline.values())
    acquired_identity_count = sum(acquired.values())
    if (
        isinstance(baseline_row_count, bool)
        or not isinstance(baseline_row_count, int)
        or baseline_row_count < 0
        or isinstance(acquired_row_count, bool)
        or not isinstance(acquired_row_count, int)
        or acquired_row_count < 0
        or isinstance(noncomparable_recovery_manifest_count, bool)
        or not isinstance(noncomparable_recovery_manifest_count, int)
        or noncomparable_recovery_manifest_count < 0
    ):
        raise CandidateError(f"{code} baseline reconciliation counts are malformed")
    recovery_manifest_digest = _require_sha256(
        noncomparable_recovery_manifest_multiset_sha256,
        label=f"{code} baseline recovery-manifest multiset digest",
    )
    if (
        baseline_identity_count + noncomparable_recovery_manifest_count
        != baseline_row_count
    ):
        raise CandidateError(
            f"{code} baseline identities/recovery manifests do not close its row count"
        )
    if acquired_identity_count != acquired_row_count:
        raise CandidateError(
            f"{code} acquired source identities do not close its row count"
        )
    removed = baseline - acquired
    added = acquired - baseline
    if removed:
        raise CandidateError(
            f"{code} current official corpus removes {sum(removed.values())} "
            "authenticated baseline source-identity occurrence(s) without an "
            "independently verified per-item terminal disposition"
        )
    added_count = sum(added.values())
    delta = acquired_row_count - baseline_row_count
    if delta != added_count - noncomparable_recovery_manifest_count:
        raise CandidateError(
            f"{code} baseline source-identity reconciliation arithmetic drifted"
        )
    for label, count in (
        ("duplicate", duplicate_count),
        ("excluded", excluded_count),
        ("quarantined", quarantined_count),
    ):
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise CandidateError(f"{code} {label} count is malformed")
    return {
        "acquired_row_count": acquired_row_count,
        "acquired_source_identity_count": acquired_identity_count,
        "acquired_source_identity_multiset_sha256": (
            _source_identity_multiset_digest(acquired)
        ),
        "added_source_identity_count": added_count,
        "added_source_identity_multiset_sha256": (
            _source_identity_multiset_digest(added)
            if added
            else _empty_source_identity_multiset_digest()
        ),
        "baseline_noncomparable_recovery_manifest_count": (
            noncomparable_recovery_manifest_count
        ),
        "baseline_noncomparable_recovery_manifest_disposition": (
            "authenticated_baseline_recovery_manifest"
        ),
        "baseline_noncomparable_recovery_manifest_multiset_sha256": (
            recovery_manifest_digest
        ),
        "baseline_row_count": baseline_row_count,
        "baseline_source_identity_count": baseline_identity_count,
        "baseline_source_identity_multiset_sha256": (
            _source_identity_multiset_digest(baseline)
        ),
        "delta_from_baseline": delta,
        "disposition": (
            "current_official_growth" if added_count else "exact_match"
        ),
        "duplicate_count": duplicate_count,
        "excluded_count": excluded_count,
        "explained_delta_count": noncomparable_recovery_manifest_count,
        "jurisdiction": code,
        "quarantined_count": quarantined_count,
        "removed_source_identity_count": 0,
        "removed_source_identity_multiset_sha256": (
            _empty_source_identity_multiset_digest()
        ),
    }


def _confined_release_file(root: Path, relative_path: Any, *, label: str) -> Path:
    relative = str(relative_path or "").strip()
    selected = Path(relative)
    if not relative or selected.is_absolute() or ".." in selected.parts:
        raise CandidateError(f"{label} is not a confined relative path")
    target = _lexical_absolute(root / selected)
    try:
        target.relative_to(root.absolute())
    except ValueError as exc:
        raise CandidateError(f"{label} escapes the production output root") from exc
    with _open_regular_file_nofollow(target, label=label):
        pass
    return target


def _snapshot_release_artifacts(
    release: Any, manifest: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Rehash every declared artifact through one no-follow file snapshot."""

    root = _safe_existing_directory(
        release.output_root, label="verified production output root"
    )
    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, Sequence) or isinstance(
        raw_artifacts, (str, bytes, bytearray)
    ):
        raise CandidateError("verified production manifest artifacts are malformed")
    projections: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for position, descriptor in enumerate(raw_artifacts):
        if not isinstance(descriptor, Mapping):
            raise CandidateError(
                "verified production manifest contains a non-object artifact"
            )
        projection = _artifact_projection(descriptor, position=position)
        relative = projection["relative_path"]
        if relative in seen_paths:
            raise CandidateError(
                f"verified production manifest repeats artifact path {relative!r}"
            )
        seen_paths.add(relative)
        target = _confined_release_file(
            root, relative, label=f"production artifact {relative}"
        )
        with _open_regular_file_nofollow(
            target, label=f"production artifact {relative}"
        ) as artifact_handle:
            observed_sha256 = _open_handle_sha256(artifact_handle)
            observed_size = os.fstat(artifact_handle.fileno()).st_size
        if (
            observed_sha256 != projection["sha256"]
            or observed_size != projection["size_bytes"]
        ):
            raise CandidateError(
                f"production artifact snapshot differs from descriptor: {relative}"
            )
        projections.append(projection)
    return projections


def _derive_release_corpus_closure(
    release: Any,
    manifest: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Reopen embedded receipts and parent corpus shards from verified bytes."""

    root = _safe_existing_directory(
        release.output_root, label="verified production output root"
    )
    strict_manifest, _, _ = load_json_mapping_snapshot(
        release.path, label="completed production manifest"
    )
    if strict_manifest != dict(manifest):
        raise CandidateError("strict production manifest parse differs from verifier payload")
    manifest = strict_manifest
    expected = tuple(CANONICAL_JURISDICTION_ORDER)
    result: dict[str, dict[str, Any]] = {
        code: {
            "entry_cids": [],
            "rows": [],
            "corpus_shards": [],
        }
        for code in expected
    }

    raw_receipts = manifest.get("source_receipts")
    if not isinstance(raw_receipts, Sequence) or isinstance(
        raw_receipts, (str, bytes, bytearray)
    ):
        raise CandidateError("completed manifest source receipts are malformed")
    release_receipt_codes: set[str] = set()
    for position, descriptor in enumerate(raw_receipts):
        if not isinstance(descriptor, Mapping):
            raise CandidateError(f"release source receipt {position} is not an object")
        metadata = descriptor.get("metadata")
        if not isinstance(metadata, Mapping):
            raise CandidateError(f"release source receipt {position} lacks metadata")
        code = str(metadata.get("jurisdiction_code") or "").strip().upper()
        if code not in result or code in release_receipt_codes:
            raise CandidateError(f"release source receipt jurisdiction is duplicate/unknown: {code!r}")
        relative = str(
            descriptor.get("relative_path") or descriptor.get("path") or ""
        )
        target = _confined_release_file(
            root, relative, label=f"{code} embedded source receipt"
        )
        receipt, receipt_bytes, observed_sha256 = load_json_mapping_snapshot(
            target, label=f"{code} embedded source receipt"
        )
        if receipt.get("jurisdiction") != code:
            raise CandidateError(f"{code} embedded source receipt is mislabeled")
        if (
            observed_sha256 != descriptor.get("sha256")
            or len(receipt_bytes) != descriptor.get("size_bytes")
        ):
            raise CandidateError(f"{code} embedded source receipt digest drifted")
        release_receipt_codes.add(code)
        result[code].update(
            {
                "source_receipt": receipt,
                "source_receipt_digest_sha256": digest_payload(receipt),
                "source_receipt_path": relative,
                "source_receipt_sha256": observed_sha256,
            }
        )
    if release_receipt_codes != set(expected):
        raise CandidateError("release embedded source receipts are not exact-51")

    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, Sequence) or isinstance(
        raw_artifacts, (str, bytes, bytearray)
    ):
        raise CandidateError("completed manifest artifacts are malformed")
    corpus_descriptors: list[Mapping[str, Any]] = []
    prefix = f"{CORPUS_DATA_DIR}/jurisdiction/"
    for descriptor in raw_artifacts:
        if not isinstance(descriptor, Mapping):
            raise CandidateError("completed manifest contains a non-object artifact")
        relative = str(
            descriptor.get("relative_path") or descriptor.get("path") or ""
        )
        is_parent_corpus = relative.startswith(prefix)
        claims_parent_schema = descriptor.get("schema_id") == CORPUS_ROW_SCHEMA_VERSION
        if is_parent_corpus != claims_parent_schema:
            raise CandidateError(
                f"parent corpus descriptor path/schema mismatch: {relative!r}"
            )
        if is_parent_corpus:
            corpus_descriptors.append(descriptor)
    if not corpus_descriptors:
        raise CandidateError("completed release has no parent corpus shards")
    corpus_descriptors.sort(
        key=lambda item: str(item.get("relative_path") or item.get("path") or "")
    )
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise CandidateError("pyarrow is required for exact corpus closure") from exc
    expected_document_index = 0
    previous_global_key: tuple[str, str] | None = None
    for position, descriptor in enumerate(corpus_descriptors):
        relative = str(
            descriptor.get("relative_path") or descriptor.get("path") or ""
        )
        parts = Path(relative).parts
        if len(parts) < 5 or parts[:3] != ("data", "corpus", "jurisdiction"):
            raise CandidateError(f"parent corpus shard path is malformed: {relative!r}")
        code = parts[3].strip().upper()
        metadata = descriptor.get("metadata")
        if (
            code not in result
            or descriptor.get("family") != "corpus"
            or not isinstance(metadata, Mapping)
            or metadata.get("jurisdiction_code") != code
        ):
            raise CandidateError(f"parent corpus shard {relative!r} is mislabeled")
        target = _confined_release_file(
            root, relative, label=f"{code} parent corpus shard"
        )
        with _open_regular_file_nofollow(
            target, label=f"{code} parent corpus shard"
        ) as shard_handle:
            observed_sha256 = _open_handle_sha256(shard_handle)
            observed_size = os.fstat(shard_handle.fileno()).st_size
            if (
                observed_sha256 != descriptor.get("sha256")
                or observed_size != descriptor.get("size_bytes")
            ):
                raise CandidateError(f"{code} parent corpus shard digest drifted")
            parquet = pq.ParquetFile(shard_handle)
            schema_metadata = parquet.schema_arrow.metadata or {}
            if schema_metadata.get(b"schema_version", b"").decode(
                "utf-8", errors="strict"
            ) != CORPUS_ROW_SCHEMA_VERSION:
                raise CandidateError(f"{code} parent corpus shard schema drifted")
            rows = [
                dict(item)
                for batch in parquet.iter_batches()
                for item in batch.to_pylist()
            ]
        if len(rows) != int(descriptor.get("row_count", -1)):
            raise CandidateError(f"{code} parent corpus shard row count drifted")
        keys: list[str] = []
        for local_position, row in enumerate(rows):
            row_code = str(row.get("jurisdiction") or "").strip().upper()
            direct_code = str(row.get("jurisdiction_code") or "").strip().upper()
            key = str(row.get("entry_cid") or "")
            document_index = row.get("document_index")
            valid_document_index = (
                isinstance(document_index, int)
                and not isinstance(document_index, bool)
                and document_index == expected_document_index
            )
            if (
                row_code != code
                or direct_code != code
                or not key
                or not valid_document_index
                or row.get("acquisition_receipt_id")
                != result[code]["source_receipt"].get("receipt_id")
            ):
                raise CandidateError(
                    f"{code} parent corpus row {local_position} is redistributed/mislabeled"
                )
            global_key = (code, key)
            if previous_global_key is not None and previous_global_key >= global_key:
                raise CandidateError("release parent corpus keys are duplicated or unordered")
            previous_global_key = global_key
            expected_document_index += 1
            keys.append(key)
            result[code]["rows"].append(
                _normalized_corpus_row(
                    row, label=f"{code} release row {document_index}"
                )
            )
            result[code]["entry_cids"].append(key)
        if (
            not keys
            or descriptor.get("first_key") != keys[0]
            or descriptor.get("last_key") != keys[-1]
        ):
            raise CandidateError(f"{code} parent corpus shard key range drifted")
        result[code]["corpus_shards"].append(
            {
                "first_key": keys[0],
                "last_key": keys[-1],
                "relative_path": relative,
                "row_count": len(rows),
                "sha256": observed_sha256,
            }
        )
    if any(not result[code]["rows"] for code in expected):
        raise CandidateError("release parent corpus shards do not cover exact-51")
    return result


def _bind_exact_corpus_closure(
    input_by_code: Mapping[str, Mapping[str, Any]],
    release_by_code: Mapping[str, Mapping[str, Any]],
    *,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Require byte/key/receipt equality, not merely equal aggregate totals."""

    expected = tuple(CANONICAL_JURISDICTION_ORDER)
    if tuple(input_by_code) != expected or tuple(release_by_code) != expected:
        raise CandidateError("input/release corpus closure is not canonical exact-51")
    per_jurisdiction: list[dict[str, Any]] = []
    input_union_rows: list[dict[str, Any]] = []
    release_union_rows: list[dict[str, Any]] = []
    input_receipts: list[Mapping[str, Any]] = []
    release_receipts: list[Mapping[str, Any]] = []
    release_receipt_bindings: dict[str, dict[str, Any]] = {}
    for code in expected:
        selected = input_by_code[code]
        produced = release_by_code[code]
        input_rows = list(selected.get("rows") or [])
        release_rows = list(produced.get("rows") or [])
        input_keys = list(selected.get("entry_cids") or [])
        release_keys = list(produced.get("entry_cids") or [])
        input_receipt = selected.get("source_receipt")
        release_receipt = produced.get("source_receipt")
        if not isinstance(input_receipt, Mapping) or not isinstance(
            release_receipt, Mapping
        ):
            raise CandidateError(f"{code} source receipt closure is missing")
        if dict(input_receipt) != dict(release_receipt):
            raise CandidateError(
                f"{code} output/input source-receipt digest or content mismatched"
            )
        if input_keys != release_keys or input_rows != release_rows:
            raise CandidateError(
                f"{code} release corpus differs from selected input rows/keys"
            )
        if len(input_keys) != len(set(input_keys)) or len(input_rows) != len(input_keys):
            raise CandidateError(f"{code} selected input has duplicate/missing corpus keys")
        dispositions = selected.get("adapter_dispositions")
        expected_dispositions = {
            "admitted": len(input_rows),
            "quarantined": 0,
            "rejected": 0,
        }
        if dispositions != expected_dispositions:
            raise CandidateError(f"{code} adapter dispositions are not fully admitted")
        shards = produced.get("corpus_shards")
        if not isinstance(shards, list) or not shards:
            raise CandidateError(f"{code} release corpus shards are missing")
        if sum(int(item.get("row_count", -1)) for item in shards) != len(input_rows):
            raise CandidateError(f"{code} release shard rows do not close")
        input_key_digest = digest_payload({"entry_cids": input_keys})
        release_key_digest = digest_payload({"entry_cids": release_keys})
        input_row_digest = digest_payload(input_rows)
        release_row_digest = digest_payload(release_rows)
        receipt_digest = digest_payload(dict(input_receipt))
        if produced.get("source_receipt_digest_sha256") != receipt_digest:
            raise CandidateError(f"{code} embedded source-receipt digest mismatched")
        per_jurisdiction.append(
            {
                "adapter_dispositions": expected_dispositions,
                "admitted_row_count": len(input_rows),
                "input_corpus_rows_digest_sha256": input_row_digest,
                "input_entry_cids_digest_sha256": input_key_digest,
                "jurisdiction": code,
                "release_corpus_rows_digest_sha256": release_row_digest,
                "release_corpus_shards": shards,
                "release_corpus_shards_digest_sha256": digest_payload(shards),
                "release_entry_cids_digest_sha256": release_key_digest,
            }
        )
        release_receipt_bindings[code] = {
            "release_source_receipt_digest_sha256": receipt_digest,
            "release_source_receipt_path": str(
                produced.get("source_receipt_path") or ""
            ),
            "release_source_receipt_sha256": _require_sha256(
                produced.get("source_receipt_sha256"),
                label=f"{code} embedded source receipt file digest",
            ),
        }
        input_union_rows.extend(input_rows)
        release_union_rows.extend(release_rows)
        input_receipts.append(dict(input_receipt))
        release_receipts.append(dict(release_receipt))

    input_union_rows.sort(
        key=lambda item: (str(item["jurisdiction"]), str(item["entry_cid"]))
    )
    release_union_rows.sort(
        key=lambda item: (str(item["jurisdiction"]), str(item["entry_cid"]))
    )
    input_union_keys = [str(item["entry_cid"]) for item in input_union_rows]
    release_union_keys = [str(item["entry_cid"]) for item in release_union_rows]
    if (
        input_union_rows != release_union_rows
        or input_union_keys != release_union_keys
        or len(input_union_keys) != len(set(input_union_keys))
    ):
        raise CandidateError("deduped union differs from selected exact-51 input")
    counts = manifest.get("counts")
    parity = manifest.get("key_parity")
    if not isinstance(counts, Mapping) or not isinstance(parity, Mapping):
        raise CandidateError("production manifest lacks corpus count/key parity")
    union_count = len(input_union_keys)
    union_key_digest = digest_payload({"parent_entry_cids": sorted(input_union_keys)})
    if (
        counts.get("corpus_documents") != union_count
        or parity.get("parent_entry_cid_count") != union_count
        or parity.get("parent_entry_cids_sha256") != union_key_digest
    ):
        raise CandidateError(
            "production manifest parent corpus count/key digest differs from selected input"
        )
    input_receipts_digest = digest_payload({"source_receipts": input_receipts})
    release_receipts_digest = digest_payload({"source_receipts": release_receipts})
    if input_receipts_digest != release_receipts_digest:
        raise CandidateError("output/input source-receipt set digest mismatched")
    return {
        "input_source_receipts_digest_sha256": input_receipts_digest,
        "release_source_receipt_bindings": release_receipt_bindings,
        "release_source_receipts_digest_sha256": release_receipts_digest,
        "union": {
            "deduped_corpus_rows_digest_sha256": digest_payload(input_union_rows),
            "deduped_entry_cids_digest_sha256": union_key_digest,
            "deduped_union_count": union_count,
            "duplicate_row_count": 0,
            "input_source_receipts_digest_sha256": input_receipts_digest,
            "per_jurisdiction": per_jurisdiction,
            "release_source_receipts_digest_sha256": release_receipts_digest,
            "shard_sum_before_dedup": len(input_union_rows),
        },
    }


_VOLATILE_REPLAY_FIELDS: Final = frozenset(
    {
        "acquisition_time",
        "checked_at",
        "completed_at",
        "created_at",
        "fetched_at",
        "observed_at",
        "observation_time",
        "retrieved_at",
        "sealed_at",
        "started_at",
    }
)


def _stable_replay_value(value: Any) -> Any:
    """Remove only verifier-event times from an otherwise exact projection."""

    if isinstance(value, Mapping):
        return {
            str(key): _stable_replay_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _VOLATILE_REPLAY_FIELDS
        }
    if isinstance(value, list):
        return [_stable_replay_value(item) for item in value]
    return value


def _stable_official_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Project canonical content while excluding receipt-event identities."""

    projected: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        for field in (
            "acquisition_receipt_id",
            "acquisition_time",
            "observed_at",
        ):
            row.pop(field, None)
        projected.append(row)
    projected.sort(
        key=lambda item: (str(item.get("jurisdiction") or ""), str(item.get("entry_cid") or ""))
    )
    return projected


def _stable_frontier_closure_projection(
    closure: Mapping[str, Any], *, code: str
) -> dict[str, Any]:
    """Keep only source-derived, replay-repeatable closure semantics.

    Receipt ids, canonical artifact hashes, and closure file addresses can
    legitimately change when a retained response set is reparsed in a fresh
    verifier generation.  The enumerator's completion/frontier material,
    canonical key binding, source identity, and terminal arithmetic must not.
    """

    completion = closure.get("completion_receipt")
    replayed = closure.get("replayed_frontier")
    canonical = closure.get("canonical_output_binding")
    if not all(isinstance(value, Mapping) for value in (completion, replayed, canonical)):
        raise CandidateError(f"{code} closure lacks replayable frontier semantics")
    stable_completion = _stable_replay_value(completion)
    if not isinstance(stable_completion, dict):  # pragma: no cover - guarded above
        raise CandidateError(f"{code} closure completion projection is malformed")
    # These values are injected by close_jurisdiction_frontier from the fresh
    # canonical file.  Exact selected/replayed row and key equality is checked
    # independently, so comparing their event-specific byte hashes would make
    # an honest retained replay non-repeatable.
    for field in (
        "adapter_input_sha256",
        "artifact_sha256",
        "canonical_artifact_sha256",
        "input_sha256",
        "source_checksum",
    ):
        stable_completion.pop(field, None)
    replay = stable_completion.get("replay")
    if isinstance(replay, dict):
        for field in (
            "admitted_body_sha256",
            "request_sha256",
            "response_sha256",
        ):
            replay.pop(field, None)
    return {
        "acquisition_path_ids": list(closure.get("acquisition_path_ids") or []),
        "canonical_output_binding": dict(canonical),
        "completion_receipt": stable_completion,
        "official_source_url": closure.get("official_source_url"),
        "replayed_frontier": _stable_replay_value(replayed),
        "source_software_version": closure.get("source_software_version"),
    }


def _retained_replay_comparison_projection(
    projection: Mapping[str, Any],
) -> dict[str, Any]:
    """Drop selected-generation byte addresses from a replay comparison."""

    raw = projection.get("jurisdictions")
    if not isinstance(raw, list):
        raise CandidateError("retained replay projection lacks jurisdictions")
    jurisdictions: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise CandidateError("retained replay projection has a non-object state")
        stable = dict(item)
        stable.pop("selected_evidence", None)
        jurisdictions.append(stable)
    return {
        "jurisdiction_count": projection.get("jurisdiction_count"),
        "jurisdictions": jurisdictions,
        "network_io_performed": projection.get("network_io_performed"),
        "schema_version": projection.get("schema_version"),
        "verifier_owned": projection.get("verifier_owned"),
    }


def _attested_dependency_site_packages() -> Path:
    """Return the one dependency root already imported by this verifier.

    ``-I`` deliberately omits the user site.  The refresh stack's binary and
    async dependencies are installed there in the production environment, so
    the bootstrap adds exactly that already-loaded directory, never an
    environment-supplied ``PYTHONPATH`` or a caller-selected import root.
    """

    try:
        import anyio
        import multiformats
        import pyarrow
    except ImportError as exc:
        raise CandidateError(
            "retained replay verifier dependencies are unavailable"
        ) from exc
    roots: set[Path] = set()
    for module in (anyio, multiformats, pyarrow):
        module_file = getattr(module, "__file__", None)
        if not module_file:
            raise CandidateError("retained replay dependency has no file identity")
        candidate = _lexical_absolute(module_file)
        for parent in candidate.parents:
            if parent.name in {"site-packages", "dist-packages"}:
                roots.add(_safe_existing_directory(parent, label="dependency site"))
                break
        else:
            raise CandidateError(
                "retained replay dependency is outside an installed package root"
            )
    if len(roots) != 1:
        raise CandidateError(
            "retained replay dependencies do not share one attested package root"
        )
    return roots.pop()


def _real_account_home() -> Path:
    """Resolve HOME from the effective uid, not from ambient environment."""

    try:
        raw = pwd.getpwuid(os.geteuid()).pw_dir
    except (KeyError, OSError) as exc:
        raise CandidateError("cannot resolve verifier account HOME") from exc
    return _safe_existing_directory(raw, label="verifier account HOME")


def _confined_evidence_file(root: Path, relative: Any, *, label: str) -> Path:
    raw = str(relative or "").strip()
    selected = Path(raw)
    if not raw or selected.is_absolute() or ".." in selected.parts:
        raise CandidateError(f"{label} is not a confined relative path")
    lexical = _lexical_absolute(root / selected)
    try:
        lexical.relative_to(root.absolute())
    except ValueError as exc:
        raise CandidateError(f"{label} escapes its jurisdiction evidence root") from exc
    cursor = Path(lexical.anchor)
    for component in lexical.parts[1:]:
        cursor /= component
        if cursor.is_symlink():
            raise CandidateError(f"{label} must not traverse a symlink: {cursor}")
    with _open_regular_file_nofollow(lexical, label=label):
        pass
    return lexical


def _address_matches_file(
    path: Path, address: Any, *, label: str
) -> tuple[bytes, str]:
    if not isinstance(address, Mapping):
        raise CandidateError(f"{label} lacks its content address")
    body = read_regular_file_bytes(path, label=label)
    digest = hashlib.sha256(body).hexdigest()
    declared_size = address.get("byte_size")
    if (
        address.get("sha256") != digest
        or isinstance(declared_size, bool)
        or not isinstance(declared_size, int)
        or declared_size != len(body)
    ):
        raise CandidateError(f"{label} content address differs from exact bytes")
    return body, digest


def _load_addressed_json_mapping(
    path: Path, address: Any, *, label: str
) -> tuple[dict[str, Any], str]:
    """Verify, hash, and parse one content-addressed JSON byte snapshot."""

    serialized, digest = _address_matches_file(path, address, label=label)
    return load_json_mapping_bytes(serialized, label=label), digest


def _closure_input_for_raw_receipt(
    *,
    jurisdiction_root: Path,
    raw_receipt: Mapping[str, Any],
    code: str,
) -> tuple[Path, dict[str, Any]]:
    """Find the unique content-addressed closure input that generated a receipt."""

    closure_dir = _safe_existing_directory(
        jurisdiction_root / "frontiers" / "closure-inputs",
        label=f"{code} retained closure-input directory",
    )
    matches: list[tuple[Path, dict[str, Any]]] = []
    for candidate in sorted(closure_dir.iterdir(), key=lambda item: item.name):
        if candidate.suffix != ".json" or _SHA256_RE.fullmatch(candidate.stem) is None:
            continue
        serialized = read_regular_file_bytes(
            candidate, label=f"{code} retained closure input"
        )
        if hashlib.sha256(serialized).hexdigest() != candidate.stem:
            raise CandidateError(f"{code} closure-input filename digest drifted")
        closure = load_json_mapping_bytes(
            serialized, label=f"{code} retained closure input"
        )
        completion = closure.get("completion_receipt")
        binding = closure.get("canonical_output_binding")
        if not isinstance(completion, Mapping) or not isinstance(binding, Mapping):
            continue
        if (
            str(completion.get("jurisdiction") or "").strip().upper() != code
            or completion.get("index_keys") != raw_receipt.get("index_keys")
            or completion.get("disposition") != raw_receipt.get("disposition")
            or binding.get("canonical_row_count")
            != raw_receipt.get("canonical_row_count")
        ):
            continue
        raw_catalog_evidence = raw_receipt.get("source_catalog_evidence")
        completion_catalog_evidence = completion.get("source_catalog_evidence")
        if (
            (
                raw_catalog_evidence is not None
                or completion_catalog_evidence is not None
            )
            and (
                not isinstance(raw_catalog_evidence, Mapping)
                or not isinstance(completion_catalog_evidence, Mapping)
                or canonical_json_bytes(raw_catalog_evidence)
                != canonical_json_bytes(completion_catalog_evidence)
            )
        ):
            continue
        raw_frontier = dict(raw_receipt.get("frontier") or {})
        completion_frontier = dict(completion.get("frontier") or {})
        raw_frontier.pop("frontier_digest_sha256", None)
        completion_frontier.pop("frontier_digest_sha256", None)
        replayed_frontier = dict(closure.get("replayed_frontier") or {})
        replayed_frontier.pop("frontier_digest_sha256", None)
        if raw_frontier != completion_frontier or raw_frontier != replayed_frontier:
            continue
        matches.append((candidate, closure))
    if len(matches) != 1:
        raise CandidateError(
            f"{code} raw receipt must bind exactly one retained closure input; "
            f"matches={len(matches)}"
        )
    return matches[0]


def _derive_retained_frontier_projection(
    prepared: Any,
    corpus_closure: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Reopen raw closure, ledger, fetch, and object bytes for exact-51."""

    bindings = {item.jurisdiction: item for item in prepared.bindings}
    expected = tuple(CANONICAL_JURISDICTION_ORDER)
    if tuple(bindings) != expected or tuple(corpus_closure) != expected:
        raise CandidateError("retained frontier projection is not canonical exact-51")
    projections: list[dict[str, Any]] = []
    for code in expected:
        binding = bindings[code]
        normalized_path = binding.normalized_source_receipt_path
        normalized, _, _ = load_bound_json_mapping_snapshot(
            normalized_path,
            expected_sha256=binding.normalized_source_receipt_sha256,
            label=f"{code} normalized source receipt",
        )
        payload = normalized.get("payload")
        if not isinstance(payload, Mapping):
            raise CandidateError(f"{code} normalized receipt lacks its raw binding")
        legacy_digest = _require_sha256(
            payload.get("legacy_receipt_sha256"),
            label=f"{code} legacy receipt digest",
        )
        raw_path = normalized_path.with_name(f"{legacy_digest}.json")
        raw_receipt, _, _ = load_bound_json_mapping_snapshot(
            raw_path,
            expected_sha256=legacy_digest,
            label=f"{code} raw closure receipt",
        )
        jurisdiction_root = _safe_existing_directory(
            raw_path.parent.parent, label=f"{code} jurisdiction evidence root"
        )
        closure_path, closure = _closure_input_for_raw_receipt(
            jurisdiction_root=jurisdiction_root,
            raw_receipt=raw_receipt,
            code=code,
        )
        aggregate = raw_receipt.get("frontier_aggregate")
        if not isinstance(aggregate, Mapping):
            raise CandidateError(f"{code} raw receipt lacks frontier_aggregate")
        request_path = _confined_evidence_file(
            jurisdiction_root,
            aggregate.get("request_ledger_relative_path"),
            label=f"{code} request ledger",
        )
        response_path = _confined_evidence_file(
            jurisdiction_root,
            aggregate.get("response_ledger_relative_path"),
            label=f"{code} response ledger",
        )
        requests, request_sha = _load_addressed_json_mapping(
            request_path, aggregate.get("request_ledger"), label=f"{code} request ledger"
        )
        responses, response_sha = _load_addressed_json_mapping(
            response_path, aggregate.get("response_ledger"), label=f"{code} response ledger"
        )
        hashes = raw_receipt.get("hashes")
        replay = raw_receipt.get("replay")
        if (
            not isinstance(hashes, Mapping)
            or not isinstance(replay, Mapping)
            or hashes.get("request_sha256") != request_sha
            or hashes.get("response_sha256") != response_sha
            or replay.get("request_sha256") != request_sha
            or replay.get("response_sha256") != response_sha
        ):
            raise CandidateError(f"{code} raw receipt ledger digest binding drifted")
        request_rows = requests.get("requests")
        response_rows = responses.get("responses")
        if (
            requests.get("jurisdiction") != code
            or responses.get("jurisdiction") != code
            or not isinstance(request_rows, list)
            or not isinstance(response_rows, list)
            or not request_rows
            or len(request_rows) != len(response_rows)
        ):
            raise CandidateError(f"{code} retained request/response ledgers do not close")
        request_ids: dict[str, Mapping[str, Any]] = {}
        for row in request_rows:
            if not isinstance(row, Mapping):
                raise CandidateError(f"{code} request ledger contains a non-object")
            receipt_sha = _require_sha256(
                row.get("acquisition_receipt_sha256"),
                label=f"{code} request acquisition receipt",
            )
            if receipt_sha in request_ids:
                raise CandidateError(f"{code} request ledger repeats an acquisition receipt")
            if not isinstance(row.get("sanitized_request"), Mapping):
                raise CandidateError(f"{code} request ledger lacks sanitized request bytes")
            request_ids[receipt_sha] = row
        stable_responses: list[dict[str, Any]] = []
        body_hashes: list[str] = []
        for row in response_rows:
            if not isinstance(row, Mapping):
                raise CandidateError(f"{code} response ledger contains a non-object")
            receipt_sha = _require_sha256(
                row.get("acquisition_receipt_sha256"),
                label=f"{code} response acquisition receipt",
            )
            request = request_ids.pop(receipt_sha, None)
            content = row.get("content")
            if request is None or not isinstance(content, Mapping):
                raise CandidateError(f"{code} response ledger does not match requests")
            if row.get("endpoint") != request.get("endpoint"):
                raise CandidateError(f"{code} request/response endpoint drifted")
            body_path = _confined_evidence_file(
                jurisdiction_root,
                row.get("body_relative_path"),
                label=f"{code} retained response body",
            )
            _, body_sha = _address_matches_file(
                body_path, content, label=f"{code} retained response body"
            )
            body_hashes.append(body_sha)
            stable_responses.append(
                {
                    "body_relative_path": str(row.get("body_relative_path") or ""),
                    "content": dict(content),
                    "endpoint": row.get("endpoint"),
                    "outcome_kind": row.get("outcome_kind"),
                    "response_status": row.get("response_status"),
                    "sanitized_request": dict(request["sanitized_request"]),
                    "transport_receipt": _stable_replay_value(
                        row.get("transport_receipt")
                    ),
                }
            )
        if request_ids:
            raise CandidateError(f"{code} request ledger has unmatched entries")
        stable_responses.sort(
            key=lambda item: (
                str(item["endpoint"]),
                canonical_json_bytes(item["sanitized_request"]),
                str(item["content"].get("sha256") or ""),
            )
        )
        closure_binding = closure.get("canonical_output_binding")
        if not isinstance(closure_binding, Mapping):
            raise CandidateError(f"{code} closure input lacks canonical output binding")
        corpus_rows = _stable_official_rows(
            list(corpus_closure[code].get("rows") or [])
        )
        corpus_keys = [str(row.get("entry_cid") or "") for row in corpus_rows]
        run_seal, _, run_seal_sha256 = load_bound_json_mapping_snapshot(
            binding.run_seal_path,
            expected_sha256=binding.run_seal_sha256,
            label=f"{code} run seal",
        )
        state_binding = dict((run_seal.get("states") or {}).get(code) or {})
        stable_run_binding = {
            "canonical_jsonld_sha256": state_binding.get("canonical_jsonld_sha256"),
            "normalized_source_receipt_sha256": state_binding.get(
                "normalized_source_receipt_sha256"
            ),
            "runner_end_identity": run_seal.get("runner_end_identity"),
            "runner_start_identity": run_seal.get("runner_start_identity"),
            "source_software_version": state_binding.get("source_software_version"),
        }
        terminal = _stable_frontier_closure_projection(closure, code=code)
        projections.append(
            {
                "acquisition_path_ids": list(payload.get("acquisition_path_ids") or []),
                "canonical_row_count": len(corpus_rows),
                "content_body_hashes_digest_sha256": digest_payload(sorted(body_hashes)),
                "corpus_entry_cids_digest_sha256": digest_payload(
                    {"entry_cids": corpus_keys}
                ),
                "corpus_rows_digest_sha256": digest_payload(corpus_rows),
                "jurisdiction": code,
                "official_source_url": normalized.get("official_source_url"),
                "request_ledger_sha256": request_sha,
                "response_ledger_sha256": response_sha,
                "response_projection_digest_sha256": digest_payload(stable_responses),
                "runner_identity_binding": {
                    "runner_end_identity": stable_run_binding["runner_end_identity"],
                    "runner_start_identity": stable_run_binding["runner_start_identity"],
                    "source_software_version": stable_run_binding[
                        "source_software_version"
                    ],
                },
                "selected_evidence": {
                    "canonical_jsonld_sha256": binding.canonical_jsonld_sha256,
                    "closure_input_sha256": closure_path.stem,
                    "legacy_receipt_sha256": legacy_digest,
                    "normalized_source_receipt_sha256": (
                        binding.normalized_source_receipt_sha256
                    ),
                    "run_seal_canonical_jsonld_sha256": stable_run_binding[
                        "canonical_jsonld_sha256"
                    ],
                    "run_seal_normalized_source_receipt_sha256": stable_run_binding[
                        "normalized_source_receipt_sha256"
                    ],
                    "run_seal_sha256": run_seal_sha256,
                    "selected_corpus_rows_digest_sha256": digest_payload(
                        list(corpus_closure[code].get("rows") or [])
                    ),
                    "selected_entry_cids_digest_sha256": digest_payload(
                        {"entry_cids": corpus_keys}
                    ),
                },
                "source_software_version": normalized.get("source_software_version"),
                "start_urls": list(normalized.get("start_urls") or []),
                "terminal_projection_digest_sha256": digest_payload(terminal),
            }
        )
    return {
        "jurisdiction_count": len(projections),
        "jurisdictions": projections,
        "jurisdictions_digest_sha256": digest_payload(projections),
        "network_io_performed": False,
        "schema_version": "state-laws-verifier-retained-replay/v1",
        "verifier_owned": True,
    }


def _require_complete_transport_inventory(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise CandidateError("retained replay transport-bypass inventory is missing")
    jurisdictions = value.get("jurisdictions")
    if not isinstance(jurisdictions, Mapping):
        raise CandidateError("retained replay transport inventory is malformed")
    expected = list(CANONICAL_JURISDICTION_ORDER)
    if (
        value.get("schema_version")
        != "state-laws-registered-transport-bypass-inventory-v1"
        or value.get("candidate_count") != 0
        or value.get("complete") is not True
        or value.get("publication_evidence_complete") is not True
        or value.get("jurisdiction_count") != EXPECTED_JURISDICTION_COUNT
        or list(jurisdictions) != expected
        or value.get("gap_jurisdictions") != []
        or value.get("closure_projection_missing_jurisdictions") != []
        or any(
            not isinstance(jurisdictions.get(code), Mapping)
            or jurisdictions[code].get("candidate_count") != 0
            or jurisdictions[code].get("complete") is not True
            or jurisdictions[code].get("closure_projection_producer_present")
            is not True
            for code in expected
        )
    ):
        raise CandidateError(
            "retained replay has a parser-reachable transport bypass"
        )


def _parse_retained_replay_result(stdout: str) -> dict[str, Any]:
    """Reject a zero-exit partial refresh and bind its exact verifier plan."""

    try:
        value = json.loads(
            stdout,
            object_pairs_hook=_json_value_without_duplicate_keys,
        )
    except CandidateError:
        raise
    except json.JSONDecodeError as exc:
        raise CandidateError(
            "verifier retained replay stdout is not one strict JSON result"
        ) from exc
    if not isinstance(value, dict):
        raise CandidateError("verifier retained replay result must be an object")
    if value.get("status") != "success":
        raise CandidateError(
            "verifier retained replay did not report exact success: "
            f"{value.get('status')!r}"
        )
    expected = list(CANONICAL_JURISDICTION_ORDER)
    plan = value.get("plan")
    if not isinstance(plan, Mapping) or (
        plan.get("requested_states") != expected
        or plan.get("requested_state_count") != EXPECTED_JURISDICTION_COUNT
        or plan.get("states") != expected
        or plan.get("state_count") != EXPECTED_JURISDICTION_COUNT
        or plan.get("skipped_completed_states") != []
        or plan.get("skipped_completed_count") != 0
        or plan.get("scrape") is not True
        or plan.get("strict_acquisition_evidence") is not True
        or plan.get("retained_replay_only") is not True
        or plan.get("publish_to_hf") is not False
        or plan.get("merge_hf_existing") is not False
        or plan.get("startup_stale_sync") is not False
        or plan.get("incremental_state_publish") is not False
    ):
        raise CandidateError("verifier retained replay plan is not fixed exact-51")
    _require_complete_transport_inventory(plan.get("transport_bypass_inventory"))
    acquisition = value.get("acquisition_evidence")
    build = value.get("build")
    if not isinstance(acquisition, Mapping) or not isinstance(build, Mapping):
        raise CandidateError("verifier retained replay completion surfaces are missing")
    if (
        value.get("scrape_gap_states") != []
        or value.get("build_gap_states") != []
        or build.get("missing_jsonld_states") != []
        or acquisition.get("strict") is not True
        or acquisition.get("retained_replay_only") is not True
        or acquisition.get("aggregate_closed_count")
        != EXPECTED_JURISDICTION_COUNT
        or acquisition.get("evidence_gap_states") != []
        or acquisition.get("authorizing_for_publication") is not True
        or acquisition.get("transport_bypass_inventory")
        != plan.get("transport_bypass_inventory")
    ):
        raise CandidateError("verifier retained replay is incomplete or nonauthorizing")
    return value


def _strict_retained_fetch_evidence_hashes(
    entries: Sequence[Any], *, jurisdiction: str
) -> dict[Path, str]:
    """Strict-load every selected raw fetch receipt and pin its initial hash."""

    snapshots: dict[Path, str] = {}
    for entry in entries:
        evidence_path = Path(entry.evidence_path)
        _, _, evidence_sha256 = load_json_mapping_snapshot(
            evidence_path,
            label=f"{jurisdiction} retained fetch evidence",
        )
        previous = snapshots.setdefault(evidence_path, evidence_sha256)
        if previous != evidence_sha256:
            raise CandidateError(
                f"{jurisdiction} retained fetch evidence identity is ambiguous"
            )
    return snapshots


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    """Stop the worker and any parser subprocesses in its private session."""

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        if process.poll() is not None:
            return
        try:
            process.kill()
        except OSError:
            pass


def _run_bounded_retained_replay_subprocess(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float = _RETAINED_REPLAY_TIMEOUT_SECONDS,
    output_limit_bytes: int = _RETAINED_REPLAY_OUTPUT_LIMIT_BYTES,
) -> tuple[int, bytes, str]:
    """Run the worker while enforcing a live combined stdout/stderr budget."""

    if timeout_seconds <= 0 or output_limit_bytes <= 0:
        raise CandidateError("verifier retained replay subprocess bounds are invalid")
    try:
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            env=dict(environment),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            start_new_session=True,
        )
    except OSError as exc:
        raise CandidateError(
            "verifier-owned exact-51 retained replay could not start"
        ) from exc
    if process.stdout is None or process.stderr is None:  # pragma: no cover
        _kill_process_group(process)
        process.wait()
        raise CandidateError("verifier retained replay pipes are unavailable")

    selector = selectors.DefaultSelector()
    stdout = bytearray()
    stderr_tail = bytearray()
    total = 0
    deadline = time.monotonic() + float(timeout_seconds)
    streams = ((process.stdout, "stdout"), (process.stderr, "stderr"))
    try:
        for stream, name in streams:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_process_group(process)
                raise CandidateError(
                    "verifier-owned exact-51 retained replay timed out: "
                    + stderr_tail.decode("utf-8", errors="replace")
                )
            for key, _ in selector.select(timeout=min(remaining, 0.25)):
                try:
                    chunk = os.read(key.fileobj.fileno(), 64 * 1024)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                total += len(chunk)
                if total > output_limit_bytes:
                    _kill_process_group(process)
                    raise CandidateError(
                        "verifier retained replay subprocess output exceeded its bound"
                    )
                if key.data == "stdout":
                    stdout.extend(chunk)
                else:
                    stderr_tail.extend(chunk)
                    if len(stderr_tail) > 2000:
                        del stderr_tail[:-2000]
        returncode = process.wait(timeout=max(0.1, deadline - time.monotonic()))
        return (
            returncode,
            bytes(stdout),
            stderr_tail.decode("utf-8", errors="replace"),
        )
    except subprocess.TimeoutExpired as exc:
        _kill_process_group(process)
        raise CandidateError(
            "verifier-owned exact-51 retained replay timed out: "
            + stderr_tail.decode("utf-8", errors="replace")
        ) from exc
    finally:
        selector.close()
        if process.poll() is None:
            _kill_process_group(process)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        for stream, _ in streams:
            if not stream.closed:
                stream.close()


def _verifier_phase_bound_seed_selection(
    *,
    scraper: Any,
    ledger: Any,
    code: str,
) -> tuple[tuple[str, ...], Path | None]:
    """Resolve one current-scraper-validated live phase plan for verifier seeding.

    The generic retained ledger deliberately cannot choose between different
    bodies for one exact request.  Shared official-frontier scrapers have a
    narrower selector: their original live closure binds each helper call to
    an immutable receipt in ``first``/``replay`` order and rejects competing
    live histories.  Reuse that current scraper validator here, then retain
    only one content-addressed original-live closure as the replay selector.
    """

    attach = getattr(scraper, "attach_state_law_acquisition_ledger", None)
    load_phase = getattr(
        scraper, "_bound_shared_official_frontier_replay_plan", None
    )
    if not callable(attach) or not callable(load_phase):
        raise CandidateError(
            f"{code} current scraper lacks phase-bound retained replay support"
        )
    attach(ledger)
    try:
        first = load_phase(phase="first")
        replay = load_phase(phase="replay")
    except RuntimeError as exc:
        raise CandidateError(
            f"{code} shared-frontier phase plan is not uniquely replayable: {exc}"
        ) from exc

    if first is None and replay is None:
        return (), None
    if (
        not isinstance(first, list)
        or not first
        or not isinstance(replay, list)
        or not replay
    ):
        raise CandidateError(
            f"{code} shared-frontier phase plan omitted one traversal"
        )

    expected_receipts: dict[str, tuple[str, ...]] = {}
    bound_receipts: set[str] = set()
    for phase, rows in (("first", first), ("replay", replay)):
        phase_receipts: list[str] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise CandidateError(
                    f"{code} shared-frontier {phase} plan has a non-object input"
                )
            receipt_sha256 = _require_sha256(
                row.get("receipt_sha256"),
                label=f"{code} shared-frontier {phase} receipt",
            )
            phase_receipts.append(receipt_sha256)
            bound_receipts.add(receipt_sha256)
        expected_receipts[phase] = tuple(phase_receipts)

    closure_dir = Path(ledger.closure_inputs_dir)
    live_selectors: list[Path] = []
    for candidate in sorted(closure_dir.glob("*.json"), key=lambda item: item.name):
        try:
            source = ledger.resolve_frontier_closure_projection_path(candidate)
            closure = ledger._load_frontier_closure_projection(source)
        except Exception as exc:
            raise CandidateError(
                f"{code} phase-bound closure selector failed fixity"
            ) from exc
        completion = closure.get("completion_receipt")
        if not isinstance(completion, Mapping):
            continue
        catalog = completion.get("source_catalog_evidence")
        if not isinstance(catalog, Mapping):
            continue
        first_observation = catalog.get("first_observation")
        replay_observation = catalog.get("replay_observation")
        if not isinstance(first_observation, Mapping) or not isinstance(
            replay_observation, Mapping
        ):
            continue
        if (
            first_observation.get("retained_replay"),
            replay_observation.get("retained_replay"),
        ) != (False, False):
            continue
        observed_receipts: dict[str, tuple[str, ...]] = {}
        malformed = False
        for phase, observation in (
            ("first", first_observation),
            ("replay", replay_observation),
        ):
            raw_inputs = observation.get("retained_parser_inputs")
            if not isinstance(raw_inputs, list) or not raw_inputs:
                malformed = True
                break
            phase_receipts = []
            for raw_input in raw_inputs:
                if not isinstance(raw_input, Mapping):
                    malformed = True
                    break
                receipt_sha256 = str(
                    raw_input.get("receipt_sha256") or ""
                ).strip().lower()
                phase_receipts.append(receipt_sha256)
            if malformed:
                break
            observed_receipts[phase] = tuple(phase_receipts)
        if not malformed and observed_receipts == expected_receipts:
            live_selectors.append(Path(source))

    if not live_selectors:
        raise CandidateError(
            f"{code} phase-bound plan lacks its original live closure selector"
        )
    return tuple(sorted(bound_receipts)), min(
        live_selectors, key=lambda item: item.name
    )


def _hardlink_verifier_phase_selector(
    *,
    source: Path,
    destination_root: Path,
    code: str,
) -> Path:
    """Hardlink one digest-named live closure into the isolated verifier root."""

    source_bytes = read_regular_file_bytes(
        source, label=f"{code} live phase closure selector"
    )
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    if source.name != f"{source_sha256}.json":
        raise CandidateError(
            f"{code} live phase closure selector filename failed fixity"
        )
    jurisdiction_root = _safe_existing_directory(
        destination_root / code,
        label=f"{code} verifier jurisdiction evidence root",
    )
    selector_dir = jurisdiction_root / "frontiers" / "closure-inputs"
    if selector_dir.exists() and (
        selector_dir.is_symlink() or not selector_dir.is_dir()
    ):
        raise CandidateError(
            f"{code} verifier closure selector directory is invalid"
        )
    selector_dir.mkdir(parents=True, exist_ok=True)
    if selector_dir.is_symlink() or not selector_dir.is_dir():
        raise CandidateError(
            f"{code} verifier closure selector directory is invalid"
        )
    destination = selector_dir / source.name
    if destination.exists() or destination.is_symlink():
        raise CandidateError(
            f"{code} verifier closure selector destination already exists"
        )
    try:
        os.link(source, destination, follow_symlinks=False)
    except OSError as exc:
        raise CandidateError(
            f"{code} verifier closure selector could not be hardlinked"
        ) from exc
    destination_bytes = read_regular_file_bytes(
        destination, label=f"{code} verifier live phase closure selector"
    )
    source_stat = source.stat(follow_symlinks=False)
    destination_stat = destination.stat(follow_symlinks=False)
    if (
        destination_bytes != source_bytes
        or source_stat.st_dev != destination_stat.st_dev
        or source_stat.st_ino != destination_stat.st_ino
    ):
        raise CandidateError(
            f"{code} verifier closure selector is not the source hardlink"
        )
    return destination


def _verifier_owned_retained_replay(
    *,
    prepared: Any,
    selected_corpus_closure: Mapping[str, Mapping[str, Any]],
    selected_projection: Mapping[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    """Regenerate exact-51 from a verifier-seeded, zero-network retained replay."""

    try:
        from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
            StateLawMultiFetchAcquisitionLedger,
        )
        from ipfs_datasets_py.processors.legal_data.state_laws_retained_evidence_seed import (
            seed_retained_evidence_generation,
        )
        from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
            US_STATES,
        )
        from ipfs_datasets_py.processors.legal_scrapers.state_scrapers import (
            get_scraper_for_state,
        )
        from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.retained_replay_isolated_worker import (
            EVIDENCE_ROOT_ENV,
            FETCH_CACHE_DIR_ENV,
            PAGE_CACHE_DIR_ENV,
            authorize_hardlink_only_seed,
            build_host_retained_replay_command,
            build_host_retained_replay_environment,
            local_state_laws_root,
        )
        from scripts.ops.legal_data import (
            assemble_state_laws_production_input_map as input_assembler,
        )
    except ImportError as exc:
        raise CandidateError("retained-replay verifier dependencies are unavailable") from exc

    bindings = {item.jurisdiction: item for item in prepared.bindings}
    expected = tuple(CANONICAL_JURISDICTION_ORDER)
    if tuple(bindings) != expected:
        raise CandidateError("retained replay selected bindings are not exact-51")
    # The shared v2 preparer has already anchored relative map roots against
    # the input-map directory and confined every receipt/seal to them.  Consume
    # those resolved typed bindings rather than resolving caller JSON again
    # against this process's current working directory.
    source_roots = sorted(
        {
            _safe_existing_directory(root, label="acquisition evidence root")
            for binding in prepared.bindings
            for root in binding.acquisition_evidence_roots
        },
        key=str,
    )
    if not source_roots:
        raise CandidateError("exact-51 prepared inputs lack acquisition evidence roots")

    verifier_home = _real_account_home()
    state_laws_root = local_state_laws_root(verifier_home)
    state_laws_root.mkdir(parents=True, exist_ok=True)
    state_laws_root = _safe_existing_directory(
        state_laws_root, label="verifier state-laws root"
    )
    dependency_site = _attested_dependency_site_packages()
    with tempfile.TemporaryDirectory(
        prefix=".lcr084-verifier-replay-", dir=str(state_laws_root)
    ) as temporary_name:
        temporary = Path(temporary_name)
        evidence_root = temporary / "evidence"
        output_root = temporary / "output"
        jsonld_dir = output_root / "jsonld"
        parquet_dir = output_root / "parquet"
        evidence_root.parent.mkdir(parents=True)
        page_cache = temporary / "page-cache"
        fetch_cache = temporary / "fetch-cache"
        pycache_root = temporary / "pycache"
        page_cache.mkdir()
        fetch_cache.mkdir()
        pycache_root.mkdir()

        hardlinked_files = 0
        selected_fetch_evidence_hashes: dict[Path, str] = {}
        for code in expected:
            normalized_path = bindings[code].normalized_source_receipt_path
            matching_roots = []
            for root in source_roots:
                try:
                    normalized_path.relative_to(root)
                except ValueError:
                    continue
                matching_roots.append(root)
            if len(matching_roots) != 1:
                raise CandidateError(
                    f"{code} normalized receipt must belong to one exact evidence root"
                )
            scraper = get_scraper_for_state(code, US_STATES[code])
            if scraper is None:
                raise CandidateError(f"{code} has no current registered scraper")
            parser_name = type(scraper).__name__
            source_ledger = StateLawMultiFetchAcquisitionLedger(
                matching_roots[0],
                jurisdiction=code,
                parser_name=parser_name,
            )
            entries = source_ledger.entries
            if not entries:
                raise CandidateError(f"{code} selected evidence has no retained parser inputs")
            for evidence_path, evidence_sha256 in (
                _strict_retained_fetch_evidence_hashes(
                    entries, jurisdiction=code
                ).items()
            ):
                previous = selected_fetch_evidence_hashes.setdefault(
                    evidence_path, evidence_sha256
                )
                if previous != evidence_sha256:
                    raise CandidateError(
                        f"{code} retained fetch evidence identity is ambiguous"
                    )
            transports = sorted(
                {
                    str(entry.transport_receipt.get("source_transport") or "").strip()
                    for entry in entries
                    if str(entry.transport_receipt.get("source_transport") or "").strip()
                }
            )
            if not transports:
                raise CandidateError(f"{code} retained evidence has no verified transports")
            replay_selection_ledger = StateLawMultiFetchAcquisitionLedger(
                matching_roots[0],
                jurisdiction=code,
                parser_name=parser_name,
                allowed_source_transports=transports,
                retained_replay_only=True,
            )
            phase_bound_receipts, live_phase_selector = (
                _verifier_phase_bound_seed_selection(
                    scraper=scraper,
                    ledger=replay_selection_ledger,
                    code=code,
                )
            )
            seed_report = seed_retained_evidence_generation(
                source_root=matching_roots[0],
                destination_root=evidence_root,
                jurisdiction=code,
                parser_name=parser_name,
                allowed_source_transports=transports,
                phase_bound_receipt_sha256s=phase_bound_receipts,
            )
            authorize_hardlink_only_seed(seed_report, home=verifier_home)
            if int(seed_report.copied_file_count) != 0:
                raise CandidateError(f"{code} verifier seed copied retained evidence")
            hardlinked_files += int(seed_report.hardlinked_file_count)
            if live_phase_selector is not None:
                _hardlink_verifier_phase_selector(
                    source=live_phase_selector,
                    destination_root=evidence_root,
                    code=code,
                )
                hardlinked_files += 1

        source_root = _safe_existing_directory(
            REPOSITORY_ROOT,
            label="retained replay verifier source root",
        )
        refresh_script = _lexical_absolute(
            source_root
            / "scripts/ops/legal_data/refresh_state_laws_corpus.py"
        )
        refresh_arguments = [
            "--states",
            "all",
            "--output-root",
            str(output_root),
            "--jsonld-dir",
            str(jsonld_dir),
            "--parquet-dir",
            str(parquet_dir),
            "--scrape",
            "--acquisition-evidence-root",
            str(evidence_root),
            "--strict-acquisition-evidence",
            "--retained-replay-only",
            "--strict-full-text",
            "--max-statutes",
            "0",
            "--no-merge-existing-local",
            "--no-load-completed-states-baseline",
            "--no-skip-completed-states",
            "--no-persist-completed-states-registry",
            "--no-startup-stale-sync",
            "--no-incremental-state-publish",
            "--parallel-workers",
            "1",
            "--json",
        ]
        bootstrap = (
            "import runpy,sys;"
            f"sys.path[:0]=[{str(source_root)!r},{str(dependency_site)!r}];"
            f"sys.argv=[{str(refresh_script)!r},*sys.argv[1:]];"
            f"runpy.run_path({str(refresh_script)!r},run_name='__main__')"
        )
        argv = [
            "-I",
            "-X",
            f"pycache_prefix={pycache_root}",
            "-c",
            bootstrap,
            *refresh_arguments,
        ]
        command = build_host_retained_replay_command(
            argv=argv,
            workdir=source_root,
            python_executable=sys.executable,
            home=verifier_home,
        )
        environment = build_host_retained_replay_environment(
            source={
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "TZ": "UTC",
            },
            extra_environment={
                "HOME": str(verifier_home),
                EVIDENCE_ROOT_ENV: str(evidence_root),
                PAGE_CACHE_DIR_ENV: str(page_cache),
                FETCH_CACHE_DIR_ENV: str(fetch_cache),
            },
            home=verifier_home,
        )
        returncode, stdout_bytes, stderr_tail = (
            _run_bounded_retained_replay_subprocess(
                command,
                cwd=source_root,
                environment=environment,
            )
        )
        if returncode != 0:
            raise CandidateError(
                "verifier-owned exact-51 retained replay failed: " + stderr_tail
            )
        try:
            replay_stdout = stdout_bytes.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise CandidateError(
                "verifier retained replay stdout is not UTF-8 JSON"
            ) from exc
        _parse_retained_replay_result(replay_stdout)

        replay_input_map = temporary / "replayed-input-map.json"
        assembly = input_assembler.assemble_state_laws_production_input_map(
            acquisition_evidence_root=evidence_root,
            canonical_output_roots=[jsonld_dir],
            output_path=replay_input_map,
        )
        if (
            assembly.get("status") != "written"
            or assembly.get("exact_51_ready") is not True
            or assembly.get("jurisdiction_count") != EXPECTED_JURISDICTION_COUNT
        ):
            raise CandidateError("verifier retained replay did not assemble exact-51")
        replayed = production_runner.prepare_exact_51_inputs(
            input_map_path=replay_input_map,
            rights_receipt_path=prepared.rights_receipt_path,
        )
        production_runner.reverify_prepared_inputs(replayed)
        replayed_closure = _derive_input_corpus_closure(replayed)
        replayed_projection = _derive_retained_frontier_projection(
            replayed, replayed_closure
        )

        selected_stable = {
            code: _stable_official_rows(
                list(selected_corpus_closure[code].get("rows") or [])
            )
            for code in expected
        }
        replayed_stable = {
            code: _stable_official_rows(
                list(replayed_closure[code].get("rows") or [])
            )
            for code in expected
        }
        if selected_stable != replayed_stable:
            raise CandidateError(
                "verifier retained replay canonical rows/keys differ from selected input"
            )
        if _retained_replay_comparison_projection(
            replayed_projection
        ) != _retained_replay_comparison_projection(selected_projection):
            raise CandidateError(
                "verifier retained replay raw frontier/ledger projection differs "
                "from selected input"
            )
        for evidence_path, expected_sha256 in selected_fetch_evidence_hashes.items():
            _, _, observed_sha256 = load_json_mapping_snapshot(
                evidence_path,
                label="selected retained fetch evidence bookend",
            )
            if observed_sha256 != expected_sha256:
                raise CandidateError(
                    "selected retained fetch evidence changed during verifier replay"
                )
        # Bookend every selected byte surface after the isolated replay.  The
        # production runner reopens all selected files and seals again here.
        production_runner.reverify_prepared_inputs(prepared)
        bookend_closure = _derive_input_corpus_closure(prepared)
        bookend_projection = _derive_retained_frontier_projection(
            prepared, bookend_closure
        )
        if (
            bookend_closure != dict(selected_corpus_closure)
            or bookend_projection != dict(selected_projection)
        ):
            raise CandidateError("selected exact-51 evidence changed during retained replay")

    return {
        **dict(selected_projection),
        "copied_file_count": 0,
        "derivation_reverified_with_current_code": True,
        "hardlinked_file_count": hardlinked_files,
        "origin_reauthentication_performed": False,
        "provenance_trust_root": "verified-retained-acquisition-bytes",
        "retained_replay_completed": True,
    }


def collect_production_evidence(
    *,
    input_map_path: Path | str,
    rights_receipt_path: Path | str,
    production_output_root: Path | str,
    live_baseline_path: Path | str,
    source_revision: str,
    repo_root: Path | str | None = None,
    require_clean_source: bool,
    sealed_source_control: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reopen the exact-51 map and completed local release through shared gates.

    The production build remains local-only and no Hub mutation is possible.
    Acceptance verification itself performs an authenticated read-only Hub
    replay of LCR-081, then uses the production runner's v2 input verifier and
    local release verifier to bind exact bytes for the LCR-084 report pair.
    """

    root = _safe_existing_directory(
        repo_root or REPOSITORY_ROOT, label="repository root"
    )
    revision = _require_git_revision(source_revision)
    baseline_lexical = _require_canonical_repo_path(
        live_baseline_path,
        repo_root=root,
        relative_path=DEFAULT_LIVE_BASELINE_RELPATH,
        label="authenticated live-baseline receipt",
        must_exist=True,
    )
    acceptance_path = root / PRODUCTION_ACCEPTANCE_RELPATH
    candidate_path = root / DEFAULT_REPORT_RELPATH
    controlled_evidence_paths = (
        baseline_lexical,
        acceptance_path,
        candidate_path,
    )
    current_source_control = source_control_binding(
        repo_root=root,
        source_revision=revision,
        require_clean=require_clean_source,
    )
    excluded_evidence_paths = [
        _display_path(path, repo_root=root) for path in controlled_evidence_paths
    ]
    if require_clean_source:
        if sealed_source_control is not None:
            raise CandidateError(
                "initial clean production sealing cannot accept a prior source binding"
            )
        source_control = dict(current_source_control)
        source_control["excluded_evidence_paths"] = excluded_evidence_paths
    else:
        require_only_expected_dirty_paths(
            repo_root=root,
            source_revision=revision,
            allowed_paths=controlled_evidence_paths,
        )
        expected_sealed_source_control = {
            "clean_at_seal": True,
            "excluded_evidence_paths": excluded_evidence_paths,
            "revision": revision,
            "tree": current_source_control["tree"],
        }
        if not isinstance(sealed_source_control, Mapping) or dict(
            sealed_source_control
        ) != expected_sealed_source_control:
            raise CandidateError(
                "report-only remeasurement requires the exact prior clean source binding"
            )
        source_control = dict(expected_sealed_source_control)
    (
        baseline_path,
        baseline,
        live_replay_binding,
        baseline_source_identity_closures,
        baseline_file_sha256,
    ) = _validated_live_baseline(live_baseline_path, repo_root=root)
    try:
        production_runner.assert_local_only_contract()
        prepared = production_runner.prepare_exact_51_inputs(
            input_map_path=input_map_path,
            rights_receipt_path=rights_receipt_path,
        )
        production_runner.reverify_prepared_inputs(prepared)
        release = verify_state_laws_local_release_manifest(
            _safe_existing_directory(
                production_output_root, label="production output root"
            )
        )
    except CandidateError:
        raise
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise CandidateError(
            f"production evidence failed shared exact-51 verification: {exc}"
        ) from exc

    manifest_path = _lexical_absolute(release.path)
    manifest, manifest_bytes, manifest_file_sha256 = load_json_mapping_snapshot(
        manifest_path, label="completed production manifest"
    )
    if manifest != dict(release.payload):
        raise CandidateError(
            "completed production manifest snapshot differs from shared verifier payload"
        )
    if manifest.get("source_revision") != revision:
        raise CandidateError(
            "completed production manifest source_revision differs from the sealed revision"
        )
    if manifest.get("jurisdictions") != list(CANONICAL_JURISDICTION_ORDER):
        raise CandidateError("completed production manifest is not canonical exact-51")
    release_control = manifest.get("release_control")
    if not isinstance(release_control, Mapping) or release_control != {
        "authorizes_hub_upload": False,
        "authorizes_publication": False,
        "fail_closed": True,
        "local_staging_only": True,
        "network_io_performed": False,
        "publication_action_performed": False,
    }:
        raise CandidateError("completed production manifest is not strictly local-only")

    input_corpus_closure = _derive_input_corpus_closure(prepared)
    release_corpus_closure = _derive_release_corpus_closure(release, manifest)
    exact_corpus_closure = _bind_exact_corpus_closure(
        input_corpus_closure,
        release_corpus_closure,
        manifest=manifest,
    )
    selected_retained_projection = _derive_retained_frontier_projection(
        prepared, input_corpus_closure
    )
    official_retained_replay = _verifier_owned_retained_replay(
        prepared=prepared,
        selected_corpus_closure=input_corpus_closure,
        selected_projection=selected_retained_projection,
        repo_root=root,
    )

    input_map_payload, _, input_map_sha256 = load_bound_json_mapping_snapshot(
        prepared.input_map_path,
        expected_sha256=prepared.input_map_sha256,
        label="exact-51 input map",
    )
    map_runner_identity = str(
        input_map_payload.get("refresh_runner_source_software_version") or ""
    ).strip()
    if not map_runner_identity or any(
        item.refresh_runner_source_software_version != map_runner_identity
        for item in prepared.bindings
    ):
        raise CandidateError("exact-51 input map refresh-runner identity drifted")

    adapter_rows = {
        code: len(input_corpus_closure[code]["rows"])
        for code in CANONICAL_JURISDICTION_ORDER
    }
    receipts = {item.jurisdiction: item for item in prepared.source_receipts}
    bindings = {item.jurisdiction: item for item in prepared.bindings}
    if (
        tuple(bindings) != tuple(CANONICAL_JURISDICTION_ORDER)
        or tuple(receipts) != tuple(CANONICAL_JURISDICTION_ORDER)
        or tuple(adapter_rows) != tuple(CANONICAL_JURISDICTION_ORDER)
    ):
        raise CandidateError("prepared production inputs are not canonical exact-51")

    jurisdiction_evidence: list[dict[str, Any]] = []
    for code in CANONICAL_JURISDICTION_ORDER:
        binding = bindings[code]
        receipt = receipts[code]
        row_count = adapter_rows[code]
        content_hashes = list(receipt.content_hashes)
        if not content_hashes or binding.canonical_jsonld_sha256 not in content_hashes:
            raise CandidateError(
                f"{code} normalized receipt lacks the canonical artifact response hash"
            )
        if (
            receipt.frontier_closed is not True
            or receipt.failed_final != 0
            or receipt.fetched != row_count
            or receipt.discovered
            != receipt.fetched
            + receipt.excluded
            + receipt.quarantined
            + receipt.failed_final
        ):
            raise CandidateError(f"{code} normalized receipt is not exhaustive")
        run_seal, _, run_seal_sha256 = load_bound_json_mapping_snapshot(
            binding.run_seal_path,
            expected_sha256=binding.run_seal_sha256,
            label=f"{code} run-final seal",
        )
        run_seal_created_at = str(run_seal.get("created_at") or "").strip()
        if not run_seal_created_at:
            raise CandidateError(f"{code} run-final seal lacks created_at")
        jurisdiction_evidence.append(
            {
                "canonical_jsonld_path": _display_path(
                    binding.canonical_jsonld_path, repo_root=root
                ),
                "canonical_jsonld_sha256": binding.canonical_jsonld_sha256,
                "canonical_row_count": row_count,
                "content_hashes_digest_sha256": digest_payload(content_hashes),
                "discovered": receipt.discovered,
                "duplicates": receipt.duplicates,
                "excluded": receipt.excluded,
                "failed_final": receipt.failed_final,
                "fetched": receipt.fetched,
                "frontier_closed": True,
                "jurisdiction": code,
                "normalized_source_receipt_path": _display_path(
                    binding.normalized_source_receipt_path, repo_root=root
                ),
                "normalized_source_receipt_sha256": (
                    binding.normalized_source_receipt_sha256
                ),
                "observation_time": receipt.observation_time,
                "official_source_url": receipt.official_source_url,
                "quarantined": receipt.quarantined,
                "receipt_id": receipt.receipt_id,
                "release_point": receipt.release_point,
                **exact_corpus_closure["release_source_receipt_bindings"][code],
                "run_seal_path": _display_path(binding.run_seal_path, repo_root=root),
                "run_seal_created_at": run_seal_created_at,
                "run_seal_sha256": run_seal_sha256,
                "source_software_version": str(receipt.source_software_version or ""),
            }
        )
    baseline_state = baseline.get("state_laws")
    baseline_partitions = (
        baseline_state.get("partitions") if isinstance(baseline_state, Mapping) else None
    )
    if not isinstance(baseline_partitions, Mapping) or set(baseline_partitions) != set(
        CANONICAL_JURISDICTION_ORDER
    ):
        raise CandidateError("LCR-081 baseline partitions are not exact-51")
    baseline_projection: list[dict[str, Any]] = []
    baseline_source_identity_projection: list[dict[str, Any]] = []
    baseline_reconciliation: list[dict[str, Any]] = []
    for code in CANONICAL_JURISDICTION_ORDER:
        part = baseline_partitions.get(code)
        if not isinstance(part, Mapping):
            raise CandidateError(f"LCR-081 baseline partition {code} is malformed")
        baseline_rows = int(part.get("num_rows", -1))
        if baseline_rows < 0:
            raise CandidateError(f"LCR-081 baseline partition {code} row count is invalid")
        identity_closure = baseline_source_identity_closures.get(code)
        if not isinstance(identity_closure, Mapping):
            raise CandidateError(
                f"LCR-081 baseline partition {code} lacks source-identity closure"
            )
        baseline_identity_count = int(
            identity_closure.get("source_identity_count", -1)
        )
        baseline_identity_digest = _require_sha256(
            identity_closure.get("source_identity_multiset_sha256"),
            label=f"baseline.partitions.{code}.source identity digest",
        )
        recovery_manifest_count = int(
            identity_closure.get(
                "noncomparable_recovery_manifest_count", -1
            )
        )
        recovery_manifest_digest = _require_sha256(
            identity_closure.get(
                "noncomparable_recovery_manifest_multiset_sha256"
            ),
            label=f"baseline.partitions.{code}.recovery manifest digest",
        )
        if (
            baseline_identity_count < 0
            or recovery_manifest_count < 0
            or baseline_identity_count + recovery_manifest_count != baseline_rows
        ):
            raise CandidateError(
                f"LCR-081 baseline partition {code} identity closure drifted"
            )
        baseline_projection.append(
            {
                "content_sha256": _require_sha256(
                    part.get("content_sha256"),
                    label=f"baseline.partitions.{code}.content_sha256",
                ),
                "footer_sha256": _require_sha256(
                    part.get("footer_sha256"),
                    label=f"baseline.partitions.{code}.footer_sha256",
                ),
                "jurisdiction": code,
                "noncomparable_recovery_manifest_count": (
                    recovery_manifest_count
                ),
                "noncomparable_recovery_manifest_multiset_sha256": (
                    recovery_manifest_digest
                ),
                "num_rows": baseline_rows,
                "path": str(part.get("path") or ""),
                "source_identity_count": baseline_identity_count,
                "source_identity_multiset_sha256": baseline_identity_digest,
            }
        )
        baseline_source_identity_projection.append(
            {
                "jurisdiction": code,
                "noncomparable_recovery_manifest_count": (
                    recovery_manifest_count
                ),
                "noncomparable_recovery_manifest_multiset_sha256": (
                    recovery_manifest_digest
                ),
                "source_identity_count": baseline_identity_count,
                "source_identity_multiset_sha256": baseline_identity_digest,
            }
        )
        receipt = receipts[code]
        acquired_rows = adapter_rows[code]
        baseline_reconciliation.append(
            _reconcile_baseline_source_identities(
                jurisdiction=code,
                baseline_counter=identity_closure.get("counter") or {},
                acquired_counter=(
                    input_corpus_closure[code].get("source_identity_counter") or {}
                ),
                baseline_row_count=baseline_rows,
                acquired_row_count=acquired_rows,
                noncomparable_recovery_manifest_count=recovery_manifest_count,
                noncomparable_recovery_manifest_multiset_sha256=(
                    recovery_manifest_digest
                ),
                duplicate_count=receipt.duplicates,
                excluded_count=receipt.excluded,
                quarantined_count=receipt.quarantined,
            )
        )

    manifest_bookend, manifest_bytes, _ = load_bound_json_mapping_snapshot(
        manifest_path,
        expected_sha256=manifest_file_sha256,
        label="completed production manifest bookend",
    )
    if manifest_bookend != manifest:
        raise CandidateError("completed production manifest changed during verification")
    artifacts = _snapshot_release_artifacts(release, manifest_bookend)
    if artifacts != sorted(artifacts, key=lambda item: item["relative_path"]):
        raise CandidateError("verified production artifact descriptors are not ordered")

    counts = _manifest_counts(manifest)
    count_map = {item["name"]: item["value"] for item in counts}
    deduped_union_count = int(count_map.get("corpus_documents", -1))
    if deduped_union_count < EXPECTED_JURISDICTION_COUNT:
        raise CandidateError("production deduped union underfills exact-51 coverage")
    shard_sum = sum(adapter_rows.values())
    if (
        shard_sum != deduped_union_count
        or exact_corpus_closure["union"]["deduped_union_count"]
        != deduped_union_count
    ):
        raise CandidateError(
            "production deduped union is not exactly the selected admitted shards"
        )

    rights, _, rights_file_sha256 = load_bound_json_mapping_snapshot(
        prepared.rights_receipt_path,
        expected_sha256=prepared.rights_receipt_sha256,
        label="source-rights receipt",
    )
    if rights != dict(prepared.rights_receipt):
        raise CandidateError("source-rights receipt snapshot drifted")
    rights_digest = _require_sha256(
        rights.get("receipt_digest") or rights.get("report_digest_sha256"),
        label="source-rights receipt digest",
    )
    catalog_digest = _require_sha256(
        rights.get("catalog_digest_sha256"),
        label="source-rights catalog digest",
    )
    if (
        manifest.get("source_rights_receipt_digest") != rights_digest
        or manifest.get("source_rights_catalog_digest") != catalog_digest
    ):
        raise CandidateError(
            "completed production manifest differs from the verified rights receipt"
        )

    current_versions = [
        {"jurisdiction": code, "source_software_version": identity}
        for code, identity in sorted(prepared.current_source_software_versions.items())
    ]
    baseline_display_path = _display_path(baseline_path, repo_root=root)
    baseline_bookend, _, _ = load_bound_json_mapping_snapshot(
        baseline_path,
        expected_sha256=baseline_file_sha256,
        label="LCR-081 baseline bookend",
    )
    if baseline_bookend != baseline:
        raise CandidateError("LCR-081 baseline changed during verification")
    # Recheck the exact source/report boundary after both verifier-owned
    # replays, then bookend all selected inputs below before returning.
    require_only_expected_dirty_paths(
        repo_root=root,
        source_revision=revision,
        allowed_paths=controlled_evidence_paths,
    )
    source_receipts_digest = production_runner.production_source_receipts_digest(
        prepared.source_receipts
    )
    if (
        source_receipts_digest
        != exact_corpus_closure["input_source_receipts_digest_sha256"]
        or source_receipts_digest
        != exact_corpus_closure["release_source_receipts_digest_sha256"]
    ):
        raise CandidateError(
            "production source-receipt digest does not bind input and embedded output"
        )
    evidence: dict[str, Any] = {
        "authenticated_live_baseline": {
            **live_replay_binding,
            "observed_at": str(baseline.get("observed_at") or ""),
            "partitions": baseline_projection,
            "partitions_digest_sha256": digest_payload(baseline_projection),
            "path": baseline_display_path,
            "receipt_digest_sha256": _require_sha256(
                baseline.get(live_baseline_audit.RECEIPT_SELF_DIGEST_FIELD),
                label="LCR-081 receipt digest",
            ),
            "sha256": baseline_file_sha256,
            "source_identity_closure_digest_sha256": digest_payload(
                baseline_source_identity_projection
            ),
            "source_identity_closure_schema": (
                BASELINE_SOURCE_IDENTITY_CLOSURE_SCHEMA
            ),
            "state_revision": str(
                baseline_state.get("revision") if isinstance(baseline_state, Mapping) else ""
            ),
        },
        "baseline_reconciliation": baseline_reconciliation,
        "input_map": {
            "path": _display_path(prepared.input_map_path, repo_root=root),
            "schema_version": production_runner.INPUT_MAP_SCHEMA_VERSION,
            "sha256": input_map_sha256,
        },
        "jurisdictions": jurisdiction_evidence,
        "official_frontier_reobservation": official_retained_replay,
        "production_release": {
            "artifact_count": len(artifacts),
            "artifact_descriptors_digest_sha256": digest_payload(artifacts),
            "artifacts": artifacts,
            "counts": counts,
            "dataset_repo_id": str(manifest.get("dataset_repo_id") or ""),
            "key_parity": _manifest_key_parity(manifest),
            "manifest_digest": _require_sha256(
                release.manifest_digest, label="production manifest digest"
            ),
            "manifest_file_sha256": manifest_file_sha256,
            "manifest_path": _display_path(manifest_path, repo_root=root),
            "manifest_size_bytes": len(manifest_bytes),
            "output_root": _display_path(release.output_root, repo_root=root),
            "release_point": str(manifest.get("release_point") or ""),
            "source_revision": revision,
        },
        "rights_receipt": {
            "catalog_digest_sha256": catalog_digest,
            "path": _display_path(prepared.rights_receipt_path, repo_root=root),
            "receipt_digest_sha256": rights_digest,
            "sha256": rights_file_sha256,
            "status": str(rights.get("status") or ""),
        },
        "source_bundle": {
            "current_source_software_versions": current_versions,
            "current_source_software_versions_digest_sha256": (
                digest_payload(current_versions)
            ),
            "refresh_runner_source_software_version": map_runner_identity,
        },
        "source_control": source_control,
        "source_receipts_digest_sha256": _require_sha256(
            source_receipts_digest, label="source receipts digest"
        ),
        "union": exact_corpus_closure["union"],
    }
    return evidence


def write_json_report(report: Mapping[str, Any], path: Path | str) -> Path:
    report_path = _lexical_absolute(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _safe_existing_directory(report_path.parent, label="report parent")
    if report_path.exists() or report_path.is_symlink():
        with _open_regular_file_nofollow(report_path, label="existing report"):
            pass
    return write_json_atomic(report_path, dict(report))


def _digest_for_report(payload: Mapping[str, Any]) -> str:
    stripped = {
        key: value
        for key, value in payload.items()
        if key != "report_digest_sha256"
    }
    return digest_payload(stripped)


def _receipt_digest(label: str) -> str:
    return content_sha256(f"lcr039:{label}")


def exact_51_family_rows() -> dict[str, list[dict[str, Any]]]:
    """Compact one-row-per-jurisdiction candidate recipe including DC."""

    corpus: list[dict[str, Any]] = []
    for code in CANONICAL_JURISDICTION_ORDER:
        lower = code.lower()
        row = example_corpus_payload(
            legal_id=f"state:{lower}:code:1:1",
            jurisdiction=code,
            entry_cid=content_sha256(f"lcr039-entry:{lower}:code:1:1"),
        )
        row["admission_status"] = "admitted"
        row["verification_result"] = "verified"
        row["rights_disposition"] = "allowed"
        row["source_id"] = f"{lower}-fixture-statutory_text"
        row["text"] = (
            f"{code} fixture candidate section 1-1 remains in force for the "
            "sealed exact-51 release recipe."
        )
        row["official_source_url"] = (
            f"https://legislature.example.gov/{lower}/statutes/1-1"
        )
        corpus.append(row)

    oregon = next(row for row in corpus if row["jurisdiction"] == "OR")
    washington = next(row for row in corpus if row["jurisdiction"] == "WA")
    bm25_docs = [
        {
            "document_index": index,
            "entry_cid": row["entry_cid"],
            "chunk_cid": row["entry_cid"],
            "jurisdiction": row["jurisdiction"],
            "legal_id": row["legal_id"],
            "field_lengths": {"body": len(str(row.get("text") or "").split())},
        }
        for index, row in enumerate(corpus)
    ]
    bm25_postings = [
        {
            "chunk_cid": row["entry_cid"],
            "entry_cid": row["entry_cid"],
            "term": "fixture",
            "tf": 1,
        }
        for row in corpus
    ]
    vectors = [
        {
            "chunk_cid": row["entry_cid"],
            "cluster_id": 0,
            "dimension": DEFAULT_EMBEDDING_DIMENSION,
            "entry_cid": row["entry_cid"],
            "legal_id": row["legal_id"],
            "model_id": DEFAULT_EMBEDDING_MODEL_ID,
            "model_revision": DEFAULT_EMBEDDING_MODEL_REVISION,
            "relative_path": "data/vectors/centroid-000-part-000000.parquet",
            "row_offset": index,
        }
        for index, row in enumerate(corpus)
    ]
    centroids = [
        {
            "centroid_id": "cluster-000000",
            "cluster_id": 0,
            "dimension": DEFAULT_EMBEDDING_DIMENSION,
            "entry_cid": oregon["entry_cid"],
            "relative_path": "data/vectors/centroid-000-part-000000.parquet",
            "row_count": len(vectors),
        }
    ]
    locator = [
        {
            "chunk_cid": row["entry_cid"],
            "cluster_id": 0,
            "entry_cid": row["entry_cid"],
            "global_shard_id": 0,
            "relative_path": "data/vectors/centroid-000-part-000000.parquet",
            "row_offset": index,
            "vector_key": row["entry_cid"],
        }
        for index, row in enumerate(corpus)
    ]
    graph_nodes = [
        {
            "entry_cid": row["entry_cid"],
            "legal_id": row["legal_id"],
            "node_cid": row["entry_cid"],
            "node_key": row["legal_id"],
            "node_type": "section",
        }
        for row in corpus
    ]
    graph_edges = [
        {
            "edge_cid": _receipt_digest("edge:cites"),
            "edge_type": "CITES",
            "source_node_cid": oregon["entry_cid"],
            "target_node_cid": washington["entry_cid"],
        }
    ]
    adjacency_out = [
        {
            "direction": "out",
            "node_cid": oregon["entry_cid"],
            "page_index": 0,
            "pointer_count": 1,
            "pointers": [
                {
                    "edge_cid": graph_edges[0]["edge_cid"],
                    "neighbor_node_cid": washington["entry_cid"],
                }
            ],
        }
    ]
    adjacency_in = [
        {
            "direction": "in",
            "node_cid": washington["entry_cid"],
            "page_index": 0,
            "pointer_count": 1,
            "pointers": [
                {
                    "edge_cid": graph_edges[0]["edge_cid"],
                    "neighbor_node_cid": oregon["entry_cid"],
                }
            ],
        }
    ]
    recovery = [
        {
            "admission_status": "recovery",
            "authorizing_for_publication": False,
            "jurisdiction": "OR",
            "reason": "recovery-seed-excluded-from-exact-51",
            "recovery_id": _receipt_digest("recovery:or"),
            "raw_digest": _receipt_digest("recovery-raw:or"),
        }
    ]
    quarantine = [
        {
            "admission_status": "quarantined",
            "authorizing_for_publication": False,
            "jurisdiction": "WA",
            "reason": "unknown-or-prohibited-rights-excluded-from-default",
            "recovery_id": _receipt_digest("quarantine:wa"),
            "rights_disposition": "prohibited",
            "raw_digest": _receipt_digest("quarantine-raw:wa"),
        }
    ]
    return {
        "bm25_documents": bm25_docs,
        "bm25_postings": bm25_postings,
        "centroids": centroids,
        "corpus": corpus,
        "graph_adjacency_in": adjacency_in,
        "graph_adjacency_out": adjacency_out,
        "graph_edges": graph_edges,
        "graph_nodes": graph_nodes,
        "quarantine": quarantine,
        "recovery": recovery,
        "source_receipts": fixture_source_receipts(corpus),
        "vector_locator": locator,
        "vectors": vectors,
    }


def assemble_candidate(*, repo_root: Path | str | None = None) -> dict[str, Any]:
    rows = exact_51_family_rows()
    codes = [str(row["jurisdiction"]).upper() for row in rows["corpus"]]
    if codes != list(CANONICAL_JURISDICTION_ORDER):
        raise CandidateError("candidate corpus is not CANONICAL_JURISDICTION_ORDER")
    if len(set(codes)) != EXPECTED_JURISDICTION_COUNT:
        raise CandidateError("candidate corpus is not the sealed exact-51 set")

    release = assemble_state_laws_hf_release(
        rows,
        legacy_files=fixture_legacy_files(),
        dry_run=True,
    )
    validation = validate_state_laws_hf_release(release)
    rights = load_source_rights_receipt()
    e2e_path = (Path(repo_root) if repo_root is not None else REPOSITORY_ROOT) / LOCAL_E2E_RELPATH
    e2e = load_json_mapping(e2e_path) if e2e_path.is_file() else {}
    if e2e.get("task_id") != "LCR-038":
        raise CandidateError("LCR-038 local_e2e.json is required and must be sealed")
    if e2e.get("authorizing_for_publication") is not False:
        raise CandidateError("LCR-038 receipt must not authorize publication")

    artifact_bytes = sum(int(item.size_bytes) for item in release.artifacts)
    multipart = {
        "estimated_parts": max(1, (artifact_bytes + (8 * 1024 * 1024) - 1) // (8 * 1024 * 1024)),
        "estimated_total_bytes": artifact_bytes,
        "part_size_bytes": 8 * 1024 * 1024,
        "resumable": True,
        "transactional_staging_ready": True,
    }
    payload: dict[str, Any] = {
        "acceptance": {
            "byte_descriptor_complete": validation.get("valid") is True,
            "contains_exact_51": True,
            "criteria": ACCEPTANCE_CRITERIA,
            "no_stale_model_revision": (
                release.model_id == DEFAULT_EMBEDDING_MODEL_ID
                and release.model_revision == DEFAULT_EMBEDDING_MODEL_REVISION
            ),
            "ready_for_transactional_staging": True,
            "required_semantic_families": True,
        },
        "assembler_goal_id": ASSEMBLER_GOAL_ID,
        "assembler_schema_version": ASSEMBLER_SCHEMA_VERSION,
        "assembler_task_id": ASSEMBLER_TASK_ID,
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "board_namespace": BOARD_NAMESPACE,
        "bundle": BUNDLE,
        "code_version": CODE_VERSION,
        "configs": {
            "default": DEFAULT_CONFIG_NAME,
            "legacy": LEGACY_CONFIG_NAME,
            "quarantine": QUARANTINE_CONFIG_NAME,
            "recovery": RECOVERY_CONFIG_NAME,
        },
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "families": list(REQUIRED_FAMILIES),
        "fixture_only": True,
        "goal_id": GOAL_ID,
        "hub_upload": False,
        "inputs": {
            "local_e2e_digest_sha256": file_sha256(e2e_path) if e2e_path.is_file() else "",
            "local_e2e_path": LOCAL_E2E_RELPATH.as_posix(),
            "source_rights_receipt_path": SOURCE_RIGHTS_RECEIPT_RELPATH,
        },
        "jurisdiction_codes": codes,
        "jurisdiction_count": len(codes),
        "lineage_report": LINEAGE_REPORT_PATH,
        "manifest_digest": release.manifest_digest,
        "model_id": release.model_id,
        "model_revision": release.model_revision,
        "multipart_plan": multipart,
        "previous_public_pin": PREVIOUS_PUBLIC_PIN,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "proves_software_contract_only": True,
        "release_profile": RELEASE_PROFILE,
        "release_root_cid": release.release_root_cid,
        "required_manifest_bindings": list(REQUIRED_MANIFEST_BINDINGS),
        "rollback_target": PREVIOUS_PUBLIC_PIN,
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "source_rights_receipt_digest": rights.get("receipt_digest")
        or release.source_rights_receipt_digest,
        "status": "pass",
        "task_id": TASK_ID,
        "validation": {
            "artifact_count": validation.get("artifact_count"),
            "config_count": validation.get("config_count"),
            "default_config": validation.get("default_config"),
            "descriptor_count": validation.get("descriptor_count"),
            "valid": validation.get("valid") is True,
        },
        "vector_space_id": release.vector_space_id,
    }
    assert_no_secrets_or_home_paths(payload)
    payload["report_digest_sha256"] = _digest_for_report(payload)
    return payload


def _validate_acceptance_for_production_candidate(
    acceptance: Mapping[str, Any],
    *,
    acceptance_path: Path,
    candidate_path: Path,
    evidence: Mapping[str, Any],
    repo_root: Path,
) -> None:
    schema_path = repo_root / "data/legal/state_laws_full_scrape_acceptance.schema.json"
    try:
        from jsonschema import Draft202012Validator

        schema = load_json_mapping(schema_path)
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(dict(acceptance)),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
    except ImportError as exc:
        raise CandidateError(
            "jsonschema is required to seal a production candidate"
        ) from exc
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise CandidateError(
            f"full-scrape acceptance fails schema at {location}: {first.message}"
        )
    if (
        acceptance.get("schema") != PRODUCTION_ACCEPTANCE_SCHEMA
        or acceptance.get("task_id") != PRODUCTION_TASK_ID
        or acceptance.get("goal_id") != PRODUCTION_GOAL_ID
        or acceptance.get("mode") != "live_official"
        or acceptance.get("status") != "passed"
        or acceptance.get("local_only") is not False
        or acceptance.get("production_generation_local_only") is not True
        or acceptance.get("network_io_performed") is not True
        or acceptance.get("read_only_live_verification") is not True
        or acceptance.get("hub_mutation_performed") is not False
        or acceptance.get("authorizing_hub_upload") is not False
        or acceptance.get("authorizing_for_publication") is not False
        or acceptance.get("freshness_max_age_seconds")
        != PRODUCTION_MAX_EVIDENCE_AGE_SECONDS
    ):
        raise CandidateError("full-scrape acceptance is not sealed local production evidence")
    if acceptance.get("evidence") != dict(evidence):
        raise CandidateError("full-scrape acceptance evidence differs from remeasurement")
    evidence_digest = digest_payload(evidence)
    if acceptance.get("production_evidence_digest_sha256") != evidence_digest:
        raise CandidateError("full-scrape acceptance evidence digest drifted")
    if acceptance.get("report_digest_sha256") != _digest_for_report(acceptance):
        raise CandidateError("full-scrape acceptance report digest drifted")
    requirement = acceptance.get("candidate_requirement")
    if not isinstance(requirement, Mapping):
        raise CandidateError("full-scrape acceptance lacks candidate_requirement")
    expected_candidate_path = _display_path(candidate_path, repo_root=repo_root)
    if requirement != {
        "candidate_path": expected_candidate_path,
        "candidate_schema": PRODUCTION_REPORT_SCHEMA,
        "manifest_digest": evidence["production_release"]["manifest_digest"],
        "production_evidence_digest_sha256": evidence_digest,
    }:
        raise CandidateError("full-scrape acceptance candidate requirement drifted")
    on_disk, _, _ = load_json_mapping_snapshot(
        acceptance_path, label="full-scrape acceptance"
    )
    if on_disk != dict(acceptance):
        raise CandidateError("full-scrape acceptance bytes changed while sealing")


def _production_mutation_audit_binding(*, repo_root: Path) -> dict[str, Any]:
    """Remeasure and bind the exact frozen protected-Hub-write inventory."""

    report_path = _require_canonical_repo_path(
        repo_root / PRODUCTION_MUTATION_AUDIT_RELPATH,
        repo_root=repo_root,
        relative_path=PRODUCTION_MUTATION_AUDIT_RELPATH,
        label="Hugging Face mutation-path audit",
        must_exist=True,
    )
    try:
        audit_capture = mutation_path_audit.validate_frozen_mutation_capture(
            repository_root=repo_root
        )
        measured = audit_capture.report
        source_projection = audit_capture.source_projection
    except mutation_path_audit.MutationPathAuditError as exc:
        raise CandidateError(
            f"Hugging Face mutation-path audit verification failed: {exc}"
        ) from exc
    frozen, frozen_bytes, frozen_sha256 = load_json_mapping_snapshot(
        report_path,
        label="Hugging Face mutation-path audit",
    )
    canonical_bytes = mutation_path_audit._canonical_report_text(frozen).encode(
        "utf-8"
    )
    if frozen != measured or frozen_bytes != canonical_bytes:
        raise CandidateError(
            "Hugging Face mutation-path audit is not the exact canonical "
            "remeasured inventory"
        )
    return {
        "authorizing_hub_upload": False,
        "callsite_count": measured["callsite_count"],
        "inventory_digest_sha256": digest_payload(measured),
        "path": PRODUCTION_MUTATION_AUDIT_RELPATH.as_posix(),
        "protected_callsite_count": measured["protected_callsite_count"],
        "report_sha256": frozen_sha256,
        "schema": mutation_path_audit.SCHEMA,
        "source_file_count": len(source_projection),
        "source_projection_digest_sha256": digest_payload(source_projection),
        "status": "passed",
        "unprotected_count": 0,
        "write_methods": list(measured["write_methods"]),
    }


def assemble_production_candidate(
    *,
    input_map_path: Path | str,
    rights_receipt_path: Path | str,
    production_output_root: Path | str,
    live_baseline_path: Path | str,
    source_revision: str,
    acceptance_report_path: Path | str,
    candidate_report_path: Path | str,
    repo_root: Path | str | None = None,
    require_clean_source: bool = True,
) -> dict[str, Any]:
    """Seal a local-only LCR-084 candidate from verified production bytes."""

    root = _safe_existing_directory(
        repo_root or REPOSITORY_ROOT, label="repository root"
    )
    acceptance_path = _require_canonical_repo_path(
        acceptance_report_path,
        repo_root=root,
        relative_path=PRODUCTION_ACCEPTANCE_RELPATH,
        label="production acceptance report",
        must_exist=True,
    )
    candidate_path = _require_canonical_repo_path(
        candidate_report_path,
        repo_root=root,
        relative_path=DEFAULT_REPORT_RELPATH,
        label="production candidate report",
        must_exist=False,
    )
    acceptance, _, acceptance_file_sha256 = load_json_mapping_snapshot(
        acceptance_path, label="production acceptance report"
    )
    sealed_acceptance_evidence = acceptance.get("evidence")
    if not isinstance(sealed_acceptance_evidence, Mapping):
        raise CandidateError("production acceptance evidence is missing")
    sealed_source_control = sealed_acceptance_evidence.get("source_control")
    if not isinstance(sealed_source_control, Mapping):
        raise CandidateError("production acceptance source binding is missing")
    if require_clean_source:
        require_only_expected_dirty_paths(
            repo_root=root,
            source_revision=source_revision,
            allowed_paths=(_lexical_absolute(live_baseline_path), acceptance_path),
        )
    evidence = collect_production_evidence(
        input_map_path=input_map_path,
        rights_receipt_path=rights_receipt_path,
        production_output_root=production_output_root,
        live_baseline_path=live_baseline_path,
        source_revision=source_revision,
        repo_root=root,
        require_clean_source=False,
        sealed_source_control=sealed_source_control,
    )
    _validate_acceptance_for_production_candidate(
        acceptance,
        acceptance_path=acceptance_path,
        candidate_path=candidate_path,
        evidence=evidence,
        repo_root=root,
    )
    mutation_audit = _production_mutation_audit_binding(repo_root=root)
    evidence_digest = digest_payload(evidence)
    manifest = evidence["production_release"]
    rights = evidence["rights_receipt"]
    payload: dict[str, Any] = {
        "acceptance": {
            "byte_descriptor_complete": True,
            "contains_exact_51": True,
            "full_scrape_acceptance_path": _display_path(
                acceptance_path, repo_root=root
            ),
            "full_scrape_acceptance_report_digest_sha256": acceptance[
                "report_digest_sha256"
            ],
            "full_scrape_acceptance_sealed_at": acceptance["sealed_at"],
            "full_scrape_acceptance_sha256": acceptance_file_sha256,
            "live_official": True,
            "no_hub_mutation": True,
            "production_evidence_digest_sha256": evidence_digest,
            "required_semantic_families": True,
        },
        "authorizing_for_publication": False,
        "authorizing_for_release": False,
        "board_namespace": BOARD_NAMESPACE,
        "bundle": "state-full-live-acceptance-hardening",
        "candidate": {
            "acceptance_schema": PRODUCTION_ACCEPTANCE_SCHEMA,
            "kind": PRODUCTION_KIND,
        },
        "code_version": "2",
        "dataset_repo_id": manifest["dataset_repo_id"],
        "families": list(REQUIRED_FAMILIES),
        "fixture_only": False,
        "goal_id": PRODUCTION_GOAL_ID,
        "hub_upload": False,
        "hub_mutation_performed": False,
        "inputs": {
            "input_map_path": evidence["input_map"]["path"],
            "input_map_sha256": evidence["input_map"]["sha256"],
            "live_baseline_path": evidence["authenticated_live_baseline"]["path"],
            "live_baseline_sha256": evidence["authenticated_live_baseline"]["sha256"],
            "source_rights_receipt_path": rights["path"],
            "source_rights_receipt_sha256": rights["sha256"],
        },
        "jurisdiction_codes": list(CANONICAL_JURISDICTION_ORDER),
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "local_only": False,
        "manifest_digest": manifest["manifest_digest"],
        "manifest_file_sha256": manifest["manifest_file_sha256"],
        "model_id": DEFAULT_EMBEDDING_MODEL_ID,
        "model_revision": DEFAULT_EMBEDDING_MODEL_REVISION,
        "mutation_audit": mutation_audit,
        "network_io_performed": True,
        "producer": PRODUCER,
        "production_generation_local_only": True,
        "production_evidence": dict(evidence),
        "production_evidence_digest_sha256": evidence_digest,
        "program_id": PROGRAM_ID,
        "publication_binding": None,
        "proves_software_contract_only": False,
        "read_only_live_verification": True,
        "release_profile": RELEASE_PROFILE,
        "schema": PRODUCTION_REPORT_SCHEMA,
        "schema_version": PRODUCTION_SCHEMA_VERSION,
        "sealed_at": acceptance["sealed_at"],
        "source_revision": evidence["source_control"]["revision"],
        "source_rights_catalog_digest": rights["catalog_digest_sha256"],
        "source_rights_receipt_digest": rights["receipt_digest_sha256"],
        "status": "passed",
        "task_id": PRODUCTION_TASK_ID,
        "validation": {
            "artifact_count": manifest["artifact_count"],
            "descriptor_bytes_verified": True,
            "local_release_verified": True,
            "valid": True,
        },
    }
    payload["report_digest_sha256"] = _digest_for_report(payload)
    return payload


_PRODUCTION_CANDIDATE_KEYS: Final = frozenset(
    {
        "acceptance",
        "authorizing_for_publication",
        "authorizing_for_release",
        "board_namespace",
        "bundle",
        "candidate",
        "code_version",
        "dataset_repo_id",
        "families",
        "fixture_only",
        "goal_id",
        "hub_upload",
        "hub_mutation_performed",
        "inputs",
        "jurisdiction_codes",
        "jurisdiction_count",
        "local_only",
        "manifest_digest",
        "manifest_file_sha256",
        "model_id",
        "model_revision",
        "mutation_audit",
        "network_io_performed",
        "producer",
        "production_generation_local_only",
        "production_evidence",
        "production_evidence_digest_sha256",
        "program_id",
        "publication_binding",
        "proves_software_contract_only",
        "read_only_live_verification",
        "release_profile",
        "report_digest_sha256",
        "schema",
        "schema_version",
        "sealed_at",
        "source_revision",
        "source_rights_catalog_digest",
        "source_rights_receipt_digest",
        "status",
        "task_id",
        "validation",
    }
)


_PRODUCTION_PUBLICATION_BINDING_KEYS: Final = frozenset(
    {
        "plan_digest",
        "policy_proof_digest",
        "release_manifest_digest",
        "staging_candidate_digest",
    }
)


def production_candidate_staging_digest(payload: Mapping[str, Any]) -> str:
    """Return candidate identity A with the publication binding set to null."""

    if not isinstance(payload, Mapping):
        raise CandidateError("production candidate report must be an object")
    if payload.get("schema") != PRODUCTION_REPORT_SCHEMA:
        raise CandidateError("staging digest requires an LCR-084 @2 candidate")
    if "publication_binding" not in payload:
        raise CandidateError("production candidate lacks publication_binding")
    staging_payload = dict(payload)
    staging_payload["publication_binding"] = None
    return _digest_for_report(staging_payload)


def check_production_candidate_publication_binding(
    payload: Mapping[str, Any],
    *,
    phase: str | None = None,
) -> dict[str, str] | None:
    """Validate the exact staging-null/main-object publication binding.

    With no phase this accepts either structurally valid form.  Phase-aware
    callers must name ``state_staging`` or ``state_main`` and receive the
    corresponding null or populated form only.
    """

    if not isinstance(payload, Mapping):
        raise CandidateError("production candidate report must be an object")
    if payload.get("schema") != PRODUCTION_REPORT_SCHEMA:
        raise CandidateError("publication binding requires an LCR-084 @2 candidate")
    if phase not in {None, "state_staging", "state_main"}:
        raise CandidateError(f"unsupported publication-binding phase: {phase!r}")
    if "publication_binding" not in payload:
        raise CandidateError("production candidate lacks publication_binding")

    binding = payload["publication_binding"]
    if binding is None:
        if phase == "state_main":
            raise CandidateError(
                "state_main requires a populated publication_binding"
            )
        return None
    if phase == "state_staging":
        raise CandidateError("state_staging requires publication_binding=null")
    if type(binding) is not dict:
        raise CandidateError("publication_binding must be null or an exact object")
    missing = sorted(_PRODUCTION_PUBLICATION_BINDING_KEYS.difference(binding))
    extra = sorted(set(binding).difference(_PRODUCTION_PUBLICATION_BINDING_KEYS))
    if missing or extra:
        raise CandidateError(
            "publication_binding fields drifted: "
            f"missing={missing} extra={extra}"
        )
    normalized: dict[str, str] = {}
    for field_name in sorted(_PRODUCTION_PUBLICATION_BINDING_KEYS):
        value = binding[field_name]
        if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
            raise CandidateError(
                f"publication_binding.{field_name} must be a lowercase SHA-256"
            )
        normalized[field_name] = value
    if normalized["release_manifest_digest"] != payload.get("manifest_digest"):
        raise CandidateError(
            "publication_binding release manifest differs from the candidate"
        )
    expected_staging_digest = production_candidate_staging_digest(payload)
    if normalized["staging_candidate_digest"] != expected_staging_digest:
        raise CandidateError(
            "publication_binding staging candidate digest differs from A"
        )
    return normalized


def _validate_production_evidence_schema(evidence: Mapping[str, Any]) -> None:
    """Apply the acceptance evidence schema recursively to candidate evidence."""

    schema = load_json_mapping(
        REPOSITORY_ROOT / "data/legal/state_laws_full_scrape_acceptance.schema.json",
        label="LCR-084 acceptance schema",
    )
    definitions = schema.get("$defs")
    if not isinstance(definitions, Mapping) or "evidence" not in definitions:
        raise CandidateError("LCR-084 schema lacks its production evidence definition")
    evidence_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": dict(definitions),
        "$ref": "#/$defs/evidence",
    }
    try:
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(evidence_schema)
        errors = sorted(
            Draft202012Validator(evidence_schema).iter_errors(dict(evidence)),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
    except ImportError as exc:
        raise CandidateError(
            "jsonschema is required for a production candidate"
        ) from exc
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise CandidateError(
            f"production candidate evidence schema failed at {location}: {first.message}"
        )


def _candidate_timestamp(value: Any) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CandidateError("production candidate sealed_at is not RFC3339") from exc
    if parsed.tzinfo is None:
        raise CandidateError("production candidate sealed_at lacks a timezone")
    return parsed.astimezone(UTC)


def _validate_candidate_evidence_chronology(
    evidence: Mapping[str, Any],
    *,
    sealed_at: datetime,
    checked_at: datetime,
) -> None:
    """Apply the acceptance freshness policy to standalone candidate checks."""

    baseline = evidence.get("authenticated_live_baseline")
    jurisdictions = evidence.get("jurisdictions")
    if not isinstance(baseline, Mapping) or not isinstance(jurisdictions, list):
        raise CandidateError("production candidate chronology evidence is missing")
    codes = [
        str(item.get("jurisdiction") or "")
        for item in jurisdictions
        if isinstance(item, Mapping)
    ]
    if codes != list(CANONICAL_JURISDICTION_ORDER):
        raise CandidateError("production candidate chronology is not exact-51")
    baseline_observed = _candidate_timestamp(baseline.get("observed_at"))
    if (
        baseline_observed > sealed_at
        or baseline_observed > checked_at
        or checked_at - baseline_observed > PRODUCTION_MAX_EVIDENCE_AGE
    ):
        raise CandidateError("production candidate live baseline is stale or misordered")
    for item in jurisdictions:
        if not isinstance(item, Mapping):
            raise CandidateError("production candidate jurisdiction chronology is malformed")
        code = str(item.get("jurisdiction") or "")
        observed = _candidate_timestamp(item.get("observation_time"))
        run_sealed = _candidate_timestamp(item.get("run_seal_created_at"))
        if (
            observed > checked_at
            or observed > sealed_at
            or checked_at - observed > PRODUCTION_MAX_EVIDENCE_AGE
        ):
            raise CandidateError(f"{code} production observation is stale or misordered")
        if run_sealed < observed or run_sealed > sealed_at or run_sealed > checked_at:
            raise CandidateError(f"{code} production run seal chronology drifted")


def check_production_candidate_report(
    payload: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
    remeasure_production_evidence: bool = True,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise CandidateError("production candidate report must be an object")
    missing = sorted(_PRODUCTION_CANDIDATE_KEYS.difference(payload))
    extra = sorted(set(payload).difference(_PRODUCTION_CANDIDATE_KEYS))
    if missing or extra:
        raise CandidateError(
            f"production candidate fields drifted: missing={missing} extra={extra}"
        )
    if (
        payload.get("schema") != PRODUCTION_REPORT_SCHEMA
        or payload.get("schema_version") != PRODUCTION_SCHEMA_VERSION
        or payload.get("task_id") != PRODUCTION_TASK_ID
        or payload.get("goal_id") != PRODUCTION_GOAL_ID
        or payload.get("program_id") != PROGRAM_ID
        or payload.get("status") != "passed"
        or payload.get("board_namespace") != BOARD_NAMESPACE
        or payload.get("bundle") != "state-full-live-acceptance-hardening"
        or payload.get("code_version") != "2"
        or payload.get("producer") != PRODUCER
        or payload.get("release_profile") != RELEASE_PROFILE
    ):
        raise CandidateError("production candidate identity/status drifted")
    check_production_candidate_publication_binding(payload)
    if (
        payload.get("fixture_only") is not False
        or payload.get("proves_software_contract_only") is not False
        or payload.get("authorizing_for_publication") is not False
        or payload.get("authorizing_for_release") is not False
        or payload.get("hub_upload") is not False
        or payload.get("hub_mutation_performed") is not False
        or payload.get("local_only") is not False
        or payload.get("production_generation_local_only") is not True
        or payload.get("network_io_performed") is not True
        or payload.get("read_only_live_verification") is not True
    ):
        raise CandidateError("production candidate safety flags drifted")
    candidate = payload.get("candidate")
    if candidate != {
        "acceptance_schema": PRODUCTION_ACCEPTANCE_SCHEMA,
        "kind": PRODUCTION_KIND,
    }:
        raise CandidateError("production candidate kind drifted")
    if payload.get("jurisdiction_codes") != list(CANONICAL_JURISDICTION_ORDER):
        raise CandidateError("production candidate is not canonical exact-51")
    if payload.get("jurisdiction_count") != EXPECTED_JURISDICTION_COUNT:
        raise CandidateError("production candidate jurisdiction_count is not exactly 51")
    if payload.get("families") != list(REQUIRED_FAMILIES):
        raise CandidateError("production candidate semantic families drifted")
    evidence = payload.get("production_evidence")
    if not isinstance(evidence, Mapping):
        raise CandidateError("production candidate lacks production_evidence")
    _validate_production_evidence_schema(evidence)
    evidence_digest = digest_payload(evidence)
    if payload.get("production_evidence_digest_sha256") != evidence_digest:
        raise CandidateError("production candidate evidence digest drifted")
    release = evidence.get("production_release")
    rights = evidence.get("rights_receipt")
    source_control = evidence.get("source_control")
    if not all(isinstance(item, Mapping) for item in (release, rights, source_control)):
        raise CandidateError("production candidate evidence surfaces are malformed")
    if (
        payload.get("manifest_digest") != release.get("manifest_digest")
        or payload.get("manifest_file_sha256") != release.get("manifest_file_sha256")
        or payload.get("source_revision") != source_control.get("revision")
        or payload.get("source_rights_catalog_digest")
        != rights.get("catalog_digest_sha256")
        or payload.get("source_rights_receipt_digest")
        != rights.get("receipt_digest_sha256")
    ):
        raise CandidateError("production candidate top-level evidence bindings drifted")
    if (
        payload.get("dataset_repo_id") != DEFAULT_DATASET_REPO_ID
        or payload.get("dataset_repo_id") != release.get("dataset_repo_id")
    ):
        raise CandidateError("production candidate dataset repository drifted")
    if payload.get("model_id") != DEFAULT_EMBEDDING_MODEL_ID:
        raise CandidateError("production candidate model_id drifted")
    if payload.get("model_revision") != DEFAULT_EMBEDDING_MODEL_REVISION:
        raise CandidateError("production candidate model_revision drifted")
    inputs = payload.get("inputs")
    baseline = evidence.get("authenticated_live_baseline")
    input_map = evidence.get("input_map")
    if not all(isinstance(item, Mapping) for item in (inputs, baseline, input_map)):
        raise CandidateError("production candidate input bindings are malformed")
    if inputs != {
        "input_map_path": input_map.get("path"),
        "input_map_sha256": input_map.get("sha256"),
        "live_baseline_path": baseline.get("path"),
        "live_baseline_sha256": baseline.get("sha256"),
        "source_rights_receipt_path": rights.get("path"),
        "source_rights_receipt_sha256": rights.get("sha256"),
    }:
        raise CandidateError("production candidate exact inputs drifted")
    acceptance = payload.get("acceptance")
    if not isinstance(acceptance, Mapping) or set(acceptance) != {
        "byte_descriptor_complete",
        "contains_exact_51",
        "full_scrape_acceptance_path",
        "full_scrape_acceptance_report_digest_sha256",
        "full_scrape_acceptance_sealed_at",
        "full_scrape_acceptance_sha256",
        "live_official",
        "no_hub_mutation",
        "production_evidence_digest_sha256",
        "required_semantic_families",
    } or any(
        acceptance.get(flag) is not True
        for flag in (
            "byte_descriptor_complete", "contains_exact_51", "live_official",
            "no_hub_mutation", "required_semantic_families",
        )
    ):
        raise CandidateError("production candidate acceptance flags drifted")
    if (
        not str(acceptance.get("full_scrape_acceptance_path") or "").strip()
        or _SHA256_RE.fullmatch(
            str(acceptance.get("full_scrape_acceptance_report_digest_sha256") or "")
        )
        is None
        or _SHA256_RE.fullmatch(
            str(acceptance.get("full_scrape_acceptance_sha256") or "")
        )
        is None
        or acceptance.get("full_scrape_acceptance_sealed_at")
        != payload.get("sealed_at")
    ):
        raise CandidateError("production candidate acceptance byte binding is malformed")
    root = _safe_existing_directory(
        repo_root or REPOSITORY_ROOT, label="repository root"
    )
    initial_mutation_audit = _production_mutation_audit_binding(repo_root=root)
    if payload.get("mutation_audit") != initial_mutation_audit:
        raise CandidateError(
            "production candidate mutation-path audit binding drifted"
        )
    expected_acceptance_path = _lexical_absolute(
        root / PRODUCTION_ACCEPTANCE_RELPATH
    )
    if _lexical_absolute(
        acceptance.get("full_scrape_acceptance_path"), base=root
    ) != expected_acceptance_path:
        raise CandidateError(
            "production candidate must bind the canonical full-scrape acceptance"
        )
    acceptance_path = resolve_evidence_path(
        acceptance.get("full_scrape_acceptance_path"),
        repo_root=root,
        label="candidate-bound full-scrape acceptance",
    )
    acceptance_document, acceptance_bytes, acceptance_file_sha256 = (
        load_json_mapping_snapshot(
        acceptance_path,
        label="candidate-bound full-scrape acceptance",
        )
    )
    if (
        acceptance_file_sha256 != acceptance.get("full_scrape_acceptance_sha256")
        or acceptance_document.get("report_digest_sha256")
        != acceptance.get("full_scrape_acceptance_report_digest_sha256")
        or acceptance_document.get("sealed_at")
        != acceptance.get("full_scrape_acceptance_sealed_at")
        or acceptance_document.get("sealed_at") != payload.get("sealed_at")
    ):
        raise CandidateError(
            "production candidate does not bind exact acceptance bytes/seal time"
        )
    if acceptance.get("production_evidence_digest_sha256") != evidence_digest:
        raise CandidateError("candidate acceptance/evidence binding drifted")
    if payload.get("report_digest_sha256") != _digest_for_report(payload):
        raise CandidateError("production candidate report digest drifted")

    canonical_candidate_path = root / DEFAULT_REPORT_RELPATH
    _validate_acceptance_for_production_candidate(
        acceptance_document,
        acceptance_path=acceptance_path,
        candidate_path=canonical_candidate_path,
        evidence=evidence,
        repo_root=root,
    )
    validation = payload.get("validation")
    if validation != {
        "artifact_count": release.get("artifact_count"),
        "descriptor_bytes_verified": True,
        "local_release_verified": True,
        "valid": True,
    }:
        raise CandidateError("production candidate validation drifted")
    sealed_at = _candidate_timestamp(payload.get("sealed_at"))
    checked_at = datetime.now(UTC)
    if sealed_at > checked_at:
        raise CandidateError("production candidate sealed_at is in the future")
    _validate_candidate_evidence_chronology(
        evidence,
        sealed_at=sealed_at,
        checked_at=checked_at,
    )
    if remeasure_production_evidence is not True:
        if remeasure_production_evidence is not False:
            raise CandidateError(
                "remeasure_production_evidence must be an exact boolean"
            )
        return {
            "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
            "ok": True,
            "task_id": PRODUCTION_TASK_ID,
            "valid": True,
        }

    resolved_input_map = resolve_evidence_path(
        input_map.get("path"), repo_root=root, label="candidate input map"
    )
    resolved_rights = resolve_evidence_path(
        rights.get("path"), repo_root=root, label="candidate rights receipt"
    )
    resolved_output_root = resolve_evidence_directory(
        release.get("output_root"),
        repo_root=root,
        label="candidate production output root",
    )
    resolved_baseline = _require_canonical_repo_path(
        str(baseline.get("path") or ""),
        repo_root=root,
        relative_path=DEFAULT_LIVE_BASELINE_RELPATH,
        label="candidate authenticated live baseline",
        must_exist=True,
    )

    # Production --check is an evidence verifier, not a self-digest checker.
    # There is intentionally no public switch that disables the authenticated
    # Hub baseline read or the current-code, process-network-denied retained
    # replay performed by collect_production_evidence.
    try:
        remeasured = collect_production_evidence(
            input_map_path=resolved_input_map,
            rights_receipt_path=resolved_rights,
            production_output_root=resolved_output_root,
            live_baseline_path=resolved_baseline,
            source_revision=str(source_control.get("revision") or ""),
            repo_root=root,
            require_clean_source=False,
            sealed_source_control=source_control,
        )
    except CandidateError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise CandidateError(
            f"production candidate evidence remeasurement failed: {exc}"
        ) from exc
    if remeasured != dict(evidence):
        raise CandidateError(
            "production candidate evidence differs from current verified bytes"
        )
    _validate_acceptance_for_production_candidate(
        acceptance_document,
        acceptance_path=acceptance_path,
        candidate_path=canonical_candidate_path,
        evidence=remeasured,
        repo_root=root,
    )
    (
        final_acceptance_document,
        final_acceptance_bytes,
        final_acceptance_sha256,
    ) = load_json_mapping_snapshot(
        acceptance_path,
        label="candidate-bound full-scrape acceptance final bookend",
    )
    if (
        final_acceptance_document != acceptance_document
        or final_acceptance_bytes != acceptance_bytes
        or final_acceptance_sha256 != acceptance_file_sha256
    ):
        raise CandidateError(
            "candidate-bound full-scrape acceptance changed during "
            "production remeasurement"
        )
    if (
        _production_mutation_audit_binding(repo_root=root)
        != initial_mutation_audit
    ):
        raise CandidateError(
            "candidate-bound mutation-path audit changed during production "
            "remeasurement"
        )
    checked_at = datetime.now(UTC)
    if sealed_at > checked_at:
        raise CandidateError("production candidate sealed_at is in the future")
    _validate_candidate_evidence_chronology(
        remeasured,
        sealed_at=sealed_at,
        checked_at=checked_at,
    )
    return {
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "ok": True,
        "task_id": PRODUCTION_TASK_ID,
        "valid": True,
    }


def check_candidate_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise CandidateError("release candidate report must be an object")
    if (
        payload.get("schema") == PRODUCTION_REPORT_SCHEMA
        or payload.get("schema_version") == PRODUCTION_SCHEMA_VERSION
        or payload.get("fixture_only") is False
    ):
        return check_production_candidate_report(payload)
    if payload.get("task_id") != TASK_ID:
        raise CandidateError(f"report task_id must be {TASK_ID}")
    if payload.get("goal_id") != GOAL_ID:
        raise CandidateError(f"report goal_id must be {GOAL_ID}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise CandidateError("report schema_version drifted")
    if payload.get("authorizing_for_publication") is not False:
        raise CandidateError("release candidate must not authorize publication")
    if payload.get("hub_upload") is not False:
        raise CandidateError("release candidate must not authorize Hub upload")
    acceptance = payload.get("acceptance")
    if not isinstance(acceptance, Mapping):
        raise CandidateError("acceptance must be a mapping")
    for flag in (
        "byte_descriptor_complete",
        "contains_exact_51",
        "no_stale_model_revision",
        "required_semantic_families",
        "ready_for_transactional_staging",
    ):
        if acceptance.get(flag) is not True:
            raise CandidateError(f"acceptance.{flag} is not true")
    if acceptance.get("criteria") != ACCEPTANCE_CRITERIA:
        raise CandidateError("acceptance criteria drifted")
    codes = payload.get("jurisdiction_codes")
    if not isinstance(codes, list) or codes != list(CANONICAL_JURISDICTION_ORDER):
        raise CandidateError("report jurisdiction_codes are not the sealed exact-51 set")
    if int(payload.get("jurisdiction_count") or 0) != EXPECTED_JURISDICTION_COUNT:
        raise CandidateError("report jurisdiction_count is not 51")
    if payload.get("model_id") != DEFAULT_EMBEDDING_MODEL_ID:
        raise CandidateError("model_id is not the pinned GTE-small id")
    if payload.get("model_revision") != DEFAULT_EMBEDDING_MODEL_REVISION:
        raise CandidateError("model_revision is not the pinned GTE revision")
    if payload.get("previous_public_pin") != PREVIOUS_PUBLIC_PIN:
        raise CandidateError("previous_public_pin drifted")
    if payload.get("rollback_target") != PREVIOUS_PUBLIC_PIN:
        raise CandidateError("rollback_target drifted")
    families = payload.get("families")
    if not isinstance(families, list) or set(families) != set(REQUIRED_FAMILIES):
        raise CandidateError("required semantic families drifted")
    validation = payload.get("validation")
    if not isinstance(validation, Mapping) or validation.get("valid") is not True:
        raise CandidateError("validation.valid is not true")
    declared = payload.get("report_digest_sha256")
    actual = _digest_for_report(payload)
    if not isinstance(declared, str) or declared != actual:
        raise CandidateError("report_digest_sha256 does not match canonical payload")
    assert_no_secrets_or_home_paths(payload)
    return {
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "ok": True,
        "task_id": TASK_ID,
        "valid": True,
    }


def check_report_matches_build(
    on_disk: Mapping[str, Any],
    measured: Mapping[str, Any],
) -> None:
    keys = (
        "task_id",
        "goal_id",
        "schema_version",
        "jurisdiction_codes",
        "jurisdiction_count",
        "manifest_digest",
        "release_root_cid",
        "model_id",
        "model_revision",
        "acceptance",
        "families",
    )
    for key in keys:
        if on_disk.get(key) != measured.get(key):
            raise CandidateError(f"committed report {key} drifted from measurement")
    if _digest_for_report(on_disk) != _digest_for_report(measured):
        raise CandidateError("committed report digest drifted from measurement")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_state_laws_hf_release.py",
        description=(
            "Assemble the exact-51 state-law Hugging Face release candidate "
            "(LCR-039). Fixture-only default; no Hub upload."
        ),
    )
    report_mode = parser.add_mutually_exclusive_group()
    report_mode.add_argument(
        "--check",
        action="store_true",
        help="Re-assemble the candidate and validate the frozen report without rewriting it.",
    )
    report_mode.add_argument(
        "--write",
        action="store_true",
        help="Write the release-candidate report to --report.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=f"Report path (default: {DEFAULT_REPORT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--fixture-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Offline fixture assembly (default: true; no network, no Hub).",
    )
    parser.add_argument(
        "--production-local",
        action="store_true",
        help=(
            "Seal/check a completed exact-51 local production release. Requires "
            "--no-fixture-only and the four production evidence arguments; never uploads."
        ),
    )
    parser.add_argument("--input-map", type=Path, default=None)
    parser.add_argument("--rights-receipt", type=Path, default=None)
    parser.add_argument("--production-output-root", type=Path, default=None)
    parser.add_argument(
        "--live-baseline",
        type=Path,
        default=None,
        help=f"Fresh authenticated LCR-081 receipt (default: {DEFAULT_LIVE_BASELINE_RELPATH})",
    )
    parser.add_argument("--source-revision", default="")
    parser.add_argument(
        "--acceptance-report",
        type=Path,
        default=None,
        help=(
            "Sealed LCR-084 full-scrape acceptance report (default: "
            "docs/reports/legal_corpora_reindex/full_scrape_acceptance.json)"
        ),
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the candidate report JSON to stdout.",
    )
    parser.add_argument(
        "--hub-upload",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code or 0)

    report_path = _lexical_absolute(
        args.report if args.report is not None else default_report_path()
    )
    try:
        if getattr(args, "hub_upload", False):
            raise CandidateError("Hub upload is forbidden in LCR-039")
        if args.production_local:
            if bool(args.fixture_only):
                raise CandidateError(
                    "--production-local requires explicit --no-fixture-only"
                )
            required = {
                "--input-map": args.input_map,
                "--rights-receipt": args.rights_receipt,
                "--production-output-root": args.production_output_root,
                "--source-revision": args.source_revision,
            }
            missing = [name for name, value in required.items() if value in (None, "")]
            if missing:
                raise CandidateError(
                    f"production-local evidence arguments are required: {missing}"
                )
            acceptance_path = _lexical_absolute(
                args.acceptance_report
                if args.acceptance_report is not None
                else REPOSITORY_ROOT / PRODUCTION_ACCEPTANCE_RELPATH
            )
            live_baseline_path = _lexical_absolute(
                args.live_baseline
                if args.live_baseline is not None
                else REPOSITORY_ROOT / DEFAULT_LIVE_BASELINE_RELPATH
            )
            _require_canonical_repo_path(
                acceptance_path,
                repo_root=REPOSITORY_ROOT,
                relative_path=PRODUCTION_ACCEPTANCE_RELPATH,
                label="production acceptance report",
                must_exist=True,
            )
            _require_canonical_repo_path(
                report_path,
                repo_root=REPOSITORY_ROOT,
                relative_path=DEFAULT_REPORT_RELPATH,
                label="production candidate report",
                must_exist=bool(args.check),
            )
            if args.check:
                if not report_path.is_file():
                    raise CandidateError(
                        f"production candidate report not found for --check: {report_path}"
                    )
                on_disk, _, report_file_sha256 = load_json_mapping_snapshot(
                    report_path, label="production candidate report"
                )
                check_production_candidate_report(on_disk)
                bookend, _, bookend_sha256 = load_json_mapping_snapshot(
                    report_path, label="production candidate report bookend"
                )
                if bookend_sha256 != report_file_sha256 or bookend != on_disk:
                    raise CandidateError(
                        "production candidate report changed during verification"
                    )
                if args.print_json:
                    sys.stdout.write(json.dumps(dict(on_disk), indent=2, sort_keys=True) + "\n")
                print(
                    "state_laws_release_candidate: PASS "
                    f"task={PRODUCTION_TASK_ID} jurisdictions=51 valid=True"
                )
                return 0
            measured = assemble_production_candidate(
                input_map_path=args.input_map,
                rights_receipt_path=args.rights_receipt,
                production_output_root=args.production_output_root,
                live_baseline_path=live_baseline_path,
                source_revision=args.source_revision,
                acceptance_report_path=acceptance_path,
                candidate_report_path=report_path,
                repo_root=REPOSITORY_ROOT,
                require_clean_source=True,
            )
            check_production_candidate_report(measured)
            if args.write:
                write_json_report(measured, report_path)
                print(f"wrote production release candidate report: {report_path}", file=sys.stderr)
            if args.print_json:
                sys.stdout.write(json.dumps(measured, indent=2, sort_keys=True) + "\n")
            if args.write or args.print_json:
                return 0
            print(
                "state_laws_release_candidate: PASS "
                f"task={PRODUCTION_TASK_ID} jurisdictions=51 valid=True"
            )
            return 0
        if not bool(args.fixture_only):
            raise CandidateError(
                "--no-fixture-only is valid only with explicit --production-local"
            )

        measured = assemble_candidate(repo_root=REPOSITORY_ROOT)
        check_candidate_report(measured)

        if args.write:
            write_json_report(measured, report_path)
            print(f"wrote release candidate report: {report_path}", file=sys.stderr)

        if args.check:
            if not report_path.is_file():
                raise CandidateError(
                    f"frozen release candidate report not found for --check: {report_path}"
                )
            on_disk, _, report_file_sha256 = load_json_mapping_snapshot(
                report_path, label="frozen release candidate report"
            )
            check_candidate_report(on_disk)
            check_report_matches_build(on_disk, measured)
            result = check_candidate_report(on_disk)
            bookend, _, bookend_sha256 = load_json_mapping_snapshot(
                report_path, label="frozen release candidate report bookend"
            )
            if bookend_sha256 != report_file_sha256 or bookend != on_disk:
                raise CandidateError(
                    "frozen release candidate report changed during verification"
                )
            print(
                "state_laws_release_candidate: PASS "
                f"task={result.get('task_id')} "
                f"jurisdictions={result.get('jurisdiction_count')} "
                f"valid={result.get('valid')}"
            )
            if args.print_json:
                sys.stdout.write(json.dumps(dict(on_disk), indent=2, sort_keys=True) + "\n")
            return 0

        if args.print_json:
            sys.stdout.write(json.dumps(measured, indent=2, sort_keys=True) + "\n")
            return 0
        if args.write:
            return 0
        result = check_candidate_report(measured)
        print(
            "state_laws_release_candidate: PASS "
            f"task={result.get('task_id')} "
            f"jurisdictions={result.get('jurisdiction_count')} "
            f"valid={result.get('valid')}"
        )
        print("hint: pass --check to validate the frozen report", file=sys.stderr)
        return 0
    except CandidateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
