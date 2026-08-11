"""Provider-capability schemas and the canonical baseline catalog.

``ProviderCapabilityCatalog@1`` is a side-effect-free join of:

* exact executable-matrix provider IDs and reviewed aliases;
* advisory provider lanes with hard authority ceilings;
* baseline family/fragment support descriptors validated against
  :mod:`ipfs_datasets_py.logic.families.registry`; and
* an explicit open extension point for the LFP-040 generated closure.

Presence of a descriptor never claims that a binary is installed, that a
process can run, or that a proof has been produced.  Availability and proof
remain separate axes owned by explicit probes and evidence gates.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.registry import (
    EXECUTABLE_PROVIDER_ALIASES,
    EXECUTABLE_PROVIDER_IDS,
    EXECUTABLE_PROVIDER_MATRIX,
    EXECUTABLE_PROVIDER_MATRIX_INTERFACE,
    ProviderMatrixEntry,
)

from .models import (
    DESCRIPTOR_VERSION,
    EvidenceAuthority,
    FamilySupportDescriptor,
    ProviderCapabilityDescriptor,
    SupportLevel,
    TaxonomyError,
    _enum,
    _identifier,
    _strings,
    _text,
    _version,
)
from .registry import (
    BASELINE_FAMILY_IDS,
    DECLARATION_ONLY_FAMILY_IDS,
    DEFAULT_REGISTRY,
    LogicFamilyRegistry,
    NON_FAMILY_PROFILE_LABELS,
    PLANNED_EXTENSION_FAMILY_IDS,
    REGISTRY_INTERFACE,
    build_default_registry,
)


CATALOG_INTERFACE: Final = "ProviderCapabilityCatalog@1"
CATALOG_SCHEMA_VERSION: Final = "logic-family-provider-capability-catalog/v1"
CATALOG_MODULE_VERSION: Final = "1.0.0"
PROVIDER_ENTRY_SCHEMA: Final = "logic-family-provider-capability-entry/v1"
BASELINE_SOURCE: Final = "baseline"
GENERATED_CLOSURE_TASK: Final = "LFP-040"
GENERATED_CLOSURE_SOURCE: Final = "lfp040_generated_closure"

# Baseline provider version for inert declarations (not a live package version).
BASELINE_PROVIDER_VERSION: Final = "baseline-v1"

# Exact executable-matrix provider IDs (closed set; order matches matrix).
EXECUTABLE_MATRIX_PROVIDER_IDS: Final[tuple[str, ...]] = tuple(EXECUTABLE_PROVIDER_IDS)

# Reviewed dual-read aliases for executable-matrix providers.
REVIEWED_EXECUTABLE_PROVIDER_ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    dict(EXECUTABLE_PROVIDER_ALIASES)
)

# Advisory providers are outside the executable proof matrix.
ADVISORY_PROVIDER_IDS: Final[frozenset[str]] = frozenset({"ergoai", "hammer", "symbolicai"})

# Full baseline provider ID set (matrix + reviewed advisory lanes).
BASELINE_PROVIDER_IDS: Final[frozenset[str]] = frozenset(
    {
        *EXECUTABLE_MATRIX_PROVIDER_IDS,
        "ergoai",
        "symbolicai",
    }
)

# Hard authority ceilings for advisory lanes (cannot be inflated by presence).
ADVISORY_AUTHORITY_CEILINGS: Final[Mapping[str, EvidenceAuthority]] = MappingProxyType(
    {
        "ergoai": EvidenceAuthority.ADVISORY,
        "hammer": EvidenceAuthority.ADVISORY,
        "symbolicai": EvidenceAuthority.ADVISORY,
    }
)

# Authority ranks used to enforce hard ceilings (higher = stronger).
_AUTHORITY_RANK: Final[dict[EvidenceAuthority, int]] = {
    EvidenceAuthority.AUTHORITATIVE: 4,
    EvidenceAuthority.INDEPENDENTLY_CHECKABLE: 3,
    EvidenceAuthority.BOUNDED: 2,
    EvidenceAuthority.ADVISORY: 1,
    EvidenceAuthority.NONE: 0,
}


class ProviderCatalogError(TaxonomyError):
    """Raised when a provider-capability catalog entry is invalid."""


class ProviderCatalogAuthorityError(ProviderCatalogError):
    """Raised when a descriptor exceeds its hard authority ceiling."""


class ProviderCatalogDriftError(ProviderCatalogError):
    """Raised when free-form family or provider drift is detected."""


class ProviderAvailabilityPosture(str, Enum):
    """Static availability posture — never a live probe result."""

    DECLARED = "declared"
    NOT_DECLARED = "not_declared"
    ADVISORY_ONLY = "advisory_only"
    UNKNOWN = "unknown"


class ProviderCatalogSource(str, Enum):
    """Whether a descriptor belongs to the baseline or a later generated closure."""

    BASELINE = BASELINE_SOURCE
    GENERATED_CLOSURE = GENERATED_CLOSURE_SOURCE


def authority_rank(authority: EvidenceAuthority | str) -> int:
    """Return the comparable rank of an evidence authority."""

    resolved = _enum(authority, EvidenceAuthority, "authority")
    return _AUTHORITY_RANK[resolved]


def authority_at_most(
    claimed: EvidenceAuthority | str,
    ceiling: EvidenceAuthority | str,
) -> bool:
    """Return True when *claimed* does not exceed *ceiling*."""

    return authority_rank(claimed) <= authority_rank(ceiling)


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ProviderCatalogError(f"{field_name} must be a boolean")
    return value


@dataclass(frozen=True, slots=True)
class ProviderCapabilityEntry:
    """One versioned, inert provider-capability baseline descriptor.

    Construction never probes PATH, imports a solver, installs a package, or
    starts a process.  ``availability_posture`` is a declaration only.
    """

    provider_id: str
    provider_version: str
    authority_ceiling: EvidenceAuthority
    family_support: tuple[FamilySupportDescriptor, ...]
    aliases: tuple[str, ...] = ()
    runtime_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    boundedness_ids: tuple[str, ...] = ()
    translation_ids: tuple[str, ...] = ()
    deterministic: bool | None = None
    in_executable_matrix: bool = False
    advisory: bool = False
    availability_posture: ProviderAvailabilityPosture = (
        ProviderAvailabilityPosture.DECLARED
    )
    catalog_source: ProviderCatalogSource = ProviderCatalogSource.BASELINE
    notes: str = ""
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    version: str = DESCRIPTOR_VERSION

    schema_version: ClassVar[str] = PROVIDER_ENTRY_SCHEMA
    interface: ClassVar[str] = CATALOG_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "provider_id", _identifier(self.provider_id, "provider_id")
        )
        object.__setattr__(
            self,
            "provider_version",
            _version(self.provider_version, "provider_version"),
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _enum(self.authority_ceiling, EvidenceAuthority, "authority_ceiling"),
        )
        object.__setattr__(self, "version", _version(self.version))
        object.__setattr__(
            self, "aliases", _strings(self.aliases, "aliases")
        )
        for field_name in (
            "runtime_ids",
            "evidence_ids",
            "boundedness_ids",
            "translation_ids",
        ):
            object.__setattr__(
                self,
                field_name,
                _strings(getattr(self, field_name), field_name, identifiers=True),
            )
        object.__setattr__(
            self, "in_executable_matrix", _bool(self.in_executable_matrix, "in_executable_matrix")
        )
        object.__setattr__(self, "advisory", _bool(self.advisory, "advisory"))
        object.__setattr__(
            self,
            "availability_posture",
            _enum(
                self.availability_posture,
                ProviderAvailabilityPosture,
                "availability_posture",
            ),
        )
        object.__setattr__(
            self,
            "catalog_source",
            _enum(self.catalog_source, ProviderCatalogSource, "catalog_source"),
        )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes") if self.notes else ""
        )
        if self.deterministic is not None and not isinstance(self.deterministic, bool):
            raise ProviderCatalogError("deterministic must be a boolean or None")

        if isinstance(self.family_support, (str, bytes, bytearray)) or not isinstance(
            self.family_support, Sequence
        ):
            raise ProviderCatalogError(
                "family_support must be a sequence of FamilySupportDescriptor values"
            )
        support = tuple(
            item
            if isinstance(item, FamilySupportDescriptor)
            else FamilySupportDescriptor.from_dict(item)
            for item in self.family_support
        )
        support = tuple(sorted(support, key=lambda item: item.family_id))
        family_ids = tuple(item.family_id for item in support)
        if len(set(family_ids)) != len(family_ids):
            raise ProviderCatalogError(
                "family_support must declare each family at most once"
            )
        # Reject profile-label promotion before free-form family drift.
        profile_collisions = sorted(
            set(family_ids) & set(NON_FAMILY_PROFILE_LABELS)
        )
        if profile_collisions:
            raise ProviderCatalogDriftError(
                f"provider {self.provider_id!r} treats non-family profile labels "
                f"as families: {', '.join(profile_collisions)}"
            )
        unknown_families = sorted(set(family_ids) - set(BASELINE_FAMILY_IDS))
        if unknown_families:
            raise ProviderCatalogDriftError(
                f"provider {self.provider_id!r} references families outside the "
                f"baseline catalog: {', '.join(unknown_families)}"
            )
        object.__setattr__(self, "family_support", support)

        raw_metadata: object = self.metadata
        if isinstance(raw_metadata, Mapping):
            raw_metadata = tuple(raw_metadata.items())
        if (
            isinstance(raw_metadata, (str, bytes, bytearray))
            or not isinstance(raw_metadata, Sequence)
        ):
            raise ProviderCatalogError(
                "metadata must be a mapping or key/value sequence"
            )
        metadata: list[tuple[str, str]] = []
        for item in raw_metadata:
            if (
                not isinstance(item, Sequence)
                or isinstance(item, (str, bytes, bytearray))
                or len(item) != 2
            ):
                raise ProviderCatalogError("metadata entries must be key/value pairs")
            key = _identifier(item[0], "metadata key")
            metadata.append((key, _text(item[1], f"metadata[{key}]")))
        if len({key for key, _ in metadata}) != len(metadata):
            raise ProviderCatalogError("metadata must not contain duplicate keys")
        # Always record authority ceiling and catalog source in metadata.
        meta_map = {key: value for key, value in metadata}
        meta_map["authority_ceiling"] = self.authority_ceiling.value
        meta_map["catalog_source"] = self.catalog_source.value
        meta_map["in_executable_matrix"] = (
            "true" if self.in_executable_matrix else "false"
        )
        meta_map["advisory"] = "true" if self.advisory else "false"
        meta_map["availability_posture"] = self.availability_posture.value
        object.__setattr__(
            self, "metadata", tuple(sorted(meta_map.items()))
        )

        # Hard authority ceilings for advisory providers.
        if self.provider_id in ADVISORY_AUTHORITY_CEILINGS:
            hard_ceiling = ADVISORY_AUTHORITY_CEILINGS[self.provider_id]
            if not authority_at_most(self.authority_ceiling, hard_ceiling):
                raise ProviderCatalogAuthorityError(
                    f"advisory provider {self.provider_id!r} authority_ceiling "
                    f"{self.authority_ceiling.value!r} exceeds hard ceiling "
                    f"{hard_ceiling.value!r}"
                )
            if not self.advisory:
                raise ProviderCatalogAuthorityError(
                    f"provider {self.provider_id!r} must be marked advisory"
                )
        if self.advisory and not authority_at_most(
            self.authority_ceiling, EvidenceAuthority.ADVISORY
        ):
            raise ProviderCatalogAuthorityError(
                f"advisory provider {self.provider_id!r} cannot claim authority "
                f"above advisory; got {self.authority_ceiling.value!r}"
            )
        if self.advisory and self.evidence_ids:
            forbidden = {
                "kernel_checked_proof",
                "checked_proof",
                "proof_certificate",
                "attestation",
            }
            claimed = forbidden & set(self.evidence_ids)
            if claimed:
                raise ProviderCatalogAuthorityError(
                    f"advisory provider {self.provider_id!r} cannot claim "
                    f"authoritative evidence kinds: {', '.join(sorted(claimed))}"
                )

        # Executable-matrix membership is closed.
        if self.in_executable_matrix and self.provider_id not in set(
            EXECUTABLE_MATRIX_PROVIDER_IDS
        ):
            raise ProviderCatalogDriftError(
                f"provider {self.provider_id!r} is not an executable-matrix ID"
            )
        if (
            self.provider_id in set(EXECUTABLE_MATRIX_PROVIDER_IDS)
            and self.catalog_source is ProviderCatalogSource.BASELINE
            and not self.in_executable_matrix
            and self.provider_id not in ADVISORY_PROVIDER_IDS
        ):
            raise ProviderCatalogDriftError(
                f"matrix provider {self.provider_id!r} must set "
                "in_executable_matrix=True in the baseline catalog"
            )

    @property
    def capability_id(self) -> str:
        return f"{self.provider_id}@{self.provider_version}"

    @property
    def is_baseline(self) -> bool:
        return self.catalog_source is ProviderCatalogSource.BASELINE

    @property
    def is_generated_closure(self) -> bool:
        return self.catalog_source is ProviderCatalogSource.GENERATED_CLOSURE

    def to_capability_descriptor(self) -> ProviderCapabilityDescriptor:
        """Project this entry into a taxonomy provider-capability descriptor."""

        return ProviderCapabilityDescriptor(
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            family_support=self.family_support,
            runtime_ids=self.runtime_ids,
            evidence_ids=self.evidence_ids,
            boundedness_ids=self.boundedness_ids,
            translation_ids=self.translation_ids,
            deterministic=self.deterministic,
            metadata=dict(self.metadata),
            version=self.version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "advisory": self.advisory,
            "aliases": list(self.aliases),
            "authority_ceiling": self.authority_ceiling.value,
            "availability_posture": self.availability_posture.value,
            "boundedness_ids": list(self.boundedness_ids),
            "catalog_source": self.catalog_source.value,
            "deterministic": self.deterministic,
            "evidence_ids": list(self.evidence_ids),
            "family_support": [item.to_dict() for item in self.family_support],
            "in_executable_matrix": self.in_executable_matrix,
            "interface": self.interface,
            "metadata": {key: value for key, value in self.metadata},
            "notes": self.notes,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "runtime_ids": list(self.runtime_ids),
            "schema_version": self.schema_version,
            "translation_ids": list(self.translation_ids),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderCapabilityEntry":
        return cls(
            provider_id=value["provider_id"],
            provider_version=value["provider_version"],
            authority_ceiling=value["authority_ceiling"],
            family_support=tuple(
                FamilySupportDescriptor.from_dict(item)
                for item in value.get("family_support", ())
            ),
            aliases=tuple(value.get("aliases", ())),
            runtime_ids=tuple(value.get("runtime_ids", ())),
            evidence_ids=tuple(value.get("evidence_ids", ())),
            boundedness_ids=tuple(value.get("boundedness_ids", ())),
            translation_ids=tuple(value.get("translation_ids", ())),
            deterministic=value.get("deterministic"),
            in_executable_matrix=bool(value.get("in_executable_matrix", False)),
            advisory=bool(value.get("advisory", False)),
            availability_posture=value.get(
                "availability_posture", ProviderAvailabilityPosture.DECLARED.value
            ),
            catalog_source=value.get(
                "catalog_source", ProviderCatalogSource.BASELINE.value
            ),
            notes=value.get("notes", ""),
            metadata=value.get("metadata", {}),
            version=value.get("version", DESCRIPTOR_VERSION),
        )


def _support(
    family_id: str,
    level: SupportLevel | str = SupportLevel.NATIVE,
    *,
    fragments: Sequence[str] = (),
    properties: Sequence[str] = (),
    operations: Sequence[str] = (),
    notes: str = "",
) -> FamilySupportDescriptor:
    return FamilySupportDescriptor(
        family_id=family_id,
        support_level=level,
        fragment_ids=tuple(fragments),
        property_ids=tuple(properties),
        operation_ids=tuple(operations),
        notes=notes,
    )


def _entry(
    provider_id: str,
    *,
    authority_ceiling: EvidenceAuthority | str,
    family_support: Sequence[FamilySupportDescriptor],
    aliases: Sequence[str] = (),
    runtime_ids: Sequence[str] = (),
    evidence_ids: Sequence[str] = (),
    boundedness_ids: Sequence[str] = (),
    deterministic: bool | None = True,
    in_executable_matrix: bool = True,
    advisory: bool = False,
    availability_posture: ProviderAvailabilityPosture | str = (
        ProviderAvailabilityPosture.DECLARED
    ),
    notes: str = "",
    metadata: Mapping[str, str] | None = None,
) -> ProviderCapabilityEntry:
    return ProviderCapabilityEntry(
        provider_id=provider_id,
        provider_version=BASELINE_PROVIDER_VERSION,
        authority_ceiling=authority_ceiling,
        family_support=tuple(family_support),
        aliases=tuple(aliases),
        runtime_ids=tuple(runtime_ids),
        evidence_ids=tuple(evidence_ids),
        boundedness_ids=tuple(boundedness_ids),
        deterministic=deterministic,
        in_executable_matrix=in_executable_matrix,
        advisory=advisory,
        availability_posture=availability_posture,
        catalog_source=ProviderCatalogSource.BASELINE,
        notes=notes,
        metadata=dict(metadata or {}),
    )


def _matrix_aliases(provider_id: str) -> tuple[str, ...]:
    return tuple(
        alias
        for alias, canonical in REVIEWED_EXECUTABLE_PROVIDER_ALIASES.items()
        if canonical == provider_id
    )


def build_baseline_provider_entries() -> tuple[ProviderCapabilityEntry, ...]:
    """Build the sealed baseline provider-capability descriptors.

    Entries are pure data.  Catalog construction never probes availability.
    """

    resource_bounds = ("resource_bounded",)
    entries = (
        _entry(
            "z3",
            authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            family_support=(
                _support(
                    "first_order",
                    fragments=("arithmetic", "equality", "propositional", "quantifiers"),
                    properties=("satisfiability", "theorem", "validity"),
                    operations=("check_satisfiability", "prove"),
                ),
                _support(
                    "horn_chc",
                    fragments=("arithmetic", "horn_clauses", "quantifiers"),
                    properties=("invariant", "reachability", "safety", "satisfiability"),
                    operations=("check_satisfiability", "fixedpoint", "ic3", "pdr"),
                ),
                _support(
                    "propositional",
                    fragments=("propositional",),
                    properties=("satisfiability", "theorem", "validity"),
                    operations=("check_satisfiability", "prove"),
                ),
            ),
            aliases=_matrix_aliases("z3"),
            runtime_ids=("native_process",),
            evidence_ids=("model", "unsat_core", "counterexample"),
            boundedness_ids=resource_bounds,
            notes="SMT/CHC compiler and result decoder.",
        ),
        _entry(
            "cvc5",
            authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            family_support=(
                _support(
                    "first_order",
                    fragments=("arithmetic", "equality", "propositional", "quantifiers"),
                    properties=("satisfiability", "theorem", "validity"),
                    operations=("check_satisfiability", "prove"),
                ),
                _support(
                    "horn_chc",
                    fragments=("arithmetic", "horn_clauses", "quantifiers"),
                    properties=("invariant", "reachability", "safety", "satisfiability"),
                    operations=("check_satisfiability", "fixedpoint"),
                ),
                _support(
                    "propositional",
                    fragments=("propositional",),
                    properties=("satisfiability", "theorem", "validity"),
                    operations=("check_satisfiability", "prove"),
                ),
            ),
            aliases=_matrix_aliases("cvc5"),
            runtime_ids=("native_process",),
            evidence_ids=("model", "unsat_core", "counterexample", "proof_certificate"),
            boundedness_ids=resource_bounds,
            notes="SMT compiler and result decoder; SyGuS remains declaration-only in v1.",
        ),
        _entry(
            "tla_tlc",
            authority_ceiling=EvidenceAuthority.BOUNDED,
            family_support=(
                _support(
                    "temporal",
                    fragments=("linear_time",),
                    properties=("invariant", "liveness", "reachability", "safety"),
                    operations=("model_check",),
                ),
                _support(
                    "transition_system",
                    fragments=("action_system", "kripke", "transition_system"),
                    properties=("invariant", "liveness", "reachability", "safety"),
                    operations=("model_check",),
                ),
            ),
            aliases=_matrix_aliases("tla_tlc"),
            runtime_ids=("jvm_process",),
            evidence_ids=("counterexample", "trace"),
            boundedness_ids=("finite_domain", "resource_bounded"),
            notes="Finite-state TLC lane; exhaustive only for configured finite state space.",
        ),
        _entry(
            "apalache",
            authority_ceiling=EvidenceAuthority.BOUNDED,
            family_support=(
                _support(
                    "temporal",
                    fragments=("linear_time",),
                    properties=("invariant", "reachability", "safety"),
                    operations=("model_check",),
                ),
                _support(
                    "transition_system",
                    fragments=("action_system", "transition_system"),
                    properties=("invariant", "reachability", "safety"),
                    operations=("model_check",),
                ),
            ),
            aliases=_matrix_aliases("apalache"),
            runtime_ids=("jvm_process",),
            evidence_ids=("counterexample", "model"),
            boundedness_ids=("step_bounded", "resource_bounded"),
            notes="Bounded symbolic TLA+ lane.",
        ),
        _entry(
            "runtime_mtl",
            authority_ceiling=EvidenceAuthority.BOUNDED,
            family_support=(
                _support(
                    "temporal",
                    fragments=("finite_trace", "metric_time"),
                    properties=("safety", "trace_conformance"),
                    operations=("runtime_monitor",),
                ),
            ),
            aliases=_matrix_aliases("runtime_mtl"),
            runtime_ids=("in_process",),
            evidence_ids=("monitor_verdict", "trace"),
            boundedness_ids=("finite_trace", "resource_bounded"),
            notes="Finite-trace metric-temporal monitor lane.",
        ),
        _entry(
            "datalog_secpal",
            authority_ceiling=EvidenceAuthority.BOUNDED,
            family_support=(
                _support(
                    "authorization",
                    fragments=("datalog", "deontic"),
                    properties=("authorization",),
                    operations=("authorize",),
                ),
                _support(
                    "datalog",
                    fragments=("datalog", "horn_clauses"),
                    properties=("authorization", "reachability", "satisfiability"),
                    operations=("authorize", "fixedpoint"),
                ),
            ),
            aliases=_matrix_aliases("datalog_secpal"),
            runtime_ids=("in_process", "native_process"),
            evidence_ids=("policy_decision",),
            boundedness_ids=resource_bounds,
            notes="Datalog/Horn/SecPAL authorization lane.",
        ),
        _entry(
            "proverif",
            authority_ceiling=EvidenceAuthority.BOUNDED,
            family_support=(
                _support(
                    "cryptographic_protocol",
                    fragments=("symbolic_crypto", "transition_system"),
                    properties=("authentication", "secrecy"),
                    operations=("verify_protocol",),
                ),
            ),
            aliases=_matrix_aliases("proverif"),
            runtime_ids=("ocaml_process", "native_process"),
            evidence_ids=("counterexample", "trace"),
            boundedness_ids=resource_bounds,
            notes="Symbolic applied-pi protocol lane (over-approximation-aware).",
        ),
        _entry(
            "tamarin",
            authority_ceiling=EvidenceAuthority.BOUNDED,
            family_support=(
                _support(
                    "cryptographic_protocol",
                    fragments=("symbolic_crypto", "transition_system"),
                    properties=("authentication", "secrecy"),
                    operations=("verify_protocol",),
                ),
            ),
            aliases=_matrix_aliases("tamarin"),
            runtime_ids=("native_process",),
            evidence_ids=("counterexample", "trace"),
            boundedness_ids=resource_bounds,
            notes="Multiset-rewriting protocol lane.",
        ),
        _entry(
            "hyperltl_autohyper_mchyper",
            authority_ceiling=EvidenceAuthority.BOUNDED,
            family_support=(
                _support(
                    "hyperproperty",
                    fragments=("hypertrace", "information_flow", "linear_time"),
                    properties=("hyperproperty", "noninterference"),
                    operations=("check_hyperproperty",),
                ),
            ),
            aliases=_matrix_aliases("hyperltl_autohyper_mchyper"),
            runtime_ids=("native_process",),
            evidence_ids=("counterexample", "model"),
            boundedness_ids=("resource_bounded", "step_bounded"),
            notes="HyperLTL AutoHyper/MCHyper lane.",
        ),
        _entry(
            "vampire",
            authority_ceiling=EvidenceAuthority.ADVISORY,
            family_support=(
                _support(
                    "first_order",
                    fragments=("equality", "propositional", "quantifiers"),
                    properties=("theorem", "validity"),
                    operations=("prove",),
                ),
                _support(
                    "dcec",
                    fragments=("deontic", "event_calculus", "modal", "quantifiers"),
                    properties=("theorem", "validity"),
                    operations=("prove",),
                ),
                _support(
                    "tdfol",
                    fragments=(
                        "deontic",
                        "linear_time",
                        "modal",
                        "propositional",
                        "quantifiers",
                    ),
                    properties=("theorem", "validity"),
                    operations=("prove",),
                ),
            ),
            aliases=_matrix_aliases("vampire"),
            runtime_ids=("native_process",),
            evidence_ids=("candidate",),
            boundedness_ids=resource_bounds,
            deterministic=False,
            notes="Classical TPTP ATP lane; untrusted until reconstructed.",
        ),
        _entry(
            "eprover",
            authority_ceiling=EvidenceAuthority.ADVISORY,
            family_support=(
                _support(
                    "first_order",
                    fragments=("equality", "propositional", "quantifiers"),
                    properties=("theorem", "validity"),
                    operations=("prove",),
                ),
                _support(
                    "dcec",
                    fragments=("deontic", "event_calculus", "modal", "quantifiers"),
                    properties=("theorem", "validity"),
                    operations=("prove",),
                ),
                _support(
                    "tdfol",
                    fragments=(
                        "deontic",
                        "linear_time",
                        "modal",
                        "propositional",
                        "quantifiers",
                    ),
                    properties=("theorem", "validity"),
                    operations=("prove",),
                ),
            ),
            aliases=_matrix_aliases("eprover"),
            runtime_ids=("native_process",),
            evidence_ids=("candidate",),
            boundedness_ids=resource_bounds,
            deterministic=False,
            notes="E prover classical TPTP ATP lane; untrusted until reconstructed.",
        ),
        _entry(
            "hammer",
            authority_ceiling=EvidenceAuthority.ADVISORY,
            family_support=(
                _support(
                    "first_order",
                    SupportLevel.NATIVE,
                    fragments=("equality", "propositional", "quantifiers"),
                    properties=("theorem", "validity"),
                    operations=("prove",),
                    notes="Premise selection / reconstruction strategy only.",
                ),
                _support(
                    "higher_order",
                    SupportLevel.NATIVE,
                    fragments=("higher_order", "propositional", "quantifiers"),
                    properties=("theorem", "validity"),
                    operations=("prove", "reconstruct"),
                ),
                _support(
                    "dependent_type",
                    SupportLevel.DECLARATION_ONLY,
                    notes="Dependent-type hammer targets remain declaration-only.",
                ),
            ),
            aliases=_matrix_aliases("hammer"),
            runtime_ids=("in_process", "native_process"),
            evidence_ids=("candidate",),
            boundedness_ids=resource_bounds,
            advisory=True,
            notes="Premise-selection/reconstruction strategy lane; advisory until reconstruction.",
        ),
        _entry(
            "lean",
            authority_ceiling=EvidenceAuthority.AUTHORITATIVE,
            family_support=(
                _support(
                    "higher_order",
                    fragments=("higher_order", "propositional", "quantifiers"),
                    properties=("theorem", "validity"),
                    operations=("kernel_check", "prove", "reconstruct"),
                ),
                _support(
                    "program",
                    fragments=("cfg", "contracts", "dynamic", "program_state"),
                    properties=("contract", "safety", "termination"),
                    operations=("generate_vc", "prove"),
                ),
                _support(
                    "dependent_type",
                    SupportLevel.DECLARATION_ONLY,
                    notes="Dependent-type kernel targets remain declaration-only in baseline.",
                ),
            ),
            aliases=_matrix_aliases("lean"),
            runtime_ids=("native_process",),
            evidence_ids=("kernel_checked_proof", "checked_proof"),
            boundedness_ids=resource_bounds,
            notes="Lean kernel target lane.",
        ),
        _entry(
            "rocq",
            authority_ceiling=EvidenceAuthority.AUTHORITATIVE,
            family_support=(
                _support(
                    "higher_order",
                    fragments=("higher_order", "propositional", "quantifiers"),
                    properties=("theorem", "validity"),
                    operations=("kernel_check", "prove", "reconstruct"),
                ),
                _support(
                    "program",
                    fragments=("cfg", "contracts", "dynamic", "program_state"),
                    properties=("contract", "safety", "termination"),
                    operations=("generate_vc", "prove"),
                ),
                _support(
                    "dependent_type",
                    SupportLevel.DECLARATION_ONLY,
                    notes="Dependent-type kernel targets remain declaration-only in baseline.",
                ),
            ),
            aliases=_matrix_aliases("rocq"),
            runtime_ids=("native_process",),
            evidence_ids=("kernel_checked_proof", "checked_proof"),
            boundedness_ids=resource_bounds,
            notes="Rocq kernel target lane.",
        ),
        _entry(
            "isabelle",
            authority_ceiling=EvidenceAuthority.AUTHORITATIVE,
            family_support=(
                _support(
                    "higher_order",
                    fragments=("higher_order", "propositional", "quantifiers"),
                    properties=("theorem", "validity"),
                    operations=("kernel_check", "prove", "reconstruct"),
                ),
                _support(
                    "program",
                    fragments=("cfg", "contracts", "dynamic", "program_state"),
                    properties=("contract", "safety", "termination"),
                    operations=("generate_vc", "prove"),
                ),
            ),
            aliases=_matrix_aliases("isabelle"),
            runtime_ids=("native_process",),
            evidence_ids=("kernel_checked_proof", "checked_proof"),
            boundedness_ids=resource_bounds,
            notes="Isabelle/HOL kernel target lane.",
        ),
        # Advisory lanes outside the executable proof matrix.
        _entry(
            "ergoai",
            authority_ceiling=EvidenceAuthority.ADVISORY,
            family_support=(
                _support(
                    "frame_logic",
                    SupportLevel.NATIVE,
                    fragments=("modal", "propositional", "resources"),
                    properties=("satisfiability", "theorem", "validity"),
                    operations=("prove",),
                    notes="Controlled F-logic/rule advisor; not a proof lane.",
                ),
            ),
            aliases=("ergo_ai",),
            runtime_ids=("native_process",),
            evidence_ids=("candidate",),
            boundedness_ids=resource_bounds,
            in_executable_matrix=False,
            advisory=True,
            availability_posture=ProviderAvailabilityPosture.ADVISORY_ONLY,
            notes="Controlled F-logic/rule advisor; not an executable matrix proof lane.",
        ),
        _entry(
            "symbolicai",
            authority_ceiling=EvidenceAuthority.ADVISORY,
            family_support=(),
            aliases=("symai",),
            runtime_ids=("remote_service", "in_process"),
            evidence_ids=("candidate",),
            boundedness_ids=resource_bounds,
            in_executable_matrix=False,
            advisory=True,
            availability_posture=ProviderAvailabilityPosture.ADVISORY_ONLY,
            deterministic=False,
            notes="Natural-language/symbolic proposal advisor; unverified candidate only.",
        ),
    )
    return tuple(sorted(entries, key=lambda item: item.provider_id))


class ProviderCapabilityCatalog:
    """Versioned catalog of baseline provider-capability descriptors.

    The catalog is mutable while assembled and may then be frozen.  It never
    treats descriptor presence as tool availability or proof authority.
    Generated-closure descriptors (LFP-040) are tracked separately from the
    sealed baseline and cannot silently overwrite baseline entries.
    """

    interface: Final = CATALOG_INTERFACE
    schema_version: Final = CATALOG_SCHEMA_VERSION

    def __init__(
        self,
        entries: Iterable[ProviderCapabilityEntry] = (),
        *,
        version: str = CATALOG_MODULE_VERSION,
        frozen: bool = False,
        generated_closure_open: bool = True,
        generated_closure_task: str = GENERATED_CLOSURE_TASK,
    ) -> None:
        if not isinstance(version, str) or not version.strip():
            raise ProviderCatalogError("catalog version must be a non-empty string")
        self.version = version.strip()
        self.generated_closure_open = bool(generated_closure_open)
        self.generated_closure_task = _text(
            generated_closure_task, "generated_closure_task"
        )
        self._entries: dict[str, ProviderCapabilityEntry] = {}
        self._aliases: dict[str, str] = {}
        self._frozen = False
        for entry in sorted(entries, key=lambda item: item.provider_id):
            self.register(entry)
        if frozen:
            self.freeze()

    @property
    def frozen(self) -> bool:
        return self._frozen

    def freeze(self) -> "ProviderCapabilityCatalog":
        self._frozen = True
        return self

    def _require_mutable(self) -> None:
        if self._frozen:
            raise ProviderCatalogError("provider-capability catalog is frozen")

    def register(self, entry: ProviderCapabilityEntry) -> ProviderCapabilityEntry:
        self._require_mutable()
        if not isinstance(entry, ProviderCapabilityEntry):
            raise TypeError("entry must be a ProviderCapabilityEntry")
        # Baseline descriptors cannot be replaced by generated-closure rows.
        # Checked before the duplicate-id gate so LFP-040 overwrites fail closed
        # with a catalog-source diagnostic rather than a generic collision.
        if (
            entry.catalog_source is ProviderCatalogSource.GENERATED_CLOSURE
            and entry.provider_id in BASELINE_PROVIDER_IDS
        ):
            raise ProviderCatalogDriftError(
                f"LFP-040 generated closure cannot overwrite baseline provider "
                f"{entry.provider_id!r}"
            )
        if entry.provider_id in self._entries:
            raise ProviderCatalogError(
                f"provider {entry.provider_id!r} is already registered"
            )
        if entry.provider_id in self._aliases:
            raise ProviderCatalogError(
                f"provider id {entry.provider_id!r} collides with an alias"
            )
        claimed = (entry.provider_id, *entry.aliases)
        for name in claimed:
            owner = self._aliases.get(name)
            if owner is not None and owner != entry.provider_id:
                raise ProviderCatalogError(
                    f"provider alias {name!r} collides with registered provider "
                    f"{owner!r}"
                )
            if name in self._entries and name != entry.provider_id:
                raise ProviderCatalogError(
                    f"provider alias {name!r} collides with provider id {name!r}"
                )
        self._entries[entry.provider_id] = entry
        for name in claimed:
            self._aliases[name] = entry.provider_id
        return entry

    def get(self, provider_id: str) -> ProviderCapabilityEntry:
        canonical = self._aliases.get(provider_id, provider_id)
        try:
            return self._entries[canonical]
        except KeyError as error:
            raise ProviderCatalogError(
                f"unknown provider {provider_id!r}"
            ) from error

    def resolve(self, provider_id: str) -> ProviderCapabilityEntry:
        return self.get(provider_id)

    @property
    def entries(self) -> Mapping[str, ProviderCapabilityEntry]:
        return MappingProxyType(
            {key: self._entries[key] for key in sorted(self._entries)}
        )

    @property
    def provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    @property
    def baseline_entries(self) -> tuple[ProviderCapabilityEntry, ...]:
        return tuple(
            self._entries[key]
            for key in sorted(self._entries)
            if self._entries[key].is_baseline
        )

    @property
    def generated_closure_entries(self) -> tuple[ProviderCapabilityEntry, ...]:
        return tuple(
            self._entries[key]
            for key in sorted(self._entries)
            if self._entries[key].is_generated_closure
        )

    @property
    def executable_matrix_ids(self) -> tuple[str, ...]:
        return tuple(
            key
            for key in sorted(self._entries)
            if self._entries[key].in_executable_matrix
        )

    @property
    def reviewed_aliases(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                alias: canonical
                for alias, canonical in sorted(self._aliases.items())
                if alias != canonical
            }
        )

    def authority_ceiling_for(self, provider_id: str) -> EvidenceAuthority:
        return self.get(provider_id).authority_ceiling

    def is_available(self, provider_id: str) -> bool:
        """Never treat catalog presence as availability.

        Explicitly returns ``False`` for pure discovery.  Callers must use a
        backend availability probe for live status.
        """

        # Touch the provider to ensure it is registered, then refuse presence.
        self.get(provider_id)
        return False

    def claims_proof(self, provider_id: str) -> bool:
        """Presence never constitutes a proof claim."""

        self.get(provider_id)
        return False

    def validate_against_registry(
        self, registry: LogicFamilyRegistry | None = None
    ) -> None:
        """Validate every entry's capability projection against a family registry."""

        active = registry if registry is not None else DEFAULT_REGISTRY
        for entry in self.baseline_entries:
            active.validate_provider_capability(entry.to_capability_descriptor())
            # Declaration-only families cannot gain executable support.
            for support in entry.family_support:
                family = active.families.get(support.family_id)
                if family is None:
                    raise ProviderCatalogDriftError(
                        f"provider {entry.provider_id!r} references unknown family "
                        f"{support.family_id!r}"
                    )
                if (
                    family.declaration_only
                    and support.support_level
                    not in {SupportLevel.DECLARATION_ONLY, SupportLevel.UNSUPPORTED}
                ):
                    raise ProviderCatalogDriftError(
                        f"provider {entry.provider_id!r} claims executable support "
                        f"for declaration-only family {family.family_id!r}"
                    )

    def validate_executable_matrix_join(
        self,
        matrix: Sequence[ProviderMatrixEntry] | None = None,
    ) -> None:
        """Ensure baseline catalog enumerates every executable-matrix ID/alias."""

        active = tuple(matrix) if matrix is not None else EXECUTABLE_PROVIDER_MATRIX
        matrix_ids = {entry.provider_id for entry in active}
        catalog_matrix_ids = set(self.executable_matrix_ids)
        if matrix_ids != catalog_matrix_ids:
            missing = sorted(matrix_ids - catalog_matrix_ids)
            extra = sorted(catalog_matrix_ids - matrix_ids)
            raise ProviderCatalogDriftError(
                "executable-matrix join mismatch"
                + (f"; missing={missing}" if missing else "")
                + (f"; extra={extra}" if extra else "")
            )
        for entry in active:
            catalog_entry = self.get(entry.provider_id)
            expected_aliases = set(entry.aliases)
            observed_aliases = set(catalog_entry.aliases)
            if expected_aliases != observed_aliases:
                raise ProviderCatalogDriftError(
                    f"provider {entry.provider_id!r} alias mismatch: "
                    f"matrix={sorted(expected_aliases)} "
                    f"catalog={sorted(observed_aliases)}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_family_ids": sorted(BASELINE_FAMILY_IDS),
            "declaration_only_family_ids": sorted(DECLARATION_ONLY_FAMILY_IDS),
            "entries": [
                self._entries[key].to_dict() for key in sorted(self._entries)
            ],
            "executable_matrix_interface": EXECUTABLE_PROVIDER_MATRIX_INTERFACE,
            "executable_matrix_provider_ids": list(EXECUTABLE_MATRIX_PROVIDER_IDS),
            "generated_closure_open": self.generated_closure_open,
            "generated_closure_task": self.generated_closure_task,
            "interface": self.interface,
            "non_family_profile_labels": sorted(NON_FAMILY_PROFILE_LABELS),
            "planned_extension_family_ids": sorted(PLANNED_EXTENSION_FAMILY_IDS),
            "provider_ids": list(self.provider_ids),
            "registry_interface": REGISTRY_INTERFACE,
            "reviewed_aliases": dict(self.reviewed_aliases),
            "schema_version": self.schema_version,
            "version": self.version,
        }

    def to_json(self, *, indent: int | None = None) -> str:
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
    ) -> "ProviderCapabilityCatalog":
        schema = value.get("schema_version")
        if schema != CATALOG_SCHEMA_VERSION:
            raise ProviderCatalogError(
                f"unsupported or missing catalog schema_version: {schema!r}"
            )
        interface = value.get("interface")
        if interface not in (None, CATALOG_INTERFACE):
            raise ProviderCatalogError(
                f"unsupported catalog interface: {interface!r}"
            )
        return cls(
            entries=(
                ProviderCapabilityEntry.from_dict(item)
                for item in value.get("entries", ())
            ),
            version=value.get("version", CATALOG_MODULE_VERSION),
            frozen=frozen,
            generated_closure_open=bool(value.get("generated_closure_open", True)),
            generated_closure_task=value.get(
                "generated_closure_task", GENERATED_CLOSURE_TASK
            ),
        )

    def __contains__(self, provider_id: object) -> bool:
        if not isinstance(provider_id, str):
            return False
        return provider_id in self._aliases or provider_id in self._entries

    def __iter__(self) -> Iterator[ProviderCapabilityEntry]:
        for key in sorted(self._entries):
            yield self._entries[key]

    def __len__(self) -> int:
        return len(self._entries)


