"""Replay legacy Hammer obligations into current, trusted proof feedback.

Historical Hammer cycle output is an input corpus, not proof evidence.  This
module recovers and content-addresses obligations from that corpus, discards
historical verdicts and bulky artifacts, and executes each unique obligation
through an injected *current* proof executor.  A replay result is eligible for
proof-feedback training only when a fresh receipt is bound to the obligation
and replay policy and records all of the following:

* a current compiler/schema and toolchain fingerprint;
* a proved, proof-checked, non-draft backend result;
* a trusted proof checker/trust root;
* successful native reconstruction and its receipt.

The filesystem cache is keyed by both obligation content and the complete
current execution policy.  Cache records are content checked before use and
written atomically.  Consequently an interrupted replay is resumable, while a
policy, timeout, compiler, translator, solver, theorem registry, or trust-root
change necessarily creates a new cache namespace.

Only bounded categorical fields and digests are serialized.  In particular,
statements, decoded text, prompts, proof scripts, solver output, historical
receipts, nested artifacts, and exception messages never enter replay state.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import importlib
import json
import math
import os
import re
import tempfile
import threading
from collections import Counter
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Optional, Protocol, Sequence

from ipfs_datasets_py.logic.integration.reasoning.hammer import HammerGoal
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_hammer_translation import (
    reconstruction_receipt_from_hammer_result,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_obligations import (
    LEGAL_IR_OBLIGATION_SCHEMA_VERSION,
    LegalIRProofObligation,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_proof_feedback import (
    KernelReconstructionFeedback,
    LegalIRProofFeedbackRecord,
    ProofFeedbackReplay,
    ProofFeedbackStore,
    ProofFeedbackVersions,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_proof_router import (
    LegalIRProofRouteResult,
    ProofTrustLevel,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler,
    LeaseCancelledError,
    LeaseTimeoutError,
    ResourceLane,
    get_global_resource_scheduler,
)


LEGAL_IR_HISTORICAL_HAMMER_REPLAY_SCHEMA_VERSION = (
    "legal-ir-historical-hammer-proof-feedback-replay-v1"
)
LEGAL_IR_HISTORICAL_HAMMER_INVENTORY_SCHEMA_VERSION = (
    "legal-ir-historical-hammer-obligation-inventory-v1"
)
LEGAL_IR_HISTORICAL_HAMMER_CACHE_SCHEMA_VERSION = (
    "legal-ir-historical-hammer-replay-cache-v1"
)
LEGAL_IR_HISTORICAL_HAMMER_EXECUTION_RESULT_SCHEMA_VERSION = (
    "legal-ir-historical-hammer-execution-result-v1"
)

CANONICAL_HISTORICAL_CYCLE_FILE_COUNT = 115
CANONICAL_HISTORICAL_NESTED_ARTIFACT_COUNT = 1_196
CANONICAL_HISTORICAL_UNIQUE_OBLIGATION_COUNT = 96
CANONICAL_HISTORICALLY_TRUSTED_COUNT = 0

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]*$")
_OBLIGATION_COLLECTION_KEYS = frozenset(
    {
        "hammer_obligation",
        "hammer_obligations",
        "obligation",
        "obligations",
        "proof_obligation",
        "proof_obligations",
    }
)
_ARTIFACT_COLLECTION_KEYS = frozenset(
    {
        "artifact",
        "artifacts",
        "hammer_artifacts",
        "nested_artifacts",
        "proof_artifacts",
    }
)
_BULKY_OR_UNTRUSTED_KEYS = frozenset(
    {
        "artifact",
        "artifacts",
        "backend_results",
        "cache",
        "counterexample",
        "decoded",
        "decoded_text",
        "generated_text",
        "historical_receipt",
        "lean_code",
        "lean_proof",
        "model_output",
        "nested_artifacts",
        "output",
        "prompt",
        "proof",
        "proof_artifact",
        "proof_artifacts",
        "proof_script",
        "raw",
        "raw_output",
        "receipt",
        "receipts",
        "reconstruction",
        "result",
        "results",
        "solver_output",
        "source",
        "source_text",
        "text",
        "trace",
        "translation",
        "translations",
        "verdict",
    }
)
_EXECUTION_METADATA_KEYS = frozenset(
    {
        "allow_empty",
        "allowed_values",
        "contract_id",
        "contract_view",
        "coverage_scope",
        "exception",
        "failing_fields",
        "failure_code",
        "field_aliases",
        "obligation_family",
        "obligation_type",
        "preservation_rules",
        "repair_label",
        "repair_lane",
        "required_field",
        "required_field_types",
        "semantic_family",
        "semantic_slots",
        "slots",
        "target_component",
    }
)
_ACCEPTED_RECONSTRUCTION_STATUSES = frozenset(
    {
        "accepted",
        "kernel_accepted",
        "kernel_verified",
        "native_reconstruction",
        "proved",
        "verified",
    }
)
_PROVED_STATUSES = frozenset({"passed", "proved", "success", "verified"})
_TIMEOUT_STATUSES = frozenset({"deadline_exceeded", "timed_out", "timeout"})
_UNSUPPORTED_STATUSES = frozenset(
    {"translation_failed", "unsupported", "unsupported_translation"}
)
_SUPPORTED_TRANSLATION_STATUSES = frozenset(
    {"passed", "success", "supported", "translated", "verified"}
)
_DRAFT_STATUSES = frozenset({"candidate", "draft", "proposed"})


class HistoricalHammerReplayError(ValueError):
    """Base error for invalid replay input, policy, or state."""


class HistoricalHammerInventoryError(HistoricalHammerReplayError):
    """The historical corpus could not be inventoried deterministically."""


class HistoricalHammerCacheIntegrityError(HistoricalHammerReplayError):
    """A replay cache entry failed its content-address check."""


class HistoricalHammerExecutionError(HistoricalHammerReplayError):
    """A configured current proof executor is malformed or unavailable."""


class ReplayFailureClass(str, Enum):
    """Stable, source-free classifications for replay rejection."""

    NONE = "none"
    INVALID_INPUT = "invalid_input"
    INVENTORY_MISMATCH = "inventory_mismatch"
    CACHE_INTEGRITY = "cache_integrity"
    EXECUTOR_ERROR = "executor_error"
    CANCELLED = "cancelled"
    DRAFT = "draft"
    TIMEOUT = "timeout"
    UNSUPPORTED_TRANSLATION = "unsupported_translation"
    COMPILER_SCHEMA_MISMATCH = "compiler_schema_mismatch"
    STALE_RECEIPT = "stale_receipt"
    RECEIPT_MISMATCH = "receipt_mismatch"
    PROOF_NOT_PROVED = "proof_not_proved"
    PROOF_NOT_CHECKED = "proof_not_checked"
    PROOF_UNTRUSTED = "proof_untrusted"
    TRUST_ROOT_REJECTED = "trust_root_rejected"
    RECONSTRUCTION_MISSING = "reconstruction_missing"
    RECONSTRUCTION_FAILED = "reconstruction_failed"


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise HistoricalHammerReplayError("non-finite values are not canonical JSON")
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=str)]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    return str(value)


def canonical_replay_json(value: Any) -> str:
    """Return the canonical encoding used by replay content addresses."""

    return json.dumps(
        _json_ready(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def replay_content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_replay_json(value).encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _safe_identifier(value: Any, *, fallback: str = "unknown", max_length: int = 240) -> str:
    text = str(getattr(value, "value", value) or "").strip()
    if text and len(text) <= max_length and _SAFE_IDENTIFIER_RE.fullmatch(text):
        return text
    if not text:
        return fallback
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _digest_identifier(value: Any, namespace: str) -> str:
    return f"{namespace}-{replay_content_digest(value)}"


def _normalize_statement(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise HistoricalHammerInventoryError("historical obligation has no statement")
    return text


def _bounded_execution_value(value: Any, *, depth: int = 0) -> Any:
    """Retain only small values needed by the current obligation contract.

    This value is held in memory while executing and is never serialized by a
    public replay object.  Bounding it still prevents a hostile historical
    cycle from expanding replay memory without limit.
    """

    if depth > 4:
        return None
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if not isinstance(value, float) or math.isfinite(value) else None
    if isinstance(value, str):
        return value[:2048]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_item in list(value.items())[:64]:
            key = str(raw_key)
            lowered = key.lower()
            if lowered in _BULKY_OR_UNTRUSTED_KEYS or "decoded" in lowered:
                continue
            bounded = _bounded_execution_value(raw_item, depth=depth + 1)
            if bounded is not None:
                result[key[:128]] = bounded
        return result
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [
            bounded
            for item in list(value)[:64]
            if (bounded := _bounded_execution_value(item, depth=depth + 1)) is not None
        ]
    return str(value)[:512]


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    return {}


def _sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return tuple(value)
    return (value,)


def _statement_from_mapping(value: Mapping[str, Any]) -> str:
    for key in ("statement", "formula", "conjecture", "problem"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return _normalize_statement(candidate)
    goal = value.get("goal")
    if isinstance(goal, str) and goal.strip():
        return _normalize_statement(goal)
    if isinstance(goal, Mapping):
        for key in ("statement", "formula", "text"):
            candidate = goal.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return _normalize_statement(candidate)
    candidate = value.get("obligation")
    if (
        isinstance(candidate, str)
        and candidate.strip()
        and any(
            key in value
            for key in ("kind", "logic_family", "obligation_id", "obligation_type")
        )
    ):
        return _normalize_statement(candidate)
    return ""


def _looks_like_obligation(value: Mapping[str, Any], parent_key: str) -> bool:
    if not _statement_from_mapping(value):
        return False
    keys = {str(key).lower() for key in value}
    explicit_identity = bool(
        keys.intersection(
            {
                "kind",
                "legal_ir_view",
                "logic_family",
                "obligation_id",
                "obligation_type",
            }
        )
    )
    if explicit_identity or parent_key.lower() in _OBLIGATION_COLLECTION_KEYS:
        return True
    if parent_key.lower() == "goal":
        metadata = _mapping(value.get("metadata"))
        return bool(
            value.get("name")
            or value.get("itp_system")
            or metadata.get("obligation_id")
        )
    return False


def _count_artifact_members(value: Any, *, depth: int = 0) -> int:
    if depth > 64:
        return 0
    count = 0
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key).lower()
            if key in _ARTIFACT_COLLECTION_KEYS:
                if isinstance(child, Mapping):
                    count += len(child)
                elif isinstance(child, Sequence) and not isinstance(
                    child, (bytes, bytearray, str)
                ):
                    count += len(child)
                elif child is not None:
                    count += 1
            count += _count_artifact_members(child, depth=depth + 1)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        for child in value:
            count += _count_artifact_members(child, depth=depth + 1)
    return count


def _walk_mappings(
    value: Any,
    *,
    parent_key: str = "",
    pointer: tuple[str, ...] = (),
    depth: int = 0,
) -> Iterator[tuple[Mapping[str, Any], str, tuple[str, ...]]]:
    if depth > 64:
        return
    if isinstance(value, Mapping):
        yield value, parent_key, pointer
        # Once an obligation envelope has been recovered, its nested goal,
        # translation, receipt, and artifact mappings are evidence about that
        # same obligation rather than additional replay candidates.
        if _looks_like_obligation(value, parent_key):
            return
        for raw_key, child in value.items():
            key = str(raw_key)
            yield from _walk_mappings(
                child,
                parent_key=key,
                pointer=(*pointer, key),
                depth=depth + 1,
            )
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        for index, child in enumerate(value):
            yield from _walk_mappings(
                child,
                parent_key=parent_key,
                pointer=(*pointer, str(index)),
                depth=depth + 1,
            )


@dataclass(frozen=True, slots=True)
class HistoricalHammerObligation:
    """One deduplicated historical obligation.

    ``statement`` and ``execution_metadata`` are intentionally excluded from
    :meth:`to_dict`; they exist only for the current executor invocation.
    """

    content_address: str
    kind: str
    legal_ir_view: str
    logic_family: str
    premise_hints: tuple[str, ...]
    source_artifact_digests: tuple[str, ...]
    original_id_digests: tuple[str, ...]
    occurrence_count: int
    statement: str = field(repr=False, compare=False)
    execution_metadata: Mapping[str, Any] = field(
        default_factory=dict, repr=False, compare=False
    )
    schema_version: str = LEGAL_IR_HISTORICAL_HAMMER_INVENTORY_SCHEMA_VERSION

    @property
    def digest(self) -> str:
        return self.content_address.rsplit("-", 1)[-1]

    @property
    def replay_obligation_id(self) -> str:
        return f"historical-hammer-{self.digest[:32]}"

    def to_legal_ir_obligation(self) -> LegalIRProofObligation:
        """Build a fresh current-schema obligation for the current router."""

        return LegalIRProofObligation(
            obligation_id=self.replay_obligation_id,
            statement=self.statement,
            kind=self.kind,
            legal_ir_view=self.legal_ir_view,
            logic_family=self.logic_family,
            premise_hints=list(self.premise_hints),
            metadata=dict(self.execution_metadata),
            schema_version=LEGAL_IR_OBLIGATION_SCHEMA_VERSION,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the source-free public inventory representation."""

        return {
            "content_address": self.content_address,
            "kind": self.kind,
            "legal_ir_view": self.legal_ir_view,
            "logic_family": self.logic_family,
            "occurrence_count": self.occurrence_count,
            "original_id_digests": list(self.original_id_digests),
            "premise_hint_digests": [
                replay_content_digest(item) for item in self.premise_hints
            ],
            "schema_version": self.schema_version,
            "source_artifact_digests": list(self.source_artifact_digests),
        }


