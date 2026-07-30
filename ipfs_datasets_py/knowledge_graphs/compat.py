"""Versioned knowledge-graph compatibility, deprecation, and migration policy.

**Task:** ``KGP-034`` — Publish compatibility, migration, and deprecation runbooks  
**Policy version:** ``kg-compatibility/v1``  
**Companion ADR:** ``docs/architecture/knowledge_graphs_compatibility.md``  
**Runbooks:** ``docs/migration/knowledge_graphs/``,
``docs/operations/knowledge_graphs_release.md``

This module is the **executable** source of truth for:

* compatibility tiers (``T0``–``T3``);
* adopt / adapt / deprecate dispositions for legacy graph classes and paths;
* warning and removal windows (calendar + minimum minor-release floor);
* producer migration prerequisites and phase gates;
* storage-profile selection vocabulary aligned with ``GraphTarget``;
* helpers that emit versioned :class:`DeprecationWarning` messages and refuse
  same-release warn+remove violations.

Normative rules (also documented in the migration runbooks):

1. New public APIs **must** be tier ``T0`` (``GraphService`` + ``GraphTarget``).
2. **Do not** remove an import or data reader in the same release that first
   warns about it (``SAME_RELEASE_WARN_REMOVE`` is forbidden).
3. Minimum public-name warn period is **one minor release** after warn
   instrumentation is on by default, unless a security receipt requires faster
   removal.
4. Producers remain authoritative until stage-6 corpus evidence passes.
5. Rollback is catalog-head CAS to the last verified immutable revision —
   never in-place conversion or deletion of legacy payloads.

This module has **no** optional backend imports so it is safe for package-root
and unit-test load paths.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Dict,
    Final,
    FrozenSet,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

# ---------------------------------------------------------------------------
# Schema stamps
# ---------------------------------------------------------------------------

POLICY_VERSION: Final = "kg-compatibility/v1"
POLICY_ID: Final = "kg-compatibility"
CANONICAL_SERVICE: Final = "GraphService"
CANONICAL_TARGET: Final = "GraphTarget"
ONE_SERVICE_RULE: Final = True

# Package minor versions used as warn/remove markers for the public surface.
# These are policy stamps, not dynamic package metadata lookups: tests and
# runbooks pin them so windows cannot silently drift.
PACKAGE_WARN_BASELINE: Final = "0.1.0"
PACKAGE_MIN_REMOVE_FLOOR: Final = "0.2.0"

# Calendar anchors for the KGP program (UTC dates, inclusive start of day).
ANNOUNCE_DATE: Final = "2026-07-29"
WARN_WINDOW_START: Final = "2026-07-29"
# Earliest calendar date a public T2 name may be removed under the default
# one-minor-release floor (coordinated with PACKAGE_MIN_REMOVE_FLOOR).
DEFAULT_REMOVAL_EARLIEST: Final = "2026-10-01"

# Storage profiles (must match GraphTarget / catalog / manifest contracts).
STORAGE_PROFILES: Final = frozenset({"parquet", "ipfs_ipld", "ipfs_kit", "hybrid"})
DEFAULT_STORAGE_PROFILE: Final = "parquet"

# Closed tier and disposition vocabularies.
TIERS: Final = ("T0", "T1", "T2", "T3")
DISPOSITIONS: Final = ("adopt", "adapt", "deprecate")

# Migration phase order (operator runbook + release gate).
MIGRATION_PHASES: Final = (
    "prerequisites",
    "backup",
    "dry_run",
    "shadow",
    "canary",
    "cutover",
    "rollback",  # always available; not a forward gate
)

FORWARD_PHASES: Final = (
    "prerequisites",
    "backup",
    "dry_run",
    "shadow",
    "canary",
    "cutover",
)


class CompatibilityTier(str, Enum):
    """What callers may rely on during the hardening program."""

    T0 = "T0"  # Canonical contract
    T1 = "T1"  # Supported adapter
    T2 = "T2"  # Compatibility shim (warns)
    T3 = "T3"  # Fixture / legacy only


class Disposition(str, Enum):
    """Adopt / adapt / deprecate disposition for a legacy component."""

    ADOPT = "adopt"
    ADAPT = "adapt"
    DEPRECATE = "deprecate"


class DeprecationPhase(str, Enum):
    """Lifecycle phase for a deprecated public name or path."""

    ANNOUNCE = "announce"
    WARN = "warn"
    SHADOW = "shadow"
    CANARY = "canary"
    REMOVE = "remove"


class CompatPolicyError(ValueError):
    """Invalid compatibility policy query or configuration."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Legacy component entries
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegacyEntry:
    """One legacy graph class or path under the compatibility map."""

    legacy_id: str
    component: str
    paths: Tuple[str, ...]
    disposition: str
    tier: str
    replacement: str
    secondary_disposition: Optional[str] = None
    public_tier: Optional[str] = None
    warn_since_version: Optional[str] = None
    remove_after_version: Optional[str] = None
    removal_earliest: Optional[str] = None
    notes: str = ""

    def __post_init__(self) -> None:
        if self.disposition not in DISPOSITIONS:
            raise CompatPolicyError(
                "BAD_DISPOSITION",
                f"disposition must be one of {DISPOSITIONS}, got {self.disposition!r}",
            )
        if self.tier not in TIERS:
            raise CompatPolicyError(
                "BAD_TIER",
                f"tier must be one of {TIERS}, got {self.tier!r}",
            )
        if self.public_tier is not None and self.public_tier not in TIERS:
            raise CompatPolicyError(
                "BAD_PUBLIC_TIER",
                f"public_tier must be one of {TIERS}, got {self.public_tier!r}",
            )
        if (
            self.secondary_disposition is not None
            and self.secondary_disposition not in DISPOSITIONS
        ):
            raise CompatPolicyError(
                "BAD_SECONDARY_DISPOSITION",
                f"secondary_disposition must be one of {DISPOSITIONS}",
            )
        if not self.paths:
            raise CompatPolicyError("EMPTY_PATHS", "paths must be non-empty")
        if not self.replacement:
            raise CompatPolicyError("EMPTY_REPLACEMENT", "replacement is required")

    @property
    def effective_public_tier(self) -> str:
        return self.public_tier or self.tier

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "legacy_id": self.legacy_id,
            "component": self.component,
            "paths": list(self.paths),
            "disposition": self.disposition,
            "tier": self.tier,
            "replacement": self.replacement,
        }
        if self.secondary_disposition is not None:
            payload["secondary_disposition"] = self.secondary_disposition
        if self.public_tier is not None:
            payload["public_tier"] = self.public_tier
        if self.warn_since_version is not None:
            payload["warn_since_version"] = self.warn_since_version
        if self.remove_after_version is not None:
            payload["remove_after_version"] = self.remove_after_version
        if self.removal_earliest is not None:
            payload["removal_earliest"] = self.removal_earliest
        if self.notes:
            payload["notes"] = self.notes
        return payload


