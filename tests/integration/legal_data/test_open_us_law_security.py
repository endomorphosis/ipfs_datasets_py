"""Integration tests for Open US Law fail-closed resource security (OUL-038).

Acceptance
----------
Malformed descriptors, path escapes, digest drift, oversized pages,
decompression bombs, hostile Parquet metadata, budget exhaustion, stale
bucket pointers, and cross-release vector misuse fail closed before bytes
are trusted. Two clean fixture builds remain byte-identical.

Recipes stay compact and local. A green run never authorizes publication.
"""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    PINNED_MODEL_ID,
    PINNED_MODEL_REVISION,
    EmbeddingConfigError,
    OpenUsLawEmbeddingConfig,
    default_vector_space_id,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_resolver import (
    AUTHORIZED_BUCKET_ID,
    DEFAULT_MANIFEST_NAME,
    BucketPrefixError,
    MappingTransport,
    MutablePointerError,
    OpenUsLawResolver,
    OpenUsLawResolverError,
    PrefixConfinedTransport,
    ResolverBudgetExhausted,
    ResolverLimits,
    RouteJustification,
    UnauthorizedTargetError,
    UnsafePathError,
    prefix_bucket_files,
    reject_mutable_pointer,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    MAX_ROWS_PER_PHYSICAL_SHARD,
    RELEASE_PROFILE,
    digest_mapping,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_vectors import (
    VectorBindingError,
    bind_open_us_law_vectors,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    ArtifactIntegrityError,
    PhysicalBoundError,
    validate_zstd_parquet,
    write_zstd_parquet,
)
from ipfs_datasets_py.retrieval.hf_graphrag.hierarchical_routes import (
    MAX_DESCRIPTORS_PER_ROUTE_PAGE,
    RouteIntegrityError,
    RoutePage,
    RoutePageError,
    verify_route_page,
)
from ipfs_datasets_py.retrieval.hf_graphrag.remote_search import (
    ModelSpace,
    ModelSpaceMismatchError,
    assert_model_space_compatible,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    ArtifactDescriptor,
    DigestDriftError,
    OversizedArtifactError,
    SchemaMismatchError,
    build_descriptor_for_bytes,
    safe_relative_path,
)


CHECKER_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "ops"
    / "legal_data"
    / "check_open_us_law_reproducibility.py"
)
REPORT_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "reports"
    / "open_us_law_reindex"
    / "reproducibility.json"
)

PINNED_REVISION = "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
FOREIGN_MINILM_REVISION = "c9745ed1d9f207416be6d2e6f19aa49b8566f3e3"
CORPUS_PATH = "data/corpus/part-000000.parquet"
PARQUET_MEDIA = "application/vnd.apache.parquet"

REQUIRED_CATEGORIES = frozenset(
    {
        "malformed_descriptors",
        "path_escapes",
        "digest_drift",
        "oversized_pages",
        "decompression_bombs",
        "hostile_parquet_metadata",
        "budget_exhaustion",
        "stale_bucket_pointers",
        "cross_release_vector_misuse",
    }
)


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_open_us_law_reproducibility", CHECKER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    assert CHECKER_PATH.is_file()
    return _load_checker()


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


def _dataset(
    tmp_path: Path,
    files: dict[str, bytes],
    *,
    limits: ResolverLimits | None = None,
) -> OpenUsLawResolver:
    return OpenUsLawResolver.for_dataset(
        PINNED_REVISION,
        artifact_transport=MappingTransport(files),
        cache_dir=tmp_path / "cache",
        limits=limits,
    )


def _corpus_route(path: str = CORPUS_PATH) -> RouteJustification:
    return RouteJustification(family="corpus", reason="hydrate_hit", relative_path=path)


def _durable(nibble: str) -> str:
    return "sha256:" + (nibble * 64)[:64]


def _unit_vector(offset: int = 0) -> list[float]:
    values = [0.0] * 384
    values[offset % 384] = 1.0
    return values


# ---------------------------------------------------------------------------
# Two clean builds
# ---------------------------------------------------------------------------


def test_two_clean_fixture_builds_are_byte_identical() -> None:
    pytest.importorskip("pyarrow")
    try:
        from ipfs_datasets_py.processors.legal_data.open_us_law_hf_release import (
            build_open_us_law_hf_release,
            fixture_family_rows,
            releases_are_byte_identical,
        )
    except ModuleNotFoundError as exc:
        pytest.skip(f"HF release extras unavailable: {exc}")

    first = build_open_us_law_hf_release(fixture_family_rows(), dry_run=True)
    second = build_open_us_law_hf_release(fixture_family_rows(), dry_run=True)
    assert releases_are_byte_identical(first, second)
    assert first.manifest_digest == second.manifest_digest
    assert first.release_root_cid == second.release_root_cid
    assert first.dry_run is True


