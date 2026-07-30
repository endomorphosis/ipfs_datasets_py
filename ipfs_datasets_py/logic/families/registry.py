"""Canonical, side-effect-free logic-family registry.

This module contains data and validation only.  In particular, it does not
import backend registries, provider adapters, solver bindings, installers, or
process runners.  Consumers may therefore use :data:`DEFAULT_REGISTRY` during
discovery without changing the host environment.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Mapping
from types import MappingProxyType
from typing import Any, Final, TypeVar

from .models import (
    BoundednessDescriptor,
    BoundednessKind,
    EvidenceAuthority,
    EvidenceDescriptor,
    EvidenceKind,
    LogicFamilyDescriptor,
    LogicFragmentDescriptor,
    LogicOperationDescriptor,
    LogicPropertyDescriptor,
    ProviderCapabilityDescriptor,
    RuntimeDescriptor,
    RuntimeKind,
    SupportLevel,
    TAXONOMY_SCHEMA_VERSION,
    TranslationDescriptor,
    TranslationKind,
)


REGISTRY_VERSION: Final = "1.0.0"


class LogicFamilyRegistryError(ValueError):
    """Base error for invalid taxonomy registry operations."""


class DuplicateDescriptorError(LogicFamilyRegistryError):
    """Raised when a canonical descriptor identifier is reused."""


class AliasCollisionError(LogicFamilyRegistryError):
    """Raised when two families claim the same normalized lookup name."""


class SemanticEquivalenceError(LogicFamilyRegistryError):
    """Raised when semantic equivalence is present but was not declared."""


class UnknownDescriptorError(LogicFamilyRegistryError, KeyError):
    """Raised when a descriptor reference cannot be resolved."""


class InvalidCapabilityError(LogicFamilyRegistryError):
    """Raised when a provider capability contradicts the taxonomy."""


class FrozenRegistryError(LogicFamilyRegistryError):
    """Raised on attempted mutation of a frozen registry."""


_Descriptor = TypeVar("_Descriptor")
_ALIAS_SEPARATORS = re.compile(r"[^a-z0-9]+")


def normalize_family_name(value: str) -> str:
    """Normalize a family identifier or human alias for collision-safe lookup."""

    if not isinstance(value, str) or not value.strip():
        raise LogicFamilyRegistryError("family name must be a non-empty string")
    normalized = _ALIAS_SEPARATORS.sub("_", value.strip().casefold()).strip("_")
    if not normalized:
        raise LogicFamilyRegistryError(
            "family name must contain at least one alphanumeric character"
        )
    return normalized


def _mapping(values: Mapping[str, _Descriptor]) -> Mapping[str, _Descriptor]:
    return MappingProxyType(dict(sorted(values.items())))


class LogicFamilyRegistry:
    """Validated catalog of logic vocabulary and provider declarations.

    A registry is mutable while it is assembled and may then be frozen.
    Registration validates every reference immediately, so a successful call
    never leaves a partially valid registry behind.
    """

    schema_version: Final = TAXONOMY_SCHEMA_VERSION

    def __init__(
        self,
        *,
        fragments: Iterable[LogicFragmentDescriptor] = (),
        properties: Iterable[LogicPropertyDescriptor] = (),
        operations: Iterable[LogicOperationDescriptor] = (),
        runtimes: Iterable[RuntimeDescriptor] = (),
        evidence: Iterable[EvidenceDescriptor] = (),
        boundedness: Iterable[BoundednessDescriptor] = (),
        families: Iterable[LogicFamilyDescriptor] = (),
        translations: Iterable[TranslationDescriptor] = (),
        provider_capabilities: Iterable[ProviderCapabilityDescriptor] = (),
        version: str = REGISTRY_VERSION,
        frozen: bool = False,
    ) -> None:
        if not isinstance(version, str) or not version.strip():
            raise LogicFamilyRegistryError("registry version must be a non-empty string")
        self.version = version.strip()
        self._fragments: dict[str, LogicFragmentDescriptor] = {}
        self._properties: dict[str, LogicPropertyDescriptor] = {}
        self._operations: dict[str, LogicOperationDescriptor] = {}
        self._runtimes: dict[str, RuntimeDescriptor] = {}
        self._evidence: dict[str, EvidenceDescriptor] = {}
        self._boundedness: dict[str, BoundednessDescriptor] = {}
        self._families: dict[str, LogicFamilyDescriptor] = {}
        self._translations: dict[str, TranslationDescriptor] = {}
        self._provider_capabilities: dict[str, ProviderCapabilityDescriptor] = {}
        self._family_names: dict[str, str] = {}
        self._semantic_identities: dict[str, str] = {}
        self._frozen = False

        for descriptor in sorted(fragments, key=lambda item: item.fragment_id):
            self.register_fragment(descriptor)
        for descriptor in sorted(properties, key=lambda item: item.property_id):
            self.register_property(descriptor)
        for descriptor in sorted(operations, key=lambda item: item.operation_id):
            self.register_operation(descriptor)
        for descriptor in sorted(runtimes, key=lambda item: item.runtime_id):
            self.register_runtime(descriptor)
        for descriptor in sorted(evidence, key=lambda item: item.evidence_id):
            self.register_evidence(descriptor)
        for descriptor in sorted(
            boundedness, key=lambda item: item.boundedness_id
        ):
            self.register_boundedness(descriptor)
        for descriptor in sorted(families, key=lambda item: item.family_id):
            self.register_family(descriptor)
        for descriptor in sorted(
            translations, key=lambda item: item.translation_id
        ):
            self.register_translation(descriptor)
        for descriptor in sorted(
            provider_capabilities, key=lambda item: item.capability_id
        ):
            self.register_provider_capability(descriptor)
        if frozen:
            self.freeze()

    @property
    def frozen(self) -> bool:
        return self._frozen

    def freeze(self) -> "LogicFamilyRegistry":
        """Prevent further registration and return this registry."""

        self._frozen = True
        return self

    def _require_mutable(self) -> None:
        if self._frozen:
            raise FrozenRegistryError("logic-family registry is frozen")

    def _insert(
        self,
        target: dict[str, _Descriptor],
        descriptor_id: str,
        descriptor: _Descriptor,
        kind: str,
    ) -> None:
        self._require_mutable()
        if descriptor_id in target:
            raise DuplicateDescriptorError(
                f"{kind} {descriptor_id!r} is already registered"
            )
        target[descriptor_id] = descriptor

    def _require_ids(
        self,
        values: Iterable[str],
        target: Mapping[str, object],
        kind: str,
        owner: str,
    ) -> None:
        missing = sorted(set(values) - set(target))
        if missing:
            raise UnknownDescriptorError(
                f"{owner} references unknown {kind}: {', '.join(missing)}"
            )

    def register_fragment(
        self, descriptor: LogicFragmentDescriptor
    ) -> LogicFragmentDescriptor:
        if not isinstance(descriptor, LogicFragmentDescriptor):
            raise TypeError("descriptor must be a LogicFragmentDescriptor")
        self._insert(
            self._fragments, descriptor.fragment_id, descriptor, "fragment"
        )
        return descriptor

    def register_property(
        self, descriptor: LogicPropertyDescriptor
    ) -> LogicPropertyDescriptor:
        if not isinstance(descriptor, LogicPropertyDescriptor):
            raise TypeError("descriptor must be a LogicPropertyDescriptor")
        self._insert(
            self._properties, descriptor.property_id, descriptor, "property"
        )
        return descriptor

    def register_operation(
        self, descriptor: LogicOperationDescriptor
    ) -> LogicOperationDescriptor:
        if not isinstance(descriptor, LogicOperationDescriptor):
            raise TypeError("descriptor must be a LogicOperationDescriptor")
        self._require_ids(
            descriptor.property_ids,
            self._properties,
            "properties",
            f"operation {descriptor.operation_id!r}",
        )
        self._insert(
            self._operations, descriptor.operation_id, descriptor, "operation"
        )
        return descriptor

    def register_runtime(self, descriptor: RuntimeDescriptor) -> RuntimeDescriptor:
        if not isinstance(descriptor, RuntimeDescriptor):
            raise TypeError("descriptor must be a RuntimeDescriptor")
        self._insert(self._runtimes, descriptor.runtime_id, descriptor, "runtime")
        return descriptor

    def register_evidence(self, descriptor: EvidenceDescriptor) -> EvidenceDescriptor:
        if not isinstance(descriptor, EvidenceDescriptor):
            raise TypeError("descriptor must be an EvidenceDescriptor")
        self._insert(
            self._evidence, descriptor.evidence_id, descriptor, "evidence"
        )
        return descriptor

    def register_boundedness(
        self, descriptor: BoundednessDescriptor
    ) -> BoundednessDescriptor:
        if not isinstance(descriptor, BoundednessDescriptor):
            raise TypeError("descriptor must be a BoundednessDescriptor")
        self._require_ids(
            descriptor.sound_for_property_ids,
            self._properties,
            "properties",
            f"boundedness {descriptor.boundedness_id!r}",
        )
        self._insert(
            self._boundedness,
            descriptor.boundedness_id,
            descriptor,
            "boundedness",
        )
        return descriptor

    def register_family(
        self, descriptor: LogicFamilyDescriptor
    ) -> LogicFamilyDescriptor:
        if not isinstance(descriptor, LogicFamilyDescriptor):
            raise TypeError("descriptor must be a LogicFamilyDescriptor")
        self._require_mutable()
        if descriptor.family_id in self._families:
            raise DuplicateDescriptorError(
                f"family {descriptor.family_id!r} is already registered"
            )
        self._require_ids(
            descriptor.fragment_ids,
            self._fragments,
            "fragments",
            f"family {descriptor.family_id!r}",
        )
        self._require_ids(
            descriptor.property_ids,
            self._properties,
            "properties",
            f"family {descriptor.family_id!r}",
        )
        self._require_ids(
            descriptor.operation_ids,
            self._operations,
            "operations",
            f"family {descriptor.family_id!r}",
        )

        existing_semantic_family = self._semantic_identities.get(
            descriptor.semantic_identity
        )
        if descriptor.equivalent_to is not None:
            equivalent = self._families.get(descriptor.equivalent_to)
            if equivalent is None:
                raise UnknownDescriptorError(
                    f"family {descriptor.family_id!r} declares unknown equivalent "
                    f"family {descriptor.equivalent_to!r}"
                )
            if equivalent.semantic_identity != descriptor.semantic_identity:
                raise SemanticEquivalenceError(
                    f"family {descriptor.family_id!r} declares equivalence with "
                    f"{descriptor.equivalent_to!r} but their semantic identities differ"
                )
            if existing_semantic_family != descriptor.equivalent_to:
                raise SemanticEquivalenceError(
                    f"family {descriptor.family_id!r} must point to the canonical "
                    f"semantic family {existing_semantic_family!r}"
                )
        elif existing_semantic_family is not None:
            raise SemanticEquivalenceError(
                f"family {descriptor.family_id!r} silently duplicates the semantics "
                f"of {existing_semantic_family!r}; use an alias or explicitly set "
                "equivalent_to"
            )

        claimed_names = (descriptor.family_id, *descriptor.aliases)
        normalized_claims: set[str] = set()
        for claimed_name in claimed_names:
            normalized = normalize_family_name(claimed_name)
            if normalized in normalized_claims:
                raise AliasCollisionError(
                    f"family {descriptor.family_id!r} contains colliding aliases "
                    f"after normalization: {claimed_name!r}"
                )
            normalized_claims.add(normalized)
            owner = self._family_names.get(normalized)
            if owner is not None:
                raise AliasCollisionError(
                    f"family name {claimed_name!r} collides with registered family "
                    f"{owner!r}"
                )

        self._families[descriptor.family_id] = descriptor
        if existing_semantic_family is None:
            self._semantic_identities[
                descriptor.semantic_identity
            ] = descriptor.family_id
        for normalized in normalized_claims:
            self._family_names[normalized] = descriptor.family_id
        return descriptor

    def register_translation(
        self, descriptor: TranslationDescriptor
    ) -> TranslationDescriptor:
        if not isinstance(descriptor, TranslationDescriptor):
            raise TypeError("descriptor must be a TranslationDescriptor")
        owner = f"translation {descriptor.translation_id!r}"
        self._require_ids(
            (descriptor.source_family_id, descriptor.target_family_id),
            self._families,
            "families",
            owner,
        )
        self._require_ids(
            (*descriptor.preserves_property_ids, *descriptor.loses_property_ids),
            self._properties,
            "properties",
            owner,
        )
        self._require_ids(
            descriptor.evidence_ids, self._evidence, "evidence", owner
        )
        source = self._families[descriptor.source_family_id]
        source_properties = set(source.property_ids)
        outside_source = sorted(
            (
                set(descriptor.preserves_property_ids)
                | set(descriptor.loses_property_ids)
            )
            - source_properties
        )
        if outside_source:
            raise LogicFamilyRegistryError(
                f"{owner} classifies properties absent from source family "
                f"{source.family_id!r}: {', '.join(outside_source)}"
            )
        self._insert(
            self._translations,
            descriptor.translation_id,
            descriptor,
            "translation",
        )
        return descriptor

    def validate_provider_capability(
        self, descriptor: ProviderCapabilityDescriptor
    ) -> ProviderCapabilityDescriptor:
        """Validate a provider declaration without registering or executing it."""

        if not isinstance(descriptor, ProviderCapabilityDescriptor):
            raise TypeError("descriptor must be a ProviderCapabilityDescriptor")
        owner = f"provider capability {descriptor.capability_id!r}"
        self._require_ids(
            descriptor.runtime_ids, self._runtimes, "runtimes", owner
        )
        self._require_ids(
            descriptor.evidence_ids, self._evidence, "evidence", owner
        )
        self._require_ids(
            descriptor.boundedness_ids,
            self._boundedness,
            "boundedness descriptors",
            owner,
        )
        self._require_ids(
            descriptor.translation_ids,
            self._translations,
            "translations",
            owner,
        )
        for support in descriptor.family_support:
            family = self._families.get(support.family_id)
            if family is None:
                raise InvalidCapabilityError(
                    f"{owner} references unknown family {support.family_id!r}"
                )
            for values, allowed, kind in (
                (support.fragment_ids, family.fragment_ids, "fragments"),
                (support.property_ids, family.property_ids, "properties"),
                (support.operation_ids, family.operation_ids, "operations"),
            ):
                outside = sorted(set(values) - set(allowed))
                if outside:
                    raise InvalidCapabilityError(
                        f"{owner} claims {kind} outside family "
                        f"{family.family_id!r}: {', '.join(outside)}"
                    )
            if (
                family.declaration_only
                and support.support_level
                not in {SupportLevel.DECLARATION_ONLY, SupportLevel.UNSUPPORTED}
            ):
                raise InvalidCapabilityError(
                    f"{owner} cannot claim executable support for declaration-only "
                    f"family {family.family_id!r}"
                )
            for translation_id in support.translation_ids:
                if translation_id not in descriptor.translation_ids:
                    raise InvalidCapabilityError(
                        f"{owner} uses translation {translation_id!r} without "
                        "declaring it at provider scope"
                    )
                translation = self._translations[translation_id]
                if translation.source_family_id != family.family_id:
                    raise InvalidCapabilityError(
                        f"{owner} uses translation {translation_id!r} for family "
                        f"{family.family_id!r}, but its source is "
                        f"{translation.source_family_id!r}"
                    )
        return descriptor

    def register_provider_capability(
        self, descriptor: ProviderCapabilityDescriptor
    ) -> ProviderCapabilityDescriptor:
        self._require_mutable()
        self.validate_provider_capability(descriptor)
        self._insert(
            self._provider_capabilities,
            descriptor.capability_id,
            descriptor,
            "provider capability",
        )
        return descriptor

    @property
    def fragments(self) -> Mapping[str, LogicFragmentDescriptor]:
        return _mapping(self._fragments)

    @property
    def properties(self) -> Mapping[str, LogicPropertyDescriptor]:
        return _mapping(self._properties)

    @property
    def operations(self) -> Mapping[str, LogicOperationDescriptor]:
        return _mapping(self._operations)

    @property
    def runtimes(self) -> Mapping[str, RuntimeDescriptor]:
        return _mapping(self._runtimes)

    @property
    def evidence(self) -> Mapping[str, EvidenceDescriptor]:
        return _mapping(self._evidence)

    @property
    def boundedness(self) -> Mapping[str, BoundednessDescriptor]:
        return _mapping(self._boundedness)

    @property
    def families(self) -> Mapping[str, LogicFamilyDescriptor]:
        return _mapping(self._families)

    @property
    def translations(self) -> Mapping[str, TranslationDescriptor]:
        return _mapping(self._translations)

    @property
    def provider_capabilities(
        self,
    ) -> Mapping[str, ProviderCapabilityDescriptor]:
        return _mapping(self._provider_capabilities)

    def resolve(self, family_name: str) -> LogicFamilyDescriptor:
        """Resolve a canonical identifier or normalized alias."""

        normalized = normalize_family_name(family_name)
        family_id = self._family_names.get(normalized)
        if family_id is None:
            raise UnknownDescriptorError(f"unknown logic family {family_name!r}")
        return self._families[family_id]

    def family(self, family_name: str) -> LogicFamilyDescriptor:
        return self.resolve(family_name)

    def get_family(
        self, family_name: str, default: Any = None
    ) -> LogicFamilyDescriptor | Any:
        try:
            return self.resolve(family_name)
        except UnknownDescriptorError:
            return default

    def capability(
        self, provider_id: str, provider_version: str
    ) -> ProviderCapabilityDescriptor:
        capability_id = f"{provider_id}@{provider_version}"
        try:
            return self._provider_capabilities[capability_id]
        except KeyError as error:
            raise UnknownDescriptorError(
                f"unknown provider capability {capability_id!r}"
            ) from error

    def __contains__(self, family_name: object) -> bool:
        if not isinstance(family_name, str):
            return False
        try:
            self.resolve(family_name)
        except LogicFamilyRegistryError:
            return False
        return True

    def __iter__(self) -> Iterator[LogicFamilyDescriptor]:
        for family_id in sorted(self._families):
            yield self._families[family_id]

    def __len__(self) -> int:
        return len(self._families)

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic, JSON-compatible registry envelope."""

        return {
            "boundedness": [
                self._boundedness[key].to_dict()
                for key in sorted(self._boundedness)
            ],
            "evidence": [
                self._evidence[key].to_dict() for key in sorted(self._evidence)
            ],
            "families": [
                self._families[key].to_dict() for key in sorted(self._families)
            ],
            "fragments": [
                self._fragments[key].to_dict() for key in sorted(self._fragments)
            ],
            "operations": [
                self._operations[key].to_dict() for key in sorted(self._operations)
            ],
            "properties": [
                self._properties[key].to_dict() for key in sorted(self._properties)
            ],
            "provider_capabilities": [
                self._provider_capabilities[key].to_dict()
                for key in sorted(self._provider_capabilities)
            ],
            "registry_version": self.version,
            "runtimes": [
                self._runtimes[key].to_dict() for key in sorted(self._runtimes)
            ],
            "schema_version": self.schema_version,
            "translations": [
                self._translations[key].to_dict()
                for key in sorted(self._translations)
            ],
        }

    def to_json(self, *, indent: int | None = None) -> str:
        """Serialize with stable key and collection ordering."""

        separators = None if indent is not None else (",", ":")
        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            indent=indent,
            separators=separators,
            sort_keys=True,
        )

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any], *, frozen: bool = False
    ) -> "LogicFamilyRegistry":
        if value.get("schema_version") != TAXONOMY_SCHEMA_VERSION:
            raise LogicFamilyRegistryError(
                "unsupported or missing taxonomy schema_version"
            )
        return cls(
            fragments=(
                LogicFragmentDescriptor.from_dict(item)
                for item in value.get("fragments", ())
            ),
            properties=(
                LogicPropertyDescriptor.from_dict(item)
                for item in value.get("properties", ())
            ),
            operations=(
                LogicOperationDescriptor.from_dict(item)
                for item in value.get("operations", ())
            ),
            runtimes=(
                RuntimeDescriptor.from_dict(item)
                for item in value.get("runtimes", ())
            ),
            evidence=(
                EvidenceDescriptor.from_dict(item)
                for item in value.get("evidence", ())
            ),
            boundedness=(
                BoundednessDescriptor.from_dict(item)
                for item in value.get("boundedness", ())
            ),
            families=(
                LogicFamilyDescriptor.from_dict(item)
                for item in value.get("families", ())
            ),
            translations=(
                TranslationDescriptor.from_dict(item)
                for item in value.get("translations", ())
            ),
            provider_capabilities=(
                ProviderCapabilityDescriptor.from_dict(item)
                for item in value.get("provider_capabilities", ())
            ),
            version=value.get("registry_version", REGISTRY_VERSION),
            frozen=frozen,
        )

    @classmethod
    def from_json(
        cls, value: str, *, frozen: bool = False
    ) -> "LogicFamilyRegistry":
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError) as error:
            raise LogicFamilyRegistryError("registry JSON is malformed") from error
        if not isinstance(decoded, Mapping):
            raise LogicFamilyRegistryError("registry JSON must contain an object")
        return cls.from_dict(decoded, frozen=frozen)