def _legacy(
    legacy_id: str,
    *,
    component: str,
    paths: Sequence[str],
    disposition: str,
    tier: str,
    replacement: str,
    secondary_disposition: Optional[str] = None,
    public_tier: Optional[str] = None,
    warn_since_version: Optional[str] = None,
    remove_after_version: Optional[str] = None,
    removal_earliest: Optional[str] = None,
    notes: str = "",
) -> LegacyEntry:
    return LegacyEntry(
        legacy_id=legacy_id,
        component=component,
        paths=tuple(paths),
        disposition=disposition,
        tier=tier,
        replacement=replacement,
        secondary_disposition=secondary_disposition,
        public_tier=public_tier,
        warn_since_version=warn_since_version,
        remove_after_version=remove_after_version,
        removal_earliest=removal_earliest,
        notes=notes,
    )


# Five mandatory legacies from KGP-003 plus extended public shims.
_LEGACY_ENTRIES: Tuple[LegacyEntry, ...] = (
    _legacy(
        "graph_engine",
        component="GraphEngine",
        paths=("ipfs_datasets_py/knowledge_graphs/core/graph_engine.py",),
        disposition="adapt",
        tier="T1",
        replacement="GraphService query/write delegate",
        notes="Must not be the public multi-graph catalog.",
    ),
    _legacy(
        "extraction_knowledge_graph",
        component="extraction KnowledgeGraph",
        paths=("ipfs_datasets_py/knowledge_graphs/extraction/graph.py",),
        disposition="adapt",
        tier="T1",
        replacement="extract then publish via GraphService",
        notes="Extraction name= is not durable kg:// identity.",
    ),
    _legacy(
        "data_transformation_ipld_graph",
        component="data_transformation IPLD graph",
        paths=(
            "ipfs_datasets_py/processors/storage/ipld/knowledge_graph.py",
            "ipfs_datasets_py/knowledge_graphs/ipld.py",
        ),
        disposition="adapt",
        secondary_disposition="deprecate",
        tier="T1",
        public_tier="T2",
        warn_since_version=PACKAGE_WARN_BASELINE,
        remove_after_version=PACKAGE_MIN_REMOVE_FLOOR,
        removal_earliest=DEFAULT_REMOVAL_EARLIEST,
        replacement="GraphStore ipfs_ipld/ipfs_kit + manifests",
        notes="Public IPLDKnowledgeGraph identity is deprecated; codecs stay T1.",
    ),
    _legacy(
        "search_graph_data_sharded_car",
        component="search GraphData/sharded CAR",
        paths=(
            "ipfs_datasets_py/knowledge_graphs/migration/formats.py",
            "ipfs_datasets_py/search/graph_query/backends/sharded_car.py",
            "ipfs_datasets_py/search/graph_query/sharded_car",
        ),
        disposition="adopt",
        secondary_disposition="adapt",
        tier="T1",
        replacement="unified query backend + v1/v2 shard manifests",
        notes="Keep v1 readable while v2 manifests land.",
    ),
    _legacy(
        "knowledge_graph_manager",
        component="KnowledgeGraphManager",
        paths=("ipfs_datasets_py/core_operations/knowledge_graph_manager.py",),
        disposition="deprecate",
        tier="T2",
        warn_since_version=PACKAGE_WARN_BASELINE,
        remove_after_version=PACKAGE_MIN_REMOVE_FLOOR,
        removal_earliest=DEFAULT_REMOVAL_EARLIEST,
        replacement="GraphService Client/AsyncClient",
        notes="Mandatory deprecation for T0 certification (one-service rule).",
    ),
    _legacy(
        "legacy_knowledge_graph_extraction_module",
        component="knowledge_graph_extraction shim",
        paths=("ipfs_datasets_py/knowledge_graphs/knowledge_graph_extraction.py",),
        disposition="deprecate",
        tier="T2",
        warn_since_version=PACKAGE_WARN_BASELINE,
        remove_after_version=PACKAGE_MIN_REMOVE_FLOOR,
        removal_earliest=DEFAULT_REMOVAL_EARLIEST,
        replacement="ipfs_datasets_py.knowledge_graphs.extraction",
    ),
    _legacy(
        "legacy_root_reexports",
        component="package-root GraphDatabase/GraphEngine re-exports",
        paths=("ipfs_datasets_py/knowledge_graphs/__init__.py",),
        disposition="deprecate",
        tier="T2",
        warn_since_version=PACKAGE_WARN_BASELINE,
        remove_after_version=PACKAGE_MIN_REMOVE_FLOOR,
        removal_earliest=DEFAULT_REMOVAL_EARLIEST,
        replacement="Client / AsyncClient / GraphService (T0 exports)",
        notes="Attribute access emits DeprecationWarning; may leave __all__.",
    ),
    _legacy(
        "advanced_knowledge_extractor_shim",
        component="advanced_knowledge_extractor shim",
        paths=("ipfs_datasets_py/knowledge_graphs/advanced_knowledge_extractor.py",),
        disposition="deprecate",
        tier="T2",
        warn_since_version=PACKAGE_WARN_BASELINE,
        remove_after_version=PACKAGE_MIN_REMOVE_FLOOR,
        removal_earliest=DEFAULT_REMOVAL_EARLIEST,
        replacement="ipfs_datasets_py.knowledge_graphs.extraction",
    ),
    _legacy(
        "nested_lift_checkout_trees",
        component="nested lift_coding ipfs_datasets_py checkouts",
        paths=(
            "lift_coding/external/ipfs_datasets",
            "lift_coding/hallucinate_app/ipfs_datasets_py",
        ),
        disposition="deprecate",
        tier="T3",
        replacement="canonical ipfs_datasets_py tree only",
        notes="Fixture-only; never implementation source of truth.",
    ),
)

