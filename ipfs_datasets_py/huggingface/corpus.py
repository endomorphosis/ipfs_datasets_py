"""Pinned, inventory-driven corpus ingest and sealed source/derivative manifests.

This module does not download Hub bytes and never executes repository scripts.
It seals a campaign corpus from the exact PGIR-004 inventory, the PGIR-010
source/lineage contracts, and optional locally injected snapshot bytes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Final

from ..logic.ir_core.canonical import canonical_json_bytes
from ..logic.ir_core.identity import cid_v1, cid_v1_from_digest
from ..logic.ir_core.provenance import SourceRef, SourceReviewStatus
from ..logic.ir_core.source_lineage import (
    CorpusManifest,
    DerivedArtifactRecord,
    LineageEdge,
    LineageGraph,
    LineageRelation,
    RightsDisposition,
    RightsRecord,
    SourceRecord,
    SourceRelease,
    TemporalCoverage,
)
from .release import HuggingFaceReleaseError, _normalize_relative_path


INVENTORY_SCHEMA: Final = "IRSourceReleaseInventory@1"
CORPUS_ROOT_SCHEMA: Final = "ir-sealed-corpus-root/v1"
PINSET_ID: Final = "JDAO-PINSET-1"
PATENT_SOURCE_GROUP_COUNT: Final = 2174
DEFAULT_MAX_FILE_BYTES: Final = 64 * 1024 * 1024
_SOURCE_ROLES: Final = frozenset({"source_candidate"})
_NON_SOURCE_ROLES: Final = frozenset(
    {
        "source_component",
        "source_projection",
        "derivative",
        "index",
        "metadata",
        "artifact",
        "unknown",
    }
)
_FAMILY_ALIASES: Final = (
    ("article", "articles"),
    ("translation", "translations"),
    ("proof", "proofs"),
    ("logic", "proofs"),
    ("vector", "vectors"),
    ("bm25", "bm25"),
    ("posting", "bm25"),
    ("term", "bm25"),
    ("graph", "graph"),
    ("cid", "cid-index"),
)


class CorpusBuildError(ValueError):
    """Raised when corpus ingest or sealing fails closed."""


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CorpusBuildError(f"{label} must be an object")
    return value


def _require_sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CorpusBuildError(f"{label} must be an array")
    return value


def _slug(value: str) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in text:
        text = text.replace("--", "-")
    if not text:
        raise CorpusBuildError("could not form a stable identifier slug")
    return text[:80]


def _family_of(observation_key: str) -> str:
    key = observation_key.lower()
    for needle, family in _FAMILY_ALIASES:
        if needle in key:
            return family
    return _slug(observation_key)


def _population_slug(lineage_group: str) -> str:
    head = lineage_group.split("@", 1)[0]
    if head.endswith("/patent-legal-source") or "patent-legal" in head:
        return "patent"
    if "netherlands" in head or "dutch" in head:
        return "dutch-law"
    return _slug(head.rsplit("/", 1)[-1])


def _rights_from_inventory(
    receipt: Mapping[str, Any],
    *,
    disposition: RightsDisposition,
) -> RightsRecord:
    return RightsRecord(
        disposition=disposition,
        license_expression=str(receipt.get("card_license") or "unknown"),
        source_rights_status=str(receipt.get("source_rights_status") or "unresolved"),
        transformation_rights_status=str(
            receipt.get("transformation_rights_status") or "unresolved"
        ),
        scope=str(receipt.get("scope") or "every named configuration"),
    )


def _temporal_from_coverage(coverage: Mapping[str, Any] | None) -> TemporalCoverage:
    cutoff = (coverage or {}).get("source_cutoff") if isinstance(coverage, Mapping) else None
    if not isinstance(cutoff, Mapping):
        return TemporalCoverage(cutoff_status="unknown", cutoff_value=None, observed_at_ms=None)
    status = str(cutoff.get("status") or "unknown")
    raw_value = cutoff.get("value")
    return TemporalCoverage(
        cutoff_status=status,
        cutoff_value=None if raw_value is None else str(raw_value),
        observed_at_ms=None,
    )


def _binding_digest(**payload: Any) -> str:
    return sha256(canonical_json_bytes(payload)).hexdigest()


def _disposition_of(repo: Mapping[str, Any]) -> str:
    decision = repo.get("configuration_decision")
    if isinstance(decision, Mapping) and decision.get("release_disposition"):
        return str(decision["release_disposition"])
    return str(repo.get("disposition") or "quarantine")


def _rights_disposition_of(repo: Mapping[str, Any]) -> RightsDisposition:
    decision = repo.get("configuration_decision")
    raw = None
    if isinstance(decision, Mapping):
        raw = decision.get("rights_disposition")
    if raw is None:
        receipt = repo.get("rights_receipt")
        if isinstance(receipt, Mapping):
            raw = receipt.get("decision")
    if raw is None:
        raw = repo.get("disposition")
    if raw in {"reject", "denied"}:
        return RightsDisposition.DENIED
    if raw == "admitted":
        return RightsDisposition.ADMITTED
    if raw == "unresolved":
        return RightsDisposition.UNRESOLVED
    return RightsDisposition.QUARANTINED


def load_release_inventory(path: str | Path) -> dict[str, Any]:
    """Load and fail-closed-validate a PGIR-004 release inventory."""

    inventory_path = Path(path)
    try:
        payload = json_loads_mapping(inventory_path.read_bytes())
    except FileNotFoundError as exc:
        raise CorpusBuildError(f"inventory is missing: {inventory_path}") from exc
    except OSError as exc:
        raise CorpusBuildError(f"inventory is unreadable: {inventory_path}") from exc
    validate_release_inventory(payload)
    return payload


def json_loads_mapping(raw: bytes) -> dict[str, Any]:
    import json

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CorpusBuildError("inventory is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise CorpusBuildError("inventory must be a JSON object")
    return payload


def validate_release_inventory(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != INVENTORY_SCHEMA:
        raise CorpusBuildError("inventory schema is not IRSourceReleaseInventory@1")
    policy = _require_mapping(payload.get("policy"), "policy")
    if policy.get("trust_remote_code") is not False:
        raise CorpusBuildError("remote code is prohibited")
    if policy.get("require_source_derivative_separation") is not True:
        raise CorpusBuildError("source/derivative separation is required")
    if policy.get("default_training_admission") != "deny":
        raise CorpusBuildError("default training admission must deny")
    repositories = _require_sequence(payload.get("repositories"), "repositories")
    if not repositories:
        raise CorpusBuildError("inventory repositories are missing")
    table = _require_mapping(
        payload.get("source_derived_count_table"), "source_derived_count_table"
    )
    groups = _require_sequence(
        table.get("inventory_candidate_lineage_groups"),
        "inventory_candidate_lineage_groups",
    )
    if not groups:
        raise CorpusBuildError("inventory candidate lineage groups are missing")


def reject_path_attack(relative_path: str) -> str:
    """Reject absolute, parent, NUL, and backslash paths."""

    if not isinstance(relative_path, str) or not relative_path:
        raise CorpusBuildError("snapshot path must be a non-empty relative POSIX path")
    if "\x00" in relative_path or "\\" in relative_path:
        raise CorpusBuildError(f"unsafe snapshot path: {relative_path!r}")
    try:
        return _normalize_relative_path(relative_path)
    except HuggingFaceReleaseError as exc:
        raise CorpusBuildError(f"unsafe snapshot path: {relative_path!r}") from exc


def ingest_local_snapshot(
    *,
    destination_root: str | Path,
    relative_path: str,
    payload: bytes,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> dict[str, Any]:
    """Promote caller-supplied bytes into a content-addressed cache path."""

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise CorpusBuildError("snapshot payload must be bytes")
    raw = bytes(payload)
    if len(raw) > max_file_bytes:
        raise CorpusBuildError("snapshot exceeds max_file_bytes")
    safe = reject_path_attack(relative_path)
    root = Path(destination_root).resolve()
    target = (root / safe).resolve()
    if root not in target.parents and target != root:
        raise CorpusBuildError(f"unsafe snapshot path: {relative_path!r}")
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = sha256(raw).hexdigest()
    target.write_bytes(raw)
    if target.stat().st_size != len(raw):
        raise CorpusBuildError("snapshot size changed during write")
    return {
        "relative_path": safe,
        "size_bytes": len(raw),
        "sha256": digest,
        "content_cid": cid_v1_from_digest(bytes.fromhex(digest)),
    }


@dataclass(frozen=True, slots=True)
class PlannedPopulation:
    """One inventory-candidate source population and its sibling families."""

    population_id: str
    lineage_group_prefix: str
    source_group_count: int
    candidate: str
    overlapping_views: tuple[str, ...]
    families: tuple[str, ...]
    rights: RightsRecord
    temporal: TemporalCoverage
    release: SourceRelease


@dataclass(frozen=True, slots=True)
class CorpusPlan:
    """Deterministic grouping plan before records and CIDs are materialized."""

    pinset_id: str
    populations: tuple[PlannedPopulation, ...]
    rejected_releases: tuple[str, ...]
    quarantined_releases: tuple[str, ...]

    @property
    def patent_group_count(self) -> int:
        return sum(
            item.source_group_count for item in self.populations if item.population_id == "patent"
        )

    @property
    def source_group_count(self) -> int:
        return sum(item.source_group_count for item in self.populations)

    def training_admitted_record_ids(self) -> tuple[str, ...]:
        admitted: list[str] = []
        for population in self.populations:
            if population.rights.disposition is RightsDisposition.ADMITTED:
                admitted.extend(
                    _source_record_id(population.population_id, index)
                    for index in range(population.source_group_count)
                )
        return tuple(admitted)


def _source_record_id(population_id: str, index: int) -> str:
    return f"src:{population_id}:{index:04d}"


def _group_id(population_id: str, index: int) -> str:
    return f"grp:{population_id}:{index:04d}"


def _derived_id(population_id: str, family: str, index: int) -> str:
    return f"drv:{population_id}:{family}:{index:04d}"


def plan_corpus(
    inventory: Mapping[str, Any],
    *,
    expected_patent_groups: int = PATENT_SOURCE_GROUP_COUNT,
) -> CorpusPlan:
    """Group inventory candidates so derivatives never inflate source counts."""

    validate_release_inventory(inventory)
    repositories = {
        str(item["id"]): item
        for item in _require_sequence(inventory.get("repositories"), "repositories")
        if isinstance(item, Mapping) and item.get("id")
    }
    table = _require_mapping(
        inventory.get("source_derived_count_table"), "source_derived_count_table"
    )
    declared = _require_mapping(
        table.get("inventory_candidate_source_rows"), "inventory_candidate_source_rows"
    )
    groups = _require_sequence(
        table.get("inventory_candidate_lineage_groups"),
        "inventory_candidate_lineage_groups",
    )
    populations: list[PlannedPopulation] = []
    for spec in groups:
        mapping = _require_mapping(spec, "lineage group")
        lineage_group = str(mapping.get("lineage_group") or "")
        candidate = str(mapping.get("candidate") or "")
        count = mapping.get("source_candidate_rows")
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            raise CorpusBuildError("source_candidate_rows must be a positive integer")
        if mapping.get("training_admitted_rows") not in (0, None):
            raise CorpusBuildError("rights-quarantined rows cannot enter training")
        population_id = _population_slug(lineage_group)
        repo_id, _, config = _split_candidate(candidate)
        repo = repositories.get(repo_id)
        if repo is None:
            raise CorpusBuildError(f"candidate repository is missing: {repo_id}")
        if _disposition_of(repo) == "reject":
            raise CorpusBuildError(f"broken release cannot be used as a source: {repo_id}")
        configs = _require_mapping(repo.get("configuration_receipts"), "configuration_receipts")
        config_name = config or next(iter(configs))
        config_receipt = _require_mapping(configs.get(config_name), f"configuration {config_name}")
        role = str(config_receipt.get("semantic_role") or "")
        if role not in _SOURCE_ROLES:
            raise CorpusBuildError(
                f"{repo_id}:{config_name} is not a source_candidate (role={role!r})"
            )
        observed = config_receipt.get("row_count")
        if observed not in (count, None):
            raise CorpusBuildError(
                f"{repo_id}:{config_name} row_count {observed} != declared {count}"
            )
        families = tuple(
            sorted(
                {
                    _family_of(str(key))
                    for key in _require_mapping(
                        mapping.get("derivative_observations") or {},
                        "derivative_observations",
                    )
                }
            )
        )
        overlapping = tuple(
            item
            for item in (
                mapping.get("overlapping_source_view"),
                *(
                    [f"historical:{mapping['historical_overlapping_source_rows']}"]
                    if mapping.get("historical_overlapping_source_rows")
                    else []
                ),
            )
            if item
        )
        rights = _rights_from_inventory(
            _require_mapping(repo.get("rights_receipt") or {}, "rights_receipt"),
            disposition=_rights_disposition_of(repo),
        )
        if rights.disposition is RightsDisposition.ADMITTED:
            raise CorpusBuildError("inventory may not admit training rows in this launch")
        revision = str(repo.get("revision") or "")
        release = SourceRelease(
            release_id=f"rel:{_slug(repo_id)}",
            repository_id=repo_id,
            revision=revision,
            pinset_id=PINSET_ID,
            rights=rights,
            temporal=_temporal_from_coverage(
                repo.get("coverage_receipt") if isinstance(repo.get("coverage_receipt"), Mapping) else None
            ),
            configuration_ids=(config_name,),
        )
        release.validate()
        populations.append(
            PlannedPopulation(
                population_id=population_id,
                lineage_group_prefix=lineage_group.split("@", 1)[0],
                source_group_count=count,
                candidate=candidate,
                overlapping_views=tuple(str(item) for item in overlapping),
                families=families,
                rights=rights,
                temporal=release.temporal,
                release=release,
            )
        )

    patent_count = sum(item.source_group_count for item in populations if item.population_id == "patent")
    if patent_count != expected_patent_groups:
        raise CorpusBuildError(
            f"patent documents must remain {expected_patent_groups} groups, got {patent_count}"
        )
    if declared.get("patent") not in (expected_patent_groups, None):
        raise CorpusBuildError("inventory patent count does not match grouped patent sources")
    expected_total = sum(item.source_group_count for item in populations)
    if declared.get("total") not in (expected_total, None):
        raise CorpusBuildError("inventory total source rows do not match grouped populations")
    if table.get("training_admitted_source_rows") not in (0, None):
        raise CorpusBuildError("rights-quarantined rows cannot enter training")

    rejected: list[str] = []
    quarantined: list[str] = []
    for repo_id, repo in sorted(repositories.items()):
        disposition = _disposition_of(repo)
        if disposition == "reject":
            rejected.append(repo_id)
        else:
            quarantined.append(repo_id)
        for config_name, receipt in _require_mapping(
            repo.get("configuration_receipts"), "configuration_receipts"
        ).items():
            role = str(_require_mapping(receipt, config_name).get("semantic_role") or "unknown")
            if role in _SOURCE_ROLES:
                continue
            if role not in _NON_SOURCE_ROLES:
                raise CorpusBuildError(f"unknown semantic role {role!r} on {repo_id}:{config_name}")

    return CorpusPlan(
        pinset_id=PINSET_ID,
        populations=tuple(populations),
        rejected_releases=tuple(rejected),
        quarantined_releases=tuple(quarantined),
    )


def _split_candidate(candidate: str) -> tuple[str, str, str]:
    # repo@revision:config
    if "@" not in candidate or ":" not in candidate:
        raise CorpusBuildError(f"candidate identity is malformed: {candidate!r}")
    repo_and_rev, config = candidate.rsplit(":", 1)
    repo_id, revision = repo_and_rev.split("@", 1)
    if not repo_id or not revision or not config:
        raise CorpusBuildError(f"candidate identity is malformed: {candidate!r}")
    return repo_id, revision, config


def materialize_records(plan: CorpusPlan) -> tuple[
    tuple[SourceRelease, ...],
    tuple[SourceRecord, ...],
    tuple[DerivedArtifactRecord, ...],
    LineageGraph,
]:
    """Expand a plan into versioned source/derived records and a lineage graph."""

    releases = tuple(item.release for item in plan.populations)
    sources: list[SourceRecord] = []
    derived: list[DerivedArtifactRecord] = []
    nodes: list[str] = []
    edges: list[LineageEdge] = []
    for population in plan.populations:
        for index in range(population.source_group_count):
            record_id = _source_record_id(population.population_id, index)
            group_id = _group_id(population.population_id, index)
            binding = _binding_digest(
                candidate=population.candidate,
                index=index,
                pinset_id=plan.pinset_id,
                population_id=population.population_id,
                revision=population.release.revision,
            )
            source = SourceRecord(
                record_id=record_id,
                release_id=population.release.release_id,
                lineage_group_id=group_id,
                source_ref=SourceRef(
                    ref_id=f"ref:{record_id}",
                    source_uri=(
                        f"hf://datasets/{population.release.repository_id}"
                        f"@{population.release.revision}"
                    ),
                    source_id=population.release.repository_id,
                    source_revision=population.release.revision,
                    content_sha256=binding,
                    review_status=SourceReviewStatus.QUARANTINED,
                    license_expression=population.rights.license_expression,
                ),
                rights=population.rights,
                temporal=population.temporal,
            )
            source.validate()
            sources.append(source)
            nodes.append(record_id)
            for family in population.families:
                artifact_id = _derived_id(population.population_id, family, index)
                artifact = DerivedArtifactRecord(
                    artifact_id=artifact_id,
                    parent_record_ids=(record_id,),
                    derivation_kind=family,
                    content_sha256=_binding_digest(
                        family=family,
                        index=index,
                        parent=record_id,
                        pinset_id=plan.pinset_id,
                    ),
                    rights=RightsRecord(
                        disposition=RightsDisposition.QUARANTINED,
                        license_expression=population.rights.license_expression,
                        source_rights_status=population.rights.source_rights_status,
                        transformation_rights_status=population.rights.transformation_rights_status,
                        scope=population.rights.scope,
                    ),
                )
                artifact.validate()
                derived.append(artifact)
                nodes.append(artifact_id)
                edges.append(
                    LineageEdge(
                        parent_id=record_id,
                        child_id=artifact_id,
                        relation=LineageRelation.DERIVED_FROM,
                    )
                )
    graph = LineageGraph(
        graph_id="lin:jdao-pinset-1",
        node_ids=tuple(nodes),
        edges=tuple(edges),
    )
    graph.validate()
    return releases, tuple(sources), tuple(derived), graph


def expand_ids(plan: CorpusPlan) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return deterministic source and derived IDs without loading row payloads."""

    sources: list[str] = []
    derived: list[str] = []
    for population in plan.populations:
        for index in range(population.source_group_count):
            sources.append(_source_record_id(population.population_id, index))
            for family in population.families:
                derived.append(_derived_id(population.population_id, family, index))
    overlap = set(sources) & set(derived)
    if overlap:
        raise CorpusBuildError("derived artifacts cannot be counted as sources")
    return tuple(sources), tuple(derived)