def _fragment(
    fragment_id: str, name: str, *, aliases: tuple[str, ...] = ()
) -> LogicFragmentDescriptor:
    return LogicFragmentDescriptor(
        fragment_id=fragment_id,
        name=name,
        semantic_identity=f"logic-fragment/{fragment_id}/v1",
        aliases=aliases,
    )


def _property(
    property_id: str, name: str, *, aliases: tuple[str, ...] = ()
) -> LogicPropertyDescriptor:
    return LogicPropertyDescriptor(
        property_id=property_id,
        name=name,
        semantic_identity=f"logic-property/{property_id}/v1",
        aliases=aliases,
    )


def _operation(
    operation_id: str,
    name: str,
    property_ids: tuple[str, ...] = (),
    *,
    bounded: bool = False,
    aliases: tuple[str, ...] = (),
) -> LogicOperationDescriptor:
    return LogicOperationDescriptor(
        operation_id=operation_id,
        name=name,
        semantic_identity=f"logic-operation/{operation_id}/v1",
        property_ids=property_ids,
        requires_boundedness=bounded,
        aliases=aliases,
    )


def _family(
    family_id: str,
    name: str,
    *,
    aliases: tuple[str, ...] = (),
    fragments: tuple[str, ...] = (),
    properties: tuple[str, ...] = (),
    operations: tuple[str, ...] = (),
    declaration_only: bool = False,
) -> LogicFamilyDescriptor:
    return LogicFamilyDescriptor(
        family_id=family_id,
        name=name,
        semantic_identity=f"logic-family/{family_id}/v1",
        aliases=aliases,
        fragment_ids=fragments,
        property_ids=properties,
        operation_ids=operations,
        declaration_only=declaration_only,
    )