def test_checker_two_clean_builds_and_staging(tmp_path: Path, checker: ModuleType) -> None:
    result = checker.run_two_clean_fixture_builds(tmp_path / "builds")
    assert result["two_clean_builds_byte_identical"] is True
    assert result["in_memory_identical"] is True
    assert result["staged_identical"] is True
    assert result["artifact_count"] >= 3
    assert result["bm25_index_root_cid"]
    assert result["vector_root_cid"]
    assert result["graph_cid"]
    assert result["manifest_digest"]
    assert result["release_root_cid"]


# ---------------------------------------------------------------------------
# Malformed descriptors
# ---------------------------------------------------------------------------


def test_malformed_descriptors_fail_closed() -> None:
    with pytest.raises((SchemaMismatchError, DigestDriftError, ValueError)):
        ArtifactDescriptor.from_mapping({"relative_path": CORPUS_PATH})
    with pytest.raises((SchemaMismatchError, DigestDriftError, ValueError)):
        ArtifactDescriptor.from_mapping(
            {"relative_path": CORPUS_PATH, "sha256": "ab" * 32, "size_bytes": -4}
        )
    with pytest.raises((UnsafePathError, SchemaMismatchError)):
        ArtifactDescriptor.from_mapping(
            {
                "relative_path": "../secrets/token",
                "sha256": "ab" * 32,
                "size_bytes": 8,
            }
        )
    with pytest.raises(SchemaMismatchError):
        ArtifactDescriptor.from_mapping("not-a-mapping")  # type: ignore[arg-type]


def test_descriptor_path_mismatch_is_not_success(tmp_path: Path) -> None:
    payload = b"PAR1-corpus"
    artifacts = [
        build_descriptor_for_bytes(CORPUS_PATH, payload, row_count=1).to_dict()
    ]
    _body, manifest, _digest = _sealed_manifest(artifacts=artifacts)
    resolver = _dataset(tmp_path, {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: payload})
    resolver.load_manifest()
    wrong = ArtifactDescriptor.from_mapping(
        {**artifacts[0], "relative_path": "data/corpus/other.parquet"}
    )
    with pytest.raises(UnsafePathError):
        resolver.resolve(CORPUS_PATH, route=_corpus_route(), descriptor=wrong)


# ---------------------------------------------------------------------------
# Path escapes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relative_path",
    [
        "../secrets/token",
        "../../etc/passwd",
        "/etc/passwd",
        "~/.ssh/id_rsa",
        "data/../../../LATEST.json",
        "data\\..\\secret",
        "//server/share/file",
    ],
)
def test_path_escapes_fail_closed(relative_path: str, tmp_path: Path) -> None:
    _body, manifest, _digest = _sealed_manifest()
    resolver = _dataset(tmp_path, {DEFAULT_MANIFEST_NAME: manifest})
    with pytest.raises((UnsafePathError, MutablePointerError, OpenUsLawResolverError)):
        resolver.resolve(
            relative_path,
            route={
                "family": "corpus",
                "reason": "hydrate_hit",
                "relative_path": relative_path,
            },
        )
    with pytest.raises((UnsafePathError, OpenUsLawResolverError)):
        safe_relative_path(relative_path)


# ---------------------------------------------------------------------------
# Digest drift
# ---------------------------------------------------------------------------


def test_digest_and_size_drift_fail_closed(tmp_path: Path) -> None:
    honest = b"PAR1-honest-corpus"
    forged = b"PAR1-forged-corpus-bytes"
    artifacts = [
        build_descriptor_for_bytes(CORPUS_PATH, honest, row_count=1).to_dict()
    ]
    _body, manifest, _digest = _sealed_manifest(artifacts=artifacts)
    resolver = _dataset(
        tmp_path, {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: forged}
    )
    resolver.load_manifest()
    with pytest.raises(DigestDriftError):
        resolver.resolve(CORPUS_PATH, route=_corpus_route())


def test_bucket_manifest_digest_swap_fails_closed(tmp_path: Path) -> None:
    _body, manifest, digest = _sealed_manifest()
    tampered = json.loads(manifest.decode("utf-8"))
    tampered["manifest_digest"] = "00" * 32
    raw = json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode("utf-8")
    resolver = OpenUsLawResolver.for_bucket(
        digest,
        artifact_transport=MappingTransport(prefix_bucket_files(digest, {DEFAULT_MANIFEST_NAME: raw})),
        cache_dir=tmp_path / "cache",
    )
    with pytest.raises(DigestDriftError, match="manifest_digest"):
        resolver.load_manifest()


