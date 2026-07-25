"""Fail-closed crypto-exchange adapter for immutable Security IR v1."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Final, Protocol, runtime_checkable

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.provenance import thaw_json
from ..adapter import (
    LegacyAdapterError,
    LegacyAdapterResult,
    LegacyVerificationData,
    adapt_legacy_security_ir,
    to_legacy_security_ir,
)
from ..model import (
    SecurityClaim,
    SecurityExtension,
    SecurityIR,
)
from ...security_models.crypto_exchange.ir.schema import SecurityModelIR
from .vocabulary import (
    EXCHANGE_ASSUMPTIONS,
    EXCHANGE_DOMAINS,
    EXCHANGE_EXTENSION_FIELDS,
    EXCHANGE_EXTENSION_ID,
    EXCHANGE_POLICY_NAMES,
    EXCHANGE_RESOURCE_KINDS,
    EXCHANGE_VOCABULARY,
    EXCHANGE_VOCABULARY_SCHEMA_VERSION,
    EXCHANGE_VOCABULARY_VERSION,
    ExchangeVocabularyError,
    exchange_term,
    parse_exchange_term,
    validate_exchange_extension,
)


EXCHANGE_ADAPTER_VERSION: Final = "exchange-security-adapter/v1"
_LEGACY_VOCABULARY: Final = "legacy.security-model-ir"


class ExchangeAdapterError(ValueError):
    """Raised when exchange semantics cannot be adapted safely."""


@runtime_checkable
class DeclaredExtensionAdapter(Protocol):
    """Validator for an extension outside the exchange vocabulary."""

    def validate(self, extension: SecurityExtension) -> None:
        """Raise when *extension* is not supported."""


ExtensionAdapter = DeclaredExtensionAdapter | Callable[[SecurityExtension], Any]
ExtensionAdapters = Mapping[str | tuple[str, str], ExtensionAdapter]


def _extension_key(extension: SecurityExtension) -> tuple[str, ...]:
    keys = [
        extension.extension_id,
        extension.vocabulary,
        f"{extension.vocabulary}@{extension.version}",
    ]
    payload = thaw_json(extension.payload)
    if extension.vocabulary == _LEGACY_VOCABULARY and isinstance(payload, Mapping):
        field_name = payload.get("field_name")
        if isinstance(field_name, str):
            keys.append(field_name)
            keys.append(field_name.removeprefix("unsupported_"))
    return tuple(keys)


def _declared_adapter(
    extension: SecurityExtension,
    adapters: ExtensionAdapters | None,
) -> ExtensionAdapter | None:
    if not adapters:
        return None
    pair = (extension.vocabulary, extension.version)
    if pair in adapters:
        return adapters[pair]
    for key in _extension_key(extension):
        if key in adapters:
            return adapters[key]
    return None


def _run_extension_adapter(
    extension: SecurityExtension, adapter: ExtensionAdapter
) -> None:
    try:
        if isinstance(adapter, DeclaredExtensionAdapter):
            result = adapter.validate(extension)
        elif callable(adapter):
            result = adapter(extension)
        else:
            raise TypeError("declared extension adapter is not callable")
    except Exception as exc:
        raise ExchangeAdapterError(
            f"declared adapter rejected extension {extension.extension_id!r}: {exc}"
        ) from exc
    if result is False:
        raise ExchangeAdapterError(
            f"declared adapter rejected extension {extension.extension_id!r}"
        )


def _legacy_extension_value(extension: SecurityExtension) -> tuple[str, Any]:
    payload = thaw_json(extension.payload)
    if not isinstance(payload, Mapping):
        raise ExchangeAdapterError(
            f"legacy extension {extension.extension_id!r} payload is malformed"
        )
    field_name = payload.get("field_name")
    if not isinstance(field_name, str) or "value" not in payload:
        raise ExchangeAdapterError(
            f"legacy extension {extension.extension_id!r} payload is malformed"
        )
    return field_name, payload["value"]


def _exchange_extension(
    legacy_extensions: Sequence[SecurityExtension],
) -> SecurityExtension:
    values: dict[str, Any] = {}
    for extension in legacy_extensions:
        field_name, value = _legacy_extension_value(extension)
        if field_name in EXCHANGE_EXTENSION_FIELDS:
            if field_name in values:
                raise ExchangeAdapterError(
                    f"duplicate legacy extension field {field_name!r}"
                )
            values[field_name] = value
    missing = sorted(set(EXCHANGE_EXTENSION_FIELDS) - set(values))
    if missing:
        raise ExchangeAdapterError(
            "legacy declaration lacks exchange field(s): " + ", ".join(missing)
        )
    return SecurityExtension(
        extension_id=EXCHANGE_EXTENSION_ID,
        vocabulary=EXCHANGE_VOCABULARY,
        version=EXCHANGE_VOCABULARY_VERSION,
        required=True,
        payload={
            "schema_version": EXCHANGE_VOCABULARY_SCHEMA_VERSION,
            **values,
        },
    )


def _semantic_inputs(
    domain: str, extension: SecurityExtension, declaration: SecurityIR
) -> Mapping[str, Any]:
    payload = thaw_json(extension.payload)
    events = payload["events"]
    event_prefixes: Mapping[str, tuple[str, ...]] = {
        "withdrawals": (
            "withdrawal_",
            "balance_",
            "nonce_",
            "wallet_",
        ),
        "deposits": ("deposit_", "chain_reorg_"),
        "hsm": ("signing_", "wallet_"),
        "capabilities": ("capability_", "privileged_action"),
        "audit": ("audit_",),
        "ledger": ("balance_", "deposit_", "withdrawal_", "audit_"),
    }
    prefixes = event_prefixes[domain]
    relevant_events = [
        item
        for item in events
        if isinstance(item.get("event"), str)
        and item["event"].startswith(prefixes)
    ]
    relevant_policy_names: Mapping[str, frozenset[str]] = {
        "withdrawals": frozenset(
            {
                "authorization_required",
                "fresh_nonce_required",
                "sufficient_balance_required",
                "wallet_not_frozen_required",
            }
        ),
        "deposits": frozenset({"credit_after_finality_required"}),
        "hsm": frozenset({"wallet_not_frozen_required"}),
        "capabilities": frozenset(
            {"delegation_monotonicity", "revocation_enforced"}
        ),
        "audit": frozenset({"audit_required"}),
        "ledger": frozenset({"atomic_reservation", "audit_required"}),
    }
    policies = [
        thaw_json(item.attributes["legacy_record"])
        for item in declaration.policies
        if item.attributes.get("legacy_record", {}).get("name")
        in relevant_policy_names[domain]
    ]
    inputs: dict[str, Any] = {
        "events": relevant_events,
        "policies": policies,
    }
    if domain in {"withdrawals", "deposits", "hsm", "ledger"}:
        inputs["resources"] = [
            thaw_json(item.attributes["legacy_record"])
            for item in declaration.resources
            if item.attributes.get("legacy_collection") in {"wallets", "accounts"}
        ]
        inputs["assets"] = [
            thaw_json(item.attributes["legacy_record"])
            for item in declaration.assets
        ]
    if domain == "capabilities":
        inputs["capabilities"] = payload["capabilities"]
    if domain == "ledger":
        inputs["metadata"] = payload["metadata"]
    return inputs


def _normalize_declaration(
    declaration: SecurityIR, exchange_extension: SecurityExtension
) -> SecurityIR:
    resource_kinds = {
        "entities": "entity",
        "wallets": "wallet",
        "accounts": "account",
    }
    resources = tuple(
        replace(
            item,
            kind=exchange_term(
                "resource",
                resource_kinds[str(item.attributes["legacy_collection"])],
            ),
        )
        if item.attributes.get("legacy_collection") in resource_kinds
        else item
        for item in declaration.resources
    )
    policies = tuple(
        replace(
            item,
            name=exchange_term("policy", item.name),
            attributes={
                **thaw_json(item.attributes),
                "exchange_vocabulary": EXCHANGE_VOCABULARY_SCHEMA_VERSION,
            },
        )
        for item in declaration.policies
    )
    assumptions = tuple(
        replace(
            item,
            statement=EXCHANGE_ASSUMPTIONS.get(item.assumption_id, item.statement),
            attributes={
                **thaw_json(item.attributes),
                "exchange_vocabulary": EXCHANGE_VOCABULARY_SCHEMA_VERSION,
            },
        )
        for item in declaration.assumptions
    )
    interim = replace(
        declaration,
        resources=resources,
        policies=policies,
        assumptions=assumptions,
        extensions=(exchange_extension,),
    )
    claims: list[SecurityClaim] = []
    for item in interim.claims:
        domain = item.domain
        if domain not in EXCHANGE_DOMAINS:
            raise ExchangeAdapterError(
                f"claim {item.claim_id!r} is outside the exchange vocabulary: {domain!r}"
            )
        semantic_inputs = _semantic_inputs(domain, exchange_extension, interim)
        semantic_digest = hashlib.sha256(
            canonical_json_bytes(semantic_inputs)
        ).hexdigest()
        claims.append(
            replace(
                item,
                domain=exchange_term("domain", domain),
                attributes={
                    **thaw_json(item.attributes),
                    "exchange_vocabulary": EXCHANGE_VOCABULARY_SCHEMA_VERSION,
                    "semantic_input_sha256": semantic_digest,
                },
            )
        )
    return replace(interim, claims=tuple(claims))


def validate_exchange_security_ir(
    declaration: SecurityIR,
    *,
    extension_adapters: ExtensionAdapters | None = None,
) -> SecurityIR:
    """Validate exchange terms and fail closed for undeclared extensions."""

    if not isinstance(declaration, SecurityIR):
        raise ExchangeAdapterError("declaration must be a SecurityIR")
    declaration.validate()
    exchange_extensions = [
        item
        for item in declaration.extensions
        if item.vocabulary == EXCHANGE_VOCABULARY
    ]
    if len(exchange_extensions) != 1:
        raise ExchangeAdapterError(
            "exchange declarations require exactly one exchange extension"
        )
    try:
        validate_exchange_extension(exchange_extensions[0])
    except ExchangeVocabularyError as exc:
        raise ExchangeAdapterError(str(exc)) from exc

    for extension in declaration.extensions:
        if extension is exchange_extensions[0]:
            continue
        adapter = _declared_adapter(extension, extension_adapters)
        if adapter is None:
            raise ExchangeAdapterError(
                f"extension {extension.extension_id!r} has no declared adapter"
            )
        _run_extension_adapter(extension, adapter)

    for resource in declaration.resources:
        try:
            local_kind = parse_exchange_term(resource.kind, category="resource")
        except ExchangeVocabularyError as exc:
            raise ExchangeAdapterError(
                f"resource {resource.resource_id!r}: {exc}"
            ) from exc
        if local_kind not in EXCHANGE_RESOURCE_KINDS:
            raise ExchangeAdapterError(
                f"resource {resource.resource_id!r} has unknown exchange kind "
                f"{local_kind!r}"
            )
        if local_kind == "wallet":
            legacy_record = resource.attributes.get("legacy_record", {})
            status = legacy_record.get("status")
            if status is not None and status not in {
                "active",
                "disabled",
                "frozen",
                "retired",
                "rotating",
            }:
                raise ExchangeAdapterError(
                    f"wallet {resource.resource_id!r} has unsupported status {status!r}"
                )
    for policy in declaration.policies:
        try:
            local_name = parse_exchange_term(policy.name, category="policy")
        except ExchangeVocabularyError as exc:
            raise ExchangeAdapterError(
                f"policy {policy.policy_id!r}: {exc}"
            ) from exc
        # Custom policies remain representable only when explicitly marked in
        # their lossless legacy record.
        if (
            local_name not in EXCHANGE_POLICY_NAMES
            and not bool(policy.attributes.get("legacy_record", {}).get("custom"))
        ):
            raise ExchangeAdapterError(
                f"policy {policy.policy_id!r} uses unknown exchange policy "
                f"{local_name!r}"
            )
    for assumption in declaration.assumptions:
        legacy_value = assumption.attributes.get("legacy_value")
        is_custom = isinstance(legacy_value, Mapping) and bool(
            legacy_value.get("custom")
        )
        if (
            assumption.assumption_id not in EXCHANGE_ASSUMPTIONS
            and not is_custom
        ):
            raise ExchangeAdapterError(
                f"assumption {assumption.assumption_id!r} is not declared by "
                "the exchange vocabulary"
            )
    for claim in declaration.claims:
        try:
            local_domain = parse_exchange_term(claim.domain, category="domain")
        except ExchangeVocabularyError as exc:
            raise ExchangeAdapterError(
                f"claim {claim.claim_id!r}: {exc}"
            ) from exc
        if local_domain not in EXCHANGE_DOMAINS:
            raise ExchangeAdapterError(
                f"claim {claim.claim_id!r} has unknown exchange domain "
                f"{local_domain!r}"
            )
        expected_digest = hashlib.sha256(
            canonical_json_bytes(
                _semantic_inputs(
                    local_domain, exchange_extensions[0], declaration
                )
            )
        ).hexdigest()
        if claim.attributes.get("semantic_input_sha256") != expected_digest:
            raise ExchangeAdapterError(
                f"claim {claim.claim_id!r} is not bound to its current "
                "exchange semantic inputs"
            )
    return declaration


def adapt_exchange_security_ir(
    legacy: SecurityModelIR | Mapping[str, Any],
    *,
    extension_adapters: ExtensionAdapters | None = None,
) -> LegacyAdapterResult:
    """Adapt a legacy crypto-exchange model using the exchange vocabulary."""

    try:
        base = adapt_legacy_security_ir(legacy)
        owned = [
            item
            for item in base.declaration.extensions
            if item.vocabulary == _LEGACY_VOCABULARY
            and _legacy_extension_value(item)[0] in EXCHANGE_EXTENSION_FIELDS
        ]
        exchange_extension = _exchange_extension(owned)
        remaining = [
            item for item in base.declaration.extensions if item not in owned
        ]
        declaration = _normalize_declaration(
            replace(base.declaration, extensions=tuple(remaining)),
            exchange_extension,
        )
        declaration = replace(
            declaration,
            extensions=(exchange_extension, *remaining),
        )
        validate_exchange_security_ir(
            declaration, extension_adapters=extension_adapters
        )
    except ExchangeAdapterError:
        raise
    except (LegacyAdapterError, ExchangeVocabularyError, ValueError) as exc:
        raise ExchangeAdapterError(str(exc)) from exc
    return LegacyAdapterResult(
        declaration=declaration,
        verification_data=base.verification_data,
        diagnostics=base.diagnostics,
        legacy_schema_version=base.legacy_schema_version,
        adapter_version=EXCHANGE_ADAPTER_VERSION,
    )


def _legacy_extension(field_name: str, value: Any) -> SecurityExtension:
    digest = hashlib.sha256(field_name.encode("utf-8")).hexdigest()[:12]
    return SecurityExtension(
        extension_id=f"extension:legacy:{field_name}:{digest}",
        vocabulary=_LEGACY_VOCABULARY,
        version="v1",
        payload={"field_name": field_name, "value": value},
    )


def _denormalize_declaration(
    declaration: SecurityIR,
    *,
    extension_adapters: ExtensionAdapters | None,
) -> SecurityIR:
    validate_exchange_security_ir(
        declaration, extension_adapters=extension_adapters
    )
    exchange_extension = next(
        item
        for item in declaration.extensions
        if item.vocabulary == EXCHANGE_VOCABULARY
    )
    payload = thaw_json(exchange_extension.payload)
    extensions = [
        _legacy_extension(name, payload[name])
        for name in EXCHANGE_EXTENSION_FIELDS
    ]
    for extension in declaration.extensions:
        if extension is exchange_extension:
            continue
        # Legacy unknown-field extensions already carry the reversible value.
        if extension.vocabulary != _LEGACY_VOCABULARY:
            raise ExchangeAdapterError(
                f"declared extension {extension.extension_id!r} has no "
                "legacy serialization contract"
            )
        extensions.append(extension)
    resource_kinds = {
        "entities": "entity",
        "wallets": "wallet",
        "accounts": "account",
    }
    resources = tuple(
        replace(
            item,
            kind=(
                f"{resource_kinds[str(item.attributes['legacy_collection'])]}:"
                f"{item.attributes.get('legacy_record', {}).get('kind')}"
                if item.attributes.get("legacy_record", {}).get("kind")
                else resource_kinds[str(item.attributes["legacy_collection"])]
            ),
        )
        for item in declaration.resources
    )
    policies = tuple(
        replace(
            item,
            name=item.attributes["legacy_record"].get(
                "name", item.attributes["legacy_record"]["id"]
            ),
        )
        for item in declaration.policies
    )
    claims = tuple(
        replace(
            item,
            domain=item.attributes["legacy_record"]["domain"],
        )
        for item in declaration.claims
    )
    return replace(
        declaration,
        resources=resources,
        policies=policies,
        claims=claims,
        extensions=tuple(extensions),
    )


def to_legacy_exchange_security_ir(
    adapted: LegacyAdapterResult | SecurityIR,
    *,
    verification_data: LegacyVerificationData | None = None,
    extension_adapters: ExtensionAdapters | None = None,
    as_model: bool = False,
) -> dict[str, Any] | SecurityModelIR:
    """Reconstruct the exact legacy exchange declaration and run data."""

    if isinstance(adapted, LegacyAdapterResult):
        declaration = adapted.declaration
        run_data = verification_data or adapted.verification_data
        schema_version = adapted.legacy_schema_version
    elif isinstance(adapted, SecurityIR):
        declaration = adapted
        run_data = verification_data or LegacyVerificationData()
        schema_version = "security-model-ir/v1"
    else:
        raise TypeError("adapted must be LegacyAdapterResult or SecurityIR")
    denormalized = _denormalize_declaration(
        declaration, extension_adapters=extension_adapters
    )
    generic = LegacyAdapterResult(
        declaration=denormalized,
        verification_data=run_data,
        legacy_schema_version=schema_version,
    )
    try:
        return to_legacy_security_ir(generic, as_model=as_model)
    except LegacyAdapterError as exc:
        raise ExchangeAdapterError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class ExchangeSecurityAdapter:
    """Dependency-injectable facade for the exchange adapter."""

    extension_adapters: ExtensionAdapters | None = None
    version: str = EXCHANGE_ADAPTER_VERSION

    def __post_init__(self) -> None:
        if self.version != EXCHANGE_ADAPTER_VERSION:
            raise ExchangeAdapterError(
                f"unsupported exchange adapter version: {self.version!r}"
            )
        if self.extension_adapters is not None and not isinstance(
            self.extension_adapters, Mapping
        ):
            raise ExchangeAdapterError("extension_adapters must be a mapping")
        if self.extension_adapters is not None:
            object.__setattr__(
                self,
                "extension_adapters",
                MappingProxyType(dict(self.extension_adapters)),
            )

    def adapt(
        self, legacy: SecurityModelIR | Mapping[str, Any]
    ) -> LegacyAdapterResult:
        return adapt_exchange_security_ir(
            legacy, extension_adapters=self.extension_adapters
        )

    def validate(self, declaration: SecurityIR) -> SecurityIR:
        return validate_exchange_security_ir(
            declaration, extension_adapters=self.extension_adapters
        )

    def to_legacy(
        self,
        adapted: LegacyAdapterResult | SecurityIR,
        *,
        verification_data: LegacyVerificationData | None = None,
        as_model: bool = False,
    ) -> dict[str, Any] | SecurityModelIR:
        return to_legacy_exchange_security_ir(
            adapted,
            verification_data=verification_data,
            extension_adapters=self.extension_adapters,
            as_model=as_model,
        )


adapt_exchange_model = adapt_exchange_security_ir
adapt_legacy_exchange_security_ir = adapt_exchange_security_ir
from_legacy = adapt_exchange_security_ir
to_legacy = to_legacy_exchange_security_ir
to_legacy_exchange_ir = to_legacy_exchange_security_ir
ExchangeAdapter = ExchangeSecurityAdapter


__all__ = [
    "EXCHANGE_ADAPTER_VERSION",
    "DeclaredExtensionAdapter",
    "ExchangeAdapter",
    "ExchangeAdapterError",
    "ExchangeSecurityAdapter",
    "ExtensionAdapter",
    "ExtensionAdapters",
    "adapt_exchange_model",
    "adapt_exchange_security_ir",
    "adapt_legacy_exchange_security_ir",
    "from_legacy",
    "to_legacy",
    "to_legacy_exchange_ir",
    "to_legacy_exchange_security_ir",
    "validate_exchange_security_ir",
]
