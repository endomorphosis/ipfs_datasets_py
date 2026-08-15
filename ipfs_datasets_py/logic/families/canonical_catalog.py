"""Immutable composition root for logic-family catalog layers.

``CanonicalLogicCatalogSnapshot@1`` composes existing typed layers without
flattening them into one untyped dictionary:

* taxonomy — registry v2 (``LogicFamilyRegistry@2``)
* namespaces — ``LogicIdentityNamespaces@1``
* aliases — ``LogicAliasRegistry@1``
* publication — registry v3 lifecycle (``LogicFamilyRegistry@3``)
* profiles — profile catalog v3 (``LogicProfileCatalog@3``)
* properties / views / notations / encodings / providers / lanes / evidence —
  projected from namespaces (and taxonomy where relevant)
* matrix — provider capability matrix v2
* translations — registry translations + generated catalog projection
* versions — layer version envelope
* content identity — reproducible catalog root via ``ir_core.identity``

Registry v2 remains the descriptor taxonomy layer.  Registry v3 remains the
lifecycle / publication layer.  Declaration never implies executability.
Presence on this snapshot never upgrades an identity to production-admitted.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.families.aliases import (
    ALIAS_INTERFACE,
    BASELINE_ALIAS_REGISTRY,
    LogicAliasRegistry,
)
from ipfs_datasets_py.logic.families.generated_catalog import (
    DEFAULT_GENERATED_CATALOG,
    GENERATED_PROVIDER_TRANSLATION_CATALOG_INTERFACE,
    GeneratedProviderTranslationCatalog,
)
from ipfs_datasets_py.logic.families.namespaces import (
    BASELINE_NAMESPACES,
    NAMESPACE_INTERFACE,
    LogicIdentityNamespaces,
    NamespaceKind,
)
from ipfs_datasets_py.logic.families.profile_catalog_v3 import (
    DEFAULT_PROFILE_CATALOG_V3,
    LOGIC_PROFILE_CATALOG_V3_INTERFACE,
    LogicProfileCatalogV3,
)
from ipfs_datasets_py.logic.families.provider_matrix_v2 import (
    BASELINE_PROVIDER_CAPABILITY_MATRIX_V2,
    MATRIX_V2_INTERFACE,
    ProviderCapabilityMatrixV2,
)
from ipfs_datasets_py.logic.families.providers import (
    BASELINE_PROVIDER_CATALOG,
    CATALOG_INTERFACE as PROVIDER_CATALOG_INTERFACE,
    ProviderCapabilityCatalog,
)
from ipfs_datasets_py.logic.families.registry import (
    DEFAULT_REGISTRY,
    REGISTRY_INTERFACE as REGISTRY_V2_INTERFACE,
    LogicFamilyRegistry,
    LogicFamilyRegistryError,
)
from ipfs_datasets_py.logic.families.registry_v3 import (
    DEFAULT_REGISTRY_V3,
    FamilyLifecycleDisposition,
    LOGIC_FAMILY_REGISTRY_V3_INTERFACE,
    LogicFamilyRegistryV3,
)
from ipfs_datasets_py.logic.ir_core.identity import (
    CanonicalIdentity,
    canonical_identity,
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

CANONICAL_CATALOG_SNAPSHOT_INTERFACE: Final = "CanonicalLogicCatalogSnapshot@1"
CANONICAL_CATALOG_SNAPSHOT_SCHEMA: Final = "logic-canonical-catalog-snapshot/v1"
CANONICAL_CATALOG_SNAPSHOT_VERSION: Final = "1.0.0"
CANONICAL_CATALOG_TASK_ID: Final = "LPC-020"
CANONICAL_CATALOG_GOAL_ID: Final = "LPC-G020"
CANONICAL_CATALOG_IDENTITY_DOMAIN: Final = "logic.families.canonical_catalog"


class CatalogPublicationStage(str, Enum):
    """Publication ladder from identity-exists through production-admitted.

    Stages are ordered from weakest presence to strongest admission.  Snapshot
    composition never auto-promotes an identity to :attr:`PRODUCTION_ADMITTED`
    from declaration or catalog presence alone.
    """

    IDENTITY_EXISTS = "identity_exists"
    DECLARED = "declared"
    DISCOVERABLE = "discoverable"
    PARSE_PRINT = "parse_print"
    CONTROLLED_EXECUTABLE = "controlled_executable"
    SHADOW = "shadow"
    CANARY = "canary"
    PRODUCTION_ADMITTED = "production_admitted"


PUBLICATION_LADDER: Final[tuple[CatalogPublicationStage, ...]] = (
    CatalogPublicationStage.IDENTITY_EXISTS,
    CatalogPublicationStage.DECLARED,
    CatalogPublicationStage.DISCOVERABLE,
    CatalogPublicationStage.PARSE_PRINT,
    CatalogPublicationStage.CONTROLLED_EXECUTABLE,
    CatalogPublicationStage.SHADOW,
    CatalogPublicationStage.CANARY,
    CatalogPublicationStage.PRODUCTION_ADMITTED,
)

_STAGE_RANK: Final[Mapping[CatalogPublicationStage, int]] = MappingProxyType(
    {stage: index for index, stage in enumerate(PUBLICATION_LADDER)}
)


class CanonicalCatalogError(ValueError):
    """Raised when the canonical catalog snapshot is malformed."""


class UnknownCatalogIdentityError(CanonicalCatalogError, KeyError):
    """Raised when a requested catalog identity cannot be resolved."""


class CatalogCompositionError(CanonicalCatalogError):
    """Raised when composed layers contradict each other."""


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CanonicalCatalogError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise CanonicalCatalogError(f"{field_name} must not contain NUL bytes")
    return value


def _namespace_values(
    namespaces: LogicIdentityNamespaces,
    kind: NamespaceKind,
) -> tuple[str, ...]:
    return tuple(
        binding.value for binding in namespaces.bindings(kind)
    )


def _disposition_to_stage(
    disposition: FamilyLifecycleDisposition | str,
) -> CatalogPublicationStage:
    if not isinstance(disposition, FamilyLifecycleDisposition):
        try:
            disposition = FamilyLifecycleDisposition(str(disposition))
        except ValueError as error:
            raise CanonicalCatalogError(
                f"unknown publication disposition {disposition!r}"
            ) from error
    if disposition is FamilyLifecycleDisposition.CONTROLLED_EXECUTABLE:
        return CatalogPublicationStage.CONTROLLED_EXECUTABLE
    if disposition is FamilyLifecycleDisposition.PARSE_PRINT:
        return CatalogPublicationStage.PARSE_PRINT
    return CatalogPublicationStage.DECLARED


@dataclass(frozen=True, slots=True)
class CanonicalLogicCatalogSnapshot:
    """Immutable composition of all reviewed logic-family catalog layers.

    Interface: ``CanonicalLogicCatalogSnapshot@1``.

    Layers remain typed and distinct.  This snapshot is a composition root,
    not a registry v4 rename and not a flattened untyped dictionary.
    """

    taxonomy: LogicFamilyRegistry
    namespaces: LogicIdentityNamespaces
    aliases: LogicAliasRegistry
    publication: LogicFamilyRegistryV3
    profiles: LogicProfileCatalogV3
    providers: ProviderCapabilityCatalog
    matrix: ProviderCapabilityMatrixV2
    generated: GeneratedProviderTranslationCatalog
    version: str = CANONICAL_CATALOG_SNAPSHOT_VERSION
    schema_version: str = CANONICAL_CATALOG_SNAPSHOT_SCHEMA
    task_id: str = CANONICAL_CATALOG_TASK_ID
    goal_id: str = CANONICAL_CATALOG_GOAL_ID
    notes: str = (
        "Immutable composition of taxonomy, namespaces, aliases, publication, "
        "profiles, providers, matrix, translations, and content identity. "
        "Declaration never implies executability; production admission is never "
        "inferred from catalog presence."
    )

    INTERFACE: ClassVar[str] = CANONICAL_CATALOG_SNAPSHOT_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.taxonomy, LogicFamilyRegistry):
            raise CanonicalCatalogError("taxonomy must be a LogicFamilyRegistry")
        if not isinstance(self.namespaces, LogicIdentityNamespaces):
            raise CanonicalCatalogError(
                "namespaces must be a LogicIdentityNamespaces"
            )
        if not isinstance(self.aliases, LogicAliasRegistry):
            raise CanonicalCatalogError("aliases must be a LogicAliasRegistry")
        if not isinstance(self.publication, LogicFamilyRegistryV3):
            raise CanonicalCatalogError(
                "publication must be a LogicFamilyRegistryV3"
            )
        if not isinstance(self.profiles, LogicProfileCatalogV3):
            raise CanonicalCatalogError(
                "profiles must be a LogicProfileCatalogV3"
            )
        if not isinstance(self.providers, ProviderCapabilityCatalog):
            raise CanonicalCatalogError(
                "providers must be a ProviderCapabilityCatalog"
            )
        if not isinstance(self.matrix, ProviderCapabilityMatrixV2):
            raise CanonicalCatalogError(
                "matrix must be a ProviderCapabilityMatrixV2"
            )
        if not isinstance(self.generated, GeneratedProviderTranslationCatalog):
            raise CanonicalCatalogError(
                "generated must be a GeneratedProviderTranslationCatalog"
            )
        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != CANONICAL_CATALOG_SNAPSHOT_SCHEMA:
            raise CanonicalCatalogError(
                f"unsupported snapshot schema {self.schema_version!r}"
            )
        object.__setattr__(self, "task_id", _text(self.task_id, "task_id"))
        object.__setattr__(self, "goal_id", _text(self.goal_id, "goal_id"))
        object.__setattr__(
            self, "notes", _text(self.notes, "notes") if self.notes else ""
        )

    # ------------------------------------------------------------------
    # Layer projections (typed, non-flattened)
    # ------------------------------------------------------------------

    @property
    def interface(self) -> str:
        return self.INTERFACE

    @property
    def properties(self) -> tuple[str, ...]:
        """Property/obligation identities from the namespace layer."""

        taxonomy_ids = tuple(sorted(self.taxonomy.properties))
        namespace_ids = _namespace_values(self.namespaces, NamespaceKind.PROPERTY)
        return tuple(sorted(set(taxonomy_ids) | set(namespace_ids)))

    @property
    def views(self) -> tuple[str, ...]:
        return _namespace_values(self.namespaces, NamespaceKind.VIEW)

    @property
    def notations(self) -> tuple[str, ...]:
        return _namespace_values(self.namespaces, NamespaceKind.NOTATION)

    @property
    def encodings(self) -> tuple[str, ...]:
        return _namespace_values(self.namespaces, NamespaceKind.ENCODING)

    @property
    def provider_ids(self) -> tuple[str, ...]:
        namespace_ids = _namespace_values(self.namespaces, NamespaceKind.PROVIDER)
        catalog_ids = tuple(sorted(self.providers.provider_ids))
        matrix_ids = tuple(self.matrix.provider_ids)
        generated_ids = tuple(self.generated.provider_ids)
        return tuple(
            sorted(set(namespace_ids) | set(catalog_ids) | set(matrix_ids) | set(generated_ids))
        )

    @property
    def lanes(self) -> tuple[str, ...]:
        namespace_ids = _namespace_values(self.namespaces, NamespaceKind.LANE)
        matrix_ids = tuple(self.matrix.lane_ids)
        return tuple(sorted(set(namespace_ids) | set(matrix_ids)))

    @property
    def evidence(self) -> tuple[str, ...]:
        taxonomy_ids = tuple(sorted(self.taxonomy.evidence))
        namespace_ids = _namespace_values(self.namespaces, NamespaceKind.EVIDENCE)
        return tuple(sorted(set(taxonomy_ids) | set(namespace_ids)))

    @property
    def translations(self) -> tuple[str, ...]:
        taxonomy_ids = tuple(sorted(self.taxonomy.translations))
        generated_ids = tuple(self.generated.translation_ids)
        return tuple(sorted(set(taxonomy_ids) | set(generated_ids)))

    @property
    def family_ids(self) -> tuple[str, ...]:
        taxonomy_ids = tuple(sorted(self.taxonomy.families))
        namespace_ids = _namespace_values(self.namespaces, NamespaceKind.FAMILY)
        publication_ids = tuple(self.publication.family_ids)
        return tuple(
            sorted(set(taxonomy_ids) | set(namespace_ids) | set(publication_ids))
        )

    @property
    def profile_ids(self) -> tuple[str, ...]:
        namespace_ids = _namespace_values(self.namespaces, NamespaceKind.PROFILE)
        catalog_ids = tuple(self.profiles.profile_ids)
        return tuple(sorted(set(namespace_ids) | set(catalog_ids)))

    @property
    def versions(self) -> Mapping[str, str]:
        """Deterministic layer version envelope."""

        return MappingProxyType(
            {
                "aliases": self.aliases.version,
                "generated": self.generated.version,
                "matrix": self.matrix.version,
                "namespaces": self.namespaces.version,
                "profiles": self.profiles.version,
                "providers": self.providers.version,
                "publication": self.publication.version,
                "snapshot": self.version,
                "taxonomy": self.taxonomy.version,
            }
        )

    @property
    def layer_interfaces(self) -> Mapping[str, str]:
        """Semantic role → owning interface identity (typed, not flattened)."""

        return MappingProxyType(
            {
                "aliases": ALIAS_INTERFACE,
                "generated": GENERATED_PROVIDER_TRANSLATION_CATALOG_INTERFACE,
                "matrix": MATRIX_V2_INTERFACE,
                "namespaces": NAMESPACE_INTERFACE,
                "profiles": LOGIC_PROFILE_CATALOG_V3_INTERFACE,
                "providers": PROVIDER_CATALOG_INTERFACE,
                "publication": LOGIC_FAMILY_REGISTRY_V3_INTERFACE,
                "snapshot": CANONICAL_CATALOG_SNAPSHOT_INTERFACE,
                "taxonomy": REGISTRY_V2_INTERFACE,
            }
        )

    # ------------------------------------------------------------------
    # Publication ladder
    # ------------------------------------------------------------------

    def publication_stage(self, family_id: str) -> CatalogPublicationStage:
        """Return the highest admitted publication stage for *family_id*.

        The ladder is fail-closed: unknown identities raise, and
        production-admitted is never inferred from presence alone.
        """

        if not isinstance(family_id, str) or not family_id.strip():
            raise CanonicalCatalogError("family_id must be a non-empty string")
        key = family_id.strip()

        if key in self.publication:
            return _disposition_to_stage(self.publication.get(key).disposition)

        try:
            self.taxonomy.resolve(key)
        except LogicFamilyRegistryError:
            pass
        else:
            return CatalogPublicationStage.DECLARED

        if self.namespaces.contains(NamespaceKind.FAMILY, key):
            return CatalogPublicationStage.IDENTITY_EXISTS

        raise UnknownCatalogIdentityError(
            f"unknown catalog family identity {key!r}"
        )

    def stage_at_least(
        self,
        family_id: str,
        minimum: CatalogPublicationStage | str,
    ) -> bool:
        """True when *family_id* reaches at least *minimum* on the ladder."""

        if not isinstance(minimum, CatalogPublicationStage):
            minimum = CatalogPublicationStage(str(minimum))
        current = self.publication_stage(family_id)
        return _STAGE_RANK[current] >= _STAGE_RANK[minimum]

    def is_production_admitted(self, family_id: str) -> bool:
        """Production admission is never inferred from catalog presence."""

        # Resolve to ensure the identity is known; presence still cannot admit.
        self.publication_stage(family_id)
        return False

    def claims_executability(self, family_id: str) -> bool:
        """True only when publication lists explicit executable features."""

        if family_id not in self.publication:
            return False
        return self.publication.claims_executability(family_id)

    def presence_implies_executability(self) -> bool:
        """Hard safety floor shared with registry v3 / profile catalog v3."""

        return False

    def presence_implies_production_admission(self) -> bool:
        """Catalog presence never grants production admission."""

        return False

    # ------------------------------------------------------------------
    # Validation / composition integrity
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """Fail closed when composed layers contradict each other."""

        if self.presence_implies_executability():
            raise CatalogCompositionError(
                "snapshot must not imply executability from presence"
            )
        if self.presence_implies_production_admission():
            raise CatalogCompositionError(
                "snapshot must not imply production admission from presence"
            )
        if self.publication.presence_implies_executability():
            raise CatalogCompositionError(
                "publication layer incorrectly implies executability"
            )
        if self.profiles.presence_implies_executability():
            raise CatalogCompositionError(
                "profile layer incorrectly implies executability"
            )

        # Taxonomy families must remain distinct from the publication ladder.
        for family_id in self.taxonomy.families:
            stage = self.publication_stage(family_id)
            if stage is CatalogPublicationStage.PRODUCTION_ADMITTED:
                raise CatalogCompositionError(
                    f"family {family_id!r} incorrectly production-admitted"
                )

        # Published families must resolve on the ladder without inventing stages.
        for family_id in self.publication.family_ids:
            stage = self.publication_stage(family_id)
            if stage not in PUBLICATION_LADDER:
                raise CatalogCompositionError(
                    f"family {family_id!r} has unknown publication stage {stage!r}"
                )
            if (
                stage is CatalogPublicationStage.CONTROLLED_EXECUTABLE
                and not self.claims_executability(family_id)
            ):
                raise CatalogCompositionError(
                    f"controlled_executable family {family_id!r} claims no "
                    "executable features"
                )

        # Profile catalog must stay aligned with publication family ids.
        self.profiles.validate_against_registry(self.publication)
        self.publication.validate_against_baseline(self.taxonomy)
        self.matrix.validate_against_catalog(self.providers)
        self.generated.validate_closure(
            registry=self.taxonomy,
            baseline=self.providers,
        )

        # Namespace roles required by LPC-020 must remain populated and distinct.
        for kind in (
            NamespaceKind.FAMILY,
            NamespaceKind.PROFILE,
            NamespaceKind.PROPERTY,
            NamespaceKind.VIEW,
            NamespaceKind.NOTATION,
            NamespaceKind.ENCODING,
            NamespaceKind.PROVIDER,
            NamespaceKind.LANE,
            NamespaceKind.EVIDENCE,
        ):
            if not _namespace_values(self.namespaces, kind):
                raise CatalogCompositionError(
                    f"namespace layer missing identities for {kind.value!r}"
                )

        # Every composed projection required by LPC-020 must be non-empty.
        for name, values in (
            ("properties", self.properties),
            ("views", self.views),
            ("notations", self.notations),
            ("encodings", self.encodings),
            ("providers", self.provider_ids),
            ("lanes", self.lanes),
            ("evidence", self.evidence),
            ("translations", self.translations),
            ("profiles", self.profile_ids),
            ("families", self.family_ids),
        ):
            if not values:
                raise CatalogCompositionError(
                    f"snapshot composition missing {name}"
                )

        # Content root must be reproducible (identity computes cleanly).
        identity = self.content_identity()
        if not identity.digest.startswith("sha256:") or not identity.cid:
            raise CatalogCompositionError(
                "snapshot content identity is incomplete"
            )

    # ------------------------------------------------------------------
    # Content identity / serialization
    # ------------------------------------------------------------------

    def layer_envelope(self) -> dict[str, Any]:
        """Deterministic composition envelope used for content identity."""

        return {
            "aliases": self.aliases.to_dict(),
            "encodings": list(self.encodings),
            "evidence": list(self.evidence),
            "family_ids": list(self.family_ids),
            "generated": self.generated.to_dict(),
            "goal_id": self.goal_id,
            "interface": self.interface,
            "lanes": list(self.lanes),
            "layer_interfaces": dict(self.layer_interfaces),
            "matrix": self.matrix.to_dict(),
            "namespaces": self.namespaces.to_dict(),
            "notations": list(self.notations),
            "notes": self.notes,
            "presence_implies_executability": self.presence_implies_executability(),
            "presence_implies_production_admission": (
                self.presence_implies_production_admission()
            ),
            "profile_ids": list(self.profile_ids),
            "profiles": self.profiles.to_dict(),
            "properties": list(self.properties),
            "provider_ids": list(self.provider_ids),
            "providers": self.providers.to_dict(),
            "publication": self.publication.to_dict(),
            "publication_ladder": [stage.value for stage in PUBLICATION_LADDER],
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "taxonomy": self.taxonomy.to_dict(),
            "translations": list(self.translations),
            "version": self.version,
            "versions": dict(self.versions),
            "views": list(self.views),
        }

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible snapshot envelope with stable key ordering."""

        return self.layer_envelope()

    def to_json(self, *, indent: int | None = None) -> str:
        separators = None if indent is not None else (",", ":")
        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            indent=indent,
            separators=separators,
            sort_keys=True,
        )

    def content_identity(self) -> CanonicalIdentity:
        """Return the reproducible content root for this snapshot."""

        return canonical_identity(
            self.layer_envelope(),
            domain=CANONICAL_CATALOG_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def content_root(self) -> str:
        """Stable CIDv1 string for the composed catalog root."""

        return self.content_identity().cid

    @property
    def content_digest(self) -> str:
        """Stable ``sha256:`` digest for the composed catalog root."""

        return self.content_identity().digest


def build_canonical_logic_catalog_snapshot(
    *,
    taxonomy: LogicFamilyRegistry | None = None,
    namespaces: LogicIdentityNamespaces | None = None,
    aliases: LogicAliasRegistry | None = None,
    publication: LogicFamilyRegistryV3 | None = None,
    profiles: LogicProfileCatalogV3 | None = None,
    providers: ProviderCapabilityCatalog | None = None,
    matrix: ProviderCapabilityMatrixV2 | None = None,
    generated: GeneratedProviderTranslationCatalog | None = None,
    validate: bool = True,
) -> CanonicalLogicCatalogSnapshot:
    """Compose the sealed default layers into one immutable snapshot."""

    snapshot = CanonicalLogicCatalogSnapshot(
        taxonomy=taxonomy if taxonomy is not None else DEFAULT_REGISTRY,
        namespaces=(
            namespaces if namespaces is not None else BASELINE_NAMESPACES
        ),
        aliases=aliases if aliases is not None else BASELINE_ALIAS_REGISTRY,
        publication=(
            publication if publication is not None else DEFAULT_REGISTRY_V3
        ),
        profiles=(
            profiles if profiles is not None else DEFAULT_PROFILE_CATALOG_V3
        ),
        providers=(
            providers if providers is not None else BASELINE_PROVIDER_CATALOG
        ),
        matrix=(
            matrix
            if matrix is not None
            else BASELINE_PROVIDER_CAPABILITY_MATRIX_V2
        ),
        generated=(
            generated if generated is not None else DEFAULT_GENERATED_CATALOG
        ),
    )
    if validate:
        snapshot.validate()
    return snapshot


DEFAULT_CANONICAL_CATALOG_SNAPSHOT: Final[CanonicalLogicCatalogSnapshot] = (
    build_canonical_logic_catalog_snapshot(validate=True)
)


__all__ = [
    "CANONICAL_CATALOG_GOAL_ID",
    "CANONICAL_CATALOG_IDENTITY_DOMAIN",
    "CANONICAL_CATALOG_SNAPSHOT_INTERFACE",
    "CANONICAL_CATALOG_SNAPSHOT_SCHEMA",
    "CANONICAL_CATALOG_SNAPSHOT_VERSION",
    "CANONICAL_CATALOG_TASK_ID",
    "CatalogCompositionError",
    "CatalogPublicationStage",
    "CanonicalCatalogError",
    "CanonicalLogicCatalogSnapshot",
    "DEFAULT_CANONICAL_CATALOG_SNAPSHOT",
    "PUBLICATION_LADDER",
    "UnknownCatalogIdentityError",
    "build_canonical_logic_catalog_snapshot",
]