# ---------------------------------------------------------------------------
# Oversized pages
# ---------------------------------------------------------------------------


def test_production_page_and_shard_bounds_are_4096() -> None:
    assert MAX_DESCRIPTORS_PER_ROUTE_PAGE == 4096
    assert MAX_ROWS_PER_PHYSICAL_SHARD == 4096


def test_oversized_route_pages_fail_closed(checker: ModuleType) -> None:
    descriptors = [checker._route_descriptor(index) for index in range(3)]
    with pytest.raises(RoutePageError):
        RoutePage.from_descriptors(
            descriptors,
            kind="corpus",
            level=0,
            page_index=0,
            max_rows_per_page=2,
        )
    honest = RoutePage.from_descriptors(
        descriptors[:2],
        kind="corpus",
        level=0,
        page_index=0,
        max_rows_per_page=2,
    )
    verify_route_page(honest)
    drifted = RoutePage(
        descriptors=honest.descriptors,
        kind=honest.kind,
        level=honest.level,
        page_index=honest.page_index,
        relative_path=honest.relative_path,
        sha256="ff" * 32,
        size_bytes=honest.size_bytes,
        first_key=honest.first_key,
        last_key=honest.last_key,
        leaf_count=honest.leaf_count,
    )
    with pytest.raises(RouteIntegrityError):
        verify_route_page(drifted)


def test_parquet_row_limit_is_physical_bound(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    path = tmp_path / "too-many.parquet"
    rows = [{"entry_cid": f"row-{index:04d}"} for index in range(5)]
    write_zstd_parquet(path, rows, max_rows=8)
    with pytest.raises((PhysicalBoundError, ArtifactIntegrityError)):
        validate_zstd_parquet(path, max_rows=2)


# ---------------------------------------------------------------------------
# Decompression bombs
# ---------------------------------------------------------------------------


def test_gzip_decompression_bomb_fails_closed(checker: ModuleType) -> None:
    bomb = checker.gzip_bomb_bytes()
    assert len(bomb) < checker.DECOMPRESSION_BOMB_INPUT_BYTES
    with pytest.raises(checker.DecompressionBombError):
        checker.bounded_decompress(bomb, max_out=checker.DECOMPRESSION_BOMB_BUDGET)
    honest = gzip.compress(b"open-us-law-fixture", compresslevel=9)
    assert checker.bounded_decompress(honest, max_out=4096) == b"open-us-law-fixture"


def test_trailing_hostile_gzip_bytes_fail_closed(checker: ModuleType) -> None:
    honest = gzip.compress(b"open-us-law", compresslevel=9)
    with pytest.raises(checker.DecompressionBombError):
        checker.bounded_decompress(honest + b"\x00TRAILER", max_out=4096)


# ---------------------------------------------------------------------------
# Hostile Parquet metadata
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        "snappy",
        "too_many_rows",
        "too_many_columns",
        "huge_kv_metadata",
        "truncated_magic",
        "hostile_footer",
    ],
)
def test_hostile_parquet_metadata_fails_closed(
    kind: str, tmp_path: Path, checker: ModuleType
) -> None:
    if kind not in {"truncated_magic", "hostile_footer"}:
        pytest.importorskip("pyarrow")
    target = tmp_path / f"{kind}.parquet"
    checker.write_hostile_parquet(target, kind=kind, max_rows=2)
    with pytest.raises(
        (
            checker.HostileParquetError,
            ArtifactIntegrityError,
            PhysicalBoundError,
        )
    ):
        checker.admit_parquet_file(target, max_rows=2)


def test_honest_zstd_parquet_is_admitted(tmp_path: Path, checker: ModuleType) -> None:
    pytest.importorskip("pyarrow")
    path = tmp_path / "honest.parquet"
    write_zstd_parquet(path, [{"entry_cid": _durable("a")}], max_rows=4)
    meta = checker.admit_parquet_file(path, max_rows=4, expected_row_count=1)
    assert meta["row_count"] == 1
    assert meta["compressions"] == ["ZSTD"]


# ---------------------------------------------------------------------------
# Budget exhaustion
# ---------------------------------------------------------------------------