LEGACY_MAP: Final[Mapping[str, LegacyEntry]] = MappingProxyType(
    {entry.legacy_id: entry for entry in _LEGACY_ENTRIES}
)

# Mandatory five-way map keys (KGP-003 acceptance).
MANDATORY_LEGACY_IDS: Final = frozenset(
    {
        "graph_engine",
        "extraction_knowledge_graph",
        "data_transformation_ipld_graph",
        "search_graph_data_sharded_car",
        "knowledge_graph_manager",
    }
)

# Disposition expected for the mandatory five (primary disposition only).
MANDATORY_DISPOSITIONS: Final = MappingProxyType(
    {
        "graph_engine": "adapt",
        "extraction_knowledge_graph": "adapt",
        "data_transformation_ipld_graph": "adapt",
        "search_graph_data_sharded_car": "adopt",
        "knowledge_graph_manager": "deprecate",
    }
)


# ---------------------------------------------------------------------------
# Producer prerequisites (corpus inventory)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProducerPrerequisites:
    """Producer-specific gates before shadow / canary / cutover."""

    producer_id: str
    display_name: str
    owner: str
    migration_risk: str
    storage_profile_default: str
    required_evidence: Tuple[str, ...]
    artifact_notes: str
    fixture_only_producer: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "producer_id": self.producer_id,
            "display_name": self.display_name,
            "owner": self.owner,
            "migration_risk": self.migration_risk,
            "storage_profile_default": self.storage_profile_default,
            "required_evidence": list(self.required_evidence),
            "artifact_notes": self.artifact_notes,
            "fixture_only_producer": self.fixture_only_producer,
        }