def build_baseline_provider_catalog(
    *,
    frozen: bool = True,
    validate: bool = True,
    registry: LogicFamilyRegistry | None = None,
) -> ProviderCapabilityCatalog:
    """Build and optionally validate the sealed baseline provider catalog."""

    catalog = ProviderCapabilityCatalog(
        build_baseline_provider_entries(),
        frozen=False,
        generated_closure_open=True,
        generated_closure_task=GENERATED_CLOSURE_TASK,
    )
    if validate:
        catalog.validate_against_registry(registry)
        catalog.validate_executable_matrix_join()
    if frozen:
        catalog.freeze()
    return catalog


def register_baseline_provider_capabilities(
    registry: LogicFamilyRegistry | None = None,
    *,
    catalog: ProviderCapabilityCatalog | None = None,
) -> LogicFamilyRegistry:
    """Register baseline provider capabilities onto a family registry.

    When *registry* is omitted a fresh mutable default registry is built.
    The input registry must be mutable.
    """

    active = registry if registry is not None else build_default_registry(frozen=False)
    source = catalog if catalog is not None else build_baseline_provider_catalog(
        frozen=True, validate=True, registry=active
    )
    for entry in source.baseline_entries:
        active.register_provider_capability(entry.to_capability_descriptor())
    return active