def test_byte_and_row_budgets_fail_closed(tmp_path: Path) -> None:
    payload = b"PAR1-budget-corpus-bytes-xxxxxxxxxxxxx"
    artifacts = [
        build_descriptor_for_bytes(CORPUS_PATH, payload, row_count=8).to_dict()
    ]
    _body, manifest, _digest = _sealed_manifest(artifacts=artifacts)
    files = {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: payload}

    byte_resolver = _dataset(
        tmp_path / "bytes",
        files,
        limits=ResolverLimits(max_bytes=32, max_artifact_bytes=1024, max_shards=8, max_rows=64),
    )
    byte_resolver.load_manifest()
    with pytest.raises((ResolverBudgetExhausted, OversizedArtifactError)) as excinfo:
        byte_resolver.resolve(CORPUS_PATH, route=_corpus_route())
    if isinstance(excinfo.value, ResolverBudgetExhausted):
        assert excinfo.value.dimension == "bytes"

    row_resolver = _dataset(
        tmp_path / "rows",
        files,
        limits=ResolverLimits(max_bytes=1024, max_artifact_bytes=1024, max_shards=8, max_rows=2),
    )
    row_resolver.load_manifest()
    with pytest.raises(ResolverBudgetExhausted) as row_exc:
        row_resolver.resolve(CORPUS_PATH, route=_corpus_route())
    assert row_exc.value.dimension == "rows"


def test_oversized_descriptor_fails_closed_before_fetch(tmp_path: Path) -> None:
    payload = b"x" * 64
    artifacts = [build_descriptor_for_bytes(CORPUS_PATH, payload, row_count=1).to_dict()]
    _body, manifest, _digest = _sealed_manifest(artifacts=artifacts)
    resolver = _dataset(
        tmp_path,
        {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: payload},
        limits=ResolverLimits(max_artifact_bytes=16, max_bytes=1024, max_shards=8),
    )
    with pytest.raises(OversizedArtifactError):
        resolver.load_manifest()


# ---------------------------------------------------------------------------
# Stale bucket pointers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pin",
    [
        "LATEST.json",
        "latest",
        "releases/latest/",
        "releases/latest.json",
        "main",
        "HEAD",
        "master",
    ],
)
def test_stale_bucket_and_mutable_pins_fail_closed(pin: str, tmp_path: Path) -> None:
    with pytest.raises(MutablePointerError):
        reject_mutable_pointer(pin)
    with pytest.raises(
        (MutablePointerError, BucketPrefixError, UnsafePathError, OpenUsLawResolverError)
    ):
        OpenUsLawResolver.for_bucket(
            bucket_prefix=pin,
            artifact_transport=MappingTransport({}),
            cache_dir=tmp_path / "cache",
        )


def test_stale_release_latest_manifest_pointer_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(
        (MutablePointerError, BucketPrefixError, UnsafePathError, OpenUsLawResolverError)
    ):
        OpenUsLawResolver.for_bucket(
            bucket_prefix="releases/latest/manifest.json",
            artifact_transport=MappingTransport({}),
            cache_dir=tmp_path / "cache",
        )


def test_bucket_prefix_confinement_rejects_raw_root_and_pointer(tmp_path: Path) -> None:
    _body, manifest, digest = _sealed_manifest()
    inner = MappingTransport(
        {
            **prefix_bucket_files(digest, {DEFAULT_MANIFEST_NAME: manifest}),
            "LATEST.json": b'{"manifest_sha256":"tamper"}',
            "raw-root.parquet": b"legacy-raw",
        }
    )
    confined = PrefixConfinedTransport(inner, prefix=f"releases/{digest}/")
    with pytest.raises((MutablePointerError, UnsafePathError)):
        confined.remote_path("LATEST.json")
    with pytest.raises((UnsafePathError, MutablePointerError)):
        confined.remote_path("raw-root.parquet")
    with pytest.raises(BucketPrefixError):
        confined.remote_path(f"releases/{'00' * 32}/manifest.json")
    assert confined.remote_path(DEFAULT_MANIFEST_NAME) == f"releases/{digest}/manifest.json"


def test_unauthorized_bucket_identity_fails_before_transport(tmp_path: Path) -> None:
    class _Boom:
        def fetch(self, **kwargs: object) -> Path:
            raise AssertionError("transport must not run for unauthorized targets")

    with pytest.raises(UnauthorizedTargetError):
        OpenUsLawResolver(
            transport="bucket",
            manifest_sha256="ab" * 32,
            bucket_id="evil/bucket",
            artifact_transport=_Boom(),  # type: ignore[arg-type]
            cache_dir=tmp_path / "cache",
        )
    assert AUTHORIZED_BUCKET_ID == "justicedao/open-us-law-bucket"