def _candidate_from_mapping(
    value: Mapping[str, Any],
    *,
    source_file_digest: str,
    pointer: tuple[str, ...],
) -> HistoricalHammerObligation:
    statement = _statement_from_mapping(value)
    metadata = _mapping(value.get("metadata"))
    kind = _safe_identifier(
        value.get("kind")
        or value.get("obligation_type")
        or metadata.get("obligation_type")
        or metadata.get("obligation_family")
        or "historical_hammer"
    )
    legal_ir_view = _safe_identifier(
        value.get("legal_ir_view")
        or metadata.get("legal_ir_view")
        or metadata.get("target_component")
        or "external_provers.router"
    )
    logic_family = _safe_identifier(
        value.get("logic_family")
        or metadata.get("logic_family")
        or metadata.get("semantic_family")
        or "proof_translation"
    )
    hints = tuple(
        sorted(
            {
                _safe_identifier(item)
                for item in _sequence(
                    value.get("premise_hints")
                    or value.get("selected_premise_families")
                    or ()
                )
                if str(item or "").strip()
            }
        )
    )
    execution_metadata = {
        key: _bounded_execution_value(metadata[key])
        for key in sorted(_EXECUTION_METADATA_KEYS.intersection(metadata))
    }
    identity = {
        "execution_metadata": execution_metadata,
        "kind": kind,
        "legal_ir_view": legal_ir_view,
        "logic_family": logic_family,
        "premise_hints": list(hints),
        "statement": statement,
    }
    digest = replay_content_digest(identity)
    original_id = (
        value.get("obligation_id")
        or metadata.get("obligation_id")
        or value.get("id")
        or ""
    )
    origin = replay_content_digest(
        {
            "file_sha256": source_file_digest,
            "json_pointer_sha256": replay_content_digest(list(pointer)),
        }
    )
    return HistoricalHammerObligation(
        content_address=f"historical-hammer-obligation-{digest}",
        kind=kind,
        legal_ir_view=legal_ir_view,
        logic_family=logic_family,
        premise_hints=hints,
        source_artifact_digests=(origin,),
        original_id_digests=(
            (replay_content_digest(str(original_id)),) if original_id else ()
        ),
        occurrence_count=1,
        statement=statement,
        execution_metadata=execution_metadata,
    )