_PRODUCER_ENTRIES: Tuple[ProducerPrerequisites, ...] = (
    ProducerPrerequisites(
        producer_id="cvefixes_security_ir_graphrag",
        display_name="CVEfixes Security IR GraphRAG",
        owner="lift_coding (artifacts) + nested CVE producer (fixture-only code)",
        migration_risk="high",
        storage_profile_default="hybrid",
        required_evidence=(
            "differential_reader_parity",
            "shard_index_integrity",
            "backup_restore_proof",
            "load_soak_chaos_receipts",
            "ucan_negative_proof",
        ),
        artifact_notes="~1.5G release + 1.2G source Parquet; non-canonical producer.",
        fixture_only_producer=True,
    ),
    ProducerPrerequisites(
        producer_id="skillcenter_ir_graphrag",
        display_name="SkillCenter Intent IR GraphRAG",
        owner="canonical ipfs_datasets_py (logic/intent_ir/graphrag)",
        migration_risk="medium",
        storage_profile_default="hybrid",
        required_evidence=(
            "schema_v2_v3_compat",
            "graph_vector_bm25_parity",
            "differential_reader_parity",
            "backup_restore_proof",
        ),
        artifact_notes="CID-keyed Parquet + BM25 + optional FAISS; release v3 (v2 compat).",
    ),
    ProducerPrerequisites(
        producer_id="two11_retrieval_package",
        display_name="211-AI retrieval package knowledge graph",
        owner="211-AI",
        migration_risk="medium",
        storage_profile_default="hybrid",
        required_evidence=(
            "manifest_cid_alignment",
            "differential_reader_parity",
            "traversal_community_workloads",
            "backup_restore_proof",
        ),
        artifact_notes="48,851 nodes / 648,958 edges; retrieval_package layout.",
    ),
    ProducerPrerequisites(
        producer_id="two11_browser_graphrag",
        display_name="211-AI browser GraphRAG export",
        owner="211-AI",
        migration_risk="low",
        storage_profile_default="parquet",
        required_evidence=(
            "cid_alignment_with_retrieval_package",
            "smoke_shard_parity",
        ),
        artifact_notes="Small projection; must stay CID-aligned with retrieval package.",
    ),
    ProducerPrerequisites(
        producer_id="supervisor_objective_graph",
        display_name="Agent supervisor objective graph",
        owner="ipfs_accelerate_py",
        migration_risk="low",
        storage_profile_default="parquet",
        required_evidence=(
            "kind_extensibility",
            "provenance_roundtrip",
        ),
        artifact_notes="Supervisor remains authoritative; rapid incremental changes.",
    ),
    ProducerPrerequisites(
        producer_id="supervisor_code_evidence_graph",
        display_name="Supervisor code-evidence / AST graphs",
        owner="ipfs_accelerate_py",
        migration_risk="low",
        storage_profile_default="parquet",
        required_evidence=(
            "blob_immutability",
            "path_projection_parity",
        ),
        artifact_notes="AST index + code-evidence; content-addressed blobs.",
    ),
)

PRODUCER_MAP: Final[Mapping[str, ProducerPrerequisites]] = MappingProxyType(
    {p.producer_id: p for p in _PRODUCER_ENTRIES}
)


# ---------------------------------------------------------------------------
# Warning / removal windows
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WarningRemovalWindow:
    """Versioned warn/remove schedule for a legacy id or public path."""

    legacy_id: str
    phase: str
    warn_since_version: str
    remove_after_version: str
    removal_earliest: str
    min_warn_minor_releases: int = 1
    same_release_warn_and_remove_forbidden: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "legacy_id": self.legacy_id,
            "phase": self.phase,
            "warn_since_version": self.warn_since_version,
            "remove_after_version": self.remove_after_version,
            "removal_earliest": self.removal_earliest,
            "min_warn_minor_releases": self.min_warn_minor_releases,
            "same_release_warn_and_remove_forbidden": (
                self.same_release_warn_and_remove_forbidden
            ),
        }


