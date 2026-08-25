"""USCIR-012: prove shared HF GraphRAG substrate compatibility with reference layouts.

Fixtures exercise artifact families, 4,096 physical bounds, immutable Hub
resolution, vector-space IDs, and graph ontology variations. Incompatible
assumptions raise typed errors. Vector spaces from patent, CVEfixes, and
SkillCenter remain intentionally non-interchangeable even when dimensions match.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from ipfs_datasets_py.retrieval.hf_graphrag.locators import (
    KIND_CORPUS,
    KIND_VECTORS,
    LOCATOR_SCHEMA_VERSION,
    LocatorRow,
    MissingKeyError,
    build_dual_cid_locators,
    build_locator_rows_from_keys,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    DEFAULT_SUPPORTED_RELEASE_SCHEMAS,
    ArtifactDescriptor as ResolverArtifactDescriptor,
    ImmutableHubResolver,
    MappingTransport,
    MutableRevisionError,
    SchemaMismatchError,
    build_descriptor_for_bytes,
    validate_immutable_revision,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MAX_ROWS_PER_VECTOR_CENTROID,
    MAX_VECTOR_SHARDS_PER_CENTROID,
    PARQUET_MEDIA_TYPE,
    ArtifactDescriptor,
    ArtifactFamily,
    ArtifactPathError,
    HfGraphragSchemaError,
    PhysicalBoundError,
    canonical_json_bytes,
    content_sha256,
    normalize_relative_artifact_path,
    physical_bounds_policy,
    validate_physical_pointer_count,
    validate_physical_row_count,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "hf_graphrag"
    / "reference_manifests.json"
)
FIXTURE_SCHEMA_VERSION = "hf-graphrag-reference-manifests/v1"
REQUIRED_DOMAINS = frozenset({"patent", "cvefixes", "skillcenter"})
REQUIRED_INCOMPATIBLE_KINDS = frozenset(
    {
        "vector_space",
        "graph_ontology",
        "immutable_resolution",
        "physical_bound",
        "artifact_family",
        "schema_mismatch",
    }
)


# ---------------------------------------------------------------------------
# Typed compatibility errors (contract surface for query-time late-fuse)
# ---------------------------------------------------------------------------


class VectorSpaceIncompatibilityError(HfGraphragSchemaError):
    """Raised when two releases declare distinct vector-space identifiers."""


class GraphOntologyIncompatibilityError(HfGraphragSchemaError):
    """Raised when two releases declare incompatible graph ontologies."""


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def load_reference_manifests(path: str | Path = FIXTURE_PATH) -> dict[str, Any]:
    """Load and lightly validate the sealed reference-layout fixture."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise HfGraphragSchemaError("reference_manifests fixture must be an object")
    if payload.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise HfGraphragSchemaError(
            f"unsupported reference fixture schema: {payload.get('schema_version')!r}"
        )
    releases = payload.get("reference_releases")
    if not isinstance(releases, list) or not releases:
        raise HfGraphragSchemaError("reference_manifests has no reference_releases")
    return dict(payload)


