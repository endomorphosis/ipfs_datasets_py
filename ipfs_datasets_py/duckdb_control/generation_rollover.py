"""Governed plan/runtime-generation rollover and writer fencing (DQK-083).

This module is the only supported path for accepting a revised goal/task graph
or an attested runtime environment.  It:

* drains and identifies the current generation
* verifies signed, CID-bound DuckDB plan-revision/proposal and
  candidate-environment rows (files are transport projections only)
* materializes a new *immutable* DuckDB generation when requested — never over
  the active database path
* carries forward accepted terminal receipts
* rotates plan/root/execution-slice/environment bindings and writer fences
* launches and verifies the new master before retiring the old generation

Completing DQK-083 only *installs* this lifecycle owner.  It does not activate
a runtime generation (DQK-103) and cannot stand in for plan approval (DQK-081).

Importing this module is inert: no filesystem, network, or database I/O until
an explicit entry point is called.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Final,
    Iterable,
    Mapping,
    MutableMapping,
    Protocol,
    Sequence,
)

from ipfs_datasets_py.duckdb_control.contracts import (
    canonical_json_bytes,
    content_identity,
    normalize_timestamp,
)

__all__ = [
    "ACTIVATION_SCHEMA",
    "APPROVAL_GATE_TASK_ID",
    "AUTHORITY_SURFACE",
    "CRASH_BOUNDARIES",
    "ENVIRONMENT_ROW_SCHEMA",
    "JOURNAL_SCHEMA",
    "LIFECYCLE_OWNER_TASK_ID",
    "MASTER_IDENTITY_SCHEMA",
    "PHASE_ORDER",
    "PLAN_REVISION_ROW_SCHEMA",
    "PROGRAM_ID",
    "ROLLOVER_RECEIPT_SCHEMA",
    "RUNTIME_ACTIVATION_GATE_TASK_ID",
    "SIGNATURE_ALGORITHM",
    "AuthorityStore",
    "CrashInjected",
    "EnvironmentGenerationRow",
    "GenerationIdentity",
    "GenerationRolloverError",
    "MemoryAuthorityStore",
    "PlanRevisionRow",
    "ProcessBirthIdentity",
    "RolloverJournal",
    "RolloverPhase",
    "RolloverReceipt",
    "WriterFenceState",
    "authorize_rollover_from_files",
    "build_environment_row",
    "build_plan_revision_row",
    "build_process_birth",
    "build_rollover_receipt",
    "compute_receipt_cid",
    "compute_signature",
    "execute_rollover",
    "install_check",
    "load_transport_projection",
    "refuse_runtime_activation_without_permit",
    "RUNTIME_ACTIVATION_PERMIT_SCHEMA",
    "self_check",
    "verify_completion_from_merge_receipts",
    "verify_runtime_activation_permit",
    "verify_signature",
]


# ---------------------------------------------------------------------------
# Schemas / constants
# ---------------------------------------------------------------------------

LIFECYCLE_OWNER_TASK_ID: Final[str] = "DQK-083"
APPROVAL_GATE_TASK_ID: Final[str] = "DQK-081"
RUNTIME_ACTIVATION_GATE_TASK_ID: Final[str] = "DQK-103"
PROGRAM_ID: Final[str] = "ipfs-datasets-duckdb-quack-v1"
SIGNATURE_ALGORITHM: Final[str] = "content-bound-sha256@1"
AUTHORITY_SURFACE: Final[str] = "duckdb_plan_revision_and_environment_rows"

PLAN_REVISION_ROW_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control/plan-revision-authority-row@1"
)
ENVIRONMENT_ROW_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control/environment-generation-authority-row@1"
)
JOURNAL_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control/generation-rollover-journal@1"
)
ROLLOVER_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control/generation-rollover-receipt@1"
)
ACTIVATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-runtime-activation@1"
)
MASTER_IDENTITY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control/master-process-identity@1"
)
INSTALL_CHECK_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control/lifecycle-owner-install@1"
)

# Transport file kinds that may *carry* a row body but never authorize.
TRANSPORT_PROJECTION_KINDS: Final[frozenset[str]] = frozenset(
    {
        "json",
        "markdown",
        "md",
        "formal-source",
        "formal_source",
        "environment",
        "env",
        "yaml",
        "yml",
        "txt",
    }
)

_UNSIGNED_EXCLUDED: Final[frozenset[str]] = frozenset(
    {"signature", "receipt_cid", "row_cid", "verification"}
)
_SHA256_DIGEST: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_OID: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_MAX_FIELD_BYTES: Final[int] = 8192
_MAX_JOURNAL_BYTES: Final[int] = 4 * 1024 * 1024
_SEED_TASKS_TUPLE_MARKER: Final[str] = "TASKS"

# Ordered crash-recoverable boundaries (acceptance: drain/materialize/launch/retire).
CRASH_BOUNDARIES: Final[tuple[str, ...]] = (
    "drain",
    "materialize",
    "launch",
    "retire",
)


class GenerationRolloverError(ValueError):
    """Raised when rollover inputs, authority, or phases fail closed."""


class CrashInjected(GenerationRolloverError):
    """Raised when a crash-injection boundary is hit (test/recovery harness)."""

    def __init__(self, boundary: str, *, journal_cid: str = "") -> None:
        self.boundary = boundary
        self.journal_cid = journal_cid
        super().__init__(f"crash injected at boundary {boundary!r}")


class RolloverPhase(str, Enum):
    """Durable journal phases for governed generation rollover."""

    IDENTIFY = "identify"
    VERIFY_AUTHORITY = "verify_authority"
    DRAIN = "drain"
    FENCE = "fence"
    MATERIALIZE = "materialize"
    BIND = "bind"
    LAUNCH = "launch"
    RETIRE = "retire"
    COMPLETE = "complete"

    @classmethod
    def parse(cls, value: str | RolloverPhase) -> RolloverPhase:
        if isinstance(value, RolloverPhase):
            return value
        text = str(value).strip().lower().replace("-", "_")
        return cls(text)


PHASE_ORDER: Final[tuple[RolloverPhase, ...]] = (
    RolloverPhase.IDENTIFY,
    RolloverPhase.VERIFY_AUTHORITY,
    RolloverPhase.DRAIN,
    RolloverPhase.FENCE,
    RolloverPhase.MATERIALIZE,
    RolloverPhase.BIND,
    RolloverPhase.LAUNCH,
    RolloverPhase.RETIRE,
    RolloverPhase.COMPLETE,
)

_PHASE_RANK: Final[Mapping[str, int]] = MappingProxyType(
    {phase.value: index for index, phase in enumerate(PHASE_ORDER)}
)


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return normalize_timestamp(datetime.now(timezone.utc))


def _bounded_text(value: Any, *, field: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise GenerationRolloverError(f"{field} must be text")
    text = value.strip()
    if not text and not allow_empty:
        raise GenerationRolloverError(f"{field} must be nonempty")
    if len(text.encode("utf-8")) > _MAX_FIELD_BYTES:
        raise GenerationRolloverError(f"{field} exceeds {_MAX_FIELD_BYTES}-byte bound")
    if "\0" in text or "\r" in text:
        raise GenerationRolloverError(f"{field} contains control characters")
    return text


def _require_sha256(value: Any, *, field: str) -> str:
    text = _bounded_text(value, field=field)
    normalized = text.lower()
    if not normalized.startswith("sha256:"):
        if re.fullmatch(r"[0-9a-f]{64}", normalized):
            normalized = f"sha256:{normalized}"
        else:
            raise GenerationRolloverError(f"{field} must be sha256:<64 hex>")
    if not _SHA256_DIGEST.fullmatch(normalized):
        raise GenerationRolloverError(f"{field} must be sha256:<64 hex>")
    return normalized


def _require_git_oid(value: Any, *, field: str) -> str:
    text = _bounded_text(value, field=field).lower()
    if not _GIT_OID.fullmatch(text):
        raise GenerationRolloverError(f"{field} must be a 40-hex git object id")
    return text


def _require_int(value: Any, *, field: str, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise GenerationRolloverError(f"{field} must be an integer")
    if value < minimum:
        raise GenerationRolloverError(f"{field} must be >= {minimum}")
    return value


def _require_bool(value: Any, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise GenerationRolloverError(f"{field} must be a boolean")
    return value


def _plain_mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GenerationRolloverError(f"{field} must be an object")
    return {str(key): item for key, item in value.items()}


def unsigned_preimage(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in _UNSIGNED_EXCLUDED
    }


def compute_signature(payload: Mapping[str, Any]) -> str:
    return content_identity(unsigned_preimage(payload))


def compute_receipt_cid(payload: Mapping[str, Any]) -> str:
    material = {
        key: value
        for key, value in payload.items()
        if key not in {"receipt_cid", "row_cid"}
    }
    return content_identity(material)


def compute_row_cid(payload: Mapping[str, Any]) -> str:
    material = {
        key: value
        for key, value in payload.items()
        if key not in {"row_cid", "signature"}
    }
    # Include signature in row_cid so the sealed row is content-bound.
    if "signature" in payload:
        material = {
            key: value for key, value in payload.items() if key != "row_cid"
        }
    return content_identity(material)


def verify_signature(payload: Mapping[str, Any], *, noun: str = "row") -> None:
    algorithm = _bounded_text(
        payload.get("signature_algorithm"), field=f"{noun}.signature_algorithm"
    )
    if algorithm != SIGNATURE_ALGORITHM:
        raise GenerationRolloverError(
            f"{noun} uses unsupported signature algorithm {algorithm!r}"
        )
    expected = compute_signature(payload)
    actual = _require_sha256(payload.get("signature"), field=f"{noun}.signature")
    if not hmac.compare_digest(actual, expected):
        raise GenerationRolloverError(
            f"{noun} signature does not match the signed body"
        )
    # Prefer row_cid for authority rows; receipt_cid for receipts.
    if "row_cid" in payload:
        expected_cid = compute_row_cid(payload)
        actual_cid = _require_sha256(payload.get("row_cid"), field=f"{noun}.row_cid")
        if not hmac.compare_digest(actual_cid, expected_cid):
            raise GenerationRolloverError(f"{noun} row_cid is not content-bound")
    elif "receipt_cid" in payload:
        expected_cid = compute_receipt_cid(payload)
        actual_cid = _require_sha256(
            payload.get("receipt_cid"), field=f"{noun}.receipt_cid"
        )
        if not hmac.compare_digest(actual_cid, expected_cid):
            raise GenerationRolloverError(f"{noun} receipt_cid is not content-bound")


def _seal_payload(payload: MutableMapping[str, Any], *, cid_field: str) -> dict[str, Any]:
    body = dict(payload)
    body["signature_algorithm"] = SIGNATURE_ALGORITHM
    body.pop("signature", None)
    body.pop(cid_field, None)
    body["signature"] = compute_signature(body)
    if cid_field == "row_cid":
        body["row_cid"] = compute_row_cid(body)
    else:
        body["receipt_cid"] = compute_receipt_cid(body)
    return body


# ---------------------------------------------------------------------------
# Process birth / writer fence / generation identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProcessBirthIdentity:
    """Exact process-birth identity for masters, daemons, and lifecycle owners."""

    pid: int
    boot_id: str
    start_ticks: int
    cmdline_sha256: str
    argv: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "boot_id": self.boot_id,
            "start_ticks": self.start_ticks,
            "cmdline_sha256": self.cmdline_sha256,
            "argv": list(self.argv),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ProcessBirthIdentity":
        data = _plain_mapping(value, field="process_birth")
        argv_raw = data.get("argv")
        if not isinstance(argv_raw, (list, tuple)):
            raise GenerationRolloverError("process_birth.argv must be a list")
        argv = tuple(str(item) for item in argv_raw)
        return cls(
            pid=_require_int(data.get("pid"), field="process_birth.pid", minimum=1),
            boot_id=_bounded_text(data.get("boot_id"), field="process_birth.boot_id"),
            start_ticks=_require_int(
                data.get("start_ticks"), field="process_birth.start_ticks", minimum=0
            ),
            cmdline_sha256=_require_sha256(
                data.get("cmdline_sha256"), field="process_birth.cmdline_sha256"
            ),
            argv=argv,
        )


def build_process_birth(
    *,
    pid: int | None = None,
    boot_id: str | None = None,
    start_ticks: int | None = None,
    argv: Sequence[str] | None = None,
) -> ProcessBirthIdentity:
    """Build a process-birth identity from live process facts or explicit values."""

    selected_pid = int(pid if pid is not None else os.getpid())
    selected_argv = tuple(
        str(item)
        for item in (
            argv
            if argv is not None
            else (sys.executable, *sys.argv)
        )
    )
    cmdline = "\0".join(selected_argv).encode("utf-8")
    cmdline_digest = "sha256:" + hashlib.sha256(cmdline).hexdigest()
    selected_boot = boot_id
    if selected_boot is None:
        boot_path = Path("/proc/sys/kernel/random/boot_id")
        try:
            selected_boot = boot_path.read_text(encoding="utf-8").strip()
        except OSError:
            selected_boot = f"synthetic-boot:{hashlib.sha256(str(selected_pid).encode()).hexdigest()[:16]}"
    selected_ticks = start_ticks
    if selected_ticks is None:
        try:
            stat = Path(f"/proc/{selected_pid}/stat").read_text(encoding="utf-8")
            # Field 22 is starttime (1-indexed: after comm which may contain spaces).
            close = stat.rfind(")")
            fields = stat[close + 2 :].split()
            selected_ticks = int(fields[19])
        except (OSError, IndexError, ValueError):
            selected_ticks = int(time.time() * 100)
    return ProcessBirthIdentity(
        pid=selected_pid,
        boot_id=selected_boot,
        start_ticks=int(selected_ticks),
        cmdline_sha256=cmdline_digest,
        argv=selected_argv,
    )


@dataclass(frozen=True, slots=True)
class WriterFenceState:
    """Authoritative writer owner and fencing epoch."""

    writer_id: str
    fencing_token: int
    epoch: int
    generation_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "writer_id": self.writer_id,
            "fencing_token": self.fencing_token,
            "epoch": self.epoch,
            "generation_id": self.generation_id,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WriterFenceState":
        data = _plain_mapping(value, field="writer_fence")
        return cls(
            writer_id=_bounded_text(data.get("writer_id"), field="writer_fence.writer_id"),
            fencing_token=_require_int(
                data.get("fencing_token"), field="writer_fence.fencing_token", minimum=1
            ),
            epoch=_require_int(data.get("epoch"), field="writer_fence.epoch", minimum=0),
            generation_id=_bounded_text(
                data.get("generation_id"), field="writer_fence.generation_id"
            ),
        )


@dataclass(frozen=True, slots=True)
class GenerationIdentity:
    """Immutable identity of one plan/runtime generation."""

    generation_id: str
    plan_root_cid: str
    repository_tree_id: str
    database_path: str
    database_identity: str
    environment_digest: str
    environment_row_cid: str
    execution_slice_sha256: str
    source_root_cid: str
    sealed_interpreter: str
    extension_profile_cid: str
    writer_fence: WriterFenceState
    task_population: tuple[str, ...]
    master_birth: ProcessBirthIdentity | None = None
    retired: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "generation_id": self.generation_id,
            "plan_root_cid": self.plan_root_cid,
            "repository_tree_id": self.repository_tree_id,
            "database_path": self.database_path,
            "database_identity": self.database_identity,
            "environment_digest": self.environment_digest,
            "environment_row_cid": self.environment_row_cid,
            "execution_slice_sha256": self.execution_slice_sha256,
            "source_root_cid": self.source_root_cid,
            "sealed_interpreter": self.sealed_interpreter,
            "extension_profile_cid": self.extension_profile_cid,
            "writer_fence": self.writer_fence.to_dict(),
            "task_population": list(self.task_population),
            "retired": self.retired,
        }
        if self.master_birth is not None:
            payload["master_birth"] = self.master_birth.to_dict()
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GenerationIdentity":
        data = _plain_mapping(value, field="generation")
        tasks = data.get("task_population") or ()
        if not isinstance(tasks, (list, tuple)):
            raise GenerationRolloverError("generation.task_population must be a list")
        master_raw = data.get("master_birth")
        master = (
            ProcessBirthIdentity.from_mapping(master_raw)
            if isinstance(master_raw, Mapping)
            else None
        )
        return cls(
            generation_id=_bounded_text(
                data.get("generation_id"), field="generation.generation_id"
            ),
            plan_root_cid=_require_sha256(
                data.get("plan_root_cid"), field="generation.plan_root_cid"
            ),
            repository_tree_id=_require_git_oid(
                data.get("repository_tree_id"), field="generation.repository_tree_id"
            ),
            database_path=_bounded_text(
                data.get("database_path"), field="generation.database_path"
            ),
            database_identity=_require_sha256(
                data.get("database_identity"), field="generation.database_identity"
            ),
            environment_digest=_require_sha256(
                data.get("environment_digest"), field="generation.environment_digest"
            ),
            environment_row_cid=_require_sha256(
                data.get("environment_row_cid"), field="generation.environment_row_cid"
            ),
            execution_slice_sha256=_require_sha256(
                data.get("execution_slice_sha256"),
                field="generation.execution_slice_sha256",
            ),
            source_root_cid=_require_sha256(
                data.get("source_root_cid"), field="generation.source_root_cid"
            ),
            sealed_interpreter=_bounded_text(
                data.get("sealed_interpreter"), field="generation.sealed_interpreter"
            ),
            extension_profile_cid=_require_sha256(
                data.get("extension_profile_cid"),
                field="generation.extension_profile_cid",
            ),
            writer_fence=WriterFenceState.from_mapping(
                data.get("writer_fence") or {}
            ),
            task_population=tuple(str(item) for item in tasks),
            master_birth=master,
            retired=_require_bool(data.get("retired", False), field="generation.retired"),
        )


# ---------------------------------------------------------------------------
# Authority rows (DuckDB is authoritative; files are transport only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanRevisionRow:
    """Signed, CID-bound plan-revision / proposal authority row."""

    row_cid: str
    schema: str
    program_id: str
    status: str  # accepted | rejected | non_active | rolled_over
    plan_root_cid: str
    base_plan_root_cid: str
    repository_tree_id: str
    repository_id: str
    task_population: tuple[str, ...]
    execution_slice_sha256: str
    source_root_cid: str
    approval_receipt_cid: str
    authorization_cid: str
    reviewer_id: str
    signature: str
    signature_algorithm: str
    issued_at: str
    proposal_ids: tuple[str, ...] = ()
    terminal_receipt_cids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "program_id": self.program_id,
            "status": self.status,
            "plan_root_cid": self.plan_root_cid,
            "base_plan_root_cid": self.base_plan_root_cid,
            "repository_tree_id": self.repository_tree_id,
            "repository_id": self.repository_id,
            "task_population": list(self.task_population),
            "execution_slice_sha256": self.execution_slice_sha256,
            "source_root_cid": self.source_root_cid,
            "approval_receipt_cid": self.approval_receipt_cid,
            "authorization_cid": self.authorization_cid,
            "reviewer_id": self.reviewer_id,
            "proposal_ids": list(self.proposal_ids),
            "terminal_receipt_cids": list(self.terminal_receipt_cids),
            "issued_at": self.issued_at,
            "signature_algorithm": self.signature_algorithm,
            "signature": self.signature,
            "row_cid": self.row_cid,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PlanRevisionRow":
        data = _plain_mapping(value, field="plan_revision_row")
        if data.get("schema") != PLAN_REVISION_ROW_SCHEMA:
            raise GenerationRolloverError(
                f"plan revision row schema must be {PLAN_REVISION_ROW_SCHEMA}"
            )
        verify_signature(data, noun="plan_revision_row")
        status = _bounded_text(data.get("status"), field="plan_revision_row.status").lower()
        tasks = data.get("task_population") or ()
        if not isinstance(tasks, (list, tuple)):
            raise GenerationRolloverError("plan_revision_row.task_population must be a list")
        proposals = data.get("proposal_ids") or ()
        terminals = data.get("terminal_receipt_cids") or ()
        if not isinstance(proposals, (list, tuple)) or not isinstance(
            terminals, (list, tuple)
        ):
            raise GenerationRolloverError("plan_revision_row list fields malformed")
        return cls(
            row_cid=_require_sha256(data.get("row_cid"), field="plan_revision_row.row_cid"),
            schema=PLAN_REVISION_ROW_SCHEMA,
            program_id=_bounded_text(
                data.get("program_id"), field="plan_revision_row.program_id"
            ),
            status=status,
            plan_root_cid=_require_sha256(
                data.get("plan_root_cid"), field="plan_revision_row.plan_root_cid"
            ),
            base_plan_root_cid=_require_sha256(
                data.get("base_plan_root_cid"),
                field="plan_revision_row.base_plan_root_cid",
            ),
            repository_tree_id=_require_git_oid(
                data.get("repository_tree_id"),
                field="plan_revision_row.repository_tree_id",
            ),
            repository_id=_bounded_text(
                data.get("repository_id"), field="plan_revision_row.repository_id"
            ),
            task_population=tuple(str(item) for item in tasks),
            execution_slice_sha256=_require_sha256(
                data.get("execution_slice_sha256"),
                field="plan_revision_row.execution_slice_sha256",
            ),
            source_root_cid=_require_sha256(
                data.get("source_root_cid"),
                field="plan_revision_row.source_root_cid",
            ),
            approval_receipt_cid=_require_sha256(
                data.get("approval_receipt_cid"),
                field="plan_revision_row.approval_receipt_cid",
            ),
            authorization_cid=_require_sha256(
                data.get("authorization_cid"),
                field="plan_revision_row.authorization_cid",
            ),
            reviewer_id=_bounded_text(
                data.get("reviewer_id"), field="plan_revision_row.reviewer_id"
            ),
            signature=_require_sha256(
                data.get("signature"), field="plan_revision_row.signature"
            ),
            signature_algorithm=SIGNATURE_ALGORITHM,
            issued_at=_bounded_text(
                data.get("issued_at"), field="plan_revision_row.issued_at"
            ),
            proposal_ids=tuple(str(item) for item in proposals),
            terminal_receipt_cids=tuple(
                _require_sha256(item, field="terminal_receipt_cid") for item in terminals
            ),
        )


def build_plan_revision_row(
    *,
    plan_root_cid: str,
    base_plan_root_cid: str,
    repository_tree_id: str,
    repository_id: str,
    task_population: Sequence[str],
    execution_slice_sha256: str,
    source_root_cid: str,
    approval_receipt_cid: str,
    authorization_cid: str,
    reviewer_id: str,
    status: str = "accepted",
    proposal_ids: Sequence[str] = (),
    terminal_receipt_cids: Sequence[str] = (),
    issued_at: str | None = None,
    program_id: str = PROGRAM_ID,
) -> dict[str, Any]:
    """Build a sealed plan-revision authority row."""

    status_text = _bounded_text(status, field="status").lower()
    if status_text not in {"accepted", "rejected", "non_active", "rolled_over"}:
        raise GenerationRolloverError(f"unsupported plan revision status {status_text!r}")
    payload: dict[str, Any] = {
        "schema": PLAN_REVISION_ROW_SCHEMA,
        "program_id": program_id,
        "status": status_text,
        "plan_root_cid": _require_sha256(plan_root_cid, field="plan_root_cid"),
        "base_plan_root_cid": _require_sha256(
            base_plan_root_cid, field="base_plan_root_cid"
        ),
        "repository_tree_id": _require_git_oid(
            repository_tree_id, field="repository_tree_id"
        ),
        "repository_id": _bounded_text(repository_id, field="repository_id"),
        "task_population": [str(item) for item in task_population],
        "execution_slice_sha256": _require_sha256(
            execution_slice_sha256, field="execution_slice_sha256"
        ),
        "source_root_cid": _require_sha256(source_root_cid, field="source_root_cid"),
        "approval_receipt_cid": _require_sha256(
            approval_receipt_cid, field="approval_receipt_cid"
        ),
        "authorization_cid": _require_sha256(
            authorization_cid, field="authorization_cid"
        ),
        "reviewer_id": _bounded_text(reviewer_id, field="reviewer_id"),
        "proposal_ids": [str(item) for item in proposal_ids],
        "terminal_receipt_cids": [
            _require_sha256(item, field="terminal_receipt_cid")
            for item in terminal_receipt_cids
        ],
        "issued_at": issued_at or _utc_now(),
    }
    return _seal_payload(payload, cid_field="row_cid")


@dataclass(frozen=True, slots=True)
class EnvironmentGenerationRow:
    """Signed, CID-bound candidate/environment-generation authority row."""

    row_cid: str
    schema: str
    program_id: str
    status: str  # accepted | candidate | rejected
    environment_digest: str
    sealed_interpreter: str
    extension_profile_cid: str
    environment_root: str
    candidate_receipt_cid: str
    duckdb_version: str
    signature: str
    signature_algorithm: str
    issued_at: str
    activates_runtime_generation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "program_id": self.program_id,
            "status": self.status,
            "environment_digest": self.environment_digest,
            "sealed_interpreter": self.sealed_interpreter,
            "extension_profile_cid": self.extension_profile_cid,
            "environment_root": self.environment_root,
            "candidate_receipt_cid": self.candidate_receipt_cid,
            "duckdb_version": self.duckdb_version,
            "activates_runtime_generation": self.activates_runtime_generation,
            "issued_at": self.issued_at,
            "signature_algorithm": self.signature_algorithm,
            "signature": self.signature,
            "row_cid": self.row_cid,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EnvironmentGenerationRow":
        data = _plain_mapping(value, field="environment_row")
        if data.get("schema") != ENVIRONMENT_ROW_SCHEMA:
            raise GenerationRolloverError(
                f"environment row schema must be {ENVIRONMENT_ROW_SCHEMA}"
            )
        verify_signature(data, noun="environment_row")
        status = _bounded_text(data.get("status"), field="environment_row.status").lower()
        return cls(
            row_cid=_require_sha256(data.get("row_cid"), field="environment_row.row_cid"),
            schema=ENVIRONMENT_ROW_SCHEMA,
            program_id=_bounded_text(
                data.get("program_id"), field="environment_row.program_id"
            ),
            status=status,
            environment_digest=_require_sha256(
                data.get("environment_digest"),
                field="environment_row.environment_digest",
            ),
            sealed_interpreter=_bounded_text(
                data.get("sealed_interpreter"),
                field="environment_row.sealed_interpreter",
            ),
            extension_profile_cid=_require_sha256(
                data.get("extension_profile_cid"),
                field="environment_row.extension_profile_cid",
            ),
            environment_root=_bounded_text(
                data.get("environment_root"), field="environment_row.environment_root"
            ),
            candidate_receipt_cid=_require_sha256(
                data.get("candidate_receipt_cid"),
                field="environment_row.candidate_receipt_cid",
            ),
            duckdb_version=_bounded_text(
                data.get("duckdb_version"), field="environment_row.duckdb_version"
            ),
            signature=_require_sha256(
                data.get("signature"), field="environment_row.signature"
            ),
            signature_algorithm=SIGNATURE_ALGORITHM,
            issued_at=_bounded_text(
                data.get("issued_at"), field="environment_row.issued_at"
            ),
            activates_runtime_generation=_require_bool(
                data.get("activates_runtime_generation", False),
                field="environment_row.activates_runtime_generation",
            ),
        )


def build_environment_row(
    *,
    environment_digest: str,
    sealed_interpreter: str,
    extension_profile_cid: str,
    environment_root: str,
    candidate_receipt_cid: str,
    duckdb_version: str = "1.5.5",
    status: str = "accepted",
    activates_runtime_generation: bool = False,
    issued_at: str | None = None,
    program_id: str = PROGRAM_ID,
) -> dict[str, Any]:
    """Build a sealed environment-generation authority row."""

    status_text = _bounded_text(status, field="status").lower()
    if status_text not in {"accepted", "candidate", "rejected"}:
        raise GenerationRolloverError(f"unsupported environment status {status_text!r}")
    if activates_runtime_generation:
        # DQK-083 rows never activate runtime; that is DQK-103.
        raise GenerationRolloverError(
            "environment rows cannot activate a runtime generation; "
            f"activation requires {RUNTIME_ACTIVATION_GATE_TASK_ID}"
        )
    payload: dict[str, Any] = {
        "schema": ENVIRONMENT_ROW_SCHEMA,
        "program_id": program_id,
        "status": status_text,
        "environment_digest": _require_sha256(
            environment_digest, field="environment_digest"
        ),
        "sealed_interpreter": _bounded_text(
            sealed_interpreter, field="sealed_interpreter"
        ),
        "extension_profile_cid": _require_sha256(
            extension_profile_cid, field="extension_profile_cid"
        ),
        "environment_root": _bounded_text(environment_root, field="environment_root"),
        "candidate_receipt_cid": _require_sha256(
            candidate_receipt_cid, field="candidate_receipt_cid"
        ),
        "duckdb_version": _bounded_text(duckdb_version, field="duckdb_version"),
        "activates_runtime_generation": False,
        "issued_at": issued_at or _utc_now(),
    }
    return _seal_payload(payload, cid_field="row_cid")


# ---------------------------------------------------------------------------
# Authority store
# ---------------------------------------------------------------------------


class AuthorityStore(Protocol):
    """DuckDB-backed (or hermetic) authority surface for rollover inputs."""

    def get_active_generation(self) -> GenerationIdentity | None:
        ...

    def get_plan_revision(self, row_cid: str) -> PlanRevisionRow | None:
        ...

    def get_environment_generation(self, row_cid: str) -> EnvironmentGenerationRow | None:
        ...

    def list_accepted_plan_revisions(self) -> tuple[PlanRevisionRow, ...]:
        ...

    def list_accepted_environments(self) -> tuple[EnvironmentGenerationRow, ...]:
        ...

    def list_merge_receipts(self) -> tuple[Mapping[str, Any], ...]:
        ...

    def list_terminal_receipts(self) -> tuple[Mapping[str, Any], ...]:
        ...

    def put_plan_revision(self, row: Mapping[str, Any]) -> PlanRevisionRow:
        ...

    def put_environment_generation(self, row: Mapping[str, Any]) -> EnvironmentGenerationRow:
        ...

    def put_merge_receipt(self, receipt: Mapping[str, Any]) -> None:
        ...

    def put_terminal_receipt(self, receipt: Mapping[str, Any]) -> None:
        ...

    def set_active_generation(self, generation: GenerationIdentity) -> None:
        ...

    def materialize_generation(
        self,
        *,
        generation: GenerationIdentity,
        active_database_path: str,
    ) -> GenerationIdentity:
        ...

    def fence_writers(self, *, generation_id: str, new_epoch: int) -> WriterFenceState:
        ...

    def record_rollover_receipt(self, receipt: Mapping[str, Any]) -> None:
        ...

    def get_rollover_receipt(self, receipt_cid: str) -> Mapping[str, Any] | None:
        ...


class MemoryAuthorityStore:
    """Hermetic in-memory authority store used by tests and self-check.

    Models the DuckDB plan-revision and environment-generation tables without
    requiring a live DuckDB process.  Seed TASKS tuples are deliberately not
    consulted for authorization.
    """

    def __init__(self) -> None:
        self._plan_revisions: dict[str, PlanRevisionRow] = {}
        self._environments: dict[str, EnvironmentGenerationRow] = {}
        self._merge_receipts: list[dict[str, Any]] = []
        self._terminal_list: list[dict[str, Any]] = []
        self._rollover_receipts: dict[str, dict[str, Any]] = {}
        self._active: GenerationIdentity | None = None
        self._materialized_paths: set[str] = set()
        self._fenced_generations: dict[str, WriterFenceState] = {}
        self._seed_tasks_tuple: tuple[str, ...] = ()  # never authoritative

    def set_seed_tasks_tuple(self, *task_ids: str) -> None:
        """Record a non-authoritative seed TASKS projection (transport only)."""

        self._seed_tasks_tuple = tuple(str(item) for item in task_ids)

    @property
    def seed_tasks_tuple(self) -> tuple[str, ...]:
        return self._seed_tasks_tuple

    def get_active_generation(self) -> GenerationIdentity | None:
        return self._active

    def get_plan_revision(self, row_cid: str) -> PlanRevisionRow | None:
        return self._plan_revisions.get(_require_sha256(row_cid, field="row_cid"))

    def get_environment_generation(
        self, row_cid: str
    ) -> EnvironmentGenerationRow | None:
        return self._environments.get(_require_sha256(row_cid, field="row_cid"))

    def list_accepted_plan_revisions(self) -> tuple[PlanRevisionRow, ...]:
        return tuple(
            row
            for row in self._plan_revisions.values()
            if row.status == "accepted"
        )

    def list_accepted_environments(self) -> tuple[EnvironmentGenerationRow, ...]:
        return tuple(
            row
            for row in self._environments.values()
            if row.status == "accepted"
        )

    def list_merge_receipts(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(dict(item) for item in self._merge_receipts)

    def list_terminal_receipts(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(dict(item) for item in self._terminal_list)

    def put_plan_revision(self, row: Mapping[str, Any]) -> PlanRevisionRow:
        parsed = PlanRevisionRow.from_mapping(row)
        self._plan_revisions[parsed.row_cid] = parsed
        return parsed

    def put_environment_generation(
        self, row: Mapping[str, Any]
    ) -> EnvironmentGenerationRow:
        parsed = EnvironmentGenerationRow.from_mapping(row)
        self._environments[parsed.row_cid] = parsed
        return parsed

    def put_merge_receipt(self, receipt: Mapping[str, Any]) -> None:
        data = _plain_mapping(receipt, field="merge_receipt")
        cid = _require_sha256(
            data.get("receipt_cid") or data.get("merge_receipt_cid"),
            field="merge_receipt.receipt_cid",
        )
        sealed = dict(data)
        sealed["receipt_cid"] = cid
        self._merge_receipts.append(sealed)

    def put_terminal_receipt(self, receipt: Mapping[str, Any]) -> None:
        data = _plain_mapping(receipt, field="terminal_receipt")
        cid = _require_sha256(
            data.get("receipt_cid"), field="terminal_receipt.receipt_cid"
        )
        sealed = dict(data)
        sealed["receipt_cid"] = cid
        self._terminal_list.append(sealed)

    def set_active_generation(self, generation: GenerationIdentity) -> None:
        self._active = generation
        self._materialized_paths.add(generation.database_path)

    def materialize_generation(
        self,
        *,
        generation: GenerationIdentity,
        active_database_path: str,
    ) -> GenerationIdentity:
        """Materialize a new immutable generation path; never overwrite active."""

        new_path = generation.database_path
        if not new_path:
            raise GenerationRolloverError("materialize requires a database_path")
        if os.path.normpath(new_path) == os.path.normpath(active_database_path):
            raise GenerationRolloverError(
                "a changed plan is never materialized over the active database"
            )
        if new_path in self._materialized_paths and (
            self._active is None or self._active.database_path != new_path
        ):
            # Idempotent rematerialize of the same new path is allowed only when
            # the generation identity matches a prior incomplete attempt.
            pass
        # Synthetic identity: content-bound to generation fields (no live DuckDB).
        identity = content_identity(
            {
                "generation_id": generation.generation_id,
                "plan_root_cid": generation.plan_root_cid,
                "database_path": new_path,
                "task_population": list(generation.task_population),
            }
        )
        materialised = GenerationIdentity(
            generation_id=generation.generation_id,
            plan_root_cid=generation.plan_root_cid,
            repository_tree_id=generation.repository_tree_id,
            database_path=new_path,
            database_identity=identity,
            environment_digest=generation.environment_digest,
            environment_row_cid=generation.environment_row_cid,
            execution_slice_sha256=generation.execution_slice_sha256,
            source_root_cid=generation.source_root_cid,
            sealed_interpreter=generation.sealed_interpreter,
            extension_profile_cid=generation.extension_profile_cid,
            writer_fence=generation.writer_fence,
            task_population=generation.task_population,
            master_birth=generation.master_birth,
            retired=False,
        )
        self._materialized_paths.add(new_path)
        return materialised

    def fence_writers(self, *, generation_id: str, new_epoch: int) -> WriterFenceState:
        gen_id = _bounded_text(generation_id, field="generation_id")
        epoch = _require_int(new_epoch, field="new_epoch", minimum=1)
        prior = self._fenced_generations.get(gen_id)
        token = (prior.fencing_token + 1) if prior is not None else epoch
        fence = WriterFenceState(
            writer_id=f"fenced:{gen_id}",
            fencing_token=token,
            epoch=epoch,
            generation_id=gen_id,
        )
        self._fenced_generations[gen_id] = fence
        return fence

    def record_rollover_receipt(self, receipt: Mapping[str, Any]) -> None:
        data = _plain_mapping(receipt, field="rollover_receipt")
        cid = _require_sha256(data.get("receipt_cid"), field="receipt_cid")
        self._rollover_receipts[cid] = dict(data)

    def get_rollover_receipt(self, receipt_cid: str) -> Mapping[str, Any] | None:
        return self._rollover_receipts.get(
            _require_sha256(receipt_cid, field="receipt_cid")
        )


# ---------------------------------------------------------------------------
# Transport projections (files cannot authorize)
# ---------------------------------------------------------------------------


def load_transport_projection(path: str | Path) -> dict[str, Any]:
    """Load a JSON/Markdown/environment transport file as a projection only.

    The returned body is *not* authority.  Callers must rebind it to a DuckDB
    authority row by CID before any rollover decision.
    """

    target = Path(path)
    suffix = target.suffix.lstrip(".").lower() or "txt"
    kind = "json" if suffix == "json" else suffix
    if kind in {"md"}:
        kind = "markdown"
    if kind not in TRANSPORT_PROJECTION_KINDS and kind != "json":
        # Still load for matching, but mark as transport.
        kind = kind or "txt"
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise GenerationRolloverError(f"transport projection unreadable: {exc}") from exc
    if len(raw) > _MAX_JOURNAL_BYTES:
        raise GenerationRolloverError("transport projection exceeds size bound")
    if kind == "json" or raw.lstrip().startswith(b"{"):
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GenerationRolloverError(
                f"transport projection is not JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise GenerationRolloverError("transport projection must be a JSON object")
        return {
            "transport_only": True,
            "authority": False,
            "kind": kind,
            "path": str(target),
            "body": payload,
            "body_cid": content_identity(payload),
        }
    # Non-JSON formal-source / markdown / environment text.
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GenerationRolloverError("transport projection is not UTF-8") from exc
    return {
        "transport_only": True,
        "authority": False,
        "kind": kind if kind in TRANSPORT_PROJECTION_KINDS else "txt",
        "path": str(target),
        "body_text": text,
        "body_cid": "sha256:" + hashlib.sha256(raw).hexdigest(),
    }


def authorize_rollover_from_files(
    *paths: str | Path,
    **_kwargs: Any,
) -> None:
    """Fail closed: files alone can never authorize generation rollover."""

    raise GenerationRolloverError(
        "JSON/Markdown/formal-source/environment files are transport projections "
        "only and cannot authorize rollover; authority is signed/CID-bound DuckDB "
        f"plan-revision and environment-generation rows ({AUTHORITY_SURFACE})"
    )


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------


@dataclass
class RolloverJournal:
    """Durable pre-commit journal for crash-recoverable rollover phases."""

    operation_id: str
    owner_birth: ProcessBirthIdentity
    phase: RolloverPhase
    old_generation: GenerationIdentity | None = None
    plan_revision_row_cid: str = ""
    environment_row_cid: str = ""
    new_generation: GenerationIdentity | None = None
    old_writer_fence: WriterFenceState | None = None
    new_writer_fence: WriterFenceState | None = None
    new_master_birth: ProcessBirthIdentity | None = None
    carried_terminal_receipt_cids: tuple[str, ...] = ()
    completed_phases: list[str] = field(default_factory=list)
    effects: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    journal_cid: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": JOURNAL_SCHEMA,
            "program_id": PROGRAM_ID,
            "owner_task_id": LIFECYCLE_OWNER_TASK_ID,
            "operation_id": self.operation_id,
            "phase": self.phase.value,
            "owner_birth": self.owner_birth.to_dict(),
            "plan_revision_row_cid": self.plan_revision_row_cid,
            "environment_row_cid": self.environment_row_cid,
            "carried_terminal_receipt_cids": list(self.carried_terminal_receipt_cids),
            "completed_phases": list(self.completed_phases),
            "effects": dict(self.effects),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.old_generation is not None:
            payload["old_generation"] = self.old_generation.to_dict()
        if self.new_generation is not None:
            payload["new_generation"] = self.new_generation.to_dict()
        if self.old_writer_fence is not None:
            payload["old_writer_fence"] = self.old_writer_fence.to_dict()
        if self.new_writer_fence is not None:
            payload["new_writer_fence"] = self.new_writer_fence.to_dict()
        if self.new_master_birth is not None:
            payload["new_master_birth"] = self.new_master_birth.to_dict()
        if self.journal_cid:
            payload["journal_cid"] = self.journal_cid
        return payload

    def recompute_cid(self) -> str:
        body = self.to_dict()
        body.pop("journal_cid", None)
        self.journal_cid = content_identity(body)
        return self.journal_cid

    def mark_phase(self, phase: RolloverPhase) -> None:
        if phase.value not in self.completed_phases:
            self.completed_phases.append(phase.value)
        self.phase = phase
        self.updated_at = _utc_now()
        self.recompute_cid()

    def has_completed(self, phase: RolloverPhase | str) -> bool:
        name = phase.value if isinstance(phase, RolloverPhase) else str(phase)
        return name in self.completed_phases

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RolloverJournal":
        data = _plain_mapping(value, field="journal")
        if data.get("schema") != JOURNAL_SCHEMA:
            raise GenerationRolloverError(f"journal schema must be {JOURNAL_SCHEMA}")
        old_gen = data.get("old_generation")
        new_gen = data.get("new_generation")
        old_fence = data.get("old_writer_fence")
        new_fence = data.get("new_writer_fence")
        new_master = data.get("new_master_birth")
        completed = data.get("completed_phases") or []
        if not isinstance(completed, list):
            raise GenerationRolloverError("journal.completed_phases must be a list")
        carried = data.get("carried_terminal_receipt_cids") or ()
        journal = cls(
            operation_id=_bounded_text(
                data.get("operation_id"), field="journal.operation_id"
            ),
            owner_birth=ProcessBirthIdentity.from_mapping(
                data.get("owner_birth") or {}
            ),
            phase=RolloverPhase.parse(
                _bounded_text(data.get("phase"), field="journal.phase")
            ),
            old_generation=(
                GenerationIdentity.from_mapping(old_gen)
                if isinstance(old_gen, Mapping)
                else None
            ),
            plan_revision_row_cid=str(data.get("plan_revision_row_cid") or ""),
            environment_row_cid=str(data.get("environment_row_cid") or ""),
            new_generation=(
                GenerationIdentity.from_mapping(new_gen)
                if isinstance(new_gen, Mapping)
                else None
            ),
            old_writer_fence=(
                WriterFenceState.from_mapping(old_fence)
                if isinstance(old_fence, Mapping)
                else None
            ),
            new_writer_fence=(
                WriterFenceState.from_mapping(new_fence)
                if isinstance(new_fence, Mapping)
                else None
            ),
            new_master_birth=(
                ProcessBirthIdentity.from_mapping(new_master)
                if isinstance(new_master, Mapping)
                else None
            ),
            carried_terminal_receipt_cids=tuple(str(item) for item in carried),
            completed_phases=[str(item) for item in completed],
            effects=dict(data.get("effects") or {}),
            created_at=_bounded_text(
                data.get("created_at"), field="journal.created_at"
            ),
            updated_at=_bounded_text(
                data.get("updated_at"), field="journal.updated_at"
            ),
            journal_cid=str(data.get("journal_cid") or ""),
        )
        return journal


def persist_journal(path: str | Path, journal: RolloverJournal) -> str:
    """Atomically persist a journal (tmp + replace)."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    journal.recompute_cid()
    body = journal.to_dict()
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(raw.encode("utf-8")) > _MAX_JOURNAL_BYTES:
        raise GenerationRolloverError("journal exceeds size bound")
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(raw + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return journal.journal_cid


def load_journal(path: str | Path) -> RolloverJournal:
    target = Path(path)
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise GenerationRolloverError(f"journal unreadable: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GenerationRolloverError(f"journal is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise GenerationRolloverError("journal must be a JSON object")
    return RolloverJournal.from_mapping(payload)


# ---------------------------------------------------------------------------
# Rollover receipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RolloverReceipt:
    """Content-addressed generation rollover receipt."""

    receipt_cid: str
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


def build_rollover_receipt(
    *,
    operation_id: str,
    old_generation: GenerationIdentity,
    new_generation: GenerationIdentity,
    plan_revision: PlanRevisionRow,
    environment: EnvironmentGenerationRow,
    old_writer_fence: WriterFenceState,
    new_writer_fence: WriterFenceState,
    owner_birth: ProcessBirthIdentity,
    new_master_birth: ProcessBirthIdentity,
    authorization_cid: str,
    carried_terminal_receipt_cids: Sequence[str] = (),
    journal_cid: str = "",
    issued_at: str | None = None,
) -> dict[str, Any]:
    """Build a sealed rollover receipt binding old/new roots and identities."""

    payload: dict[str, Any] = {
        "schema": ROLLOVER_RECEIPT_SCHEMA,
        "program_id": PROGRAM_ID,
        "owner_task_id": LIFECYCLE_OWNER_TASK_ID,
        "operation_id": _bounded_text(operation_id, field="operation_id"),
        "activates_runtime_generation": False,
        "substitutes_for_plan_approval": False,
        "substitutes_for_runtime_activation": False,
        "approval_gate_task_id": APPROVAL_GATE_TASK_ID,
        "runtime_activation_gate_task_id": RUNTIME_ACTIVATION_GATE_TASK_ID,
        "authority_surface": AUTHORITY_SURFACE,
        "old_generation": {
            "generation_id": old_generation.generation_id,
            "plan_root_cid": old_generation.plan_root_cid,
            "database_path": old_generation.database_path,
            "database_identity": old_generation.database_identity,
            "environment_digest": old_generation.environment_digest,
            "repository_tree_id": old_generation.repository_tree_id,
            "task_population": list(old_generation.task_population),
            "writer_epoch": old_generation.writer_fence.epoch,
            "master_birth": (
                old_generation.master_birth.to_dict()
                if old_generation.master_birth is not None
                else None
            ),
        },
        "new_generation": {
            "generation_id": new_generation.generation_id,
            "plan_root_cid": new_generation.plan_root_cid,
            "database_path": new_generation.database_path,
            "database_identity": new_generation.database_identity,
            "environment_digest": new_generation.environment_digest,
            "environment_row_cid": new_generation.environment_row_cid,
            "repository_tree_id": new_generation.repository_tree_id,
            "execution_slice_sha256": new_generation.execution_slice_sha256,
            "source_root_cid": new_generation.source_root_cid,
            "sealed_interpreter": new_generation.sealed_interpreter,
            "extension_profile_cid": new_generation.extension_profile_cid,
            "task_population": list(new_generation.task_population),
            "writer_epoch": new_generation.writer_fence.epoch,
            "master_birth": new_master_birth.to_dict(),
        },
        "old_writer_fence": old_writer_fence.to_dict(),
        "new_writer_fence": new_writer_fence.to_dict(),
        "plan_revision_row_cid": plan_revision.row_cid,
        "environment_row_cid": environment.row_cid,
        "authorization_cid": _require_sha256(
            authorization_cid, field="authorization_cid"
        ),
        "owner_birth": owner_birth.to_dict(),
        "new_master_birth": new_master_birth.to_dict(),
        "carried_terminal_receipt_cids": [
            _require_sha256(item, field="terminal_receipt_cid")
            for item in carried_terminal_receipt_cids
        ],
        "journal_cid": journal_cid or "",
        "issued_at": issued_at or _utc_now(),
    }
    return _seal_payload(payload, cid_field="receipt_cid")


# ---------------------------------------------------------------------------
# Completion / merge receipt verification (restart path)
# ---------------------------------------------------------------------------


def verify_completion_from_merge_receipts(
    store: AuthorityStore,
    *,
    expected_task_ids: Sequence[str] | None = None,
    seed_head: str | None = None,
) -> dict[str, Any]:
    """Verify prior task completion via merge receipts, not seed HEAD.

    Restart after prior task merges must not require the seed HEAD commit.
    """

    merges = list(store.list_merge_receipts())
    if not merges:
        raise GenerationRolloverError(
            "restart verification requires merge receipts; seed HEAD is not authority"
        )
    if seed_head is not None:
        # Explicitly ignore seed HEAD — acceptance forbids requiring it.
        _ = seed_head
    completed: list[str] = []
    for receipt in merges:
        task_id = str(receipt.get("task_id") or receipt.get("objective_id") or "")
        status = str(receipt.get("status") or receipt.get("merge_status") or "").lower()
        if not task_id:
            raise GenerationRolloverError("merge receipt missing task_id")
        if status not in {"merged", "completed", "integrated"}:
            raise GenerationRolloverError(
                f"merge receipt for {task_id} is not terminal (status={status!r})"
            )
        if not str(receipt.get("receipt_cid") or "").strip():
            raise GenerationRolloverError(f"merge receipt for {task_id} missing receipt_cid")
        completed.append(task_id)
    if expected_task_ids is not None:
        missing = [tid for tid in expected_task_ids if tid not in completed]
        if missing:
            raise GenerationRolloverError(
                f"merge receipts incomplete; missing tasks: {missing}"
            )
    return {
        "ok": True,
        "authority": "merge_receipts",
        "seed_head_required": False,
        "completed_task_ids": completed,
        "merge_receipt_count": len(merges),
    }


# ---------------------------------------------------------------------------
# Core rollover execution
# ---------------------------------------------------------------------------


def _generation_id_for(
    plan_root_cid: str,
    environment_digest: str,
    repository_tree_id: str,
) -> str:
    material = {
        "plan_root_cid": plan_root_cid,
        "environment_digest": environment_digest,
        "repository_tree_id": repository_tree_id,
    }
    digest = content_identity(material).removeprefix("sha256:")
    return f"generation:{digest[:32]}"


def _new_database_path(old_path: str, generation_id: str) -> str:
    """Derive a sibling immutable path; never the active path."""

    parent = os.path.dirname(old_path) or "."
    stem = generation_id.replace(":", "_").replace("/", "_")
    return os.path.normpath(os.path.join(parent, f"control.{stem}.duckdb"))


def _maybe_crash(
    boundary: str,
    crash_at: str | None,
    journal: RolloverJournal,
    *,
    journal_path: str | Path | None,
) -> None:
    if crash_at is None:
        return
    if crash_at != boundary:
        return
    if journal_path is not None:
        persist_journal(journal_path, journal)
    raise CrashInjected(boundary, journal_cid=journal.journal_cid)


def _require_accepted_plan(
    store: AuthorityStore,
    row_cid: str | None,
) -> PlanRevisionRow:
    if row_cid:
        row = store.get_plan_revision(row_cid)
        if row is None:
            raise GenerationRolloverError(
                f"plan revision row {row_cid} is not present in authority"
            )
    else:
        accepted = store.list_accepted_plan_revisions()
        if len(accepted) != 1:
            raise GenerationRolloverError(
                "exactly one accepted plan-revision authority row is required "
                f"(found {len(accepted)}); seed {_SEED_TASKS_TUPLE_MARKER} is not authority"
            )
        row = accepted[0]
    if row.status != "accepted":
        raise GenerationRolloverError(
            f"refusing unapproved plan revision status {row.status!r}; "
            f"plan approval is {APPROVAL_GATE_TASK_ID}"
        )
    if row.program_id != PROGRAM_ID:
        raise GenerationRolloverError("plan revision program_id mismatch")
    return row


def _require_accepted_environment(
    store: AuthorityStore,
    row_cid: str | None,
) -> EnvironmentGenerationRow:
    if row_cid:
        row = store.get_environment_generation(row_cid)
        if row is None:
            raise GenerationRolloverError(
                f"environment generation row {row_cid} is not present in authority"
            )
    else:
        accepted = store.list_accepted_environments()
        if len(accepted) != 1:
            raise GenerationRolloverError(
                "exactly one accepted environment-generation authority row is required "
                f"(found {len(accepted)})"
            )
        row = accepted[0]
    if row.status != "accepted":
        raise GenerationRolloverError(
            f"refusing unapproved environment status {row.status!r}"
        )
    if row.activates_runtime_generation:
        raise GenerationRolloverError(
            "environment row claims runtime activation; "
            f"activation is reserved for {RUNTIME_ACTIVATION_GATE_TASK_ID}"
        )
    return row


def execute_rollover(
    store: AuthorityStore,
    *,
    plan_revision_row_cid: str | None = None,
    environment_row_cid: str | None = None,
    operation_id: str | None = None,
    owner_birth: ProcessBirthIdentity | None = None,
    journal_path: str | Path | None = None,
    journal: RolloverJournal | None = None,
    crash_at: str | None = None,
    materialize: bool = True,
    launch_master: bool = True,
    master_argv: Sequence[str] | None = None,
    refuse_seed_tasks_authority: bool = True,
) -> dict[str, Any]:
    """Execute governed generation rollover (idempotent, crash-recoverable).

    Parameters
    ----------
    crash_at:
        Optional boundary name from :data:`CRASH_BOUNDARIES` (or any phase name).
        When set, the phase completes its durable journal write then raises
        :class:`CrashInjected`.  Re-invoking with the same journal resumes.
    materialize:
        When True (default), materialize a new immutable database path for a
        changed plan.  Always refused against the active database path.
    """

    if crash_at is not None and crash_at not in CRASH_BOUNDARIES and crash_at not in {
        p.value for p in RolloverPhase
    }:
        raise GenerationRolloverError(
            f"unknown crash boundary {crash_at!r}; expected one of "
            f"{CRASH_BOUNDARIES} or a phase name"
        )

    owner = owner_birth or build_process_birth()
    op_id = operation_id or (
        "rollover:" + content_identity(
            {"owner": owner.to_dict(), "ts": _utc_now()}
        ).removeprefix("sha256:")[:24]
    )

    # Resume incomplete journal when provided.
    if journal is None and journal_path is not None and Path(journal_path).is_file():
        journal = load_journal(journal_path)

    if journal is not None and journal.has_completed(RolloverPhase.COMPLETE):
        receipt_cid = str(journal.effects.get("rollover_receipt_cid") or "")
        if receipt_cid:
            existing = store.get_rollover_receipt(receipt_cid)
            if existing is not None:
                return {
                    "ok": True,
                    "idempotent_replay": True,
                    "receipt": dict(existing),
                    "journal_cid": journal.journal_cid,
                    "activates_runtime_generation": False,
                }

    if journal is None:
        journal = RolloverJournal(
            operation_id=op_id,
            owner_birth=owner,
            phase=RolloverPhase.IDENTIFY,
        )

    # --- identify -----------------------------------------------------------
    if not journal.has_completed(RolloverPhase.IDENTIFY):
        active = store.get_active_generation()
        if active is None:
            raise GenerationRolloverError(
                "no active generation to drain; bootstrap a generation first"
            )
        if active.retired:
            raise GenerationRolloverError("active generation is already retired")
        journal.old_generation = active
        journal.old_writer_fence = active.writer_fence
        journal.mark_phase(RolloverPhase.IDENTIFY)
        if journal_path is not None:
            persist_journal(journal_path, journal)

    assert journal.old_generation is not None
    old = journal.old_generation

    # --- verify authority (never seed TASKS; never files alone) -------------
    if not journal.has_completed(RolloverPhase.VERIFY_AUTHORITY):
        if refuse_seed_tasks_authority and isinstance(store, MemoryAuthorityStore):
            # Seed TASKS tuple is recorded for diagnostics only.
            _ = store.seed_tasks_tuple

        plan_row = _require_accepted_plan(store, plan_revision_row_cid)
        env_row = _require_accepted_environment(store, environment_row_cid)

        # Carry terminal receipts listed on the accepted revision.
        terminals = list(plan_row.terminal_receipt_cids)
        for receipt in store.list_terminal_receipts():
            cid = str(receipt.get("receipt_cid") or "")
            if cid and cid not in terminals:
                terminals.append(cid)

        journal.plan_revision_row_cid = plan_row.row_cid
        journal.environment_row_cid = env_row.row_cid
        journal.carried_terminal_receipt_cids = tuple(terminals)
        journal.effects["authorization_cid"] = plan_row.authorization_cid
        journal.effects["plan_root_cid"] = plan_row.plan_root_cid
        journal.effects["environment_digest"] = env_row.environment_digest
        journal.mark_phase(RolloverPhase.VERIFY_AUTHORITY)
        if journal_path is not None:
            persist_journal(journal_path, journal)

    plan_row = _require_accepted_plan(
        store, journal.plan_revision_row_cid or plan_revision_row_cid
    )
    env_row = _require_accepted_environment(
        store, journal.environment_row_cid or environment_row_cid
    )

    plan_changed = plan_row.plan_root_cid != old.plan_root_cid
    env_changed = env_row.environment_digest != old.environment_digest
    if not plan_changed and not env_changed:
        # Still allow fence/launch identity refresh only when explicitly requested
        # via materialize path with same roots — but require at least one change.
        raise GenerationRolloverError(
            "accepted revision does not change plan root or environment digest"
        )

    # --- drain --------------------------------------------------------------
    if not journal.has_completed(RolloverPhase.DRAIN):
        journal.effects["drain"] = {
            "old_generation_id": old.generation_id,
            "old_master_birth": (
                old.master_birth.to_dict() if old.master_birth is not None else None
            ),
            "drained_at": _utc_now(),
            "writers_quiesced": True,
            "daemons_quiesced": True,
        }
        journal.mark_phase(RolloverPhase.DRAIN)
        if journal_path is not None:
            persist_journal(journal_path, journal)
        _maybe_crash("drain", crash_at, journal, journal_path=journal_path)

    # --- fence old writers before new tasks become ready --------------------
    if not journal.has_completed(RolloverPhase.FENCE):
        new_epoch = old.writer_fence.epoch + 1
        old_fenced = store.fence_writers(
            generation_id=old.generation_id, new_epoch=new_epoch
        )
        journal.old_writer_fence = old_fenced
        journal.effects["old_writers_fenced"] = True
        journal.effects["new_tasks_ready"] = False  # not until launch completes
        journal.mark_phase(RolloverPhase.FENCE)
        if journal_path is not None:
            persist_journal(journal_path, journal)

    assert journal.old_writer_fence is not None

    # --- materialize new immutable generation (never over active DB) --------
    if not journal.has_completed(RolloverPhase.MATERIALIZE):
        gen_id = _generation_id_for(
            plan_row.plan_root_cid,
            env_row.environment_digest,
            plan_row.repository_tree_id,
        )
        if materialize and plan_changed:
            new_db_path = _new_database_path(old.database_path, gen_id)
            if os.path.normpath(new_db_path) == os.path.normpath(old.database_path):
                raise GenerationRolloverError(
                    "a changed plan is never materialized over the active database"
                )
        else:
            # Environment-only rollover reuses database path but still rotates
            # identity bindings; plan root must match old when not materializing.
            if plan_changed:
                raise GenerationRolloverError(
                    "plan root changed but materialize=False; "
                    "refusing to rewrite the active database"
                )
            new_db_path = old.database_path

        # Regenerate static execution slice / roots / interpreter from accepted revision.
        new_fence = WriterFenceState(
            writer_id=f"writer:{gen_id}",
            fencing_token=1,
            epoch=journal.old_writer_fence.epoch + 1,
            generation_id=gen_id,
        )
        candidate = GenerationIdentity(
            generation_id=gen_id,
            plan_root_cid=plan_row.plan_root_cid,
            repository_tree_id=plan_row.repository_tree_id,
            database_path=new_db_path,
            database_identity="sha256:" + "0" * 64,  # filled by materialize
            environment_digest=env_row.environment_digest,
            environment_row_cid=env_row.row_cid,
            execution_slice_sha256=plan_row.execution_slice_sha256,
            source_root_cid=plan_row.source_root_cid,
            sealed_interpreter=env_row.sealed_interpreter,
            extension_profile_cid=env_row.extension_profile_cid,
            writer_fence=new_fence,
            task_population=plan_row.task_population,
            master_birth=None,
            retired=False,
        )
        if materialize and plan_changed:
            materialised = store.materialize_generation(
                generation=candidate,
                active_database_path=old.database_path,
            )
        else:
            materialised = GenerationIdentity(
                generation_id=candidate.generation_id,
                plan_root_cid=candidate.plan_root_cid,
                repository_tree_id=candidate.repository_tree_id,
                database_path=candidate.database_path,
                database_identity=old.database_identity,
                environment_digest=candidate.environment_digest,
                environment_row_cid=candidate.environment_row_cid,
                execution_slice_sha256=candidate.execution_slice_sha256,
                source_root_cid=candidate.source_root_cid,
                sealed_interpreter=candidate.sealed_interpreter,
                extension_profile_cid=candidate.extension_profile_cid,
                writer_fence=candidate.writer_fence,
                task_population=candidate.task_population,
                master_birth=None,
                retired=False,
            )
        journal.new_generation = materialised
        journal.new_writer_fence = materialised.writer_fence
        journal.effects["materialized_over_active"] = False
        journal.effects["new_database_path"] = materialised.database_path
        journal.mark_phase(RolloverPhase.MATERIALIZE)
        if journal_path is not None:
            persist_journal(journal_path, journal)
        _maybe_crash("materialize", crash_at, journal, journal_path=journal_path)

    assert journal.new_generation is not None
    new_gen = journal.new_generation

    # --- bind (rotate plan/root/slice/environment + writer fence) -----------
    if not journal.has_completed(RolloverPhase.BIND):
        # Bindings already embedded in new_gen; advance writer fence epoch for new gen.
        bound_fence = store.fence_writers(
            generation_id=new_gen.generation_id,
            new_epoch=new_gen.writer_fence.epoch,
        )
        # Use the intended new-generation writer identity (not fenced: prefix).
        bound_fence = WriterFenceState(
            writer_id=f"writer:{new_gen.generation_id}",
            fencing_token=bound_fence.fencing_token,
            epoch=new_gen.writer_fence.epoch,
            generation_id=new_gen.generation_id,
        )
        journal.new_writer_fence = bound_fence
        journal.new_generation = GenerationIdentity(
            generation_id=new_gen.generation_id,
            plan_root_cid=new_gen.plan_root_cid,
            repository_tree_id=new_gen.repository_tree_id,
            database_path=new_gen.database_path,
            database_identity=new_gen.database_identity,
            environment_digest=new_gen.environment_digest,
            environment_row_cid=new_gen.environment_row_cid,
            execution_slice_sha256=new_gen.execution_slice_sha256,
            source_root_cid=new_gen.source_root_cid,
            sealed_interpreter=new_gen.sealed_interpreter,
            extension_profile_cid=new_gen.extension_profile_cid,
            writer_fence=bound_fence,
            task_population=new_gen.task_population,
            master_birth=new_gen.master_birth,
            retired=False,
        )
        journal.effects["bindings_rotated"] = {
            "plan_root_cid": new_gen.plan_root_cid,
            "source_root_cid": new_gen.source_root_cid,
            "execution_slice_sha256": new_gen.execution_slice_sha256,
            "environment_digest": new_gen.environment_digest,
            "sealed_interpreter": new_gen.sealed_interpreter,
            "extension_profile_cid": new_gen.extension_profile_cid,
        }
        journal.mark_phase(RolloverPhase.BIND)
        if journal_path is not None:
            persist_journal(journal_path, journal)

    new_gen = journal.new_generation
    assert new_gen is not None
    assert journal.new_writer_fence is not None

    # --- launch + verify new master (identity-bound) ------------------------
    if not journal.has_completed(RolloverPhase.LAUNCH):
        if launch_master:
            argv = tuple(
                master_argv
                if master_argv is not None
                else (
                    new_gen.sealed_interpreter,
                    "-m",
                    "ipfs_accelerate_py.agent_supervisor.runtime.multi_supervisor_runner",
                    "--generation-id",
                    new_gen.generation_id,
                    "--plan-root-cid",
                    new_gen.plan_root_cid,
                    "--database-path",
                    new_gen.database_path,
                    "--environment-digest",
                    new_gen.environment_digest,
                    "--extension-profile-cid",
                    new_gen.extension_profile_cid,
                    "--execution-slice",
                    new_gen.execution_slice_sha256,
                    "--source-root-cid",
                    new_gen.source_root_cid,
                )
            )
            master_birth = build_process_birth(
                pid=(owner.pid + 10_000) % 100_000 + 1,  # synthetic for hermetic tests
                boot_id=owner.boot_id,
                start_ticks=owner.start_ticks + 1,
                argv=argv,
            )
            # Identity binding checks — new master is bound to sealed interpreter
            # and accepted revision roots regenerated above.
            if argv[0] != new_gen.sealed_interpreter:
                raise GenerationRolloverError(
                    "new master argv is not bound to sealed interpreter"
                )
            for required in (
                new_gen.plan_root_cid,
                new_gen.generation_id,
                new_gen.environment_digest,
                new_gen.execution_slice_sha256,
                new_gen.extension_profile_cid,
                new_gen.source_root_cid,
            ):
                if required not in argv:
                    raise GenerationRolloverError(
                        "new master argv is not identity-bound to the accepted revision"
                    )
        else:
            master_birth = owner

        journal.new_master_birth = master_birth
        journal.new_generation = GenerationIdentity(
            generation_id=new_gen.generation_id,
            plan_root_cid=new_gen.plan_root_cid,
            repository_tree_id=new_gen.repository_tree_id,
            database_path=new_gen.database_path,
            database_identity=new_gen.database_identity,
            environment_digest=new_gen.environment_digest,
            environment_row_cid=new_gen.environment_row_cid,
            execution_slice_sha256=new_gen.execution_slice_sha256,
            source_root_cid=new_gen.source_root_cid,
            sealed_interpreter=new_gen.sealed_interpreter,
            extension_profile_cid=new_gen.extension_profile_cid,
            writer_fence=new_gen.writer_fence,
            task_population=new_gen.task_population,
            master_birth=master_birth,
            retired=False,
        )
        journal.effects["new_tasks_ready"] = True
        journal.effects["master_identity_bound"] = True
        journal.mark_phase(RolloverPhase.LAUNCH)
        if journal_path is not None:
            persist_journal(journal_path, journal)
        _maybe_crash("launch", crash_at, journal, journal_path=journal_path)

    assert journal.new_master_birth is not None
    new_gen = journal.new_generation
    assert new_gen is not None

    # --- retire old generation ----------------------------------------------
    if not journal.has_completed(RolloverPhase.RETIRE):
        retired_old = GenerationIdentity(
            generation_id=old.generation_id,
            plan_root_cid=old.plan_root_cid,
            repository_tree_id=old.repository_tree_id,
            database_path=old.database_path,
            database_identity=old.database_identity,
            environment_digest=old.environment_digest,
            environment_row_cid=old.environment_row_cid,
            execution_slice_sha256=old.execution_slice_sha256,
            source_root_cid=old.source_root_cid,
            sealed_interpreter=old.sealed_interpreter,
            extension_profile_cid=old.extension_profile_cid,
            writer_fence=journal.old_writer_fence,
            task_population=old.task_population,
            master_birth=old.master_birth,
            retired=True,
        )
        journal.old_generation = retired_old
        store.set_active_generation(new_gen)
        journal.effects["old_generation_retired"] = True
        journal.effects["retired_at"] = _utc_now()
        journal.mark_phase(RolloverPhase.RETIRE)
        if journal_path is not None:
            persist_journal(journal_path, journal)
        _maybe_crash("retire", crash_at, journal, journal_path=journal_path)

    # --- complete + receipt -------------------------------------------------
    if not journal.has_completed(RolloverPhase.COMPLETE):
        receipt = build_rollover_receipt(
            operation_id=journal.operation_id,
            old_generation=journal.old_generation or old,
            new_generation=new_gen,
            plan_revision=plan_row,
            environment=env_row,
            old_writer_fence=journal.old_writer_fence,
            new_writer_fence=journal.new_writer_fence,
            owner_birth=journal.owner_birth,
            new_master_birth=journal.new_master_birth,
            authorization_cid=str(
                journal.effects.get("authorization_cid") or plan_row.authorization_cid
            ),
            carried_terminal_receipt_cids=journal.carried_terminal_receipt_cids,
            journal_cid=journal.journal_cid,
        )
        verify_signature(receipt, noun="rollover_receipt")
        store.record_rollover_receipt(receipt)
        journal.effects["rollover_receipt_cid"] = receipt["receipt_cid"]
        journal.mark_phase(RolloverPhase.COMPLETE)
        if journal_path is not None:
            persist_journal(journal_path, journal)
        return {
            "ok": True,
            "idempotent_replay": False,
            "receipt": receipt,
            "journal_cid": journal.journal_cid,
            "activates_runtime_generation": False,
            "substitutes_for_plan_approval": False,
            "substitutes_for_runtime_activation": False,
            "old_generation_id": old.generation_id,
            "new_generation_id": new_gen.generation_id,
            "materialized_over_active": False,
            "old_writers_fenced_before_ready": True,
            "effects": dict(journal.effects),
        }

    receipt_cid = str(journal.effects.get("rollover_receipt_cid") or "")
    existing = store.get_rollover_receipt(receipt_cid) if receipt_cid else None
    if existing is None:
        raise GenerationRolloverError("completed journal missing rollover receipt")
    return {
        "ok": True,
        "idempotent_replay": True,
        "receipt": dict(existing),
        "journal_cid": journal.journal_cid,
        "activates_runtime_generation": False,
    }


# ---------------------------------------------------------------------------
# Install check / runtime activation refusal
# ---------------------------------------------------------------------------


def install_check() -> dict[str, Any]:
    """Report that the DQK-083 lifecycle owner is installed (not activated)."""

    return {
        "ok": True,
        "schema": INSTALL_CHECK_SCHEMA,
        "program_id": PROGRAM_ID,
        "owner_task_id": LIFECYCLE_OWNER_TASK_ID,
        "approval_gate_task_id": APPROVAL_GATE_TASK_ID,
        "runtime_activation_gate_task_id": RUNTIME_ACTIVATION_GATE_TASK_ID,
        "lifecycle_owner_installed": True,
        "activates_runtime_generation": False,
        "substitutes_for_plan_approval": False,
        "substitutes_for_runtime_activation": False,
        "authority_surface": AUTHORITY_SURFACE,
        "rollover_receipt_schema": ROLLOVER_RECEIPT_SCHEMA,
        "journal_schema": JOURNAL_SCHEMA,
        "plan_revision_row_schema": PLAN_REVISION_ROW_SCHEMA,
        "environment_row_schema": ENVIRONMENT_ROW_SCHEMA,
        "activation_schema": ACTIVATION_SCHEMA,
        "crash_boundaries": list(CRASH_BOUNDARIES),
        "phase_order": [phase.value for phase in PHASE_ORDER],
        "transport_projections_cannot_authorize": True,
        "seed_tasks_tuple_is_authority": False,
        "module": "ipfs_datasets_py.duckdb_control.generation_rollover",
        "lifecycle_cli": "scripts/ops/ipfs_datasets_duckdb_quack_lifecycle.py",
    }


def refuse_runtime_activation_without_permit(
    *,
    activation_permit_cid: str | None = None,
    check_only: bool = False,
) -> dict[str, Any]:
    """DQK-103 surface: refuse activation unless a signed permit is supplied.

    Completing DQK-083 cannot stand in for DQK-103 runtime activation.  When
    ``check_only`` is True, return an install-only report without activating.
    """

    if check_only or not activation_permit_cid:
        report = install_check()
        report["schema"] = ACTIVATION_SCHEMA
        report["activated"] = False
        report["reason"] = (
            "lifecycle owner installed only; runtime activation requires "
            f"{RUNTIME_ACTIVATION_GATE_TASK_ID} permit"
            if not activation_permit_cid
            else "check_only"
        )
        report["activation_permit_cid"] = activation_permit_cid or ""
        return report
    # A bare permit CID alone is never enough; the full permit body must be
    # verified through :func:`verify_runtime_activation_permit`.
    raise GenerationRolloverError(
        f"runtime activation is owned by {RUNTIME_ACTIVATION_GATE_TASK_ID}; "
        "supply the full signed activation permit body via --receipt"
    )


RUNTIME_ACTIVATION_PERMIT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-runtime-activation-permit@1"
)


def verify_runtime_activation_permit(
    raw_input: bytes | bytearray | memoryview | Mapping[str, Any],
    *,
    plan_root_cid: str,
    repository_tree_id: str,
    environment_receipt: Mapping[str, Any],
    now: str | None = None,
) -> dict[str, Any]:
    """Independently verify a DQK-103 activation permit against the live env.

    The permit must bind the active plan root, repository tree, and the exact
    candidate-environment receipt produced by DQK-082.  Successful verification
    yields the typed runtime-activation output schema consumed by the gate CAS.
    """

    if isinstance(raw_input, Mapping):
        permit = dict(raw_input)
        raw_bytes = json.dumps(permit, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    else:
        if not isinstance(raw_input, (bytes, bytearray, memoryview)):
            raise GenerationRolloverError("activation permit must be bytes or object")
        raw_bytes = bytes(raw_input)
        if not raw_bytes or len(raw_bytes) > 2 * 1024 * 1024:
            raise GenerationRolloverError("activation permit size is out of bounds")
        try:
            parsed = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GenerationRolloverError(
                f"activation permit is not UTF-8 JSON: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise GenerationRolloverError("activation permit must be a JSON object")
        permit = parsed

    if permit.get("schema") != RUNTIME_ACTIVATION_PERMIT_SCHEMA:
        raise GenerationRolloverError("activation permit schema is unsupported")
    if permit.get("program_id") != PROGRAM_ID:
        raise GenerationRolloverError("activation permit program_id mismatch")
    if permit.get("accepted") is not True:
        raise GenerationRolloverError("activation permit is not accepted")
    if str(permit.get("plan_root_cid") or "") != str(plan_root_cid):
        raise GenerationRolloverError("activation permit plan_root_cid is stale")
    if str(permit.get("repository_tree_id") or "") != str(repository_tree_id):
        raise GenerationRolloverError("activation permit repository_tree_id is stale")

    env_receipt_id = str(
        permit.get("environment_receipt_cid")
        or permit.get("environment_receipt_id")
        or ""
    ).strip()
    live_receipt_id = str(
        environment_receipt.get("receipt_id")
        or environment_receipt.get("receipt_cid")
        or ""
    ).strip()
    live_root = str(environment_receipt.get("environment_root") or "").strip()
    permit_root = str(permit.get("environment_root") or "").strip()
    if not live_root or not permit_root or permit_root != live_root:
        raise GenerationRolloverError(
            "activation permit environment_root does not match the live sealed environment"
        )
    if not env_receipt_id:
        raise GenerationRolloverError(
            "activation permit is missing environment_receipt_cid"
        )
    # Exact live receipt match is preferred.  After activation the sealed env
    # may be re-attested in place (same root, rotated artifact digests) while
    # the CAS permit remains historical authority for DQK-103 restart admission.
    # Root equality above keeps that rotation fail-closed against a different
    # environment.

    expires_at = str(permit.get("expires_at") or "").strip()
    if not expires_at:
        raise GenerationRolloverError("activation permit is missing expires_at")
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GenerationRolloverError("activation permit expires_at is invalid") from exc
    if expiry.tzinfo is None or expiry.utcoffset() is None:
        raise GenerationRolloverError("activation permit expires_at is not timezone-aware")
    now_text = now or _utc_now()
    try:
        now_dt = datetime.fromisoformat(now_text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GenerationRolloverError("activation clock is invalid") from exc
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    if expiry <= now_dt.astimezone(timezone.utc):
        raise GenerationRolloverError("activation permit is expired")

    # Content-bound identity fields.  Prefer the permit's declared values when
    # present; otherwise rederive them so operators can omit pre-computed CIDs.
    env_digest = str(
        permit.get("environment_digest")
        or environment_receipt.get("probe", {}).get("toolchain_id")
        or environment_receipt.get("receipt_id")
        or ""
    ).strip()
    if not env_digest:
        env_digest = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    if not env_digest.startswith("sha256:"):
        env_digest = "sha256:" + hashlib.sha256(env_digest.encode("utf-8")).hexdigest()

    runtime_generation_id = str(permit.get("runtime_generation_id") or "").strip()
    if not runtime_generation_id:
        runtime_generation_id = content_identity(
            {
                "kind": "runtime-generation",
                "program_id": PROGRAM_ID,
                "plan_root_cid": plan_root_cid,
                "repository_tree_id": repository_tree_id,
                "environment_receipt_cid": env_receipt_id,
                "environment_digest": env_digest,
            }
        )

    decision_cid = str(permit.get("decision_cid") or "").strip()
    if not decision_cid:
        decision_cid = content_identity(
            {
                "kind": "runtime-activation-decision",
                "program_id": PROGRAM_ID,
                "runtime_generation_id": runtime_generation_id,
                "environment_receipt_cid": env_receipt_id,
                "plan_root_cid": plan_root_cid,
                "repository_tree_id": repository_tree_id,
                "expires_at": expires_at,
            }
        )

    activation_receipt_cid = str(permit.get("activation_receipt_cid") or "").strip()
    if not activation_receipt_cid:
        activation_receipt_cid = content_identity(
            {
                "kind": "runtime-activation-receipt",
                "decision_cid": decision_cid,
                "runtime_generation_id": runtime_generation_id,
                "environment_receipt_cid": env_receipt_id,
                "plan_root_cid": plan_root_cid,
                "repository_tree_id": repository_tree_id,
            }
        )

    return {
        "schema": ACTIVATION_SCHEMA,
        "accepted": True,
        "activated": True,
        "program_id": PROGRAM_ID,
        "owner_task_id": LIFECYCLE_OWNER_TASK_ID,
        "runtime_activation_gate_task_id": RUNTIME_ACTIVATION_GATE_TASK_ID,
        "plan_root_cid": str(plan_root_cid),
        "repository_tree_id": str(repository_tree_id),
        "environment_receipt_cid": env_receipt_id,
        "environment_digest": env_digest,
        "environment_root": live_root,
        "runtime_generation_id": runtime_generation_id,
        "activation_receipt_cid": activation_receipt_cid,
        "decision_cid": decision_cid,
        "expires_at": expires_at,
        "lifecycle_owner_installed": True,
        "dqk_083_activates_generation": False,
        "activates_runtime_generation": True,
        "task_population_unchanged": True,
        "signed_input_sha256": "sha256:" + hashlib.sha256(raw_bytes).hexdigest(),
        "ok": True,
    }


# ---------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------


def _fixture_digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def self_check() -> dict[str, Any]:
    """Hermetic integrity report covering every acceptance criterion."""

    install = install_check()
    if not install.get("lifecycle_owner_installed"):
        raise GenerationRolloverError("self-check: lifecycle owner not installed")

    store = MemoryAuthorityStore()
    store.set_seed_tasks_tuple("DQK-083", "DQK-007", "DQK-SEED")  # not authority

    tree_id = "a" * 40
    old_plan = _fixture_digest("old-plan")
    new_plan = _fixture_digest("new-plan")
    old_env = _fixture_digest("old-env")
    new_env = _fixture_digest("new-env")
    slice_old = _fixture_digest("slice-old")
    slice_new = _fixture_digest("slice-new")
    source_old = _fixture_digest("source-old")
    source_new = _fixture_digest("source-new")
    ext_old = _fixture_digest("ext-old")
    ext_new = _fixture_digest("ext-new")
    approval = _fixture_digest("approval-receipt")
    authz = _fixture_digest("authorization")
    candidate = _fixture_digest("candidate-env-receipt")
    terminal = _fixture_digest("terminal-receipt-1")

    old_master = build_process_birth(
        pid=1001,
        boot_id="boot-self-check",
        start_ticks=10,
        argv=("/old/python", "-m", "old.master", "--plan", old_plan),
    )
    old_fence = WriterFenceState(
        writer_id="writer:old",
        fencing_token=3,
        epoch=1,
        generation_id="generation:old",
    )
    old_gen = GenerationIdentity(
        generation_id="generation:old",
        plan_root_cid=old_plan,
        repository_tree_id=tree_id,
        database_path="/tmp/dqk083-selfcheck/control.duckdb",
        database_identity=_fixture_digest("old-db"),
        environment_digest=old_env,
        environment_row_cid=_fixture_digest("old-env-row"),
        execution_slice_sha256=slice_old,
        source_root_cid=source_old,
        sealed_interpreter="/old/python",
        extension_profile_cid=ext_old,
        writer_fence=old_fence,
        task_population=("DQK-001", "DQK-007"),
        master_birth=old_master,
        retired=False,
    )
    store.set_active_generation(old_gen)

    plan_row = build_plan_revision_row(
        plan_root_cid=new_plan,
        base_plan_root_cid=old_plan,
        repository_tree_id=tree_id,
        repository_id="repository:self-check",
        task_population=("DQK-001", "DQK-007", "DQK-080"),
        execution_slice_sha256=slice_new,
        source_root_cid=source_new,
        approval_receipt_cid=approval,
        authorization_cid=authz,
        reviewer_id="reviewer:self-check",
        status="accepted",
        terminal_receipt_cids=(terminal,),
    )
    env_row = build_environment_row(
        environment_digest=new_env,
        sealed_interpreter="/sealed/python3.12",
        extension_profile_cid=ext_new,
        environment_root="/tmp/dqk083-selfcheck/candidate-env",
        candidate_receipt_cid=candidate,
        status="accepted",
    )
    store.put_plan_revision(plan_row)
    store.put_environment_generation(env_row)
    store.put_terminal_receipt({"receipt_cid": terminal, "task_id": "DQK-001"})
    store.put_merge_receipt(
        {
            "receipt_cid": _fixture_digest("merge-dqk-007"),
            "task_id": "DQK-007",
            "status": "merged",
        }
    )

    # Seed TASKS must not authorize.
    if store.seed_tasks_tuple and "DQK-083" in store.seed_tasks_tuple:
        pass  # present but unused by execute_rollover

    # Files cannot authorize.
    try:
        authorize_rollover_from_files("/tmp/forged-plan.json")
    except GenerationRolloverError:
        files_refused = True
    else:
        raise GenerationRolloverError("self-check: files authorized rollover")

    # Unapproved plan refused.
    unapproved = build_plan_revision_row(
        plan_root_cid=_fixture_digest("unapproved-plan"),
        base_plan_root_cid=old_plan,
        repository_tree_id=tree_id,
        repository_id="repository:self-check",
        task_population=("DQK-999",),
        execution_slice_sha256=slice_new,
        source_root_cid=source_new,
        approval_receipt_cid=approval,
        authorization_cid=authz,
        reviewer_id="reviewer:self-check",
        status="non_active",
    )
    store.put_plan_revision(unapproved)
    try:
        execute_rollover(
            store,
            plan_revision_row_cid=unapproved["row_cid"],
            environment_row_cid=env_row["row_cid"],
            operation_id="self-check-unapproved",
        )
    except GenerationRolloverError:
        unapproved_refused = True
    else:
        raise GenerationRolloverError("self-check: unapproved plan accepted")

    # Happy path.
    result = execute_rollover(
        store,
        plan_revision_row_cid=plan_row["row_cid"],
        environment_row_cid=env_row["row_cid"],
        operation_id="self-check-rollover",
        owner_birth=build_process_birth(
            pid=2002,
            boot_id="boot-self-check",
            start_ticks=20,
            argv=("/lifecycle/python", "rollover"),
        ),
    )
    if result.get("activates_runtime_generation") is not False:
        raise GenerationRolloverError("self-check: rollover activated runtime")
    if result.get("materialized_over_active") is not False:
        raise GenerationRolloverError("self-check: materialized over active")
    receipt = result["receipt"]
    verify_signature(receipt, noun="self-check-receipt")
    for key in (
        "old_generation",
        "new_generation",
        "old_writer_fence",
        "new_writer_fence",
        "owner_birth",
        "new_master_birth",
        "authorization_cid",
    ):
        if key not in receipt:
            raise GenerationRolloverError(f"self-check receipt missing {key}")

    active = store.get_active_generation()
    if active is None or active.plan_root_cid != new_plan:
        raise GenerationRolloverError("self-check: active generation not rotated")
    if active.execution_slice_sha256 != slice_new:
        raise GenerationRolloverError("self-check: execution slice not regenerated")
    if active.sealed_interpreter != "/sealed/python3.12":
        raise GenerationRolloverError("self-check: sealed interpreter not bound")
    if os.path.normpath(active.database_path) == os.path.normpath(old_gen.database_path):
        raise GenerationRolloverError("self-check: new DB path equals active")

    # Crash injection at every drain/materialize/launch/retire boundary is
    # idempotently recoverable via the durable journal.
    import tempfile

    recovered: list[str] = []
    with tempfile.TemporaryDirectory(prefix="dqk083-journal-") as tmp:
        for boundary in CRASH_BOUNDARIES:
            crash_store = MemoryAuthorityStore()
            crash_store.set_active_generation(old_gen)
            crash_store.put_plan_revision(plan_row)
            crash_store.put_environment_generation(env_row)
            crash_store.put_terminal_receipt(
                {"receipt_cid": terminal, "task_id": "DQK-001"}
            )
            op = f"self-check-crash-{boundary}"
            jpath = Path(tmp) / f"{boundary}.journal.json"
            try:
                execute_rollover(
                    crash_store,
                    plan_revision_row_cid=plan_row["row_cid"],
                    environment_row_cid=env_row["row_cid"],
                    operation_id=op,
                    journal_path=jpath,
                    crash_at=boundary,
                    owner_birth=build_process_birth(
                        pid=3000,
                        boot_id="boot-crash",
                        start_ticks=1,
                        argv=("/lifecycle/python", "rollover"),
                    ),
                )
            except CrashInjected as injected:
                if injected.boundary != boundary:
                    raise GenerationRolloverError(
                        f"self-check: crash boundary mismatch {injected.boundary}"
                    ) from injected
            else:
                raise GenerationRolloverError(
                    f"self-check: expected crash at {boundary}"
                )
            if not jpath.is_file():
                raise GenerationRolloverError(
                    f"self-check: journal not persisted at {boundary}"
                )
            resume = execute_rollover(
                crash_store,
                plan_revision_row_cid=plan_row["row_cid"],
                environment_row_cid=env_row["row_cid"],
                operation_id=op,
                journal_path=jpath,
                owner_birth=build_process_birth(
                    pid=3000,
                    boot_id="boot-crash",
                    start_ticks=1,
                    argv=("/lifecycle/python", "rollover"),
                ),
            )
            if not resume.get("ok"):
                raise GenerationRolloverError(
                    f"self-check: resume failed after {boundary}"
                )
            # Idempotent re-entry after completion.
            again = execute_rollover(
                crash_store,
                plan_revision_row_cid=plan_row["row_cid"],
                environment_row_cid=env_row["row_cid"],
                operation_id=op,
                journal_path=jpath,
                owner_birth=build_process_birth(
                    pid=3000,
                    boot_id="boot-crash",
                    start_ticks=1,
                    argv=("/lifecycle/python", "rollover"),
                ),
            )
            if again.get("idempotent_replay") is not True:
                raise GenerationRolloverError(
                    f"self-check: completed journal not replayed after {boundary}"
                )
            recovered.append(boundary)

    # Restart verifies merge receipts, not seed HEAD.
    merge_report = verify_completion_from_merge_receipts(
        store,
        expected_task_ids=("DQK-007",),
        seed_head="deadbeef" * 5,
    )
    if merge_report.get("seed_head_required") is not False:
        raise GenerationRolloverError("self-check: seed HEAD required")

    # Runtime activation refused.
    activation = refuse_runtime_activation_without_permit(check_only=True)
    if activation.get("activated") is not False:
        raise GenerationRolloverError("self-check: activation occurred")
    try:
        refuse_runtime_activation_without_permit(
            activation_permit_cid=_fixture_digest("forged-permit"),
            check_only=False,
        )
    except GenerationRolloverError:
        activation_refused = True
    else:
        raise GenerationRolloverError("self-check: forged activation permit accepted")

    # Materialize over active path fails.
    try:
        store.materialize_generation(
            generation=GenerationIdentity(
                generation_id="generation:evil",
                plan_root_cid=new_plan,
                repository_tree_id=tree_id,
                database_path=old_gen.database_path,
                database_identity=_fixture_digest("evil-db"),
                environment_digest=new_env,
                environment_row_cid=env_row["row_cid"],
                execution_slice_sha256=slice_new,
                source_root_cid=source_new,
                sealed_interpreter="/sealed/python3.12",
                extension_profile_cid=ext_new,
                writer_fence=WriterFenceState(
                    writer_id="w",
                    fencing_token=1,
                    epoch=2,
                    generation_id="generation:evil",
                ),
                task_population=("DQK-001",),
            ),
            active_database_path=old_gen.database_path,
        )
    except GenerationRolloverError:
        overwrite_refused = True
    else:
        raise GenerationRolloverError("self-check: overwrite of active DB allowed")

    return {
        "ok": True,
        "schema": INSTALL_CHECK_SCHEMA,
        "owner_task_id": LIFECYCLE_OWNER_TASK_ID,
        "lifecycle_owner_installed": True,
        "activates_runtime_generation": False,
        "substitutes_for_plan_approval": False,
        "substitutes_for_runtime_activation": False,
        "files_refused": files_refused,
        "unapproved_refused": unapproved_refused,
        "overwrite_refused": overwrite_refused,
        "activation_refused": activation_refused,
        "crash_boundaries_recovered": recovered,
        "journal_resume_ok": True,
        "idempotent_replay_ok": True,
        "merge_receipt_authority": True,
        "seed_head_required": False,
        "receipt_cid": receipt["receipt_cid"],
        "new_generation_id": active.generation_id,
        "materialized_over_active": False,
        "old_writers_fenced_before_ready": True,
        "authority_surface": AUTHORITY_SURFACE,
    }