def compact_lineage_payload(plan: CorpusPlan) -> dict[str, Any]:
    return {
        "graph_id": "lin:jdao-pinset-1",
        "kind": "compact_lineage_index",
        "pinset_id": plan.pinset_id,
        "populations": [
            {
                "candidate": item.candidate,
                "families": list(item.families),
                "overlapping_views": list(item.overlapping_views),
                "population_id": item.population_id,
                "source_group_count": item.source_group_count,
            }
            for item in plan.populations
        ],
        "schema": "ir-corpus-lineage-index/v1",
    }


def build_corpus_manifest(
    sources: Sequence[SourceRecord],
    derived: Sequence[DerivedArtifactRecord],
    graph: LineageGraph,
    *,
    rights: RightsRecord,
    manifest_id: str = "corp:jdao-pinset-1",
) -> CorpusManifest:
    manifest = CorpusManifest(
        manifest_id=manifest_id,
        source_record_ids=tuple(item.record_id for item in sources),
        derived_artifact_ids=tuple(item.artifact_id for item in derived),
        lineage_graph_id=graph.graph_id,
        rights=rights,
    )
    manifest.validate()
    if set(manifest.derived_artifact_ids) & set(manifest.source_record_ids):
        raise CorpusBuildError("derived artifacts cannot be counted as sources")
    return manifest


