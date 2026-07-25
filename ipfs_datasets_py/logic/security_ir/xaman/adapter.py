"""Xaman-specific adapter for immutable Security IR v1 declarations.

The generic legacy adapter provides lossless decoding.  This adapter adds the
Xaman boundary: a pinned source binding, namespaced domain vocabulary, and
declarative evidence requirements for unresolved assumptions.  Verification
observations and repository orchestration configuration remain detached and
have no proof authority.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, ClassVar, Final

from ...ir_core.diagnostics import Diagnostic
from ...ir_core.provenance import (
    ProvenanceValidationError,
    freeze_json_mapping,
    thaw_json,
)
from ...security_models.crypto_exchange.ir.schema import (
    SecurityModelIR,
    validate_ir as validate_legacy_ir,
)
from ..adapter import (
    LEGACY_TOP_LEVEL_FIELDS,
    LegacyAdapterError,
    LegacyVerificationData,
    adapt_legacy_security_ir,
)
from ..model import (
    SecurityExtension,
    SecurityIR,
    SecuritySource,
)
from .config import (
    XAMAN_ASSUMPTIONS,
    XAMAN_EXTENSION_ID,
    XAMAN_SECURITY_DOMAINS,
    XAMAN_VOCABULARY,
    XAMAN_VOCABULARY_SCHEMA_VERSION,
    XAMAN_VOCABULARY_VERSION,
    XamanAdapterConfig,
)


XAMAN_ADAPTER_VERSION: Final = "xaman-security-adapter/v1"
XAMAN_EVIDENCE_REQUIREMENT_VERSION: Final = "xaman-evidence-requirement/v1"
_REQUIREMENT_ID_RE = re.compile(r"[^A-Za-z0-9._:/-]+")
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class XamanAdapterError(ValueError):
    """Raised when input cannot be safely represented as a Xaman model."""


def _string_tuple(
    values: Sequence[str],
    name: str,
    *,
    identifiers: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise XamanAdapterError(f"{name} must be a sequence")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise XamanAdapterError(f"{name} must contain non-empty strings")
        if value != value.strip():
            raise XamanAdapterError(
                f"{name} values must not have surrounding whitespace"
            )
        if identifiers and not _STABLE_ID_RE.fullmatch(value):
            raise XamanAdapterError(
                f"{name} must contain stable identifiers"
            )
        result.append(value)
    if len(result) != len(set(result)):
        raise XamanAdapterError(f"{name} must contain unique values")
    return tuple(result)


@dataclass(frozen=True, slots=True)
class XamanEvidenceRequirement:
    """Evidence needed to substantiate an assumption used by Xaman claims.

    This is a requirement declaration only.  It has no satisfaction status,
    solver verdict, release decision, or proof authority.
    """

    requirement_id: str
    assumption_id: str
    claim_ids: tuple[str, ...]
    required_evidence: tuple[str, ...]
    blocking: bool
    source_ids: tuple[str, ...] = ()
    schema_version: str = XAMAN_EVIDENCE_REQUIREMENT_VERSION

    def __post_init__(self) -> None:
        for name in ("requirement_id", "assumption_id"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not _STABLE_ID_RE.fullmatch(value)
            ):
                raise XamanAdapterError(
                    f"{name} must be a stable identifier"
                )
        object.__setattr__(
            self,
            "claim_ids",
            _string_tuple(
                self.claim_ids, "claim_ids", identifiers=True
            ),
        )
        object.__setattr__(
            self,
            "required_evidence",
            _string_tuple(self.required_evidence, "required_evidence"),
        )
        object.__setattr__(
            self,
            "source_ids",
            _string_tuple(
                self.source_ids, "source_ids", identifiers=True
            ),
        )
        if not self.claim_ids:
            raise XamanAdapterError("claim_ids must not be empty")
        if not self.required_evidence:
            raise XamanAdapterError("required_evidence must not be empty")
        if not isinstance(self.blocking, bool):
            raise XamanAdapterError("blocking must be a boolean")
        if self.schema_version != XAMAN_EVIDENCE_REQUIREMENT_VERSION:
            raise XamanAdapterError(
                f"unsupported evidence requirement version: "
                f"{self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "blocking": self.blocking,
            "claim_ids": list(self.claim_ids),
            "required_evidence": list(self.required_evidence),
            "requirement_id": self.requirement_id,
            "schema_version": self.schema_version,
            "source_ids": list(self.source_ids),
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> "XamanEvidenceRequirement":
        if not isinstance(value, Mapping):
            raise XamanAdapterError(
                "Xaman evidence requirement must be a mapping"
            )
        allowed = {
            "assumption_id",
            "blocking",
            "claim_ids",
            "required_evidence",
            "requirement_id",
            "schema_version",
            "source_ids",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise XamanAdapterError(
                "unknown Xaman evidence requirement field(s): "
                + ", ".join(unknown)
            )
        return cls(
            requirement_id=value.get("requirement_id", ""),
            assumption_id=value.get("assumption_id", ""),
            claim_ids=tuple(value.get("claim_ids", ())),
            required_evidence=tuple(value.get("required_evidence", ())),
            blocking=value.get("blocking"),
            source_ids=tuple(value.get("source_ids", ())),
            schema_version=value.get(
                "schema_version", XAMAN_EVIDENCE_REQUIREMENT_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class XamanAdapterResult:
    """Adapted declaration plus detached compatibility and runtime bindings."""

    declaration: SecurityIR
    configuration: XamanAdapterConfig
    evidence_requirements: tuple[XamanEvidenceRequirement, ...]
    verification_data: LegacyVerificationData = field(
        default_factory=LegacyVerificationData
    )
    diagnostics: tuple[Diagnostic, ...] = ()
    legacy_payload: Mapping[str, Any] = field(default_factory=dict, repr=False)
    adapter_version: str = XAMAN_ADAPTER_VERSION

    # Explicitly prevent this result family from being treated as a proof.
    proof_authoritative: ClassVar[bool] = False
    authority: ClassVar[str] = "evidence_requirement"

    def __post_init__(self) -> None:
        if not isinstance(self.declaration, SecurityIR):
            raise XamanAdapterError("declaration must be a SecurityIR")
        if not isinstance(self.configuration, XamanAdapterConfig):
            raise XamanAdapterError(
                "configuration must be a XamanAdapterConfig"
            )
        requirements = tuple(self.evidence_requirements)
        if any(
            not isinstance(item, XamanEvidenceRequirement)
            for item in requirements
        ):
            raise XamanAdapterError(
                "evidence_requirements must contain XamanEvidenceRequirement"
            )
        object.__setattr__(self, "evidence_requirements", requirements)
        if not isinstance(self.verification_data, LegacyVerificationData):
            raise XamanAdapterError(
                "verification_data must be LegacyVerificationData"
            )
        diagnostics = tuple(self.diagnostics)
        for diagnostic in diagnostics:
            if not isinstance(diagnostic, Diagnostic):
                raise XamanAdapterError(
                    "diagnostics must contain Diagnostic records"
                )
            diagnostic.validate()
        object.__setattr__(self, "diagnostics", diagnostics)
        try:
            frozen_payload = freeze_json_mapping(self.legacy_payload)
        except ProvenanceValidationError as exc:
            raise XamanAdapterError(f"legacy_payload: {exc}") from exc
        object.__setattr__(self, "legacy_payload", frozen_payload)

    @property
    def security_ir(self) -> SecurityIR:
        return self.declaration

    @property
    def ir(self) -> SecurityIR:
        return self.declaration

    @property
    def config(self) -> XamanAdapterConfig:
        return self.configuration

    @property
    def configuration_digest(self) -> str:
        return self.configuration.digest

    @property
    def blockers(self) -> tuple[XamanEvidenceRequirement, ...]:
        return tuple(item for item in self.evidence_requirements if item.blocking)


def _copy_payload(
    legacy: SecurityModelIR | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(legacy, SecurityModelIR):
        raw: Mapping[str, Any] = legacy.to_dict()
    elif isinstance(legacy, Mapping):
        raw = legacy
    else:
        raise TypeError(
            "legacy must be a SecurityModelIR or JSON-like mapping"
        )
    try:
        payload = thaw_json(freeze_json_mapping(raw))
    except ProvenanceValidationError as exc:
        raise XamanAdapterError(f"Xaman input: {exc}") from exc
    unknown = sorted(set(payload) - set(LEGACY_TOP_LEVEL_FIELDS))
    if unknown:
        raise XamanAdapterError(
            "unknown Xaman legacy field(s): " + ", ".join(unknown)
        )
    return payload


def _validate_source_binding(
    payload: Mapping[str, Any], config: XamanAdapterConfig
) -> None:
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise XamanAdapterError("Xaman metadata must be a mapping")
    corpus = metadata.get("corpus", {})
    if not isinstance(corpus, Mapping):
        raise XamanAdapterError("Xaman metadata.corpus must be a mapping")
    source_url = corpus.get("source_url")
    revision = corpus.get("pinned_commit")
    if not isinstance(source_url, str) or not source_url:
        raise XamanAdapterError(
            "Xaman input must declare metadata.corpus.source_url"
        )
    if not isinstance(revision, str) or not revision:
        raise XamanAdapterError(
            "Xaman input must declare metadata.corpus.pinned_commit"
        )
    if source_url != config.source.uri:
        raise XamanAdapterError(
            "configured source URI does not match metadata.corpus.source_url"
        )
    if revision != config.source.revision:
        raise XamanAdapterError(
            "configured source revision does not match "
            "metadata.corpus.pinned_commit"
        )


def _legacy_extension_values(
    declaration: SecurityIR,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for extension in declaration.extensions:
        if extension.vocabulary != "legacy.security-model-ir":
            continue
        payload = extension.payload
        if not isinstance(payload, Mapping):
            continue
        field_name = payload.get("field_name")
        if isinstance(field_name, str):
            result[field_name] = thaw_json(payload.get("value"))
    return result


def _requirements(
    declaration: SecurityIR,
    config: XamanAdapterConfig,
) -> tuple[XamanEvidenceRequirement, ...]:
    claims_by_assumption: dict[str, list[str]] = {}
    blocking_assumptions: set[str] = set()
    for claim in declaration.claims:
        for assumption_id in claim.assumption_ids:
            claims_by_assumption.setdefault(assumption_id, []).append(
                claim.claim_id
            )
            if claim.severity == "blocking":
                blocking_assumptions.add(assumption_id)

    missing = sorted(
        set(claims_by_assumption) - set(config.evidence_requirements)
    )
    if missing:
        raise XamanAdapterError(
            "missing evidence requirements for Xaman assumption(s): "
            + ", ".join(missing)
        )

    requirements: list[XamanEvidenceRequirement] = []
    for assumption_id, claim_ids in sorted(claims_by_assumption.items()):
        slug = _REQUIREMENT_ID_RE.sub("-", assumption_id).strip("-")
        requirements.append(
            XamanEvidenceRequirement(
                requirement_id=f"requirement:xaman:{slug}",
                assumption_id=assumption_id,
                claim_ids=tuple(sorted(claim_ids)),
                required_evidence=tuple(
                    config.evidence_requirements[assumption_id]
                ),
                blocking=assumption_id in blocking_assumptions,
                source_ids=(config.source.source_id,),
            )
        )
    return tuple(requirements)


def _bind_source(record: Any, source_id: str) -> Any:
    return replace(
        record,
        source_ids=tuple(dict.fromkeys((*record.source_ids, source_id))),
    )


def _xaman_declaration(
    base: SecurityIR,
    config: XamanAdapterConfig,
    requirements: tuple[XamanEvidenceRequirement, ...],
) -> SecurityIR:
    domains = {claim.domain for claim in base.claims}
    if not domains:
        raise XamanAdapterError("Xaman input must contain at least one claim")
    unsupported = sorted(domains - XAMAN_SECURITY_DOMAINS)
    if unsupported:
        raise XamanAdapterError(
            "claim domains are outside Xaman vocabulary: "
            + ", ".join(unsupported)
        )
    if not domains - {"ledger"}:
        raise XamanAdapterError(
            "input is ambiguous with the exchange adapter; a Xaman-specific "
            "claim domain is required"
        )

    legacy_values = _legacy_extension_values(base)
    xaman_payload = {
        "capabilities": legacy_values.get("capabilities", []),
        "config_binding": {"config_id": config.config_id},
        "domains": sorted(domains),
        "events": legacy_values.get("events", []),
        "evidence_requirements": [
            item.to_dict() for item in requirements
        ],
        "invariants": legacy_values.get("invariants", []),
        "roles": legacy_values.get("roles", []),
        "schema_version": XAMAN_VOCABULARY_SCHEMA_VERSION,
        "source_binding": {"source_id": config.source.source_id},
    }
    xaman_extension = SecurityExtension(
        extension_id=XAMAN_EXTENSION_ID,
        vocabulary=XAMAN_VOCABULARY,
        version=XAMAN_VOCABULARY_VERSION,
        payload=xaman_payload,
        required=True,
        source_ids=(config.source.source_id,),
    )
    source = SecuritySource(
        source_id=config.source.source_id,
        uri=config.source.uri,
        revision=config.source.revision,
        content_sha256=config.source.content_sha256,
        review_status=config.source.review_status,
        attributes={
            "binding_kind": "pinned_source_revision",
            "config_id": config.config_id,
        },
    )
    existing_sources = tuple(
        item for item in base.sources if item.source_id != source.source_id
    )

    return SecurityIR(
        declaration_id=base.declaration_id,
        principals=tuple(
            _bind_source(item, source.source_id) for item in base.principals
        ),
        assets=tuple(
            _bind_source(item, source.source_id) for item in base.assets
        ),
        trust_zones=tuple(
            _bind_source(item, source.source_id) for item in base.trust_zones
        ),
        channels=tuple(
            _bind_source(item, source.source_id) for item in base.channels
        ),
        resources=tuple(
            _bind_source(item, source.source_id) for item in base.resources
        ),
        policies=tuple(
            _bind_source(item, source.source_id) for item in base.policies
        ),
        state_machines=tuple(
            _bind_source(item, source.source_id)
            for item in base.state_machines
        ),
        assumptions=tuple(
            _bind_source(
                replace(
                    item,
                    statement=XAMAN_ASSUMPTIONS.get(
                        item.assumption_id, item.statement
                    ),
                ),
                source.source_id,
            )
            for item in base.assumptions
        ),
        claims=tuple(
            _bind_source(item, source.source_id) for item in base.claims
        ),
        sources=(*existing_sources, source),
        extensions=(xaman_extension,),
    )


def validate_xaman_security_ir(declaration: SecurityIR) -> SecurityIR:
    """Validate the complete isolated Xaman declaration contract."""

    if not isinstance(declaration, SecurityIR):
        raise XamanAdapterError("declaration must be a SecurityIR")
    declaration.validate()
    extensions = [
        item
        for item in declaration.extensions
        if item.vocabulary == XAMAN_VOCABULARY
    ]
    if len(extensions) != 1 or len(declaration.extensions) != 1:
        raise XamanAdapterError(
            "Xaman declarations require exactly one Xaman extension"
        )
    extension = extensions[0]
    if (
        extension.extension_id != XAMAN_EXTENSION_ID
        or extension.version != XAMAN_VOCABULARY_VERSION
        or not extension.required
    ):
        raise XamanAdapterError(
            "Xaman extension identity, version, and required flag must match "
            "the Xaman v1 vocabulary"
        )
    if not isinstance(extension.payload, Mapping):
        raise XamanAdapterError("Xaman extension payload must be a mapping")
    allowed = {
        "capabilities",
        "config_binding",
        "domains",
        "events",
        "evidence_requirements",
        "invariants",
        "roles",
        "schema_version",
        "source_binding",
    }
    unknown = sorted(set(extension.payload) - allowed)
    missing = sorted(allowed - set(extension.payload))
    if unknown or missing:
        details = []
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        if missing:
            details.append("missing: " + ", ".join(missing))
        raise XamanAdapterError(
            "invalid Xaman extension fields (" + "; ".join(details) + ")"
        )
    if (
        extension.payload["schema_version"]
        != XAMAN_VOCABULARY_SCHEMA_VERSION
    ):
        raise XamanAdapterError("Xaman extension schema version mismatch")
    domains = extension.payload["domains"]
    if isinstance(domains, (str, bytes, bytearray)) or not isinstance(
        domains, Sequence
    ):
        raise XamanAdapterError("Xaman domains must be a sequence")
    domain_values = _string_tuple(
        tuple(domains), "Xaman domains", identifiers=True
    )
    if set(domain_values) != {
        claim.domain for claim in declaration.claims
    }:
        raise XamanAdapterError(
            "Xaman extension domains must match declaration claims"
        )
    unsupported = sorted(set(domain_values) - XAMAN_SECURITY_DOMAINS)
    if unsupported:
        raise XamanAdapterError(
            "claim domains are outside Xaman vocabulary: "
            + ", ".join(unsupported)
        )
    source_binding = extension.payload["source_binding"]
    config_binding = extension.payload["config_binding"]
    if (
        not isinstance(source_binding, Mapping)
        or set(source_binding) != {"source_id"}
        or source_binding["source_id"]
        not in {source.source_id for source in declaration.sources}
    ):
        raise XamanAdapterError("Xaman source binding is invalid")
    if (
        not isinstance(config_binding, Mapping)
        or set(config_binding) != {"config_id"}
        or not isinstance(config_binding["config_id"], str)
        or not config_binding["config_id"]
    ):
        raise XamanAdapterError("Xaman config binding is invalid")

    assumption_ids = {
        assumption.assumption_id for assumption in declaration.assumptions
    }
    claim_ids = {claim.claim_id for claim in declaration.claims}
    raw_requirements = extension.payload["evidence_requirements"]
    if isinstance(
        raw_requirements, (str, bytes, bytearray)
    ) or not isinstance(raw_requirements, Sequence):
        raise XamanAdapterError(
            "Xaman evidence_requirements must be a sequence"
        )
    parsed_items: list[XamanEvidenceRequirement] = []
    for item in raw_requirements:
        parsed_items.append(XamanEvidenceRequirement.from_dict(item))
    parsed = tuple(parsed_items)
    if len({item.requirement_id for item in parsed}) != len(parsed):
        raise XamanAdapterError(
            "Xaman evidence requirement identifiers must be unique"
        )
    for item in parsed:
        if item.assumption_id not in assumption_ids:
            raise XamanAdapterError(
                f"evidence requirement {item.requirement_id!r} references "
                "an unknown assumption"
            )
        if set(item.claim_ids) - claim_ids:
            raise XamanAdapterError(
                f"evidence requirement {item.requirement_id!r} references "
                "an unknown claim"
            )
    required_assumption_ids = {
        assumption_id
        for claim in declaration.claims
        for assumption_id in claim.assumption_ids
    }
    if {item.assumption_id for item in parsed} != required_assumption_ids:
        raise XamanAdapterError(
            "Xaman evidence requirements must cover every claim assumption"
        )
    return declaration


def adapt_xaman_security_ir(
    legacy: SecurityModelIR | Mapping[str, Any],
    config: XamanAdapterConfig,
) -> XamanAdapterResult:
    """Adapt a legacy Xaman declaration with explicit source/config bindings."""

    if not isinstance(config, XamanAdapterConfig):
        raise XamanAdapterError("config must be an explicit XamanAdapterConfig")
    payload = _copy_payload(legacy)
    _validate_source_binding(payload, config)
    try:
        generic = adapt_legacy_security_ir(payload)
    except LegacyAdapterError as exc:
        raise XamanAdapterError(str(exc)) from exc
    requirements = _requirements(generic.declaration, config)
    declaration = _xaman_declaration(
        generic.declaration, config, requirements
    )
    validate_xaman_security_ir(declaration)
    return XamanAdapterResult(
        declaration=declaration,
        configuration=config,
        evidence_requirements=requirements,
        verification_data=generic.verification_data,
        diagnostics=generic.diagnostics,
        legacy_payload=payload,
    )


def to_legacy_xaman_security_ir(
    adapted: XamanAdapterResult,
    *,
    as_model: bool = False,
) -> dict[str, Any] | SecurityModelIR:
    """Return the detached legacy payload captured during Xaman adaptation."""

    if not isinstance(adapted, XamanAdapterResult):
        raise TypeError("adapted must be a XamanAdapterResult")
    payload = thaw_json(adapted.legacy_payload)
    if not as_model:
        return payload
    try:
        model = SecurityModelIR.from_untrusted_dict(payload, strict=True)
        return validate_legacy_ir(model)
    except (TypeError, ValueError) as exc:
        raise XamanAdapterError(
            f"captured legacy payload is invalid: {exc}"
        ) from exc


class XamanSecurityAdapter:
    """Bound adapter object implementing the ``XamanSecurityAdapter@1`` API."""

    interface: ClassVar[str] = "XamanSecurityAdapter@1"

    def __init__(self, config: XamanAdapterConfig) -> None:
        if not isinstance(config, XamanAdapterConfig):
            raise XamanAdapterError(
                "config must be an explicit XamanAdapterConfig"
            )
        self._config = config

    @property
    def config(self) -> XamanAdapterConfig:
        return self._config

    def adapt(
        self, legacy: SecurityModelIR | Mapping[str, Any]
    ) -> XamanAdapterResult:
        return adapt_xaman_security_ir(legacy, config=self._config)

    def to_legacy(self, adapted: XamanAdapterResult) -> dict[str, Any]:
        return to_legacy_xaman_security_ir(adapted)

    def validate(self, declaration: SecurityIR) -> SecurityIR:
        return validate_xaman_security_ir(declaration)


# Concise aliases following the shared legacy adapter's naming.
adapt_xaman_declaration = adapt_xaman_security_ir
to_legacy_xaman_declaration = to_legacy_xaman_security_ir


__all__ = [
    "XAMAN_ADAPTER_VERSION",
    "XAMAN_EVIDENCE_REQUIREMENT_VERSION",
    "XamanAdapterError",
    "XamanAdapterResult",
    "XamanEvidenceRequirement",
    "XamanSecurityAdapter",
    "adapt_xaman_declaration",
    "adapt_xaman_security_ir",
    "to_legacy_xaman_declaration",
    "to_legacy_xaman_security_ir",
    "validate_xaman_security_ir",
]