@dataclass(frozen=True, slots=True)
class HistoricalHammerInventory:
    """Source-free inventory of all supplied historical cycle files."""

    obligations: tuple[HistoricalHammerObligation, ...]
    cycle_file_count: int
    nested_artifact_count: int
    obligation_occurrence_count: int
    duplicate_occurrence_count: int
    malformed_file_count: int
    source_file_digests: tuple[str, ...]
    historically_trusted_count: int = CANONICAL_HISTORICALLY_TRUSTED_COUNT
    schema_version: str = LEGAL_IR_HISTORICAL_HAMMER_INVENTORY_SCHEMA_VERSION

    @property
    def unique_obligation_count(self) -> int:
        return len(self.obligations)

    @property
    def inventory_id(self) -> str:
        payload = {
            "cycle_file_count": self.cycle_file_count,
            "historically_trusted_count": self.historically_trusted_count,
            "nested_artifact_count": self.nested_artifact_count,
            "obligation_addresses": [
                item.content_address for item in self.obligations
            ],
            "schema_version": self.schema_version,
            "source_file_digests": list(self.source_file_digests),
        }
        return f"historical-hammer-inventory-{replay_content_digest(payload)}"

    def to_dict(self, *, include_obligations: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "cycle_file_count": self.cycle_file_count,
            "duplicate_occurrence_count": self.duplicate_occurrence_count,
            "historically_trusted_count": self.historically_trusted_count,
            "inventory_id": self.inventory_id,
            "malformed_file_count": self.malformed_file_count,
            "nested_artifact_count": self.nested_artifact_count,
            "obligation_occurrence_count": self.obligation_occurrence_count,
            "schema_version": self.schema_version,
            "source_file_digests": list(self.source_file_digests),
            "unique_obligation_count": self.unique_obligation_count,
        }
        if include_obligations:
            result["obligations"] = [item.to_dict() for item in self.obligations]
        return result


def discover_historical_cycle_files(
    inputs: Iterable[str | os.PathLike[str]],
) -> tuple[Path, ...]:
    """Resolve JSON/JSONL inputs deterministically without following symlinks."""

    discovered: dict[str, Path] = {}
    for raw in inputs:
        path = Path(raw).expanduser()
        if path.is_file():
            if path.suffix.lower() in {".json", ".jsonl", ".ndjson"}:
                resolved = path.resolve()
                discovered[str(resolved)] = resolved
            continue
        if path.is_dir():
            for candidate in path.rglob("*"):
                if (
                    candidate.is_file()
                    and not candidate.is_symlink()
                    and candidate.suffix.lower() in {".json", ".jsonl", ".ndjson"}
                ):
                    resolved = candidate.resolve()
                    discovered[str(resolved)] = resolved
            continue
        raise HistoricalHammerInventoryError(f"historical input does not exist: {path}")
    if not discovered:
        raise HistoricalHammerInventoryError("no historical JSON cycle files found")
    return tuple(discovered[key] for key in sorted(discovered))


def _payloads_from_file(path: Path) -> tuple[Any, ...]:
    try:
        if path.suffix.lower() in {".jsonl", ".ndjson"}:
            payloads: list[Any] = []
            with path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        payloads.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        raise HistoricalHammerInventoryError(
                            f"invalid JSONL record at line {line_number}"
                        ) from exc
            return tuple(payloads)
        with path.open("r", encoding="utf-8") as handle:
            return (json.load(handle),)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HistoricalHammerInventoryError(
            f"cannot parse historical cycle file sha256={_file_digest(path)}"
        ) from exc


def load_historical_hammer_obligations(
    inputs: Iterable[str | os.PathLike[str]],
    *,
    fail_on_malformed: bool = True,
) -> HistoricalHammerInventory:
    """Scan, content-address, and deduplicate historical Hammer obligations."""

    files = discover_historical_cycle_files(inputs)
    candidates: dict[str, HistoricalHammerObligation] = {}
    occurrence_count = 0
    nested_artifact_count = 0
    malformed = 0
    file_digests: list[str] = []
    for path in files:
        digest = _file_digest(path)
        file_digests.append(digest)
        try:
            payloads = _payloads_from_file(path)
        except HistoricalHammerInventoryError:
            malformed += 1
            if fail_on_malformed:
                raise
            continue
        for payload_index, payload in enumerate(payloads):
            nested_artifact_count += _count_artifact_members(payload)
            for value, parent_key, pointer in _walk_mappings(
                payload, pointer=(str(payload_index),)
            ):
                if not _looks_like_obligation(value, parent_key):
                    continue
                occurrence_count += 1
                candidate = _candidate_from_mapping(
                    value,
                    source_file_digest=digest,
                    pointer=pointer,
                )
                existing = candidates.get(candidate.content_address)
                if existing is None:
                    candidates[candidate.content_address] = candidate
                    continue
                candidates[candidate.content_address] = replace(
                    existing,
                    source_artifact_digests=tuple(
                        sorted(
                            set(existing.source_artifact_digests)
                            | set(candidate.source_artifact_digests)
                        )
                    ),
                    original_id_digests=tuple(
                        sorted(
                            set(existing.original_id_digests)
                            | set(candidate.original_id_digests)
                        )
                    ),
                    occurrence_count=existing.occurrence_count + 1,
                )
    obligations = tuple(candidates[key] for key in sorted(candidates))
    return HistoricalHammerInventory(
        obligations=obligations,
        cycle_file_count=len(files),
        nested_artifact_count=nested_artifact_count,
        obligation_occurrence_count=occurrence_count,
        duplicate_occurrence_count=max(0, occurrence_count - len(obligations)),
        malformed_file_count=malformed,
        source_file_digests=tuple(sorted(file_digests)),
    )


