"""Build minimized surviving-mutant reports with bounded reproduction evidence (AAE-031).

Interface surface:

* ``build_surviving_mutant_report@1`` — seal a ``SurvivingMutantReport@1`` from a
  bounded observation subject. The report always binds the smallest changed
  source region, symbol identities, violated/missing property, detectors run
  and omitted, smallest reproducing input, expected/observed behavior delta,
  source spans, dependency path, proof/receipt IDs, reproduction command, and
  risk. Full execution logs are excluded from the durable report and model
  context unless bounded minimization fails explicitly, in which case only a
  log digest CID (never the full log body) may be referenced.

Authority rules (normative):

* Pure and deterministic: no store, worktree, network, or production-policy
  mutation.
* Canonical identity comes only from ``software_contracts.content``.
* Incomplete observation fails closed.
* Full-log / raw-log / unbounded-output fields are rejected.
* Minimization failure is explicit via ``MinimizedEvidenceBinding``.
* Closed risk taxonomy fails closed on unknowns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Mapping, Sequence
import re
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    AssuranceArtifactHeader,
    AssuranceBaseError,
    GeneratorIdentity,
    VersionBinding,
    reject_private_model_authority_and_host_fallbacks,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.analysis_contracts import (
    AnalysisContractError,
    MAX_COMMAND_CHARS,
    MAX_DEPENDENCY_PATH,
    MAX_DETECTORS,
    MAX_SPANS,
    MinimizedEvidenceBinding,
    SourceSpan,
    SurvivingMutantReport,
    SurvivorRiskClass,
    verify_survivor_report_identity,
)

# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

BUILD_SURVIVING_MUTANT_REPORT_INTERFACE: Final[str] = (
    "build_surviving_mutant_report@1"
)

SURVIVOR_MINIMIZATION_SUBJECT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-survivor-minimization-subject@1"
)
SURVIVOR_MINIMIZATION_SUBJECT_INTERFACE: Final[str] = "SurvivorMinimizationSubject@1"
BOUNDED_LOG_DIGEST_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-bounded-log-digest@1"
)
SURVIVOR_REPORT_BUILD_RESULT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-survivor-report-build-result@1"
)
SURVIVOR_REPORT_BUILD_RESULT_INTERFACE: Final[str] = "SurvivorReportBuildResult@1"

GENERATOR_ID: Final[str] = "survivor_minimization"
GENERATOR_VERSION: Final[str] = "1.0.0"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_LIST: Final[int] = 1_024
MAX_EVIDENCE_CIDS: Final[int] = 256
MAX_PROOF_CIDS: Final[int] = 256
MAX_RECEIPT_CIDS: Final[int] = 256
MAX_DECLARED_LOG_BYTES: Final[int] = 1_048_576  # 1 MiB declared bound
MAX_LOG_DIGEST_NOTES: Final[int] = 512

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_SYMBOL_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+@#$-]{0,511}$"
)

# Field-name markers that must never appear on durable survivor reports or
# builder subjects. Full logs stay out of model context (plan §9).
FULL_LOG_FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "complete_log",
        "complete_logs",
        "execution_log",
        "execution_logs",
        "full_execution_log",
        "full_log",
        "full_logs",
        "full_stdout",
        "full_stderr",
        "full_traceback",
        "raw_log",
        "raw_logs",
        "raw_output",
        "raw_stdout",
        "raw_stderr",
        "raw_traceback",
        "unbounded_log",
        "unbounded_logs",
        "unbounded_output",
        "unbounded_stdout",
        "unbounded_stderr",
    }
)

# Required report surface keys checked by acceptance helpers (plan §9).
REQUIRED_REPORT_SURFACE_KEYS: Final[tuple[str, ...]] = (
    "candidate_id",
    "candidate_cid",
    "outcome_cid",
    "risk_class",
    "symbol_ids",
    "violated_or_missing_property",
    "detectors_run",
    "detectors_omitted",
    "expected_behavior",
    "observed_behavior",
    "source_spans",
    "dependency_path",
    "reproduction_command",
    "minimized_evidence",
    "proof_cids",
    "receipt_cids",
)


class MinimizationError(AssuranceBaseError):
    """Raised when survivor minimization fails closed."""


class MinimizationStatus(str, Enum):
    """Closed status for bounded reproduction minimization."""

    MINIMIZED = "minimized"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(
    value: Any, name: str, *, empty: bool = False, maximum: int = MAX_TEXT_CHARS
) -> str:
    if type(value) is not str or (not empty and not value):
        raise MinimizationError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise MinimizationError(
            f"{name} must be NFC-normalized and free of leading/trailing whitespace"
        )
    if len(value) > maximum:
        raise MinimizationError(f"{name} exceeds maximum length")
    if any(not char.isprintable() for char in value):
        raise MinimizationError(f"{name} contains non-printable characters")
    reject_private_model_authority_and_host_fallbacks({name: value}, path=name)
    return value


def _optional_text(
    value: Any, name: str, *, maximum: int = MAX_TEXT_CHARS
) -> str | None:
    if value is None:
        return None
    return _text(value, name, maximum=maximum)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise MinimizationError(f"{name} must be a boolean")
    return value


def _nonneg_int(value: Any, name: str, *, maximum: int) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise MinimizationError(f"{name} must be an integer")
    if value < 0 or value > maximum:
        raise MinimizationError(f"{name} out of allowed range")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise MinimizationError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _symbol_id(value: Any, name: str) -> str:
    text = _text(value, name)
    if _SYMBOL_ID_RE.fullmatch(text) is None:
        raise MinimizationError(
            f"{name} must be a symbol identity matching {_SYMBOL_ID_RE.pattern}"
        )
    return text


def _cid(value: Any, name: str) -> str:
    text = _text(value, name)
    try:
        validate_cid(text)
    except Exception as exc:  # pragma: no cover - validate_cid raises ValueError
        raise MinimizationError(f"{name} must be a valid CIDv1") from exc
    return text


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    if isinstance(value, enum_type):
        return value.value
    if type(value) is not str:
        raise MinimizationError(f"{name} must be a string or {enum_type.__name__}")
    allowed = {item.value for item in enum_type}
    if value not in allowed:
        raise MinimizationError(
            f"{name}={value!r} is not in closed set {sorted(allowed)}"
        )
    return value


def _freeze_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_structured(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_structured(item) for item in value)
    return value


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_structured(item) for item in value]
    return value


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise MinimizationError(f"{name} must be a mapping")
    unknown = set(data) - fields
    if unknown:
        raise MinimizationError(
            f"{name} contains unknown fields: {sorted(unknown)}"
        )
    return dict(data)


def _reject_full_log_keys(mapping: Mapping[str, Any], path: str) -> None:
    """Fail closed when full / raw / unbounded log bodies appear.

    Uses exact key matching (not substring) so policy flags such as
    ``full_logs_excluded`` remain admissible while ``full_logs`` is rejected.
    """

    stack: list[tuple[str, Any]] = [(path, mapping)]
    while stack:
        current_path, current = stack.pop()
        if isinstance(current, Mapping):
            for key, item in current.items():
                key_text = str(key)
                lowered = key_text.lower()
                if lowered in FULL_LOG_FORBIDDEN_KEYS:
                    raise MinimizationError(
                        f"{current_path}.{key_text} is forbidden; full logs must "
                        "remain out of survivor reports (use a bounded log digest)"
                    )
                if isinstance(item, (Mapping, list, tuple)):
                    stack.append((f"{current_path}.{key_text}", item))
        elif isinstance(current, (list, tuple)):
            for index, item in enumerate(current):
                if isinstance(item, (Mapping, list, tuple)):
                    stack.append((f"{current_path}[{index}]", item))


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise MinimizationError(f"{name} must be a mapping")
    reject_private_model_authority_and_host_fallbacks(dict(value), path=name)
    _reject_full_log_keys(dict(value), name)
    try:
        validate_structured_value(dict(value))
    except Exception as exc:
        raise MinimizationError(f"{name} is not a DAG-JSON structured value") from exc
    return MappingProxyType(_thaw_structured(dict(value)))


def _unique_sorted_tokens(
    values: Sequence[Any],
    name: str,
    *,
    maximum: int = MAX_LIST,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise MinimizationError(f"{name} must be a list")
    if len(values) > maximum:
        raise MinimizationError(f"{name} exceeds maximum length")
    items = [_token(item, f"{name}[{index}]") for index, item in enumerate(values)]
    if len(items) != len(set(items)):
        raise MinimizationError(f"{name} values must be unique")
    ordered = tuple(sorted(items))
    if not ordered and not allow_empty:
        raise MinimizationError(f"{name} must not be empty")
    return ordered


def _unique_sorted_symbol_ids(
    values: Sequence[Any], name: str, *, maximum: int = MAX_LIST
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise MinimizationError(f"{name} must be a list")
    if len(values) > maximum:
        raise MinimizationError(f"{name} exceeds maximum length")
    items = [
        _symbol_id(item, f"{name}[{index}]") for index, item in enumerate(values)
    ]
    if len(items) != len(set(items)):
        raise MinimizationError(f"{name} values must be unique")
    return tuple(sorted(items))


def _unique_sorted_cids(
    values: Sequence[Any], name: str, *, maximum: int = MAX_LIST
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise MinimizationError(f"{name} must be a list")
    if len(values) > maximum:
        raise MinimizationError(f"{name} exceeds maximum length")
    items = [_cid(item, f"{name}[{index}]") for index, item in enumerate(values)]
    if len(items) != len(set(items)):
        raise MinimizationError(f"{name} values must be unique")
    return tuple(sorted(items))


def _header(value: Any, name: str = "header") -> AssuranceArtifactHeader:
    if isinstance(value, AssuranceArtifactHeader):
        return value
    if isinstance(value, Mapping):
        try:
            return AssuranceArtifactHeader.from_dict(value)
        except Exception as exc:
            raise MinimizationError(f"{name} is malformed: {exc}") from exc
    raise MinimizationError(f"{name} must be AssuranceArtifactHeader or mapping")


def _normalize_source_span(
    value: SourceSpan | Mapping[str, Any], name: str
) -> SourceSpan:
    if isinstance(value, SourceSpan):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value or "span_cid" in value:
                return SourceSpan.from_dict(value)
            return SourceSpan(**dict(value))  # type: ignore[arg-type]
        except (AnalysisContractError, TypeError, KeyError) as exc:
            raise MinimizationError(f"{name} is malformed: {exc}") from exc
    raise MinimizationError(f"{name} must be SourceSpan or mapping")


def _normalize_source_spans(
    values: Sequence[SourceSpan | Mapping[str, Any]], name: str
) -> tuple[SourceSpan, ...]:
    if not isinstance(values, (list, tuple)):
        raise MinimizationError(f"{name} must be a list")
    if len(values) > MAX_SPANS:
        raise MinimizationError(f"{name} exceeds maximum length")
    if not values:
        raise MinimizationError(f"{name} must not be empty")
    return tuple(
        _normalize_source_span(item, f"{name}[{index}]")
        for index, item in enumerate(values)
    )


def _artifact_header(
    base: AssuranceArtifactHeader,
    *,
    artifact_kind: str,
    interface_id: str,
    symbol_ids: Sequence[str] | None = None,
    repository_state_cid: str | None = None,
    receipt_cids: Sequence[str] | None = None,
    proof_cids: Sequence[str] | None = None,
) -> AssuranceArtifactHeader:
    generator = GeneratorIdentity(
        generator_id=GENERATOR_ID,
        generator_version=GENERATOR_VERSION,
        interface_id=interface_id,
    )
    versions = VersionBinding(
        operator_id=base.versions.operator_id,
        operator_version=base.versions.operator_version,
        campaign_policy_id=base.versions.campaign_policy_id,
        campaign_policy_version=base.versions.campaign_policy_version,
        generator=generator,
    )
    return AssuranceArtifactHeader(
        artifact_kind=artifact_kind,
        repository_id=base.repository_id,
        repository_state_cid=repository_state_cid or base.repository_state_cid,
        target_symbol_ids=(
            tuple(symbol_ids)
            if symbol_ids is not None
            else tuple(base.target_symbol_ids)
        ),
        target_artifact_cids=tuple(base.target_artifact_cids),
        capsule_cids=tuple(base.capsule_cids),
        proof_unit_cids=tuple(base.proof_unit_cids),
        environment_cid=base.environment_cid,
        dependency_lock_cid=base.dependency_lock_cid,
        versions=versions,
        provenance=base.provenance,
        terminal_status=base.terminal_status,
        receipt_cids=(
            tuple(receipt_cids)
            if receipt_cids is not None
            else tuple(base.receipt_cids)
        ),
        proof_cids=(
            tuple(proof_cids) if proof_cids is not None else tuple(base.proof_cids)
        ),
        metadata=dict(base.metadata),
    )


# ---------------------------------------------------------------------------
# Span minimization (smallest changed region)
# ---------------------------------------------------------------------------


def _span_line_width(span: SourceSpan) -> int:
    return span.end_line - span.start_line


def _spans_overlap_or_adjacent(left: SourceSpan, right: SourceSpan) -> bool:
    if left.path != right.path:
        return False
    # Adjacent lines merge so the changed region collapses tightly.
    return not (
        left.end_line + 1 < right.start_line or right.end_line + 1 < left.start_line
    )


def _merge_two_spans(left: SourceSpan, right: SourceSpan) -> SourceSpan:
    start_line = min(left.start_line, right.start_line)
    end_line = max(left.end_line, right.end_line)
    start_col: int | None
    end_col: int | None
    if left.start_line < right.start_line:
        start_col = left.start_col
    elif right.start_line < left.start_line:
        start_col = right.start_col
    else:
        cols = [c for c in (left.start_col, right.start_col) if c is not None]
        start_col = min(cols) if cols else None
    if left.end_line > right.end_line:
        end_col = left.end_col
    elif right.end_line > left.end_line:
        end_col = right.end_col
    else:
        cols = [c for c in (left.end_col, right.end_col) if c is not None]
        end_col = max(cols) if cols else None
    return SourceSpan(
        path=left.path,
        start_line=start_line,
        end_line=end_line,
        start_col=start_col,
        end_col=end_col,
    )


def minimize_source_spans(
    spans: Sequence[SourceSpan | Mapping[str, Any]],
    *,
    name: str = "source_spans",
) -> tuple[SourceSpan, ...]:
    """Collapse overlapping/adjacent spans into the smallest changed region set.

    Deterministic pure reduction: no oracle. Merges overlapping or line-adjacent
    spans on the same path, de-duplicates identical spans, and returns a stable
    path/line ordered tuple. Empty input fails closed.
    """

    normalized = list(_normalize_source_spans(list(spans), name))
    # Process per path so cross-file spans stay distinct.
    by_path: dict[str, list[SourceSpan]] = {}
    for span in normalized:
        by_path.setdefault(span.path, []).append(span)

    minimized: list[SourceSpan] = []
    for path in sorted(by_path):
        ordered = sorted(
            by_path[path],
            key=lambda item: (
                item.start_line,
                item.end_line,
                item.start_col if item.start_col is not None else -1,
                item.end_col if item.end_col is not None else -1,
                item.span_cid,
            ),
        )
        merged: list[SourceSpan] = []
        for span in ordered:
            if not merged:
                merged.append(span)
                continue
            previous = merged[-1]
            if _spans_overlap_or_adjacent(previous, span):
                merged[-1] = _merge_two_spans(previous, span)
            else:
                merged.append(span)
        minimized.extend(merged)

    result = tuple(
        sorted(
            minimized,
            key=lambda item: (
                item.path,
                item.start_line,
                item.end_line,
                item.span_cid,
            ),
        )
    )
    if not result:
        raise MinimizationError(f"{name} must not be empty after minimization")
    if len(result) > MAX_SPANS:
        raise MinimizationError(f"{name} exceeds maximum length after minimization")
    return result


# ---------------------------------------------------------------------------
# Bounded log digest
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BoundedLogDigest:
    """Bounded reference to execution logs — never embeds full log bodies.

    When minimization fails, reports may reference a digest of the bounded log
    budget rather than shipping complete logs into model context (plan §9).
    """

    digest_cid: str
    byte_count: int
    truncated: bool = False
    full_log_excluded: bool = True
    notes: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "digest_cid",
            "byte_count",
            "truncated",
            "full_log_excluded",
            "notes",
            "digest_binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "digest_cid", _cid(self.digest_cid, "digest_cid"))
        object.__setattr__(
            self,
            "byte_count",
            _nonneg_int(
                self.byte_count, "byte_count", maximum=MAX_DECLARED_LOG_BYTES
            ),
        )
        object.__setattr__(self, "truncated", _bool(self.truncated, "truncated"))
        excluded = _bool(self.full_log_excluded, "full_log_excluded")
        if not excluded:
            raise MinimizationError(
                "full_log_excluded must be true; full logs are never admitted"
            )
        object.__setattr__(self, "full_log_excluded", True)
        object.__setattr__(
            self,
            "notes",
            _optional_text(self.notes, "notes", maximum=MAX_LOG_DIGEST_NOTES),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": BOUNDED_LOG_DIGEST_SCHEMA,
            "digest_cid": self.digest_cid,
            "byte_count": self.byte_count,
            "truncated": self.truncated,
            "full_log_excluded": self.full_log_excluded,
            "notes": self.notes,
        }

    @property
    def digest_binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["digest_binding_cid"] = self.digest_binding_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BoundedLogDigest":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("digest_binding_cid", None)
        if payload.pop("schema", BOUNDED_LOG_DIGEST_SCHEMA) != BOUNDED_LOG_DIGEST_SCHEMA:
            raise MinimizationError("unsupported BoundedLogDigest schema version")
        result = cls(
            digest_cid=payload["digest_cid"],
            byte_count=payload["byte_count"],
            truncated=payload.get("truncated", False),
            full_log_excluded=payload.get("full_log_excluded", True),
            notes=payload.get("notes"),
        )
        if claimed is not None and claimed != result.digest_binding_cid:
            raise MinimizationError(
                "BoundedLogDigest digest_binding_cid identity mismatch"
            )
        return result


def _normalize_log_digest(
    value: BoundedLogDigest | Mapping[str, Any] | None,
    name: str = "bounded_log_digest",
) -> BoundedLogDigest | None:
    if value is None:
        return None
    if isinstance(value, BoundedLogDigest):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value or "digest_binding_cid" in value:
                return BoundedLogDigest.from_dict(value)
            return BoundedLogDigest(**dict(value))  # type: ignore[arg-type]
        except (MinimizationError, TypeError, KeyError) as exc:
            raise MinimizationError(f"{name} is malformed: {exc}") from exc
    raise MinimizationError(f"{name} must be BoundedLogDigest or mapping")


# ---------------------------------------------------------------------------
# Survivor minimization subject
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SurvivorMinimizationSubject:
    """Bounded observation inputs for ``build_surviving_mutant_report@1``.

    Carries the identities, property, detector inventory, behavior delta, spans,
    dependency path, proof/receipt IDs, reproduction command, risk, and either
    minimized evidence CIDs or an explicit minimization-failure + bounded log
    digest. Full log bodies are forbidden.
    """

    subject_id: str
    report_id: str
    candidate_id: str
    candidate_cid: str
    outcome_cid: str
    risk_class: SurvivorRiskClass | str
    symbol_ids: Sequence[str]
    violated_or_missing_property: str
    source_spans: Sequence[SourceSpan | Mapping[str, Any]]
    detectors_run: Sequence[str]
    detectors_omitted: Sequence[str]
    expected_behavior: str
    observed_behavior: str
    dependency_path: Sequence[str]
    reproduction_command: str
    evidence_cids: Sequence[str] = ()
    reproduction_input_cid: str | None = None
    proof_cids: Sequence[str] = ()
    receipt_cids: Sequence[str] = ()
    equivalence_assessment_cid: str | None = None
    minimization_status: MinimizationStatus | str = MinimizationStatus.MINIMIZED
    minimization_failure_reason: str | None = None
    bounded_log_digest: BoundedLogDigest | Mapping[str, Any] | None = None
    observation_complete: bool = True
    repository_state_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "subject_id",
            "report_id",
            "candidate_id",
            "candidate_cid",
            "outcome_cid",
            "risk_class",
            "symbol_ids",
            "violated_or_missing_property",
            "source_spans",
            "detectors_run",
            "detectors_omitted",
            "expected_behavior",
            "observed_behavior",
            "dependency_path",
            "reproduction_command",
            "evidence_cids",
            "reproduction_input_cid",
            "proof_cids",
            "receipt_cids",
            "equivalence_assessment_cid",
            "minimization_status",
            "minimization_failure_reason",
            "bounded_log_digest",
            "observation_complete",
            "repository_state_cid",
            "notes",
            "metadata",
            "subject_observation_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _token(self.subject_id, "subject_id"))
        object.__setattr__(self, "report_id", _token(self.report_id, "report_id"))
        object.__setattr__(
            self, "candidate_id", _token(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "candidate_cid", _cid(self.candidate_cid, "candidate_cid")
        )
        object.__setattr__(self, "outcome_cid", _cid(self.outcome_cid, "outcome_cid"))
        object.__setattr__(
            self,
            "risk_class",
            _enum(self.risk_class, SurvivorRiskClass, "risk_class"),
        )
        symbols = _unique_sorted_symbol_ids(list(self.symbol_ids), "symbol_ids")
        if not symbols:
            raise MinimizationError("symbol_ids must not be empty")
        object.__setattr__(self, "symbol_ids", symbols)
        object.__setattr__(
            self,
            "violated_or_missing_property",
            _text(self.violated_or_missing_property, "violated_or_missing_property"),
        )
        # Store raw normalized spans; builder applies minimize_source_spans.
        spans = _normalize_source_spans(list(self.source_spans), "source_spans")
        object.__setattr__(self, "source_spans", spans)
        run = _unique_sorted_tokens(
            list(self.detectors_run), "detectors_run", maximum=MAX_DETECTORS
        )
        omitted = _unique_sorted_tokens(
            list(self.detectors_omitted),
            "detectors_omitted",
            maximum=MAX_DETECTORS,
        )
        overlap = set(run) & set(omitted)
        if overlap:
            raise MinimizationError(
                f"detectors_run and detectors_omitted must be disjoint; "
                f"overlap={sorted(overlap)}"
            )
        object.__setattr__(self, "detectors_run", run)
        object.__setattr__(self, "detectors_omitted", omitted)
        object.__setattr__(
            self, "expected_behavior", _text(self.expected_behavior, "expected_behavior")
        )
        object.__setattr__(
            self, "observed_behavior", _text(self.observed_behavior, "observed_behavior")
        )
        path = _unique_sorted_tokens(
            list(self.dependency_path),
            "dependency_path",
            maximum=MAX_DEPENDENCY_PATH,
            allow_empty=False,
        )
        object.__setattr__(self, "dependency_path", path)
        object.__setattr__(
            self,
            "reproduction_command",
            _text(
                self.reproduction_command,
                "reproduction_command",
                maximum=MAX_COMMAND_CHARS,
            ),
        )
        object.__setattr__(
            self,
            "evidence_cids",
            _unique_sorted_cids(
                list(self.evidence_cids), "evidence_cids", maximum=MAX_EVIDENCE_CIDS
            ),
        )
        object.__setattr__(
            self,
            "reproduction_input_cid",
            _optional_cid(self.reproduction_input_cid, "reproduction_input_cid"),
        )
        object.__setattr__(
            self,
            "proof_cids",
            _unique_sorted_cids(
                list(self.proof_cids), "proof_cids", maximum=MAX_PROOF_CIDS
            ),
        )
        object.__setattr__(
            self,
            "receipt_cids",
            _unique_sorted_cids(
                list(self.receipt_cids), "receipt_cids", maximum=MAX_RECEIPT_CIDS
            ),
        )
        object.__setattr__(
            self,
            "equivalence_assessment_cid",
            _optional_cid(
                self.equivalence_assessment_cid, "equivalence_assessment_cid"
            ),
        )
        status = _enum(
            self.minimization_status, MinimizationStatus, "minimization_status"
        )
        object.__setattr__(self, "minimization_status", status)
        reason = _optional_text(
            self.minimization_failure_reason, "minimization_failure_reason"
        )
        digest = _normalize_log_digest(self.bounded_log_digest)
        if status == MinimizationStatus.MINIMIZED.value:
            if reason is not None:
                raise MinimizationError(
                    "minimization_failure_reason requires minimization_status=failed"
                )
            if not self.evidence_cids:
                raise MinimizationError(
                    "evidence_cids must not be empty when minimization succeeds"
                )
            if self.reproduction_input_cid is None:
                raise MinimizationError(
                    "reproduction_input_cid is required when minimization succeeds "
                    "(smallest reproducing input)"
                )
        else:
            if reason is None:
                raise MinimizationError(
                    "minimization_failure_reason is required when "
                    "minimization_status=failed"
                )
            if digest is None:
                raise MinimizationError(
                    "bounded_log_digest is required when minimization fails so "
                    "full logs stay out of the report"
                )
        object.__setattr__(self, "minimization_failure_reason", reason)
        object.__setattr__(self, "bounded_log_digest", digest)
        object.__setattr__(
            self,
            "observation_complete",
            _bool(self.observation_complete, "observation_complete"),
        )
        object.__setattr__(
            self,
            "repository_state_cid",
            _optional_cid(self.repository_state_cid, "repository_state_cid"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SURVIVOR_MINIMIZATION_SUBJECT_SCHEMA,
            "subject_id": self.subject_id,
            "report_id": self.report_id,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "outcome_cid": self.outcome_cid,
            "risk_class": self.risk_class,
            "symbol_ids": list(self.symbol_ids),
            "violated_or_missing_property": self.violated_or_missing_property,
            "source_spans": [span.identity_payload() for span in self.source_spans],
            "detectors_run": list(self.detectors_run),
            "detectors_omitted": list(self.detectors_omitted),
            "expected_behavior": self.expected_behavior,
            "observed_behavior": self.observed_behavior,
            "dependency_path": list(self.dependency_path),
            "reproduction_command": self.reproduction_command,
            "evidence_cids": list(self.evidence_cids),
            "reproduction_input_cid": self.reproduction_input_cid,
            "proof_cids": list(self.proof_cids),
            "receipt_cids": list(self.receipt_cids),
            "equivalence_assessment_cid": self.equivalence_assessment_cid,
            "minimization_status": self.minimization_status,
            "minimization_failure_reason": self.minimization_failure_reason,
            "bounded_log_digest": (
                self.bounded_log_digest.identity_payload()
                if self.bounded_log_digest is not None
                else None
            ),
            "observation_complete": self.observation_complete,
            "repository_state_cid": self.repository_state_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def subject_observation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["source_spans"] = [span.to_dict() for span in self.source_spans]
        if self.bounded_log_digest is not None:
            value["bounded_log_digest"] = self.bounded_log_digest.to_dict()
        value["subject_observation_cid"] = self.subject_observation_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SurvivorMinimizationSubject":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("subject_observation_cid", None)
        if payload.pop("schema", SURVIVOR_MINIMIZATION_SUBJECT_SCHEMA) != (
            SURVIVOR_MINIMIZATION_SUBJECT_SCHEMA
        ):
            raise MinimizationError(
                "unsupported SurvivorMinimizationSubject schema version"
            )
        result = cls(
            subject_id=payload["subject_id"],
            report_id=payload["report_id"],
            candidate_id=payload["candidate_id"],
            candidate_cid=payload["candidate_cid"],
            outcome_cid=payload["outcome_cid"],
            risk_class=payload["risk_class"],
            symbol_ids=payload["symbol_ids"],
            violated_or_missing_property=payload["violated_or_missing_property"],
            source_spans=payload["source_spans"],
            detectors_run=payload["detectors_run"],
            detectors_omitted=payload["detectors_omitted"],
            expected_behavior=payload["expected_behavior"],
            observed_behavior=payload["observed_behavior"],
            dependency_path=payload["dependency_path"],
            reproduction_command=payload["reproduction_command"],
            evidence_cids=payload.get("evidence_cids", ()),
            reproduction_input_cid=payload.get("reproduction_input_cid"),
            proof_cids=payload.get("proof_cids", ()),
            receipt_cids=payload.get("receipt_cids", ()),
            equivalence_assessment_cid=payload.get("equivalence_assessment_cid"),
            minimization_status=payload.get(
                "minimization_status", MinimizationStatus.MINIMIZED
            ),
            minimization_failure_reason=payload.get("minimization_failure_reason"),
            bounded_log_digest=payload.get("bounded_log_digest"),
            observation_complete=payload.get("observation_complete", True),
            repository_state_cid=payload.get("repository_state_cid"),
            notes=payload.get("notes"),
            metadata=payload.get("metadata", {}),
        )
        if claimed is not None and claimed != result.subject_observation_cid:
            raise MinimizationError(
                "SurvivorMinimizationSubject subject_observation_cid identity mismatch"
            )
        return result


def _normalize_subject(
    value: SurvivorMinimizationSubject | Mapping[str, Any],
    name: str = "subject",
) -> SurvivorMinimizationSubject:
    if isinstance(value, SurvivorMinimizationSubject):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value or "subject_observation_cid" in value:
                return SurvivorMinimizationSubject.from_dict(value)
            return SurvivorMinimizationSubject(**dict(value))  # type: ignore[arg-type]
        except (MinimizationError, TypeError, KeyError) as exc:
            raise MinimizationError(f"{name} is malformed: {exc}") from exc
    raise MinimizationError(
        f"{name} must be SurvivorMinimizationSubject or mapping"
    )


# ---------------------------------------------------------------------------
# Build result wrapper
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SurvivorReportBuildResult:
    """Sealed builder result binding the subject observation to the report."""

    interface_id: str
    subject_id: str
    subject_observation_cid: str
    report_id: str
    report_cid: str
    candidate_id: str
    candidate_cid: str
    outcome_cid: str
    risk_class: str
    minimization_status: str
    minimization_failed: bool
    logs_bounded: bool
    smallest_region_span_cids: Sequence[str]
    reproduction_input_cid: str | None
    detectors_run: Sequence[str]
    detectors_omitted: Sequence[str]
    report: Mapping[str, Any]
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "subject_id",
            "subject_observation_cid",
            "report_id",
            "report_cid",
            "candidate_id",
            "candidate_cid",
            "outcome_cid",
            "risk_class",
            "minimization_status",
            "minimization_failed",
            "logs_bounded",
            "smallest_region_span_cids",
            "reproduction_input_cid",
            "detectors_run",
            "detectors_omitted",
            "report",
            "notes",
            "metadata",
            "result_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "interface_id", _text(self.interface_id, "interface_id")
        )
        if self.interface_id != BUILD_SURVIVING_MUTANT_REPORT_INTERFACE:
            raise MinimizationError(
                "interface_id must be build_surviving_mutant_report@1"
            )
        object.__setattr__(self, "subject_id", _token(self.subject_id, "subject_id"))
        object.__setattr__(
            self,
            "subject_observation_cid",
            _cid(self.subject_observation_cid, "subject_observation_cid"),
        )
        object.__setattr__(self, "report_id", _token(self.report_id, "report_id"))
        object.__setattr__(self, "report_cid", _cid(self.report_cid, "report_cid"))
        object.__setattr__(
            self, "candidate_id", _token(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "candidate_cid", _cid(self.candidate_cid, "candidate_cid")
        )
        object.__setattr__(self, "outcome_cid", _cid(self.outcome_cid, "outcome_cid"))
        object.__setattr__(
            self,
            "risk_class",
            _enum(self.risk_class, SurvivorRiskClass, "risk_class"),
        )
        object.__setattr__(
            self,
            "minimization_status",
            _enum(self.minimization_status, MinimizationStatus, "minimization_status"),
        )
        failed = _bool(self.minimization_failed, "minimization_failed")
        object.__setattr__(self, "minimization_failed", failed)
        if failed and self.minimization_status != MinimizationStatus.FAILED.value:
            raise MinimizationError(
                "minimization_failed requires minimization_status=failed"
            )
        if (
            not failed
            and self.minimization_status != MinimizationStatus.MINIMIZED.value
        ):
            raise MinimizationError(
                "successful builds require minimization_status=minimized"
            )
        bounded = _bool(self.logs_bounded, "logs_bounded")
        if not bounded:
            raise MinimizationError("logs_bounded must be true")
        object.__setattr__(self, "logs_bounded", True)
        object.__setattr__(
            self,
            "smallest_region_span_cids",
            _unique_sorted_cids(
                list(self.smallest_region_span_cids),
                "smallest_region_span_cids",
                maximum=MAX_SPANS,
            ),
        )
        if not self.smallest_region_span_cids:
            raise MinimizationError("smallest_region_span_cids must not be empty")
        object.__setattr__(
            self,
            "reproduction_input_cid",
            _optional_cid(self.reproduction_input_cid, "reproduction_input_cid"),
        )
        object.__setattr__(
            self,
            "detectors_run",
            _unique_sorted_tokens(
                list(self.detectors_run), "detectors_run", maximum=MAX_DETECTORS
            ),
        )
        object.__setattr__(
            self,
            "detectors_omitted",
            _unique_sorted_tokens(
                list(self.detectors_omitted),
                "detectors_omitted",
                maximum=MAX_DETECTORS,
            ),
        )
        if not isinstance(self.report, Mapping):
            raise MinimizationError("report must be a mapping")
        _reject_full_log_keys(dict(self.report), "report")
        try:
            sealed_report = SurvivingMutantReport.from_dict(dict(self.report))
        except (AnalysisContractError, TypeError, KeyError) as exc:
            raise MinimizationError(f"report is malformed: {exc}") from exc
        if sealed_report.report_cid != self.report_cid:
            raise MinimizationError(
                "report_cid must match sealed SurvivingMutantReport.report_cid"
            )
        object.__setattr__(
            self, "report", MappingProxyType(_thaw_structured(sealed_report.to_dict()))
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SURVIVOR_REPORT_BUILD_RESULT_SCHEMA,
            "interface_id": self.interface_id,
            "subject_id": self.subject_id,
            "subject_observation_cid": self.subject_observation_cid,
            "report_id": self.report_id,
            "report_cid": self.report_cid,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "outcome_cid": self.outcome_cid,
            "risk_class": self.risk_class,
            "minimization_status": self.minimization_status,
            "minimization_failed": self.minimization_failed,
            "logs_bounded": self.logs_bounded,
            "smallest_region_span_cids": list(self.smallest_region_span_cids),
            "reproduction_input_cid": self.reproduction_input_cid,
            "detectors_run": list(self.detectors_run),
            "detectors_omitted": list(self.detectors_omitted),
            "report": _thaw_structured(self.report),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def result_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["result_cid"] = self.result_cid
        return value

    def surviving_mutant_report(self) -> SurvivingMutantReport:
        """Decode the sealed ``SurvivingMutantReport@1`` from this build result."""

        return SurvivingMutantReport.from_dict(dict(self.report))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SurvivorReportBuildResult":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("result_cid", None)
        if payload.pop("schema", SURVIVOR_REPORT_BUILD_RESULT_SCHEMA) != (
            SURVIVOR_REPORT_BUILD_RESULT_SCHEMA
        ):
            raise MinimizationError(
                "unsupported SurvivorReportBuildResult schema version"
            )
        result = cls(**payload)  # type: ignore[arg-type]
        if claimed is not None and claimed != result.result_cid:
            raise MinimizationError(
                "SurvivorReportBuildResult result_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# Evidence construction and acceptance helpers
# ---------------------------------------------------------------------------


def _build_minimized_evidence(
    subject: SurvivorMinimizationSubject,
) -> MinimizedEvidenceBinding:
    if subject.minimization_status == MinimizationStatus.MINIMIZED.value:
        return MinimizedEvidenceBinding(
            evidence_cids=subject.evidence_cids,
            minimized=True,
            minimization_failed=False,
            reproduction_input_cid=subject.reproduction_input_cid,
            notes=subject.notes,
        )

    # Failure path: full logs stay out; only the bounded digest CID is retained
    # as evidence, with an explicit failure reason.
    assert subject.bounded_log_digest is not None
    digest_cid = subject.bounded_log_digest.digest_cid
    evidence = list(subject.evidence_cids)
    if digest_cid not in evidence:
        evidence.append(digest_cid)
    notes_parts = [
        f"minimization_failed: {subject.minimization_failure_reason}",
        (
            f"bounded_log_digest={digest_cid} "
            f"bytes={subject.bounded_log_digest.byte_count} "
            f"truncated={subject.bounded_log_digest.truncated}"
        ),
    ]
    if subject.notes:
        notes_parts.append(subject.notes)
    return MinimizedEvidenceBinding(
        evidence_cids=tuple(evidence),
        minimized=False,
        minimization_failed=True,
        reproduction_input_cid=subject.reproduction_input_cid,
        notes="; ".join(notes_parts),
    )


def report_contains_required_surface(report: SurvivingMutantReport) -> bool:
    """Return True when the report binds every plan §9 minimized-report field."""

    payload = report.to_dict()
    for key in REQUIRED_REPORT_SURFACE_KEYS:
        if key not in payload:
            return False
    if not report.symbol_ids:
        return False
    if not report.source_spans:
        return False
    if not report.dependency_path:
        return False
    if not report.violated_or_missing_property:
        return False
    if not report.reproduction_command:
        return False
    if not report.risk_class:
        return False
    if not report.expected_behavior or not report.observed_behavior:
        return False
    # Detector inventory may be empty on both sides only when both empty —
    # still present as lists on the surface.
    if not isinstance(report.detectors_run, tuple):
        return False
    if not isinstance(report.detectors_omitted, tuple):
        return False
    evidence = report.minimized_evidence
    if evidence.minimized and not evidence.evidence_cids:
        return False
    if evidence.minimized and evidence.reproduction_input_cid is None:
        return False
    return True


def logs_remain_bounded(
    report: SurvivingMutantReport | Mapping[str, Any] | SurvivorReportBuildResult,
) -> bool:
    """Return True when no full-log body is present on the sealed report surface."""

    if isinstance(report, SurvivorReportBuildResult):
        if not report.logs_bounded:
            return False
        payload = dict(report.report)
    elif isinstance(report, SurvivingMutantReport):
        payload = report.to_dict()
    elif isinstance(report, Mapping):
        payload = dict(report)
    else:
        return False
    try:
        _reject_full_log_keys(payload, "report")
    except MinimizationError:
        return False
    # Nested notes may mention digests but must not embed multi-kilobyte dumps
    # beyond MAX_TEXT_CHARS (already enforced by constructors).
    return True


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_surviving_mutant_report(
    subject: SurvivorMinimizationSubject | Mapping[str, Any],
    header: AssuranceArtifactHeader | Mapping[str, Any],
    *,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SurvivorReportBuildResult:
    """Build a sealed minimized ``SurvivingMutantReport@1``.

    Interface: ``build_surviving_mutant_report@1``

    Acceptance (AAE-031 / plan §9):

    * Smallest changed source region (overlapping/adjacent spans merged).
    * Smallest reproducing input CID when minimization succeeds.
    * Identities: candidate, outcome, symbols, report.
    * Violated/missing property.
    * Detector inventory (run + omitted, disjoint).
    * Behavior delta (expected vs observed).
    * Source spans, dependency path, proof/receipt IDs.
    * Reproduction command and risk class.
    * Logs remain bounded (digest only; full logs forbidden).
    * Minimization failure is explicit via ``minimization_failed``.

    Incomplete observation fails closed. Pure and deterministic.
    """

    sealed = _normalize_subject(subject)
    if not sealed.observation_complete:
        raise MinimizationError(
            "build_surviving_mutant_report fails closed when observation_complete "
            "is false"
        )

    base_header = _header(header)
    minimized_spans = minimize_source_spans(sealed.source_spans)
    evidence = _build_minimized_evidence(sealed)

    report_header = _artifact_header(
        base_header,
        artifact_kind="surviving_mutant_report",
        interface_id=BUILD_SURVIVING_MUTANT_REPORT_INTERFACE,
        symbol_ids=sealed.symbol_ids,
        repository_state_cid=sealed.repository_state_cid,
        receipt_cids=sealed.receipt_cids or None,
        proof_cids=sealed.proof_cids or None,
    )

    note_text = notes if notes is not None else sealed.notes
    if note_text is not None:
        note_text = _optional_text(note_text, "notes")

    report_metadata: dict[str, Any] = dict(sealed.metadata)
    if metadata:
        report_metadata.update(dict(metadata))
    report_metadata = dict(_mapping(report_metadata, "metadata"))
    report_metadata["generator_id"] = GENERATOR_ID
    report_metadata["generator_version"] = GENERATOR_VERSION
    report_metadata["builder_interface"] = BUILD_SURVIVING_MUTANT_REPORT_INTERFACE
    report_metadata["subject_id"] = sealed.subject_id
    report_metadata["subject_observation_cid"] = sealed.subject_observation_cid
    report_metadata["minimization_status"] = sealed.minimization_status
    report_metadata["input_span_count"] = len(sealed.source_spans)
    report_metadata["minimized_span_count"] = len(minimized_spans)
    report_metadata["span_reduction"] = max(
        0, len(sealed.source_spans) - len(minimized_spans)
    )
    if sealed.bounded_log_digest is not None:
        report_metadata["bounded_log_digest_cid"] = (
            sealed.bounded_log_digest.digest_binding_cid
        )
        report_metadata["bounded_log_byte_count"] = sealed.bounded_log_digest.byte_count
        report_metadata["bounded_log_truncated"] = sealed.bounded_log_digest.truncated
    report_metadata["full_logs_excluded"] = True
    report_metadata["logs_bounded"] = True

    report = SurvivingMutantReport(
        header=report_header,
        report_id=sealed.report_id,
        candidate_id=sealed.candidate_id,
        candidate_cid=sealed.candidate_cid,
        outcome_cid=sealed.outcome_cid,
        risk_class=sealed.risk_class,
        symbol_ids=sealed.symbol_ids,
        violated_or_missing_property=sealed.violated_or_missing_property,
        detectors_run=sealed.detectors_run,
        detectors_omitted=sealed.detectors_omitted,
        expected_behavior=sealed.expected_behavior,
        observed_behavior=sealed.observed_behavior,
        source_spans=minimized_spans,
        dependency_path=sealed.dependency_path,
        reproduction_command=sealed.reproduction_command,
        minimized_evidence=evidence,
        proof_cids=sealed.proof_cids,
        receipt_cids=sealed.receipt_cids,
        equivalence_assessment_cid=sealed.equivalence_assessment_cid,
        notes=note_text,
        metadata=report_metadata,
    )
    verify_survivor_report_identity(report)
    if not report_contains_required_surface(report):
        raise MinimizationError(
            "sealed report is missing required minimized-survivor surface fields"
        )
    if not logs_remain_bounded(report):
        raise MinimizationError("sealed report must keep logs bounded")

    failed = sealed.minimization_status == MinimizationStatus.FAILED.value
    result = SurvivorReportBuildResult(
        interface_id=BUILD_SURVIVING_MUTANT_REPORT_INTERFACE,
        subject_id=sealed.subject_id,
        subject_observation_cid=sealed.subject_observation_cid,
        report_id=report.report_id,
        report_cid=report.report_cid,
        candidate_id=report.candidate_id,
        candidate_cid=report.candidate_cid,
        outcome_cid=report.outcome_cid,
        risk_class=report.risk_class,
        minimization_status=sealed.minimization_status,
        minimization_failed=failed,
        logs_bounded=True,
        smallest_region_span_cids=tuple(span.span_cid for span in minimized_spans),
        reproduction_input_cid=evidence.reproduction_input_cid,
        detectors_run=report.detectors_run,
        detectors_omitted=report.detectors_omitted,
        report=report.to_dict(),
        notes=note_text,
        metadata={
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "input_span_count": len(sealed.source_spans),
            "minimized_span_count": len(minimized_spans),
        },
    )
    verify_survivor_report_build_result_identity(result)
    return result


# ---------------------------------------------------------------------------
# Vocabulary / identity helpers
# ---------------------------------------------------------------------------


def minimization_statuses() -> tuple[str, ...]:
    """Return the closed minimization-status vocabulary."""

    return tuple(item.value for item in MinimizationStatus)


def full_log_forbidden_keys() -> tuple[str, ...]:
    """Return the closed set of forbidden full-log field markers."""

    return tuple(sorted(FULL_LOG_FORBIDDEN_KEYS))


def verify_survivor_report_build_result_identity(
    result: SurvivorReportBuildResult | Mapping[str, Any],
) -> SurvivorReportBuildResult:
    """Decode-and-recompute identity for a sealed build result."""

    if isinstance(result, SurvivorReportBuildResult):
        restored = SurvivorReportBuildResult.from_dict(result.to_dict())
        if restored.result_cid != result.result_cid:
            raise MinimizationError("SurvivorReportBuildResult identity mismatch")
        return restored
    if isinstance(result, Mapping):
        return SurvivorReportBuildResult.from_dict(result)
    raise MinimizationError(
        "result must be SurvivorReportBuildResult or mapping"
    )


__all__ = [
    "BOUNDED_LOG_DIGEST_SCHEMA",
    "BUILD_SURVIVING_MUTANT_REPORT_INTERFACE",
    "FULL_LOG_FORBIDDEN_KEYS",
    "GENERATOR_ID",
    "GENERATOR_VERSION",
    "MAX_DECLARED_LOG_BYTES",
    "REQUIRED_REPORT_SURFACE_KEYS",
    "SURVIVOR_MINIMIZATION_SUBJECT_INTERFACE",
    "SURVIVOR_MINIMIZATION_SUBJECT_SCHEMA",
    "SURVIVOR_REPORT_BUILD_RESULT_INTERFACE",
    "SURVIVOR_REPORT_BUILD_RESULT_SCHEMA",
    "BoundedLogDigest",
    "MinimizationError",
    "MinimizationStatus",
    "SurvivorMinimizationSubject",
    "SurvivorReportBuildResult",
    "build_surviving_mutant_report",
    "full_log_forbidden_keys",
    "logs_remain_bounded",
    "minimize_source_spans",
    "minimization_statuses",
    "report_contains_required_surface",
    "verify_survivor_report_build_result_identity",
]
