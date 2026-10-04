"""Deterministic Solidity structural projection for Security IR GraphRAG.

Source code is untrusted, inert data.  This module never executes, compiles, or
interprets Solidity as instructions.  It projects verified source-row metadata
and bounded parser facts into content-addressed :class:`CodeUnit` records and
typed structural facts whose authority classes remain distinct:

* ``observed_syntax`` — deterministic parser observations
* ``inferred_candidate`` — heuristic candidate security concepts
* ``reviewed_claim`` / ``verified_result`` — accepted only when supplied by a
  separate reviewed stage (never invented here)

Source bodies remain out of public graph records; only digests, CIDs, spans, and
bounded excerpts are retained.  Corpus quality scores never become security
labels.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import re
from typing import Any, Final

from ...ir_core.identity import CanonicalIdentity, canonical_identity
from ....processors.smart_contracts.solidity.models import (
    ContractKind,
    ParseStatus,
    SolidityParseResult,
    SolidityTypeDefinition,
)
from ....processors.smart_contracts.solidity.parser import parse_solidity
from .release_policy import SOLIDITY_CPT_DATASET_ID, SOLIDITY_CPT_REVISION
from .schemas import CodeUnit, canonical_config_cid
from .source_snapshot import (
    AdaptedSolidityCPTRow,
    SolidityCPTRow,
    SolidityCPTSourceBody,
)
from .vocabulary import SolidityAuthorityType, require_authority_type


PROJECTOR_SCHEMA_VERSION: Final = "solidity-cpt-semantic-projector/v1"
PROJECTOR_CONFIG_SCHEMA_VERSION: Final = "solidity-cpt-semantic-projector-config/v1"
_IR_CORE_CID_HEADER: Final = b"\x01\x55\x12\x20"
_LANGUAGE: Final = "solidity"


class ProjectionError(ValueError):
    """Raised for malformed projector configuration or caller-supplied facts."""


def _validate_cid(value: str, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"b[a-z2-7]{58}", value):
        raise ProjectionError(f"{label} must be an ir_core raw/sha2-256 CIDv1")
    try:
        encoded = value[1:].upper()
        raw = base64.b32decode(encoded + ("=" * ((-len(encoded)) % 8)))
    except (ValueError, base64.binascii.Error) as exc:
        raise ProjectionError(
            f"{label} must be an ir_core raw/sha2-256 CIDv1"
        ) from exc
    if len(raw) != 36 or not raw.startswith(_IR_CORE_CID_HEADER):
        raise ProjectionError(f"{label} must be an ir_core raw/sha2-256 CIDv1")
    return value


class UnitKind(str, Enum):
    SOURCE_UNIT = "source_unit"
    CONTRACT = "contract"
    LIBRARY = "library"
    INTERFACE = "interface"
    FUNCTION = "function"
    MODIFIER = "modifier"
    VARIABLE = "variable"
    EVENT = "event"
    ERROR = "error"
    CALL_SITE = "call_site"
    STATE_ACCESS = "state_access"
    EFFECT = "effect"
    AUTH_GUARD = "auth_guard"
    ASSEMBLY = "assembly"


class FactKind(str, Enum):
    STRUCTURAL = "structural"
    CONTROL = "control"
    STATE = "state"
    EFFECT = "effect"
    SECURITY_CONCEPT = "security_concept"
    ASSUMPTION = "assumption"
    MITIGATION = "mitigation"
    PROOF_OBLIGATION = "proof_obligation"
    PROVENANCE = "provenance"
    LICENSE = "license"
    COMPILER = "compiler"


class ExtractionMethod(str, Enum):
    DETERMINISTIC_SYNTAX = "deterministic_syntax"
    HEURISTIC_INFERENCE = "heuristic_inference"
    REVIEWED_SUPPLIED = "reviewed_supplied"
    VERIFIED_SUPPLIED = "verified_supplied"


class DiagnosticCode(str, Enum):
    PARSE_FAILED = "parse.failed"
    PARSE_PARTIAL = "parse.partial"
    PARSE_UNSUPPORTED = "parse.unsupported"
    LIMIT_EXCEEDED = "projection.limit_exceeded"
    NO_DECLARATIONS = "projection.no_declarations"
    BODY_DIGEST_MISMATCH = "source.body_digest_mismatch"
    QUALITY_NOT_SECURITY = "quality.not_security_label"


@dataclass(frozen=True, slots=True)
class ProjectorConfig:
    """Resource bounds and public-output limits included in every identity."""

    max_code_units: int = 16_384
    max_structural_facts: int = 65_536
    max_excerpt_chars: int = 256
    max_predicate_chars: int = 2_048
    emit_inferred_candidates: bool = True
    schema_version: str = PROJECTOR_CONFIG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "max_code_units",
            "max_structural_facts",
            "max_excerpt_chars",
            "max_predicate_chars",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ProjectionError(f"{name} must be a positive integer")
        if self.schema_version != PROJECTOR_CONFIG_SCHEMA_VERSION:
            raise ProjectionError(
                f"unsupported projector config schema {self.schema_version!r}"
            )
        if type(self.emit_inferred_candidates) is not bool:
            raise ProjectionError("emit_inferred_candidates must be a bool")

    def to_dict(self) -> dict[str, Any]:
        return {
            "emit_inferred_candidates": self.emit_inferred_candidates,
            "max_code_units": self.max_code_units,
            "max_excerpt_chars": self.max_excerpt_chars,
            "max_predicate_chars": self.max_predicate_chars,
            "max_structural_facts": self.max_structural_facts,
            "schema_version": self.schema_version,
        }

    @property
    def cid(self) -> str:
        return canonical_config_cid(
            self.to_dict(), schema_version=self.schema_version
        )


@dataclass(frozen=True, slots=True)
class ProjectionDiagnostic:
    """A retained reason why source evidence was incomplete or ambiguous."""

    code: DiagnosticCode
    message: str
    path: str = ""
    unit_kind: str = ""
    unit_index: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, DiagnosticCode):
            raise ProjectionError("diagnostic code must be DiagnosticCode")
        if not isinstance(self.message, str) or not self.message:
            raise ProjectionError("diagnostic message must be non-empty")
        if self.unit_index is not None and (
            type(self.unit_index) is not int or self.unit_index < 0
        ):
            raise ProjectionError("diagnostic unit_index must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "path": self.path,
            "unit_index": self.unit_index,
            "unit_kind": self.unit_kind,
        }


@dataclass(frozen=True, slots=True)
class SuppliedEvidenceFact:
    """Reviewed or verified evidence supplied by a later stage.

    The projector binds these facts to existing code units; it never invents
    ``reviewed_claim`` or ``verified_result`` authority on its own.
    """

    kind: FactKind
    predicate: str
    authority_type: SolidityAuthorityType
    code_unit_cid: str
    confidence: float = 1.0
    model_id: str = ""
    model_revision: str = ""
    review_id: str = ""
    verification_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, FactKind):
            raise ProjectionError("supplied fact kind must be FactKind")
        object.__setattr__(
            self,
            "authority_type",
            require_authority_type(self.authority_type),
        )
        if self.authority_type not in {
            SolidityAuthorityType.REVIEWED_CLAIM,
            SolidityAuthorityType.VERIFIED_RESULT,
        }:
            raise ProjectionError(
                "supplied facts must use reviewed_claim or verified_result"
            )
        for name in ("predicate", "code_unit_cid"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or "\x00" in value
            ):
                raise ProjectionError(f"supplied fact {name} is invalid")
        _validate_cid(self.code_unit_cid, "supplied fact code_unit_cid")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0.0 <= float(self.confidence) <= 1.0
        ):
            raise ProjectionError(
                "supplied fact confidence must be between zero and one"
            )
        if (
            self.authority_type is SolidityAuthorityType.REVIEWED_CLAIM
            and not self.review_id
        ):
            raise ProjectionError("reviewed_claim requires review_id")
        if (
            self.authority_type is SolidityAuthorityType.VERIFIED_RESULT
            and not self.verification_id
        ):
            raise ProjectionError("verified_result requires verification_id")


@dataclass(frozen=True, slots=True)
class StructuralFact:
    """A non-authoritative structural or candidate fact bound to code evidence.

    The ``authority_type`` field is distinct from derived-record ``authority``
    (always non_authoritative on these facts) and from quality scores.
    """

    kind: FactKind
    predicate: str
    authority_type: SolidityAuthorityType
    extraction_method: ExtractionMethod
    code_unit_cid: str
    source_cid: str
    config_cid: str
    confidence: float = 1.0
    model_id: str = ""
    model_revision: str = ""
    review_id: str = ""
    verification_id: str = ""
    fact_id: str = ""
    schema_version: str = PROJECTOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.kind, FactKind):
            raise ProjectionError("fact kind must be FactKind")
        object.__setattr__(
            self,
            "authority_type",
            require_authority_type(self.authority_type),
        )
        if not isinstance(self.extraction_method, ExtractionMethod):
            raise ProjectionError("extraction method is invalid")
        for name in ("predicate", "code_unit_cid", "source_cid", "config_cid"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or "\x00" in value
            ):
                raise ProjectionError(f"structural {name} is invalid")
        for name in ("code_unit_cid", "source_cid", "config_cid"):
            _validate_cid(getattr(self, name), f"structural {name}")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0.0 <= float(self.confidence) <= 1.0
        ):
            raise ProjectionError("confidence must be between zero and one")
        object.__setattr__(self, "confidence", float(self.confidence))
        if self.schema_version != PROJECTOR_SCHEMA_VERSION:
            raise ProjectionError(
                f"unsupported structural fact schema {self.schema_version!r}"
            )
        if self.extraction_method is ExtractionMethod.DETERMINISTIC_SYNTAX:
            if self.authority_type is not SolidityAuthorityType.OBSERVED_SYNTAX:
                raise ProjectionError(
                    "deterministic syntax must use observed_syntax authority"
                )
            if self.confidence != 1.0 or self.model_id or self.model_revision:
                raise ProjectionError(
                    "deterministic facts cannot carry model identity or "
                    "reduced confidence"
                )
        elif self.extraction_method is ExtractionMethod.HEURISTIC_INFERENCE:
            if self.authority_type is not SolidityAuthorityType.INFERRED_CANDIDATE:
                raise ProjectionError(
                    "heuristic inference must use inferred_candidate authority"
                )
        elif self.extraction_method is ExtractionMethod.REVIEWED_SUPPLIED:
            if self.authority_type is not SolidityAuthorityType.REVIEWED_CLAIM:
                raise ProjectionError(
                    "reviewed supply must use reviewed_claim authority"
                )
            if not self.review_id:
                raise ProjectionError("reviewed facts require review_id")
        elif self.extraction_method is ExtractionMethod.VERIFIED_SUPPLIED:
            if self.authority_type is not SolidityAuthorityType.VERIFIED_RESULT:
                raise ProjectionError(
                    "verified supply must use verified_result authority"
                )
            if not self.verification_id:
                raise ProjectionError("verified facts require verification_id")
        computed = self.identity.cid
        if self.fact_id and self.fact_id != computed:
            raise ProjectionError("structural fact_id does not match content")
        object.__setattr__(self, "fact_id", computed)

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "authority": "non_authoritative",
            "authority_type": self.authority_type.value,
            "code_unit_cid": self.code_unit_cid,
            "confidence": self.confidence,
            "config_cid": self.config_cid,
            "extraction_method": self.extraction_method.value,
            "grants_execution_authority": False,
            "kind": self.kind.value,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "predicate": self.predicate,
            "review_id": self.review_id,
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "verification_id": self.verification_id,
        }

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.deterministic_dict(),
            domain="solidity-cpt-security-ir/structural-fact",
            schema_version=self.schema_version,
        )

    @property
    def cid(self) -> str:
        return self.fact_id

    def to_dict(self) -> dict[str, Any]:
        return {"fact_id": self.fact_id, **self.deterministic_dict()}


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    """Complete deterministic projection, including diagnostics."""

    source_cid: str
    config_cid: str
    language: str
    path: str
    parse_status: str
    code_units: tuple[CodeUnit, ...]
    structural_facts: tuple[StructuralFact, ...]
    diagnostics: tuple[ProjectionDiagnostic, ...]
    quality_score: float | None = None
    quality_is_security_label: bool = False
    projection_id: str = ""
    schema_version: str = PROJECTOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.source_cid or not self.config_cid:
            raise ProjectionError(
                "projection source_cid and config_cid are required"
            )
        _validate_cid(self.source_cid, "projection source_cid")
        _validate_cid(self.config_cid, "projection config_cid")
        if self.schema_version != PROJECTOR_SCHEMA_VERSION:
            raise ProjectionError(
                f"unsupported projection schema {self.schema_version!r}"
            )
        if self.language != _LANGUAGE:
            raise ProjectionError("projection language must be solidity")
        if not isinstance(self.path, str) or not self.path:
            raise ProjectionError("projection path must be non-empty")
        if self.quality_is_security_label is not False:
            raise ProjectionError(
                "corpus quality must never become a security label"
            )
        if self.quality_score is not None and (
            isinstance(self.quality_score, bool)
            or not isinstance(self.quality_score, (int, float))
            or not 0.0 <= float(self.quality_score) <= 1.0
        ):
            raise ProjectionError(
                "quality_score must be between zero and one when present"
            )
        if self.quality_score is not None:
            object.__setattr__(self, "quality_score", float(self.quality_score))
        units = tuple(sorted(self.code_units, key=lambda item: item.cid))
        facts = tuple(sorted(self.structural_facts, key=lambda item: item.cid))
        diagnostics = tuple(
            sorted(
                self.diagnostics,
                key=lambda item: (
                    item.code.value,
                    item.path,
                    item.unit_kind,
                    -1 if item.unit_index is None else item.unit_index,
                    item.message,
                ),
            )
        )
        if len({item.cid for item in units}) != len(units):
            raise ProjectionError("projection contains duplicate code units")
        if len({item.cid for item in facts}) != len(facts):
            raise ProjectionError("projection contains duplicate structural facts")
        unit_ids = {item.cid for item in units}
        if any(item.code_unit_cid not in unit_ids for item in facts):
            raise ProjectionError(
                "structural fact references a code unit outside the result"
            )
        object.__setattr__(self, "code_units", units)
        object.__setattr__(self, "structural_facts", facts)
        object.__setattr__(self, "diagnostics", diagnostics)
        computed = self.identity.cid
        if self.projection_id and self.projection_id != computed:
            raise ProjectionError("projection_id does not match content")
        object.__setattr__(self, "projection_id", computed)

    @property
    def supported(self) -> bool:
        return not any(
            item.code
            in {
                DiagnosticCode.PARSE_FAILED,
                DiagnosticCode.PARSE_UNSUPPORTED,
            }
            for item in self.diagnostics
        )

    def facts_by_authority(
        self, authority: SolidityAuthorityType | str
    ) -> tuple[StructuralFact, ...]:
        authority = require_authority_type(authority)
        return tuple(
            item
            for item in self.structural_facts
            if item.authority_type is authority
        )

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "code_units": [item.to_dict() for item in self.code_units],
            "config_cid": self.config_cid,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "language": self.language,
            "parse_status": self.parse_status,
            "path": self.path,
            "quality_is_security_label": False,
            "quality_score": self.quality_score,
            "schema_version": self.schema_version,
            "source_cid": self.source_cid,
            "structural_facts": [
                item.to_dict() for item in self.structural_facts
            ],
        }

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.deterministic_dict(),
            domain="solidity-cpt-security-ir/projection",
            schema_version=self.schema_version,
        )

    @property
    def cid(self) -> str:
        return self.projection_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "projection_id": self.projection_id,
            **self.deterministic_dict(),
        }


def canonical_source_row_cid(row: SolidityCPTRow) -> str:
    """Return the pinned-row identity used as the projection source CID."""

    if not isinstance(row, SolidityCPTRow):
        raise TypeError("row must be SolidityCPTRow")
    return row.row_id


def _bounded_text(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    suffix = f":sha256:{digest}"
    if maximum <= len(suffix):
        return suffix[-maximum:]
    return value[: maximum - len(suffix)] + suffix


def _contract_unit_kind(kind: ContractKind) -> UnitKind:
    if kind is ContractKind.LIBRARY:
        return UnitKind.LIBRARY
    if kind is ContractKind.INTERFACE:
        return UnitKind.INTERFACE
    return UnitKind.CONTRACT


def _span_dict(span: Any) -> dict[str, int]:
    if span is None:
        return {}
    return span.to_dict() if hasattr(span, "to_dict") else {}


_INFERRED_HINTS: Final = (
    (
        re.compile(r"\bonlyOwner\b|\bonlyRole\b|\bhasRole\b", re.I),
        "access_control",
        FactKind.SECURITY_CONCEPT,
    ),
    (
        re.compile(r"\bnonReentrant\b|\breentrancy\b", re.I),
        "reentrancy",
        FactKind.SECURITY_CONCEPT,
    ),
    (
        re.compile(r"\btx\.origin\b"),
        "tx_origin",
        FactKind.SECURITY_CONCEPT,
    ),
    (
        re.compile(r"\bdelegatecall\b", re.I),
        "delegatecall_injection",
        FactKind.SECURITY_CONCEPT,
    ),
    (
        re.compile(r"\bselfdestruct\b|\bsuicide\b", re.I),
        "unchecked_call",
        FactKind.SECURITY_CONCEPT,
    ),
)


@dataclass(slots=True)
class _ProjectionBuilder:
    row: SolidityCPTRow
    source_cid: str
    config: ProjectorConfig
    config_cid: str
    path: str
    units: list[CodeUnit] = field(default_factory=list)
    facts: list[StructuralFact] = field(default_factory=list)
    diagnostics: list[ProjectionDiagnostic] = field(default_factory=list)

    def bounded_predicate(self, value: str) -> str:
        if len(value) <= self.config.max_predicate_chars:
            return value
        message = (
            "predicate exceeded max_predicate_chars; retained a bounded "
            "prefix and full-content digest"
        )
        if not any(
            item.code is DiagnosticCode.LIMIT_EXCEEDED
            and item.message == message
            for item in self.diagnostics
        ):
            self.diagnostics.append(
                ProjectionDiagnostic(DiagnosticCode.LIMIT_EXCEEDED, message)
            )
        return _bounded_text(value, self.config.max_predicate_chars)

    def add_unit(
        self,
        *,
        unit_kind: UnitKind,
        path: str,
        payload: Mapping[str, Any],
        parent_cids: Sequence[str],
    ) -> CodeUnit:
        if len(self.units) >= self.config.max_code_units:
            self.diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.LIMIT_EXCEEDED,
                    f"code unit budget {self.config.max_code_units} exceeded",
                    path=path,
                    unit_kind=unit_kind.value,
                    unit_index=len(self.units),
                )
            )
            # Still fail closed by raising so identities stay consistent.
            raise ProjectionError(
                f"code unit budget {self.config.max_code_units} exceeded"
            )
        clean = dict(payload)
        clean["grants_execution_authority"] = False
        clean["authority_type"] = SolidityAuthorityType.OBSERVED_SYNTAX.value
        unit = CodeUnit(
            source_cids=(self.source_cid,),
            parent_cids=tuple(parent_cids),
            config_cid=self.config_cid,
            unit_kind=unit_kind.value,
            language=_LANGUAGE,
            path=path,
            payload=clean,
        )
        self.units.append(unit)
        return unit

    def add_fact(
        self,
        *,
        kind: FactKind,
        predicate: str,
        authority_type: SolidityAuthorityType,
        extraction_method: ExtractionMethod,
        code_unit_cid: str,
        confidence: float = 1.0,
        model_id: str = "",
        model_revision: str = "",
        review_id: str = "",
        verification_id: str = "",
    ) -> StructuralFact | None:
        if len(self.facts) >= self.config.max_structural_facts:
            self.diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.LIMIT_EXCEEDED,
                    f"structural fact budget "
                    f"{self.config.max_structural_facts} exceeded",
                )
            )
            raise ProjectionError(
                f"structural fact budget {self.config.max_structural_facts} "
                "exceeded"
            )
        fact = StructuralFact(
            kind=kind,
            predicate=self.bounded_predicate(predicate),
            authority_type=authority_type,
            extraction_method=extraction_method,
            code_unit_cid=code_unit_cid,
            source_cid=self.source_cid,
            config_cid=self.config_cid,
            confidence=confidence,
            model_id=model_id,
            model_revision=model_revision,
            review_id=review_id,
            verification_id=verification_id,
        )
        self.facts.append(fact)
        return fact

    def project_type(
        self,
        type_def: SolidityTypeDefinition,
        *,
        source_unit_cid: str,
        type_index: int,
    ) -> CodeUnit:
        unit_kind = _contract_unit_kind(type_def.kind)
        type_unit = self.add_unit(
            unit_kind=unit_kind,
            path=self.path,
            parent_cids=(source_unit_cid, self.source_cid),
            payload={
                "contract_kind": type_def.kind.value,
                "name": type_def.name,
                "span": _span_dict(type_def.span),
                "type_index": type_index,
            },
        )
        self.add_fact(
            kind=FactKind.STRUCTURAL,
            predicate=f"declares:{unit_kind.value}:{type_def.name}",
            authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
            extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
            code_unit_cid=type_unit.cid,
        )
        for base in type_def.inheritance:
            self.add_fact(
                kind=FactKind.STRUCTURAL,
                predicate=f"inherits:{base.name}",
                authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
                extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
                code_unit_cid=type_unit.cid,
            )
        for index, function in enumerate(type_def.functions):
            fn_unit = self.add_unit(
                unit_kind=UnitKind.FUNCTION,
                path=self.path,
                parent_cids=(type_unit.cid, self.source_cid),
                payload={
                    "enclosing": type_def.name,
                    "function_kind": function.kind,
                    "modifiers": list(function.modifiers),
                    "name": function.name,
                    "span": _span_dict(function.span),
                    "state_mutability": function.state_mutability.value,
                    "unit_index": index,
                    "visibility": function.visibility.value,
                },
            )
            self.add_fact(
                kind=FactKind.STRUCTURAL,
                predicate=f"declares:function:{type_def.name}.{function.name}",
                authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
                extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
                code_unit_cid=fn_unit.cid,
            )
            for modifier_name in function.modifiers:
                self.add_fact(
                    kind=FactKind.CONTROL,
                    predicate=f"guards:{modifier_name}",
                    authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
                    extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
                    code_unit_cid=fn_unit.cid,
                )
        for index, modifier in enumerate(type_def.modifiers):
            mod_unit = self.add_unit(
                unit_kind=UnitKind.MODIFIER,
                path=self.path,
                parent_cids=(type_unit.cid, self.source_cid),
                payload={
                    "enclosing": type_def.name,
                    "name": modifier.name,
                    "span": _span_dict(modifier.span),
                    "unit_index": index,
                },
            )
            self.add_fact(
                kind=FactKind.STRUCTURAL,
                predicate=f"declares:modifier:{type_def.name}.{modifier.name}",
                authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
                extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
                code_unit_cid=mod_unit.cid,
            )
        for index, variable in enumerate(type_def.state_variables):
            var_unit = self.add_unit(
                unit_kind=UnitKind.VARIABLE,
                path=self.path,
                parent_cids=(type_unit.cid, self.source_cid),
                payload={
                    "enclosing": type_def.name,
                    "name": variable.name,
                    "span": _span_dict(variable.span),
                    "type_name": variable.type_name,
                    "unit_index": index,
                    "visibility": variable.visibility.value,
                },
            )
            self.add_fact(
                kind=FactKind.STATE,
                predicate=f"declares:variable:{type_def.name}.{variable.name}",
                authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
                extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
                code_unit_cid=var_unit.cid,
            )
        for index, event in enumerate(type_def.events):
            event_unit = self.add_unit(
                unit_kind=UnitKind.EVENT,
                path=self.path,
                parent_cids=(type_unit.cid, self.source_cid),
                payload={
                    "enclosing": type_def.name,
                    "name": event.name,
                    "span": _span_dict(event.span),
                    "unit_index": index,
                },
            )
            self.add_fact(
                kind=FactKind.STRUCTURAL,
                predicate=f"declares:event:{type_def.name}.{event.name}",
                authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
                extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
                code_unit_cid=event_unit.cid,
            )
        for index, error in enumerate(type_def.errors):
            error_unit = self.add_unit(
                unit_kind=UnitKind.ERROR,
                path=self.path,
                parent_cids=(type_unit.cid, self.source_cid),
                payload={
                    "enclosing": type_def.name,
                    "name": error.name,
                    "span": _span_dict(error.span),
                    "unit_index": index,
                },
            )
            self.add_fact(
                kind=FactKind.STRUCTURAL,
                predicate=f"declares:error:{type_def.name}.{error.name}",
                authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
                extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
                code_unit_cid=error_unit.cid,
            )
        for index, call in enumerate(type_def.calls):
            call_unit = self.add_unit(
                unit_kind=UnitKind.CALL_SITE,
                path=self.path,
                parent_cids=(type_unit.cid, self.source_cid),
                payload={
                    "callee": call.callee,
                    "call_kind": call.kind.value,
                    "enclosing": call.enclosing or type_def.name,
                    "span": _span_dict(call.span),
                    "unit_index": index,
                },
            )
            self.add_fact(
                kind=FactKind.STRUCTURAL,
                predicate=f"calls:{call.kind.value}:{call.callee}",
                authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
                extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
                code_unit_cid=call_unit.cid,
            )
        for index, access in enumerate(type_def.storage_accesses):
            access_unit = self.add_unit(
                unit_kind=UnitKind.STATE_ACCESS,
                path=self.path,
                parent_cids=(type_unit.cid, self.source_cid),
                payload={
                    "access_kind": access.kind.value,
                    "enclosing": access.enclosing or type_def.name,
                    "span": _span_dict(access.span),
                    "target": access.target,
                    "unit_index": index,
                },
            )
            self.add_fact(
                kind=FactKind.STATE,
                predicate=f"{access.kind.value}:{access.target}",
                authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
                extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
                code_unit_cid=access_unit.cid,
            )
        for index, guard in enumerate(type_def.auth_guards):
            guard_unit = self.add_unit(
                unit_kind=UnitKind.AUTH_GUARD,
                path=self.path,
                parent_cids=(type_unit.cid, self.source_cid),
                payload={
                    "enclosing": guard.enclosing or type_def.name,
                    "expression": _bounded_text(
                        guard.expression, self.config.max_excerpt_chars
                    ),
                    "guard_kind": guard.kind.value,
                    "span": _span_dict(guard.span),
                    "unit_index": index,
                },
            )
            self.add_fact(
                kind=FactKind.CONTROL,
                predicate=f"guards:{guard.kind.value}:{guard.expression}",
                authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
                extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
                code_unit_cid=guard_unit.cid,
            )
        for index, effect in enumerate(type_def.value_effects):
            effect_unit = self.add_unit(
                unit_kind=UnitKind.EFFECT,
                path=self.path,
                parent_cids=(type_unit.cid, self.source_cid),
                payload={
                    "effect_kind": effect.kind.value,
                    "enclosing": effect.enclosing or type_def.name,
                    "expression": _bounded_text(
                        effect.expression, self.config.max_excerpt_chars
                    ),
                    "span": _span_dict(effect.span),
                    "unit_index": index,
                },
            )
            self.add_fact(
                kind=FactKind.EFFECT,
                predicate=f"may_effect:{effect.kind.value}",
                authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
                extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
                code_unit_cid=effect_unit.cid,
            )
        for index, assembly in enumerate(type_def.assembly_blocks):
            asm_unit = self.add_unit(
                unit_kind=UnitKind.ASSEMBLY,
                path=self.path,
                parent_cids=(type_unit.cid, self.source_cid),
                payload={
                    "dialect": assembly.dialect,
                    "enclosing": assembly.enclosing or type_def.name,
                    "span": _span_dict(assembly.span),
                    "unit_index": index,
                },
            )
            self.add_fact(
                kind=FactKind.STRUCTURAL,
                predicate=f"assembly:{assembly.dialect}",
                authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
                extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
                code_unit_cid=asm_unit.cid,
            )
        return type_unit


class SolidityGraphProjector:
    """Project verified Solidity CPT rows into typed structural graph inputs."""

    def __init__(self, config: ProjectorConfig = ProjectorConfig()) -> None:
        if not isinstance(config, ProjectorConfig):
            raise TypeError("config must be ProjectorConfig")
        self.config = config
        self.config_cid = config.cid

    def project(
        self,
        row: SolidityCPTRow,
        source_body: str | SolidityCPTSourceBody,
        *,
        parse_result: SolidityParseResult | None = None,
        supplied_facts: Sequence[SuppliedEvidenceFact] = (),
        quality_score: float | None = None,
    ) -> ProjectionResult:
        if not isinstance(row, SolidityCPTRow):
            raise TypeError("row must be SolidityCPTRow")
        if isinstance(source_body, SolidityCPTSourceBody):
            text = source_body.text
            body_sha256 = source_body.sha256
            body_cid = source_body.content_cid
        elif isinstance(source_body, str):
            text = source_body
            body_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
            body_cid = ""
        else:
            raise TypeError("source_body must be str or SolidityCPTSourceBody")
        if body_sha256 != row.source_body_sha256:
            raise ProjectionError(
                "source body digest does not match row.source_body_sha256"
            )
        if isinstance(supplied_facts, (str, bytes, bytearray)) or not isinstance(
            supplied_facts, Sequence
        ):
            raise TypeError("supplied_facts must be a sequence")
        if not all(
            isinstance(item, SuppliedEvidenceFact) for item in supplied_facts
        ):
            raise TypeError(
                "every supplied fact must be SuppliedEvidenceFact"
            )

        source_cid = canonical_source_row_cid(row)
        builder = _ProjectionBuilder(
            row=row,
            source_cid=source_cid,
            config=self.config,
            config_cid=self.config_cid,
            path=row.path or f"row-{row.row_index}.sol",
        )
        if body_cid and body_cid != row.source_body_cid:
            builder.diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.BODY_DIGEST_MISMATCH,
                    "source body CID does not match row.source_body_cid",
                    path=builder.path,
                )
            )

        if parse_result is None:
            parse_result = parse_solidity(text, path=builder.path)
        if not isinstance(parse_result, SolidityParseResult):
            raise TypeError("parse_result must be SolidityParseResult")

        parse_status = parse_result.status.value
        if parse_result.status is ParseStatus.FAILED:
            builder.diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.PARSE_FAILED,
                    "parser returned failed status",
                    path=builder.path,
                )
            )
        elif parse_result.status is ParseStatus.UNSUPPORTED:
            builder.diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.PARSE_UNSUPPORTED,
                    "parser returned unsupported status",
                    path=builder.path,
                )
            )
        elif parse_result.status is ParseStatus.PARTIAL or parse_result.partial:
            builder.diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.PARSE_PARTIAL,
                    "parser returned partial coverage",
                    path=builder.path,
                )
            )

        # Provenance / license / compiler facts (observed evidence claims).
        source_unit = builder.add_unit(
            unit_kind=UnitKind.SOURCE_UNIT,
            path=builder.path,
            parent_cids=(source_cid,),
            payload={
                "n_chars": row.n_chars,
                "parse_status": parse_status,
                "row_index": row.row_index,
                "source_body_cid": row.source_body_cid,
                "source_body_sha256": row.source_body_sha256,
                "source_provider": row.source,
            },
        )
        builder.add_fact(
            kind=FactKind.PROVENANCE,
            predicate=f"derived_from:row:{row.row_index}",
            authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
            extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
            code_unit_cid=source_unit.cid,
        )
        builder.add_fact(
            kind=FactKind.LICENSE,
            predicate=f"has_license:{row.license or 'absent'}",
            authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
            extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
            code_unit_cid=source_unit.cid,
        )
        builder.add_fact(
            kind=FactKind.COMPILER,
            predicate=f"has_compiler:{row.compiler or 'absent'}",
            authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
            extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
            code_unit_cid=source_unit.cid,
        )
        if row.address:
            builder.add_fact(
                kind=FactKind.PROVENANCE,
                predicate=f"address_hint:{row.address}",
                authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
                extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
                code_unit_cid=source_unit.cid,
            )

        unit = parse_result.source_unit
        if unit is not None:
            for imp in unit.imports:
                builder.add_fact(
                    kind=FactKind.STRUCTURAL,
                    predicate=f"imports:{imp.path}",
                    authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
                    extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
                    code_unit_cid=source_unit.cid,
                )
            for pragma in unit.pragmas:
                builder.add_fact(
                    kind=FactKind.COMPILER,
                    predicate=f"pragma:{pragma.name}:{pragma.value}",
                    authority_type=SolidityAuthorityType.OBSERVED_SYNTAX,
                    extraction_method=ExtractionMethod.DETERMINISTIC_SYNTAX,
                    code_unit_cid=source_unit.cid,
                )
            if not unit.type_definitions:
                builder.diagnostics.append(
                    ProjectionDiagnostic(
                        DiagnosticCode.NO_DECLARATIONS,
                        "no contract/library/interface declarations observed",
                        path=builder.path,
                    )
                )
            for type_index, type_def in enumerate(unit.type_definitions):
                builder.project_type(
                    type_def,
                    source_unit_cid=source_unit.cid,
                    type_index=type_index,
                )
        elif parse_result.is_success:
            builder.diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.NO_DECLARATIONS,
                    "successful parse produced no source unit",
                    path=builder.path,
                )
            )

        if self.config.emit_inferred_candidates and text:
            for pattern, concept, kind in _INFERRED_HINTS:
                if pattern.search(text):
                    builder.add_fact(
                        kind=kind,
                        predicate=f"candidate_for:{concept}",
                        authority_type=SolidityAuthorityType.INFERRED_CANDIDATE,
                        extraction_method=ExtractionMethod.HEURISTIC_INFERENCE,
                        code_unit_cid=source_unit.cid,
                        confidence=0.5,
                    )

        unit_ids = {item.cid for item in builder.units}
        for supplied in supplied_facts:
            if supplied.code_unit_cid not in unit_ids:
                raise ProjectionError(
                    "supplied fact references a code unit outside the projection"
                )
            method = (
                ExtractionMethod.VERIFIED_SUPPLIED
                if supplied.authority_type
                is SolidityAuthorityType.VERIFIED_RESULT
                else ExtractionMethod.REVIEWED_SUPPLIED
            )
            builder.add_fact(
                kind=supplied.kind,
                predicate=supplied.predicate,
                authority_type=supplied.authority_type,
                extraction_method=method,
                code_unit_cid=supplied.code_unit_cid,
                confidence=float(supplied.confidence),
                model_id=supplied.model_id,
                model_revision=supplied.model_revision,
                review_id=supplied.review_id,
                verification_id=supplied.verification_id,
            )

        if quality_score is not None:
            builder.diagnostics.append(
                ProjectionDiagnostic(
                    DiagnosticCode.QUALITY_NOT_SECURITY,
                    "corpus quality score retained as non-security metadata only",
                    path=builder.path,
                )
            )

        return ProjectionResult(
            source_cid=source_cid,
            config_cid=self.config_cid,
            language=_LANGUAGE,
            path=builder.path,
            parse_status=parse_status,
            code_units=tuple(builder.units),
            structural_facts=tuple(builder.facts),
            diagnostics=tuple(builder.diagnostics),
            quality_score=quality_score,
            quality_is_security_label=False,
        )

    def project_adapted(
        self,
        adapted: AdaptedSolidityCPTRow,
        *,
        parse_result: SolidityParseResult | None = None,
        supplied_facts: Sequence[SuppliedEvidenceFact] = (),
        quality_score: float | None = None,
    ) -> ProjectionResult:
        if not isinstance(adapted, AdaptedSolidityCPTRow):
            raise TypeError("adapted must be AdaptedSolidityCPTRow")
        return self.project(
            adapted.row,
            adapted.source_body,
            parse_result=parse_result,
            supplied_facts=supplied_facts,
            quality_score=quality_score,
        )


def project_solidity_row(
    row: SolidityCPTRow,
    source_body: str | SolidityCPTSourceBody,
    *,
    config: ProjectorConfig = ProjectorConfig(),
    parse_result: SolidityParseResult | None = None,
    supplied_facts: Sequence[SuppliedEvidenceFact] = (),
    quality_score: float | None = None,
) -> ProjectionResult:
    """Convenience wrapper for deterministic Solidity row projection."""

    return SolidityGraphProjector(config).project(
        row,
        source_body,
        parse_result=parse_result,
        supplied_facts=supplied_facts,
        quality_score=quality_score,
    )


# Descriptive aliases for downstream graph/retrieval tasks.
GraphProjector = SolidityGraphProjector
project_row = project_solidity_row


__all__ = [
    "DiagnosticCode",
    "ExtractionMethod",
    "FactKind",
    "GraphProjector",
    "PROJECTOR_CONFIG_SCHEMA_VERSION",
    "PROJECTOR_SCHEMA_VERSION",
    "ProjectionDiagnostic",
    "ProjectionError",
    "ProjectionResult",
    "ProjectorConfig",
    "SolidityGraphProjector",
    "StructuralFact",
    "SuppliedEvidenceFact",
    "UnitKind",
    "canonical_source_row_cid",
    "project_row",
    "project_solidity_row",
]