def rights_manifest(plan: CorpusPlan, sources: Sequence[SourceRecord]) -> dict[str, Any]:
    return {
        "admitted_source_record_ids": [],
        "kind": "rights_manifest",
        "pinset_id": plan.pinset_id,
        "quarantined_source_record_ids": [item.record_id for item in sources],
        "schema": "ir-corpus-rights-manifest/v1",
        "source_count": len(sources),
        "training_admitted_rows": 0,
    }


def quarantine_manifest(plan: CorpusPlan, sources: Sequence[SourceRecord]) -> dict[str, Any]:
    return {
        "kind": "quarantine_manifest",
        "pinset_id": plan.pinset_id,
        "quarantined_releases": list(plan.quarantined_releases),
        "quarantined_source_record_ids": [item.record_id for item in sources],
        "reason": "unresolved source and transformation rights; training denied",
        "rejected_releases": list(plan.rejected_releases),
        "schema": "ir-corpus-quarantine-manifest/v1",
        "training_eligible_rows": 0,
    }


def reconciliation_receipt(
    plan: CorpusPlan,
    sources: Sequence[SourceRecord],
    derived: Sequence[DerivedArtifactRecord],
) -> dict[str, Any]:
    by_population = {
        item.population_id: item.source_group_count for item in plan.populations
    }
    return {
        "derived_count": len(derived),
        "kind": "count_reconciliation",
        "patent_source_groups": plan.patent_group_count,
        "pinset_id": plan.pinset_id,
        "populations": by_population,
        "schema": "ir-corpus-reconciliation/v1",
        "source_count": len(sources),
        "training_admitted_rows": 0,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = canonical_json_bytes(dict(payload)) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_bytes(raw)
    temporary.replace(path)
    digest = sha256(raw).hexdigest()
    return {
        "path": path.name,
        "sha256": digest,
        "content_cid": cid_v1(raw),
        "size_bytes": len(raw),
    }


def seal_corpus(
    inventory: Mapping[str, Any],
    output_dir: str | Path,
    *,
    materialize: bool = True,
    expected_patent_groups: int = PATENT_SOURCE_GROUP_COUNT,
) -> dict[str, Any]:
    """Write immutable corpus, rights, quarantine, and reconciliation receipts."""

    plan = plan_corpus(inventory, expected_patent_groups=expected_patent_groups)
    if plan.training_admitted_record_ids():
        raise CorpusBuildError("rights-quarantined rows cannot enter training")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    source_ids, derived_ids = expand_ids(plan)
    rights = plan.populations[0].rights
    compact_graph = compact_lineage_payload(plan)
    manifest = CorpusManifest(
        manifest_id="corp:jdao-pinset-1",
        source_record_ids=source_ids,
        derived_artifact_ids=derived_ids,
        lineage_graph_id=str(compact_graph["graph_id"]),
        rights=rights,
    )
    manifest.validate()
    if materialize:
        _releases, sources, derived, graph = materialize_records(plan)
        if tuple(item.record_id for item in sources) != source_ids:
            raise CorpusBuildError("materialized source IDs drifted from the compact plan")
        lineage_payload = graph.to_dict()
        rights_payload = rights_manifest(plan, sources)
        quarantine_payload = quarantine_manifest(plan, sources)
        recon = reconciliation_receipt(plan, sources, derived)
        lineage_cid = graph.record_cid
    else:
        lineage_payload = compact_graph
        rights_payload = {
            "admitted_source_record_ids": [],
            "kind": "rights_manifest",
            "pinset_id": plan.pinset_id,
            "quarantined_source_record_ids": list(source_ids),
            "schema": "ir-corpus-rights-manifest/v1",
            "source_count": len(source_ids),
            "training_admitted_rows": 0,
        }
        quarantine_payload = {
            "kind": "quarantine_manifest",
            "pinset_id": plan.pinset_id,
            "quarantined_releases": list(plan.quarantined_releases),
            "quarantined_source_record_ids": list(source_ids),
            "reason": "unresolved source and transformation rights; training denied",
            "rejected_releases": list(plan.rejected_releases),
            "schema": "ir-corpus-quarantine-manifest/v1",
            "training_eligible_rows": 0,
        }
        recon = {
            "derived_count": len(derived_ids),
            "kind": "count_reconciliation",
            "patent_source_groups": plan.patent_group_count,
            "pinset_id": plan.pinset_id,
            "populations": {
                item.population_id: item.source_group_count for item in plan.populations
            },
            "schema": "ir-corpus-reconciliation/v1",
            "source_count": len(source_ids),
            "training_admitted_rows": 0,
        }
        lineage_cid = cid_v1(canonical_json_bytes(compact_graph))
    descriptors = {
        "corpus_manifest.json": _write_json(output / "corpus_manifest.json", manifest.to_dict()),
        "lineage_graph.json": _write_json(output / "lineage_graph.json", lineage_payload),
        "rights_manifest.json": _write_json(output / "rights_manifest.json", rights_payload),
        "quarantine_manifest.json": _write_json(
            output / "quarantine_manifest.json", quarantine_payload
        ),
        "reconciliation_receipt.json": _write_json(
            output / "reconciliation_receipt.json", recon
        ),
        "source_releases.json": _write_json(
            output / "source_releases.json",
            {
                "kind": "source_releases",
                "releases": [item.release.to_dict() for item in plan.populations],
                "schema": "ir-corpus-source-releases/v1",
            },
        ),
    }
    root = {
        "artifacts": descriptors,
        "derived_count": manifest.derived_count,
        "kind": CORPUS_ROOT_SCHEMA,
        "lineage_graph_cid": lineage_cid,
        "manifest_cid": manifest.record_cid,
        "manifest_id": manifest.manifest_id,
        "materialized": materialize,
        "patent_source_groups": plan.patent_group_count,
        "pinset_id": plan.pinset_id,
        "source_count": manifest.source_count,
        "training_admitted_rows": 0,
    }
    descriptors["corpus_root.json"] = _write_json(output / "corpus_root.json", root)
    return {
        **root,
        "artifacts": descriptors,
        "record_cid": descriptors["corpus_root.json"]["content_cid"],
    }


def seal_inventory_path(
    inventory_path: str | Path,
    output_dir: str | Path,
    *,
    materialize: bool = True,
    expected_patent_groups: int = PATENT_SOURCE_GROUP_COUNT,
) -> dict[str, Any]:
    return seal_corpus(
        load_release_inventory(inventory_path),
        output_dir,
        materialize=materialize,
        expected_patent_groups=expected_patent_groups,
    )


__all__ = [
    "CORPUS_ROOT_SCHEMA",
    "CorpusBuildError",
    "CorpusPlan",
    "DEFAULT_MAX_FILE_BYTES",
    "INVENTORY_SCHEMA",
    "PATENT_SOURCE_GROUP_COUNT",
    "PINSET_ID",
    "PlannedPopulation",
    "build_corpus_manifest",
    "ingest_local_snapshot",
    "load_release_inventory",
    "materialize_records",
    "plan_corpus",
    "quarantine_manifest",
    "reconciliation_receipt",
    "reject_path_attack",
    "rights_manifest",
    "seal_corpus",
    "seal_inventory_path",
    "validate_release_inventory",
]