def reference_by_domain(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Index sealed releases by domain token."""

    out: dict[str, dict[str, Any]] = {}
    for item in payload["reference_releases"]:
        if not isinstance(item, Mapping):
            raise HfGraphragSchemaError("reference release must be a mapping")
        domain = str(item.get("domain") or "").strip()
        if not domain:
            raise HfGraphragSchemaError("reference release missing domain")
        if domain in out:
            raise HfGraphragSchemaError(f"duplicate reference domain: {domain!r}")
        out[domain] = dict(item)
    return out


def _label_bytes(label: str) -> bytes:
    return str(label).encode("utf-8")


def _label_digest(label: str) -> str:
    return hashlib.sha256(_label_bytes(label)).hexdigest()


def require_compatible_vector_spaces(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    left_name: str = "left",
    right_name: str = "right",
) -> str:
    """Late-fuse gate: identical vector_space_id only (never dimension alone)."""

    left_id = str(left.get("vector_space_id") or "").strip()
    right_id = str(right.get("vector_space_id") or "").strip()
    if not left_id or not right_id:
        raise VectorSpaceIncompatibilityError(
            "vector_space_id is required on both releases"
        )
    if left_id != right_id:
        left_dim = left.get("dimension")
        right_dim = right.get("dimension")
        raise VectorSpaceIncompatibilityError(
            f"vector spaces are not interchangeable: {left_name}={left_id!r} "
            f"(dim={left_dim}) vs {right_name}={right_id!r} (dim={right_dim}); "
            "matching dimensions alone never imply compatibility"
        )
    return left_id


def require_compatible_graph_ontologies(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    left_name: str = "left",
    right_name: str = "right",
) -> str:
    """Graph layout families may align; domain ontologies must match exactly."""

    left_ver = str(left.get("ontology_version") or "").strip()
    right_ver = str(right.get("ontology_version") or "").strip()
    if not left_ver or not right_ver:
        raise GraphOntologyIncompatibilityError(
            "graph ontology_version is required on both releases"
        )
    if left_ver != right_ver:
        raise GraphOntologyIncompatibilityError(
            f"graph ontologies are not interchangeable: {left_name}={left_ver!r} "
            f"vs {right_name}={right_ver!r}"
        )
    left_nodes = tuple(left.get("node_types") or ())
    right_nodes = tuple(right.get("node_types") or ())
    left_edges = tuple(left.get("edge_types") or ())
    right_edges = tuple(right.get("edge_types") or ())
    if left_nodes != right_nodes or left_edges != right_edges:
        raise GraphOntologyIncompatibilityError(
            f"graph vocabularies differ between {left_name} and {right_name}"
        )
    return left_ver


def schema_descriptor_from_artifact(
    artifact: Mapping[str, Any],
    *,
    schema_id: str,
) -> ArtifactDescriptor:
    """Build a shared-schema ArtifactDescriptor from a compact fixture recipe."""

    label = str(artifact["content_label"])
    body = _label_bytes(label)
    return ArtifactDescriptor(
        relative_path=str(artifact["relative_path"]),
        sha256=_label_digest(label),
        size_bytes=len(body),
        row_count=int(artifact.get("row_count") or 0),
        media_type=(
            PARQUET_MEDIA_TYPE
            if str(artifact["relative_path"]).endswith(".parquet")
            else "application/json"
        ),
        schema_id=schema_id,
        family=str(artifact["family"]),
        first_key="entry-a" if int(artifact.get("row_count") or 0) else None,
        last_key="entry-b" if int(artifact.get("row_count") or 0) else None,
        shard_id=0 if int(artifact.get("row_count") or 0) else None,
    )


def build_release_manifest_bytes(release: Mapping[str, Any]) -> bytes:
    """Canonical control-plane manifest admitted by the shared resolver."""

    vector = dict(release["vector_space"])
    graph = dict(release["graph"])
    payload = {
        "dataset_repo_id": release["repo_id"],
        "dataset_revision": release["revision"],
        "graph": {
            "adjacency_directions": list(graph.get("adjacency_directions") or []),
            "max_adjacency_pointers_per_row": int(
                graph.get("max_adjacency_pointers_per_row") or MAX_ADJACENCY_POINTERS_PER_ROW
            ),
            "ontology_version": graph["ontology_version"],
        },
        "physical_bounds": dict(release["physical_bounds"]),
        "primary_key": release.get("primary_key") or "entry_cid",
        "release_profile": release.get("release_profile") or release["schema_version"],
        "schema_version": release["schema_version"],
        "vector": {
            "dimension": int(vector["dimension"]),
            "layout": vector.get("layout"),
            "model_id": vector["model_id"],
            "model_revision": vector["model_revision"],
            "vector_space_id": vector["vector_space_id"],
        },
    }
    return canonical_json_bytes(payload)


def release_transport_files(release: Mapping[str, Any]) -> dict[str, bytes]:
    """Materialize recipe labels into a fake Hub file map."""

    files: dict[str, bytes] = {}
    for artifact in release["artifacts"]:
        path = str(artifact["relative_path"])
        if path == "manifest.json":
            files[path] = build_release_manifest_bytes(release)
        else:
            files[path] = _label_bytes(str(artifact["content_label"]))
    return files


def _resolver_for_release(
    tmp_path: Path,
    release: Mapping[str, Any],
    *,
    supported_schemas: set[str] | frozenset[str] | None = None,
    revision: str | None = None,
) -> ImmutableHubResolver:
    files = release_transport_files(release)
    schemas = set(supported_schemas or DEFAULT_SUPPORTED_RELEASE_SCHEMAS)
    schemas.add(str(release["schema_version"]))
    profile = release.get("release_profile")
    if isinstance(profile, str) and profile.strip():
        schemas.add(profile.strip())
    return ImmutableHubResolver(
        repo_id=str(release["repo_id"]),
        revision=revision or str(release["revision"]),
        cache_dir=tmp_path / "cache" / str(release["domain"]),
        transport=MappingTransport(files),
        supported_schemas=schemas,
        max_rows_per_artifact=MAX_ROWS_PER_PHYSICAL_SHARD,
    )


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_reference_manifests_fixture_is_sealed() -> None:
    assert FIXTURE_PATH.is_file()
    payload = load_reference_manifests()
    assert payload["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert payload["task_id"] == "USCIR-012"
    assert payload["policy"]["dimension_implies_vector_space_compatibility"] is False
    assert payload["policy"]["vector_spaces_are_not_interchangeable"] is True

    by_domain = reference_by_domain(payload)
    assert set(by_domain) == REQUIRED_DOMAINS

    kinds = {case["kind"] for case in payload["incompatible_assumptions"]}
    assert REQUIRED_INCOMPATIBLE_KINDS <= kinds

    shared = payload["shared_physical_bounds"]
    assert shared["max_rows_per_physical_shard"] == 4096
    assert shared["max_pointers_per_row"] == 4096
    assert set(payload["shared_artifact_families"]) == {
        family.value for family in ArtifactFamily
    }


def test_shared_physical_bounds_match_substrate_policy() -> None:
    payload = load_reference_manifests()
    policy = physical_bounds_policy()
    shared = payload["shared_physical_bounds"]
    assert shared["max_rows_per_physical_shard"] == policy["max_rows_per_physical_shard"]
    assert shared["max_pointers_per_row"] == policy["max_pointers_per_row"]
    assert shared["max_adjacency_pointers_per_row"] == policy[
        "max_adjacency_pointers_per_row"
    ]
    assert shared["max_rows_per_vector_centroid"] == policy[
        "max_rows_per_vector_centroid"
    ]
    assert shared["max_vector_shards_per_centroid"] == policy[
        "max_vector_shards_per_centroid"
    ]
    assert MAX_ROWS_PER_PHYSICAL_SHARD == 4096
    assert MAX_POINTERS_PER_ROW == 4096
    assert MAX_ADJACENCY_POINTERS_PER_ROW == 4096
    assert MAX_ROWS_PER_VECTOR_CENTROID == 8192
    assert MAX_VECTOR_SHARDS_PER_CENTROID == 2


# ---------------------------------------------------------------------------
# Artifact families
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("domain", sorted(REQUIRED_DOMAINS))
def test_reference_artifact_families_map_to_shared_enum(domain: str) -> None:
    release = reference_by_domain(load_reference_manifests())[domain]
    families = [str(item["family"]) for item in release["artifacts"]]
    assert families, f"{domain} must declare artifacts"
    coerced = [ArtifactFamily.coerce(name) for name in families]
    assert all(isinstance(item, ArtifactFamily) for item in coerced)
    # Every reference exercises corpus + graph + vector families.
    values = {item.value for item in coerced}
    assert ArtifactFamily.CORPUS.value in values
    assert ArtifactFamily.VECTORS.value in values
    assert ArtifactFamily.GRAPH_NODES.value in values
    assert ArtifactFamily.GRAPH_EDGES.value in values
    assert ArtifactFamily.GRAPH_ADJACENCY_OUT.value in values
    assert ArtifactFamily.GRAPH_ADJACENCY_IN.value in values
    assert ArtifactFamily.MANIFEST.value in values


@pytest.mark.parametrize("domain", sorted(REQUIRED_DOMAINS))
def test_reference_artifact_descriptors_validate(domain: str) -> None:
    release = reference_by_domain(load_reference_manifests())[domain]
    for artifact in release["artifacts"]:
        descriptor = schema_descriptor_from_artifact(
            artifact, schema_id=str(release["schema_version"])
        )
        assert descriptor.relative_path == artifact["relative_path"]
        assert descriptor.family == ArtifactFamily.coerce(artifact["family"])
        assert descriptor.row_count <= MAX_ROWS_PER_PHYSICAL_SHARD
        assert len(descriptor.sha256) == 64
        # Paths stay confined and POSIX.
        normalize_relative_artifact_path(descriptor.relative_path)
        again = ArtifactDescriptor.from_mapping(descriptor.to_dict())
        assert again.to_dict() == descriptor.to_dict()


def test_unknown_artifact_family_raises_typed_error() -> None:
    payload = load_reference_manifests()
    case = next(
        item
        for item in payload["incompatible_assumptions"]
        if item["id"] == "unknown_artifact_family"
    )
    with pytest.raises(HfGraphragSchemaError, match="unknown artifact family"):
        ArtifactFamily.coerce(case["family"])


# ---------------------------------------------------------------------------
# 4,096 physical bounds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("domain", sorted(REQUIRED_DOMAINS))
def test_reference_bounds_are_within_4096_policy(domain: str) -> None:
    release = reference_by_domain(load_reference_manifests())[domain]
    bounds = release["physical_bounds"]
    assert bounds["max_rows_per_physical_shard"] == 4096
    assert bounds["max_pointers_per_row"] == 4096
    assert bounds["max_adjacency_pointers_per_row"] == 4096
    assert bounds["max_term_rows_per_shard"] == 4096
    assert bounds["max_rows_per_vector_centroid"] <= MAX_ROWS_PER_VECTOR_CENTROID
    assert bounds["max_vector_shards_per_centroid"] <= MAX_VECTOR_SHARDS_PER_CENTROID
    for artifact in release["artifacts"]:
        validate_physical_row_count(int(artifact["row_count"]))
    validate_physical_pointer_count(bounds["max_pointers_per_row"])
    # Vector layout bounds used by CVEfixes/SkillCenter-style clustering.
    vector = release["vector_space"]
    assert int(vector["max_rows_per_chunk"]) == 4096
    assert int(vector["max_rows_per_centroid"]) <= 8192


def test_oversize_row_count_raises_physical_bound_error() -> None:
    payload = load_reference_manifests()
    case = next(
        item
        for item in payload["incompatible_assumptions"]
        if item["id"] == "physical_bound_oversize_rows"
    )
    with pytest.raises(PhysicalBoundError, match="exceeds physical bound"):
        validate_physical_row_count(int(case["row_count"]))
    with pytest.raises(PhysicalBoundError):
        ArtifactDescriptor(
            relative_path="data/corpus/part-000000.parquet",
            sha256=content_sha256("oversize"),
            size_bytes=8,
            row_count=MAX_ROWS_PER_PHYSICAL_SHARD + 1,
            family=ArtifactFamily.CORPUS,
        )


def test_oversize_pointer_count_raises_physical_bound_error() -> None:
    with pytest.raises(PhysicalBoundError, match="pointer"):
        validate_physical_pointer_count(MAX_POINTERS_PER_ROW + 1)


# ---------------------------------------------------------------------------
# Immutable resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("domain", sorted(REQUIRED_DOMAINS))
def test_reference_revisions_are_immutable_hub_pins(domain: str) -> None:
    release = reference_by_domain(load_reference_manifests())[domain]
    assert validate_immutable_revision(release["revision"]) == release["revision"]
    vector = release["vector_space"]
    # Model pins must also be immutable digests/SHAs (not latest/main).
    model_rev = str(vector["model_revision"])
    assert model_rev not in {"latest", "main", "master", "HEAD"}
    assert len(model_rev) >= 40


@pytest.mark.parametrize("domain", sorted(REQUIRED_DOMAINS))
def test_immutable_resolver_admits_reference_manifests(
    domain: str, tmp_path: Path
) -> None:
    release = reference_by_domain(load_reference_manifests())[domain]
    resolver = _resolver_for_release(tmp_path, release)
    manifest_bytes = build_release_manifest_bytes(release)
    descriptor = build_descriptor_for_bytes(
        "manifest.json",
        manifest_bytes,
        schema_id=str(release["schema_version"]),
        media_type="application/json",
    )
    artifact = resolver.resolve("manifest.json", descriptor=descriptor)
    assert artifact.verified is True
    assert artifact.cache_hit is False
    assert artifact.sha256 == descriptor.sha256

    loaded = resolver.load_manifest(descriptor=descriptor)
    assert loaded["schema_version"] == release["schema_version"]
    assert loaded["primary_key"] == "entry_cid"
    assert loaded["vector"]["vector_space_id"] == release["vector_space"][
        "vector_space_id"
    ]

    # Second resolve is revision-scoped cache hit.
    again = resolver.resolve("manifest.json", descriptor=descriptor)
    assert again.cache_hit is True

    # Data family resolves with descriptor verification.
    corpus = next(
        item for item in release["artifacts"] if item["family"] == "corpus"
    )
    corpus_bytes = _label_bytes(str(corpus["content_label"]))
    corpus_desc = build_descriptor_for_bytes(
        str(corpus["relative_path"]),
        corpus_bytes,
        schema_id=str(release["schema_version"]),
        row_count=int(corpus["row_count"]),
        media_type=PARQUET_MEDIA_TYPE,
    )
    corpus_art = resolver.resolve(str(corpus["relative_path"]), descriptor=corpus_desc)
    assert corpus_art.verified is True
    assert corpus_art.sha256 == _label_digest(str(corpus["content_label"]))

    trace = resolver.fetch_trace()
    assert trace["repo_id"] == release["repo_id"]
    assert trace["revision"] == release["revision"]
    rendered = json.dumps(trace, sort_keys=True)
    assert "hf_" not in rendered
    assert "Bearer " not in rendered


def test_mutable_revision_raises_typed_error(tmp_path: Path) -> None:
    payload = load_reference_manifests()
    case = next(
        item
        for item in payload["incompatible_assumptions"]
        if item["id"] == "mutable_revision_main"
    )
    release = reference_by_domain(payload)["patent"]
    with pytest.raises(MutableRevisionError):
        _resolver_for_release(tmp_path, release, revision=str(case["revision"]))


def test_unregistered_domain_schema_raises_schema_mismatch(tmp_path: Path) -> None:
    payload = load_reference_manifests()
    case = next(
        item
        for item in payload["incompatible_assumptions"]
        if item["id"] == "schema_mismatch_unregistered"
    )
    release = reference_by_domain(payload)[str(case["domain"])]
    # Ambient defaults do not include SkillCenter/CVEfixes release schemas.
    resolver = ImmutableHubResolver(
        repo_id=str(release["repo_id"]),
        revision=str(release["revision"]),
        cache_dir=tmp_path / "cache-default",
        transport=MappingTransport(release_transport_files(release)),
        supported_schemas=DEFAULT_SUPPORTED_RELEASE_SCHEMAS,
    )
    manifest_bytes = build_release_manifest_bytes(release)
    descriptor = build_descriptor_for_bytes(
        "manifest.json",
        manifest_bytes,
        schema_id=str(release["schema_version"]),
    )
    with pytest.raises(SchemaMismatchError, match="unsupported release schema"):
        resolver.load_manifest(descriptor=descriptor)


# ---------------------------------------------------------------------------
# Vector-space IDs (non-interchangeable)
# ---------------------------------------------------------------------------


def test_vector_space_ids_are_unique_across_reference_domains() -> None:
    by_domain = reference_by_domain(load_reference_manifests())
    ids = {
        domain: release["vector_space"]["vector_space_id"]
        for domain, release in by_domain.items()
    }
    assert len(ids) == len(set(ids.values()))
    # Explicit plan facts.
    assert by_domain["patent"]["vector_space"]["dimension"] == 256
    assert by_domain["cvefixes"]["vector_space"]["dimension"] == 384
    assert by_domain["skillcenter"]["vector_space"]["dimension"] == 384
    # Same dimension does not collapse identity.
    assert (
        by_domain["cvefixes"]["vector_space"]["vector_space_id"]
        != by_domain["skillcenter"]["vector_space"]["vector_space_id"]
    )


@pytest.mark.parametrize(
    "case_id",
    [
        "vector_space_same_dim_different_model",
        "vector_space_patent_vs_cvefixes",
        "vector_space_patent_vs_skillcenter",
    ],
)
def test_incompatible_vector_spaces_raise_typed_error(case_id: str) -> None:
    payload = load_reference_manifests()
    case = next(
        item for item in payload["incompatible_assumptions"] if item["id"] == case_id
    )
    by_domain = reference_by_domain(payload)
    left = by_domain[str(case["left_domain"])]["vector_space"]
    right = by_domain[str(case["right_domain"])]["vector_space"]
    with pytest.raises(VectorSpaceIncompatibilityError, match="not interchangeable"):
        require_compatible_vector_spaces(
            left,
            right,
            left_name=str(case["left_domain"]),
            right_name=str(case["right_domain"]),
        )


def test_identical_vector_space_is_compatible() -> None:
    release = reference_by_domain(load_reference_manifests())["cvefixes"]
    space = release["vector_space"]
    assert (
        require_compatible_vector_spaces(space, dict(space), left_name="a", right_name="b")
        == space["vector_space_id"]
    )


def test_dimension_match_alone_never_implies_compatibility() -> None:
    """Regression for plan §2.4: 384-d MiniLM ≠ 384-d GTE."""

    by_domain = reference_by_domain(load_reference_manifests())
    left = by_domain["cvefixes"]["vector_space"]
    right = by_domain["skillcenter"]["vector_space"]
    assert left["dimension"] == right["dimension"] == 384
    assert left["model_id"] != right["model_id"]
    with pytest.raises(VectorSpaceIncompatibilityError, match="dimensions alone"):
        require_compatible_vector_spaces(left, right)


# ---------------------------------------------------------------------------
# Graph variations
# ---------------------------------------------------------------------------


def test_graph_ontologies_differ_across_reference_domains() -> None:
    by_domain = reference_by_domain(load_reference_manifests())
    ontologies = {
        domain: release["graph"]["ontology_version"]
        for domain, release in by_domain.items()
    }
    assert len(set(ontologies.values())) == len(ontologies)
    # Vocabularies are domain-private.
    assert "cve" in by_domain["cvefixes"]["graph"]["node_types"]
    assert "skill" in by_domain["skillcenter"]["graph"]["node_types"]
    assert "claim" in by_domain["patent"]["graph"]["node_types"]
    assert "cve" not in by_domain["patent"]["graph"]["node_types"]
    assert "claim" not in by_domain["skillcenter"]["graph"]["node_types"]


@pytest.mark.parametrize(
    "case_id",
    [
        "graph_ontology_cvefixes_vs_skillcenter",
        "graph_ontology_patent_vs_cvefixes",
    ],
)
def test_incompatible_graph_ontologies_raise_typed_error(case_id: str) -> None:
    payload = load_reference_manifests()
    case = next(
        item for item in payload["incompatible_assumptions"] if item["id"] == case_id
    )
    by_domain = reference_by_domain(payload)
    left = by_domain[str(case["left_domain"])]["graph"]
    right = by_domain[str(case["right_domain"])]["graph"]
    with pytest.raises(GraphOntologyIncompatibilityError):
        require_compatible_graph_ontologies(
            left,
            right,
            left_name=str(case["left_domain"]),
            right_name=str(case["right_domain"]),
        )


@pytest.mark.parametrize("domain", sorted(REQUIRED_DOMAINS))
def test_graph_families_share_substrate_layout(domain: str) -> None:
    release = reference_by_domain(load_reference_manifests())[domain]
    graph_artifacts = [
        item
        for item in release["artifacts"]
        if str(item["family"]).startswith("graph_")
    ]
    assert len(graph_artifacts) >= 4
    for artifact in graph_artifacts:
        family = ArtifactFamily.coerce(artifact["family"])
        assert family in {
            ArtifactFamily.GRAPH_NODES,
            ArtifactFamily.GRAPH_EDGES,
            ArtifactFamily.GRAPH_ADJACENCY_OUT,
            ArtifactFamily.GRAPH_ADJACENCY_IN,
        }
        path = normalize_relative_artifact_path(artifact["relative_path"])
        assert path.startswith("data/graph/")
        assert int(artifact["row_count"]) <= MAX_ROWS_PER_PHYSICAL_SHARD
    # Domain path aliases (outgoing/incoming vs out/in) are still confined.
    for artifact in graph_artifacts:
        if "adjacency" in artifact["relative_path"]:
            normalize_relative_artifact_path(artifact["relative_path"])


def test_identical_graph_ontology_is_compatible() -> None:
    graph = reference_by_domain(load_reference_manifests())["patent"]["graph"]
    assert (
        require_compatible_graph_ontologies(graph, dict(graph))
        == graph["ontology_version"]
    )


# ---------------------------------------------------------------------------
# Locators on reference-shaped keys
# ---------------------------------------------------------------------------


def test_locators_work_for_reference_entry_cid_layout() -> None:
    """CID locators are domain-neutral; keys stay entry_cid-ordered."""

    keys = [
        "bafyrefcvefix0003cccccccccccccccccccccccccccccccccccc",
        "bafyrefpatent0001aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "bafyrefpatent0002bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "bafyrefskill0004dddddddddddddddddddddddddddddddddddd",
    ]
    keys = sorted(keys)
    corpus_rows = build_locator_rows_from_keys(
        keys,
        kind=KIND_CORPUS,
        data_dir="data/corpus",
        max_rows_per_shard=2,
        sha256_seed="reference-compatibility-corpus",
    )
    vector_rows = build_locator_rows_from_keys(
        keys,
        kind=KIND_VECTORS,
        data_dir="data/vectors",
        max_rows_per_shard=2,
        sha256_seed="reference-compatibility-vectors",
    )
    dual = build_dual_cid_locators(
        corpus_rows=corpus_rows,
        vector_rows=vector_rows,
    )
    assert dual.corpus.kind == KIND_CORPUS
    assert dual.vectors.kind == KIND_VECTORS
    hit = dual.corpus.locate(keys[2])
    assert hit.relative_path.startswith("data/corpus/")
    with pytest.raises(MissingKeyError):
        dual.corpus.locate("missing-entry-cid")


def test_locator_row_rejects_path_escape_like_reference_malice() -> None:
    with pytest.raises(ArtifactPathError):
        LocatorRow.from_mapping(
            {
                "first_key": "a",
                "last_key": "b",
                "kind": KIND_CORPUS,
                "relative_path": "../escape.parquet",
                "row_count": 1,
                "schema_version": LOCATOR_SCHEMA_VERSION,
                "sha256": content_sha256("x"),
                "shard_id": 0,
                "size_bytes": 1,
            }
        )


# ---------------------------------------------------------------------------
# Cross-cutting: all incompatible cases dispatch
# ---------------------------------------------------------------------------


def test_all_incompatible_assumption_cases_raise_expected_typed_errors(
    tmp_path: Path,
) -> None:
    payload = load_reference_manifests()
    by_domain = reference_by_domain(payload)
    error_types = {
        "VectorSpaceIncompatibilityError": VectorSpaceIncompatibilityError,
        "GraphOntologyIncompatibilityError": GraphOntologyIncompatibilityError,
        "MutableRevisionError": MutableRevisionError,
        "PhysicalBoundError": PhysicalBoundError,
        "HfGraphragSchemaError": HfGraphragSchemaError,
        "SchemaMismatchError": SchemaMismatchError,
    }

    for case in payload["incompatible_assumptions"]:
        expect = error_types[str(case["expect_error"])]
        kind = case["kind"]
        if kind == "vector_space":
            left = by_domain[str(case["left_domain"])]["vector_space"]
            right = by_domain[str(case["right_domain"])]["vector_space"]
            with pytest.raises(expect):
                require_compatible_vector_spaces(left, right)
        elif kind == "graph_ontology":
            left = by_domain[str(case["left_domain"])]["graph"]
            right = by_domain[str(case["right_domain"])]["graph"]
            with pytest.raises(expect):
                require_compatible_graph_ontologies(left, right)
        elif kind == "immutable_resolution":
            with pytest.raises(expect):
                _resolver_for_release(
                    tmp_path / str(case["id"]),
                    by_domain["patent"],
                    revision=str(case["revision"]),
                )
        elif kind == "physical_bound":
            with pytest.raises(expect):
                validate_physical_row_count(int(case["row_count"]))
        elif kind == "artifact_family":
            with pytest.raises(expect):
                ArtifactFamily.coerce(case["family"])
        elif kind == "schema_mismatch":
            release = by_domain[str(case["domain"])]
            resolver = ImmutableHubResolver(
                repo_id=str(release["repo_id"]),
                revision=str(release["revision"]),
                cache_dir=tmp_path / f"mismatch-{case['id']}",
                transport=MappingTransport(release_transport_files(release)),
                supported_schemas=DEFAULT_SUPPORTED_RELEASE_SCHEMAS,
            )
            manifest_bytes = build_release_manifest_bytes(release)
            descriptor = build_descriptor_for_bytes(
                "manifest.json",
                manifest_bytes,
                schema_id=str(release["schema_version"]),
            )
            with pytest.raises(expect):
                resolver.load_manifest(descriptor=descriptor)
        else:
            raise AssertionError(f"unhandled incompatible kind: {kind}")


def test_resolver_descriptor_round_trip_matches_schema_family_paths() -> None:
    """Resolver and schema descriptors both accept the same relative paths."""

    release = reference_by_domain(load_reference_manifests())["cvefixes"]
    for artifact in release["artifacts"]:
        if artifact["relative_path"] == "manifest.json":
            # Control-plane manifest body is synthesized; recipe content_label
            # is only a fixture anchor, not the on-wire bytes.
            body = build_release_manifest_bytes(release)
            resolver_desc = build_descriptor_for_bytes(
                "manifest.json",
                body,
                schema_id=str(release["schema_version"]),
                media_type="application/json",
            )
            assert isinstance(resolver_desc, ResolverArtifactDescriptor)
            assert resolver_desc.relative_path == "manifest.json"
            assert len(resolver_desc.sha256) == 64
            continue

        body = _label_bytes(str(artifact["content_label"]))
        resolver_desc = build_descriptor_for_bytes(
            str(artifact["relative_path"]),
            body,
            schema_id=str(release["schema_version"]),
            row_count=int(artifact.get("row_count") or 0) or None,
        )
        assert isinstance(resolver_desc, ResolverArtifactDescriptor)
        schema_desc = schema_descriptor_from_artifact(
            artifact, schema_id=str(release["schema_version"])
        )
        assert resolver_desc.relative_path == schema_desc.relative_path
        assert resolver_desc.sha256 == schema_desc.sha256
        assert resolver_desc.size_bytes == schema_desc.size_bytes


def test_reference_fixture_is_json_serializable_and_compact() -> None:
    raw = FIXTURE_PATH.read_text(encoding="utf-8")
    # Prefer compact recipes over bulk golden dumps (admission policy).
    assert len(raw.encode("utf-8")) < 64_000
    payload = json.loads(raw)
    again = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    assert json.loads(again) == payload