def _parse_semver(version: str) -> Tuple[int, int, int]:
    text = str(version).strip()
    if text.startswith("v"):
        text = text[1:]
    parts = text.split(".")
    if len(parts) < 2:
        raise CompatPolicyError(
            "BAD_VERSION",
            f"expected major.minor[.patch], got {version!r}",
        )
    try:
        major = int(parts[0])
        minor = int(parts[1])
        patch = int(parts[2]) if len(parts) > 2 else 0
    except ValueError as exc:
        raise CompatPolicyError(
            "BAD_VERSION",
            f"non-integer semver component in {version!r}",
        ) from exc
    if major < 0 or minor < 0 or patch < 0:
        raise CompatPolicyError("BAD_VERSION", f"negative component in {version!r}")
    return major, minor, patch


def compare_versions(left: str, right: str) -> int:
    """Return -1 / 0 / 1 for ``left < = > right`` (semver major.minor.patch)."""

    a = _parse_semver(left)
    b = _parse_semver(right)
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def minor_releases_between(start: str, end: str) -> int:
    """Count minor-release boundaries crossed from *start* to *end* (same major).

    Examples: ``0.1.0 → 0.2.0`` is ``1``; ``0.1.0 → 0.1.5`` is ``0``;
    ``0.1.0 → 0.3.1`` is ``2``. Returns ``0`` when *end* <= *start*.
    Raises when majors differ (policy windows do not span major bumps
    without an explicit security receipt).
    """

    a = _parse_semver(start)
    b = _parse_semver(end)
    if b[0] != a[0]:
        raise CompatPolicyError(
            "MAJOR_CROSSING",
            f"cannot count minor releases across majors: {start!r} → {end!r}",
        )
    if b <= a:
        return 0
    return b[1] - a[1]


def _minor_distance(start: str, end: str) -> int:
    """Alias for :func:`minor_releases_between` (internal call sites)."""

    return minor_releases_between(start, end)


def window_for_legacy(legacy_id: str) -> Optional[WarningRemovalWindow]:
    """Return the warn/remove window for a legacy id, if it is on a warn path."""

    entry = LEGACY_MAP.get(legacy_id)
    if entry is None:
        raise CompatPolicyError("UNKNOWN_LEGACY", f"unknown legacy_id {legacy_id!r}")
    if entry.warn_since_version is None or entry.remove_after_version is None:
        return None
    phase = DeprecationPhase.WARN.value
    if entry.effective_public_tier == "T3":
        phase = DeprecationPhase.ANNOUNCE.value
    return WarningRemovalWindow(
        legacy_id=legacy_id,
        phase=phase,
        warn_since_version=entry.warn_since_version,
        remove_after_version=entry.remove_after_version,
        removal_earliest=entry.removal_earliest or DEFAULT_REMOVAL_EARLIEST,
        min_warn_minor_releases=1,
        same_release_warn_and_remove_forbidden=True,
    )


def all_warning_windows() -> List[WarningRemovalWindow]:
    """List warn/remove windows for every legacy that is on a deprecation track."""

    windows: List[WarningRemovalWindow] = []
    for legacy_id in LEGACY_MAP:
        window = window_for_legacy(legacy_id)
        if window is not None:
            windows.append(window)
    return windows


def removal_allowed(
    legacy_id: str,
    *,
    package_version: str,
    calendar_date: Optional[str] = None,
    security_receipt: bool = False,
) -> bool:
    """Whether *legacy_id* may be removed at *package_version*.

    Enforces:

    * known legacy id with a removal window;
    * package_version > warn_since_version (same-release warn+remove forbidden);
    * at least ``min_warn_minor_releases`` minor releases since warn, unless
      ``security_receipt`` is True;
    * optional calendar floor when ``calendar_date`` is provided.
    """

    window = window_for_legacy(legacy_id)
    if window is None:
        return False
    if compare_versions(package_version, window.warn_since_version) <= 0:
        # Same or earlier than first warn release → never remove.
        return False
    if window.same_release_warn_and_remove_forbidden:
        if package_version == window.warn_since_version:
            return False
    if not security_receipt:
        distance = _minor_distance(window.warn_since_version, package_version)
        if distance < window.min_warn_minor_releases:
            return False
        if compare_versions(package_version, window.remove_after_version) < 0:
            return False
        if calendar_date is not None and calendar_date < window.removal_earliest:
            return False
    return True


