"""Loss-aware adapter from the mutable legacy security model to Security IR v1."""

from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from ..ir_core.canonical import canonical_json_bytes
from ..ir_core.diagnostics import (
    Diagnostic,
    DiagnosticLocation,
    DiagnosticSeverity,
)
from ..ir_core.provenance import (
    ProvenanceValidationError,
    freeze_json_mapping,
    thaw_json,
)
from ..security_models.crypto_exchange.ir.schema import (
    SecurityModelIR,
    validate_ir as validate_legacy_ir,
)
from .model import (
    Asset,
    Policy,
    PolicyEffect,
    Principal,
    Resource,
    SecurityClaim,
    SecurityExtension,
    SecurityIR,
    SecuritySource,
    StateMachine,
    StateTransition,
    ThreatAssumption,
)


LEGACY_ADAPTER_VERSION: Final = "security-ir-legacy-adapter/v1"

LEGACY_DECLARATION_FIELDS: Final = (
    "entities",
    "assets",
    "wallets",
    "accounts",
    "roles",
    "principals",
    "capabilities",
    "policies",
    "events",
    "state_machines",
    "invariants",
    "claims",
    "assumptions",
    "prover_targets",
    "metadata",
)
LEGACY_VERIFICATION_FIELDS: Final = (
    "proof_obligations",
    "disproof_vectors",
    "runtime_traces",
    "solver_results",
)
LEGACY_TOP_LEVEL_FIELDS: Final = (
    "schema_version",
    "model_id",
    *LEGACY_DECLARATION_FIELDS,
    *LEGACY_VERIFICATION_FIELDS,
)
_EXTENSION_FIELDS: Final = (
    "roles",
    "capabilities",
    "events",
    "invariants",
    "prover_targets",
    "metadata",
)


class LegacyAdapterError(ValueError):
    """Raised when a legacy payload cannot be safely adapted."""


def _freeze_mapping(value: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value)
    except ProvenanceValidationError as exc:
        raise LegacyAdapterError(f"{name}: {exc}") from exc