# ---------------------------------------------------------------------------
# Cross-release vector misuse
# ---------------------------------------------------------------------------


def test_cross_release_model_spaces_fail_closed() -> None:
    pinned = default_vector_space_id()
    release = ModelSpace(
        model_id=PINNED_MODEL_ID,
        model_revision=PINNED_MODEL_REVISION,
        vector_space_id=pinned,
        dimension=384,
        pooling="mean",
        normalization="l2",
    )
    foreign = (
        ModelSpace(
            model_id="sentence-transformers/all-MiniLM-L6-v2",
            model_revision=FOREIGN_MINILM_REVISION,
            vector_space_id=(
                f"all-minilm-l6-v2@{FOREIGN_MINILM_REVISION}:d384:pool=mean:norm=l2"
            ),
            dimension=384,
            pooling="mean",
            normalization="l2",
        ),
        ModelSpace(
            model_id=PINNED_MODEL_ID,
            model_revision=PINNED_MODEL_REVISION,
            vector_space_id=f"uscode@{PINNED_MODEL_REVISION}:d384:pool=mean:norm=l2",
            dimension=384,
            pooling="mean",
            normalization="l2",
        ),
        ModelSpace(
            model_id=PINNED_MODEL_ID,
            model_revision=PINNED_MODEL_REVISION,
            vector_space_id=pinned,
            dimension=768,
            pooling="mean",
            normalization="l2",
        ),
    )
    for query in foreign:
        with pytest.raises(ModelSpaceMismatchError):
            assert_model_space_compatible(release, query)
    assert assert_model_space_compatible(release, release) is release


def test_embedding_config_rejects_foreign_vector_space() -> None:
    with pytest.raises(EmbeddingConfigError):
        OpenUsLawEmbeddingConfig(
            vector_space_id=f"skillcenter@{PINNED_MODEL_REVISION}:d384:pool=mean:norm=l2"
        )


def test_mixed_embedding_pins_fail_closed() -> None:
    pinned = default_vector_space_id()
    honest = {
        "chunk_cid": _durable("a"),
        "config_cid": "sha256:" + "11" * 32,
        "dimension": 384,
        "embedding": _unit_vector(0),
        "entry_cid": _durable("b"),
        "model_id": PINNED_MODEL_ID,
        "model_revision": PINNED_MODEL_REVISION,
        "normalization": "l2",
        "pooling": "mean",
        "vector_space_id": pinned,
    }
    foreign = dict(honest)
    foreign["chunk_cid"] = _durable("c")
    foreign["entry_cid"] = _durable("d")
    foreign["embedding"] = _unit_vector(1)
    foreign["vector_space_id"] = f"cve@{PINNED_MODEL_REVISION}:d384:pool=mean:norm=l2"
    foreign["config_cid"] = "sha256:" + "22" * 32
    with pytest.raises(VectorBindingError):
        bind_open_us_law_vectors([honest, foreign])


# ---------------------------------------------------------------------------
# Sealed report + checker recipes
# ---------------------------------------------------------------------------


def test_fail_closed_recipe_suite_covers_every_category(
    tmp_path: Path, checker: ModuleType
) -> None:
    security = checker.run_fail_closed_security_recipes(tmp_path / "recipes")
    assert security["every_category_fail_closed"] is True
    assert set(security["categories"]) == REQUIRED_CATEGORIES
    assert security["case_count"] >= len(REQUIRED_CATEGORIES)
    for category in REQUIRED_CATEGORIES:
        assert security["by_category"][category] >= 1
        for case in security["cases"][category]:
            assert case["fail_closed"] is True


def test_sealed_reproducibility_report_matches_contract(checker: ModuleType) -> None:
    assert REPORT_PATH.is_file(), f"missing reproducibility report: {REPORT_PATH}"
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    result = checker.check_reproducibility_report(payload)
    assert result["acceptance"] is True
    assert payload["task_id"] == "OUL-038"
    assert payload["goal_id"] == "OUL-G060"
    assert payload["authorizing_for_publication"] is False
    assert payload["authorizing_for_release"] is False
    assert payload["fixture_only"] is True
    assert payload["proves_software_contract_only"] is True
    assert set(payload["fail_closed"]["categories"]) == REQUIRED_CATEGORIES
    rendered = json.dumps(payload, sort_keys=True)
    assert "hf_" not in rendered
    assert "/home/" not in rendered
    assert "file://" not in rendered
    assert "Bearer " not in rendered