BASELINE_PROVIDER_CATALOG: Final[ProviderCapabilityCatalog] = (
    build_baseline_provider_catalog(frozen=True, validate=True)
)


__all__ = [
    "ADVISORY_AUTHORITY_CEILINGS",
    "ADVISORY_PROVIDER_IDS",
    "BASELINE_PROVIDER_CATALOG",
    "BASELINE_PROVIDER_IDS",
    "BASELINE_PROVIDER_VERSION",
    "BASELINE_SOURCE",
    "CATALOG_INTERFACE",
    "CATALOG_MODULE_VERSION",
    "CATALOG_SCHEMA_VERSION",
    "EXECUTABLE_MATRIX_PROVIDER_IDS",
    "GENERATED_CLOSURE_SOURCE",
    "GENERATED_CLOSURE_TASK",
    "PROVIDER_ENTRY_SCHEMA",
    "ProviderAvailabilityPosture",
    "ProviderCapabilityCatalog",
    "ProviderCapabilityEntry",
    "ProviderCatalogAuthorityError",
    "ProviderCatalogDriftError",
    "ProviderCatalogError",
    "ProviderCatalogSource",
    "REVIEWED_EXECUTABLE_PROVIDER_ALIASES",
    "authority_at_most",
    "authority_rank",
    "build_baseline_provider_catalog",
    "build_baseline_provider_entries",
    "register_baseline_provider_capabilities",
]
