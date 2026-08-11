"""Final generated provider/translation catalog (``GeneratedProviderTranslationCatalog@1``).

LFP-040 projects the sealed baseline provider catalog and registry translation
edges into one closed, side-effect-free generated catalog.  The projection:

* enumerates every exact baseline / executable-matrix provider ID;
* carries every reviewed translation edge from the family registry;
* never overwrites baseline providers with generated-closure rows;
* rejects duplicate, eager, and unknown provider/family/translation entries;
* never treats catalog presence as tool availability or proof authority.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.registry import (
    EXECUTABLE_PROVIDER_ALIASES,
    EXECUTABLE_PROVIDER_IDS,
    EXECUTABLE_PROVIDER_MATRIX,
)
from ipfs_datasets_py.logic.families.models import (
    DESCRIPTOR_VERSION,
    TranslationDescriptor,
    TranslationKind,
)
from ipfs_datasets_py.logic.families.providers import (
    BASELINE_PROVIDER_CATALOG,
    BASELINE_PROVIDER_IDS,
    GENERATED_CLOSURE_SOURCE,
    GENERATED_CLOSURE_TASK,
    ProviderCapabilityCatalog,
    ProviderCapabilityEntry,
    ProviderCatalogDriftError,
    ProviderCatalogError,
    ProviderCatalogSource,
    build_baseline_provider_catalog,
)
from ipfs_datasets_py.logic.families.registry import (
    BASELINE_FAMILY_IDS,
    DEFAULT_REGISTRY,
    LogicFamilyRegistry,
)


GENERATED_PROVIDER_TRANSLATION_CATALOG_INTERFACE: Final = (
    "GeneratedProviderTranslationCatalog@1"
)
GENERATED_CATALOG_SCHEMA_VERSION: Final = (
    "logic-family-generated-provider-translation-catalog/v1"
)
GENERATED_CATALOG_VERSION: Final = "1.0.0"
GENERATED_CATALOG_TASK_ID: Final = GENERATED_CLOSURE_TASK
GENERATED_CATALOG_GOAL_ID: Final = "LFP-G080"


class GeneratedCatalogError(ValueError):
    """Raised when the generated provider/translation catalog is invalid."""


class DuplicateGeneratedCatalogEntryError(GeneratedCatalogError):
    """Raised when a provider or translation id appears more than once."""


class EagerGeneratedCatalogEntryError(GeneratedCatalogError):
    """Raised when the catalog claims live availability or proof authority."""


class UnknownGeneratedCatalogEntryError(GeneratedCatalogError):
    """Raised when a referenced provider, family, or translation is unknown."""


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise GeneratedCatalogError(f"{field_name} must be a non-empty trimmed string")
    if "\x00" in value:
        raise GeneratedCatalogError(f"{field_name} must not contain NUL bytes")
    return value


def _identifier(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if any(character.isspace() for character in result):
        raise GeneratedCatalogError(
            f"{field_name} must not contain whitespace; got {result!r}"
        )
    return result


@dataclass(frozen=True, slots=True)
class GeneratedTranslationEdge:
    """One projected translation edge in the generated closure."""

    translation_id: str
    source_family_id: str
    target_family_id: str
    translation_kind: TranslationKind
    preserves_property_ids: tuple[str, ...] = ()
    loses_property_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    description: str = ""
    catalog_source: str = GENERATED_CLOSURE_SOURCE
    version: str = DESCRIPTOR_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "translation_id",
            _identifier(self.translation_id, "translation_id"),
        )
        object.__setattr__(
            self,
            "source_family_id",
            _identifier(self.source_family_id, "source_family_id"),
        )
        object.__setattr__(
            self,
            "target_family_id",
            _identifier(self.target_family_id, "target_family_id"),
        )
        kind = self.translation_kind
        if not isinstance(kind, TranslationKind):
            kind = TranslationKind(str(kind))
        object.__setattr__(self, "translation_kind", kind)
        object.__setattr__(
            self,
            "preserves_property_ids",
            tuple(
                _identifier(item, "preserves_property_ids item")
                for item in self.preserves_property_ids
            ),
        )
        object.__setattr__(
            self,
            "loses_property_ids",
            tuple(
                _identifier(item, "loses_property_ids item")
                for item in self.loses_property_ids
            ),
        )
        object.__setattr__(
            self,
            "evidence_ids",
            tuple(_identifier(item, "evidence_ids item") for item in self.evidence_ids),
        )
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description") if self.description else "",
        )
        object.__setattr__(
            self,
            "catalog_source",
            _text(self.catalog_source, "catalog_source"),
        )
        object.__setattr__(self, "version", _text(self.version, "version"))

    @classmethod
    def from_descriptor(
        cls, descriptor: TranslationDescriptor
    ) -> "GeneratedTranslationEdge":
        return cls(
            translation_id=descriptor.translation_id,
            source_family_id=descriptor.source_family_id,
            target_family_id=descriptor.target_family_id,
            translation_kind=descriptor.translation_kind,
            preserves_property_ids=descriptor.preserves_property_ids,
            loses_property_ids=descriptor.loses_property_ids,
            evidence_ids=descriptor.evidence_ids,
            description=descriptor.description,
            version=descriptor.version,
        )

    def to_descriptor(self) -> TranslationDescriptor:
        return TranslationDescriptor(
            translation_id=self.translation_id,
            source_family_id=self.source_family_id,
            target_family_id=self.target_family_id,
            translation_kind=self.translation_kind,
            preserves_property_ids=self.preserves_property_ids,
            loses_property_ids=self.loses_property_ids,
            evidence_ids=self.evidence_ids,
            description=self.description,
            version=self.version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_source": self.catalog_source,
            "description": self.description,
            "evidence_ids": list(self.evidence_ids),
            "loses_property_ids": list(self.loses_property_ids),
            "preserves_property_ids": list(self.preserves_property_ids),
            "source_family_id": self.source_family_id,
            "target_family_id": self.target_family_id,
            "translation_id": self.translation_id,
            "translation_kind": self.translation_kind.value,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GeneratedTranslationEdge":
        if not isinstance(value, Mapping):
            raise GeneratedCatalogError("translation edge must be a mapping")
        return cls(
            translation_id=str(value.get("translation_id") or ""),
            source_family_id=str(value.get("source_family_id") or ""),
            target_family_id=str(value.get("target_family_id") or ""),
            translation_kind=str(
                value.get("translation_kind") or TranslationKind.LOSSLESS.value
            ),
            preserves_property_ids=tuple(value.get("preserves_property_ids") or ()),
            loses_property_ids=tuple(value.get("loses_property_ids") or ()),
            evidence_ids=tuple(value.get("evidence_ids") or ()),
            description=str(value.get("description") or ""),
            catalog_source=str(
                value.get("catalog_source") or GENERATED_CLOSURE_SOURCE
            ),
            version=str(value.get("version") or DESCRIPTOR_VERSION),
        )


def _project_translations(
    registry: LogicFamilyRegistry,
) -> tuple[GeneratedTranslationEdge, ...]:
    edges = [
        GeneratedTranslationEdge.from_descriptor(descriptor)
        for descriptor in registry.translations.values()
    ]
    return tuple(sorted(edges, key=lambda item: item.translation_id))


def _project_provider_entries(
    baseline: ProviderCapabilityCatalog,
) -> tuple[ProviderCapabilityEntry, ...]:
    # Final projection reuses sealed baseline entries; it does not invent
    # generated-closure overwrites of baseline provider IDs.
    return tuple(baseline.baseline_entries)


@dataclass(frozen=True, slots=True)
class GeneratedProviderTranslationCatalog:
    """Closed provider + translation projection for LFP-040.

    Interface: ``GeneratedProviderTranslationCatalog@1``.
    """

    INTERFACE: ClassVar[str] = GENERATED_PROVIDER_TRANSLATION_CATALOG_INTERFACE

    providers: tuple[ProviderCapabilityEntry, ...] = field(default_factory=tuple)
    translations: tuple[GeneratedTranslationEdge, ...] = field(default_factory=tuple)
    schema_version: str = GENERATED_CATALOG_SCHEMA_VERSION
    version: str = GENERATED_CATALOG_VERSION
    task_id: str = GENERATED_CATALOG_TASK_ID
    goal_id: str = GENERATED_CATALOG_GOAL_ID
    generated_closure_source: str = GENERATED_CLOSURE_SOURCE
    generated_closure_open: bool = False
    notes: str = (
        "Final LFP-040 projection of baseline providers and registry "
        "translation edges. Presence is not availability or proof."
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != GENERATED_CATALOG_SCHEMA_VERSION:
            raise GeneratedCatalogError(
                f"unsupported generated catalog schema: {self.schema_version!r}"
            )
        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(self, "task_id", _text(self.task_id, "task_id"))
        object.__setattr__(self, "goal_id", _text(self.goal_id, "goal_id"))
        object.__setattr__(
            self,
            "generated_closure_source",
            _text(self.generated_closure_source, "generated_closure_source"),
        )
        if not isinstance(self.generated_closure_open, bool):
            raise GeneratedCatalogError("generated_closure_open must be a boolean")
        object.__setattr__(
            self, "notes", _text(self.notes, "notes") if self.notes else ""
        )

        providers = self._normalize_providers(self.providers)
        translations = self._normalize_translations(self.translations)
        self._reject_duplicates(providers, translations)
        object.__setattr__(self, "providers", providers)
        object.__setattr__(self, "translations", translations)

    @staticmethod
    def _normalize_providers(
        providers: Sequence[ProviderCapabilityEntry] | object,
    ) -> tuple[ProviderCapabilityEntry, ...]:
        if isinstance(providers, (str, bytes, bytearray)) or not isinstance(
            providers, Sequence
        ):
            raise GeneratedCatalogError("providers must be a sequence")
        items: list[ProviderCapabilityEntry] = []
        for item in providers:
            if isinstance(item, ProviderCapabilityEntry):
                items.append(item)
            elif isinstance(item, Mapping):
                items.append(ProviderCapabilityEntry.from_dict(item))
            else:
                raise GeneratedCatalogError(
                    "providers must be ProviderCapabilityEntry values"
                )
        return tuple(sorted(items, key=lambda item: item.provider_id))

    @staticmethod
    def _normalize_translations(
        translations: Sequence[GeneratedTranslationEdge] | object,
    ) -> tuple[GeneratedTranslationEdge, ...]:
        if isinstance(translations, (str, bytes, bytearray)) or not isinstance(
            translations, Sequence
        ):
            raise GeneratedCatalogError("translations must be a sequence")
        items: list[GeneratedTranslationEdge] = []
        for item in translations:
            if isinstance(item, GeneratedTranslationEdge):
                items.append(item)
            elif isinstance(item, Mapping):
                items.append(GeneratedTranslationEdge.from_dict(item))
            elif isinstance(item, TranslationDescriptor):
                items.append(GeneratedTranslationEdge.from_descriptor(item))
            else:
                raise GeneratedCatalogError(
                    "translations must be GeneratedTranslationEdge values"
                )
        return tuple(sorted(items, key=lambda item: item.translation_id))

    @staticmethod
    def _reject_duplicates(
        providers: Sequence[ProviderCapabilityEntry],
        translations: Sequence[GeneratedTranslationEdge],
    ) -> None:
        provider_ids = [item.provider_id for item in providers]
        if len(provider_ids) != len(set(provider_ids)):
            seen: set[str] = set()
            for provider_id in provider_ids:
                if provider_id in seen:
                    raise DuplicateGeneratedCatalogEntryError(
                        f"duplicate provider id {provider_id!r}"
                    )
                seen.add(provider_id)
        translation_ids = [item.translation_id for item in translations]
        if len(translation_ids) != len(set(translation_ids)):
            seen_t: set[str] = set()
            for translation_id in translation_ids:
                if translation_id in seen_t:
                    raise DuplicateGeneratedCatalogEntryError(
                        f"duplicate translation id {translation_id!r}"
                    )
                seen_t.add(translation_id)

    def __iter__(self) -> Iterator[ProviderCapabilityEntry]:
        return iter(self.providers)

    def __len__(self) -> int:
        return len(self.providers)

    def __contains__(self, provider_id: object) -> bool:
        if not isinstance(provider_id, str):
            return False
        return provider_id in self.provider_ids or provider_id in self.reviewed_aliases

    @property
    def provider_ids(self) -> tuple[str, ...]:
        return tuple(item.provider_id for item in self.providers)

    @property
    def translation_ids(self) -> tuple[str, ...]:
        return tuple(item.translation_id for item in self.translations)

    @property
    def executable_matrix_provider_ids(self) -> tuple[str, ...]:
        return tuple(
            item.provider_id for item in self.providers if item.in_executable_matrix
        )

    @property
    def reviewed_aliases(self) -> Mapping[str, str]:
        aliases: dict[str, str] = {}
        for entry in self.providers:
            for alias in entry.aliases:
                aliases[alias] = entry.provider_id
        return MappingProxyType(dict(sorted(aliases.items())))

    @property
    def by_provider_id(self) -> Mapping[str, ProviderCapabilityEntry]:
        return MappingProxyType(
            {item.provider_id: item for item in self.providers}
        )

    def get_provider(self, provider_id: str) -> ProviderCapabilityEntry:
        canonical = self.reviewed_aliases.get(provider_id, provider_id)
        try:
            return self.by_provider_id[canonical]
        except KeyError as error:
            raise UnknownGeneratedCatalogEntryError(
                f"unknown provider {provider_id!r}"
            ) from error

    def get_translation(self, translation_id: str) -> GeneratedTranslationEdge:
        for item in self.translations:
            if item.translation_id == translation_id:
                return item
        raise UnknownGeneratedCatalogEntryError(
            f"unknown translation {translation_id!r}"
        )

    def is_eager(self) -> bool:
        """Generated projection never claims live availability or proof."""

        return False

    def claims_availability(self, provider_id: str) -> bool:
        self.get_provider(provider_id)
        return False

    def claims_proof(self, provider_id: str) -> bool:
        self.get_provider(provider_id)
        return False

    def has_unknown_entries(self) -> bool:
        """Return True when any provider or translation is empty/unknown."""

        if not self.providers or not self.translations:
            return True
        for entry in self.providers:
            if not entry.provider_id or entry.provider_id == "unknown":
                return True
        for edge in self.translations:
            if not edge.translation_id or edge.translation_id == "unknown":
                return True
            if (
                edge.source_family_id == "unknown"
                or edge.target_family_id == "unknown"
            ):
                return True
        return False

    def validate_closure(
        self,
        *,
        registry: LogicFamilyRegistry | None = None,
        baseline: ProviderCapabilityCatalog | None = None,
    ) -> None:
        """Reject duplicate/eager/unknown entries and unexplained registry gaps."""

        if self.is_eager():
            raise EagerGeneratedCatalogEntryError(
                "generated catalog must not be eager"
            )
        if self.has_unknown_entries() and not self.translations:
            raise UnknownGeneratedCatalogEntryError(
                "generated catalog has unknown or empty translation projection"
            )
        if self.has_unknown_entries() and not self.providers:
            raise UnknownGeneratedCatalogEntryError(
                "generated catalog has unknown or empty provider projection"
            )

        active_registry = registry if registry is not None else DEFAULT_REGISTRY
        active_baseline = (
            baseline if baseline is not None else BASELINE_PROVIDER_CATALOG
        )

        # Exact provider ID closure against baseline + executable matrix.
        expected_providers = set(BASELINE_PROVIDER_IDS) | set(EXECUTABLE_PROVIDER_IDS)
        observed_providers = set(self.provider_ids)
        missing_providers = sorted(expected_providers - observed_providers)
        extra_providers = sorted(observed_providers - expected_providers)
        if missing_providers or extra_providers:
            raise UnknownGeneratedCatalogEntryError(
                "generated catalog provider set mismatch"
                + (f"; missing={missing_providers}" if missing_providers else "")
                + (f"; extra={extra_providers}" if extra_providers else "")
            )

        matrix_ids = {entry.provider_id for entry in EXECUTABLE_PROVIDER_MATRIX}
        catalog_matrix_ids = set(self.executable_matrix_provider_ids)
        if matrix_ids != catalog_matrix_ids:
            raise ProviderCatalogDriftError(
                "generated catalog executable-matrix join mismatch"
                + f"; missing={sorted(matrix_ids - catalog_matrix_ids)}"
                + f"; extra={sorted(catalog_matrix_ids - matrix_ids)}"
            )

        # Alias closure.
        for alias, canonical in EXECUTABLE_PROVIDER_ALIASES.items():
            if self.reviewed_aliases.get(alias) != canonical:
                raise ProviderCatalogDriftError(
                    f"generated catalog alias {alias!r} must resolve to {canonical!r}"
                )

        # Family/translation referential integrity.
        family_ids = set(BASELINE_FAMILY_IDS) | set(active_registry.families)
        for edge in self.translations:
            if edge.source_family_id not in family_ids:
                raise UnknownGeneratedCatalogEntryError(
                    f"translation {edge.translation_id!r} references unknown source "
                    f"family {edge.source_family_id!r}"
                )
            if edge.target_family_id not in family_ids:
                raise UnknownGeneratedCatalogEntryError(
                    f"translation {edge.translation_id!r} references unknown target "
                    f"family {edge.target_family_id!r}"
                )

        registry_translation_ids = set(active_registry.translations)
        projected_translation_ids = set(self.translation_ids)
        missing_translations = sorted(
            registry_translation_ids - projected_translation_ids
        )
        if missing_translations:
            raise UnknownGeneratedCatalogEntryError(
                "generated catalog missing registry translations: "
                f"{', '.join(missing_translations)}"
            )

        # Baseline entries must remain baseline-sourced (no overwrite).
        for entry in self.providers:
            if entry.provider_id in BASELINE_PROVIDER_IDS:
                if entry.catalog_source is not ProviderCatalogSource.BASELINE:
                    raise ProviderCatalogDriftError(
                        f"baseline provider {entry.provider_id!r} cannot be "
                        "re-sourced as generated closure"
                    )
            baseline_entry = active_baseline.get(entry.provider_id)
            if baseline_entry.provider_id != entry.provider_id:
                raise ProviderCatalogDriftError(
                    f"provider projection drifted for {entry.provider_id!r}"
                )

        # Presence never means availability/proof.
        for provider_id in self.provider_ids:
            if self.claims_availability(provider_id) or self.claims_proof(provider_id):
                raise EagerGeneratedCatalogEntryError(
                    f"provider {provider_id!r} incorrectly claims availability/proof"
                )

        if self.generated_closure_open:
            raise GeneratedCatalogError(
                "final generated catalog must close generated_closure_open"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "executable_matrix_provider_ids": list(self.executable_matrix_provider_ids),
            "generated_closure_open": self.generated_closure_open,
            "generated_closure_source": self.generated_closure_source,
            "goal_id": self.goal_id,
            "interface": self.INTERFACE,
            "notes": self.notes,
            "provider_ids": list(self.provider_ids),
            "providers": [item.to_dict() for item in self.providers],
            "reviewed_aliases": dict(self.reviewed_aliases),
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "translation_ids": list(self.translation_ids),
            "translations": [item.to_dict() for item in self.translations],
            "version": self.version,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> "GeneratedProviderTranslationCatalog":
        if not isinstance(value, Mapping):
            raise TypeError("generated catalog must be a mapping")
        interface = value.get(
            "interface", GENERATED_PROVIDER_TRANSLATION_CATALOG_INTERFACE
        )
        if interface != GENERATED_PROVIDER_TRANSLATION_CATALOG_INTERFACE:
            raise GeneratedCatalogError(
                f"unknown generated catalog interface: {interface!r}"
            )
        return cls(
            providers=tuple(value.get("providers") or ()),
            translations=tuple(value.get("translations") or ()),
            schema_version=str(
                value.get("schema_version") or GENERATED_CATALOG_SCHEMA_VERSION
            ),
            version=str(value.get("version") or GENERATED_CATALOG_VERSION),
            task_id=str(value.get("task_id") or GENERATED_CATALOG_TASK_ID),
            goal_id=str(value.get("goal_id") or GENERATED_CATALOG_GOAL_ID),
            generated_closure_source=str(
                value.get("generated_closure_source") or GENERATED_CLOSURE_SOURCE
            ),
            generated_closure_open=bool(value.get("generated_closure_open", False)),
            notes=str(value.get("notes") or ""),
        )


def build_generated_provider_translation_catalog(
    *,
    registry: LogicFamilyRegistry | None = None,
    baseline: ProviderCapabilityCatalog | None = None,
    validate: bool = True,
) -> GeneratedProviderTranslationCatalog:
    """Project the final LFP-040 provider/translation catalog."""

    active_registry = registry if registry is not None else DEFAULT_REGISTRY
    active_baseline = (
        baseline
        if baseline is not None
        else build_baseline_provider_catalog(frozen=True, validate=True)
    )
    catalog = GeneratedProviderTranslationCatalog(
        providers=_project_provider_entries(active_baseline),
        translations=_project_translations(active_registry),
        generated_closure_open=False,
    )
    if validate:
        catalog.validate_closure(registry=active_registry, baseline=active_baseline)
    return catalog


DEFAULT_GENERATED_CATALOG: Final[GeneratedProviderTranslationCatalog] = (
    build_generated_provider_translation_catalog(validate=True)
)


__all__ = [
    "DEFAULT_GENERATED_CATALOG",
    "DuplicateGeneratedCatalogEntryError",
    "EagerGeneratedCatalogEntryError",
    "GENERATED_CATALOG_GOAL_ID",
    "GENERATED_CATALOG_SCHEMA_VERSION",
    "GENERATED_CATALOG_TASK_ID",
    "GENERATED_CATALOG_VERSION",
    "GENERATED_PROVIDER_TRANSLATION_CATALOG_INTERFACE",
    "GeneratedCatalogError",
    "GeneratedProviderTranslationCatalog",
    "GeneratedTranslationEdge",
    "UnknownGeneratedCatalogEntryError",
    "build_generated_provider_translation_catalog",
]
