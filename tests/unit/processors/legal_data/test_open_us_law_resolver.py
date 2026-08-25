"""Unit tests for content-addressed Bucket and immutable Dataset resolution (OUL-033).

Acceptance
----------
* Dataset queries require a 40-hex revision.
* Bucket queries require ``releases/<manifest_sha256>/`` and verified descriptors.
* Both transports fetch only routed artifacts under explicit byte, shard, row,
  time, graph, and centroid budgets.
* Mutable pointers and digest/size/schema drift fail closed.

Tests inject :class:`MappingTransport` only. No live Hub or Bucket I/O.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_resolver import (
    AUTHORIZED_BUCKET_ID,
    AUTHORIZED_DATASET_REPO_ID,
    DEFAULT_MANIFEST_NAME,
    RESOLVER_SCHEMA_VERSION,
    BucketPrefixError,
    DescriptorRequiredError,
    DigestDriftError,
    MappingTransport,
    MutablePointerError,
    OpenUsLawResolver,
    OpenUsLawResolverError,
    ResolverBudgetExhausted,
    ResolverLimits,
    RouteJustification,
    SchemaMismatchError,
    UnauthorizedTargetError,
    UnjustifiedFetchError,
    UnsafePathError,
    authorize_query_pin,
    control_plane_route,
    is_mutable_pointer,
    prefix_bucket_files,
    require_bucket_release_prefix,
    require_dataset_revision,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    RELEASE_PROFILE,
    digest_mapping,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import build_descriptor_for_bytes


PINNED_REVISION = "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
CORPUS_PATH = "data/corpus/part-000000.parquet"
CENTROID_PATH = "data/vectors/centroid-000000-part-000000.parquet"
GRAPH_NODES_PATH = "data/graph/nodes-part-000000.parquet"
GRAPH_EDGES_PATH = "data/graph/edges-part-000000.parquet"


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += float(seconds)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sealed_manifest(
    *,
    artifacts: list[dict[str, object]] | None = None,
    **extra: object,
) -> tuple[dict[str, object], bytes, str]:
    body: dict[str, object] = {
        "artifacts": list(artifacts or []),
        "primary_key": "entry_cid",
        "release_profile": RELEASE_PROFILE,
        "schema_version": RELEASE_PROFILE,
    }
    body.update(extra)
    digest = digest_mapping(body)
    body["manifest_digest"] = digest
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return body, raw, digest


def _corpus_bytes() -> bytes:
    return b"PAR1-open-us-law-corpus-fixture-row"

def _centroid_bytes() -> bytes:
    return b"PAR1-open-us-law-centroid-fixture"

def _graph_nodes_bytes() -> bytes:
    return b"PAR1-open-us-law-graph-nodes"

def _graph_edges_bytes() -> bytes:
    return b"PAR1-open-us-law-graph-edges"


def _inventory(*items: tuple[str, bytes, int]) -> list[dict[str, object]]:
    descriptors = []
    for path, content, rows in items:
        descriptors.append(
            build_descriptor_for_bytes(
                path,
                content,
                schema_id=RELEASE_PROFILE,
                row_count=rows,
                media_type="application/vnd.apache.parquet",
            ).to_dict()
        )
    return descriptors


def _dataset_resolver(
    tmp_path: Path,
    files: dict[str, bytes],
    *,
    revision: str = PINNED_REVISION,
    limits: ResolverLimits | dict[str, int] | None = None,
    token: str | None = None,
    clock: _Clock | None = None,
    require_descriptors: bool = True,
) -> OpenUsLawResolver:
    return OpenUsLawResolver.for_dataset(
        revision,
        artifact_transport=MappingTransport(files),
        cache_dir=tmp_path / "cache-dataset",
        limits=limits,
        token=token,
        clock=clock or time_clock(),
        require_descriptors=require_descriptors,
    )


def time_clock() -> _Clock:
    return _Clock()


def _bucket_resolver(
    tmp_path: Path,
    files: dict[str, bytes],
    *,
    manifest_sha256: str,
    limits: ResolverLimits | dict[str, int] | None = None,
    token: str | None = None,
    clock: _Clock | None = None,
    require_descriptors: bool = True,
) -> OpenUsLawResolver:
    return OpenUsLawResolver.for_bucket(
        manifest_sha256,
        artifact_transport=MappingTransport(
            prefix_bucket_files(manifest_sha256, files)
        ),
        cache_dir=tmp_path / "cache-bucket",
        limits=limits,
        token=token,
        clock=clock or time_clock(),
        require_descriptors=require_descriptors,
    )


def _data_route(path: str, family: str, reason: str, **metadata: object) -> RouteJustification:
    return RouteJustification(
        family=family,
        reason=reason,
        relative_path=path,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Pin validation
# ---------------------------------------------------------------------------


def test_dataset_revision_must_be_40_hex() -> None:
    assert require_dataset_revision(PINNED_REVISION) == PINNED_REVISION
    assert require_dataset_revision(PINNED_REVISION.upper()) == PINNED_REVISION


@pytest.mark.parametrize(
    "revision",
    [
        "main",
        "latest",
        "HEAD",
        "master",
        "refs/heads/main",
        "LATEST.json",
        "75cfc5982dc3a6808614",
        "https://huggingface.co/datasets/x/y/resolve/main/manifest.json",
    ],
)
def test_mutable_dataset_revisions_fail_closed(revision: str, tmp_path: Path) -> None:
    with pytest.raises(MutablePointerError):
        require_dataset_revision(revision)
    with pytest.raises(MutablePointerError):
        _dataset_resolver(tmp_path, {}, revision=revision)


def test_bucket_prefix_requires_releases_manifest_digest() -> None:
    digest = "ab" * 32
    assert require_bucket_release_prefix(digest) == (digest, f"releases/{digest}/")
    assert require_bucket_release_prefix(f"releases/{digest}/") == (
        digest,
        f"releases/{digest}/",
    )


@pytest.mark.parametrize(
    "prefix",
    [
        "LATEST.json",
        "latest",
        "releases/latest/",
        "releases/main/manifest.json",
        "raw/corpus.parquet",
        "",
        None,
    ],
)
def test_mutable_or_missing_bucket_pins_fail_closed(prefix: object, tmp_path: Path) -> None:
    with pytest.raises((MutablePointerError, BucketPrefixError, OpenUsLawResolverError)):
        require_bucket_release_prefix(prefix)
    kwargs = {"bucket_prefix": prefix} if prefix else {}
    with pytest.raises((MutablePointerError, BucketPrefixError, OpenUsLawResolverError)):
        OpenUsLawResolver.for_bucket(
            artifact_transport=MappingTransport({}),
            cache_dir=tmp_path / "cache",
            **kwargs,
        )


def test_dataset_constructor_rejects_bucket_prefix(tmp_path: Path) -> None:
    with pytest.raises(MutablePointerError, match="40-hex"):
        OpenUsLawResolver(
            transport="dataset",
            revision=PINNED_REVISION,
            bucket_prefix=f"releases/{'ab' * 32}/",
            artifact_transport=MappingTransport({}),
            cache_dir=tmp_path / "cache",
        )


def test_bucket_constructor_rejects_dataset_revision_as_identity(tmp_path: Path) -> None:
    with pytest.raises(MutablePointerError, match="releases/"):
        OpenUsLawResolver(
            transport="bucket",
            revision=PINNED_REVISION,
            artifact_transport=MappingTransport({}),
            cache_dir=tmp_path / "cache",
        )


def test_unauthorized_targets_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(UnauthorizedTargetError):
        OpenUsLawResolver.for_dataset(
            PINNED_REVISION,
            dataset_repo_id="other/repo",
            artifact_transport=MappingTransport({}),
            cache_dir=tmp_path / "cache",
        )
    with pytest.raises(UnauthorizedTargetError):
        OpenUsLawResolver.for_bucket(
            "ab" * 32,
            bucket_id="other/bucket",
            artifact_transport=MappingTransport({}),
            cache_dir=tmp_path / "cache",
        )


def test_authorize_query_pin_is_read_only() -> None:
    dataset = authorize_query_pin(transport="dataset", revision=PINNED_REVISION)
    assert dataset["authorized"] is True
    assert dataset["network_mutation_permitted"] is False
    assert dataset["operation"] == "dataset_query"
    digest = "cd" * 32
    bucket = authorize_query_pin(
        transport="bucket",
        bucket_prefix=f"releases/{digest}/",
        manifest_sha256=digest,
    )
    assert bucket["authorized"] is True
    assert bucket["network_mutation_permitted"] is False
    assert bucket["operation"] == "bucket_query"


# ---------------------------------------------------------------------------
# Dataset happy path
# ---------------------------------------------------------------------------


def test_dataset_resolve_requires_40_hex_and_records_safe_trace(tmp_path: Path) -> None:
    corpus = _corpus_bytes()
    artifacts = _inventory((CORPUS_PATH, corpus, 2))
    _body, manifest, _digest = _sealed_manifest(artifacts=artifacts)
    resolver = _dataset_resolver(
        tmp_path, {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: corpus}
    )

    loaded = resolver.load_manifest()
    assert loaded["schema_version"] == RELEASE_PROFILE
    assert resolver.revision == PINNED_REVISION
    assert resolver.transport == "dataset"

    descriptor = resolver.descriptor_for(CORPUS_PATH)
    assert descriptor is not None
    artifact = resolver.resolve(
        CORPUS_PATH,
        route=_data_route(CORPUS_PATH, "corpus", "hydrate_hit"),
        descriptor=descriptor,
    )
    assert artifact.verified is True
    assert artifact.cache_hit is False
    assert artifact.sha256 == _sha(corpus)
    again = resolver.resolve(
        CORPUS_PATH,
        route=_data_route(CORPUS_PATH, "corpus", "hydrate_hit"),
    )
    assert again.cache_hit is True

    trace = resolver.fetch_trace()
    assert trace["resolver_schema_version"] == RESOLVER_SCHEMA_VERSION
    assert trace["transport"] == "dataset"
    assert trace["revision"] == PINNED_REVISION
    assert trace["dataset_repo_id"] == AUTHORIZED_DATASET_REPO_ID
    assert trace["route_justified"] is True
    assert trace["verification_state"] == "verified"
    assert trace["network_mutation_permitted"] is False
    assert trace["publication_gate"]["authorized"] is True
    assert all(item["verified"] for item in trace["files"])
    rendered = json.dumps(trace)
    assert "hf_" not in rendered
    assert str(tmp_path) not in rendered
    assert "token" not in rendered


# ---------------------------------------------------------------------------
# Bucket happy path
# ---------------------------------------------------------------------------


def test_bucket_resolve_requires_release_prefix_and_verified_descriptors(
    tmp_path: Path,
) -> None:
    corpus = _corpus_bytes()
    artifacts = _inventory((CORPUS_PATH, corpus, 2))
    _body, manifest, digest = _sealed_manifest(artifacts=artifacts)
    resolver = _bucket_resolver(
        tmp_path,
        {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: corpus},
        manifest_sha256=digest,
    )
    assert resolver.transport == "bucket"
    assert resolver.bucket_prefix == f"releases/{digest}/"
    assert resolver.manifest_sha256 == digest
    assert resolver.bucket_id == AUTHORIZED_BUCKET_ID

    loaded = resolver.load_manifest()
    assert loaded["manifest_digest"] == digest
    descriptor = resolver.descriptor_for(CORPUS_PATH)
    assert descriptor is not None
    artifact = resolver.resolve(
        CORPUS_PATH,
        route=_data_route(CORPUS_PATH, "corpus", "hydrate_hit"),
    )
    assert artifact.verified is True
    assert artifact.sha256 == descriptor.sha256

    prefixed = resolver.resolve(
        f"releases/{digest}/{CORPUS_PATH}",
        route=_data_route(CORPUS_PATH, "corpus", "hydrate_hit"),
    )
    assert prefixed.relative_path == CORPUS_PATH
    assert prefixed.cache_hit is True

    trace = resolver.fetch_trace()
    assert trace["transport"] == "bucket"
    assert trace["bucket_prefix"] == f"releases/{digest}/"
    assert trace["manifest_sha256"] == digest
    assert all(
        item.get("remote_path", "").startswith(f"releases/{digest}/")
        for item in trace["files"]
    )
    assert str(tmp_path) not in json.dumps(trace)


def test_bucket_manifest_digest_drift_fails_closed(tmp_path: Path) -> None:
    _body, manifest, digest = _sealed_manifest()
    other = "ef" * 32
    resolver = OpenUsLawResolver.for_bucket(
        other,
        artifact_transport=MappingTransport(prefix_bucket_files(other, {DEFAULT_MANIFEST_NAME: manifest})),
        cache_dir=tmp_path / "cache",
    )
    with pytest.raises(DigestDriftError, match="manifest_digest"):
        resolver.load_manifest()


def test_bucket_recomputed_digest_drift_fails_closed(tmp_path: Path) -> None:
    body, _raw, digest = _sealed_manifest()
    body["producer"] = "tampered"
    # Keep the original digest so the prefix still matches the declared field,
    # but the recomputed digest diverges.
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    resolver = _bucket_resolver(
        tmp_path, {DEFAULT_MANIFEST_NAME: raw}, manifest_sha256=digest
    )
    with pytest.raises(DigestDriftError, match="recomputed"):
        resolver.load_manifest()


# ---------------------------------------------------------------------------
# Routed fetches only
# ---------------------------------------------------------------------------


def test_unjustified_fetch_fails_closed(tmp_path: Path) -> None:
    _body, manifest, _digest = _sealed_manifest()
    resolver = _dataset_resolver(tmp_path, {DEFAULT_MANIFEST_NAME: manifest})
    with pytest.raises(UnjustifiedFetchError):
        resolver.resolve(DEFAULT_MANIFEST_NAME, route={"family": "nope", "reason": "manifest"})
    with pytest.raises(UnjustifiedFetchError):
        resolver.resolve(DEFAULT_MANIFEST_NAME, route={"family": "control_plane", "reason": "nope"})
    with pytest.raises(UnjustifiedFetchError):
        resolver.resolve(
            DEFAULT_MANIFEST_NAME,
            route=_data_route(CORPUS_PATH, "control_plane", "manifest"),
        )


def test_data_plane_requires_verified_descriptor(tmp_path: Path) -> None:
    corpus = _corpus_bytes()
    _body, manifest, digest = _sealed_manifest()
    resolver = _bucket_resolver(
        tmp_path,
        {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: corpus},
        manifest_sha256=digest,
    )
    resolver.load_manifest()
    with pytest.raises(DescriptorRequiredError):
        resolver.resolve(
            CORPUS_PATH,
            route=_data_route(CORPUS_PATH, "corpus", "hydrate_hit"),
        )


def test_descriptor_inventory_drift_fails_closed(tmp_path: Path) -> None:
    corpus = _corpus_bytes()
    other = b"PAR1-tampered-corpus-bytes-not-matching"
    artifacts = _inventory((CORPUS_PATH, corpus, 2))
    _body, manifest, _digest = _sealed_manifest(artifacts=artifacts)
    resolver = _dataset_resolver(
        tmp_path, {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: corpus}
    )
    resolver.load_manifest()
    forged = build_descriptor_for_bytes(CORPUS_PATH, other, row_count=2)
    with pytest.raises(DigestDriftError, match="inventory"):
        resolver.resolve(
            CORPUS_PATH,
            route=_data_route(CORPUS_PATH, "corpus", "hydrate_hit"),
            descriptor=forged,
        )


def test_fetched_bytes_drift_fails_closed(tmp_path: Path) -> None:
    corpus = _corpus_bytes()
    swapped = b"PAR1-swapped-on-the-wire"
    artifacts = _inventory((CORPUS_PATH, corpus, 1))
    _body, manifest, _digest = _sealed_manifest(artifacts=artifacts)
    resolver = _dataset_resolver(
        tmp_path, {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: swapped}
    )
    resolver.load_manifest()
    with pytest.raises(DigestDriftError):
        resolver.resolve(
            CORPUS_PATH,
            route=_data_route(CORPUS_PATH, "corpus", "hydrate_hit"),
        )


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


def test_byte_budget_fails_closed_before_fetch(tmp_path: Path) -> None:
    corpus = _corpus_bytes()
    artifacts = _inventory((CORPUS_PATH, corpus, 1))
    _body, manifest, _digest = _sealed_manifest(artifacts=artifacts)
    resolver = _dataset_resolver(
        tmp_path,
        {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: corpus},
        limits=ResolverLimits(max_bytes=32, max_artifact_bytes=1024),
    )
    resolver.load_manifest()
    with pytest.raises(ResolverBudgetExhausted) as excinfo:
        resolver.resolve(
            CORPUS_PATH,
            route=_data_route(CORPUS_PATH, "corpus", "hydrate_hit"),
        )
    assert excinfo.value.dimension == "bytes"


def test_shard_and_row_budgets_fail_closed(tmp_path: Path) -> None:
    corpus = _corpus_bytes()
    second_path = "data/corpus/part-000001.parquet"
    second = corpus + b"-b"
    artifacts = _inventory((CORPUS_PATH, corpus, 8), (second_path, second, 8))
    _body, manifest, _digest = _sealed_manifest(artifacts=artifacts)
    shard_resolver = _dataset_resolver(
        tmp_path,
        {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: corpus, second_path: second},
        limits=ResolverLimits(max_shards=1, max_rows=100),
    )
    shard_resolver.load_manifest()
    shard_resolver.resolve(
        CORPUS_PATH,
        route=_data_route(CORPUS_PATH, "corpus", "hydrate_hit"),
    )
    with pytest.raises(ResolverBudgetExhausted) as excinfo:
        shard_resolver.resolve(
            second_path,
            route=_data_route(second_path, "corpus", "hydrate_hit"),
        )
    assert excinfo.value.dimension == "shards"

    row_resolver = _dataset_resolver(
        tmp_path,
        {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: corpus},
        limits=ResolverLimits(max_shards=8, max_rows=2),
    )
    row_resolver.load_manifest()
    with pytest.raises(ResolverBudgetExhausted) as excinfo:
        row_resolver.resolve(
            CORPUS_PATH,
            route=_data_route(CORPUS_PATH, "corpus", "hydrate_hit"),
        )
    assert excinfo.value.dimension == "rows"


def test_time_budget_fails_closed(tmp_path: Path) -> None:
    clock = _Clock()
    _body, manifest, _digest = _sealed_manifest()
    resolver = _dataset_resolver(
        tmp_path,
        {DEFAULT_MANIFEST_NAME: manifest},
        limits=ResolverLimits(max_time_ms=10),
        clock=clock,
    )
    clock.advance(1.0)
    with pytest.raises(ResolverBudgetExhausted) as excinfo:
        resolver.load_manifest()
    assert excinfo.value.dimension == "time"


def test_graph_budget_fails_closed(tmp_path: Path) -> None:
    nodes = _graph_nodes_bytes()
    artifacts = _inventory((GRAPH_NODES_PATH, nodes, 4))
    _body, manifest, _digest = _sealed_manifest(artifacts=artifacts)
    resolver = _dataset_resolver(
        tmp_path,
        {DEFAULT_MANIFEST_NAME: manifest, GRAPH_NODES_PATH: nodes},
        limits=ResolverLimits(max_graph_nodes=2, max_shards=8, max_rows=100),
    )
    resolver.load_manifest()
    with pytest.raises(ResolverBudgetExhausted) as excinfo:
        resolver.resolve(
            GRAPH_NODES_PATH,
            route=_data_route(GRAPH_NODES_PATH, "graph_nodes", "graph_node", depth=1),
        )
    assert excinfo.value.dimension == "graph"


def test_graph_depth_budget_fails_closed(tmp_path: Path) -> None:
    edges = _graph_edges_bytes()
    artifacts = _inventory((GRAPH_EDGES_PATH, edges, 1))
    _body, manifest, _digest = _sealed_manifest(artifacts=artifacts)
    resolver = _dataset_resolver(
        tmp_path,
        {DEFAULT_MANIFEST_NAME: manifest, GRAPH_EDGES_PATH: edges},
        limits=ResolverLimits(max_graph_depth=1, max_shards=8, max_rows=100),
    )
    resolver.load_manifest()
    with pytest.raises(ResolverBudgetExhausted) as excinfo:
        resolver.resolve(
            GRAPH_EDGES_PATH,
            route=_data_route(GRAPH_EDGES_PATH, "graph_edges", "graph_edge", depth=2),
        )
    assert excinfo.value.dimension == "graph"


def test_centroid_budget_fails_closed(tmp_path: Path) -> None:
    first = _centroid_bytes()
    second = first + b"-two"
    artifacts = _inventory(
        (CENTROID_PATH, first, 1),
        ("data/vectors/centroid-000001-part-000000.parquet", second, 1),
    )
    _body, manifest, _digest = _sealed_manifest(artifacts=artifacts)
    resolver = _dataset_resolver(
        tmp_path,
        {
            DEFAULT_MANIFEST_NAME: manifest,
            CENTROID_PATH: first,
            "data/vectors/centroid-000001-part-000000.parquet": second,
        },
        limits=ResolverLimits(max_centroids=1, max_shards=8, max_rows=100),
    )
    resolver.load_manifest()
    resolver.resolve(
        CENTROID_PATH,
        route=_data_route(CENTROID_PATH, "centroids", "centroid_probe"),
    )
    with pytest.raises(ResolverBudgetExhausted) as excinfo:
        resolver.resolve(
            "data/vectors/centroid-000001-part-000000.parquet",
            route=_data_route(
                "data/vectors/centroid-000001-part-000000.parquet",
                "centroids",
                "centroid_probe",
            ),
        )
    assert excinfo.value.dimension == "centroids"
    assert resolver.usage.snapshot()["centroids"] == 1


def test_both_transports_charge_every_budget_dimension(tmp_path: Path) -> None:
    corpus = _corpus_bytes()
    centroid = _centroid_bytes()
    nodes = _graph_nodes_bytes()
    artifacts = _inventory(
        (CORPUS_PATH, corpus, 2),
        (CENTROID_PATH, centroid, 1),
        (GRAPH_NODES_PATH, nodes, 3),
    )
    _body, manifest, digest = _sealed_manifest(artifacts=artifacts)
    files = {
        DEFAULT_MANIFEST_NAME: manifest,
        CORPUS_PATH: corpus,
        CENTROID_PATH: centroid,
        GRAPH_NODES_PATH: nodes,
    }
    for factory in (
        lambda: _dataset_resolver(tmp_path / "ds", files),
        lambda: _bucket_resolver(tmp_path / "bk", files, manifest_sha256=digest),
    ):
        resolver = factory()
        resolver.load_manifest()
        resolver.resolve(CORPUS_PATH, route=_data_route(CORPUS_PATH, "corpus", "hydrate_hit"))
        resolver.resolve(
            CENTROID_PATH,
            route=_data_route(CENTROID_PATH, "centroids", "centroid_probe"),
        )
        resolver.resolve(
            GRAPH_NODES_PATH,
            route=_data_route(GRAPH_NODES_PATH, "graph_nodes", "graph_node", depth=1),
        )
        usage = resolver.usage.snapshot()
        assert usage["bytes"] > 0
        assert usage["shards"] == 3
        assert usage["rows"] == 6
        assert usage["centroids"] == 1
        assert usage["graph_nodes"] == 3
        assert usage["graph_depth"] == 1
        assert usage["time_ms"] >= 0
        limits = resolver.fetch_trace()["limits"]
        for key in (
            "max_bytes",
            "max_shards",
            "max_rows",
            "max_time_ms",
            "max_graph_nodes",
            "max_graph_edges",
            "max_graph_depth",
            "max_centroids",
        ):
            assert key in limits


# ---------------------------------------------------------------------------
# Path confinement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relative_path",
    [
        "../secrets/token",
        "/etc/passwd",
        "LATEST.json",
        "latest",
        "data/../../etc/passwd",
        "raw-root.parquet",
    ],
)
def test_unsafe_or_mutable_paths_fail_closed(relative_path: str, tmp_path: Path) -> None:
    _body, manifest, _digest = _sealed_manifest()
    resolver = _dataset_resolver(tmp_path, {DEFAULT_MANIFEST_NAME: manifest})
    with pytest.raises(
        (UnsafePathError, MutablePointerError, UnjustifiedFetchError, OpenUsLawResolverError)
    ):
        resolver.resolve(
            relative_path,
            route={"family": "control_plane", "reason": "manifest", "relative_path": relative_path},
        )


def test_bucket_refuses_foreign_release_prefix(tmp_path: Path) -> None:
    _body, manifest, digest = _sealed_manifest()
    resolver = _bucket_resolver(
        tmp_path, {DEFAULT_MANIFEST_NAME: manifest}, manifest_sha256=digest
    )
    foreign = f"releases/{'11' * 32}/manifest.json"
    with pytest.raises(BucketPrefixError):
        resolver.resolve(foreign, route=control_plane_route(DEFAULT_MANIFEST_NAME))


def test_is_mutable_pointer_covers_acceptance_aliases() -> None:
    assert is_mutable_pointer("main")
    assert is_mutable_pointer("LATEST.json")
    assert is_mutable_pointer("releases/latest/")
    assert not is_mutable_pointer(PINNED_REVISION)
    assert not is_mutable_pointer(f"releases/{'ab' * 32}/manifest.json")


def test_unsupported_manifest_schema_fails_closed(tmp_path: Path) -> None:
    body = {"schema_version": "mutable/latest", "primary_key": "entry_cid"}
    raw = json.dumps(body).encode("utf-8")
    resolver = _dataset_resolver(tmp_path, {DEFAULT_MANIFEST_NAME: raw})
    with pytest.raises(SchemaMismatchError, match="unsupported"):
        resolver.load_manifest()


def test_control_plane_route_helper_matches_manifest() -> None:
    route = control_plane_route()
    assert route.family == "control_plane"
    assert route.reason == "manifest"
    assert route.relative_path == DEFAULT_MANIFEST_NAME