def same_release_warn_remove_forbidden(
    warn_version: str,
    remove_version: str,
) -> bool:
    """Return True when warn and remove share a release (policy violation)."""

    return compare_versions(warn_version, remove_version) == 0


# ---------------------------------------------------------------------------
# Storage profile helpers
# ---------------------------------------------------------------------------

STORAGE_PROFILE_GUIDANCE: Final = MappingProxyType(
    {
        "parquet": {
            "use_when": "Analytical corpora, local/lab reproducibility, HF-style shards",
            "notes": "Default profile; strong for bulk scan and offline fixtures",
        },
        "ipfs_ipld": {
            "use_when": "Content-addressed block graphs with direct IPLD DAGs",
            "notes": "Prefer when CID-native linking is the primary access path",
        },
        "ipfs_kit": {
            "use_when": "Production pin/fetch via ipfs_kit_py cluster integration",
            "notes": "Requires kit availability; same contract suite as other profiles",
        },
        "hybrid": {
            "use_when": "Parquet + vector/BM25 + sharded CAR/IPFS (SkillCenter, CVE, 211)",
            "notes": "Typical for GraphRAG producers with mixed retrieval surfaces",
        },
    }
)


def validate_storage_profile(profile: Optional[str]) -> Optional[str]:
    """Validate a storage profile; ``None`` means default at open time."""

    if profile is None:
        return None
    if profile not in STORAGE_PROFILES:
        raise CompatPolicyError(
            "BAD_STORAGE_PROFILE",
            f"storage_profile must be one of {sorted(STORAGE_PROFILES)}, got {profile!r}",
        )
    return profile


def resolve_storage_profile(profile: Optional[str]) -> str:
    """Return the effective storage profile (default ``parquet``)."""

    if profile is None or profile == "":
        return DEFAULT_STORAGE_PROFILE
    validated = validate_storage_profile(profile)
    assert validated is not None
    return validated


# ---------------------------------------------------------------------------
# Deprecation warning emission
# ---------------------------------------------------------------------------


def deprecation_message(legacy_id: str) -> str:
    """Build the standard DeprecationWarning text for a legacy id."""

    entry = get_legacy(legacy_id)
    window = window_for_legacy(legacy_id)
    parts = [
        f"{entry.component} is deprecated under {POLICY_VERSION} "
        f"(tier {entry.effective_public_tier}, disposition {entry.disposition}).",
        f"Use {entry.replacement} instead.",
    ]
    if window is not None:
        parts.append(
            f"Warned since package {window.warn_since_version}; "
            f"removal no earlier than {window.remove_after_version} "
            f"(calendar floor {window.removal_earliest})."
        )
    parts.append(
        "See docs/migration/knowledge_graphs/ and "
        "docs/architecture/knowledge_graphs_compatibility.md."
    )
    return " ".join(parts)


def warn_legacy(legacy_id: str, *, stacklevel: int = 2) -> None:
    """Emit a :class:`DeprecationWarning` for *legacy_id* (no-op for non-T2)."""

    entry = get_legacy(legacy_id)
    if entry.effective_public_tier not in {"T2", "T3"} and entry.disposition != "deprecate":
        return
    warnings.warn(deprecation_message(legacy_id), DeprecationWarning, stacklevel=stacklevel)


def get_legacy(legacy_id: str) -> LegacyEntry:
    """Return a legacy map entry or raise :class:`CompatPolicyError`."""

    try:
        return LEGACY_MAP[legacy_id]
    except KeyError as exc:
        raise CompatPolicyError(
            "UNKNOWN_LEGACY",
            f"unknown legacy_id {legacy_id!r}",
        ) from exc


def get_producer(producer_id: str) -> ProducerPrerequisites:
    """Return producer prerequisites or raise :class:`CompatPolicyError`."""

    try:
        return PRODUCER_MAP[producer_id]
    except KeyError as exc:
        raise CompatPolicyError(
            "UNKNOWN_PRODUCER",
            f"unknown producer_id {producer_id!r}",
        ) from exc


def list_legacy_ids() -> List[str]:
    return sorted(LEGACY_MAP.keys())


def list_producer_ids() -> List[str]:
    return sorted(PRODUCER_MAP.keys())


def legacy_ids_for_path(path: str) -> List[str]:
    """Return legacy ids whose registered paths match or prefix *path*."""

    needle = path.replace("\\", "/").strip()
    hits: List[str] = []
    for entry in LEGACY_MAP.values():
        for registered in entry.paths:
            reg = registered.replace("\\", "/")
            if needle == reg or needle.startswith(reg.rstrip("/") + "/") or reg in needle:
                hits.append(entry.legacy_id)
                break
    return hits


