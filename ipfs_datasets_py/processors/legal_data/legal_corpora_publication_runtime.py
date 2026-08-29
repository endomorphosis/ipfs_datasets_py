"""Canonical repository and runtime authority for legal-corpora publication (LCR-080).

The in-memory gate (LCR-074) still evaluates a constructed request. This
runtime is the only adapter that may authorize a live mutation: it derives
repository HEAD, task lineage, receipts, candidate manifest, credentials,
and any main seal from **fixed canonical paths** at the actual clean 40-hex
HEAD and rechecks that evidence immediately before invoking a network
callback.

Caller-asserted statuses, receipts, digests, commits, path overrides, or
seals cannot authorize. LCR-083 ``source_rights_binding`` remains a required
gate. This module never contacts the Hub except through a caller-supplied
read-only principal probe and a single upload callback after authorization.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Optional, Sequence, TypeVar, Union


def _pin_trusted_system_git() -> tuple[Path, str]:
    """Pin one root-owned system Git without consulting ambient ``PATH``."""

    for candidate in (Path("/usr/bin/git"), Path("/usr/local/bin/git")):
        try:
            resolved = candidate.resolve(strict=True)
            metadata = resolved.stat(follow_symlinks=False)
        except OSError:
            continue
        if (
            resolved.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or not metadata.st_mode & stat.S_IXUSR
        ):
            continue
        return resolved, hashlib.sha256(resolved.read_bytes()).hexdigest()
    raise RuntimeError("no trusted root-owned system Git executable is available")


_TRUSTED_GIT_EXECUTABLE, _TRUSTED_GIT_SHA256 = _pin_trusted_system_git()
del _pin_trusted_system_git
_AUTHORITY_GIT_ENVIRONMENT: Final[Mapping[str, str]] = MappingProxyType(
    {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "TZ": "UTC",
    }
)

from ipfs_datasets_py.huggingface.protected_repo_guard import (
    CanonicalMutationBinding,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (
    AUTHORIZED_DATASET_REPO_IDS,
    BASELINE_REVISIONS,
    REQUIRED_PUBLICATION_GATES,
    RIGHTS_RECEIPT_RELPATH,
    SECRET_ENV_NAMES,
    STATE_DATASET_REPO_ID,
    PublicationGateDecision,
    PublicationGateDeniedError,
    PublicationGateError,
    PublicationPhase,
    credentials_scope_for,
    evaluate_publication_gate,
    normalize_sha256,
    phase_requirements,
    prepublication_seal_required,
    reject_credentials_in_payload,
    require_immutable_revision,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (
    PROGRAM_ID as GATE_PROGRAM_ID,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (
    SUCCESSOR_TASK_ID as GATE_SUCCESSOR_TASK_ID,
)
from ipfs_datasets_py.processors.legal_data.legal_corpora_publication_gate import (
    TASK_ID as GATE_TASK_ID,
)

# ---------------------------------------------------------------------------
# Schema / task identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "legal-corpora-publication-runtime-v1"
RUNTIME_SCHEMA: Final = "ipfs_datasets_py/legal-corpora-publication-runtime@1"
TASK_ID: Final = "LCR-080"
GOAL_ID: Final = "LCR-G142"
PROGRAM_ID: Final = GATE_PROGRAM_ID
PRODUCER: Final = "legal_corpora_publication_runtime.py"
PREDECESSOR_GATE_TASK_ID: Final = GATE_TASK_ID
PREDECESSOR_RIGHTS_TASK_ID: Final = GATE_SUCCESSOR_TASK_ID

TOKEN_ENV_ALLOWLIST: Final = SECRET_ENV_NAMES
# Each phase reaches the same source-attested, payload-bound publisher capsule.
# A branch creation and its subsequent commit still require two independent
# calls and therefore two one-shot runtime capabilities.
CANONICAL_MUTATION_EXECUTOR_PHASES: Final = frozenset(
    {"state_staging", "state_main", "federal_staging", "federal_main"}
)

RECEIPT_SCHEMA_V1: Final = "ipfs_datasets_py/legal-corpora-publication-receipt@1"
MANIFEST_SCHEMA_V1: Final = "ipfs_datasets_py/legal-corpora-candidate-manifest@1"
PRODUCTION_MANIFEST_SCHEMA_V2: Final = (
    "ipfs_datasets_py/legal-corpora-reindex-release-candidate@2"
)
PRODUCTION_ACCEPTANCE_SCHEMA_V2: Final = (
    "ipfs_datasets_py/state-laws-full-scrape-acceptance@2"
)
FEDERAL_PRODUCTION_CANDIDATE_SCHEMA: Final = (
    "ipfs_datasets_py/legal-corpora-reindex-federal-candidate@1"
)
FEDERAL_STAGING_CANARY_SCHEMA_V1: Final = (
    "ipfs_datasets_py/legal-corpora-reindex-federal-staging-canary@1"
)
FEDERAL_FULL_LIVE_ACCEPTANCE_SCHEMA_V2: Final = (
    "ipfs_datasets_py/federal-register-full-live-acceptance@2"
)
MUTATION_AUDIT_SCHEMA_V2: Final = (
    "ipfs_datasets_py/legal-corpora-hugging-face-mutation-path-audit@2"
)
SEAL_SCHEMA_V1: Final = "ipfs_datasets_py/legal-corpora-prepublication-seal@1"
LIVE_SOURCE_RIGHTS_REPORT_SCHEMA: Final = (
    "ipfs_datasets_py/legal-source-rights-compliance@2"
)
ALLOWED_RECEIPT_SCHEMAS: Final = frozenset(
    {
        RECEIPT_SCHEMA_V1,
        MANIFEST_SCHEMA_V1,
        PRODUCTION_MANIFEST_SCHEMA_V2,
        PRODUCTION_ACCEPTANCE_SCHEMA_V2,
        MUTATION_AUDIT_SCHEMA_V2,
        SEAL_SCHEMA_V1,
        LIVE_SOURCE_RIGHTS_REPORT_SCHEMA,
        FEDERAL_STAGING_CANARY_SCHEMA_V1,
    }
)

RELEASE_POLICY_RELPATH: Final = (
    "data/agent_supervisor/legal_corpora_reindex/bundles/release_policy.json"
)
TASKBOARD_RELPATH: Final = "docs/architecture/legal_corpora_reindex.todo.md"
OBJECTIVES_RELPATH: Final = "docs/architecture/legal_corpora_reindex.objectives.md"
STATE_CANDIDATE_MANIFEST_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/release_candidate.json"
)
FEDERAL_CANDIDATE_MANIFEST_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/federal_candidate.json"
)
STATE_PREPUBLICATION_SEAL_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/state_prepublication_seal.json"
)
STATE_STAGING_UPLOAD_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/staging_upload.json"
)
STATE_STAGING_CANARY_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/staging_canary.json"
)
FEDERAL_PREPUBLICATION_SEAL_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/federal_prepublication_seal.json"
)
STATE_DATASET_CARD_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/state_dataset_card.md"
)
MUTATION_AUDIT_REPORT_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/"
    "hugging_face_mutation_path_audit.json"
)
MUTATION_AUDIT_SCHEMA_RELPATH: Final = (
    "data/legal/legal_corpora_hugging_face_mutation_path_audit.schema.json"
)
_NATIVE_PHASE_RECEIPT_SCHEMAS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "docs/reports/legal_corpora_reindex/live_baseline_provenance_receipt.json": (
            "ipfs_datasets_py/legal-corpora-reindex-live-baseline-provenance@2"
        ),
        "docs/reports/legal_corpora_reindex/full_scrape_acceptance.json": (
            "ipfs_datasets_py/legal-corpora-reindex-full-scrape-acceptance@1"
        ),
        "docs/reports/legal_corpora_reindex/local_e2e.json": (
            "ipfs_datasets_py/legal-corpora-reindex-local-e2e@1"
        ),
        STATE_CANDIDATE_MANIFEST_RELPATH: (
            "ipfs_datasets_py/legal-corpora-reindex-release-candidate@1"
        ),
        "docs/reports/legal_corpora_reindex/federal_inventory.json": (
            "ipfs_datasets_py/legal-corpora-reindex-federal-inventory@1"
        ),
        "docs/reports/legal_corpora_reindex/federal_fulltext_coverage.json": (
            "ipfs_datasets_py/legal-corpora-reindex-federal-fulltext-coverage@1"
        ),
        FEDERAL_CANDIDATE_MANIFEST_RELPATH: (
            "ipfs_datasets_py/legal-corpora-reindex-federal-candidate@1"
        ),
        "docs/reports/legal_corpora_reindex/federal_evaluation.json": (
            "ipfs_datasets_py/legal-corpora-reindex-federal-evaluation@1"
        ),
        "docs/reports/legal_corpora_reindex/federal_full_live_acceptance.json": (
            FEDERAL_FULL_LIVE_ACCEPTANCE_SCHEMA_V2
        ),
        "docs/reports/legal_corpora_reindex/federal_adjacency_reconciliation.json": (
            "ipfs_datasets_py/legal-corpora-reindex-federal-adjacency@1"
        ),
        "docs/reports/legal_corpora_reindex/federal_staging_canary.json": (
            FEDERAL_STAGING_CANARY_SCHEMA_V1
        ),
    }
)
_IMPLEMENTATION_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
_VERIFIER_SOURCE_RELPATHS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "lcr084_candidate": (
            "scripts/ops/legal_data/build_state_laws_hf_release.py"
        ),
        "mutation_audit": (
            "scripts/ops/legal_data/"
            "audit_legal_corpora_hugging_face_mutation_paths.py"
        ),
        "live_baseline": (
            "scripts/ops/legal_data/audit_legal_corpora_live_baseline.py"
        ),
        "state_local_e2e": (
            "scripts/ops/legal_data/build_state_laws_sparse_graphrag.py"
        ),
        "state_acceptance_v1": (
            "scripts/ops/legal_data/state_laws_acquisition_gap_refill.py"
        ),
        "federal_evaluation": (
            "scripts/ops/legal_data/"
            "evaluate_federal_register_sparse_graphrag.py"
        ),
        "federal_inventory": (
            "ipfs_datasets_py/processors/legal_data/"
            "federal_register_acquisition.py"
        ),
        "federal_fulltext": (
            "ipfs_datasets_py/processors/legal_data/"
            "federal_register_fulltext.py"
        ),
        "federal_candidate": (
            "ipfs_datasets_py/processors/legal_data/"
            "federal_register_hf_release.py"
        ),
        "federal_adjacency": (
            "ipfs_datasets_py/processors/legal_data/"
            "federal_register_adjacency_gate.py"
        ),
        "federal_staging_canary": (
            "scripts/ops/legal_data/canary_federal_register_hf_release.py"
        ),
        "federal_full_live_acceptance": (
            "scripts/ops/legal_data/"
            "run_federal_register_full_release_acceptance.py"
        ),
    }
)
_VERIFIER_IMPORT_SOURCE_SHA256: Final[Mapping[str, str]] = MappingProxyType(
    {
        label: hashlib.sha256(
            (_IMPLEMENTATION_REPOSITORY_ROOT / relpath).read_bytes()
        ).hexdigest()
        for label, relpath in _VERIFIER_SOURCE_RELPATHS.items()
    }
)
_LCR084_SOURCE_ARCHIVE_PATHS: Final = (
    ":(glob)ipfs_datasets_py/**/*.py",
    ":(glob)scripts/**/*.py",
    "data/legal/state_laws_full_scrape_acceptance.schema.json",
)
_LCR084_SOURCE_ARCHIVE_LIMIT_BYTES: Final = 256 * 1024 * 1024
_LCR084_SOURCE_ARCHIVE_MEMBER_LIMIT: Final = 10_000
_LCR084_CANDIDATE_LIMIT_BYTES: Final = 8 * 1024 * 1024
_LCR084_VERIFIER_OUTPUT_LIMIT_BYTES: Final = 64 * 1024
# The retained replay owns a 7,200-second timeout.  Its supervising verifier
# must have enough time to finish the remaining exact evidence bookends.
_LCR084_VERIFIER_TIMEOUT_SECONDS: Final = (2 * 60 * 60) + (15 * 60)
FEDERAL_DATASET_CARD_RELPATH: Final = (
    "docs/reports/legal_corpora_reindex/federal_dataset_card.md"
)

CANONICAL_PATHS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "release_policy": RELEASE_POLICY_RELPATH,
        "taskboard": TASKBOARD_RELPATH,
        "objectives": OBJECTIVES_RELPATH,
        "state_candidate_manifest": STATE_CANDIDATE_MANIFEST_RELPATH,
        "federal_candidate_manifest": FEDERAL_CANDIDATE_MANIFEST_RELPATH,
        "state_prepublication_seal": STATE_PREPUBLICATION_SEAL_RELPATH,
        "federal_prepublication_seal": FEDERAL_PREPUBLICATION_SEAL_RELPATH,
        "state_dataset_card": STATE_DATASET_CARD_RELPATH,
        "federal_dataset_card": FEDERAL_DATASET_CARD_RELPATH,
        "source_rights_receipt": RIGHTS_RECEIPT_RELPATH,
    }
)

AUTHORITATIVE_OVERRIDE_KEYS: Final = frozenset(
    {
        "branch",
        "claimed_commit",
        "claimed_head",
        "commit",
        "current_commit",
        "expected_receipt_digests",
        "final_manifest_digest",
        "git_ref",
        "goal_parents",
        "manifest_path",
        "objectives_path",
        "path_overrides",
        "paths",
        "prepublication_seal",
        "receipt_paths",
        "receipt_root",
        "receipts",
        "ref",
        "release_policy_path",
        "seal_path",
        "task_dependencies",
        "task_goal_ids",
        "task_statuses",
        "taskboard_path",
    }
)

SELF_DIGEST_FIELDS: Final = frozenset(
    {
        "canonical_digest",
        "content_digest",
        "digest",
        "final_manifest_digest",
        "manifest_digest",
        "no_self_field_digest",
        "raw_sha256",
        "receipt_sha256",
        "sha256",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_UTC_Z_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z$")
_TASK_HEADING_RE = re.compile(r"^## (LCR-(?:\d{3}|\d{4,})) (\S.+)$")
_GOAL_HEADING_RE = re.compile(r"^## (LCR-G(?:\d{3}|\d{4,})) (\S.+)$")
_FIELD_LINE_RE = re.compile(r"^- ([^:]+):(.*)$")
_OFFSET_TIME_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|[+-]\d{4}|Zulu)$"
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]
T = TypeVar("T")
PrincipalProbe = Callable[[str, str], Mapping[str, Any]]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PublicationRuntimeError(PublicationGateError):
    """Base error for canonical runtime failures."""

    code = "publication_runtime_error"


class CanonicalPathOverrideError(PublicationRuntimeError):
    """Raised when a caller tries to override a canonical evidence path."""

    code = "canonical_path_override"


class DirtyAuthoritativePathError(PublicationRuntimeError):
    """Raised when a canonical control or evidence path is dirty."""

    code = "dirty_authoritative_path"


class AlternateRepositoryError(PublicationRuntimeError):
    """Raised when the requested root or branch is not the actual HEAD."""

    code = "alternate_repository"


class CallerCommitError(PublicationRuntimeError):
    """Raised when a caller-selected commit is offered as authority."""

    code = "caller_selected_commit"


class ReceiptSchemaError(PublicationRuntimeError):
    """Raised when a receipt schema is missing or unknown."""

    code = "unknown_receipt_schema"


class ReceiptStatusError(PublicationRuntimeError):
    """Raised when a required receipt omits status."""

    code = "missing_receipt_status"


class IndependentDigestError(PublicationRuntimeError):
    """Raised when declared digests do not match recomputed bytes."""

    code = "independent_digest_mismatch"


class ManifestBindingError(PublicationRuntimeError):
    """Raised when the candidate manifest omits required bindings."""

    code = "missing_manifest_binding"


class CredentialTokenError(PublicationRuntimeError):
    """Raised when the allowlisted token is missing or wrong-scope."""

    code = "credential_token_error"


class PrincipalAuthorityError(PublicationRuntimeError):
    """Raised when the probed principal cannot write the exact target."""

    code = "principal_authority_error"


class SealTimeError(PublicationRuntimeError):
    """Raised when a main seal time is absent, offset, future, or post-mutation."""

    code = "seal_time_error"


class EvidenceRaceError(PublicationRuntimeError):
    """Raised when HEAD or evidence bytes change before the callback."""

    code = "evidence_race"


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublicationRuntimeError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise PublicationRuntimeError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise PublicationRuntimeError(f"{name} exceeds maximum length {maximum}")
    return text


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def raw_file_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_object_without_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise PublicationRuntimeError(
                f"canonical JSON contains duplicate key {key!r}"
            )
        payload[key] = value
    return payload


def _load_fresh_attested_verifier(label: str) -> tuple[Any, str]:
    """Load one verifier from import-attested repository source bytes."""

    relpath = _VERIFIER_SOURCE_RELPATHS.get(label)
    expected_sha256 = _VERIFIER_IMPORT_SOURCE_SHA256.get(label)
    if not relpath or not expected_sha256:
        raise PublicationRuntimeError(f"unknown canonical verifier {label!r}")
    source_path = _IMPLEMENTATION_REPOSITORY_ROOT / relpath
    if source_path.is_symlink() or not source_path.is_file():
        raise PublicationRuntimeError(
            f"canonical {label} verifier source is missing or symlinked"
        )
    source_bytes = source_path.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != expected_sha256:
        raise PublicationRuntimeError(
            f"canonical {label} verifier source changed after runtime import"
        )
    nonce = object()
    module_name = f"_lcr084_fresh_{label}_{id(nonce):x}"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if (
        spec is None
        or spec.loader is None
        or Path(str(spec.origin or "")).resolve() != source_path.resolve()
    ):
        raise PublicationRuntimeError(
            f"canonical {label} verifier cannot be loaded from exact source"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        code = compile(source_bytes, str(source_path), "exec")
        exec(code, vars(module), vars(module))
        if source_path.read_bytes() != source_bytes:
            raise PublicationRuntimeError(
                f"canonical {label} verifier source changed while loading"
            )
    except Exception:
        if sys.modules.get(module_name) is module:
            sys.modules.pop(module_name, None)
        raise
    return module, module_name


def _discard_fresh_attested_verifier(module: Any, module_name: str) -> None:
    if sys.modules.get(module_name) is module:
        sys.modules.pop(module_name, None)


def _process_identity_table() -> dict[int, tuple[int, int]]:
    """Return ``pid -> (ppid, starttime)`` from Linux procfs.

    Start times make descendant cleanup safe against PID reuse during the
    verifier's deliberately long retained-replay bound.
    """

    proc_root = Path("/proc")
    if not proc_root.is_dir():
        raise PublicationRuntimeError(
            "isolated verifier requires procfs descendant accounting"
        )
    table: dict[int, tuple[int, int]] = {}
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            serialized = (entry / "stat").read_text(encoding="ascii")
            close = serialized.rfind(")")
            fields = serialized[close + 2 :].split()
            pid = int(entry.name)
            table[pid] = (int(fields[1]), int(fields[19]))
        except (FileNotFoundError, IndexError, OSError, UnicodeError, ValueError):
            continue
    return table


def _isolated_descendant_identities(
    root_pid: int,
) -> dict[int, int]:
    table = _process_identity_table()
    descendants: dict[int, int] = {}
    frontier = {int(root_pid)}
    while frontier:
        children = {
            pid
            for pid, (ppid, _starttime) in table.items()
            if ppid in frontier and pid not in descendants
        }
        if not children:
            break
        for pid in children:
            descendants[pid] = table[pid][1]
        frontier = children
    return descendants


def _signal_process_identity(pid: int, starttime: int, sig: int) -> None:
    current = _process_identity_table().get(int(pid))
    if current is None or current[1] != int(starttime):
        return
    try:
        os.kill(int(pid), sig)
    except ProcessLookupError:
        pass


def _terminate_isolated_process_tree(
    process: subprocess.Popen[bytes],
    known_descendants: Mapping[int, int],
) -> None:
    """Stop and kill the verifier plus separately-sessioned descendants."""

    identities = dict(known_descendants)
    root_identity = _process_identity_table().get(process.pid)
    if root_identity is not None:
        _signal_process_identity(process.pid, root_identity[1], signal.SIGSTOP)
    # The retained worker creates its own session.  Freeze every observed
    # descendant before killing so a grandchild cannot escape by forking or
    # being reparented while the outer supervisor tears down.
    for _ in range(3):
        identities.update(_isolated_descendant_identities(process.pid))
        for pid, starttime in tuple(identities.items()):
            _signal_process_identity(pid, starttime, signal.SIGSTOP)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    for pid, starttime in tuple(identities.items()):
        _signal_process_identity(pid, starttime, signal.SIGKILL)
    if root_identity is not None:
        _signal_process_identity(process.pid, root_identity[1], signal.SIGKILL)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _run_bounded_isolated_process(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str] | None,
    timeout_seconds: float,
    output_limit_bytes: int,
) -> tuple[int, bytes, bytes]:
    """Run a process with live pipe bounds and descendant-safe cleanup."""

    if timeout_seconds <= 0 or output_limit_bytes <= 0:
        raise PublicationRuntimeError("isolated verifier bounds are invalid")
    try:
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            env=None if environment is None else dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            start_new_session=True,
        )
    except OSError as exc:
        raise PublicationRuntimeError(
            "isolated verifier process could not start"
        ) from exc
    if process.stdout is None or process.stderr is None:  # pragma: no cover
        _terminate_isolated_process_tree(process, {})
        raise PublicationRuntimeError("isolated verifier pipes are unavailable")
    selector = selectors.DefaultSelector()
    stdout = bytearray()
    stderr = bytearray()
    total = 0
    descendants: dict[int, int] = {}
    deadline = time.monotonic() + float(timeout_seconds)
    streams = ((process.stdout, stdout), (process.stderr, stderr))
    failed = False
    try:
        for stream, target in streams:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, target)
        while selector.get_map():
            descendants.update(_isolated_descendant_identities(process.pid))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failed = True
                raise PublicationRuntimeError("isolated verifier timed out")
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
                    failed = True
                    raise PublicationRuntimeError(
                        "isolated verifier output exceeded its live bound"
                    )
                key.data.extend(chunk)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            failed = True
            raise PublicationRuntimeError("isolated verifier timed out")
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            failed = True
            raise PublicationRuntimeError("isolated verifier timed out") from exc
        descendants.update(_isolated_descendant_identities(process.pid))
        survivors = {
            pid: starttime
            for pid, starttime in descendants.items()
            if _process_identity_table().get(pid, (0, -1))[1] == starttime
        }
        if survivors:
            failed = True
            raise PublicationRuntimeError(
                "isolated verifier left a descendant process running"
            )
        return returncode, bytes(stdout), bytes(stderr)
    finally:
        selector.close()
        for stream, _target in streams:
            if not stream.closed:
                stream.close()
        if failed or process.poll() is None:
            _terminate_isolated_process_tree(process, descendants)


def _write_private_snapshot_file(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    path.chmod(0o400)


def _materialize_lcr084_source_snapshot(
    root: Path,
    destination: Path,
    head: str,
    *,
    archive_paths: Sequence[str] = _LCR084_SOURCE_ARCHIVE_PATHS,
    expected_source_sha256: Mapping[str, str] = _VERIFIER_IMPORT_SOURCE_SHA256,
) -> tuple[Path, dict[Path, str], dict[str, str]]:
    """Materialize regular verifier sources from immutable HEAD Git objects."""

    if tuple(archive_paths) != (
        ":(glob)ipfs_datasets_py/**/*.py",
        ":(glob)scripts/**/*.py",
        "data/legal/state_laws_full_scrape_acceptance.schema.json",
    ):
        raise PublicationRuntimeError("LCR-084 source archive path set drifted")
    archive_path = destination / "lcr084-source.tar"
    source_root = destination / "source"
    source_root.mkdir(mode=0o700)
    git_executable, git_environment = _authority_git_invocation()
    returncode, _stdout, stderr = _run_bounded_isolated_process(
        [
            git_executable,
            "archive",
            "--format=tar",
            f"--output={archive_path}",
            head,
            "--",
            *archive_paths,
        ],
        cwd=root,
        environment=git_environment,
        timeout_seconds=180,
        output_limit_bytes=64 * 1024,
    )
    if returncode != 0:
        raise PublicationRuntimeError(
            "could not materialize immutable LCR-084 source archive: "
            + stderr.decode("utf-8", errors="replace")[-2048:]
        )
    archive_size = archive_path.stat().st_size
    if not (0 < archive_size <= 256 * 1024 * 1024):
        raise PublicationRuntimeError("LCR-084 source archive exceeds its bound")
    archive_digests = {archive_path: raw_file_digest(archive_path.read_bytes())}
    manifest: dict[str, str] = {}
    total = 0
    count = 0
    try:
        archive = tarfile.open(archive_path, mode="r:")
    except (OSError, tarfile.TarError) as exc:
        raise PublicationRuntimeError("invalid LCR-084 source archive") from exc
    with archive:
        for member in archive:
            relative = PurePosixPath(member.name)
            if (
                relative.is_absolute()
                or not relative.parts
                or any(part in ("", ".", "..") for part in relative.parts)
            ):
                raise PublicationRuntimeError(
                    "LCR-084 source archive contains an unsafe path"
                )
            target = source_root.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            if not member.isreg():
                raise PublicationRuntimeError(
                    "LCR-084 source archive contains a non-regular Git entry"
                )
            if not (
                relative.suffix == ".py"
                or relative.as_posix()
                == "data/legal/state_laws_full_scrape_acceptance.schema.json"
            ):
                raise PublicationRuntimeError(
                    "LCR-084 source archive contains an unexpected blob"
                )
            count += 1
            total += int(member.size)
            if count > 10_000 or total > 256 * 1024 * 1024:
                raise PublicationRuntimeError(
                    "LCR-084 source archive member bound exceeded"
                )
            if relative.as_posix() in manifest:
                raise PublicationRuntimeError(
                    "LCR-084 source archive contains a duplicate path"
                )
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            extracted = archive.extractfile(member)
            if extracted is None:
                raise PublicationRuntimeError(
                    "LCR-084 source archive blob cannot be read"
                )
            digest = hashlib.sha256()
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(target, flags, 0o600)
            try:
                with os.fdopen(descriptor, "wb", closefd=False) as stream:
                    while True:
                        chunk = extracted.read(64 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        stream.write(chunk)
            finally:
                os.close(descriptor)
                extracted.close()
            target.chmod(0o500 if member.mode & 0o111 else 0o400)
            manifest[relative.as_posix()] = digest.hexdigest()
    submodule_relpath = (
        "ipfs_datasets_py/processors/web_archiving/"
        "common_crawl_search_engine"
    )
    gitlink_line = _git(
        root,
        "ls-tree",
        head,
        "--",
        submodule_relpath,
    ).strip()
    match = re.fullmatch(
        rf"160000 commit ([0-9a-f]{{40}})\t{re.escape(submodule_relpath)}",
        gitlink_line,
    )
    if match is None:
        raise PublicationRuntimeError(
            "LCR-084 Common Crawl dependency is not an exact Git link"
        )
    gitlink_commit = match.group(1)
    submodule_root = root / submodule_relpath
    if submodule_root.is_symlink() or not submodule_root.is_dir():
        raise PublicationRuntimeError(
            "LCR-084 Common Crawl Git dependency is not initialized"
        )
    if _git(submodule_root, "cat-file", "-t", gitlink_commit).strip() != "commit":
        raise PublicationRuntimeError(
            "LCR-084 Common Crawl Git-link object is unavailable"
        )
    if _git(submodule_root, "rev-parse", "HEAD").strip().casefold() != gitlink_commit:
        raise PublicationRuntimeError(
            "LCR-084 Common Crawl checkout is not at the pinned Git link"
        )
    submodule_archive_path = destination / "common-crawl-source.tar"
    returncode, _stdout, stderr = _run_bounded_isolated_process(
        [
            git_executable,
            "archive",
            "--format=tar",
            f"--output={submodule_archive_path}",
            gitlink_commit,
            "--",
            ":(glob)**/*.py",
        ],
        cwd=submodule_root,
        environment=git_environment,
        timeout_seconds=60,
        output_limit_bytes=64 * 1024,
    )
    if returncode != 0:
        raise PublicationRuntimeError(
            "could not materialize pinned Common Crawl source: "
            + stderr.decode("utf-8", errors="replace")[-2048:]
        )
    submodule_size = submodule_archive_path.stat().st_size
    if not (0 < submodule_size <= 32 * 1024 * 1024):
        raise PublicationRuntimeError(
            "LCR-084 Common Crawl source archive exceeds its bound"
        )
    archive_digests[submodule_archive_path] = raw_file_digest(
        submodule_archive_path.read_bytes()
    )
    try:
        submodule_archive = tarfile.open(submodule_archive_path, mode="r:")
    except (OSError, tarfile.TarError) as exc:
        raise PublicationRuntimeError(
            "invalid pinned Common Crawl source archive"
        ) from exc
    with submodule_archive:
        for member in submodule_archive:
            relative = PurePosixPath(member.name)
            if (
                relative.is_absolute()
                or not relative.parts
                or any(part in ("", ".", "..") for part in relative.parts)
            ):
                raise PublicationRuntimeError(
                    "Common Crawl source archive contains an unsafe path"
                )
            prefixed = PurePosixPath(submodule_relpath) / relative
            target = source_root.joinpath(*prefixed.parts)
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            if not member.isreg() or relative.suffix != ".py":
                raise PublicationRuntimeError(
                    "Common Crawl source archive contains a non-Python Git blob"
                )
            count += 1
            total += int(member.size)
            if count > 10_000 or total > 256 * 1024 * 1024:
                raise PublicationRuntimeError(
                    "LCR-084 source archive member bound exceeded"
                )
            key = prefixed.as_posix()
            if key in manifest:
                raise PublicationRuntimeError(
                    "Common Crawl source archive overlaps a source path"
                )
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            extracted = submodule_archive.extractfile(member)
            if extracted is None:
                raise PublicationRuntimeError(
                    "Common Crawl source archive blob cannot be read"
                )
            digest = hashlib.sha256()
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(target, flags, 0o600)
            try:
                with os.fdopen(descriptor, "wb", closefd=False) as stream:
                    while True:
                        chunk = extracted.read(64 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        stream.write(chunk)
            finally:
                os.close(descriptor)
                extracted.close()
            target.chmod(0o500 if member.mode & 0o111 else 0o400)
            manifest[key] = digest.hexdigest()
    if _git(submodule_root, "rev-parse", "HEAD").strip().casefold() != gitlink_commit:
        raise PublicationRuntimeError(
            "LCR-084 Common Crawl Git link changed while archiving"
        )
    for label, relpath in _VERIFIER_SOURCE_RELPATHS.items():
        expected = expected_source_sha256.get(label)
        if not expected or manifest.get(relpath) != expected:
            raise PublicationRuntimeError(
                f"Git-HEAD source for {label} differs from runtime import"
            )
    for directory in sorted(
        (path for path in source_root.rglob("*") if path.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        directory.chmod(0o500)
    source_root.chmod(0o500)
    for frozen_archive in archive_digests:
        frozen_archive.chmod(0o400)
    return source_root, archive_digests, manifest


def _require_trusted_lcr084_snapshot_boundary(source_root: Path) -> None:
    """Require a source tree that the verifier's own uid cannot mutate."""

    prefix = "trusted LCR-084 source snapshot unavailable"

    def refuse(detail: str) -> None:
        raise PublicationRuntimeError(f"{prefix}: {detail}")

    def reject_authority_xattrs(path: Path) -> None:
        forbidden = (
            "security.capability",
            "system.posix_acl_access",
            "system.posix_acl_default",
        )
        present = set(os.listxattr(path, follow_symlinks=False))
        hidden_authority = sorted(present.intersection(forbidden))
        if hidden_authority:
            refuse(
                f"path carries ACL/capability authority {hidden_authority}: {path}"
            )

    selected = Path(source_root)
    if not selected.is_absolute() or selected != Path(
        os.path.abspath(os.fspath(selected))
    ):
        refuse("source root is not a lexical absolute path")
    verifier_uid = os.geteuid()
    if verifier_uid == 0:
        refuse("verifier uid must be distinct from the trusted root owner")
    try:
        boundaries = (selected, *selected.parents)
        for boundary in boundaries:
            metadata = os.lstat(boundary)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(
                metadata.st_mode
            ):
                refuse(f"boundary component is not a nofollow directory: {boundary}")
            if metadata.st_uid != 0 or metadata.st_uid == verifier_uid:
                refuse(f"boundary component lacks a distinct root owner: {boundary}")
            if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                refuse(f"boundary component is group/world writable: {boundary}")
            reject_authority_xattrs(boundary)

        pending = [selected]
        seen = 0
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    seen += 1
                    if seen > 10_000:
                        refuse("source tree exceeds its trusted-entry bound")
                    metadata = entry.stat(follow_symlinks=False)
                    path = Path(entry.path)
                    if stat.S_ISLNK(metadata.st_mode):
                        refuse(f"source entry is symlinked: {path}")
                    if metadata.st_uid != 0 or metadata.st_uid == verifier_uid:
                        refuse(f"source entry lacks a distinct root owner: {path}")
                    if metadata.st_mode & (
                        stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
                    ):
                        refuse(f"source entry is writable: {path}")
                    if stat.S_ISDIR(metadata.st_mode):
                        pending.append(path)
                    elif not stat.S_ISREG(metadata.st_mode):
                        refuse(f"source entry is not regular: {path}")
                    elif metadata.st_nlink != 1:
                        refuse(f"source file is multiply linked: {path}")
                    reject_authority_xattrs(path)
    except PublicationRuntimeError:
        raise
    except OSError as exc:
        raise PublicationRuntimeError(f"{prefix}: source boundary changed") from exc