@dataclass(frozen=True, slots=True)
class HistoricalHammerReplayPolicy:
    """Current policy whose fingerprint isolates every replay cache entry."""

    versions: ProofFeedbackVersions = field(default_factory=ProofFeedbackVersions)
    compiler_schema_version: str = LEGAL_IR_OBLIGATION_SCHEMA_VERSION
    solver_policy_fingerprint: str = "unspecified"
    proof_routing_policy_fingerprint: str = "unspecified"
    timeout_seconds: float = 30.0
    max_workers: int = 4
    trusted_proof_checkers: tuple[str, ...] = ()
    trusted_root_ids: tuple[str, ...] = ()
    use_global_solver_budget: bool = True
    resource_wait_timeout_seconds: Optional[float] = None
    expected_cycle_file_count: Optional[int] = None
    expected_nested_artifact_count: Optional[int] = None
    expected_unique_obligation_count: Optional[int] = None
    require_zero_historical_trust: bool = True
    schema_version: str = LEGAL_IR_HISTORICAL_HAMMER_REPLAY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or not math.isfinite(float(self.timeout_seconds))
            or float(self.timeout_seconds) <= 0
        ):
            raise HistoricalHammerReplayError("timeout_seconds must be positive and finite")
        if not isinstance(self.max_workers, int) or isinstance(self.max_workers, bool):
            raise HistoricalHammerReplayError("max_workers must be an integer")
        if self.max_workers <= 0 or self.max_workers > 256:
            raise HistoricalHammerReplayError("max_workers must be between 1 and 256")
        if (
            self.resource_wait_timeout_seconds is not None
            and self.resource_wait_timeout_seconds < 0
        ):
            raise HistoricalHammerReplayError(
                "resource_wait_timeout_seconds cannot be negative"
            )
        for value in (
            self.compiler_schema_version,
            self.solver_policy_fingerprint,
            self.proof_routing_policy_fingerprint,
            *self.trusted_proof_checkers,
            *self.trusted_root_ids,
        ):
            if _safe_identifier(value) != value:
                raise HistoricalHammerReplayError(
                    "schema, checker, and trust-root identifiers must be bounded"
                )
        for expected in (
            self.expected_cycle_file_count,
            self.expected_nested_artifact_count,
            self.expected_unique_obligation_count,
        ):
            if expected is not None and expected < 0:
                raise HistoricalHammerReplayError("expected inventory counts cannot be negative")

    @property
    def fingerprint(self) -> str:
        return replay_content_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "compiler_schema_version": self.compiler_schema_version,
            "proof_routing_policy_fingerprint": self.proof_routing_policy_fingerprint,
            "resource_wait_timeout_seconds": self.resource_wait_timeout_seconds,
            "schema_version": self.schema_version,
            "solver_policy_fingerprint": self.solver_policy_fingerprint,
            "timeout_seconds": float(self.timeout_seconds),
            "trusted_proof_checkers": sorted(set(self.trusted_proof_checkers)),
            "trusted_root_ids": sorted(set(self.trusted_root_ids)),
            "use_global_solver_budget": bool(self.use_global_solver_budget),
            "versions": self.versions.to_dict(),
        }

    def validate_inventory(self, inventory: HistoricalHammerInventory) -> None:
        mismatches: list[str] = []
        expected_pairs = (
            ("cycle_file_count", self.expected_cycle_file_count),
            ("nested_artifact_count", self.expected_nested_artifact_count),
            ("unique_obligation_count", self.expected_unique_obligation_count),
        )
        for name, expected in expected_pairs:
            actual = int(getattr(inventory, name))
            if expected is not None and actual != expected:
                mismatches.append(f"{name}:{actual}!={expected}")
        if self.require_zero_historical_trust and inventory.historically_trusted_count:
            mismatches.append(
                f"historically_trusted_count:{inventory.historically_trusted_count}!=0"
            )
        if mismatches:
            raise HistoricalHammerInventoryError(
                "historical Hammer inventory mismatch: " + ",".join(mismatches)
            )


@dataclass(frozen=True, slots=True)
class ReplayExecutorContext:
    obligation_content_address: str
    execution_key: str
    execution_fingerprint: str
    timeout_seconds: float
    compiler_schema_version: str
    solver_policy_fingerprint: str
    proof_routing_policy_fingerprint: str
    versions: ProofFeedbackVersions
    trusted_proof_checkers: tuple[str, ...]
    trusted_root_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplayExecutorResult:
    """Bounded current-execution receipt accepted by the replay trust gate."""

    status: str
    obligation_content_address: str
    execution_fingerprint: str
    compiler_schema_version: str
    versions_fingerprint: str
    translation_status: str
    backend: str
    backend_proved: bool
    proof_checked: bool
    trusted: bool
    draft: bool
    proof_receipt_id: str
    reconstruction_receipt_id: str
    reconstruction_attempted: bool
    reconstruction_verified: bool
    reconstruction_status: str
    checker: str
    trust_root_id: str
    selected_premise_families: tuple[str, ...] = ()
    route_result: Optional[LegalIRProofRouteResult] = field(
        default=None, repr=False, compare=False
    )
    schema_version: str = LEGAL_IR_HISTORICAL_HAMMER_EXECUTION_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "status",
            "compiler_schema_version",
            "translation_status",
            "backend",
            "proof_receipt_id",
            "reconstruction_receipt_id",
            "reconstruction_status",
            "checker",
            "trust_root_id",
        ):
            value = str(getattr(self, name))
            if value and _safe_identifier(value, fallback="") != value:
                raise HistoricalHammerExecutionError(
                    f"executor result {name} is not a bounded identifier"
                )
        for family in self.selected_premise_families:
            if _safe_identifier(family) != family:
                raise HistoricalHammerExecutionError(
                    "selected premise families must be bounded identifiers"
                )

    def to_cache_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "backend_proved": bool(self.backend_proved),
            "checker": self.checker,
            "compiler_schema_version": self.compiler_schema_version,
            "draft": bool(self.draft),
            "execution_fingerprint": self.execution_fingerprint,
            "obligation_content_address": self.obligation_content_address,
            "proof_checked": bool(self.proof_checked),
            "proof_receipt_id": self.proof_receipt_id,
            "reconstruction_attempted": bool(self.reconstruction_attempted),
            "reconstruction_receipt_id": self.reconstruction_receipt_id,
            "reconstruction_status": self.reconstruction_status,
            "reconstruction_verified": bool(self.reconstruction_verified),
            "schema_version": self.schema_version,
            "selected_premise_families": list(self.selected_premise_families),
            "status": self.status,
            "translation_status": self.translation_status,
            "trust_root_id": self.trust_root_id,
            "trusted": bool(self.trusted),
            "versions_fingerprint": self.versions_fingerprint,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ReplayExecutorResult":
        receipt = _mapping(
            value.get("reconstruction_receipt")
            or value.get("receipt")
            or value.get("fresh_receipt")
        )
        reconstruction = _mapping(value.get("reconstruction"))
        proof = _mapping(value.get("proof_receipt") or value.get("proof"))

        def first(*items: Any, default: Any = "") -> Any:
            return next((item for item in items if item is not None and item != ""), default)

        raw_status = first(
            value.get("status"), proof.get("status"), default="unknown"
        )
        status = _safe_identifier(
            str(getattr(raw_status, "value", raw_status)).lower()
        )
        reconstruction_status = _safe_identifier(
            str(
                first(
                    value.get("reconstruction_status"),
                    receipt.get("reconstruction_status"),
                    receipt.get("outcome"),
                    reconstruction.get("status"),
                    default="not_attempted",
                )
            ).lower()
        )
        checker = _safe_identifier(
            first(value.get("checker"), receipt.get("checker"), proof.get("checker"), default=""),
            fallback="",
        )
        return cls(
            status=status,
            obligation_content_address=str(
                first(
                    value.get("obligation_content_address"),
                    receipt.get("obligation_content_address"),
                    default="",
                )
            ),
            execution_fingerprint=str(
                first(
                    value.get("execution_fingerprint"),
                    receipt.get("execution_fingerprint"),
                    default="",
                )
            ),
            compiler_schema_version=_safe_identifier(
                first(
                    value.get("compiler_schema_version"),
                    receipt.get("compiler_schema_version"),
                    default="unknown",
                )
            ),
            versions_fingerprint=str(
                first(
                    value.get("versions_fingerprint"),
                    receipt.get("versions_fingerprint"),
                    default="",
                )
            ),
            translation_status=_safe_identifier(
                str(
                    first(
                        value.get("translation_status"),
                        receipt.get("translation_status"),
                        default="success",
                    )
                ).lower()
            ),
            backend=_safe_identifier(
                first(value.get("backend"), receipt.get("backend"), default="unknown")
            ),
            backend_proved=bool(
                first(
                    value.get("backend_proved"),
                    receipt.get("backend_proved"),
                    proof.get("proved"),
                    default=False,
                )
            ),
            proof_checked=bool(
                first(
                    value.get("proof_checked"),
                    proof.get("proof_checked"),
                    proof.get("verified"),
                    default=False,
                )
            ),
            trusted=bool(
                first(value.get("trusted"), receipt.get("trusted"), default=False)
            ),
            draft=bool(
                first(
                    value.get("draft"),
                    proof.get("draft"),
                    default=status in _DRAFT_STATUSES,
                )
            ),
            proof_receipt_id=_safe_identifier(
                first(
                    value.get("proof_receipt_id"),
                    proof.get("receipt_id"),
                    default="",
                ),
                fallback="",
            ),
            reconstruction_receipt_id=_safe_identifier(
                first(
                    value.get("reconstruction_receipt_id"),
                    receipt.get("receipt_id"),
                    default="",
                ),
                fallback="",
            ),
            reconstruction_attempted=bool(
                first(
                    value.get("reconstruction_attempted"),
                    receipt.get("native_reconstruction"),
                    reconstruction.get("attempted"),
                    default=False,
                )
            ),
            reconstruction_verified=bool(
                first(
                    value.get("reconstruction_verified"),
                    receipt.get("native_reconstruction_verified"),
                    reconstruction.get("verified"),
                    default=False,
                )
            ),
            reconstruction_status=reconstruction_status,
            checker=checker,
            trust_root_id=_safe_identifier(
                first(
                    value.get("trust_root_id"),
                    receipt.get("trust_root_id"),
                    checker,
                    default="",
                ),
                fallback="",
            ),
            selected_premise_families=tuple(
                sorted(
                    {
                        _safe_identifier(item)
                        for item in _sequence(
                            value.get("selected_premise_families") or ()
                        )
                        if str(item or "").strip()
                    }
                )
            ),
        )

    @classmethod
    def from_route_result(
        cls,
        route_result: LegalIRProofRouteResult,
        *,
        candidate: HistoricalHammerObligation,
        context: ReplayExecutorContext,
        trust_root_id: str = "",
    ) -> "ReplayExecutorResult":
        receipt = reconstruction_receipt_from_hammer_result(
            route_result.hammer_result,
            obligation_id=candidate.replay_obligation_id,
            trusted_requires_reconstruction=True,
        )
        status = str(getattr(route_result.status, "value", route_result.status)).lower()
        backend = receipt.backend or "unknown"
        checker = _safe_identifier(receipt.checker, fallback="")
        receipt_id = _safe_identifier(receipt.receipt_id, fallback="")
        proof_receipt_id = _safe_identifier(
            _digest_identifier(
                {
                    "backend": backend,
                    "obligation": candidate.content_address,
                    "reconstruction_receipt_id": receipt_id,
                },
                "fresh-proof-receipt",
            )
        )
        selected_premise_families: set[str] = set()
        selection = getattr(route_result.hammer_result, "premise_selection", None)
        for premise in getattr(selection, "selected", ()) or ():
            metadata = _mapping(getattr(premise, "metadata", {}))
            family = next(
                (
                    metadata[key]
                    for key in (
                        "premise_family",
                        "premise_kind",
                        "logic_family",
                        "legal_ir_view",
                        "source_module",
                    )
                    if metadata.get(key)
                ),
                "",
            )
            if family:
                selected_premise_families.add(_safe_identifier(family))
        return cls(
            status=_safe_identifier(status),
            obligation_content_address=candidate.content_address,
            execution_fingerprint=context.execution_fingerprint,
            compiler_schema_version=context.compiler_schema_version,
            versions_fingerprint=context.versions.fingerprint,
            translation_status=(
                "unsupported_translation"
                if receipt.translation_failed
                else "success"
                if receipt.translation_succeeded
                else "unknown"
            ),
            backend=_safe_identifier(backend),
            backend_proved=receipt.backend_proved,
            proof_checked=bool(
                receipt.native_reconstruction_verified
                and route_result.trust_level >= ProofTrustLevel.KERNEL
            ),
            trusted=receipt.trusted,
            draft=False,
            proof_receipt_id=proof_receipt_id,
            reconstruction_receipt_id=receipt_id,
            reconstruction_attempted=receipt.native_reconstruction,
            reconstruction_verified=receipt.native_reconstruction_verified,
            reconstruction_status=_safe_identifier(
                str(receipt.reconstruction_status or receipt.outcome.value).lower()
            ),
            checker=checker,
            trust_root_id=_safe_identifier(
                trust_root_id or checker,
                fallback="",
            ),
            selected_premise_families=tuple(sorted(selected_premise_families)),
            route_result=route_result,
        )