# ---------------------------------------------------------------------------
# Migration phase helpers
# ---------------------------------------------------------------------------


def phase_index(phase: str) -> int:
    """Index of a forward migration phase (raises for unknown / rollback)."""

    if phase == "rollback":
        raise CompatPolicyError(
            "ROLLBACK_NOT_FORWARD",
            "rollback is always available and is not a forward phase gate",
        )
    try:
        return FORWARD_PHASES.index(phase)
    except ValueError as exc:
        raise CompatPolicyError(
            "UNKNOWN_PHASE",
            f"unknown migration phase {phase!r}; expected one of {FORWARD_PHASES}",
        ) from exc


def can_enter_phase(
    target_phase: str,
    *,
    completed_phases: Iterable[str],
    producer_id: Optional[str] = None,
    evidence: Optional[Iterable[str]] = None,
) -> bool:
    """Whether *target_phase* may start given completed prior phases + evidence.

    ``rollback`` is always allowed. ``cutover`` additionally requires the
    producer's ``required_evidence`` set when *producer_id* is provided.
    """

    if target_phase == "rollback":
        return True
    target_i = phase_index(target_phase)
    completed = {str(p) for p in completed_phases}
    for prior in FORWARD_PHASES[:target_i]:
        if prior not in completed:
            return False
    if target_phase == "cutover" and producer_id is not None:
        producer = get_producer(producer_id)
        have = {str(e) for e in (evidence or ())}
        missing = set(producer.required_evidence) - have
        if missing:
            return False
    return True


# ---------------------------------------------------------------------------
# Policy export (machine-readable, ADR-aligned)
# ---------------------------------------------------------------------------


def policy_dict() -> Dict[str, Any]:
    """Full machine-readable policy document (JSON-serializable)."""

    legacy_map: Dict[str, Any] = {}
    for legacy_id, entry in LEGACY_MAP.items():
        body = {
            "component": entry.component,
            "paths": list(entry.paths),
            "disposition": entry.disposition,
            "tier": entry.tier,
            "replacement": entry.replacement,
        }
        if entry.secondary_disposition is not None:
            body["secondary_disposition"] = entry.secondary_disposition
        if entry.public_tier is not None:
            body["public_tier"] = entry.public_tier
        if entry.warn_since_version is not None:
            body["warn_since_version"] = entry.warn_since_version
        if entry.remove_after_version is not None:
            body["remove_after_version"] = entry.remove_after_version
        if entry.removal_earliest is not None:
            body["removal_earliest"] = entry.removal_earliest
        if entry.notes:
            body["notes"] = entry.notes
        legacy_map[legacy_id] = body

    return {
        "policy_version": POLICY_VERSION,
        "policy_id": POLICY_ID,
        "one_service_rule": ONE_SERVICE_RULE,
        "canonical_service": CANONICAL_SERVICE,
        "canonical_target": CANONICAL_TARGET,
        "tiers": list(TIERS),
        "dispositions": list(DISPOSITIONS),
        "migration_phases": list(MIGRATION_PHASES),
        "forward_phases": list(FORWARD_PHASES),
        "storage_profiles": sorted(STORAGE_PROFILES),
        "default_storage_profile": DEFAULT_STORAGE_PROFILE,
        "package_warn_baseline": PACKAGE_WARN_BASELINE,
        "package_min_remove_floor": PACKAGE_MIN_REMOVE_FLOOR,
        "announce_date": ANNOUNCE_DATE,
        "warn_window_start": WARN_WINDOW_START,
        "default_removal_earliest": DEFAULT_REMOVAL_EARLIEST,
        "same_release_warn_and_remove_forbidden": True,
        "min_warn_minor_releases": 1,
        "legacy_map": legacy_map,
        "warning_windows": [w.to_dict() for w in all_warning_windows()],
        "producers": {pid: p.to_dict() for pid, p in PRODUCER_MAP.items()},
        "storage_profile_guidance": {
            k: dict(v) for k, v in STORAGE_PROFILE_GUIDANCE.items()
        },
        "tier_rules": {
            "TIER-1": "New public APIs must be T0.",
            "TIER-2": "T1 modules must not invent durable graph identity outside the catalog.",
            "TIER-3": "T2 shims must warn on import or first use and document the T0 replacement.",
            "TIER-4": "T3 paths must not be selected by ambient MCP/CLI defaults.",
            "TIER-5": "Cross-surface conformance vectors run only against T0 behavior.",
        },
        "runbooks": {
            "migration": "docs/migration/knowledge_graphs/",
            "release": "docs/operations/knowledge_graphs_release.md",
            "operations": "docs/operations/knowledge_graphs_runbook.md",
            "compatibility_adr": "docs/architecture/knowledge_graphs_compatibility.md",
        },
    }


