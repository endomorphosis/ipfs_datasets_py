"""Formal-proof and policy vacuity analysis (AAE-026).

Implements the two vacuity-family analyzers required by plan §9 and AAE-G040:

* ``analyze_formal_vacuity@1`` — unsatisfiable antecedents, unreachable modeled
  state, impossible discharge, unconstrained results, omitted behavior, and
  behavior assumed rather than proven.
* ``analyze_policy_vacuity@1`` — unreachable rules/confirmations, shadowed
  prohibitions, impossible obligations, dominating defaults, and obsolete
  interface references.

Every emitted :class:`VacuityFinding` states exactly what remains proven and
what is not proven (precise residual / nonclaim). Unknown kinds, missing
observation capability, and malformed subjects fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
import re
import unicodedata
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence

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
    MinimizedEvidenceBinding,
    SourceSpan,
    VacuityFamily,
    VacuityFinding,
    VacuityKind,
    verify_vacuity_finding_identity,
)

# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

ANALYZE_FORMAL_VACUITY_INTERFACE: Final[str] = "analyze_formal_vacuity@1"
ANALYZE_POLICY_VACUITY_INTERFACE: Final[str] = "analyze_policy_vacuity@1"

FORMAL_VACUITY_SUBJECT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-formal-vacuity-subject@1"
)
POLICY_VACUITY_SUBJECT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-policy-vacuity-subject@1"
)
VACUITY_ANALYSIS_RESULT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-vacuity-analysis-result@1"
)
VACUITY_ANALYSIS_RESULT_INTERFACE: Final[str] = "VacuityAnalysisResult@1"

GENERATOR_ID: Final[str] = "vacuity_formal_policy"
GENERATOR_VERSION: Final[str] = "1.0.0"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_LIST: Final[int] = 1_024
MAX_NONCLAIMS: Final[int] = 256
MAX_FINDINGS: Final[int] = 256
MAX_RULES: Final[int] = 1_024
MAX_STATES: Final[int] = 4_096

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_SYMBOL_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+@#$-]{0,511}$"
)


class VacuityFormalPolicyError(AssuranceBaseError):
    """Raised when formal/policy vacuity analysis inputs fail closed."""


class PolicyDefaultAction(str, Enum):
    """Closed default-action vocabulary for policy vacuity subjects."""

    ALLOW = "allow"
    DENY = "deny"
    UNDEFINED = "undefined"
    REQUIRE_CONFIRMATION = "require_confirmation"


class PolicyEffect(str, Enum):
    """Closed effect vocabulary for individual policy rules."""

    ALLOW = "allow"
    DENY = "deny"
    OBLIGE = "oblige"
    CONFIRM = "confirm"
    ABSTAIN = "abstain"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False, maximum: int = MAX_TEXT_CHARS) -> str:
    if type(value) is not str or (not empty and not value):
        raise VacuityFormalPolicyError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise VacuityFormalPolicyError(
            f"{name} must be NFC-normalized and free of leading/trailing whitespace"
        )
    if len(value) > maximum:
        raise VacuityFormalPolicyError(f"{name} exceeds maximum length")
    reject_private_model_authority_and_host_fallbacks({name: value}, path=name)
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise VacuityFormalPolicyError(f"{name} must be a boolean")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise VacuityFormalPolicyError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _symbol_id(value: Any, name: str) -> str:
    text = _text(value, name)
    if _SYMBOL_ID_RE.fullmatch(text) is None:
        raise VacuityFormalPolicyError(
            f"{name} must be a symbol identity matching {_SYMBOL_ID_RE.pattern}"
        )
    return text


def _cid(value: Any, name: str) -> str:
    text = _text(value, name)
    try:
        validate_cid(text)
    except Exception as exc:  # pragma: no cover - validate_cid raises ValueError
        raise VacuityFormalPolicyError(f"{name} must be a valid CIDv1") from exc
    return text


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    if isinstance(value, enum_type):
        return value.value
    if type(value) is str:
        try:
            return enum_type(value).value
        except ValueError as exc:
            raise VacuityFormalPolicyError(
                f"{name}={value!r} is not an admitted {enum_type.__name__}"
            ) from exc
    raise VacuityFormalPolicyError(f"{name} must be {enum_type.__name__} or string")


def _freeze_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_structured(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_structured(item) for item in value)
    return value


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_structured(item) for item in value]
    return value


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise VacuityFormalPolicyError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        missing = sorted(fields - actual)
        extra = sorted(actual - fields)
        raise VacuityFormalPolicyError(
            f"{name} field set mismatch; missing={missing}; extra={extra}"
        )
    return dict(data)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VacuityFormalPolicyError(f"{name} must be a mapping")
    reject_private_model_authority_and_host_fallbacks(value, path=name)
    validate_structured_value(value)
    return MappingProxyType(_thaw_structured(value))


def _unique_sorted_tokens(
    values: Iterable[Any],
    name: str,
    *,
    maximum: int = MAX_LIST,
    symbol: bool = False,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise VacuityFormalPolicyError(f"{name} must be a list")
    if len(values) > maximum:
        raise VacuityFormalPolicyError(f"{name} exceeds maximum length")
    seen: set[str] = set()
    out: list[str] = []
    for index, raw in enumerate(values):
        item = _symbol_id(raw, f"{name}[{index}]") if symbol else _token(raw, f"{name}[{index}]")
        if item in seen:
            raise VacuityFormalPolicyError(f"{name} must not contain duplicates")
        seen.add(item)
        out.append(item)
    return tuple(sorted(out))


def _unique_sorted_texts(
    values: Iterable[Any],
    name: str,
    *,
    maximum: int = MAX_LIST,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise VacuityFormalPolicyError(f"{name} must be a list")
    if len(values) > maximum:
        raise VacuityFormalPolicyError(f"{name} exceeds maximum length")
    seen: set[str] = set()
    out: list[str] = []
    for index, raw in enumerate(values):
        item = _text(raw, f"{name}[{index}]")
        if item in seen:
            raise VacuityFormalPolicyError(f"{name} must not contain duplicates")
        seen.add(item)
        out.append(item)
    return tuple(sorted(out))


def _normalize_source_span(
    value: SourceSpan | Mapping[str, Any],
    name: str = "source_span",
) -> SourceSpan:
    if isinstance(value, SourceSpan):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "span_cid" in value:
            try:
                return SourceSpan.from_dict(value)
            except AnalysisContractError as exc:
                raise VacuityFormalPolicyError(str(exc)) from exc
        try:
            return SourceSpan(
                path=value["path"],
                start_line=value["start_line"],
                end_line=value["end_line"],
                start_col=value.get("start_col"),
                end_col=value.get("end_col"),
            )
        except (KeyError, AnalysisContractError, TypeError) as exc:
            raise VacuityFormalPolicyError(f"{name} is malformed: {exc}") from exc
    raise VacuityFormalPolicyError(f"{name} must be SourceSpan or mapping")


def _normalize_source_spans(
    values: Sequence[SourceSpan | Mapping[str, Any]],
    name: str = "source_spans",
) -> tuple[SourceSpan, ...]:
    if not isinstance(values, (list, tuple)):
        raise VacuityFormalPolicyError(f"{name} must be a list")
    if not values:
        raise VacuityFormalPolicyError(f"{name} must not be empty")
    if len(values) > MAX_LIST:
        raise VacuityFormalPolicyError(f"{name} exceeds maximum length")
    spans = tuple(
        _normalize_source_span(item, f"{name}[{index}]")
        for index, item in enumerate(values)
    )
    return tuple(
        sorted(
            spans,
            key=lambda item: (item.path, item.start_line, item.end_line, item.span_cid),
        )
    )


def _normalize_evidence(
    value: MinimizedEvidenceBinding | Mapping[str, Any] | None,
    name: str = "minimized_evidence",
) -> MinimizedEvidenceBinding:
    if value is None:
        raise VacuityFormalPolicyError(f"{name} is required")
    if isinstance(value, MinimizedEvidenceBinding):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value or "binding_cid" in value:
                return MinimizedEvidenceBinding.from_dict(value)
            return MinimizedEvidenceBinding(
                evidence_cids=value["evidence_cids"],
                minimized=value.get("minimized", True),
                minimization_failed=value.get("minimization_failed", False),
                reproduction_input_cid=value.get("reproduction_input_cid"),
                notes=value.get("notes"),
            )
        except (KeyError, AnalysisContractError, TypeError) as exc:
            raise VacuityFormalPolicyError(f"{name} is malformed: {exc}") from exc
    raise VacuityFormalPolicyError(f"{name} must be MinimizedEvidenceBinding or mapping")


def _header(value: Any, name: str = "header") -> AssuranceArtifactHeader:
    if isinstance(value, AssuranceArtifactHeader):
        return value
    if isinstance(value, Mapping):
        try:
            return AssuranceArtifactHeader.from_dict(value)
        except AssuranceBaseError as exc:
            raise VacuityFormalPolicyError(str(exc)) from exc
    raise VacuityFormalPolicyError(f"{name} must be AssuranceArtifactHeader or mapping")


def _finding_header(
    base: AssuranceArtifactHeader,
    *,
    interface_id: str,
    symbol_ids: Sequence[str],
) -> AssuranceArtifactHeader:
    """Derive a vacuity_finding header from a caller-supplied base header."""

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
        artifact_kind="vacuity_finding",
        repository_id=base.repository_id,
        repository_state_cid=base.repository_state_cid,
        target_symbol_ids=tuple(symbol_ids) if symbol_ids else tuple(base.target_symbol_ids),
        target_artifact_cids=tuple(base.target_artifact_cids),
        capsule_cids=tuple(base.capsule_cids),
        proof_unit_cids=tuple(base.proof_unit_cids),
        environment_cid=base.environment_cid,
        dependency_lock_cid=base.dependency_lock_cid,
        versions=versions,
        provenance=base.provenance,
        terminal_status=base.terminal_status,
        receipt_cids=tuple(base.receipt_cids),
        proof_cids=tuple(base.proof_cids),
        metadata=dict(base.metadata),
    )


# ---------------------------------------------------------------------------
# Formal-proof vacuity subject
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FormalProofVacuitySubject:
    """Closed observation record for formal-proof vacuity analysis.

    Callers supply factual observations already extracted by collectors or
    provers. This module does not invent satisfiability, reachability, or
    discharge facts. Missing capability (``observation_complete=false``)
    fails closed.
    """

    subject_id: str
    claimed_property: str
    symbol_ids: Sequence[str]
    source_spans: Sequence[SourceSpan | Mapping[str, Any]]
    dependency_path: Sequence[str]
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any]
    proposition: str
    antecedent: str | None = None
    antecedent_satisfiable: bool = True
    modeled_state_ids: Sequence[str] = ()
    reachable_state_ids: Sequence[str] = ()
    discharge_possible: bool = True
    result_constrained: bool = True
    unconstrained_result_ids: Sequence[str] = ()
    required_behavior_ids: Sequence[str] = ()
    modeled_behavior_ids: Sequence[str] = ()
    assumed_ids: Sequence[str] = ()
    proven_ids: Sequence[str] = ()
    assumptions_used_as_proven: Sequence[str] = ()
    declared_nonclaims: Sequence[str] = ()
    subject_cid: str | None = None
    observation_complete: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "subject_id",
            "claimed_property",
            "symbol_ids",
            "source_spans",
            "dependency_path",
            "minimized_evidence",
            "proposition",
            "antecedent",
            "antecedent_satisfiable",
            "modeled_state_ids",
            "reachable_state_ids",
            "discharge_possible",
            "result_constrained",
            "unconstrained_result_ids",
            "required_behavior_ids",
            "modeled_behavior_ids",
            "assumed_ids",
            "proven_ids",
            "assumptions_used_as_proven",
            "declared_nonclaims",
            "subject_cid",
            "observation_complete",
            "notes",
            "metadata",
            "subject_observation_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _token(self.subject_id, "subject_id"))
        object.__setattr__(
            self,
            "claimed_property",
            _text(self.claimed_property, "claimed_property"),
        )
        symbols = _unique_sorted_tokens(
            list(self.symbol_ids), "symbol_ids", symbol=True
        )
        if not symbols:
            raise VacuityFormalPolicyError("symbol_ids must not be empty")
        object.__setattr__(self, "symbol_ids", symbols)
        spans = _normalize_source_spans(list(self.source_spans), "source_spans")
        object.__setattr__(self, "source_spans", spans)
        path = _unique_sorted_tokens(
            list(self.dependency_path), "dependency_path", symbol=True
        )
        if not path:
            raise VacuityFormalPolicyError("dependency_path must not be empty")
        object.__setattr__(self, "dependency_path", path)
        object.__setattr__(
            self,
            "minimized_evidence",
            _normalize_evidence(self.minimized_evidence),
        )
        object.__setattr__(self, "proposition", _text(self.proposition, "proposition"))
        object.__setattr__(self, "antecedent", _optional_text(self.antecedent, "antecedent"))
        object.__setattr__(
            self,
            "antecedent_satisfiable",
            _bool(self.antecedent_satisfiable, "antecedent_satisfiable"),
        )
        modeled = _unique_sorted_tokens(
            list(self.modeled_state_ids),
            "modeled_state_ids",
            symbol=True,
            maximum=MAX_STATES,
        )
        reachable = _unique_sorted_tokens(
            list(self.reachable_state_ids),
            "reachable_state_ids",
            symbol=True,
            maximum=MAX_STATES,
        )
        unknown_reachable = sorted(set(reachable) - set(modeled))
        if unknown_reachable and modeled:
            raise VacuityFormalPolicyError(
                "reachable_state_ids must be a subset of modeled_state_ids when "
                f"modeled states are declared; unknown={unknown_reachable}"
            )
        object.__setattr__(self, "modeled_state_ids", modeled)
        object.__setattr__(self, "reachable_state_ids", reachable)
        object.__setattr__(
            self,
            "discharge_possible",
            _bool(self.discharge_possible, "discharge_possible"),
        )
        object.__setattr__(
            self,
            "result_constrained",
            _bool(self.result_constrained, "result_constrained"),
        )
        unconstrained = _unique_sorted_tokens(
            list(self.unconstrained_result_ids),
            "unconstrained_result_ids",
            symbol=True,
        )
        if not self.result_constrained and not unconstrained:
            # Explicit unconstrained flag without enumerated results is admitted;
            # residual text will restate the unconstrained claim generally.
            pass
        object.__setattr__(self, "unconstrained_result_ids", unconstrained)
        required_behaviors = _unique_sorted_tokens(
            list(self.required_behavior_ids),
            "required_behavior_ids",
            symbol=True,
        )
        modeled_behaviors = _unique_sorted_tokens(
            list(self.modeled_behavior_ids),
            "modeled_behavior_ids",
            symbol=True,
        )
        object.__setattr__(self, "required_behavior_ids", required_behaviors)
        object.__setattr__(self, "modeled_behavior_ids", modeled_behaviors)
        assumed = _unique_sorted_tokens(
            list(self.assumed_ids), "assumed_ids", symbol=True
        )
        proven = _unique_sorted_tokens(list(self.proven_ids), "proven_ids", symbol=True)
        used_as_proven = _unique_sorted_tokens(
            list(self.assumptions_used_as_proven),
            "assumptions_used_as_proven",
            symbol=True,
        )
        object.__setattr__(self, "assumed_ids", assumed)
        object.__setattr__(self, "proven_ids", proven)
        object.__setattr__(self, "assumptions_used_as_proven", used_as_proven)
        nonclaims = _unique_sorted_texts(
            list(self.declared_nonclaims),
            "declared_nonclaims",
            maximum=MAX_NONCLAIMS,
        )
        object.__setattr__(self, "declared_nonclaims", nonclaims)
        object.__setattr__(
            self, "subject_cid", _optional_cid(self.subject_cid, "subject_cid")
        )
        object.__setattr__(
            self,
            "observation_complete",
            _bool(self.observation_complete, "observation_complete"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": FORMAL_VACUITY_SUBJECT_SCHEMA,
            "subject_id": self.subject_id,
            "claimed_property": self.claimed_property,
            "symbol_ids": list(self.symbol_ids),
            "source_spans": [span.identity_payload() for span in self.source_spans],
            "dependency_path": list(self.dependency_path),
            "minimized_evidence": self.minimized_evidence.identity_payload(),
            "proposition": self.proposition,
            "antecedent": self.antecedent,
            "antecedent_satisfiable": self.antecedent_satisfiable,
            "modeled_state_ids": list(self.modeled_state_ids),
            "reachable_state_ids": list(self.reachable_state_ids),
            "discharge_possible": self.discharge_possible,
            "result_constrained": self.result_constrained,
            "unconstrained_result_ids": list(self.unconstrained_result_ids),
            "required_behavior_ids": list(self.required_behavior_ids),
            "modeled_behavior_ids": list(self.modeled_behavior_ids),
            "assumed_ids": list(self.assumed_ids),
            "proven_ids": list(self.proven_ids),
            "assumptions_used_as_proven": list(self.assumptions_used_as_proven),
            "declared_nonclaims": list(self.declared_nonclaims),
            "subject_cid": self.subject_cid,
            "observation_complete": self.observation_complete,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def subject_observation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["source_spans"] = [span.to_dict() for span in self.source_spans]
        value["minimized_evidence"] = self.minimized_evidence.to_dict()
        value["subject_observation_cid"] = self.subject_observation_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FormalProofVacuitySubject":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("subject_observation_cid")
        if payload.pop("schema") != FORMAL_VACUITY_SUBJECT_SCHEMA:
            raise VacuityFormalPolicyError(
                "unsupported FormalProofVacuitySubject schema version"
            )
        result = cls(
            subject_id=payload["subject_id"],
            claimed_property=payload["claimed_property"],
            symbol_ids=payload["symbol_ids"],
            source_spans=payload["source_spans"],
            dependency_path=payload["dependency_path"],
            minimized_evidence=payload["minimized_evidence"],
            proposition=payload["proposition"],
            antecedent=payload["antecedent"],
            antecedent_satisfiable=payload["antecedent_satisfiable"],
            modeled_state_ids=payload["modeled_state_ids"],
            reachable_state_ids=payload["reachable_state_ids"],
            discharge_possible=payload["discharge_possible"],
            result_constrained=payload["result_constrained"],
            unconstrained_result_ids=payload["unconstrained_result_ids"],
            required_behavior_ids=payload["required_behavior_ids"],
            modeled_behavior_ids=payload["modeled_behavior_ids"],
            assumed_ids=payload["assumed_ids"],
            proven_ids=payload["proven_ids"],
            assumptions_used_as_proven=payload["assumptions_used_as_proven"],
            declared_nonclaims=payload["declared_nonclaims"],
            subject_cid=payload["subject_cid"],
            observation_complete=payload["observation_complete"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.subject_observation_cid:
            raise VacuityFormalPolicyError(
                "FormalProofVacuitySubject subject_observation_cid identity mismatch"
            )
        return result


def _normalize_formal_subject(
    value: FormalProofVacuitySubject | Mapping[str, Any],
) -> FormalProofVacuitySubject:
    if isinstance(value, FormalProofVacuitySubject):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "subject_observation_cid" in value:
            return FormalProofVacuitySubject.from_dict(value)
        fields = {
            key: value[key]
            for key in FormalProofVacuitySubject._FIELDS
            if key not in {"schema", "subject_observation_cid"} and key in value
        }
        return FormalProofVacuitySubject(**fields)  # type: ignore[arg-type]
    raise VacuityFormalPolicyError(
        "subject must be FormalProofVacuitySubject or mapping"
    )


# ---------------------------------------------------------------------------
# Policy vacuity subject
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PolicyRuleObservation:
    """One policy rule observed on a policy vacuity subject."""

    rule_id: str
    effect: PolicyEffect | str
    reachable: bool = True
    is_prohibition: bool = False
    shadowed_by_rule_ids: Sequence[str] = ()
    obligation_satisfiable: bool = True
    is_default: bool = False
    interface_reference_id: str | None = None
    interface_obsolete: bool = False
    is_confirmation: bool = False
    notes: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "rule_id",
            "effect",
            "reachable",
            "is_prohibition",
            "shadowed_by_rule_ids",
            "obligation_satisfiable",
            "is_default",
            "interface_reference_id",
            "interface_obsolete",
            "is_confirmation",
            "notes",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _token(self.rule_id, "rule_id"))
        effect = _enum(self.effect, PolicyEffect, "effect")
        object.__setattr__(self, "effect", effect)
        object.__setattr__(self, "reachable", _bool(self.reachable, "reachable"))
        object.__setattr__(
            self, "is_prohibition", _bool(self.is_prohibition, "is_prohibition")
        )
        shadowed = _unique_sorted_tokens(
            list(self.shadowed_by_rule_ids), "shadowed_by_rule_ids"
        )
        object.__setattr__(self, "shadowed_by_rule_ids", shadowed)
        object.__setattr__(
            self,
            "obligation_satisfiable",
            _bool(self.obligation_satisfiable, "obligation_satisfiable"),
        )
        object.__setattr__(self, "is_default", _bool(self.is_default, "is_default"))
        if self.interface_reference_id is None:
            object.__setattr__(self, "interface_reference_id", None)
        else:
            object.__setattr__(
                self,
                "interface_reference_id",
                _symbol_id(self.interface_reference_id, "interface_reference_id"),
            )
        object.__setattr__(
            self,
            "interface_obsolete",
            _bool(self.interface_obsolete, "interface_obsolete"),
        )
        object.__setattr__(
            self, "is_confirmation", _bool(self.is_confirmation, "is_confirmation")
        )
        # Fail closed: prohibition effect consistency.
        if self.is_prohibition and effect not in {
            PolicyEffect.DENY.value,
            PolicyEffect.ABSTAIN.value,
        }:
            raise VacuityFormalPolicyError(
                "is_prohibition requires effect deny or abstain"
            )
        if effect == PolicyEffect.OBLIGE.value and self.is_prohibition:
            raise VacuityFormalPolicyError(
                "obligation rules cannot also be prohibitions"
            )
        if self.is_confirmation and effect != PolicyEffect.CONFIRM.value:
            raise VacuityFormalPolicyError(
                "is_confirmation requires effect confirm"
            )
        if self.interface_obsolete and self.interface_reference_id is None:
            raise VacuityFormalPolicyError(
                "interface_obsolete requires interface_reference_id"
            )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "effect": self.effect
            if isinstance(self.effect, str)
            else self.effect.value,
            "reachable": self.reachable,
            "is_prohibition": self.is_prohibition,
            "shadowed_by_rule_ids": list(self.shadowed_by_rule_ids),
            "obligation_satisfiable": self.obligation_satisfiable,
            "is_default": self.is_default,
            "interface_reference_id": self.interface_reference_id,
            "interface_obsolete": self.interface_obsolete,
            "is_confirmation": self.is_confirmation,
            "notes": self.notes,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.identity_payload()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PolicyRuleObservation":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class PolicyVacuitySubject:
    """Closed observation record for policy vacuity analysis.

    Facts are supplied by collectors. This analyzer never elevates presence of
    a rule text into reachability, nor a default into a proven constraint on
    every decision path.
    """

    subject_id: str
    claimed_property: str
    symbol_ids: Sequence[str]
    source_spans: Sequence[SourceSpan | Mapping[str, Any]]
    dependency_path: Sequence[str]
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any]
    rules: Sequence[PolicyRuleObservation | Mapping[str, Any]] = ()
    default_action: PolicyDefaultAction | str | None = None
    default_dominates_specific_rules: bool = False
    obsolete_interface_reference_ids: Sequence[str] = ()
    live_interface_reference_ids: Sequence[str] = ()
    declared_nonclaims: Sequence[str] = ()
    subject_cid: str | None = None
    observation_complete: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "subject_id",
            "claimed_property",
            "symbol_ids",
            "source_spans",
            "dependency_path",
            "minimized_evidence",
            "rules",
            "default_action",
            "default_dominates_specific_rules",
            "obsolete_interface_reference_ids",
            "live_interface_reference_ids",
            "declared_nonclaims",
            "subject_cid",
            "observation_complete",
            "notes",
            "metadata",
            "subject_observation_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _token(self.subject_id, "subject_id"))
        object.__setattr__(
            self,
            "claimed_property",
            _text(self.claimed_property, "claimed_property"),
        )
        symbols = _unique_sorted_tokens(
            list(self.symbol_ids), "symbol_ids", symbol=True
        )
        if not symbols:
            raise VacuityFormalPolicyError("symbol_ids must not be empty")
        object.__setattr__(self, "symbol_ids", symbols)
        spans = _normalize_source_spans(list(self.source_spans), "source_spans")
        object.__setattr__(self, "source_spans", spans)
        path = _unique_sorted_tokens(
            list(self.dependency_path), "dependency_path", symbol=True
        )
        if not path:
            raise VacuityFormalPolicyError("dependency_path must not be empty")
        object.__setattr__(self, "dependency_path", path)
        object.__setattr__(
            self,
            "minimized_evidence",
            _normalize_evidence(self.minimized_evidence),
        )
        rules = _normalize_rules(list(self.rules))
        object.__setattr__(self, "rules", rules)
        if self.default_action is None:
            object.__setattr__(self, "default_action", None)
        else:
            object.__setattr__(
                self,
                "default_action",
                _enum(self.default_action, PolicyDefaultAction, "default_action"),
            )
        object.__setattr__(
            self,
            "default_dominates_specific_rules",
            _bool(
                self.default_dominates_specific_rules,
                "default_dominates_specific_rules",
            ),
        )
        obsolete = _unique_sorted_tokens(
            list(self.obsolete_interface_reference_ids),
            "obsolete_interface_reference_ids",
            symbol=True,
        )
        live = _unique_sorted_tokens(
            list(self.live_interface_reference_ids),
            "live_interface_reference_ids",
            symbol=True,
        )
        overlap = sorted(set(obsolete) & set(live))
        if overlap:
            raise VacuityFormalPolicyError(
                "obsolete_interface_reference_ids and live_interface_reference_ids "
                f"must be disjoint; overlap={overlap}"
            )
        object.__setattr__(self, "obsolete_interface_reference_ids", obsolete)
        object.__setattr__(self, "live_interface_reference_ids", live)
        nonclaims = _unique_sorted_texts(
            list(self.declared_nonclaims),
            "declared_nonclaims",
            maximum=MAX_NONCLAIMS,
        )
        object.__setattr__(self, "declared_nonclaims", nonclaims)
        object.__setattr__(
            self, "subject_cid", _optional_cid(self.subject_cid, "subject_cid")
        )
        object.__setattr__(
            self,
            "observation_complete",
            _bool(self.observation_complete, "observation_complete"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": POLICY_VACUITY_SUBJECT_SCHEMA,
            "subject_id": self.subject_id,
            "claimed_property": self.claimed_property,
            "symbol_ids": list(self.symbol_ids),
            "source_spans": [span.identity_payload() for span in self.source_spans],
            "dependency_path": list(self.dependency_path),
            "minimized_evidence": self.minimized_evidence.identity_payload(),
            "rules": [item.identity_payload() for item in self.rules],
            "default_action": self.default_action,
            "default_dominates_specific_rules": self.default_dominates_specific_rules,
            "obsolete_interface_reference_ids": list(
                self.obsolete_interface_reference_ids
            ),
            "live_interface_reference_ids": list(self.live_interface_reference_ids),
            "declared_nonclaims": list(self.declared_nonclaims),
            "subject_cid": self.subject_cid,
            "observation_complete": self.observation_complete,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def subject_observation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["source_spans"] = [span.to_dict() for span in self.source_spans]
        value["minimized_evidence"] = self.minimized_evidence.to_dict()
        value["rules"] = [item.to_dict() for item in self.rules]
        value["subject_observation_cid"] = self.subject_observation_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PolicyVacuitySubject":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("subject_observation_cid")
        if payload.pop("schema") != POLICY_VACUITY_SUBJECT_SCHEMA:
            raise VacuityFormalPolicyError(
                "unsupported PolicyVacuitySubject schema version"
            )
        result = cls(
            subject_id=payload["subject_id"],
            claimed_property=payload["claimed_property"],
            symbol_ids=payload["symbol_ids"],
            source_spans=payload["source_spans"],
            dependency_path=payload["dependency_path"],
            minimized_evidence=payload["minimized_evidence"],
            rules=payload["rules"],
            default_action=payload["default_action"],
            default_dominates_specific_rules=payload[
                "default_dominates_specific_rules"
            ],
            obsolete_interface_reference_ids=payload[
                "obsolete_interface_reference_ids"
            ],
            live_interface_reference_ids=payload["live_interface_reference_ids"],
            declared_nonclaims=payload["declared_nonclaims"],
            subject_cid=payload["subject_cid"],
            observation_complete=payload["observation_complete"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.subject_observation_cid:
            raise VacuityFormalPolicyError(
                "PolicyVacuitySubject subject_observation_cid identity mismatch"
            )
        return result


def _normalize_rules(
    values: Sequence[PolicyRuleObservation | Mapping[str, Any]],
) -> tuple[PolicyRuleObservation, ...]:
    if not isinstance(values, (list, tuple)):
        raise VacuityFormalPolicyError("rules must be a list")
    if len(values) > MAX_RULES:
        raise VacuityFormalPolicyError("rules exceeds maximum length")
    out: list[PolicyRuleObservation] = []
    seen: set[str] = set()
    for index, raw in enumerate(values):
        if isinstance(raw, PolicyRuleObservation):
            item = raw
        elif isinstance(raw, Mapping):
            item = PolicyRuleObservation.from_dict(raw)
        else:
            raise VacuityFormalPolicyError(
                f"rules[{index}] must be PolicyRuleObservation or mapping"
            )
        if item.rule_id in seen:
            raise VacuityFormalPolicyError("rules must have unique rule_id values")
        seen.add(item.rule_id)
        out.append(item)
    return tuple(sorted(out, key=lambda item: item.rule_id))


def _normalize_policy_subject(
    value: PolicyVacuitySubject | Mapping[str, Any],
) -> PolicyVacuitySubject:
    if isinstance(value, PolicyVacuitySubject):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "subject_observation_cid" in value:
            return PolicyVacuitySubject.from_dict(value)
        fields = {
            key: value[key]
            for key in PolicyVacuitySubject._FIELDS
            if key not in {"schema", "subject_observation_cid"} and key in value
        }
        return PolicyVacuitySubject(**fields)  # type: ignore[arg-type]
    raise VacuityFormalPolicyError("subject must be PolicyVacuitySubject or mapping")


# ---------------------------------------------------------------------------
# Analysis result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VacuityAnalysisResult:
    """Deterministic result of one formal/policy vacuity analysis run.

    Interface: ``VacuityAnalysisResult@1``
    """

    interface_id: str
    vacuity_family: VacuityFamily | str
    subject_id: str
    subject_observation_cid: str
    findings: Sequence[VacuityFinding | Mapping[str, Any]]
    finding_cids: Sequence[str]
    residual_properties: Sequence[str]
    precise_nonclaims: Sequence[str]
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "vacuity_family",
            "subject_id",
            "subject_observation_cid",
            "findings",
            "finding_cids",
            "residual_properties",
            "precise_nonclaims",
            "notes",
            "metadata",
            "result_cid",
        }
    )

    def __post_init__(self) -> None:
        interface_id = _text(self.interface_id, "interface_id")
        if interface_id not in {
            ANALYZE_FORMAL_VACUITY_INTERFACE,
            ANALYZE_POLICY_VACUITY_INTERFACE,
        }:
            raise VacuityFormalPolicyError(
                "interface_id must be analyze_formal_vacuity@1 or "
                "analyze_policy_vacuity@1"
            )
        object.__setattr__(self, "interface_id", interface_id)
        family = _enum(self.vacuity_family, VacuityFamily, "vacuity_family")
        if interface_id == ANALYZE_FORMAL_VACUITY_INTERFACE:
            if family != VacuityFamily.FORMAL_PROOF.value:
                raise VacuityFormalPolicyError(
                    "analyze_formal_vacuity@1 requires vacuity_family=formal_proof"
                )
        else:
            if family != VacuityFamily.POLICY.value:
                raise VacuityFormalPolicyError(
                    "analyze_policy_vacuity@1 requires vacuity_family=policy"
                )
        object.__setattr__(self, "vacuity_family", family)
        object.__setattr__(self, "subject_id", _token(self.subject_id, "subject_id"))
        object.__setattr__(
            self,
            "subject_observation_cid",
            _cid(self.subject_observation_cid, "subject_observation_cid"),
        )
        findings = _normalize_findings(list(self.findings))
        if len(findings) > MAX_FINDINGS:
            raise VacuityFormalPolicyError("findings exceeds maximum length")
        object.__setattr__(self, "findings", findings)
        claimed_cids = _unique_sorted_texts(
            list(self.finding_cids), "finding_cids", maximum=MAX_FINDINGS
        )
        actual_cids = tuple(sorted(item.finding_cid for item in findings))
        if claimed_cids != actual_cids:
            raise VacuityFormalPolicyError(
                "finding_cids must exactly match sorted finding identities"
            )
        object.__setattr__(self, "finding_cids", claimed_cids)
        residuals = _unique_sorted_texts(
            list(self.residual_properties), "residual_properties"
        )
        nonclaims = _unique_sorted_texts(
            list(self.precise_nonclaims), "precise_nonclaims", maximum=MAX_NONCLAIMS
        )
        if findings:
            if not residuals:
                raise VacuityFormalPolicyError(
                    "residual_properties must restate what remains proven"
                )
            if not nonclaims:
                raise VacuityFormalPolicyError(
                    "precise_nonclaims must restate what is not proven"
                )
        object.__setattr__(self, "residual_properties", residuals)
        object.__setattr__(self, "precise_nonclaims", nonclaims)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": VACUITY_ANALYSIS_RESULT_SCHEMA,
            "interface_id": self.interface_id,
            "vacuity_family": self.vacuity_family
            if isinstance(self.vacuity_family, str)
            else self.vacuity_family.value,
            "subject_id": self.subject_id,
            "subject_observation_cid": self.subject_observation_cid,
            "findings": [item.identity_payload() for item in self.findings],
            "finding_cids": list(self.finding_cids),
            "residual_properties": list(self.residual_properties),
            "precise_nonclaims": list(self.precise_nonclaims),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def result_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": VACUITY_ANALYSIS_RESULT_SCHEMA,
            "interface_id": self.interface_id,
            "vacuity_family": self.vacuity_family
            if isinstance(self.vacuity_family, str)
            else self.vacuity_family.value,
            "subject_id": self.subject_id,
            "subject_observation_cid": self.subject_observation_cid,
            "findings": [item.to_dict() for item in self.findings],
            "finding_cids": list(self.finding_cids),
            "residual_properties": list(self.residual_properties),
            "precise_nonclaims": list(self.precise_nonclaims),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "result_cid": self.result_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VacuityAnalysisResult":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("result_cid")
        if payload.pop("schema") != VACUITY_ANALYSIS_RESULT_SCHEMA:
            raise VacuityFormalPolicyError(
                "unsupported VacuityAnalysisResult schema version"
            )
        result = cls(
            interface_id=payload["interface_id"],
            vacuity_family=payload["vacuity_family"],
            subject_id=payload["subject_id"],
            subject_observation_cid=payload["subject_observation_cid"],
            findings=payload["findings"],
            finding_cids=payload["finding_cids"],
            residual_properties=payload["residual_properties"],
            precise_nonclaims=payload["precise_nonclaims"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.result_cid:
            raise VacuityFormalPolicyError(
                "VacuityAnalysisResult result_cid identity mismatch"
            )
        return result


def _normalize_findings(
    values: Sequence[VacuityFinding | Mapping[str, Any]],
) -> tuple[VacuityFinding, ...]:
    if not isinstance(values, (list, tuple)):
        raise VacuityFormalPolicyError("findings must be a list")
    out: list[VacuityFinding] = []
    for index, raw in enumerate(values):
        if isinstance(raw, VacuityFinding):
            item = raw
        elif isinstance(raw, Mapping):
            try:
                item = VacuityFinding.from_dict(raw)
            except AnalysisContractError as exc:
                raise VacuityFormalPolicyError(
                    f"findings[{index}] is malformed: {exc}"
                ) from exc
        else:
            raise VacuityFormalPolicyError(
                f"findings[{index}] must be VacuityFinding or mapping"
            )
        try:
            verify_vacuity_finding_identity(item)
        except AnalysisContractError as exc:
            raise VacuityFormalPolicyError(str(exc)) from exc
        out.append(item)
    return tuple(sorted(out, key=lambda item: (item.vacuity_kind, item.finding_id)))


# ---------------------------------------------------------------------------
# Finding construction
# ---------------------------------------------------------------------------


def _make_finding(
    *,
    header: AssuranceArtifactHeader,
    finding_id: str,
    family: VacuityFamily,
    kind: VacuityKind,
    subject_id: str,
    subject_cid: str | None,
    vacuous_claim: str,
    remains: str,
    not_proven: str,
    symbol_ids: Sequence[str],
    source_spans: Sequence[SourceSpan],
    dependency_path: Sequence[str],
    evidence: MinimizedEvidenceBinding,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> VacuityFinding:
    return VacuityFinding(
        header=header,
        finding_id=finding_id,
        vacuity_family=family,
        vacuity_kind=kind,
        subject_id=subject_id,
        subject_cid=subject_cid,
        vacuous_claim=vacuous_claim,
        what_remains_proven=remains,
        what_is_not_proven=not_proven,
        symbol_ids=symbol_ids,
        source_spans=source_spans,
        dependency_path=dependency_path,
        minimized_evidence=evidence,
        notes=notes,
        metadata=dict(metadata or {}),
    )


def _merge_nonclaims(
    findings: Sequence[VacuityFinding],
    declared: Sequence[str],
) -> tuple[str, ...]:
    residuals_from_findings = {item.what_is_not_proven for item in findings}
    merged = set(residuals_from_findings)
    merged.update(declared)
    return tuple(sorted(merged))


# ---------------------------------------------------------------------------
# analyze_formal_vacuity@1
# ---------------------------------------------------------------------------


def analyze_formal_vacuity(
    subject: FormalProofVacuitySubject | Mapping[str, Any],
    header: AssuranceArtifactHeader | Mapping[str, Any],
    *,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> VacuityAnalysisResult:
    """Detect formal-proof vacuity and emit precise residual / nonclaim findings.

    Interface: ``analyze_formal_vacuity@1``

    Fail-closed when observation is incomplete or the subject cannot be sealed.
    Deterministic: same sealed subject and header inputs always yield the same
    result CID and finding set.
    """

    sealed_subject = _normalize_formal_subject(subject)
    if not sealed_subject.observation_complete:
        raise VacuityFormalPolicyError(
            "analyze_formal_vacuity fails closed when observation_complete is false"
        )
    base_header = _header(header)
    finding_header = _finding_header(
        base_header,
        interface_id=ANALYZE_FORMAL_VACUITY_INTERFACE,
        symbol_ids=sealed_subject.symbol_ids,
    )
    findings: list[VacuityFinding] = []
    claim = sealed_subject.claimed_property
    proposition = sealed_subject.proposition
    declared = list(sealed_subject.declared_nonclaims)

    # --- unsatisfiable antecedent ---
    if not sealed_subject.antecedent_satisfiable:
        antecedent_text = sealed_subject.antecedent or "declared antecedent"
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.unsatisfiable_antecedent",
                family=VacuityFamily.FORMAL_PROOF,
                kind=VacuityKind.UNSATISFIABLE_ANTECEDENT,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=(
                    f"implication holds vacuously under unsatisfiable antecedent: "
                    f"{antecedent_text}"
                ),
                not_proven=(
                    f"proposition is not established for any reachable state; "
                    f"antecedent is unsatisfiable: {proposition}; claimed: {claim}"
                ),
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
                notes="unsatisfiable antecedents never exercise the consequent",
                metadata={
                    "antecedent": sealed_subject.antecedent,
                    "proposition": proposition,
                },
            )
        )

    # --- unreachable modeled state ---
    if sealed_subject.modeled_state_ids:
        unreachable = sorted(
            set(sealed_subject.modeled_state_ids)
            - set(sealed_subject.reachable_state_ids)
        )
        if unreachable:
            unreachable_list = ", ".join(unreachable)
            reachable_list = (
                ", ".join(sealed_subject.reachable_state_ids) or "(none)"
            )
            findings.append(
                _make_finding(
                    header=finding_header,
                    finding_id=f"{sealed_subject.subject_id}.unreachable_modeled_state",
                    family=VacuityFamily.FORMAL_PROOF,
                    kind=VacuityKind.UNREACHABLE_MODELED_STATE,
                    subject_id=sealed_subject.subject_id,
                    subject_cid=sealed_subject.subject_cid,
                    vacuous_claim=claim,
                    remains=(
                        f"proof covers modeled states that remain unreachable: "
                        f"{unreachable_list}; reachable modeled states: "
                        f"{reachable_list}"
                    ),
                    not_proven=(
                        f"behavior on unreachable modeled states is not proven for "
                        f"any executable path: {unreachable_list}; claimed: {claim}"
                    ),
                    symbol_ids=sealed_subject.symbol_ids,
                    source_spans=sealed_subject.source_spans,
                    dependency_path=sealed_subject.dependency_path,
                    evidence=sealed_subject.minimized_evidence,
                    notes="unreachable modeled states contribute vacuous coverage",
                    metadata={
                        "unreachable_state_ids": unreachable,
                        "reachable_state_ids": list(
                            sealed_subject.reachable_state_ids
                        ),
                    },
                )
            )

    # --- impossible discharge ---
    if not sealed_subject.discharge_possible:
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.impossible_discharge",
                family=VacuityFamily.FORMAL_PROOF,
                kind=VacuityKind.IMPOSSIBLE_DISCHARGE,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=(
                    f"proof obligation structure is recorded for proposition: "
                    f"{proposition}"
                ),
                not_proven=(
                    f"obligation cannot be discharged under the admitted proof "
                    f"system; property not proven: {claim}"
                ),
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
                notes="impossible discharge never yields a proven residual property",
                metadata={"proposition": proposition},
            )
        )

    # --- unconstrained result ---
    if (
        not sealed_subject.result_constrained
        or sealed_subject.unconstrained_result_ids
    ):
        if sealed_subject.unconstrained_result_ids:
            result_list = ", ".join(sealed_subject.unconstrained_result_ids)
            remains = (
                f"proof admits unconstrained results for: {result_list}"
            )
            not_proven = (
                f"values of unconstrained results are not fixed by the proof: "
                f"{result_list}; claimed: {claim}"
            )
        else:
            remains = (
                f"proof structure validates without constraining results of "
                f"proposition: {proposition}"
            )
            not_proven = (
                f"result values are unconstrained; claimed property is not "
                f"established: {claim}"
            )
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.unconstrained_result",
                family=VacuityFamily.FORMAL_PROOF,
                kind=VacuityKind.UNCONSTRAINED_RESULT,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=remains,
                not_proven=not_proven,
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
                notes="unconstrained results leave postconditions open",
                metadata={
                    "unconstrained_result_ids": list(
                        sealed_subject.unconstrained_result_ids
                    ),
                    "result_constrained": sealed_subject.result_constrained,
                },
            )
        )

    # --- omitted behavior ---
    if sealed_subject.required_behavior_ids:
        omitted = sorted(
            set(sealed_subject.required_behavior_ids)
            - set(sealed_subject.modeled_behavior_ids)
        )
        if omitted:
            omitted_list = ", ".join(omitted)
            modeled_list = (
                ", ".join(sealed_subject.modeled_behavior_ids) or "(none)"
            )
            findings.append(
                _make_finding(
                    header=finding_header,
                    finding_id=f"{sealed_subject.subject_id}.omitted_behavior",
                    family=VacuityFamily.FORMAL_PROOF,
                    kind=VacuityKind.OMITTED_BEHAVIOR,
                    subject_id=sealed_subject.subject_id,
                    subject_cid=sealed_subject.subject_cid,
                    vacuous_claim=claim,
                    remains=(
                        f"proof models a subset of required behaviors: "
                        f"{modeled_list}"
                    ),
                    not_proven=(
                        f"omitted required behaviors are outside the model and "
                        f"are not proven: {omitted_list}; claimed: {claim}"
                    ),
                    symbol_ids=sealed_subject.symbol_ids,
                    source_spans=sealed_subject.source_spans,
                    dependency_path=sealed_subject.dependency_path,
                    evidence=sealed_subject.minimized_evidence,
                    notes="omitted behaviors never inherit proof coverage",
                    metadata={
                        "omitted_behavior_ids": omitted,
                        "modeled_behavior_ids": list(
                            sealed_subject.modeled_behavior_ids
                        ),
                    },
                )
            )

    # --- assumed not proven ---
    assumed_as_proven = set(sealed_subject.assumptions_used_as_proven)
    # Assumptions present but not in proven_ids are also residual nonproofs when
    # they are recorded as used-as-proven, or when assumed exceeds proven.
    unproven_assumptions = sorted(
        (set(sealed_subject.assumed_ids) - set(sealed_subject.proven_ids))
        | assumed_as_proven
    )
    # Only fire when something is actually treated as established without proof.
    if unproven_assumptions and (
        sealed_subject.assumptions_used_as_proven
        or (
            sealed_subject.assumed_ids
            and not set(sealed_subject.assumed_ids).issubset(
                set(sealed_subject.proven_ids)
            )
            and sealed_subject.assumptions_used_as_proven
        )
        or sealed_subject.assumptions_used_as_proven
    ):
        # Prefer explicit assumptions_used_as_proven; fall back to assumed\proven
        # only when the subject marks those assumptions as used-as-proven.
        targets = sorted(set(sealed_subject.assumptions_used_as_proven))
        if not targets:
            targets = unproven_assumptions
        target_list = ", ".join(targets)
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.assumed_not_proven",
                family=VacuityFamily.FORMAL_PROOF,
                kind=VacuityKind.ASSUMED_NOT_PROVEN,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=(
                    f"proof proceeds under assumptions treated as established: "
                    f"{target_list}"
                ),
                not_proven=(
                    f"assumptions were not independently proven and do not "
                    f"establish the claimed property: {target_list}; claimed: "
                    f"{claim}"
                ),
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
                notes="assumed premises are not residual proofs of the claim",
                metadata={
                    "assumptions_used_as_proven": list(
                        sealed_subject.assumptions_used_as_proven
                    ),
                    "assumed_ids": list(sealed_subject.assumed_ids),
                    "proven_ids": list(sealed_subject.proven_ids),
                },
            )
        )
    elif sealed_subject.assumptions_used_as_proven:
        # Defensive branch: already covered above.
        pass
    elif sealed_subject.assumed_ids and sealed_subject.assumptions_used_as_proven == ():
        # Pure assumed_ids without used-as-proven markers: still vacuous when
        # assumed set is non-empty and none are proven AND the subject claims
        # the property (collectors should set assumptions_used_as_proven).
        # We only fire when proven is a proper subset and assumed is nonempty
        # with zero proven overlap — treat as assumed_not_proven.
        if not set(sealed_subject.assumed_ids) & set(sealed_subject.proven_ids):
            target_list = ", ".join(sealed_subject.assumed_ids)
            findings.append(
                _make_finding(
                    header=finding_header,
                    finding_id=f"{sealed_subject.subject_id}.assumed_not_proven",
                    family=VacuityFamily.FORMAL_PROOF,
                    kind=VacuityKind.ASSUMED_NOT_PROVEN,
                    subject_id=sealed_subject.subject_id,
                    subject_cid=sealed_subject.subject_cid,
                    vacuous_claim=claim,
                    remains=(
                        f"proof depends on undischarged assumptions: {target_list}"
                    ),
                    not_proven=(
                        f"undischarged assumptions are not proven and do not "
                        f"establish the claimed property: {target_list}; claimed: "
                        f"{claim}"
                    ),
                    symbol_ids=sealed_subject.symbol_ids,
                    source_spans=sealed_subject.source_spans,
                    dependency_path=sealed_subject.dependency_path,
                    evidence=sealed_subject.minimized_evidence,
                    notes="undischarged assumptions never prove the consequent",
                    metadata={
                        "assumed_ids": list(sealed_subject.assumed_ids),
                        "proven_ids": list(sealed_subject.proven_ids),
                    },
                )
            )

    findings_sorted = tuple(
        sorted(findings, key=lambda item: (item.vacuity_kind, item.finding_id))
    )
    residuals = tuple(sorted({item.what_remains_proven for item in findings_sorted}))
    nonclaims = _merge_nonclaims(findings_sorted, declared)
    result_metadata = dict(metadata or {})
    result_metadata.setdefault(
        "subject_observation_cid", sealed_subject.subject_observation_cid
    )
    if declared:
        result_metadata["declared_nonclaims"] = list(declared)
    return VacuityAnalysisResult(
        interface_id=ANALYZE_FORMAL_VACUITY_INTERFACE,
        vacuity_family=VacuityFamily.FORMAL_PROOF,
        subject_id=sealed_subject.subject_id,
        subject_observation_cid=sealed_subject.subject_observation_cid,
        findings=findings_sorted,
        finding_cids=tuple(sorted(item.finding_cid for item in findings_sorted)),
        residual_properties=residuals,
        precise_nonclaims=nonclaims,
        notes=_optional_text(notes, "notes") if notes is not None else None,
        metadata=result_metadata,
    )


# ---------------------------------------------------------------------------
# analyze_policy_vacuity@1
# ---------------------------------------------------------------------------


def analyze_policy_vacuity(
    subject: PolicyVacuitySubject | Mapping[str, Any],
    header: AssuranceArtifactHeader | Mapping[str, Any],
    *,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> VacuityAnalysisResult:
    """Detect policy vacuity with precise residual nonclaims.

    Interface: ``analyze_policy_vacuity@1``

    Rule text presence never elevates to reachability. Shadowed prohibitions,
    dominating defaults, and obsolete interface references never establish the
    claimed authorization/constraint property.
    """

    sealed_subject = _normalize_policy_subject(subject)
    if not sealed_subject.observation_complete:
        raise VacuityFormalPolicyError(
            "analyze_policy_vacuity fails closed when observation_complete is false"
        )
    base_header = _header(header)
    finding_header = _finding_header(
        base_header,
        interface_id=ANALYZE_POLICY_VACUITY_INTERFACE,
        symbol_ids=sealed_subject.symbol_ids,
    )
    findings: list[VacuityFinding] = []
    claim = sealed_subject.claimed_property
    declared = list(sealed_subject.declared_nonclaims)
    rules = sealed_subject.rules

    # --- unreachable rules ---
    unreachable_rules = [item for item in rules if not item.reachable]
    if unreachable_rules:
        rule_ids = ", ".join(sorted(item.rule_id for item in unreachable_rules))
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.unreachable_rule",
                family=VacuityFamily.POLICY,
                kind=VacuityKind.UNREACHABLE_RULE,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=(
                    f"policy text includes rules that evaluation never reaches: "
                    f"{rule_ids}"
                ),
                not_proven=(
                    f"unreachable rules never constrain decisions; property not "
                    f"proven by those rules: {rule_ids}; claimed: {claim}"
                ),
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
                notes="unreachable rules contribute zero enforcement power",
                metadata={
                    "unreachable_rule_ids": sorted(
                        item.rule_id for item in unreachable_rules
                    )
                },
            )
        )

    # --- unreachable confirmations ---
    unreachable_confirmations = [
        item
        for item in rules
        if item.is_confirmation and not item.reachable
    ]
    # Also treat confirm-effect rules that are unreachable even if flag omitted
    # when effect is confirm and not reachable (already covered by is_confirmation).
    if not unreachable_confirmations:
        unreachable_confirmations = [
            item
            for item in rules
            if item.effect == PolicyEffect.CONFIRM.value and not item.reachable
        ]
    if unreachable_confirmations:
        conf_ids = ", ".join(
            sorted(item.rule_id for item in unreachable_confirmations)
        )
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.unreachable_confirmation",
                family=VacuityFamily.POLICY,
                kind=VacuityKind.UNREACHABLE_CONFIRMATION,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=(
                    f"confirmation steps exist in policy text but are never "
                    f"reached: {conf_ids}"
                ),
                not_proven=(
                    f"unreachable confirmations never bind operator approval; "
                    f"property not proven: {conf_ids}; claimed: {claim}"
                ),
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
                notes="unreachable confirmations vacate dual-control claims",
                metadata={
                    "unreachable_confirmation_ids": sorted(
                        item.rule_id for item in unreachable_confirmations
                    )
                },
            )
        )

    # --- shadowed prohibitions ---
    shadowed_prohibitions = [
        item
        for item in rules
        if item.is_prohibition and item.shadowed_by_rule_ids
    ]
    if shadowed_prohibitions:
        details = []
        for item in sorted(shadowed_prohibitions, key=lambda r: r.rule_id):
            shadows = ", ".join(item.shadowed_by_rule_ids)
            details.append(f"{item.rule_id} shadowed_by [{shadows}]")
        detail_text = "; ".join(details)
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.shadowed_prohibition",
                family=VacuityFamily.POLICY,
                kind=VacuityKind.SHADOWED_PROHIBITION,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=(
                    f"prohibition rules are present but dominated by earlier "
                    f"matching rules: {detail_text}"
                ),
                not_proven=(
                    f"shadowed prohibitions never deny matching requests; "
                    f"enforcement not proven: {detail_text}; claimed: {claim}"
                ),
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
                notes="shadowed denials are dead policy text",
                metadata={
                    "shadowed_prohibition_ids": sorted(
                        item.rule_id for item in shadowed_prohibitions
                    ),
                    "shadow_map": {
                        item.rule_id: list(item.shadowed_by_rule_ids)
                        for item in shadowed_prohibitions
                    },
                },
            )
        )

    # --- impossible obligations ---
    impossible_obligations = [
        item
        for item in rules
        if item.effect == PolicyEffect.OBLIGE.value
        and not item.obligation_satisfiable
    ]
    if impossible_obligations:
        obl_ids = ", ".join(
            sorted(item.rule_id for item in impossible_obligations)
        )
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.impossible_obligation",
                family=VacuityFamily.POLICY,
                kind=VacuityKind.IMPOSSIBLE_OBLIGATION,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=(
                    f"obligation rules are declared but cannot be satisfied: "
                    f"{obl_ids}"
                ),
                not_proven=(
                    f"impossible obligations never produce compliant outcomes; "
                    f"property not proven: {obl_ids}; claimed: {claim}"
                ),
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
                notes="unsatisfiable obligations are vacuous policy constraints",
                metadata={
                    "impossible_obligation_ids": sorted(
                        item.rule_id for item in impossible_obligations
                    )
                },
            )
        )

    # --- dominating default ---
    if sealed_subject.default_dominates_specific_rules:
        default = sealed_subject.default_action or PolicyDefaultAction.UNDEFINED.value
        specific_ids = sorted(
            item.rule_id for item in rules if not item.is_default
        )
        specific_list = ", ".join(specific_ids) if specific_ids else "(none)"
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.dominating_default",
                family=VacuityFamily.POLICY,
                kind=VacuityKind.DOMINATING_DEFAULT,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=(
                    f"default action {default!r} dominates evaluation over "
                    f"specific rules: {specific_list}"
                ),
                not_proven=(
                    f"specific policy rules never control decisions under a "
                    f"dominating default ({default}); property not proven by "
                    f"those rules: {specific_list}; claimed: {claim}"
                ),
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
                notes="dominating defaults render specific rules residual text",
                metadata={
                    "default_action": default,
                    "dominated_rule_ids": specific_ids,
                },
            )
        )

    # --- obsolete interface references ---
    obsolete_from_rules = sorted(
        {
            item.interface_reference_id
            for item in rules
            if item.interface_obsolete and item.interface_reference_id is not None
        }
    )
    obsolete = sorted(
        set(sealed_subject.obsolete_interface_reference_ids)
        | set(obsolete_from_rules)
    )
    if obsolete:
        obsolete_list = ", ".join(obsolete)
        live_list = (
            ", ".join(sealed_subject.live_interface_reference_ids) or "(none)"
        )
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.obsolete_interface_reference",
                family=VacuityFamily.POLICY,
                kind=VacuityKind.OBSOLETE_INTERFACE_REFERENCE,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=(
                    f"policy references obsolete interfaces: {obsolete_list}; "
                    f"live interfaces: {live_list}"
                ),
                not_proven=(
                    f"constraints on obsolete interfaces do not bind current "
                    f"call paths: {obsolete_list}; claimed: {claim}"
                ),
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
                notes="obsolete interface refs never constrain live APIs",
                metadata={
                    "obsolete_interface_reference_ids": obsolete,
                    "live_interface_reference_ids": list(
                        sealed_subject.live_interface_reference_ids
                    ),
                },
            )
        )

    findings_sorted = tuple(
        sorted(findings, key=lambda item: (item.vacuity_kind, item.finding_id))
    )
    residuals = tuple(sorted({item.what_remains_proven for item in findings_sorted}))
    nonclaims = _merge_nonclaims(findings_sorted, declared)
    result_metadata = dict(metadata or {})
    result_metadata.setdefault(
        "subject_observation_cid", sealed_subject.subject_observation_cid
    )
    if declared:
        result_metadata["declared_nonclaims"] = list(declared)
    return VacuityAnalysisResult(
        interface_id=ANALYZE_POLICY_VACUITY_INTERFACE,
        vacuity_family=VacuityFamily.POLICY,
        subject_id=sealed_subject.subject_id,
        subject_observation_cid=sealed_subject.subject_observation_cid,
        findings=findings_sorted,
        finding_cids=tuple(sorted(item.finding_cid for item in findings_sorted)),
        residual_properties=residuals,
        precise_nonclaims=nonclaims,
        notes=_optional_text(notes, "notes") if notes is not None else None,
        metadata=result_metadata,
    )


def verify_vacuity_analysis_result_identity(
    result: VacuityAnalysisResult | Mapping[str, Any],
) -> str:
    """Recompute and return the result CID; raise on forged input."""

    if isinstance(result, VacuityAnalysisResult):
        sealed = result
    elif isinstance(result, Mapping):
        sealed = VacuityAnalysisResult.from_dict(result)
    else:
        raise VacuityFormalPolicyError(
            "result must be VacuityAnalysisResult or mapping"
        )
    for finding in sealed.findings:
        verify_vacuity_finding_identity(finding)
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.result_cid:
        raise VacuityFormalPolicyError(
            "result_cid identity mismatch with recomputed identity"
        )
    return recomputed


def policy_default_actions() -> tuple[str, ...]:
    """Return the closed policy default-action vocabulary."""

    return tuple(item.value for item in PolicyDefaultAction)


def policy_effects() -> tuple[str, ...]:
    """Return the closed policy-effect vocabulary."""

    return tuple(item.value for item in PolicyEffect)


__all__ = [
    "ANALYZE_FORMAL_VACUITY_INTERFACE",
    "ANALYZE_POLICY_VACUITY_INTERFACE",
    "FORMAL_VACUITY_SUBJECT_SCHEMA",
    "GENERATOR_ID",
    "GENERATOR_VERSION",
    "POLICY_VACUITY_SUBJECT_SCHEMA",
    "VACUITY_ANALYSIS_RESULT_INTERFACE",
    "VACUITY_ANALYSIS_RESULT_SCHEMA",
    "FormalProofVacuitySubject",
    "PolicyDefaultAction",
    "PolicyEffect",
    "PolicyRuleObservation",
    "PolicyVacuitySubject",
    "VacuityAnalysisResult",
    "VacuityFormalPolicyError",
    "analyze_formal_vacuity",
    "analyze_policy_vacuity",
    "policy_default_actions",
    "policy_effects",
    "verify_vacuity_analysis_result_identity",
]