class HistoricalHammerExecutor(Protocol):
    def __call__(
        self,
        candidate: HistoricalHammerObligation,
        context: ReplayExecutorContext,
    ) -> ReplayExecutorResult | LegalIRProofRouteResult | Mapping[str, Any]: ...


class CurrentLegalIRHammerExecutor:
    """Adapter from a current :class:`LegalIRProofRouter` to replay results."""

    # SolverPortfolio obtains the authoritative process-safe lease.  The
    # coordinator inspects this marker to avoid charging the same execution as
    # a second root lease (which could deadlock a one-slot global budget).
    manages_global_solver_budget = True

    def __init__(
        self,
        proof_router: Any,
        *,
        premises: Sequence[Any] | Callable[[HistoricalHammerObligation], Sequence[Any]] = (),
        sample_or_document: Any = None,
        trust_root_id: str = "",
    ) -> None:
        if not callable(getattr(proof_router, "route", None)):
            raise HistoricalHammerExecutionError("proof_router must expose route(...)")
        self.proof_router = proof_router
        self.premises = premises
        self.sample_or_document = sample_or_document
        self.trust_root_id = trust_root_id

    def __call__(
        self,
        candidate: HistoricalHammerObligation,
        context: ReplayExecutorContext,
    ) -> ReplayExecutorResult:
        router_policy = getattr(self.proof_router, "policy", None)
        configured_timeout = getattr(router_policy, "total_timeout_seconds", None)
        if configured_timeout is not None and not math.isclose(
            float(configured_timeout),
            float(context.timeout_seconds),
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise HistoricalHammerExecutionError(
                "current proof router timeout does not match replay policy"
            )
        if (
            router_policy is not None
            and context.proof_routing_policy_fingerprint != "unspecified"
        ):
            to_dict = getattr(router_policy, "to_dict", None)
            if not callable(to_dict) or replay_content_digest(
                to_dict()
            ) != context.proof_routing_policy_fingerprint:
                raise HistoricalHammerExecutionError(
                    "current proof router policy fingerprint does not match replay policy"
                )
        obligation = candidate.to_legal_ir_obligation()
        goal = HammerGoal(
            candidate.statement,
            name=candidate.replay_obligation_id,
            metadata={
                "obligation_id": candidate.replay_obligation_id,
                "replay_content_address": candidate.content_address,
            },
        )
        premises = (
            self.premises(candidate) if callable(self.premises) else self.premises
        )
        route_result = self.proof_router.route(
            obligation,
            goal,
            tuple(premises),
            sample_or_document=self.sample_or_document,
        )
        return ReplayExecutorResult.from_route_result(
            route_result,
            candidate=candidate,
            context=context,
            trust_root_id=self.trust_root_id,
        )


def load_replay_executor(specification: str) -> HistoricalHammerExecutor:
    """Load ``module:attribute`` without evaluating arbitrary expressions."""

    module_name, separator, attribute_name = str(specification).partition(":")
    if (
        not separator
        or not module_name
        or not attribute_name
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", module_name)
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", attribute_name)
    ):
        raise HistoricalHammerExecutionError(
            "executor must use the form package.module:callable"
        )
    try:
        value = getattr(importlib.import_module(module_name), attribute_name)
    except (ImportError, AttributeError) as exc:
        raise HistoricalHammerExecutionError(
            f"cannot load replay executor {module_name}:{attribute_name}"
        ) from exc
    if not callable(value):
        raise HistoricalHammerExecutionError("loaded replay executor is not callable")
    return value


def _classify_result(
    result: ReplayExecutorResult,
    *,
    candidate: HistoricalHammerObligation,
    context: ReplayExecutorContext,
) -> ReplayFailureClass:
    status = result.status.lower()
    translation = result.translation_status.lower()
    reconstruction_status = result.reconstruction_status.lower()
    if result.draft or status in _DRAFT_STATUSES:
        return ReplayFailureClass.DRAFT
    if status == "cancelled":
        return ReplayFailureClass.CANCELLED
    if status in _TIMEOUT_STATUSES:
        return ReplayFailureClass.TIMEOUT
    if status in _UNSUPPORTED_STATUSES or translation in _UNSUPPORTED_STATUSES:
        return ReplayFailureClass.UNSUPPORTED_TRANSLATION
    if translation not in _SUPPORTED_TRANSLATION_STATUSES:
        return ReplayFailureClass.UNSUPPORTED_TRANSLATION
    if result.compiler_schema_version != context.compiler_schema_version:
        return ReplayFailureClass.COMPILER_SCHEMA_MISMATCH
    if (
        result.execution_fingerprint != context.execution_fingerprint
        or result.versions_fingerprint != context.versions.fingerprint
    ):
        return ReplayFailureClass.STALE_RECEIPT
    if result.obligation_content_address != candidate.content_address:
        return ReplayFailureClass.RECEIPT_MISMATCH
    if status not in _PROVED_STATUSES or not result.backend_proved:
        return ReplayFailureClass.PROOF_NOT_PROVED
    if not result.proof_checked:
        return ReplayFailureClass.PROOF_NOT_CHECKED
    if not result.trusted:
        return ReplayFailureClass.PROOF_UNTRUSTED
    if (
        context.trusted_proof_checkers
        and result.checker not in context.trusted_proof_checkers
    ):
        return ReplayFailureClass.TRUST_ROOT_REJECTED
    if context.trusted_root_ids and result.trust_root_id not in context.trusted_root_ids:
        return ReplayFailureClass.TRUST_ROOT_REJECTED
    if not result.proof_receipt_id or not result.reconstruction_receipt_id:
        return ReplayFailureClass.STALE_RECEIPT
    if not result.reconstruction_attempted:
        return ReplayFailureClass.RECONSTRUCTION_MISSING
    if (
        not result.reconstruction_verified
        or reconstruction_status not in _ACCEPTED_RECONSTRUCTION_STATUSES
    ):
        return ReplayFailureClass.RECONSTRUCTION_FAILED
    return ReplayFailureClass.NONE


def _feedback_record(
    candidate: HistoricalHammerObligation,
    result: ReplayExecutorResult,
    policy: HistoricalHammerReplayPolicy,
) -> LegalIRProofFeedbackRecord:
    metadata = dict(candidate.execution_metadata)
    slots = metadata.get("semantic_slots") or metadata.get("slots") or {}
    if not isinstance(slots, Mapping):
        slots = {}
    kernel = KernelReconstructionFeedback(
        status=result.reconstruction_status,
        attempted=True,
        verified=True,
        checker=result.checker,
        receipt_id=result.reconstruction_receipt_id,
    )
    return LegalIRProofFeedbackRecord.create(
        obligation_id=candidate.replay_obligation_id,
        obligation_type=candidate.kind,
        legal_ir_view=candidate.legal_ir_view,
        semantic_family=candidate.logic_family,
        semantic_slots=slots,
        selected_premise_families=result.selected_premise_families,
        route_availability={"historical_replay_current_hammer": True},
        route_statuses={"historical_replay_current_hammer": "proved"},
        backend_outcomes={result.backend: "proved"},
        kernel_reconstruction=kernel,
        deterministic_trusted=False,
        repair_label="historical_obligation_replay",
        evidence_ids=(
            result.proof_receipt_id,
            f"historical-replay-policy-{policy.fingerprint}",
        ),
        receipt_ids=(result.reconstruction_receipt_id,),
        obligation_digest=candidate.digest,
        partition_key=candidate.content_address,
        versions=policy.versions,
    )


@dataclass(frozen=True, slots=True)
class HistoricalHammerReplayOutcome:
    obligation_content_address: str
    execution_key: str
    failure_class: ReplayFailureClass
    executor_result: Optional[ReplayExecutorResult]
    feedback_record: Optional[LegalIRProofFeedbackRecord]
    cache_hit: bool = False

    @property
    def trusted_feedback_emitted(self) -> bool:
        return self.feedback_record is not None

    @property
    def outcome_id(self) -> str:
        payload = {
            "execution_key": self.execution_key,
            "failure_class": self.failure_class.value,
            "feedback_record_id": (
                self.feedback_record.record_id if self.feedback_record else ""
            ),
            "obligation_content_address": self.obligation_content_address,
            "schema_version": LEGAL_IR_HISTORICAL_HAMMER_REPLAY_SCHEMA_VERSION,
        }
        return f"historical-hammer-replay-outcome-{replay_content_digest(payload)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_hit": bool(self.cache_hit),
            "execution_key": self.execution_key,
            "failure_class": self.failure_class.value,
            "feedback_record_id": (
                self.feedback_record.record_id if self.feedback_record else ""
            ),
            "obligation_content_address": self.obligation_content_address,
            "outcome_id": self.outcome_id,
            "trusted_feedback_emitted": self.trusted_feedback_emitted,
        }