def assert_policy_invariants() -> None:
    """Raise :class:`CompatPolicyError` if the in-process policy is inconsistent.

    Used by unit tests and optionally by release tooling.
    """

    if POLICY_VERSION != "kg-compatibility/v1":
        raise CompatPolicyError("BAD_POLICY_VERSION", POLICY_VERSION)
    if not ONE_SERVICE_RULE:
        raise CompatPolicyError("ONE_SERVICE", "one_service_rule must be true")
    if CANONICAL_SERVICE != "GraphService" or CANONICAL_TARGET != "GraphTarget":
        raise CompatPolicyError("CANONICAL", "canonical service/target mismatch")
    missing = MANDATORY_LEGACY_IDS - set(LEGACY_MAP)
    if missing:
        raise CompatPolicyError("MISSING_LEGACY", f"missing mandatory legacies: {sorted(missing)}")
    for legacy_id, expected in MANDATORY_DISPOSITIONS.items():
        actual = LEGACY_MAP[legacy_id].disposition
        if actual != expected:
            raise CompatPolicyError(
                "DISPOSITION_DRIFT",
                f"{legacy_id}: expected disposition {expected!r}, got {actual!r}",
            )
    for entry in LEGACY_MAP.values():
        if entry.tier not in TIERS:
            raise CompatPolicyError("BAD_TIER", entry.legacy_id)
        if entry.disposition not in DISPOSITIONS:
            raise CompatPolicyError("BAD_DISPOSITION", entry.legacy_id)
        if entry.warn_since_version and entry.remove_after_version:
            if same_release_warn_remove_forbidden(
                entry.warn_since_version,
                entry.remove_after_version,
            ):
                raise CompatPolicyError(
                    "SAME_RELEASE_WARN_REMOVE",
                    f"{entry.legacy_id}: warn and remove share version "
                    f"{entry.warn_since_version}",
                )
            if compare_versions(entry.remove_after_version, entry.warn_since_version) <= 0:
                raise CompatPolicyError(
                    "REMOVE_BEFORE_WARN",
                    f"{entry.legacy_id}: remove_after must be after warn_since",
                )
    for profile in STORAGE_PROFILES:
        if profile not in STORAGE_PROFILE_GUIDANCE:
            raise CompatPolicyError("STORAGE_GUIDANCE", f"missing guidance for {profile}")
    for producer in PRODUCER_MAP.values():
        if producer.storage_profile_default not in STORAGE_PROFILES:
            raise CompatPolicyError(
                "PRODUCER_PROFILE",
                f"{producer.producer_id}: bad default profile",
            )


__all__ = [
    "POLICY_VERSION",
    "POLICY_ID",
    "CANONICAL_SERVICE",
    "CANONICAL_TARGET",
    "ONE_SERVICE_RULE",
    "PACKAGE_WARN_BASELINE",
    "PACKAGE_MIN_REMOVE_FLOOR",
    "ANNOUNCE_DATE",
    "WARN_WINDOW_START",
    "DEFAULT_REMOVAL_EARLIEST",
    "STORAGE_PROFILES",
    "DEFAULT_STORAGE_PROFILE",
    "TIERS",
    "DISPOSITIONS",
    "MIGRATION_PHASES",
    "FORWARD_PHASES",
    "CompatibilityTier",
    "Disposition",
    "DeprecationPhase",
    "CompatPolicyError",
    "LegacyEntry",
    "LEGACY_MAP",
    "MANDATORY_LEGACY_IDS",
    "MANDATORY_DISPOSITIONS",
    "ProducerPrerequisites",
    "PRODUCER_MAP",
    "WarningRemovalWindow",
    "STORAGE_PROFILE_GUIDANCE",
    "compare_versions",
    "minor_releases_between",
    "window_for_legacy",
    "all_warning_windows",
    "removal_allowed",
    "same_release_warn_remove_forbidden",
    "validate_storage_profile",
    "resolve_storage_profile",
    "deprecation_message",
    "warn_legacy",
    "get_legacy",
    "get_producer",
    "list_legacy_ids",
    "list_producer_ids",
    "legacy_ids_for_path",
    "phase_index",
    "can_enter_phase",
    "policy_dict",
    "assert_policy_invariants",
]