def build_default_registry(*, frozen: bool = True) -> LogicFamilyRegistry:
    """Build the canonical version-one taxonomy from inert declarations."""

    fragments = (
        _fragment("action_system", "Action systems"),
        _fragment("arithmetic", "Arithmetic"),
        _fragment("arrays", "Arrays and maps"),
        _fragment("branching_time", "Branching-time temporal logic", aliases=("CTL",)),
        _fragment("cfg", "Control-flow graphs"),
        _fragment("concurrency", "Concurrent composition"),
        _fragment("contracts", "Program contracts"),
        _fragment("ctl_star", "CTL-star", aliases=("CTL*",)),
        _fragment("datalog", "Datalog rules"),
        _fragment("datatypes", "Algebraic datatypes"),
        _fragment("deontic", "Deontic modalities"),
        _fragment("dynamic", "Dynamic logic"),
        _fragment("equality", "Equality"),
        _fragment("event_calculus", "Event calculus"),
        _fragment("finite_trace", "Finite-trace temporal logic", aliases=("LTLf",)),
        _fragment("heap", "Heap semantics"),
        _fragment("higher_order", "Higher-order quantification"),
        _fragment("horn_clauses", "Horn and constrained Horn clauses", aliases=("CHC",)),
        _fragment("hypertrace", "Hypertrace quantification"),
        _fragment("information_flow", "Information-flow labels"),
        _fragment("kripke", "Kripke structures"),
        _fragment("linear_time", "Linear-time temporal logic", aliases=("LTL",)),
        _fragment("metric_time", "Metric temporal logic", aliases=("MTL",)),
        _fragment("modal", "Modal operators"),
        _fragment("program_state", "Program state"),
        _fragment("propositional", "Propositional connectives"),
        _fragment("quantifiers", "First-order quantifiers"),
        _fragment("rely_guarantee", "Rely-guarantee reasoning"),
        _fragment("refinement", "Refinement relations"),
        _fragment("resources", "Resource and ownership algebras"),
        _fragment("separation", "Separating conjunction"),
        _fragment("session", "Session types"),
        _fragment("symbolic_crypto", "Symbolic cryptography"),
        _fragment("transition_system", "State-transition systems"),
    )
    properties = (
        _property("authentication", "Authentication"),
        _property("authorization", "Authorization decision"),
        _property("contract", "Contract satisfaction"),
        _property("data_race_freedom", "Data-race freedom"),
        _property("heap_safety", "Heap safety"),
        _property("hyperproperty", "Hyperproperty"),
        _property("invariant", "Invariant"),
        _property("liveness", "Liveness"),
        _property("noninterference", "Noninterference"),
        _property("reachability", "Reachability"),
        _property("refinement", "Refinement"),
        _property("safety", "Safety"),
        _property("satisfiability", "Satisfiability", aliases=("SAT",)),
        _property("secrecy", "Secrecy"),
        _property("termination", "Termination"),
        _property("theorem", "Theorem"),
        _property("trace_conformance", "Trace conformance"),
        _property("validity", "Validity"),
    )
    operations = (
        _operation("attest", "Attest checked evidence"),
        _operation("authorize", "Evaluate authorization", ("authorization",)),
        _operation(
            "check_hyperproperty",
            "Check hyperproperty",
            ("hyperproperty", "noninterference"),
            bounded=True,
        ),
        _operation(
            "check_refinement", "Check refinement", ("refinement",), bounded=True
        ),
        _operation(
            "check_satisfiability",
            "Check satisfiability",
            ("satisfiability",),
            aliases=("SAT",),
        ),
        _operation(
            "fixedpoint",
            "Compute logical fixed point",
            ("invariant", "reachability"),
        ),
        _operation(
            "generate_vc",
            "Generate verification conditions",
            ("contract", "safety", "termination"),
        ),
        _operation(
            "ic3",
            "IC3 invariant checking",
            ("invariant", "safety"),
            bounded=True,
        ),
        _operation("kernel_check", "Kernel-check a proof", ("theorem", "validity")),
        _operation(
            "model_check",
            "Model check",
            ("invariant", "liveness", "reachability", "safety"),
            bounded=True,
        ),
        _operation(
            "pdr",
            "Property-directed reachability",
            ("invariant", "reachability", "safety"),
            bounded=True,
        ),
        _operation("prove", "Prove", ("theorem", "validity")),
        _operation("reconstruct", "Reconstruct a proof", ("theorem", "validity")),
        _operation(
            "runtime_monitor",
            "Monitor a runtime trace",
            ("safety", "trace_conformance"),
            bounded=True,
        ),
        _operation("translate", "Translate between logic families"),
        _operation(
            "verify_protocol",
            "Verify a symbolic protocol",
            ("authentication", "secrecy"),
            bounded=True,
        ),
    )
    runtimes = (
        RuntimeDescriptor(
            "declaration_only",
            "Declaration only",
            RuntimeKind.DECLARATION_ONLY,
            requires_isolation=False,
            deterministic=True,
        ),
        RuntimeDescriptor(
            "in_process",
            "In-process pure library",
            RuntimeKind.IN_PROCESS,
            requires_isolation=False,
        ),
        RuntimeDescriptor("jvm_process", "Bounded JVM process", RuntimeKind.JVM),
        RuntimeDescriptor(
            "native_process", "Bounded native process", RuntimeKind.NATIVE_PROCESS
        ),
        RuntimeDescriptor("ocaml_process", "Bounded OCaml process", RuntimeKind.OCAML),
        RuntimeDescriptor(
            "remote_service", "Remote service", RuntimeKind.REMOTE_SERVICE
        ),
        RuntimeDescriptor("wasm_sandbox", "WASM sandbox", RuntimeKind.WASM),
    )
    evidence = (
        EvidenceDescriptor(
            "attestation",
            "Evidence attestation",
            EvidenceKind.ATTESTATION,
            EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            machine_checkable=True,
        ),
        EvidenceDescriptor(
            "candidate",
            "Untrusted candidate",
            EvidenceKind.CANDIDATE,
            EvidenceAuthority.ADVISORY,
        ),
        EvidenceDescriptor(
            "checked_proof",
            "Checked proof",
            EvidenceKind.CHECKED_PROOF,
            EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            machine_checkable=True,
        ),
        EvidenceDescriptor(
            "counterexample",
            "Counterexample",
            EvidenceKind.COUNTEREXAMPLE,
            EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            machine_checkable=True,
        ),
        EvidenceDescriptor(
            "declaration",
            "Capability declaration",
            EvidenceKind.DECLARATION,
            EvidenceAuthority.NONE,
        ),
        EvidenceDescriptor(
            "kernel_checked_proof",
            "Kernel-checked proof",
            EvidenceKind.KERNEL_CHECKED_PROOF,
            EvidenceAuthority.AUTHORITATIVE,
            machine_checkable=True,
        ),
        EvidenceDescriptor(
            "model",
            "Satisfying model",
            EvidenceKind.MODEL,
            EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            machine_checkable=True,
        ),
        EvidenceDescriptor(
            "monitor_verdict",
            "Runtime monitor verdict",
            EvidenceKind.MONITOR_VERDICT,
            EvidenceAuthority.BOUNDED,
            machine_checkable=True,
        ),
        EvidenceDescriptor(
            "policy_decision",
            "Policy decision",
            EvidenceKind.POLICY_DECISION,
            EvidenceAuthority.BOUNDED,
            machine_checkable=True,
        ),
        EvidenceDescriptor(
            "proof_certificate",
            "Proof certificate",
            EvidenceKind.PROOF_CERTIFICATE,
            EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            machine_checkable=True,
        ),
        EvidenceDescriptor(
            "trace",
            "Execution trace",
            EvidenceKind.TRACE,
            EvidenceAuthority.BOUNDED,
            machine_checkable=True,
        ),
        EvidenceDescriptor(
            "unsat_core",
            "Unsatisfiable core",
            EvidenceKind.UNSAT_CORE,
            EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            machine_checkable=True,
        ),
    )
    boundedness = (
        BoundednessDescriptor(
            "finite_domain",
            "Finite domain",
            BoundednessKind.FINITE_DOMAIN,
            limit_names=("domain_size",),
            sound_for_property_ids=("satisfiability",),
        ),
        BoundednessDescriptor(
            "finite_trace",
            "Finite trace",
            BoundednessKind.FINITE_TRACE,
            limit_names=("trace_length",),
            sound_for_property_ids=("trace_conformance",),
        ),
        BoundednessDescriptor(
            "resource_bounded",
            "Resource bounded",
            BoundednessKind.RESOURCE_BOUNDED,
            limit_names=(
                "max_memory_bytes",
                "max_output_bytes",
                "max_steps",
                "timeout_ms",
            ),
        ),
        BoundednessDescriptor(
            "step_bounded",
            "Step bounded",
            BoundednessKind.STEP_BOUNDED,
            limit_names=("max_steps",),
            sound_for_property_ids=("reachability",),
        ),
        BoundednessDescriptor(
            "unbounded",
            "Unbounded semantics",
            BoundednessKind.UNBOUNDED,
        ),
    )
    families = (
        _family(
            "authorization",
            "Authorization logic",
            aliases=("SecPAL", "policy_logic"),
            fragments=("datalog", "deontic"),
            properties=("authorization",),
            operations=("authorize", "translate"),
        ),
        _family(
            "concurrency",
            "Concurrency logic",
            fragments=("concurrency", "rely_guarantee", "session"),
            properties=("data_race_freedom", "refinement", "safety"),
            operations=("check_refinement", "model_check", "prove", "translate"),
        ),
        _family(
            "cryptographic_protocol",
            "Symbolic cryptographic protocol logic",
            aliases=("protocol_logic",),
            fragments=("symbolic_crypto", "transition_system"),
            properties=("authentication", "secrecy"),
            operations=("translate", "verify_protocol"),
        ),
        _family(
            "datalog",
            "Datalog",
            fragments=("datalog", "horn_clauses"),
            properties=("authorization", "reachability", "satisfiability"),
            operations=("authorize", "fixedpoint", "translate"),
        ),
        _family(
            "dcec",
            "Deontic cognitive event calculus",
            fragments=("deontic", "event_calculus", "modal", "quantifiers"),
            properties=("theorem", "validity"),
            operations=("prove", "translate"),
        ),
        _family(
            "deontic",
            "Deontic logic",
            fragments=("deontic", "modal", "propositional"),
            properties=("satisfiability", "theorem", "validity"),
            operations=("check_satisfiability", "prove", "translate"),
        ),
        _family(
            "event_calculus",
            "Event calculus",
            fragments=("event_calculus", "quantifiers", "transition_system"),
            properties=("invariant", "reachability", "theorem"),
            operations=("model_check", "prove", "translate"),
        ),
        _family(
            "first_order",
            "First-order logic",
            aliases=("FOL", "predicate_logic"),
            fragments=(
                "arithmetic",
                "datatypes",
                "equality",
                "propositional",
                "quantifiers",
            ),
            properties=("satisfiability", "theorem", "validity"),
            operations=("check_satisfiability", "prove", "translate"),
        ),
        _family(
            "frame_logic",
            "Frame logic",
            aliases=("FLogic", "F-logic"),
            fragments=("modal", "propositional", "resources"),
            properties=("satisfiability", "theorem", "validity"),
            operations=("check_satisfiability", "prove", "translate"),
        ),
        _family(
            "higher_order",
            "Higher-order logic",
            aliases=("HOL",),
            fragments=("higher_order", "propositional", "quantifiers"),
            properties=("theorem", "validity"),
            operations=("kernel_check", "prove", "reconstruct", "translate"),
        ),
        _family(
            "horn_chc",
            "Horn and constrained Horn clauses",
            aliases=("CHC", "Horn", "constrained_horn_clauses"),
            fragments=("arithmetic", "horn_clauses", "quantifiers"),
            properties=("invariant", "reachability", "safety", "satisfiability"),
            operations=(
                "check_satisfiability",
                "fixedpoint",
                "ic3",
                "pdr",
                "translate",
            ),
        ),
        _family(
            "hyperproperty",
            "Hyperproperty logic",
            aliases=("HyperLTL",),
            fragments=("hypertrace", "information_flow", "linear_time"),
            properties=("hyperproperty", "noninterference"),
            operations=("check_hyperproperty", "translate"),
        ),
        _family(
            "modal",
            "Modal logic",
            fragments=("kripke", "modal", "propositional"),
            properties=("satisfiability", "theorem", "validity"),
            operations=("check_satisfiability", "model_check", "prove", "translate"),
        ),
        _family(
            "mu_calculus",
            "Modal mu-calculus",
            fragments=("branching_time", "modal"),
            properties=("invariant", "liveness", "safety"),
            declaration_only=True,
        ),
        _family(
            "program",
            "Program and dynamic logic",
            aliases=("dynamic_logic", "hoare_logic"),
            fragments=("cfg", "contracts", "dynamic", "program_state"),
            properties=("contract", "safety", "termination"),
            operations=("generate_vc", "prove", "translate"),
        ),
        _family(
            "propositional",
            "Propositional logic",
            aliases=("PL", "Boolean_logic"),
            fragments=("propositional",),
            properties=("satisfiability", "theorem", "validity"),
            operations=("check_satisfiability", "prove", "translate"),
        ),
        _family(
            "refinement",
            "Refinement logic",
            fragments=("refinement", "transition_system"),
            properties=("refinement", "safety"),
            operations=("check_refinement", "prove", "translate"),
        ),
        _family(
            "separation_logic",
            "Separation and resource logic",
            aliases=("separation", "resource_logic"),
            fragments=("heap", "resources", "separation"),
            properties=("heap_safety", "safety"),
            operations=("generate_vc", "prove", "translate"),
        ),
        _family(
            "tdfol",
            "Temporal deontic first-order logic",
            fragments=(
                "deontic",
                "linear_time",
                "modal",
                "propositional",
                "quantifiers",
            ),
            properties=("liveness", "safety", "theorem", "validity"),
            operations=("prove", "translate"),
        ),
        _family(
            "temporal",
            "Temporal logic",
            aliases=("LTL", "LTLf", "MTL", "CTL"),
            fragments=(
                "branching_time",
                "ctl_star",
                "finite_trace",
                "linear_time",
                "metric_time",
            ),
            properties=(
                "invariant",
                "liveness",
                "reachability",
                "safety",
                "trace_conformance",
            ),
            operations=("model_check", "runtime_monitor", "translate"),
        ),
        _family(
            "transition_system",
            "State-transition and action-system logic",
            aliases=("state_transition", "kripke_structure"),
            fragments=("action_system", "kripke", "transition_system"),
            properties=("invariant", "liveness", "reachability", "safety"),
            operations=("ic3", "model_check", "pdr", "translate"),
        ),
    )

    registry = LogicFamilyRegistry(
        fragments=fragments,
        properties=properties,
        operations=operations,
        runtimes=runtimes,
        evidence=evidence,
        boundedness=boundedness,
        families=families,
    )
    registry.register_translation(
        TranslationDescriptor(
            "datalog_to_horn_chc",
            "datalog",
            "horn_chc",
            TranslationKind.LOSSLESS,
            preserves_property_ids=(
                "authorization",
                "reachability",
                "satisfiability",
            ),
            evidence_ids=("proof_certificate",),
        )
    )
    registry.register_translation(
        TranslationDescriptor(
            "propositional_to_first_order",
            "propositional",
            "first_order",
            TranslationKind.LOSSLESS,
            preserves_property_ids=("satisfiability", "theorem", "validity"),
            evidence_ids=("proof_certificate",),
        )
    )
    return registry.freeze() if frozen else registry


DEFAULT_REGISTRY: Final = build_default_registry()
CANONICAL_REGISTRY: Final = DEFAULT_REGISTRY


__all__ = [
    "AliasCollisionError",
    "CANONICAL_REGISTRY",
    "DEFAULT_REGISTRY",
    "DuplicateDescriptorError",
    "FrozenRegistryError",
    "InvalidCapabilityError",
    "LogicFamilyRegistry",
    "LogicFamilyRegistryError",
    "REGISTRY_VERSION",
    "SemanticEquivalenceError",
    "UnknownDescriptorError",
    "build_default_registry",
    "normalize_family_name",
]