class HistoricalHammerReplayCache:
    """Atomic, integrity-checked, policy-isolated replay result cache."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.entries = self.root / "results"

    def path_for(self, execution_key: str) -> Path:
        if not execution_key.startswith("historical-hammer-execution-"):
            raise HistoricalHammerCacheIntegrityError("invalid replay execution key")
        return self.entries / f"{execution_key}.json"

    def get(self, execution_key: str) -> Optional[ReplayExecutorResult]:
        path = self.path_for(execution_key)
        if not path.exists():
            return None
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(envelope, Mapping):
                raise TypeError("cache envelope is not an object")
            result_payload = envelope.get("result")
            if not isinstance(result_payload, Mapping):
                raise TypeError("cache result is not an object")
            addressed = {
                "execution_key": execution_key,
                "result": result_payload,
                "schema_version": LEGAL_IR_HISTORICAL_HAMMER_CACHE_SCHEMA_VERSION,
            }
            if envelope.get("schema_version") != LEGAL_IR_HISTORICAL_HAMMER_CACHE_SCHEMA_VERSION:
                raise ValueError("cache schema mismatch")
            if envelope.get("execution_key") != execution_key:
                raise ValueError("cache execution key mismatch")
            if envelope.get("content_sha256") != replay_content_digest(addressed):
                raise ValueError("cache digest mismatch")
            return ReplayExecutorResult.from_mapping(result_payload)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise HistoricalHammerCacheIntegrityError(
                f"invalid replay cache entry {execution_key}"
            ) from exc

    def put(self, execution_key: str, result: ReplayExecutorResult) -> bool:
        path = self.path_for(execution_key)
        self.entries.mkdir(parents=True, exist_ok=True)
        addressed = {
            "execution_key": execution_key,
            "result": result.to_cache_dict(),
            "schema_version": LEGAL_IR_HISTORICAL_HAMMER_CACHE_SCHEMA_VERSION,
        }
        envelope = {
            **addressed,
            "content_sha256": replay_content_digest(addressed),
        }
        encoded = (canonical_replay_json(envelope) + "\n").encode("utf-8")
        if path.exists():
            existing = self.get(execution_key)
            if existing is None or existing.to_cache_dict() != result.to_cache_dict():
                raise HistoricalHammerCacheIntegrityError(
                    f"replay cache collision at {execution_key}"
                )
            return False
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".historical-hammer-replay-",
            suffix=".tmp",
            dir=self.entries,
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            if path.exists():
                existing = self.get(execution_key)
                if existing is None or existing.to_cache_dict() != result.to_cache_dict():
                    raise HistoricalHammerCacheIntegrityError(
                        f"replay cache collision at {execution_key}"
                    )
                return False
            os.replace(temporary_name, path)
            temporary_name = ""
            return True
        finally:
            if temporary_name:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass


@dataclass(frozen=True, slots=True)
class HistoricalHammerReplayReport:
    inventory: HistoricalHammerInventory
    policy_fingerprint: str
    outcomes: tuple[HistoricalHammerReplayOutcome, ...]
    feedback_replay: ProofFeedbackReplay
    schema_version: str = LEGAL_IR_HISTORICAL_HAMMER_REPLAY_SCHEMA_VERSION

    @property
    def failure_counts(self) -> Mapping[str, int]:
        counts = Counter(item.failure_class.value for item in self.outcomes)
        return dict(sorted(counts.items()))

    @property
    def report_id(self) -> str:
        payload = {
            "feedback_replay_id": self.feedback_replay.replay_id,
            "inventory_id": self.inventory.inventory_id,
            "outcome_ids": [item.outcome_id for item in self.outcomes],
            "policy_fingerprint": self.policy_fingerprint,
            "schema_version": self.schema_version,
        }
        return f"historical-hammer-replay-report-{replay_content_digest(payload)}"

    def to_dict(self, *, include_inventory_obligations: bool = False) -> dict[str, Any]:
        return {
            "cache_hit_count": sum(item.cache_hit for item in self.outcomes),
            "failure_counts": dict(self.failure_counts),
            "feedback": self.feedback_replay.to_dict(include_records=False),
            "inventory": self.inventory.to_dict(
                include_obligations=include_inventory_obligations
            ),
            "outcomes": [item.to_dict() for item in self.outcomes],
            "policy_fingerprint": self.policy_fingerprint,
            "replayed_obligation_count": len(self.outcomes),
            "report_id": self.report_id,
            "schema_version": self.schema_version,
            "trusted_feedback_count": len(self.feedback_replay.records),
        }


def _atomic_json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_replay_json(value))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = ""
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


class HistoricalHammerProofFeedbackReplay:
    """Resumable parallel coordinator for current-policy obligation replay."""

    def __init__(
        self,
        executor: HistoricalHammerExecutor,
        *,
        state_dir: str | os.PathLike[str],
        policy: Optional[HistoricalHammerReplayPolicy] = None,
        feedback_store: Optional[ProofFeedbackStore] = None,
        resource_scheduler: Optional[GlobalResourceScheduler] = None,
    ) -> None:
        if not callable(executor):
            raise HistoricalHammerExecutionError("executor must be callable")
        self.executor = executor
        self.state_dir = Path(state_dir)
        self.policy = policy or HistoricalHammerReplayPolicy()
        self.cache = HistoricalHammerReplayCache(self.state_dir / "cache")
        self.feedback_store = feedback_store or ProofFeedbackStore(
            self.state_dir / "proof-feedback"
        )
        self.resource_scheduler = (
            resource_scheduler
            if resource_scheduler is not None
            else (
                get_global_resource_scheduler()
                if self.policy.use_global_solver_budget
                else None
            )
        )
        self._checkpoint_lock = threading.Lock()

    def _execution_key(self, candidate: HistoricalHammerObligation) -> str:
        return _digest_identifier(
            {
                "obligation_content_address": candidate.content_address,
                "policy_fingerprint": self.policy.fingerprint,
                "schema_version": LEGAL_IR_HISTORICAL_HAMMER_REPLAY_SCHEMA_VERSION,
            },
            "historical-hammer-execution",
        )

    def _context(
        self, candidate: HistoricalHammerObligation, execution_key: str
    ) -> ReplayExecutorContext:
        return ReplayExecutorContext(
            obligation_content_address=candidate.content_address,
            execution_key=execution_key,
            execution_fingerprint=self.policy.fingerprint,
            timeout_seconds=float(self.policy.timeout_seconds),
            compiler_schema_version=self.policy.compiler_schema_version,
            solver_policy_fingerprint=self.policy.solver_policy_fingerprint,
            proof_routing_policy_fingerprint=(
                self.policy.proof_routing_policy_fingerprint
            ),
            versions=self.policy.versions,
            trusted_proof_checkers=tuple(
                sorted(set(self.policy.trusted_proof_checkers))
            ),
            trusted_root_ids=tuple(sorted(set(self.policy.trusted_root_ids))),
        )

    def _coerce_result(
        self,
        raw: ReplayExecutorResult | LegalIRProofRouteResult | Mapping[str, Any],
        *,
        candidate: HistoricalHammerObligation,
        context: ReplayExecutorContext,
    ) -> ReplayExecutorResult:
        if isinstance(raw, ReplayExecutorResult):
            return raw
        if isinstance(raw, LegalIRProofRouteResult):
            return ReplayExecutorResult.from_route_result(
                raw, candidate=candidate, context=context
            )
        if isinstance(raw, Mapping):
            return ReplayExecutorResult.from_mapping(raw)
        raise HistoricalHammerExecutionError(
            f"executor returned unsupported type {type(raw).__name__}"
        )

    def _execute_one(
        self,
        candidate: HistoricalHammerObligation,
        execution_key: str,
    ) -> ReplayExecutorResult:
        context = self._context(candidate, execution_key)
        lease_context: Any = nullcontext()
        if self.policy.use_global_solver_budget and not bool(
            getattr(self.executor, "manages_global_solver_budget", False)
        ):
            if self.resource_scheduler is None:
                raise HistoricalHammerExecutionError(
                    "global solver budget is enabled without a scheduler"
                )
            lease_context = self.resource_scheduler.acquire(
                ResourceLane.HAMMER.value,
                cpu_slots=1,
                memory_mb=0,
                timeout=self.policy.resource_wait_timeout_seconds,
                request_id=execution_key,
            )
        with lease_context:
            raw = self.executor(candidate, context)
        return self._coerce_result(raw, candidate=candidate, context=context)

    def _outcome(
        self,
        candidate: HistoricalHammerObligation,
        execution_key: str,
        result: ReplayExecutorResult,
        *,
        cache_hit: bool,
    ) -> HistoricalHammerReplayOutcome:
        context = self._context(candidate, execution_key)
        failure = _classify_result(result, candidate=candidate, context=context)
        feedback = (
            _feedback_record(candidate, result, self.policy)
            if failure == ReplayFailureClass.NONE
            else None
        )
        return HistoricalHammerReplayOutcome(
            obligation_content_address=candidate.content_address,
            execution_key=execution_key,
            failure_class=failure,
            executor_result=result,
            feedback_record=feedback,
            cache_hit=cache_hit,
        )

    def _failure_outcome(
        self,
        candidate: HistoricalHammerObligation,
        execution_key: str,
        failure: ReplayFailureClass,
    ) -> HistoricalHammerReplayOutcome:
        return HistoricalHammerReplayOutcome(
            obligation_content_address=candidate.content_address,
            execution_key=execution_key,
            failure_class=failure,
            executor_result=None,
            feedback_record=None,
        )

    def _checkpoint(
        self,
        inventory: HistoricalHammerInventory,
        outcomes: Iterable[HistoricalHammerReplayOutcome],
    ) -> None:
        ordered = sorted(outcomes, key=lambda item: item.obligation_content_address)
        payload = {
            "completed_execution_keys": [item.execution_key for item in ordered],
            "failure_counts": dict(
                sorted(Counter(item.failure_class.value for item in ordered).items())
            ),
            "inventory_id": inventory.inventory_id,
            "policy_fingerprint": self.policy.fingerprint,
            "schema_version": LEGAL_IR_HISTORICAL_HAMMER_REPLAY_SCHEMA_VERSION,
        }
        with self._checkpoint_lock:
            _atomic_json_write(self.state_dir / "checkpoint.json", payload)

    def run(
        self,
        inputs: Iterable[str | os.PathLike[str]]
        | HistoricalHammerInventory,
        *,
        report_path: Optional[str | os.PathLike[str]] = None,
    ) -> HistoricalHammerReplayReport:
        inventory = (
            inputs
            if isinstance(inputs, HistoricalHammerInventory)
            else load_historical_hammer_obligations(inputs)
        )
        self.policy.validate_inventory(inventory)
        outcomes: dict[str, HistoricalHammerReplayOutcome] = {}
        pending: list[tuple[HistoricalHammerObligation, str]] = []
        for candidate in inventory.obligations:
            execution_key = self._execution_key(candidate)
            try:
                cached = self.cache.get(execution_key)
            except HistoricalHammerCacheIntegrityError:
                outcomes[candidate.content_address] = self._failure_outcome(
                    candidate, execution_key, ReplayFailureClass.CACHE_INTEGRITY
                )
                continue
            if cached is None:
                pending.append((candidate, execution_key))
            else:
                outcomes[candidate.content_address] = self._outcome(
                    candidate, execution_key, cached, cache_hit=True
                )
        self._checkpoint(inventory, outcomes.values())

        if pending:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(self.policy.max_workers, len(pending)),
                thread_name_prefix="historical-hammer-replay",
            ) as pool:
                futures = {
                    pool.submit(self._execute_one, candidate, execution_key): (
                        candidate,
                        execution_key,
                    )
                    for candidate, execution_key in pending
                }
                for future in concurrent.futures.as_completed(futures):
                    candidate, execution_key = futures[future]
                    try:
                        result = future.result()
                        self.cache.put(execution_key, result)
                        outcome = self._outcome(
                            candidate, execution_key, result, cache_hit=False
                        )
                    except HistoricalHammerCacheIntegrityError:
                        outcome = self._failure_outcome(
                            candidate,
                            execution_key,
                            ReplayFailureClass.CACHE_INTEGRITY,
                        )
                    except (LeaseTimeoutError, TimeoutError):
                        outcome = self._failure_outcome(
                            candidate,
                            execution_key,
                            ReplayFailureClass.TIMEOUT,
                        )
                    except (
                        LeaseCancelledError,
                        concurrent.futures.CancelledError,
                    ):
                        outcome = self._failure_outcome(
                            candidate,
                            execution_key,
                            ReplayFailureClass.CANCELLED,
                        )
                    except Exception:
                        # Exception text can contain source, solver output, a
                        # temporary path, or other nondeterministic details.
                        # Persist only this stable class.
                        outcome = self._failure_outcome(
                            candidate,
                            execution_key,
                            ReplayFailureClass.EXECUTOR_ERROR,
                        )
                    outcomes[candidate.content_address] = outcome
                    self._checkpoint(inventory, outcomes.values())

        ordered = tuple(outcomes[key] for key in sorted(outcomes))
        records = tuple(
            item.feedback_record
            for item in ordered
            if item.feedback_record is not None
        )
        self.feedback_store.put_many(records)
        feedback_replay = ProofFeedbackReplay.create(records)
        report = HistoricalHammerReplayReport(
            inventory=inventory,
            policy_fingerprint=self.policy.fingerprint,
            outcomes=ordered,
            feedback_replay=feedback_replay,
        )
        destination = (
            Path(report_path)
            if report_path is not None
            else self.state_dir / "replay-report.json"
        )
        _atomic_json_write(destination, report.to_dict())
        return report


def replay_historical_hammer_obligations(
    inputs: Iterable[str | os.PathLike[str]] | HistoricalHammerInventory,
    *,
    executor: HistoricalHammerExecutor,
    state_dir: str | os.PathLike[str],
    policy: Optional[HistoricalHammerReplayPolicy] = None,
    report_path: Optional[str | os.PathLike[str]] = None,
    feedback_store: Optional[ProofFeedbackStore] = None,
    resource_scheduler: Optional[GlobalResourceScheduler] = None,
) -> HistoricalHammerReplayReport:
    """Convenience entry point for one complete historical replay."""

    coordinator = HistoricalHammerProofFeedbackReplay(
        executor,
        state_dir=state_dir,
        policy=policy,
        feedback_store=feedback_store,
        resource_scheduler=resource_scheduler,
    )
    return coordinator.run(inputs, report_path=report_path)


def write_historical_hammer_replay_json(
    path: str | os.PathLike[str],
    value: HistoricalHammerInventory | HistoricalHammerReplayReport | Mapping[str, Any],
) -> None:
    """Atomically write a source-free inventory, report, or public mapping."""

    if isinstance(value, HistoricalHammerInventory):
        payload: Any = value.to_dict()
    elif isinstance(value, HistoricalHammerReplayReport):
        payload = value.to_dict()
    else:
        payload = dict(value)
    _atomic_json_write(Path(path), payload)


# Domain-readable aliases retained for operational callers and later migration
# gates.  The longer class names make the historical trust boundary explicit;
# these aliases keep configuration wiring concise.
HistoricalHammerReplayConfig = HistoricalHammerReplayPolicy
HistoricalHammerReplayRunner = HistoricalHammerProofFeedbackReplay
inventory_historical_hammer_obligations = load_historical_hammer_obligations
replay_historical_hammer_proof_feedback = replay_historical_hammer_obligations


__all__ = [
    "CANONICAL_HISTORICAL_CYCLE_FILE_COUNT",
    "CANONICAL_HISTORICAL_NESTED_ARTIFACT_COUNT",
    "CANONICAL_HISTORICAL_UNIQUE_OBLIGATION_COUNT",
    "CANONICAL_HISTORICALLY_TRUSTED_COUNT",
    "LEGAL_IR_HISTORICAL_HAMMER_CACHE_SCHEMA_VERSION",
    "LEGAL_IR_HISTORICAL_HAMMER_EXECUTION_RESULT_SCHEMA_VERSION",
    "LEGAL_IR_HISTORICAL_HAMMER_INVENTORY_SCHEMA_VERSION",
    "LEGAL_IR_HISTORICAL_HAMMER_REPLAY_SCHEMA_VERSION",
    "CurrentLegalIRHammerExecutor",
    "HistoricalHammerCacheIntegrityError",
    "HistoricalHammerExecutionError",
    "HistoricalHammerExecutor",
    "HistoricalHammerInventory",
    "HistoricalHammerInventoryError",
    "HistoricalHammerObligation",
    "HistoricalHammerProofFeedbackReplay",
    "HistoricalHammerReplayCache",
    "HistoricalHammerReplayConfig",
    "HistoricalHammerReplayError",
    "HistoricalHammerReplayOutcome",
    "HistoricalHammerReplayPolicy",
    "HistoricalHammerReplayReport",
    "HistoricalHammerReplayRunner",
    "ReplayExecutorContext",
    "ReplayExecutorResult",
    "ReplayFailureClass",
    "canonical_replay_json",
    "discover_historical_cycle_files",
    "load_historical_hammer_obligations",
    "load_replay_executor",
    "inventory_historical_hammer_obligations",
    "replay_content_digest",
    "replay_historical_hammer_obligations",
    "replay_historical_hammer_proof_feedback",
    "write_historical_hammer_replay_json",
]