def _isolated_lcr084_candidate_remeasurement(
    root: Path,
    *,
    phase: str,
    payload: Mapping[str, Any],
    runtime_token: str,
) -> dict[str, Any]:
    """Remeasure frozen @2 bytes using a detached Git-object source tree."""

    canonical_root = _require_mutation_implementation_root(root)
    if type(runtime_token) is not str or not runtime_token:
        raise PublicationRuntimeError(
            "isolated LCR-084 verification requires the exact runtime token"
        )
    if phase not in ("state_staging", "state_main"):
        raise PublicationRuntimeError("invalid LCR-084 publication phase")
    head_before = inspect_clean_head(canonical_root)
    git_executable, git_environment = _authority_git_invocation()
    returncode, committed_candidate_raw, git_stderr = (
        _run_bounded_isolated_process(
            [
                git_executable,
                "show",
                f"{head_before}:{STATE_CANDIDATE_MANIFEST_RELPATH}",
            ],
            cwd=canonical_root,
            environment=git_environment,
            timeout_seconds=60,
            output_limit_bytes=(8 * 1024 * 1024) + (64 * 1024),
        )
    )
    if returncode != 0:
        raise PublicationRuntimeError(
            "cannot freeze the committed LCR-084 candidate Git blob: "
            + git_stderr.decode("utf-8", errors="replace")[-2048:]
        )
    candidate_raw = read_canonical_bytes(
        canonical_root,
        STATE_CANDIDATE_MANIFEST_RELPATH,
    )
    if candidate_raw != committed_candidate_raw:
        raise PublicationRuntimeError(
            "on-disk LCR-084 candidate differs from its immutable HEAD blob"
        )
    if len(candidate_raw) > 8 * 1024 * 1024:
        raise PublicationRuntimeError("LCR-084 candidate exceeds its byte bound")
    try:
        candidate_payload = json.loads(
            candidate_raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PublicationRuntimeError("LCR-084 candidate is not strict JSON") from exc
    if type(candidate_payload) is not dict or candidate_payload != payload:
        raise PublicationRuntimeError(
            "LCR-084 candidate payload differs from exact on-disk bytes"
        )
    candidate_raw_sha256 = raw_file_digest(candidate_raw)
    candidate_report_digest = _production_candidate_report_digest(
        candidate_payload
    )
    if candidate_payload.get("report_digest_sha256") != candidate_report_digest:
        raise PublicationRuntimeError("LCR-084 candidate self-digest is invalid")
    source = (
        "import hashlib,importlib.util,json,os,pathlib,stat,subprocess,sys\n"
        "source_root=pathlib.Path(sys.argv[1]).resolve()\n"
        "evidence_root=pathlib.Path(sys.argv[2]).resolve()\n"
        "frozen_path=pathlib.Path(sys.argv[3]).resolve()\n"
        "manifest_path=pathlib.Path(sys.argv[4]).resolve()\n"
        "expected_raw_sha=sys.argv[5]\n"
        "expected_report_digest=sys.argv[6]\n"
        "expected_head=sys.argv[7]\n"
        "phase=sys.argv[8]\n"
        "git_executable=sys.argv[9]\n"
        "if source_root==evidence_root: raise RuntimeError('source/evidence roots overlap')\n"
        "def strict_pairs(pairs):\n"
        " out={}\n"
        " for key,value in pairs:\n"
        "  if key in out: raise RuntimeError('duplicate JSON key')\n"
        "  out[key]=value\n"
        " return out\n"
        "manifest=json.loads(manifest_path.read_text(encoding='utf-8'),object_pairs_hook=strict_pairs)\n"
        "def source_projection():\n"
        " measured={}\n"
        " for path in source_root.rglob('*'):\n"
        "  if path.is_symlink(): raise RuntimeError('symlink in source snapshot')\n"
        "  if path.is_file():\n"
        "   rel=path.relative_to(source_root).as_posix()\n"
        "   mode=os.lstat(path).st_mode\n"
        "   if not stat.S_ISREG(mode): raise RuntimeError('non-regular source')\n"
        "   measured[rel]=hashlib.sha256(path.read_bytes()).hexdigest()\n"
        " if measured!=manifest: raise RuntimeError('source snapshot drift')\n"
        " return measured\n"
        "def git_head():\n"
        " git_env={'GIT_CONFIG_GLOBAL':'/dev/null','GIT_CONFIG_NOSYSTEM':'1','GIT_OPTIONAL_LOCKS':'0','GIT_TERMINAL_PROMPT':'0','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','PATH':'/usr/bin:/bin','TZ':'UTC'}\n"
        " result=subprocess.run([git_executable,'rev-parse','HEAD'],cwd=evidence_root,env=git_env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False,timeout=30)\n"
        " if result.returncode!=0: raise RuntimeError('cannot read evidence HEAD')\n"
        " return result.stdout.decode('ascii',errors='strict').strip().lower()\n"
        "def evidence_modules_absent():\n"
        " for loaded in tuple(sys.modules.values()):\n"
        "  filename=getattr(loaded,'__file__',None)\n"
        "  if not filename: continue\n"
        "  try: pathlib.Path(filename).resolve().relative_to(evidence_root)\n"
        "  except ValueError: continue\n"
        "  raise RuntimeError('module loaded from evidence checkout')\n"
        "source_projection()\n"
        "if git_head()!=expected_head: raise RuntimeError('evidence HEAD drift')\n"
        "frozen=frozen_path.read_bytes()\n"
        "if hashlib.sha256(frozen).hexdigest()!=expected_raw_sha: raise RuntimeError('frozen candidate drift')\n"
        "candidate_path=evidence_root/'docs/reports/legal_corpora_reindex/release_candidate.json'\n"
        "if candidate_path.read_bytes()!=frozen: raise RuntimeError('candidate byte mismatch')\n"
        "source=source_root/'scripts/ops/legal_data/build_state_laws_hf_release.py'\n"
        "source_bytes=source.read_bytes()\n"
        "sys.path.insert(0,str(source_root))\n"
        "spec=importlib.util.spec_from_file_location("
        "'_lcr084_isolated_builder',source)\n"
        "module=importlib.util.module_from_spec(spec)\n"
        "sys.modules[spec.name]=module\n"
        "exec(compile(source_bytes,str(source),'exec'),vars(module),vars(module))\n"
        "evidence_modules_absent()\n"
        "payload=module.load_json_mapping_bytes(frozen,label='frozen canonical LCR-084 candidate')\n"
        "if module._digest_for_report(payload)!=expected_report_digest: raise RuntimeError('candidate report digest drift')\n"
        "module.check_production_candidate_publication_binding(payload,phase=phase)\n"
        "result=module.check_production_candidate_report("
        "payload,repo_root=evidence_root,remeasure_production_evidence=True)\n"
        "if source.read_bytes()!=source_bytes: raise RuntimeError('builder source drift')\n"
        "source_projection()\n"
        "evidence_modules_absent()\n"
        "if git_head()!=expected_head: raise RuntimeError('evidence HEAD drift')\n"
        "if frozen_path.read_bytes()!=frozen: raise RuntimeError('frozen candidate drift')\n"
        "if candidate_path.read_bytes()!=frozen: raise RuntimeError('candidate byte mismatch')\n"
        "sys.stdout.write(json.dumps(result,sort_keys=True,separators=(',',':')))\n"
    )
    environment = {
        **dict(_AUTHORITY_GIT_ENVIRONMENT),
        "HF_TOKEN": runtime_token,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
    }
    with tempfile.TemporaryDirectory(prefix="lcr084-verifier-") as temporary:
        temporary_root = Path(temporary)
        temporary_root.chmod(0o700)
        source_root, archive_digests, manifest = (
            _materialize_lcr084_source_snapshot(
                canonical_root,
                temporary_root,
                head_before,
            )
        )
        frozen_path = temporary_root / "candidate.json"
        manifest_path = temporary_root / "source-manifest.json"
        _write_private_snapshot_file(frozen_path, candidate_raw)
        _write_private_snapshot_file(
            manifest_path,
            canonical_json_bytes(manifest),
        )
        _require_trusted_lcr084_snapshot_boundary(source_root)
        returncode, stdout, stderr = _run_bounded_isolated_process(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                source,
                str(source_root),
                str(canonical_root),
                str(frozen_path),
                str(manifest_path),
                candidate_raw_sha256,
                candidate_report_digest,
                head_before,
                phase,
                git_executable,
            ],
            cwd=source_root,
            environment=environment,
            timeout_seconds=(2 * 60 * 60) + (15 * 60),
            output_limit_bytes=64 * 1024,
        )
        for archive_path, archive_digest in archive_digests.items():
            if raw_file_digest(archive_path.read_bytes()) != archive_digest:
                raise PublicationRuntimeError(
                    "immutable LCR-084 source archive changed during verification"
                )
        if frozen_path.read_bytes() != candidate_raw:
            raise PublicationRuntimeError(
                "frozen LCR-084 candidate changed during verification"
            )
    if inspect_clean_head(canonical_root) != head_before:
        raise PublicationRuntimeError("LCR-084 evidence HEAD changed")
    if read_canonical_bytes(
        canonical_root,
        STATE_CANDIDATE_MANIFEST_RELPATH,
    ) != candidate_raw:
        raise PublicationRuntimeError(
            "LCR-084 candidate bytes changed during verification"
        )
    if returncode != 0:
        diagnostic = stderr.decode(
            "utf-8", errors="replace"
        )[-2048:].replace(runtime_token, "<redacted>")
        raise PublicationRuntimeError(
            "isolated LCR-084 verifier denied the candidate: " + diagnostic
        )
    try:
        result = json.loads(
            stdout.decode("utf-8", errors="strict"),
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PublicationRuntimeError(
            "isolated LCR-084 verifier returned invalid JSON"
        ) from exc
    if type(result) is not dict:
        raise PublicationRuntimeError(
            "isolated LCR-084 verifier returned a non-object result"
        )
    return result


def canonical_no_self_field_digest(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise IndependentDigestError("canonical digest requires a JSON object")
    body = {key: value for key, value in payload.items() if key not in SELF_DIGEST_FIELDS}
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def _production_candidate_report_digest(payload: Mapping[str, Any]) -> str:
    """Recompute the self digest used by the LCR-084 candidate builder."""

    body = {
        key: value
        for key, value in payload.items()
        if key != "report_digest_sha256"
    }
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _federal_candidate_report_digest(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "content_digest"}
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def _candidate_release_manifest_digest(payload: Mapping[str, Any]) -> str:
    """Return the artifact-manifest digest bound by a candidate receipt.

    ``final_manifest_digest`` is the no-self-field digest of the candidate
    control receipt itself.  The State candidate binds the release artifact
    manifest at top level, while the Federal candidate nests that binding.
    Keep both identities so a mutation callback cannot confuse those layers.
    """

    candidate = payload.get("candidate")
    nested = candidate if isinstance(candidate, Mapping) else {}
    value = payload.get("manifest_digest") or nested.get("manifest_digest")
    if value in (None, ""):
        return ""
    return normalize_sha256(value, name="candidate.manifest_digest")


def _posix_relpath(path: str) -> str:
    text = _require_non_empty_str(path, "path", maximum=1024).replace("\\", "/")
    if text.startswith("/") or text.startswith("../") or "/../" in f"/{text}/":
        raise CanonicalPathOverrideError(f"unsafe canonical path {path!r}")
    if Path(text).is_absolute():
        raise CanonicalPathOverrideError(f"absolute path is not canonical: {path!r}")
    return text


def candidate_manifest_relpath(phase: PublicationPhase | str) -> str:
    key = PublicationPhase.coerce(phase).value
    if key.startswith("federal_"):
        return FEDERAL_CANDIDATE_MANIFEST_RELPATH
    return STATE_CANDIDATE_MANIFEST_RELPATH


def dataset_card_relpath(phase: PublicationPhase | str) -> str:
    key = PublicationPhase.coerce(phase).value
    if key.startswith("federal_"):
        return FEDERAL_DATASET_CARD_RELPATH
    return STATE_DATASET_CARD_RELPATH


def main_seal_relpath(phase: PublicationPhase | str) -> Optional[str]:
    contract = phase_requirements(phase)
    path = contract.get("seal_receipt_path")
    return str(path) if path else None


def authoritative_relpaths(phase: PublicationPhase | str) -> tuple[str, ...]:
    contract = phase_requirements(phase)
    paths = [
        RELEASE_POLICY_RELPATH,
        TASKBOARD_RELPATH,
        OBJECTIVES_RELPATH,
        candidate_manifest_relpath(phase),
        dataset_card_relpath(phase),
        *list(contract["required_receipts"]),
    ]
    seal_path = main_seal_relpath(phase)
    if seal_path:
        paths.append(seal_path)
    return tuple(dict.fromkeys(_posix_relpath(item) for item in paths))


def _field_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")


def _csv_ids(value: Any) -> tuple[str, ...]:
    text = str(value or "").strip()
    if not text:
        return ()
    return tuple(item for item in re.split(r"[,\s]+", text) if item)


def _secret_values(environ: Mapping[str, str]) -> tuple[str, ...]:
    values: list[str] = []
    for name in TOKEN_ENV_ALLOWLIST:
        item = environ.get(name)
        if isinstance(item, str) and item:
            values.append(item)
    return tuple(values)


def _contains_secret(text: str, secrets: Sequence[str]) -> bool:
    if not text or not secrets:
        return False
    return any(secret and secret in text for secret in secrets)


def _safe_error_text(exc: BaseException, secrets: Sequence[str]) -> str:
    text = str(exc)
    if _contains_secret(text, secrets):
        return type(exc).__name__
    return text


def _assert_secret_free(payload: Any, *, label: str, environ: Mapping[str, str]) -> None:
    reject_credentials_in_payload(payload, label=label, environ=environ)
    dumped = json.dumps(payload, default=str) if not isinstance(payload, str) else payload
    if _contains_secret(dumped, _secret_values(environ)):
        raise CredentialTokenError(f"{label} must not contain credential material")


# ---------------------------------------------------------------------------
# Git / filesystem
# ---------------------------------------------------------------------------


def _authority_git_invocation(
    *,
    executable: Path = _TRUSTED_GIT_EXECUTABLE,
    executable_sha256: str = _TRUSTED_GIT_SHA256,
    environment: Mapping[str, str] = _AUTHORITY_GIT_ENVIRONMENT,
) -> tuple[str, dict[str, str]]:
    """Return the pinned Git binary and a Git-variable-free environment."""

    expected_environment = {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "TZ": "UTC",
    }
    if dict(environment) != expected_environment:
        raise PublicationRuntimeError("authority-side Git environment drifted")
    try:
        resolved = executable.resolve(strict=True)
        metadata = resolved.stat(follow_symlinks=False)
    except OSError as exc:
        raise PublicationRuntimeError(
            "trusted system Git executable is unavailable"
        ) from exc
    if (
        resolved != executable
        or resolved.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not metadata.st_mode & stat.S_IXUSR
        or hashlib.sha256(resolved.read_bytes()).hexdigest()
        != executable_sha256
    ):
        raise PublicationRuntimeError(
            "trusted system Git executable identity drifted"
        )
    return str(resolved), dict(expected_environment)


def _git(repo: Path, *args: str) -> str:
    git_executable, git_environment = _authority_git_invocation()
    proc = subprocess.run(
        [git_executable, *args],
        cwd=str(repo),
        env=git_environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        safe = detail[0] if detail else f"exit {proc.returncode}"
        raise PublicationRuntimeError(f"git {' '.join(args)} failed: {safe[:200]}")
    return proc.stdout


def resolve_repository_root(repository_root: PathLike) -> Path:
    requested = Path(repository_root).expanduser().resolve()
    if not requested.is_dir():
        raise AlternateRepositoryError(
            f"repository root does not exist: {requested.as_posix()}"
        )
    try:
        toplevel = Path(_git(requested, "rev-parse", "--show-toplevel").strip()).resolve()
    except PublicationRuntimeError as exc:
        raise AlternateRepositoryError("repository root is not a git checkout") from exc
    if toplevel != requested:
        raise AlternateRepositoryError(
            "requested root is not the git toplevel; alternate roots cannot authorize"
        )
    return toplevel


def _require_mutation_implementation_root(repository_root: PathLike) -> Path:
    """Refuse protected authority for any alternate Git checkout."""

    root = resolve_repository_root(repository_root)
    implementation_root = _IMPLEMENTATION_REPOSITORY_ROOT.resolve()
    if root != implementation_root:
        raise AlternateRepositoryError(
            "protected mutation requires the exact runtime/publisher "
            "implementation checkout"
        )
    runtime_source = Path(__file__)
    if (
        runtime_source.is_symlink()
        or runtime_source.resolve()
        != (
            implementation_root
            / "ipfs_datasets_py/processors/legal_data/"
            "legal_corpora_publication_runtime.py"
        ).resolve()
    ):
        raise AlternateRepositoryError(
            "runtime source does not belong to the canonical implementation "
            "checkout"
        )
    return root


def inspect_clean_head(
    repository_root: PathLike,
    *,
    authoritative_paths: Sequence[str] = (),
) -> str:
    """Return the actual 40-hex HEAD after refusing dirty canonical paths."""

    root = resolve_repository_root(repository_root)
    head = _git(root, "rev-parse", "HEAD").strip().casefold()
    if not _GIT_SHA_RE.fullmatch(head):
        raise AlternateRepositoryError("HEAD is not a 40-character lowercase hex commit")
    porcelain = _git(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "-z",
    )
    dirty: list[str] = []
    if porcelain:
        entries = [item for item in porcelain.split("\0") if item]
        # porcelain -z entries are ``XY PATH`` or rename ``XY PATH\\0PATH2``;
        # ``-z`` already split on NUL so each leftover is one status record.
        for entry in entries:
            path = entry[3:] if len(entry) >= 3 else entry
            if " -> " in path:
                path = path.rsplit(" -> ", 1)[1]
            path = path.strip().replace("\\", "/")
            if path:
                dirty.append(path)
    wanted = {_posix_relpath(item) for item in authoritative_paths} if authoritative_paths else set()
    if wanted:
        hits = [
            path
            for path in dirty
            if path in wanted or any(path == item or path.startswith(f"{item}/") for item in wanted)
        ]
        if hits:
            raise DirtyAuthoritativePathError(
                "authoritative paths are dirty: " + ", ".join(sorted(hits)[:12])
            )
    elif dirty:
        raise DirtyAuthoritativePathError(
            "worktree is dirty at HEAD; clean checkout required"
        )
    return require_immutable_revision(head, name="HEAD")


def _resolve_canonical_file(root: Path, relpath: str) -> Path:
    relative = _posix_relpath(relpath)
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise CanonicalPathOverrideError(
            f"canonical path escapes repository: {relative}"
        ) from exc
    if path.is_symlink() or (root / relative).is_symlink():
        raise DirtyAuthoritativePathError(
            f"canonical path must not be a symlink: {relative}"
        )
    return path


def read_canonical_bytes(root: Path, relpath: str) -> bytes:
    path = _resolve_canonical_file(root, relpath)
    if not path.is_file():
        raise PublicationRuntimeError(f"canonical file is missing: {relpath}")
    return path.read_bytes()


def read_canonical_text(root: Path, relpath: str) -> str:
    try:
        return read_canonical_bytes(root, relpath).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PublicationRuntimeError(f"canonical file is not UTF-8: {relpath}") from exc


def read_canonical_json(root: Path, relpath: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            read_canonical_text(root, relpath),
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except PublicationRuntimeError:
        raise
    except json.JSONDecodeError as exc:
        raise PublicationRuntimeError(f"canonical JSON is invalid: {relpath}") from exc
    if not isinstance(payload, dict):
        raise PublicationRuntimeError(f"canonical JSON must be an object: {relpath}")
    return payload


# ---------------------------------------------------------------------------
# Taskboard / objectives
# ---------------------------------------------------------------------------


def _parse_namespaced_records(
    text: str,
    heading_pattern: re.Pattern[str],
    *,
    heading_prefix: str,
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        if line.startswith(heading_prefix):
            match = heading_pattern.fullmatch(line)
            if not match:
                current = None
                continue
            current = {"id": match.group(1), "title": match.group(2).strip()}
            records[match.group(1)] = current
            continue
        if line.startswith("## "):
            current = None
            continue
        if current is None or not line.startswith("- "):
            continue
        field = _FIELD_LINE_RE.fullmatch(line)
        if not field:
            continue
        key = _field_key(field.group(1))
        if key and key not in current:
            current[key] = field.group(2).strip()
    return records


def load_task_lineage(root: Path) -> dict[str, Any]:
    tasks = _parse_namespaced_records(
        read_canonical_text(root, TASKBOARD_RELPATH),
        _TASK_HEADING_RE,
        heading_prefix="## LCR-",
    )
    goals = _parse_namespaced_records(
        read_canonical_text(root, OBJECTIVES_RELPATH),
        _GOAL_HEADING_RE,
        heading_prefix="## LCR-G",
    )
    if not tasks:
        raise PublicationRuntimeError("taskboard contains no LCR task records")
    task_statuses = {
        task_id: str(record.get("status") or "").strip().lower()
        for task_id, record in tasks.items()
    }
    task_dependencies = {
        task_id: _csv_ids(record.get("depends_on"))
        for task_id, record in tasks.items()
    }
    task_goal_ids = {
        task_id: str(record.get("goal_id") or "").strip()
        for task_id, record in tasks.items()
        if str(record.get("goal_id") or "").strip()
    }
    goal_parents = {
        goal_id: _csv_ids(record.get("parent")) for goal_id, record in goals.items()
    }
    return {
        "task_statuses": task_statuses,
        "task_dependencies": task_dependencies,
        "task_goal_ids": task_goal_ids,
        "goal_parents": goal_parents,
        "tasks": tasks,
        "goals": goals,
    }


def load_release_policy(root: Path) -> dict[str, Any]:
    policy = read_canonical_json(root, RELEASE_POLICY_RELPATH)
    schema = str(policy.get("schema") or "").strip()
    if schema != "ipfs_datasets_py/legal-corpora-reindex-release-policy@1":
        raise ReceiptSchemaError("release policy schema is unknown")
    return policy


def _same_contract_value(left: Any, right: Any) -> bool:
    if isinstance(left, (list, tuple)) or isinstance(right, (list, tuple)):
        return [str(item) for item in list(left or ())] == [
            str(item) for item in list(right or ())
        ]
    return left == right


def _require_policy_phase_contract(policy: Mapping[str, Any], phase: str) -> None:
    contract = phase_requirements(phase)
    evidence = policy.get("prepublication_evidence_contract")
    if not isinstance(evidence, Mapping):
        raise PublicationRuntimeError("release policy missing prepublication_evidence_contract")
    phases = evidence.get("phase_requirements")
    if not isinstance(phases, Mapping) or phase not in phases:
        raise PublicationRuntimeError(f"release policy missing phase {phase}")
    observed = phases[phase]
    if not isinstance(observed, Mapping):
        raise PublicationRuntimeError(f"release policy phase {phase} is not an object")
    for key in (
        "dataset_repo_id",
        "authorized_operation",
        "required_task_ids",
        "required_receipts",
        "prepublication_seal_required",
    ):
        if not _same_contract_value(observed.get(key), contract.get(key)):
            raise PublicationRuntimeError(
                f"release policy {phase}.{key} drifts from the sealed gate contract"
            )
    baselines = policy.get("baseline_revisions")
    if not isinstance(baselines, Mapping):
        raise PublicationRuntimeError("release policy missing baseline_revisions")
    expected_pin = contract["previous_public_pin"]
    observed_pin = baselines.get(contract["dataset_repo_id"])
    if observed_pin != expected_pin:
        raise PublicationRuntimeError(
            "release policy baseline pin drifts from the sealed gate contract"
        )


# ---------------------------------------------------------------------------
# Receipts / manifests / seals
# ---------------------------------------------------------------------------


def _declared_digest(payload: Mapping[str, Any], *names: str) -> Optional[str]:
    for name in names:
        value = payload.get(name)
        if value is None or value == "":
            continue
        text = str(value).strip().casefold()
        if text.startswith("sha256:"):
            text = text[len("sha256:") :]
        if not _SHA256_RE.fullmatch(text):
            raise IndependentDigestError(f"{name} is not a 64-character hex digest")
        return text
    return None


def verify_independent_digests(
    *,
    relpath: str,
    raw: bytes,
    payload: Mapping[str, Any],
) -> dict[str, str]:
    raw_digest = raw_file_digest(raw)
    canonical_digest = canonical_no_self_field_digest(payload)
    declared_canonical = _declared_digest(
        payload, "canonical_digest", "content_digest", "receipt_sha256", "digest"
    )
    if declared_canonical is None:
        raise IndependentDigestError(
            f"{relpath} is missing an independently verifiable digest"
        )
    if declared_canonical != canonical_digest:
        raise IndependentDigestError(
            f"{relpath} declared digest does not match canonical no-self-field recompute"
        )
    declared_raw = _declared_digest(payload, "raw_sha256")
    if declared_raw is not None and declared_raw != raw_digest:
        raise IndependentDigestError(
            f"{relpath} declared raw digest does not match file bytes"
        )
    return {
        "raw_sha256": raw_digest,
        "canonical_digest": canonical_digest,
        "content_digest": canonical_digest,
    }


def _require_receipt_schema(payload: Mapping[str, Any], relpath: str) -> str:
    schema = str(payload.get("schema") or "").strip()
    if not schema:
        raise ReceiptSchemaError(f"{relpath} is missing a receipt schema")
    if schema not in ALLOWED_RECEIPT_SCHEMAS:
        raise ReceiptSchemaError(f"{relpath} has unknown receipt schema {schema!r}")
    return schema


def _require_receipt_status(payload: Mapping[str, Any], relpath: str) -> str:
    if "status" not in payload:
        raise ReceiptStatusError(f"{relpath} is missing status")
    status = str(payload.get("status") or "").strip().lower()
    if not status:
        raise ReceiptStatusError(f"{relpath} is missing status")
    return status


def _validated_native_phase_receipt(
    *,
    root: Path,
    relpath: str,
    payload: Mapping[str, Any],
    raw: bytes,
) -> tuple[str, dict[str, str], dict[str, Any]] | None:
    """Adapt producer-native reports only after their strict semantics pass."""

    expected_schema = _NATIVE_PHASE_RECEIPT_SCHEMAS.get(relpath)
    if expected_schema is None or payload.get("schema") != expected_schema:
        return None
    verifier: Any = None
    module_name = ""
    try:
        if relpath.endswith("live_baseline_provenance_receipt.json"):
            verifier, module_name = _load_fresh_attested_verifier(
                "live_baseline"
            )
            result = verifier.validate_receipt(
                payload,
                require_live_hub=True,
                require_local_salvage_inventory=True,
                require_fresh_observation=False,
            )
            if result.get("ok") is not True:
                raise PublicationRuntimeError("live baseline validation failed")
            content_digest = str(payload.get("receipt_sha256") or "")
        elif relpath.endswith("local_e2e.json"):
            verifier, module_name = _load_fresh_attested_verifier(
                "state_local_e2e"
            )
            result = verifier.check_full_build_report(payload)
            if result.get("ok") is not True:
                raise PublicationRuntimeError("State local-e2e validation failed")
            content_digest = str(payload.get("report_digest_sha256") or "")
        elif relpath.endswith("full_scrape_acceptance.json"):
            raise PublicationRuntimeError(
                "legacy State full-scrape acceptance is non-authorizing; "
                "LCR-084 @2 acceptance is required"
            )
        elif relpath == STATE_CANDIDATE_MANIFEST_RELPATH:
            verifier, module_name = _load_fresh_attested_verifier(
                "lcr084_candidate"
            )
            result = verifier.check_candidate_report(payload)
            if result.get("valid") is not True:
                raise PublicationRuntimeError("State candidate validation failed")
            content_digest = str(payload.get("report_digest_sha256") or "")
        elif relpath.endswith("federal_inventory.json"):
            verifier, module_name = _load_fresh_attested_verifier(
                "federal_inventory"
            )
            result = verifier._check_inventory_report_structure(
                verifier._snapshot_inventory_report(payload),
                require_live=False,
            )
            if result.get("structure_valid") is not True:
                raise PublicationRuntimeError("Federal inventory validation failed")
            content_digest = str(result.get("inventory_digest") or "")
        elif relpath.endswith("federal_fulltext_coverage.json"):
            verifier, module_name = _load_fresh_attested_verifier(
                "federal_fulltext"
            )
            result = verifier.check_coverage_report(
                payload,
                require_live=False,
            )
            if result.get("ok") is not True:
                raise PublicationRuntimeError("Federal full-text validation failed")
            content_digest = str(result.get("coverage_digest") or "")
        elif relpath == FEDERAL_CANDIDATE_MANIFEST_RELPATH:
            verifier, module_name = _load_fresh_attested_verifier(
                "federal_candidate"
            )
            body = {key: value for key, value in payload.items() if key != "content_digest"}
            computed = verifier.digest_mapping(body)
            if (
                payload.get("content_digest") != computed
                or payload.get("authorizing_for_publication") is not False
                or payload.get("authorizing_hub_upload") is not False
                or payload.get("hub_upload") is not False
            ):
                raise PublicationRuntimeError("Federal candidate validation failed")
            content_digest = computed
        elif relpath.endswith("federal_evaluation.json"):
            verifier, module_name = _load_fresh_attested_verifier(
                "federal_evaluation"
            )
            result = verifier.check_evaluation_report(payload)
            if result.get("ok") is not True:
                raise PublicationRuntimeError("Federal evaluation validation failed")
            content_digest = hashlib.sha256(
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
        elif relpath.endswith("federal_full_live_acceptance.json"):
            verifier, module_name = _load_fresh_attested_verifier(
                "federal_full_live_acceptance"
            )
            result = verifier.check_full_live_acceptance_report(
                payload,
                repository_root=root,
            )
            if result.get("ok") is not True:
                raise PublicationRuntimeError(
                    "Federal full-live acceptance validation failed"
                )
            content_digest = str(result.get("report_digest_sha256") or "")
        elif relpath.endswith("federal_adjacency_reconciliation.json"):
            verifier, module_name = _load_fresh_attested_verifier(
                "federal_adjacency"
            )
            verifier.assert_federal_adjacency_reconciliation(payload)
            content_digest = str(payload.get("report_digest_sha256") or "")
        elif relpath.endswith("federal_staging_canary.json"):
            verifier, module_name = _load_fresh_attested_verifier(
                "federal_staging_canary"
            )
            verifier.assert_live_staging_contract(payload)
            resealed = verifier.seal_report(payload)
            content_digest = str(payload.get("content_digest") or "")
            if (
                resealed.get("content_digest") != content_digest
                or payload.get("digest") != content_digest
                or payload.get("fixture_only") is not False
                or payload.get("live_staging") is not True
                or payload.get("dirty") is not False
            ):
                raise PublicationRuntimeError(
                    "Federal staging canary digest or live identity drifted"
                )
        else:  # pragma: no cover - mapping and branches are kept exhaustive.
            return None
    except PublicationRuntimeError:
        raise
    except Exception as exc:
        raise PublicationRuntimeError(
            f"producer-native receipt validation failed for {relpath}: {exc}"
        ) from exc
    finally:
        if verifier is not None and module_name:
            _discard_fresh_attested_verifier(verifier, module_name)
    content_digest = normalize_sha256(
        content_digest,
        name=f"{relpath}.producer_content_digest",
    )
    fixture_only = payload.get("fixture_only") is True or payload.get("mode") == "fixture"
    return (
        "passed",
        {
            "raw_sha256": raw_file_digest(raw),
            "canonical_digest": content_digest,
            "content_digest": content_digest,
        },
        {"fixture_only": fixture_only, "producer_native": True},
    )


def load_receipt(root: Path, relpath: str) -> dict[str, Any]:
    raw = read_canonical_bytes(root, relpath)
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except PublicationRuntimeError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PublicationRuntimeError(
            f"receipt is not strict UTF-8 JSON: {relpath}"
        ) from exc
    if not isinstance(payload, dict):
        raise PublicationRuntimeError(f"receipt must be a JSON object: {relpath}")
    native = _validated_native_phase_receipt(
        root=root,
        relpath=relpath,
        payload=payload,
        raw=raw,
    )
    receipt_overrides: dict[str, Any] = {}
    if native is not None:
        status, digests, receipt_overrides = native
    else:
        status = _require_receipt_status(payload, relpath)
        if (
            relpath == RIGHTS_RECEIPT_RELPATH
            and payload.get("report_schema") == LIVE_SOURCE_RIGHTS_REPORT_SCHEMA
        ):
            declared = _declared_digest(payload, "report_digest_sha256")
            body = dict(payload)
            body.pop("report_digest_sha256", None)
            computed = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
            if declared is None or declared != computed:
                raise IndependentDigestError(
                    "live source-rights report digest does not match its "
                    "canonical body"
                )
            digests = {
                "raw_sha256": raw_file_digest(raw),
                "canonical_digest": computed,
                "content_digest": computed,
            }
        else:
            schema = _require_receipt_schema(payload, relpath)
            if schema in {
                PRODUCTION_MANIFEST_SCHEMA_V2,
                PRODUCTION_ACCEPTANCE_SCHEMA_V2,
            }:
                declared = _declared_digest(payload, "report_digest_sha256")
                computed = _production_candidate_report_digest(payload)
                if declared is None or declared != computed:
                    raise IndependentDigestError(
                        f"{relpath} LCR-084 report digest does not match its "
                        "canonical body"
                    )
                digests = {
                    "raw_sha256": raw_file_digest(raw),
                    "canonical_digest": computed,
                    "content_digest": computed,
                }
            elif schema == MUTATION_AUDIT_SCHEMA_V2:
                mutation_audit: Any = None
                module_name = ""
                try:
                    mutation_audit, module_name = _load_fresh_attested_verifier(
                        "mutation_audit"
                    )
                    measured = mutation_audit.validate_frozen_mutation_inventory(
                        repository_root=root
                    )
                except Exception as exc:
                    raise IndependentDigestError(
                        f"{relpath} mutation-path audit verification failed: {exc}"
                    ) from exc
                finally:
                    if mutation_audit is not None and module_name:
                        _discard_fresh_attested_verifier(
                            mutation_audit,
                            module_name,
                        )
                if payload != measured:
                    raise IndependentDigestError(
                        f"{relpath} differs from the remeasured mutation inventory"
                    )
                computed = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
                digests = {
                    "raw_sha256": raw_file_digest(raw),
                    "canonical_digest": computed,
                    "content_digest": computed,
                }
            else:
                digests = verify_independent_digests(
                    relpath=relpath,
                    raw=raw,
                    payload=payload,
                )
    receipt = dict(payload)
    receipt["path"] = relpath
    receipt["status"] = status
    receipt["content_digest"] = digests["content_digest"]
    receipt["canonical_digest"] = digests["canonical_digest"]
    receipt["raw_sha256"] = digests["raw_sha256"]
    receipt.update(receipt_overrides)
    if (
        receipt.get("producer_native") is True
        and relpath
        not in {
            STATE_CANDIDATE_MANIFEST_RELPATH,
            FEDERAL_CANDIDATE_MANIFEST_RELPATH,
        }
    ):
        for field_name in ("final_manifest_digest", "manifest_digest"):
            if field_name in receipt:
                receipt[f"producer_{field_name}"] = receipt.pop(field_name)
    if relpath in {
        STATE_STAGING_UPLOAD_RELPATH,
        STATE_STAGING_CANARY_RELPATH,
    }:
        for field_name in ("final_manifest_digest", "manifest_digest"):
            if field_name in receipt:
                receipt[f"producer_{field_name}"] = receipt.pop(field_name)
    if payload.get("schema") == PRODUCTION_MANIFEST_SCHEMA_V2:
        # The gate's receipt binding uses final_manifest_digest, while the
        # candidate's top-level manifest_digest names release artifact bytes.
        receipt["final_manifest_digest"] = digests["content_digest"]
    receipt.setdefault("fixture_only", False)
    receipt.setdefault("dirty", False)
    return receipt


def parse_utc_z(value: Any, *, name: str = "sealed_at") -> datetime:
    text = str(value or "").strip()
    if not text:
        raise SealTimeError(f"{name} is missing")
    if _OFFSET_TIME_RE.search(text) or text.endswith("+00:00") or text.endswith("-00:00"):
        raise SealTimeError(f"{name} must be strict UTC-Z, not an offset timestamp")
    match = _UTC_Z_RE.fullmatch(text)
    if not match:
        raise SealTimeError(f"{name} must be YYYY-MM-DDTHH:MM:SSZ")
    parsed = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return parsed


def load_main_seal(
    root: Path,
    phase: str,
    *,
    mutation_start: datetime,
    head: str,
    manifest_digest: str,
    dataset_repo_id: str,
) -> Optional[dict[str, Any]]:
    if not prepublication_seal_required(phase):
        return None
    relpath = main_seal_relpath(phase)
    if not relpath:
        raise SealTimeError(f"{phase} is missing a sealed seal path")
    raw = read_canonical_bytes(root, relpath)
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except PublicationRuntimeError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SealTimeError("prepublication seal is not strict JSON") from exc
    if not isinstance(payload, dict):
        raise SealTimeError("prepublication seal must be a JSON object")
    _require_receipt_schema(payload, relpath)
    _require_receipt_status(payload, relpath)
    digests = verify_independent_digests(relpath=relpath, raw=raw, payload=payload)
    if payload.get("present") is not True:
        raise SealTimeError("main mutation requires present=true prepublication seal")
    sealed_at = parse_utc_z(payload.get("sealed_at") or payload.get("seal_time"))
    now = datetime.now(timezone.utc)
    if sealed_at > now:
        raise SealTimeError("main mutation refuses future-dated prepublication seal")
    if sealed_at >= mutation_start:
        raise SealTimeError("main mutation refuses post-mutation prepublication seal")
    bound_manifest = payload.get("final_manifest_digest") or payload.get("manifest_digest")
    if not bound_manifest:
        raise SealTimeError("prepublication seal is missing final_manifest_digest")
    if normalize_sha256(bound_manifest, name="seal.final_manifest_digest") != manifest_digest:
        raise SealTimeError("prepublication seal does not bind the candidate manifest digest")
    bound_head = str(payload.get("head") or payload.get("git_head") or "").strip().casefold()
    if bound_head and require_immutable_revision(bound_head, name="seal.head") != head:
        raise SealTimeError("prepublication seal HEAD does not match the actual clean HEAD")
    bound_repo = str(
        payload.get("dataset_repo_id") or payload.get("target_dataset_repo_id") or ""
    ).strip()
    if bound_repo and bound_repo != dataset_repo_id:
        raise SealTimeError("prepublication seal target does not match the mutation dataset")
    if payload.get("created_after_mutation") is True or payload.get("post_hoc") is True:
        raise SealTimeError("main mutation refuses post-hoc prepublication seal")
    staging = payload.get("staging_revision")
    if not staging:
        raise SealTimeError("main mutation seal is missing staging_revision")
    seal = dict(payload)
    seal.update(digests)
    seal["path"] = relpath
    seal["present"] = True
    seal["timing"] = "before_mutation"
    seal["sealed_at"] = sealed_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    seal["staging_revision"] = require_immutable_revision(
        staging, name="seal.staging_revision"
    )
    return seal


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def obtain_token(environ: Mapping[str, str]) -> tuple[str, str]:
    found: list[tuple[str, str]] = []
    for name in TOKEN_ENV_ALLOWLIST:
        value = environ.get(name)
        if isinstance(value, str) and value.strip():
            found.append((name, value))
    if not found:
        raise CredentialTokenError(
            "allowlisted credential environment variable is missing or empty"
        )
    names = {name for name, _ in found}
    values = {value for _, value in found}
    if len(values) > 1:
        raise CredentialTokenError("allowlisted credential environment variables disagree")
    name, token = found[0]
    if any(token == other and other != name for other in names):
        pass
    if not token.strip():
        raise CredentialTokenError("allowlisted credential environment variable is empty")
    return name, token


def verify_write_authority(
    *,
    token: str,
    dataset_repo_id: str,
    principal_probe: PrincipalProbe,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    if principal_probe is None:
        raise PrincipalAuthorityError("read-only principal probe is required")
    try:
        projection = principal_probe(token, dataset_repo_id)
    except PublicationGateError:
        raise
    except Exception as exc:
        raise PrincipalAuthorityError(
            "principal probe failed: " + _safe_error_text(exc, (token, *_secret_values(environ)))
        ) from exc
    if not isinstance(projection, Mapping):
        raise PrincipalAuthorityError("principal probe must return a mapping")
    _assert_secret_free(dict(projection), label="principal_probe", environ=environ)
    if _contains_secret(json.dumps(dict(projection), default=str), (token,)):
        raise PrincipalAuthorityError("principal probe leaked credential material")
    principal = str(projection.get("principal") or projection.get("name") or "").strip()
    if not principal:
        raise PrincipalAuthorityError("principal probe did not return a principal")
    expected_scope = credentials_scope_for(dataset_repo_id)
    write_ok = projection.get("has_write_access")
    write_targets = {
        str(item).strip()
        for item in (
            projection.get("write_targets")
            or projection.get("dataset_repo_ids")
            or ()
        )
        if str(item).strip()
    }
    scopes = {
        str(item).strip()
        for item in (projection.get("scopes") or projection.get("write_scopes") or ())
        if str(item).strip()
    }
    target = str(projection.get("dataset_repo_id") or "").strip()
    if target and target != dataset_repo_id:
        raise PrincipalAuthorityError("principal is target-mismatched for the mutation dataset")
    if write_targets and dataset_repo_id not in write_targets:
        raise PrincipalAuthorityError("principal write targets omit the exact mutation dataset")
    if scopes and expected_scope not in scopes and dataset_repo_id not in scopes:
        raise PrincipalAuthorityError("principal scopes omit the exact mutation dataset")
    if write_ok is False:
        raise PrincipalAuthorityError("principal lacks write authority for the exact target")
    if write_ok is not True and dataset_repo_id not in write_targets and expected_scope not in scopes:
        raise PrincipalAuthorityError("principal write authority for the exact target was not proven")
    identity = str(projection.get("identity") or "").strip() or f"env:{dataset_repo_id}"
    if dataset_repo_id not in identity and expected_scope not in identity:
        identity = f"env:{dataset_repo_id}"
    authority_evidence = {
        "authority_source": str(projection.get("authority_source") or "").strip(),
        "dataset_repo_id": dataset_repo_id,
        "has_write_access": write_ok is True,
        "identity": identity,
        "owner": str(projection.get("owner") or "").strip().casefold(),
        "owner_role": str(projection.get("owner_role") or "").strip().casefold(),
        "principal": principal,
        "scopes": sorted(scopes),
        "token_role": str(projection.get("token_role") or "").strip().casefold(),
        "write_targets": sorted(write_targets),
    }
    return {
        "principal": principal,
        "identity": identity,
        "credentials_scope": expected_scope,
        "dataset_repo_id": dataset_repo_id,
        "principal_authority_digest": hashlib.sha256(
            canonical_json_bytes(authority_evidence)
        ).hexdigest(),
        "token_env": next(
            (name for name in TOKEN_ENV_ALLOWLIST if environ.get(name) == token),
            TOKEN_ENV_ALLOWLIST[0],
        ),
    }


# ---------------------------------------------------------------------------
# Snapshot / request construction
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CanonicalPublicationRequest:
    """Non-authoritative caller envelope. Canonical paths and HEAD are derived."""

    phase: str
    repository_root: Path
    authorize_mutation: bool = True
    environ: Mapping[str, str] | None = None
    principal_probe: PrincipalProbe | None = None
    expected_dataset_repo_id: str | None = None
    expected_release_manifest_digest: str | None = None
    expected_plan_digest: str | None = None
    expected_policy_proof_digest: str | None = None
    mutation_binding: CanonicalMutationBinding | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase", PublicationPhase.coerce(self.phase).value)
        object.__setattr__(
            self, "repository_root", Path(self.repository_root).expanduser()
        )
        if type(self.authorize_mutation) is not bool:
            raise PublicationRuntimeError(
                "authorize_mutation must be an exact boolean"
            )
        if self.environ is not None and not isinstance(self.environ, Mapping):
            raise PublicationRuntimeError("environ must be a mapping")
        if self.principal_probe is not None and not callable(self.principal_probe):
            raise PublicationRuntimeError("principal_probe must be callable")
        if self.mutation_binding is not None and not isinstance(
            self.mutation_binding,
            CanonicalMutationBinding,
        ):
            raise PublicationRuntimeError(
                "mutation_binding must be an immutable CanonicalMutationBinding"
            )
        if self.expected_dataset_repo_id is not None:
            expected_repo = _require_non_empty_str(
                self.expected_dataset_repo_id,
                "expected_dataset_repo_id",
                maximum=512,
            )
            object.__setattr__(
                self,
                "expected_dataset_repo_id",
                expected_repo,
            )
        for attribute in (
            "expected_release_manifest_digest",
            "expected_plan_digest",
            "expected_policy_proof_digest",
        ):
            value = getattr(self, attribute)
            if value is not None:
                object.__setattr__(
                    self,
                    attribute,
                    normalize_sha256(value, name=attribute),
                )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CanonicalPublicationRequest":
        if not isinstance(value, Mapping):
            raise PublicationRuntimeError("canonical publication request must be a mapping")
        extras = set(value) & AUTHORITATIVE_OVERRIDE_KEYS
        commit_keys = extras & {
            "branch",
            "claimed_commit",
            "claimed_head",
            "commit",
            "current_commit",
            "git_ref",
            "ref",
        }
        if commit_keys:
            raise CallerCommitError(
                "caller-selected commits cannot authorize: "
                + ", ".join(sorted(commit_keys))
            )
        if extras:
            raise CanonicalPathOverrideError(
                "authoritative caller overrides are rejected: "
                + ", ".join(sorted(extras))
            )
        return cls(
            phase=value.get("phase", ""),
            repository_root=Path(str(value.get("repository_root") or value.get("repo_root") or "")),
            authorize_mutation=value.get("authorize_mutation", True),
            environ=value.get("environ"),
            principal_probe=value.get("principal_probe"),
            expected_dataset_repo_id=value.get(
                "expected_dataset_repo_id"
            ),
            expected_release_manifest_digest=value.get(
                "expected_release_manifest_digest"
            ),
            expected_plan_digest=value.get("expected_plan_digest"),
            expected_policy_proof_digest=value.get(
                "expected_policy_proof_digest"
            ),
            mutation_binding=value.get("mutation_binding"),
        )


def _control_digests(root: Path, phase: str) -> dict[str, str]:
    digests: dict[str, str] = {}
    for relpath in authoritative_relpaths(phase):
        path = _resolve_canonical_file(root, relpath)
        if path.is_file():
            digests[relpath] = raw_file_digest(path.read_bytes())
    return digests


def _validate_lcr084_production_candidate(
    root: Path,
    payload: Mapping[str, Any],
    *,
    phase: str,
    remeasure_production_evidence: bool = False,
    runtime_token: str | None = None,
) -> dict[str, str] | None:
    """Run the LCR-084 builder's strict acceptance/audit remeasurement."""

    verifier: Any = None
    module_name = ""
    try:
        if phase not in ("state_staging", "state_main"):
            raise PublicationRuntimeError(
                "LCR-084 candidate requires an exact State Laws phase"
            )
        verifier, module_name = _load_fresh_attested_verifier(
            "lcr084_candidate"
        )
        binding_checker = vars(verifier).get(
            "check_production_candidate_publication_binding"
        )
        if not callable(binding_checker):
            raise PublicationRuntimeError(
                "fresh LCR-084 verifier omits its publication-binding checker"
            )
        publication_binding = binding_checker(payload, phase=phase)
        if remeasure_production_evidence is True:
            result = _isolated_lcr084_candidate_remeasurement(
                root,
                phase=phase,
                payload=payload,
                runtime_token=str(runtime_token or ""),
            )
        else:
            if remeasure_production_evidence is not False:
                raise PublicationRuntimeError(
                    "LCR-084 remeasurement selector must be an exact boolean"
                )
            checker = vars(verifier).get("check_production_candidate_report")
            if not callable(checker):
                raise PublicationRuntimeError(
                    "fresh LCR-084 verifier omits its strict checker"
                )
            result = checker(
                payload,
                repo_root=root,
                remeasure_production_evidence=False,
            )
    except Exception as exc:
        # CandidateError intentionally remains an implementation detail of the
        # verifier script; the runtime exposes one stable binding failure.
        raise ManifestBindingError(
            f"LCR-084 production candidate verification failed: {exc}"
        ) from exc
    finally:
        if verifier is not None and module_name:
            _discard_fresh_attested_verifier(verifier, module_name)
    if result != {
        "jurisdiction_count": 51,
        "ok": True,
        "task_id": "LCR-084",
        "valid": True,
    }:
        raise ManifestBindingError(
            "LCR-084 production candidate verifier returned an unexpected result"
        )
    if publication_binding is None:
        return None
    if type(publication_binding) is not dict:
        raise ManifestBindingError(
            "LCR-084 publication binding verifier returned an invalid result"
        )
    return dict(publication_binding)


def _validate_lcr084_publication_chain(
    *,
    request: CanonicalPublicationRequest,
    payload: Mapping[str, Any],
    publication_binding: Mapping[str, str] | None,
    receipts: Mapping[str, Mapping[str, Any]],
    candidate_release_manifest_digest: str,
) -> dict[str, Any]:
    """Bind staging identity A and main identity B without conflating them."""

    staging_payload = dict(payload)
    staging_payload["publication_binding"] = None
    staging_candidate_digest = _production_candidate_report_digest(
        staging_payload
    )
    if request.phase == "state_staging":
        if publication_binding is not None:
            raise ManifestBindingError(
                "State staging requires an LCR-084 candidate with null "
                "publication_binding"
            )
        if payload.get("report_digest_sha256") != staging_candidate_digest:
            raise ManifestBindingError(
                "State staging candidate-control digest does not equal A"
            )
        return {
            "staging_candidate_digest": staging_candidate_digest,
            "staging_revision": None,
        }
    if request.phase != "state_main" or not isinstance(
        publication_binding,
        Mapping,
    ):
        raise ManifestBindingError(
            "State main requires a populated LCR-084 publication binding"
        )
    expected_constraints = {
        "plan_digest": request.expected_plan_digest,
        "policy_proof_digest": request.expected_policy_proof_digest,
        "release_manifest_digest": (
            request.expected_release_manifest_digest
        ),
    }
    for field_name, expected_value in expected_constraints.items():
        if expected_value is None:
            raise ManifestBindingError(
                f"State main requires the exact {field_name} constraint"
            )
        if publication_binding.get(field_name) != expected_value:
            raise ManifestBindingError(
                f"LCR-084 publication_binding.{field_name} differs from "
                "the source-attested publication constraint"
            )
    if (
        publication_binding.get("staging_candidate_digest")
        != staging_candidate_digest
        or publication_binding.get("release_manifest_digest")
        != candidate_release_manifest_digest
    ):
        raise ManifestBindingError(
            "LCR-084 publication binding does not close A and the release "
            "artifact identity"
        )
    canary_revision: str | None = None
    for relpath in (
        STATE_STAGING_UPLOAD_RELPATH,
        STATE_STAGING_CANARY_RELPATH,
    ):
        receipt = receipts.get(relpath)
        if not isinstance(receipt, Mapping):
            raise ManifestBindingError(
                f"State main is missing canonical staging receipt {relpath}"
            )
        if (
            receipt.get("status") != "passed"
            or receipt.get("fixture_only") is not False
            or receipt.get("dirty") is not False
            or receipt.get("dataset_repo_id") != STATE_DATASET_REPO_ID
            or receipt.get("producer_final_manifest_digest")
            != staging_candidate_digest
            or receipt.get("release_manifest_digest")
            != candidate_release_manifest_digest
        ):
            raise ManifestBindingError(
                f"State staging receipt {relpath} does not bind A, the release, "
                "and the exact live dataset"
            )
        if relpath == STATE_STAGING_CANARY_RELPATH:
            canary_revision = require_immutable_revision(
                str(receipt.get("staging_revision") or ""),
                name="State staging canary revision",
            )
    return {
        "staging_candidate_digest": staging_candidate_digest,
        "staging_revision": canary_revision,
    }


def capture_canonical_snapshot(
    request: CanonicalPublicationRequest,
    *,
    mutation_start: Optional[datetime] = None,
) -> dict[str, Any]:
    environ = dict(request.environ or {})
    start = mutation_start or datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    root = resolve_repository_root(request.repository_root)
    paths = authoritative_relpaths(request.phase)
    head = inspect_clean_head(
        root,
        authoritative_paths=() if request.authorize_mutation else paths,
    )
    policy = load_release_policy(root)
    _require_policy_phase_contract(policy, request.phase)
    lineage = load_task_lineage(root)
    contract = phase_requirements(request.phase)
    receipts: dict[str, dict[str, Any]] = {}
    expected: dict[str, str] = {}
    for relpath in contract["required_receipts"]:
        receipt = load_receipt(root, relpath)
        receipts[relpath] = receipt
        expected[relpath] = receipt["content_digest"]

    manifest_relpath = candidate_manifest_relpath(request.phase)
    if manifest_relpath not in receipts:
        receipts[manifest_relpath] = load_receipt(root, manifest_relpath)
        expected[manifest_relpath] = receipts[manifest_relpath]["content_digest"]
    manifest = dict(receipts[manifest_relpath])
    on_disk_manifest = read_canonical_json(root, manifest_relpath)
    manifest_schema = manifest.get("schema")
    publication_binding: dict[str, str] | None = None
    if request.phase.startswith("state_") and manifest_schema != (
        PRODUCTION_MANIFEST_SCHEMA_V2
    ):
        raise ManifestBindingError(
            "State Laws publication requires the canonical LCR-084 @2 "
            "candidate; generic @1 candidates are non-authorizing"
        )
    if manifest_schema == PRODUCTION_MANIFEST_SCHEMA_V2:
        if not request.phase.startswith("state_"):
            raise ManifestBindingError(
                "LCR-084 production candidate is valid only for State Laws"
            )
        publication_binding = _validate_lcr084_production_candidate(
            root,
            on_disk_manifest,
            phase=request.phase,
        )
    elif (
        request.phase.startswith("federal_")
        and manifest_schema == FEDERAL_PRODUCTION_CANDIDATE_SCHEMA
    ):
        publication_binding_value = on_disk_manifest.get("publication_binding")
        if not isinstance(publication_binding_value, Mapping):
            raise ManifestBindingError(
                "Federal publication candidate lacks its exact publication binding"
            )
        publication_binding = dict(publication_binding_value)
        if (
            on_disk_manifest.get("fixture_only") is not False
            or on_disk_manifest.get("mode")
            not in ("live", "production", "live_official")
            or on_disk_manifest.get("authorizing_for_publication") is not False
            or on_disk_manifest.get("authorizing_hub_upload") is not False
            or on_disk_manifest.get("hub_upload") is not False
        ):
            raise ManifestBindingError(
                "Federal publication candidate is fixture or mutation-authorizing"
            )
    elif manifest_schema != MANIFEST_SCHEMA_V1:
        raise ManifestBindingError("candidate manifest schema is not bound")
    rights = receipts.get(RIGHTS_RECEIPT_RELPATH)
    if not isinstance(rights, Mapping):
        raise ManifestBindingError("source-rights receipt is missing from canonical paths")
    source_rights_binding = manifest.get("source_rights")
    bound_rights = str(
        manifest.get("source_rights_receipt_digest")
        or manifest.get("source_rights_compliance_digest")
        or (
            source_rights_binding.get("receipt_digest")
            if isinstance(source_rights_binding, Mapping)
            else ""
        )
        or ""
    ).strip()
    if not bound_rights:
        raise ManifestBindingError("candidate manifest does not bind the source-rights receipt")
    if normalize_sha256(bound_rights, name="manifest.source_rights_receipt_digest") != rights[
        "content_digest"
    ]:
        raise ManifestBindingError("candidate manifest source-rights digest does not match receipt")
    card_text = read_canonical_text(root, dataset_card_relpath(request.phase))
    if rights["content_digest"] not in card_text and rights["content_digest"][:16] not in card_text:
        raise ManifestBindingError("dataset card does not bind the source-rights receipt digest")

    if manifest_schema == PRODUCTION_MANIFEST_SCHEMA_V2:
        recomputed_manifest = _production_candidate_report_digest(
            on_disk_manifest
        )
        declared_manifest = str(
            on_disk_manifest.get("report_digest_sha256") or ""
        ).strip()
        if (
            not declared_manifest
            or normalize_sha256(
                declared_manifest,
                name="report_digest_sha256",
            )
            != recomputed_manifest
        ):
            raise IndependentDigestError(
                "LCR-084 candidate report digest does not match canonical body"
            )
    elif manifest_schema == FEDERAL_PRODUCTION_CANDIDATE_SCHEMA:
        recomputed_manifest = _federal_candidate_report_digest(on_disk_manifest)
        declared_manifest = str(
            on_disk_manifest.get("content_digest") or ""
        ).strip()
        if (
            not declared_manifest
            or normalize_sha256(
                declared_manifest,
                name="content_digest",
            )
            != recomputed_manifest
        ):
            raise IndependentDigestError(
                "Federal candidate content_digest does not match canonical body"
            )
    else:
        recomputed_manifest = canonical_no_self_field_digest(on_disk_manifest)
        declared_manifest = str(
            on_disk_manifest.get("final_manifest_digest") or ""
        ).strip()
        if declared_manifest:
            if (
                normalize_sha256(
                    declared_manifest,
                    name="final_manifest_digest",
                )
                != recomputed_manifest
            ):
                raise IndependentDigestError(
                    "candidate final_manifest_digest does not match "
                    "no-self-field recompute"
                )
    final_manifest_digest = recomputed_manifest
    candidate_release_manifest_digest = _candidate_release_manifest_digest(
        manifest
    )

    dataset_repo_id = contract["dataset_repo_id"]
    if dataset_repo_id not in AUTHORIZED_DATASET_REPO_IDS:
        raise PublicationRuntimeError("phase dataset is not an authorized legal-corpora target")
    if (
        request.expected_dataset_repo_id is not None
        and request.expected_dataset_repo_id != dataset_repo_id
    ):
        raise ManifestBindingError(
            "canonical phase repository differs from the caller's fail-closed "
            "expected repository constraint"
        )
    if request.expected_release_manifest_digest is not None:
        if (
            not candidate_release_manifest_digest
            or candidate_release_manifest_digest
            != request.expected_release_manifest_digest
        ):
            raise ManifestBindingError(
                "canonical candidate release-manifest binding differs from "
                "the exact publication plan constraint"
            )
    publication_chain: dict[str, Any] | None = None
    if manifest_schema == PRODUCTION_MANIFEST_SCHEMA_V2:
        publication_chain = _validate_lcr084_publication_chain(
            request=request,
            payload=on_disk_manifest,
            publication_binding=publication_binding,
            receipts=receipts,
            candidate_release_manifest_digest=(
                candidate_release_manifest_digest
            ),
        )
    elif manifest_schema == FEDERAL_PRODUCTION_CANDIDATE_SCHEMA:
        if publication_binding is None:
            raise ManifestBindingError(
                "Federal candidate publication binding is missing"
            )
        expected_constraints = {
            "plan_digest": request.expected_plan_digest,
            "policy_proof_digest": request.expected_policy_proof_digest,
            "release_manifest_digest": request.expected_release_manifest_digest,
        }
        for field_name, expected_value in expected_constraints.items():
            if expected_value is None or publication_binding.get(field_name) != expected_value:
                raise ManifestBindingError(
                    f"Federal publication_binding.{field_name} differs from the exact request"
                )
        if (
            publication_binding.get("release_manifest_digest")
            != candidate_release_manifest_digest
        ):
            raise ManifestBindingError(
                "Federal candidate publication binding differs from release bytes"
            )
    for field_name, expected_value in (
        ("plan_digest", request.expected_plan_digest),
        ("policy_proof_digest", request.expected_policy_proof_digest),
    ):
        if expected_value is None:
            continue
        if manifest_schema in (
            PRODUCTION_MANIFEST_SCHEMA_V2,
            FEDERAL_PRODUCTION_CANDIDATE_SCHEMA,
        ):
            # The exact phase-aware nested binding was validated above.  A
            # staging candidate intentionally carries null and a main
            # candidate carries the plan/proof identities in that binding.
            continue
        candidate_value = manifest.get(field_name)
        if (
            not candidate_value
            or normalize_sha256(
                candidate_value,
                name=f"candidate_manifest.{field_name}",
            )
            != expected_value
        ):
            raise ManifestBindingError(
                f"canonical candidate {field_name} differs from the exact "
                "publication constraint"
            )

    token_name, token = obtain_token(environ)
    if request.principal_probe is None:
        raise PrincipalAuthorityError("read-only principal probe is required")
    identity = verify_write_authority(
        token=token,
        dataset_repo_id=dataset_repo_id,
        principal_probe=request.principal_probe,
        environ=environ,
    )

    seal = load_main_seal(
        root,
        request.phase,
        mutation_start=start,
        head=head,
        manifest_digest=final_manifest_digest,
        dataset_repo_id=dataset_repo_id,
    )
    staging_revision = None
    if seal is not None:
        staging_revision = seal.get("staging_revision")
        for field_name, expected_value in (
            ("plan_digest", request.expected_plan_digest),
            ("policy_proof_digest", request.expected_policy_proof_digest),
            (
                "release_manifest_digest",
                request.expected_release_manifest_digest,
            ),
        ):
            if expected_value is None:
                continue
            seal_value = seal.get(field_name)
            if (
                not seal_value
                or normalize_sha256(
                    seal_value,
                    name=f"prepublication_seal.{field_name}",
                )
                != expected_value
            ):
                raise ManifestBindingError(
                    f"canonical prepublication seal {field_name} differs "
                    "from the exact publication constraint"
                )
        if (
            manifest_schema == PRODUCTION_MANIFEST_SCHEMA_V2
            and publication_chain is not None
            and staging_revision
            != publication_chain.get("staging_revision")
        ):
            raise ManifestBindingError(
                "State main seal staging revision differs from the canonical "
                "A-bound staging canary"
            )
    elif request.phase.endswith("_main"):
        raise SealTimeError("main mutation requires a canonical prepublication seal")

    snapshot = {
        "head": head,
        "phase": request.phase,
        "repository_root": root.as_posix(),
        "mutation_start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "release_policy_digest": raw_file_digest(
            read_canonical_bytes(root, RELEASE_POLICY_RELPATH)
        ),
        "control_digests": _control_digests(root, request.phase),
        "task_statuses": lineage["task_statuses"],
        "task_dependencies": lineage["task_dependencies"],
        "task_goal_ids": lineage["task_goal_ids"],
        "goal_parents": lineage["goal_parents"],
        "receipts": receipts,
        "expected_receipt_digests": expected,
        "candidate_manifest": {
            key: value
            for key, value in manifest.items()
            if key not in SELF_DIGEST_FIELDS
        },
        "dataset_card": card_text,
        "final_manifest_digest": final_manifest_digest,
        "candidate_release_manifest_digest": (
            candidate_release_manifest_digest
        ),
        "dataset_repo_id": dataset_repo_id,
        "operation": contract["authorized_operation"],
        "previous_public_pin": contract["previous_public_pin"],
        "prepublication_seal": seal,
        "staging_revision": staging_revision,
        "credential_identity": identity["identity"],
        "credentials_scope": identity["credentials_scope"],
        "principal": identity["principal"],
        "principal_authority_digest": identity[
            "principal_authority_digest"
        ],
        "token_env": token_name,
        "authorize_mutation": bool(request.authorize_mutation),
        "expected_plan_digest": request.expected_plan_digest,
        "expected_policy_proof_digest": (
            request.expected_policy_proof_digest
        ),
        "expected_payload_digest": (
            request.mutation_binding.payload_digest
            if request.mutation_binding is not None
            else None
        ),
    }
    _assert_secret_free(snapshot, label="canonical_snapshot", environ=environ)
    return snapshot


def build_gate_request(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "phase": snapshot["phase"],
        "operation": snapshot["operation"],
        "dataset_repo_id": snapshot["dataset_repo_id"],
        "final_manifest_digest": snapshot["final_manifest_digest"],
        "previous_public_pin": snapshot["previous_public_pin"],
        "task_statuses": dict(snapshot["task_statuses"]),
        "task_dependencies": {
            key: list(value) for key, value in dict(snapshot["task_dependencies"]).items()
        },
        "task_goal_ids": dict(snapshot["task_goal_ids"]),
        "goal_parents": {
            key: list(value) for key, value in dict(snapshot["goal_parents"]).items()
        },
        "receipts": {key: dict(value) for key, value in dict(snapshot["receipts"]).items()},
        "expected_receipt_digests": dict(snapshot["expected_receipt_digests"]),
        "credentials_environment_only": True,
        "credentials_scope": snapshot["credentials_scope"],
        "credential_identity": snapshot["credential_identity"],
        "secret_redacted": True,
        "authorize_mutation": bool(snapshot["authorize_mutation"]),
        "evidence_is_dirty": False,
        "fixture_only_evidence": False,
        "current_commit": snapshot["head"],
        "payload": {
            "release_mode": "additive",
            "credentials_environment_only": True,
            "secret_redacted": True,
            "candidate_manifest": dict(snapshot["candidate_manifest"]),
            "dataset_card": snapshot["dataset_card"],
            "canonical_head": snapshot["head"],
            "runtime_task_id": TASK_ID,
            "runtime_goal_id": GOAL_ID,
            "gate_task_id": PREDECESSOR_GATE_TASK_ID,
            "source_rights_task_id": PREDECESSOR_RIGHTS_TASK_ID,
            "control_digests": dict(snapshot["control_digests"]),
            "principal": snapshot["principal"],
            "token_env": snapshot["token_env"],
            "mutation_start": snapshot["mutation_start"],
        },
        "argv": [
            "publish-legal-corpora",
            "--phase",
            str(snapshot["phase"]),
            "--authorize-mutation",
        ],
    }
    if snapshot.get("staging_revision"):
        payload["staging_revision"] = snapshot["staging_revision"]
    if snapshot.get("prepublication_seal") is not None:
        payload["prepublication_seal"] = dict(snapshot["prepublication_seal"])
    return payload


def _snapshot_fingerprint(snapshot: Mapping[str, Any]) -> str:
    material = {
        "head": snapshot.get("head"),
        "control_digests": snapshot.get("control_digests"),
        "expected_receipt_digests": snapshot.get("expected_receipt_digests"),
        "final_manifest_digest": snapshot.get("final_manifest_digest"),
        "candidate_release_manifest_digest": snapshot.get(
            "candidate_release_manifest_digest"
        ),
        "expected_plan_digest": snapshot.get("expected_plan_digest"),
        "expected_policy_proof_digest": snapshot.get(
            "expected_policy_proof_digest"
        ),
        "expected_payload_digest": snapshot.get("expected_payload_digest"),
        "task_statuses": snapshot.get("task_statuses"),
        "principal": snapshot.get("principal"),
        "credential_identity": snapshot.get("credential_identity"),
        "credentials_scope": snapshot.get("credentials_scope"),
        "token_env": snapshot.get("token_env"),
        "principal_authority_digest": snapshot.get(
            "principal_authority_digest"
        ),
    }
    return hashlib.sha256(canonical_json_bytes(material)).hexdigest()


def _denied_decision(
    *,
    phase: str,
    reason_code: str,
    message: str,
    environ: Mapping[str, str],
    extra: Optional[Mapping[str, Any]] = None,
) -> PublicationGateDecision:
    contract = None
    repo = STATE_DATASET_REPO_ID
    operation = "unknown"
    pin = str(BASELINE_REVISIONS[STATE_DATASET_REPO_ID])
    digest = "0" * 64
    try:
        coerced = PublicationPhase.coerce(phase).value
        contract = phase_requirements(coerced)
        repo = contract["dataset_repo_id"]
        operation = contract["authorized_operation"]
        pin = contract["previous_public_pin"]
        phase = coerced
    except PublicationGateError:
        pass
    details = {
        "task_id": TASK_ID,
        "gate_task_id": PREDECESSOR_GATE_TASK_ID,
        "producer": PRODUCER,
        "schema_version": SCHEMA_VERSION,
        "error": message,
        **dict(extra or {}),
    }
    decision = PublicationGateDecision(
        authorized=False,
        phase=phase,
        operation=operation,
        dataset_repo_id=repo if repo in AUTHORIZED_DATASET_REPO_IDS else STATE_DATASET_REPO_ID,
        final_manifest_digest=digest,
        previous_public_pin=pin,
        reason_codes=(reason_code,),
        passed_gates=(),
        required_gates=REQUIRED_PUBLICATION_GATES,
        message=message,
        details=details,
        network_mutation_permitted=False,
    )
    _assert_secret_free(decision.to_dict(), label="publication_runtime_decision", environ=environ)
    return decision


def evaluate_canonical_publication(
    request: CanonicalPublicationRequest | Mapping[str, Any],
    *,
    mutation_start: Optional[datetime] = None,
) -> PublicationGateDecision:
    """Load canonical evidence and evaluate the LCR-074/LCR-083 gate."""

    environ: dict[str, str] = {}
    phase = "unknown"
    try:
        req = (
            request
            if type(request) is CanonicalPublicationRequest
            else CanonicalPublicationRequest.from_mapping(request)
        )
        phase = req.phase
        environ = dict(req.environ or {})
        req = replace(req, environ=MappingProxyType(environ))
        start = mutation_start or datetime.now(timezone.utc)
        snapshot = capture_canonical_snapshot(req, mutation_start=start)
        gate_request = build_gate_request(snapshot)
        decision = evaluate_publication_gate(gate_request, environ=environ)
        details = dict(decision.details)
        details.update(
            {
                "runtime_task_id": TASK_ID,
                "runtime_goal_id": GOAL_ID,
                "gate_task_id": PREDECESSOR_GATE_TASK_ID,
                "source_rights_task_id": PREDECESSOR_RIGHTS_TASK_ID,
                "head": snapshot["head"],
                "token_env": snapshot["token_env"],
                "principal": snapshot["principal"],
                "principal_authority_digest": snapshot[
                    "principal_authority_digest"
                ],
                "operation": snapshot["operation"],
                "mutation_start": snapshot["mutation_start"],
                "control_digest_count": len(snapshot["control_digests"]),
                "snapshot_fingerprint": _snapshot_fingerprint(snapshot),
                "candidate_release_manifest_digest": snapshot.get(
                    "candidate_release_manifest_digest"
                ),
                "expected_plan_digest": snapshot.get(
                    "expected_plan_digest"
                ),
                "expected_policy_proof_digest": snapshot.get(
                    "expected_policy_proof_digest"
                ),
                "expected_payload_digest": snapshot.get(
                    "expected_payload_digest"
                ),
                "source_rights_binding_required": True,
                "source_rights_receipt_digest": snapshot["receipts"][
                    RIGHTS_RECEIPT_RELPATH
                ]["content_digest"],
                "required_task_ids": list(
                    phase_requirements(snapshot["phase"])["required_task_ids"]
                ),
                "required_gates": list(REQUIRED_PUBLICATION_GATES),
                "prepublication_seal_bound": snapshot.get("prepublication_seal")
                is not None,
            }
        )
        bound = PublicationGateDecision(
            authorized=decision.authorized,
            phase=decision.phase,
            operation=decision.operation,
            dataset_repo_id=decision.dataset_repo_id,
            final_manifest_digest=decision.final_manifest_digest,
            previous_public_pin=decision.previous_public_pin,
            reason_codes=decision.reason_codes,
            passed_gates=decision.passed_gates,
            required_gates=REQUIRED_PUBLICATION_GATES,
            message=decision.message,
            details=details,
            network_mutation_permitted=decision.network_mutation_permitted,
        )
        _assert_secret_free(bound.to_dict(), label="publication_runtime_decision", environ=environ)
        return bound
    except PublicationGateError as exc:
        code = f"runtime.{getattr(exc, 'code', 'publication_runtime_error')}"
        return _denied_decision(
            phase=phase,
            reason_code=code,
            message=_safe_error_text(exc, _secret_values(environ)),
            environ=environ,
        )


def require_canonical_publication(
    request: CanonicalPublicationRequest | Mapping[str, Any],
    *,
    mutation_start: Optional[datetime] = None,
) -> PublicationGateDecision:
    decision = evaluate_canonical_publication(request, mutation_start=mutation_start)
    return decision.require_authorized()


def _require_publisher_sealed_type(
    value: Any,
    *,
    type_name: str,
    method_name: str,
    code_name: str,
    label: str,
) -> tuple[CanonicalMutationBinding, Any]:
    """Attest one exact publisher type/method against loaded and source bytes."""

    module_name = "ipfs_datasets_py.huggingface.publisher"
    publisher_module = sys.modules.get(module_name)
    publisher_namespace = (
        vars(publisher_module) if publisher_module is not None else {}
    )
    expected_type = publisher_namespace.get(type_name)
    expected_code = publisher_namespace.get(code_name)
    expected_method = (
        vars(expected_type).get(method_name)
        if isinstance(expected_type, type)
        else None
    )
    if (
        publisher_module is None
        or not isinstance(expected_type, type)
        or type(value) is not expected_type
        or getattr(expected_type, "__module__", None) != module_name
        or getattr(expected_type, "__qualname__", None) != type_name
        or getattr(expected_method, "__code__", None) is not expected_code
    ):
        raise PublicationRuntimeError(
            f"canonical mutation requires the exact sealed legal-corpora {label}; "
            "callbacks, aliases, partials, and subclasses are rejected"
        )

    loaded_source_name = str(publisher_namespace.get("__file__") or "").strip()
    loaded_source = Path(loaded_source_name)
    if (
        not loaded_source_name
        or loaded_source.is_symlink()
        or not loaded_source.is_file()
        or tuple(loaded_source.parts[-3:])
        != ("ipfs_datasets_py", "huggingface", "publisher.py")
    ):
        raise PublicationRuntimeError(
            f"sealed legal-corpora {label} source path is not canonical"
        )
    expected_source = loaded_source.resolve()
    source_bytes = loaded_source.read_bytes()
    source_digest = hashlib.sha256(source_bytes).hexdigest()
    if source_digest != str(
        publisher_namespace.get("_PUBLISHER_IMPORT_SOURCE_SHA256") or ""
    ):
        raise PublicationRuntimeError(
            f"sealed legal-corpora {label} source changed after import"
        )
    try:
        from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
            _assert_loaded_executables_match_current_source,
            _loaded_executable_sha256,
        )

        loaded_digest = _loaded_executable_sha256(expected_type)
        _assert_loaded_executables_match_current_source(
            {
                f"legal_corpora_{label.replace(' ', '_')}": {
                    "loaded_executable_sha256": loaded_digest,
                    "source_file_sha256": source_digest,
                    "source_path": str(expected_source),
                    "target": expected_type,
                    "fresh_import_file": str(expected_source),
                    "fresh_import_module": module_name,
                }
            }
        )
    except PublicationRuntimeError:
        raise
    except Exception as exc:
        raise PublicationRuntimeError(
            f"sealed legal-corpora {label} failed loaded/current source attestation"
        ) from exc
    try:
        binding = object.__getattribute__(value, "mutation_binding")
    except Exception as exc:
        raise PublicationRuntimeError(
            f"sealed legal-corpora {label} omits its mutation binding"
        ) from exc
    if type(binding) is not CanonicalMutationBinding:
        raise PublicationRuntimeError(
            f"sealed legal-corpora {label} has no immutable mutation binding"
        )
    return binding, expected_method


def _require_attested_mutation_executor(
    mutation_executor: Any,
) -> tuple[CanonicalMutationBinding, Any]:
    """Accept only the source-attested legal-corpora preflight object."""

    return _require_publisher_sealed_type(
        mutation_executor,
        type_name="_StateLawsCanonicalCommitPreflight",
        method_name="prepare",
        code_name="_STATE_LAWS_CANONICAL_COMMIT_PREFLIGHT_CODE",
        label="commit preflight",
    )


def _require_attested_prepared_executor(
    prepared_executor: Any,
    *,
    expected_binding: CanonicalMutationBinding,
    expected_candidate_digest: str,
    runtime_token: str,
) -> Any:
    """Accept only a deeply constrained capsule returned by sealed preflight."""

    binding, prepared_call = _require_publisher_sealed_type(
        prepared_executor,
        type_name="_PreparedStateLawsCanonicalCommitExecutor",
        method_name="__call__",
        code_name="_STATE_LAWS_PREPARED_COMMIT_EXECUTOR_CODE",
        label="prepared commit executor",
    )
    try:
        candidate_digest = object.__getattribute__(
            prepared_executor,
            "canonical_candidate_digest",
        )
        canonical_message = object.__getattribute__(
            prepared_executor,
            "canonical_message",
        )
        operations = object.__getattribute__(
            prepared_executor,
            "operations_payload",
        )
        prepared_token = object.__getattribute__(
            prepared_executor,
            "runtime_token",
        )
    except Exception as exc:
        raise PublicationRuntimeError(
            "prepared legal-corpora executor omits exact inert fields"
        ) from exc
    if (
        binding != expected_binding
        or type(candidate_digest) is not str
        or candidate_digest != expected_candidate_digest
        or type(canonical_message) is not str
        or not canonical_message
        or type(operations) is not tuple
        or not operations
        or type(prepared_token) is not str
        or prepared_token != runtime_token
    ):
        raise PublicationRuntimeError(
            "prepared legal-corpora executor differs from the exact runtime mutation"
        )
    return prepared_call


def _require_exact_mutation_binding(
    request: CanonicalPublicationRequest,
    snapshot: Mapping[str, Any],
    executor_binding: CanonicalMutationBinding,
) -> None:
    """Bind the sealed executor to canonical controls and request constraints."""

    request_binding = request.mutation_binding
    if request_binding is None or request_binding != executor_binding:
        raise PublicationRuntimeError(
            "canonical request and sealed executor mutation bindings differ"
        )
    expected_repository = str(request.expected_dataset_repo_id or "").strip().casefold()
    contract = phase_requirements(request.phase)
    expected_operation = str(contract["authorized_operation"])
    expected_phase_repository = str(contract["dataset_repo_id"]).casefold()
    staging_phase = request.phase.endswith("_staging")
    revision = executor_binding.revision
    expected_staging_revision = (
        "stage/state-laws-sparse-graphrag-v2"
        if request.phase == "state_staging"
        else "stage/federal-register-ir-graphrag-v2"
        if request.phase == "federal_staging"
        else ""
    )
    revision_is_safe_staging = bool(
        staging_phase
        and revision == expected_staging_revision
        and revision != "main"
        and len(revision) <= 128
        and not revision.startswith(("-", ".", "/"))
        and not revision.endswith((".", "/", ".lock"))
        and ".." not in revision
        and "@{" not in revision
        and not any(character in revision for character in " ~^:?*[\\")
    )
    if (
        request.authorize_mutation is not True
        or request.phase not in CANONICAL_MUTATION_EXECUTOR_PHASES
        or snapshot.get("phase") != request.phase
        or snapshot.get("operation") != expected_operation
        or executor_binding.method not in ("create_branch", "create_commit")
        or (executor_binding.method == "create_branch" and not staging_phase)
        or executor_binding.repository_id != expected_repository
        or executor_binding.repository_id != expected_phase_repository
        or executor_binding.repository_id
        != str(snapshot.get("dataset_repo_id") or "").strip().casefold()
        or executor_binding.repository_type != "dataset"
        or (
            staging_phase
            and not revision_is_safe_staging
        )
        or (
            not staging_phase
            and revision != "main"
        )
        or executor_binding.parent_commit
        != str(snapshot.get("previous_public_pin") or "").strip().casefold()
        or request.expected_plan_digest != executor_binding.plan_digest
        or request.expected_release_manifest_digest
        != executor_binding.release_manifest_digest
        or request.expected_policy_proof_digest
        != executor_binding.policy_proof_digest
        or snapshot.get("candidate_release_manifest_digest")
        != executor_binding.release_manifest_digest
        or snapshot.get("expected_payload_digest")
        != executor_binding.payload_digest
        or any(item.sha256 != item.local_sha256 for item in executor_binding.files)
    ):
        raise PublicationRuntimeError(
            "sealed legal-corpora mutation is not bound to the exact canonical request"
        )


def _revalidate_mutation_inventory_before_callback(
    repository_root: Path,
    *,
    expected_head: str,
) -> dict[str, Any]:
    """Bookend HEAD while validating one paired source/report capture."""

    mutation_audit: Any = None
    module_name = ""
    try:
        mutation_audit, module_name = _load_fresh_attested_verifier(
            "mutation_audit"
        )
        root = _require_mutation_implementation_root(repository_root)
        head_before = inspect_clean_head(root)
        controls_before = {
            MUTATION_AUDIT_REPORT_RELPATH: raw_file_digest(
                read_canonical_bytes(root, MUTATION_AUDIT_REPORT_RELPATH)
            ),
            MUTATION_AUDIT_SCHEMA_RELPATH: raw_file_digest(
                read_canonical_bytes(root, MUTATION_AUDIT_SCHEMA_RELPATH)
            ),
        }
        audit_capture = mutation_audit.validate_frozen_mutation_capture(
            repository_root=root
        )
        measured = audit_capture.report
        source_projection = audit_capture.source_projection
        controls_after = {
            MUTATION_AUDIT_REPORT_RELPATH: raw_file_digest(
                read_canonical_bytes(root, MUTATION_AUDIT_REPORT_RELPATH)
            ),
            MUTATION_AUDIT_SCHEMA_RELPATH: raw_file_digest(
                read_canonical_bytes(root, MUTATION_AUDIT_SCHEMA_RELPATH)
            ),
        }
        head_after = inspect_clean_head(root)
    except Exception as exc:
        raise PublicationRuntimeError(
            f"final protected-write inventory verification failed: {exc}"
        ) from exc
    finally:
        if mutation_audit is not None and module_name:
            _discard_fresh_attested_verifier(mutation_audit, module_name)
    if (
        head_before != expected_head
        or head_after != expected_head
        or head_before != head_after
        or controls_before != controls_after
    ):
        raise EvidenceRaceError(
            "HEAD, mutation-audit controls, or audited source changed during "
            "the final protected-write inventory verification"
        )
    return {
        "inventory_digest_sha256": _production_candidate_report_digest(measured),
        "source_file_count": len(source_projection),
        "source_projection_digest_sha256": hashlib.sha256(
            json.dumps(
                source_projection,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest(),
    }


def _require_final_mutation_audit_binding(
    candidate_audit: Any,
    final_mutation_audit: Mapping[str, Any],
) -> None:
    """Require candidate inventory semantics and bytes to match one capture."""

    if not isinstance(candidate_audit, Mapping) or any(
        candidate_audit.get(key) != value
        for key, value in final_mutation_audit.items()
    ):
        raise PublicationRuntimeError(
            "LCR-084 candidate mutation audit differs from the final "
            "protected-write inventory"
        )


def authorize_and_mutate_canonical(
    request: CanonicalPublicationRequest | Mapping[str, Any],
    mutation_executor: Any,
) -> T:
    """Execute one exact source-attested State Laws canonical commit.

    Canonical evidence is revalidated immediately before invoking the sealed
    executor. Arbitrary callbacks, callable aliases, partials, and subclasses
    are never granted protected-repository mutation authority.
    """

    _CanonicalPublicationRuntimeExecutable.assert_current()

    environ: dict[str, str] = {}
    phase = "unknown"
    try:
        req = (
            request
            if type(request) is CanonicalPublicationRequest
            else CanonicalPublicationRequest.from_mapping(request)
        )
        phase = req.phase
        environ = dict(req.environ or {})
        _, runtime_token = obtain_token(environ)
        req = replace(req, environ=MappingProxyType(environ))
    except PublicationGateError as exc:
        denied = _denied_decision(
            phase=phase,
            reason_code=f"runtime.{getattr(exc, 'code', 'publication_runtime_error')}",
            message=_safe_error_text(exc, _secret_values(environ)),
            environ=environ,
        )
        raise PublicationGateDeniedError(
            denied.message,
            reason_codes=denied.reason_codes,
            decision=denied,
        ) from exc
    mutation_start = datetime.now(timezone.utc)
    try:
        first = capture_canonical_snapshot(req, mutation_start=mutation_start)
        gate_request = build_gate_request(first)
        decision = evaluate_publication_gate(gate_request, environ=environ)
    except PublicationGateError as exc:
        denied = _denied_decision(
            phase=req.phase,
            reason_code=f"runtime.{getattr(exc, 'code', 'publication_runtime_error')}",
            message=_safe_error_text(exc, _secret_values(environ)),
            environ=environ,
        )
        raise PublicationGateDeniedError(
            denied.message,
            reason_codes=denied.reason_codes,
            decision=denied,
        ) from exc
    if not decision.authorized:
        raise PublicationGateDeniedError(
            decision.message or "canonical publication denied",
            reason_codes=decision.reason_codes,
            decision=decision,
        )
    try:
        second = capture_canonical_snapshot(req, mutation_start=mutation_start)
    except PublicationGateError as exc:
        race = _denied_decision(
            phase=req.phase,
            reason_code="runtime.evidence_race",
            message="canonical evidence changed between authorization and mutation",
            environ=environ,
            extra={"head_before": first.get("head")},
        )
        raise PublicationGateDeniedError(
            race.message,
            reason_codes=race.reason_codes,
            decision=race,
        ) from exc
    if _snapshot_fingerprint(first) != _snapshot_fingerprint(second):
        race = _denied_decision(
            phase=req.phase,
            reason_code="runtime.evidence_race",
            message="canonical evidence changed between authorization and mutation",
            environ=environ,
            extra={"head_before": first["head"], "head_after": second["head"]},
        )
        raise PublicationGateDeniedError(
            race.message,
            reason_codes=race.reason_codes,
            decision=race,
        )
    if req.phase not in CANONICAL_MUTATION_EXECUTOR_PHASES:
        raise PublicationRuntimeError(
            f"canonical phase {req.phase!r} has no sealed mutation executor and "
            "therefore fails closed"
        )
    executor_binding, prepare_method = _require_attested_mutation_executor(
        mutation_executor
    )
    _require_mutation_implementation_root(second["repository_root"])
    _require_exact_mutation_binding(req, second, executor_binding)
    details = dict(decision.details)
    details.update(
        {
            "runtime_task_id": TASK_ID,
            "head": first["head"],
            "principal": first["principal"],
            "principal_authority_digest": first[
                "principal_authority_digest"
            ],
            "operation": first["operation"],
            "snapshot_fingerprint": _snapshot_fingerprint(first),
            "candidate_release_manifest_digest": first.get(
                "candidate_release_manifest_digest"
            ),
            "expected_plan_digest": first.get("expected_plan_digest"),
            "expected_policy_proof_digest": first.get(
                "expected_policy_proof_digest"
            ),
            "expected_payload_digest": first.get(
                "expected_payload_digest"
            ),
            "revalidated_before_callback": True,
            "source_rights_binding_required": True,
            "source_rights_task_id": PREDECESSOR_RIGHTS_TASK_ID,
            "source_rights_receipt_digest": first["receipts"][RIGHTS_RECEIPT_RELPATH][
                "content_digest"
            ],
            "required_task_ids": list(
                phase_requirements(first["phase"])["required_task_ids"]
            ),
            "prepublication_seal_bound": first.get("prepublication_seal") is not None,
        }
    )
    bound = PublicationGateDecision(
        authorized=True,
        phase=decision.phase,
        operation=decision.operation,
        dataset_repo_id=decision.dataset_repo_id,
        final_manifest_digest=decision.final_manifest_digest,
        previous_public_pin=decision.previous_public_pin,
        reason_codes=(),
        passed_gates=decision.passed_gates,
        required_gates=REQUIRED_PUBLICATION_GATES,
        message=decision.message,
        details=details,
        network_mutation_permitted=True,
    )
    _assert_secret_free(bound.to_dict(), label="publication_runtime_decision", environ=environ)
    if not bound.network_mutation_permitted:
        raise PublicationGateDeniedError(
            "network mutation not permitted",
            reason_codes=("network_mutation.denied",),
            decision=bound,
        )
    prepared_executor = prepare_method(
        mutation_executor,
        bound,
        runtime_token,
    )
    prepared_call = _require_attested_prepared_executor(
        prepared_executor,
        expected_binding=executor_binding,
        expected_candidate_digest=bound.final_manifest_digest,
        runtime_token=runtime_token,
    )
    try:
        final_snapshot = capture_canonical_snapshot(
            req,
            mutation_start=mutation_start,
        )
    except PublicationGateError as exc:
        race = _denied_decision(
            phase=req.phase,
            reason_code="runtime.evidence_race",
            message="canonical evidence changed during sealed mutation preflight",
            environ=environ,
            extra={"head_before": second.get("head")},
        )
        raise PublicationGateDeniedError(
            race.message,
            reason_codes=race.reason_codes,
            decision=race,
        ) from exc
    if _snapshot_fingerprint(second) != _snapshot_fingerprint(final_snapshot):
        race = _denied_decision(
            phase=req.phase,
            reason_code="runtime.evidence_race",
            message="canonical evidence changed during sealed mutation preflight",
            environ=environ,
            extra={
                "head_before": second["head"],
                "head_after": final_snapshot["head"],
            },
        )
        raise PublicationGateDeniedError(
            race.message,
            reason_codes=race.reason_codes,
            decision=race,
        )
    _require_exact_mutation_binding(req, final_snapshot, executor_binding)
    final_executor_binding, final_prepare_method = (
        _require_attested_mutation_executor(mutation_executor)
    )
    final_prepared_call = _require_attested_prepared_executor(
        prepared_executor,
        expected_binding=executor_binding,
        expected_candidate_digest=bound.final_manifest_digest,
        runtime_token=runtime_token,
    )
    if (
        final_executor_binding != executor_binding
        or final_prepare_method is not prepare_method
        or final_prepared_call is not prepared_call
    ):
        raise PublicationRuntimeError(
            "sealed legal-corpora executor identity changed after final revalidation"
        )
    if final_snapshot["candidate_manifest"].get("schema") == (
        PRODUCTION_MANIFEST_SCHEMA_V2
    ):
        _validate_lcr084_production_candidate(
            Path(final_snapshot["repository_root"]),
            read_canonical_json(
                Path(final_snapshot["repository_root"]),
                STATE_CANDIDATE_MANIFEST_RELPATH,
            ),
            phase=req.phase,
            remeasure_production_evidence=True,
            runtime_token=runtime_token,
        )
    final_mutation_audit = _revalidate_mutation_inventory_before_callback(
        Path(final_snapshot["repository_root"]),
        expected_head=final_snapshot["head"],
    )
    if final_snapshot["candidate_manifest"].get("schema") == (
        PRODUCTION_MANIFEST_SCHEMA_V2
    ):
        candidate_audit = final_snapshot["candidate_manifest"].get(
            "mutation_audit"
        )
        _require_final_mutation_audit_binding(
            candidate_audit,
            final_mutation_audit,
        )
    _CanonicalPublicationRuntimeExecutable.assert_current()
    from ipfs_datasets_py.huggingface.protected_repo_guard import (
        _assert_canonical_runtime_authorization_consumed,
        _canonical_runtime_authorization,
    )

    with _canonical_runtime_authorization(
        repository_id=bound.dataset_repo_id,
        phase=bound.phase,
        operation=bound.operation,
        final_manifest_digest=bound.final_manifest_digest,
        mutation_binding=executor_binding,
        preflight_executor=mutation_executor,
        prepare_method=prepare_method,
        prepared_executor=prepared_executor,
        prepared_call=prepared_call,
        principal=final_snapshot["principal"],
        principal_authority_digest=final_snapshot[
            "principal_authority_digest"
        ],
        principal_probe=req.principal_probe,
        credential_identity=final_snapshot["credential_identity"],
        credentials_scope=final_snapshot["credentials_scope"],
        token_env=final_snapshot["token_env"],
    ) as authorization:
        result = prepared_call(prepared_executor)
        _assert_canonical_runtime_authorization_consumed(authorization)
        return result


class _CanonicalPublicationRuntimeExecutable:
    """Stable loaded-executable allowlist for the mutation-owning runtime."""

    EXECUTABLE_IMPORT_SHA256 = {}
    AUTHORIZE_AND_MUTATE_CODE = authorize_and_mutate_canonical.__code__

    @staticmethod
    def _code_projection(code):
        constants = []
        for item in code.co_consts:
            nested_code = getattr(item, "co_code", None)
            if nested_code is not None:
                constants.append(
                    {
                        "nested_code": (
                            _CanonicalPublicationRuntimeExecutable
                            ._code_projection(item)
                        )
                    }
                )
            else:
                constants.append({"literal": repr(item)})
        return {
            "co_code": list(code.co_code),
            "co_consts": constants,
            "co_flags": int(code.co_flags),
            "co_names": list(code.co_names),
            "co_nlocals": int(code.co_nlocals),
            "co_stacksize": int(code.co_stacksize),
            "co_varnames": list(code.co_varnames),
        }

    @staticmethod
    def _function_sha256(target):
        code = getattr(target, "__code__", None)
        if code is None:
            raise PublicationRuntimeError(
                "canonical runtime target is not a loaded function"
            )
        projection = {
            "code": _CanonicalPublicationRuntimeExecutable._code_projection(
                code
            ),
            "defaults": repr(getattr(target, "__defaults__", None)),
            "kwdefaults": repr(getattr(target, "__kwdefaults__", None)),
            "qualname": str(getattr(target, "__qualname__", target.__name__)),
        }
        return hashlib.sha256(
            json.dumps(
                projection,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @classmethod
    def current_executable_identities(cls):
        module = sys.modules[__name__]
        names = (
            "_authority_git_invocation",
            "_candidate_release_manifest_digest",
            "_discard_fresh_attested_verifier",
            "_isolated_descendant_identities",
            "_json_object_without_duplicate_keys",
            "_load_fresh_attested_verifier",
            "_isolated_lcr084_candidate_remeasurement",
            "_git",
            "_materialize_lcr084_source_snapshot",
            "_process_identity_table",
            "_production_candidate_report_digest",
            "_revalidate_mutation_inventory_before_callback",
            "_require_final_mutation_audit_binding",
            "_require_attested_mutation_executor",
            "_require_exact_mutation_binding",
            "_require_mutation_implementation_root",
            "_require_trusted_lcr084_snapshot_boundary",
            "_run_bounded_isolated_process",
            "_signal_process_identity",
            "_snapshot_fingerprint",
            "_terminate_isolated_process_tree",
            "_validate_lcr084_production_candidate",
            "_validate_lcr084_publication_chain",
            "_validated_native_phase_receipt",
            "_write_private_snapshot_file",
            "authorize_and_mutate_canonical",
            "build_gate_request",
            "capture_canonical_snapshot",
            "evaluate_publication_gate",
            "inspect_clean_head",
            "load_main_seal",
            "load_receipt",
            "read_canonical_json",
        )
        return {
            name: cls._function_sha256(getattr(module, name))
            for name in names
        }

    @classmethod
    def assert_current(cls):
        if cls.current_executable_identities() != dict(
            cls.EXECUTABLE_IMPORT_SHA256
        ):
            raise PublicationRuntimeError(
                "canonical runtime executable identity drifted"
            )


_CanonicalPublicationRuntimeExecutable.EXECUTABLE_IMPORT_SHA256 = MappingProxyType(
    _CanonicalPublicationRuntimeExecutable.current_executable_identities()
)

from ipfs_datasets_py.huggingface.protected_repo_guard import (
    _register_canonical_runtime_trust_anchor,
)

_register_canonical_runtime_trust_anchor(
    runtime_module=sys.modules[__name__],
    authorizer=authorize_and_mutate_canonical,
    runtime_executable=_CanonicalPublicationRuntimeExecutable,
)
del _register_canonical_runtime_trust_anchor


__all__ = [
    "ALLOWED_RECEIPT_SCHEMAS",
    "AUTHORITATIVE_OVERRIDE_KEYS",
    "CANONICAL_PATHS",
    "CANONICAL_MUTATION_EXECUTOR_PHASES",
    "GOAL_ID",
    "PREDECESSOR_GATE_TASK_ID",
    "PREDECESSOR_RIGHTS_TASK_ID",
    "PROGRAM_ID",
    "PRODUCER",
    "RUNTIME_SCHEMA",
    "SCHEMA_VERSION",
    "TASK_ID",
    "TOKEN_ENV_ALLOWLIST",
    "AlternateRepositoryError",
    "CanonicalPathOverrideError",
    "CanonicalPublicationRequest",
    "CallerCommitError",
    "CredentialTokenError",
    "DirtyAuthoritativePathError",
    "EvidenceRaceError",
    "IndependentDigestError",
    "ManifestBindingError",
    "PrincipalAuthorityError",
    "PublicationRuntimeError",
    "ReceiptSchemaError",
    "ReceiptStatusError",
    "SealTimeError",
    "authoritative_relpaths",
    "authorize_and_mutate_canonical",
    "build_gate_request",
    "canonical_no_self_field_digest",
    "capture_canonical_snapshot",
    "evaluate_canonical_publication",
    "inspect_clean_head",
    "load_release_policy",
    "load_task_lineage",
    "obtain_token",
    "parse_utc_z",
    "raw_file_digest",
    "require_canonical_publication",
    "verify_write_authority",
]