def _freeze_records(
    values: Sequence[Mapping[str, Any]], name: str
) -> tuple[Mapping[str, Any], ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise LegacyAdapterError(f"{name} must be a sequence")
    result: list[Mapping[str, Any]] = []
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            raise LegacyAdapterError(f"{name}[{index}] must be a mapping")
        result.append(_freeze_mapping(value, f"{name}[{index}]"))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class LegacyVerificationData:
    """Detached observations from a legacy model.

    This record is immutable but intentionally has no declaration identity.
    It exists solely to make adaptation reversible until dedicated v1 result
    families replace the mixed legacy records.
    """

    proof_obligations: tuple[Mapping[str, Any], ...] = ()
    disproof_vectors: tuple[Mapping[str, Any], ...] = ()
    runtime_traces: tuple[Mapping[str, Any], ...] = ()
    solver_results: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        for name in LEGACY_VERIFICATION_FIELDS:
            object.__setattr__(
                self, name, _freeze_records(getattr(self, name), name)
            )

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {
            name: [thaw_json(item) for item in getattr(self, name)]
            for name in LEGACY_VERIFICATION_FIELDS
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> "LegacyVerificationData":
        unknown = sorted(set(value) - set(LEGACY_VERIFICATION_FIELDS))
        if unknown:
            raise LegacyAdapterError(
                f"unknown LegacyVerificationData field(s): {', '.join(unknown)}"
            )
        return cls(
            **{
                name: tuple(value.get(name, ()))
                for name in LEGACY_VERIFICATION_FIELDS
            }
        )


@dataclass(frozen=True, slots=True)
class LegacyAdapterResult:
    """A declaration, detached run data, and explicit conversion diagnostics."""

    declaration: SecurityIR
    verification_data: LegacyVerificationData = field(
        default_factory=LegacyVerificationData
    )
    diagnostics: tuple[Diagnostic, ...] = ()
    legacy_schema_version: str = "security-model-ir/v1"
    adapter_version: str = LEGACY_ADAPTER_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.declaration, SecurityIR):
            raise LegacyAdapterError("declaration must be a SecurityIR")
        if not isinstance(self.verification_data, LegacyVerificationData):
            raise LegacyAdapterError(
                "verification_data must be LegacyVerificationData"
            )
        diagnostics = tuple(self.diagnostics)
        for diagnostic in diagnostics:
            if not isinstance(diagnostic, Diagnostic):
                raise LegacyAdapterError(
                    "diagnostics must contain Diagnostic records"
                )
            diagnostic.validate()
        object.__setattr__(self, "diagnostics", diagnostics)

    @property
    def security_ir(self) -> SecurityIR:
        """Compatibility spelling for the adapted declaration."""

        return self.declaration

    @property
    def ir(self) -> SecurityIR:
        """Short compatibility spelling for the adapted declaration."""

        return self.declaration

    @property
    def model(self) -> SecurityIR:
        """Compatibility spelling used by model-adapter call sites."""

        return self.declaration

    @property
    def has_loss(self) -> bool:
        return any(
            item.code.startswith("security.adapter.loss")
            for item in self.diagnostics
        )

    @property
    def has_unsupported(self) -> bool:
        return any(
            item.code.startswith("security.adapter.unsupported")
            for item in self.diagnostics
        )

    @property
    def lossless(self) -> bool:
        return not self.has_loss


def _diagnostic(
    code: str,
    message: str,
    *,
    severity: DiagnosticSeverity = DiagnosticSeverity.INFO,
    field_path: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> Diagnostic:
    result = Diagnostic(
        code=code,
        message=message,
        severity=severity,
        location=DiagnosticLocation(
            field_path=field_path,
            metadata=metadata or {},
        ),
    )
    result.validate()
    return result


def _source_id(reference: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json_bytes(reference)).hexdigest()
    return f"source:legacy:{digest[:24]}"


class _SourceRegistry:
    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self._sources: dict[str, SecuritySource] = {}
        self._diagnostics = diagnostics

    def ids_for(
        self, record: Mapping[str, Any], *, field_path: str
    ) -> tuple[str, ...]:
        raw = record.get("evidence_refs", ())
        if raw is None:
            return ()
        if isinstance(raw, (str, bytes, bytearray)) or not isinstance(
            raw, Sequence
        ):
            self._diagnostics.append(
                _diagnostic(
                    "security.adapter.loss.invalid_evidence_refs",
                    "Legacy evidence_refs is not a sequence and cannot be typed.",
                    severity=DiagnosticSeverity.ERROR,
                    field_path=f"{field_path}/evidence_refs",
                )
            )
            return ()
        result: list[str] = []
        for index, reference in enumerate(raw):
            path = f"{field_path}/evidence_refs/{index}"
            if not isinstance(reference, Mapping):
                self._diagnostics.append(
                    _diagnostic(
                        "security.adapter.loss.invalid_evidence_ref",
                        "Legacy evidence reference is not a mapping.",
                        severity=DiagnosticSeverity.ERROR,
                        field_path=path,
                    )
                )
                continue
            identifier = _source_id(reference)
            if identifier not in self._sources:
                uri = reference.get("path") or reference.get("uri")
                if not isinstance(uri, str) or not uri.strip():
                    uri = f"legacy-evidence:{identifier}"
                    self._diagnostics.append(
                        _diagnostic(
                            "security.adapter.unsupported.source_uri",
                            "Legacy evidence has no path/URI; a stable placeholder URI was used.",
                            severity=DiagnosticSeverity.WARNING,
                            field_path=path,
                        )
                    )
                sha256 = reference.get("sha256", "")
                if not isinstance(sha256, str) or len(sha256) != 64:
                    sha256 = ""
                    self._diagnostics.append(
                        _diagnostic(
                            "security.adapter.unsupported.source_digest",
                            "Legacy evidence is not bound to a normalized SHA-256 digest.",
                            severity=DiagnosticSeverity.WARNING,
                            field_path=path,
                        )
                    )
                review_status = reference.get("review_status", "unreviewed")
                if not isinstance(review_status, str) or not review_status:
                    review_status = "unreviewed"
                self._sources[identifier] = SecuritySource(
                    source_id=identifier,
                    uri=uri,
                    content_sha256=sha256,
                    review_status=review_status,
                    attributes={"legacy_reference": reference},
                )
            result.append(identifier)
        return tuple(dict.fromkeys(result))

    @property
    def sources(self) -> tuple[SecuritySource, ...]:
        return tuple(self._sources.values())


def _legacy_attributes(
    collection: str, record: Mapping[str, Any]
) -> Mapping[str, Any]:
    return {
        "legacy_collection": collection,
        "legacy_record": record,
    }


def _string_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str) and value:
        return (value,)
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return tuple(item for item in value if isinstance(item, str) and item)
    return ()


def _resource(
    record: Mapping[str, Any],
    collection: str,
    source_ids: tuple[str, ...],
) -> Resource:
    owners = _string_values(
        record.get("owner")
        or record.get("principal")
        or record.get("principal_id")
    )
    assets = _string_values(record.get("asset_id") or record.get("asset"))
    legacy_kind = record.get("kind")
    kind = (
        f"{collection[:-1]}:{legacy_kind}"
        if isinstance(legacy_kind, str) and legacy_kind
        else collection[:-1]
    )
    return Resource(
        resource_id=record["id"],
        kind=kind,
        owner_principal_ids=owners,
        asset_ids=assets,
        source_ids=source_ids,
        attributes=_legacy_attributes(collection, record),
    )


def _state_machine(
    record: Mapping[str, Any],
    source_ids: tuple[str, ...],
    diagnostics: list[Diagnostic],
    index: int,
) -> StateMachine:
    transitions: list[StateTransition] = []
    for transition_index, raw in enumerate(record.get("transitions", ())):
        if not isinstance(raw, Mapping):
            continue
        source = raw.get("source_state", raw.get("source", raw.get("from")))
        target = raw.get("target_state", raw.get("target", raw.get("to")))
        event = raw.get("event")
        if all(isinstance(item, str) and item for item in (source, target, event)):
            transitions.append(
                StateTransition(
                    source_state=source,
                    target_state=target,
                    event=event,
                    guard=raw.get("guard", "")
                    if isinstance(raw.get("guard", ""), str)
                    else "",
                    effect=raw.get("effect", "")
                    if isinstance(raw.get("effect", ""), str)
                    else "",
                    attributes={"legacy_record": raw},
                )
            )
        else:
            diagnostics.append(
                _diagnostic(
                    "security.adapter.unsupported.state_transition_shape",
                    "A legacy transition was preserved but lacks typed endpoints.",
                    severity=DiagnosticSeverity.WARNING,
                    field_path=(
                        f"/state_machines/{index}/transitions/{transition_index}"
                    ),
                )
            )
    initial = record.get("initial", record.get("initial_state", record.get("current", "")))
    return StateMachine(
        state_machine_id=record["id"],
        states=tuple(record["states"]),
        initial_state=initial if isinstance(initial, str) else "",
        transitions=tuple(transitions),
        source_ids=source_ids,
        attributes=_legacy_attributes("state_machines", record),
    )


def _extension(field_name: str, value: Any) -> SecurityExtension:
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", field_name)[:96] or "field"
    suffix = hashlib.sha256(field_name.encode("utf-8")).hexdigest()[:12]
    return SecurityExtension(
        extension_id=f"extension:legacy:{slug}:{suffix}",
        vocabulary="legacy.security-model-ir",
        version="v1",
        payload={"field_name": field_name, "value": value},
    )


def _copy_input(
    legacy: SecurityModelIR | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(legacy, SecurityModelIR):
        value: Any = legacy.to_dict()
    elif isinstance(legacy, Mapping):
        value = dict(legacy)
    else:
        raise TypeError(
            "legacy must be a SecurityModelIR or JSON-like mapping"
        )
    if not isinstance(value, dict):
        raise LegacyAdapterError("legacy input must decode to a mapping")
    # Freezing and thawing rejects non-JSON objects while returning a completely
    # detached ordinary structure convenient for legacy validation.
    return thaw_json(_freeze_mapping(value, "legacy input"))


def adapt_legacy_security_ir(
    legacy: SecurityModelIR | Mapping[str, Any],
) -> LegacyAdapterResult:
    """Adapt a legacy model without retaining any caller-owned mutable value.

    Recognized legacy declarations become typed v1 records.  Legacy-only
    declaration fields are retained as namespaced extensions.  Mixed-in
    verification fields are retained in :class:`LegacyVerificationData`, so
    they round-trip but cannot affect :attr:`SecurityIR.identity`.
    """

    payload = _copy_input(legacy)
    known_payload = {
        name: payload[name] for name in LEGACY_TOP_LEVEL_FIELDS if name in payload
    }
    # Validate the complete recognized legacy contract before translating it.
    try:
        legacy_model = SecurityModelIR.from_untrusted_dict(
            known_payload, strict=True
        )
        validate_legacy_ir(legacy_model)
    except (TypeError, ValueError) as exc:
        raise LegacyAdapterError(f"invalid legacy SecurityModelIR: {exc}") from exc

    diagnostics: list[Diagnostic] = []
    sources = _SourceRegistry(diagnostics)

    principals: list[Principal] = []
    for index, record in enumerate(payload["principals"]):
        source_ids = sources.ids_for(record, field_path=f"/principals/{index}")
        principals.append(
            Principal(
                principal_id=record["id"],
                kind=record.get("kind", "unspecified"),
                role_ids=_string_values(record.get("role") or record.get("roles")),
                trust_zone_ids=_string_values(
                    record.get("trust_zone") or record.get("trust_zones")
                ),
                source_ids=source_ids,
                attributes=_legacy_attributes("principals", record),
            )
        )

    assets: list[Asset] = []
    for index, record in enumerate(payload["assets"]):
        assets.append(
            Asset(
                asset_id=record["id"],
                kind=record.get("kind", "unspecified"),
                symbol=record.get("symbol", ""),
                source_ids=sources.ids_for(
                    record, field_path=f"/assets/{index}"
                ),
                attributes=_legacy_attributes("assets", record),
            )
        )

    resources: list[Resource] = []
    for collection in ("entities", "wallets", "accounts"):
        for index, record in enumerate(payload[collection]):
            resources.append(
                _resource(
                    record,
                    collection,
                    sources.ids_for(
                        record, field_path=f"/{collection}/{index}"
                    ),
                )
            )

    policies: list[Policy] = []
    for index, record in enumerate(payload["policies"]):
        raw_effect = record.get("effect", "unspecified")
        try:
            effect = PolicyEffect(raw_effect)
        except (TypeError, ValueError):
            effect = PolicyEffect.UNSPECIFIED
            if "effect" in record:
                diagnostics.append(
                    _diagnostic(
                        "security.adapter.unsupported.policy_effect",
                        f"Legacy policy effect {raw_effect!r} was preserved as an extension attribute.",
                        severity=DiagnosticSeverity.WARNING,
                        field_path=f"/policies/{index}/effect",
                    )
                )
        policies.append(
            Policy(
                policy_id=record["id"],
                name=record.get("name", record["id"]),
                effect=effect,
                principal_ids=_string_values(
                    record.get("principal_ids") or record.get("principals")
                ),
                resource_ids=_string_values(
                    record.get("resource_ids") or record.get("resources")
                ),
                channel_ids=_string_values(
                    record.get("channel_ids") or record.get("channels")
                ),
                source_ids=sources.ids_for(
                    record, field_path=f"/policies/{index}"
                ),
                attributes=_legacy_attributes("policies", record),
            )
        )

    state_machines = tuple(
        _state_machine(
            record,
            sources.ids_for(record, field_path=f"/state_machines/{index}"),
            diagnostics,
            index,
        )
        for index, record in enumerate(payload["state_machines"])
    )

    assumptions: list[ThreatAssumption] = []
    for index, raw in enumerate(payload["assumptions"]):
        if isinstance(raw, str):
            assumptions.append(
                ThreatAssumption(
                    assumption_id=raw,
                    statement=raw,
                    attributes={
                        "legacy_collection": "assumptions",
                        "legacy_value": raw,
                    },
                )
            )
            diagnostics.append(
                _diagnostic(
                    "security.adapter.unsupported.assumption_statement",
                    "A legacy assumption identifier has no statement; its identifier is used as the typed statement.",
                    severity=DiagnosticSeverity.WARNING,
                    field_path=f"/assumptions/{index}",
                )
            )
            continue
        source_ids = sources.ids_for(raw, field_path=f"/assumptions/{index}")
        assumption_id = raw.get("id", raw.get("assumption_id", ""))
        statement = raw.get("description", raw.get("statement", assumption_id))
        assumptions.append(
            ThreatAssumption(
                assumption_id=assumption_id,
                statement=statement,
                source_ids=source_ids,
                attributes={
                    "legacy_collection": "assumptions",
                    "legacy_value": raw,
                },
            )
        )

    claims: list[SecurityClaim] = []
    for index, record in enumerate(payload["claims"]):
        claims.append(
            SecurityClaim(
                claim_id=record["id"],
                statement=record["description"],
                domain=record["domain"],
                severity=record.get("severity", "unspecified"),
                assumption_ids=tuple(record.get("required_assumptions", ())),
                policy_ids=tuple(record.get("policy_ids", ())),
                source_ids=sources.ids_for(
                    record, field_path=f"/claims/{index}"
                ),
                attributes=_legacy_attributes("claims", record),
            )
        )

    extensions = [_extension(name, payload[name]) for name in _EXTENSION_FIELDS]
    if any(payload[name] for name in _EXTENSION_FIELDS):
        diagnostics.append(
            _diagnostic(
                "security.adapter.extension_preserved",
                "Legacy-only declaration fields were preserved as typed, namespaced extensions.",
                metadata={"fields": list(_EXTENSION_FIELDS)},
            )
        )

    unknown_fields = sorted(set(payload) - set(LEGACY_TOP_LEVEL_FIELDS))
    for field_name in unknown_fields:
        extensions.append(_extension(f"unsupported_{field_name}", payload[field_name]))
        diagnostics.append(
            _diagnostic(
                "security.adapter.unsupported.top_level_field",
                f"Unsupported legacy top-level field {field_name!r} was preserved as an extension.",
                severity=DiagnosticSeverity.WARNING,
                field_path=f"/{field_name}",
                metadata={"field_name": field_name},
            )
        )

    verification = LegacyVerificationData(
        **{
            name: tuple(payload[name])
            for name in LEGACY_VERIFICATION_FIELDS
        }
    )
    if any(getattr(verification, name) for name in LEGACY_VERIFICATION_FIELDS):
        diagnostics.append(
            _diagnostic(
                "security.adapter.verification_detached",
                "Legacy proof, disproof, trace, and solver observations were detached from the declaration.",
                metadata={"fields": list(LEGACY_VERIFICATION_FIELDS)},
            )
        )

    declaration = SecurityIR(
        declaration_id=payload["model_id"],
        principals=tuple(principals),
        assets=tuple(assets),
        resources=tuple(resources),
        policies=tuple(policies),
        state_machines=state_machines,
        assumptions=tuple(assumptions),
        claims=tuple(claims),
        sources=sources.sources,
        extensions=tuple(extensions),
    )
    return LegacyAdapterResult(
        declaration=declaration,
        verification_data=verification,
        diagnostics=tuple(diagnostics),
        legacy_schema_version=payload["schema_version"],
    )


def _legacy_record(record: Any) -> dict[str, Any]:
    attributes = record.attributes
    value = attributes.get("legacy_record")
    if not isinstance(value, Mapping):
        raise LegacyAdapterError(
            f"{type(record).__name__} lacks its lossless legacy record"
        )
    return thaw_json(value)


def to_legacy_security_ir(
    adapted: LegacyAdapterResult | SecurityIR,
    *,
    verification_data: LegacyVerificationData | None = None,
    as_model: bool = False,
) -> dict[str, Any] | SecurityModelIR:
    """Reconstruct the legacy payload represented by an adapter result.

    Passing only a declaration is supported, but callers must explicitly
    supply detached verification data if they need those observations.
    """

    if isinstance(adapted, LegacyAdapterResult):
        declaration = adapted.declaration
        run_data = (
            verification_data
            if verification_data is not None
            else adapted.verification_data
        )
        legacy_schema_version = adapted.legacy_schema_version
    elif isinstance(adapted, SecurityIR):
        declaration = adapted
        run_data = verification_data or LegacyVerificationData()
        legacy_schema_version = "security-model-ir/v1"
    else:
        raise TypeError("adapted must be LegacyAdapterResult or SecurityIR")

    collections: dict[str, list[Any]] = {
        name: []
        for name in (
            "entities",
            "assets",
            "wallets",
            "accounts",
            "roles",
            "principals",
            "capabilities",
            "policies",
            "events",
            "state_machines",
            "invariants",
            "claims",
        )
    }
    for item in declaration.assets:
        collections["assets"].append(_legacy_record(item))
    for item in declaration.principals:
        collections["principals"].append(_legacy_record(item))
    for item in declaration.resources:
        collection = item.attributes.get("legacy_collection")
        if collection not in {"entities", "wallets", "accounts"}:
            raise LegacyAdapterError(
                f"resource {item.resource_id!r} has no supported legacy collection"
            )
        collections[collection].append(_legacy_record(item))
    for item in declaration.policies:
        collections["policies"].append(_legacy_record(item))
    for item in declaration.state_machines:
        collections["state_machines"].append(_legacy_record(item))
    for item in declaration.claims:
        collections["claims"].append(_legacy_record(item))

    assumptions: list[Any] = []
    for item in declaration.assumptions:
        value = item.attributes.get("legacy_value")
        if value is None:
            raise LegacyAdapterError(
                f"assumption {item.assumption_id!r} lacks its lossless legacy value"
            )
        assumptions.append(thaw_json(value))

    extension_values: dict[str, Any] = {}
    unknown_values: dict[str, Any] = {}
    for extension in declaration.extensions:
        if extension.vocabulary != "legacy.security-model-ir":
            raise LegacyAdapterError(
                f"extension {extension.extension_id!r} has no legacy adapter"
            )
        payload = thaw_json(extension.payload)
        if not isinstance(payload, Mapping):
            raise LegacyAdapterError(
                f"extension {extension.extension_id!r} payload is malformed"
            )
        field_name = payload.get("field_name")
        if not isinstance(field_name, str) or "value" not in payload:
            raise LegacyAdapterError(
                f"extension {extension.extension_id!r} payload is malformed"
            )
        if field_name.startswith("unsupported_"):
            unknown_values[field_name.removeprefix("unsupported_")] = payload["value"]
        else:
            extension_values[field_name] = payload["value"]

    missing_extensions = sorted(set(_EXTENSION_FIELDS) - set(extension_values))
    if missing_extensions:
        raise LegacyAdapterError(
            "declaration lacks lossless legacy extension(s): "
            + ", ".join(missing_extensions)
        )
    for name in ("roles", "capabilities", "events", "invariants"):
        collections[name] = copy.deepcopy(extension_values[name])

    payload: dict[str, Any] = {
        "schema_version": legacy_schema_version,
        "model_id": declaration.declaration_id,
        "entities": collections["entities"],
        "assets": collections["assets"],
        "wallets": collections["wallets"],
        "accounts": collections["accounts"],
        "roles": collections["roles"],
        "principals": collections["principals"],
        "capabilities": collections["capabilities"],
        "policies": collections["policies"],
        "events": collections["events"],
        "state_machines": collections["state_machines"],
        "invariants": collections["invariants"],
        "claims": collections["claims"],
        **run_data.to_dict(),
        "assumptions": assumptions,
        "prover_targets": copy.deepcopy(extension_values["prover_targets"]),
        "metadata": copy.deepcopy(extension_values["metadata"]),
        **copy.deepcopy(unknown_values),
    }
    if as_model:
        if unknown_values:
            raise LegacyAdapterError(
                "unsupported top-level fields cannot be represented by SecurityModelIR"
            )
        result = SecurityModelIR.from_untrusted_dict(payload, strict=True)
        return validate_legacy_ir(result)
    return payload


@dataclass(frozen=True, slots=True)
class SecurityIRLegacyAdapter:
    """Stateless object facade for dependency-injected adapter call sites."""

    version: str = LEGACY_ADAPTER_VERSION

    def __post_init__(self) -> None:
        if self.version != LEGACY_ADAPTER_VERSION:
            raise LegacyAdapterError(
                f"unsupported legacy adapter version: {self.version!r}"
            )

    def adapt(
        self, legacy: SecurityModelIR | Mapping[str, Any]
    ) -> LegacyAdapterResult:
        return adapt_legacy_security_ir(legacy)

    def to_legacy(
        self,
        adapted: LegacyAdapterResult | SecurityIR,
        *,
        verification_data: LegacyVerificationData | None = None,
        as_model: bool = False,
    ) -> dict[str, Any] | SecurityModelIR:
        return to_legacy_security_ir(
            adapted,
            verification_data=verification_data,
            as_model=as_model,
        )


# Concise aliases for call sites that already imply the Security domain.
adapt_legacy_model = adapt_legacy_security_ir
adapt_legacy = adapt_legacy_security_ir
from_legacy = adapt_legacy_security_ir
to_legacy_model = to_legacy_security_ir
to_legacy = to_legacy_security_ir
LegacySecurityIRAdapter = SecurityIRLegacyAdapter


__all__ = [
    "LEGACY_ADAPTER_VERSION",
    "LEGACY_DECLARATION_FIELDS",
    "LEGACY_TOP_LEVEL_FIELDS",
    "LEGACY_VERIFICATION_FIELDS",
    "LegacyAdapterError",
    "LegacyAdapterResult",
    "LegacySecurityIRAdapter",
    "LegacyVerificationData",
    "SecurityIRLegacyAdapter",
    "adapt_legacy",
    "adapt_legacy_model",
    "adapt_legacy_security_ir",
    "from_legacy",
    "to_legacy",
    "to_legacy_model",
    "to_legacy_security_ir",
]
