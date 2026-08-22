"""Integration tests for state-law fail-closed resource security (LCR-037).

Acceptance
----------
Two isolated clean fixture builds share logical CIDs, routes, counts, and
the manifest digest. Traversal, symlink, digest, decompression, row,
resource, mutable-pin, secret, and partial-checkpoint attacks fail closed
before bytes are trusted. Streaming memory stays within the declared
``memory-large`` class. Allowable Parquet byte drift is explained and
bounded.

Recipes stay compact and local. A green run never authorizes publication
or Hub upload.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from ipfs_datasets_py.processors.legal_data.federal_register_release import (
    PromotionError,
    assert_promotable,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_streaming import (
    JurisdictionUnitRecord,
    PartialCheckpointPromotionError,
    StreamingCheckpoint,
    WorkUnitStatus,
)
from ipfs_datasets_py.processors.legal_data.state_laws_graphrag_adapter import (
    AbsolutePathError,
    AdapterPinError,
    DescriptorDriftError,
    assert_no_descriptor_drift,
    assert_no_home_paths_or_tokens,
    build_immutable_resolver,
    require_relative_artifact_path,
)
from ipfs_datasets_py.processors.legal_data.state_laws_hf_release import (
    assemble_state_laws_hf_release,
    fixture_family_rows,
    fixture_legacy_files,
    releases_are_byte_identical,
)
from ipfs_datasets_py.processors.legal_data.state_laws_query import (
    ImmutablePinError,
    assert_no_secrets,
    require_immutable_revision,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    MAX_ROWS_PER_PHYSICAL_SHARD,
    PREVIOUS_PUBLIC_PIN,
    PhysicalBoundError as StatePhysicalBoundError,
    validate_physical_row_count,
)
from ipfs_datasets_py.processors.legal_data.uscode_build import (
    ResourceLimitError,
    ResourceLimits,
    SealError,
    compute_seal,
    run_fixture_build as run_uscode_fixture_build,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    ArtifactIntegrityError,
    PhysicalBoundError,
    validate_zstd_parquet,
    write_zstd_parquet,
)
from ipfs_datasets_py.retrieval.hf_graphrag.external_sort import MemoryBudget, MemoryBudgetError
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    DigestDriftError,
    LocalRootTransport,
    MappingTransport,
    MutableRevisionError,
    OversizedArtifactError,
    SymlinkRejectedError,
    UnsafePathError,
    build_descriptor_for_bytes,
    file_sha256_and_size,
    safe_relative_path,
)


CHECKER_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "ops"
    / "legal_data"
    / "check_state_laws_reproducibility.py"
)
REPORT_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "reports"
    / "legal_corpora_reindex"
    / "reproducibility.json"
)

PINNED_REVISION = PREVIOUS_PUBLIC_PIN
CORPUS_PATH = "data/corpus/part-000000.parquet"
PARQUET_MEDIA = "application/vnd.apache.parquet"

REQUIRED_CATEGORIES = frozenset(
    {
        "traversal",
        "symlink",
        "digest",
        "decompression",
        "row",
        "resource",
        "mutable-pin",
        "secret",
        "partial-checkpoint",
    }
)


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_state_laws_reproducibility", CHECKER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    assert CHECKER_PATH.is_file()
    return _load_checker()


def _durable(nibble: str) -> str:
    return "sha256:" + (nibble * 64)[:64]


# ---------------------------------------------------------------------------
# Two clean builds
# ---------------------------------------------------------------------------


def test_two_clean_fixture_builds_are_logically_identical() -> None:
    pytest.importorskip("pyarrow")
    first = assemble_state_laws_hf_release(
        fixture_family_rows(),
        dry_run=True,
        legacy_files=fixture_legacy_files(),
    )
    second = assemble_state_laws_hf_release(
        fixture_family_rows(),
        dry_run=True,
        legacy_files=fixture_legacy_files(),
    )
    assert first.manifest_digest == second.manifest_digest
    assert first.release_root_cid == second.release_root_cid
    assert first.dry_run is True
    left = {item.relative_path: item for item in first.artifacts}
    right = {item.relative_path: item for item in second.artifacts}
    assert set(left) == set(right)
    for path, artifact in left.items():
        other = right[path]
        assert artifact.content_cid == other.content_cid
        assert artifact.row_count == other.row_count
        assert artifact.first_key == other.first_key
        assert artifact.last_key == other.last_key
    assert releases_are_byte_identical(first, second)


def test_checker_two_clean_builds_and_streaming(tmp_path: Path, checker: ModuleType) -> None:
    pytest.importorskip("pyarrow")
    result = checker.run_two_clean_fixture_builds(tmp_path / "builds")
    assert result["two_clean_builds_logical_identical"] is True
    assert result["in_memory_identical"] is True
    assert result["staged_identical"] is True
    assert result["artifact_count"] >= 3
    assert result["manifest_digest"]
    assert result["release_root_cid"]
    assert result["logical_cids"]
    assert result["routes"]
    assert result["counts"]
    assert result["memory"]["memory_within_declared_class"] is True
    assert result["memory"]["resource_class"] == "memory-large"
    assert result["memory"]["peak_resident_records"] <= checker.DECLARED_MAX_RESIDENT_RECORDS
    drift = result["parquet_byte_drift"]
    assert drift["within_bound"] is True
    assert drift["max_abs_delta_bytes"] <= checker.MAX_PARQUET_FOOTER_BYTES
    assert "footer" in drift["explanation"].lower()
    assert result["streaming"]["two_sorts_identical"] is True


# ---------------------------------------------------------------------------
# Traversal
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
    ],
)
def test_path_traversal_fails_closed(relative_path: str) -> None:
    with pytest.raises(UnsafePathError):
        safe_relative_path(relative_path)
    with pytest.raises((AbsolutePathError, UnsafePathError)):
        require_relative_artifact_path(relative_path)


def test_resolver_path_traversal_fails_closed(tmp_path: Path) -> None:
    resolver = build_immutable_resolver(
        revision=PINNED_REVISION,
        transport=MappingTransport({CORPUS_PATH: b"PAR1-corpus"}),
        cache_dir=tmp_path / "cache",
        require_descriptor=False,
    )
    with pytest.raises(UnsafePathError):
        resolver.resolve("../secrets/token")


# ---------------------------------------------------------------------------
# Symlink
# ---------------------------------------------------------------------------


def test_mapping_transport_symlink_fails_closed(tmp_path: Path) -> None:
    resolver = build_immutable_resolver(
        revision=PINNED_REVISION,
        transport=MappingTransport(
            {CORPUS_PATH: b"PAR1-honest"},
            fail_paths={CORPUS_PATH: "symlink"},
        ),
        cache_dir=tmp_path / "cache",
        require_descriptor=False,
    )
    with pytest.raises(SymlinkRejectedError):
        resolver.resolve(CORPUS_PATH)


def test_local_symlink_file_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "release"
    root.mkdir()
    target = root / "honest.bin"
    target.write_bytes(b"PAR1-honest")
    link = root / "linked.bin"
    link.symlink_to(target)
    with pytest.raises(SymlinkRejectedError):
        file_sha256_and_size(link)
    transport = LocalRootTransport(root)
    with pytest.raises(SymlinkRejectedError):
        transport.fetch(
            repo_id="justicedao/ipfs_state_laws",
            revision=PINNED_REVISION,
            relative_path="linked.bin",
            destination=tmp_path / "dest.bin",
        )


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------


def test_digest_drift_fails_closed(tmp_path: Path) -> None:
    honest = b"PAR1-honest-state-laws"
    forged = b"PAR1-forged-state-laws"
    descriptor = build_descriptor_for_bytes(
        CORPUS_PATH, honest, row_count=1, media_type=PARQUET_MEDIA
    )
    resolver = build_immutable_resolver(
        revision=PINNED_REVISION,
        transport=MappingTransport({CORPUS_PATH: forged}),
        cache_dir=tmp_path / "cache",
        require_descriptor=True,
    )
    with pytest.raises(DigestDriftError):
        resolver.resolve(CORPUS_PATH, descriptor=descriptor)
    with pytest.raises((DescriptorDriftError, DigestDriftError)):
        assert_no_descriptor_drift(descriptor, payload_bytes=forged)


# ---------------------------------------------------------------------------
# Decompression
# ---------------------------------------------------------------------------


def test_gzip_decompression_bomb_fails_closed(checker: ModuleType) -> None:
    bomb = checker.gzip_bomb_bytes()
    assert len(bomb) < checker.DECOMPRESSION_BOMB_INPUT_BYTES
    with pytest.raises(checker.DecompressionBombError):
        checker.bounded_decompress(bomb, max_out=checker.DECOMPRESSION_BOMB_BUDGET)
    honest = gzip.compress(b"state-laws-fixture", compresslevel=9)
    assert checker.bounded_decompress(honest, max_out=4096) == b"state-laws-fixture"


def test_trailing_hostile_gzip_bytes_fail_closed(checker: ModuleType) -> None:
    honest = gzip.compress(b"state-laws", compresslevel=9)
    with pytest.raises(checker.DecompressionBombError):
        checker.bounded_decompress(honest + b"\x00TRAILER", max_out=4096)


# ---------------------------------------------------------------------------
# Row
# ---------------------------------------------------------------------------


def test_physical_row_bound_is_4096() -> None:
    assert MAX_ROWS_PER_PHYSICAL_SHARD == 4096
    assert validate_physical_row_count(4096) == 4096
    with pytest.raises((StatePhysicalBoundError, PhysicalBoundError)):
        validate_physical_row_count(4097)


def test_parquet_row_limit_fails_closed(tmp_path: Path, checker: ModuleType) -> None:
    pytest.importorskip("pyarrow")
    path = tmp_path / "too-many.parquet"
    rows = [{"entry_cid": f"row-{index:04d}"} for index in range(5)]
    write_zstd_parquet(path, rows, max_rows=8)
    with pytest.raises((PhysicalBoundError, ArtifactIntegrityError, checker.HostileParquetError)):
        checker.admit_parquet_file(path, max_rows=2)
    with pytest.raises((PhysicalBoundError, ArtifactIntegrityError)):
        validate_zstd_parquet(path, max_rows=2)


def test_resolver_row_bound_fails_closed(tmp_path: Path) -> None:
    payload = b"PAR1-rows"
    descriptor = build_descriptor_for_bytes(
        CORPUS_PATH, payload, row_count=8, media_type=PARQUET_MEDIA
    )
    resolver = build_immutable_resolver(
        revision=PINNED_REVISION,
        transport=MappingTransport({CORPUS_PATH: payload}),
        cache_dir=tmp_path / "cache",
        require_descriptor=True,
    )
    object.__setattr__(resolver, "max_rows_per_artifact", 1)
    with pytest.raises(OversizedArtifactError):
        resolver.resolve(CORPUS_PATH, descriptor=descriptor)


# ---------------------------------------------------------------------------
# Resource
# ---------------------------------------------------------------------------


def test_memory_budget_fails_closed() -> None:
    budget = MemoryBudget(max_resident_records=2, max_resident_bytes=32)
    budget.acquire(2, 8)
    with pytest.raises(MemoryBudgetError):
        budget.acquire(1, 1)
    tight = MemoryBudget(max_resident_records=8, max_resident_bytes=16)
    with pytest.raises(MemoryBudgetError):
        tight.acquire(1, 64)


def test_oversized_artifact_fails_closed_before_trust(tmp_path: Path) -> None:
    payload = b"x" * 64
    descriptor = build_descriptor_for_bytes(
        CORPUS_PATH, payload, row_count=1, media_type=PARQUET_MEDIA
    )
    resolver = build_immutable_resolver(
        revision=PINNED_REVISION,
        transport=MappingTransport({CORPUS_PATH: payload}),
        cache_dir=tmp_path / "cache",
        require_descriptor=True,
    )
    object.__setattr__(resolver, "max_artifact_bytes", 8)
    with pytest.raises(OversizedArtifactError):
        resolver.resolve(CORPUS_PATH, descriptor=descriptor)


def test_uscode_resource_limits_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ResourceLimitError):
        run_uscode_fixture_build(
            tmp_path / "out",
            titles=("1", "35"),
            families=("corpus",),
            resource_limits=ResourceLimits(max_titles=1, resource_class="memory-large"),
        )


# ---------------------------------------------------------------------------
# Mutable pin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pin", ["main", "latest", "HEAD", "master"])
def test_mutable_pins_fail_closed(pin: str, tmp_path: Path) -> None:
    with pytest.raises((ImmutablePinError, MutableRevisionError)):
        require_immutable_revision(pin)
    with pytest.raises((AdapterPinError, ImmutablePinError, MutableRevisionError)):
        build_immutable_resolver(
            revision=pin,
            transport=MappingTransport({}),
            cache_dir=tmp_path / "cache",
        )


# ---------------------------------------------------------------------------
# Secret
# ---------------------------------------------------------------------------


def test_secret_and_home_path_payloads_fail_closed() -> None:
    with pytest.raises(Exception):
        assert_no_secrets({"token": "hf_notarealtokenvalue0123456789"})
    with pytest.raises(Exception):
        assert_no_secrets({"path": "/home/operator/secret.json"})
    with pytest.raises(Exception):
        assert_no_home_paths_or_tokens(
            {"Authorization": "Bearer sk-live-not-a-real-secret"}
        )


# ---------------------------------------------------------------------------
# Partial checkpoint
# ---------------------------------------------------------------------------


def test_partial_uscode_checkpoint_cannot_seal(tmp_path: Path) -> None:
    result = run_uscode_fixture_build(
        tmp_path / "out",
        titles=("1", "35"),
        families=("corpus",),
        interrupt_after_units=1,
    )
    assert result.interrupted is True
    assert result.seal is None
    with pytest.raises(SealError):
        compute_seal(result.checkpoint)


def test_federal_register_partial_checkpoint_cannot_promote(
    tmp_path: Path, checker: ModuleType
) -> None:
    from ipfs_datasets_py.processors.legal_data.federal_register_release import (
        run_fixture_build as run_federal,
    )

    result = run_federal(
        tmp_path / "out",
        partitions=("2026-03", "2026-08"),
        families=("corpus",),
        interrupt_after_units=1,
    )
    assert result.interrupted is True
    assert result.seal is None
    with pytest.raises(PromotionError):
        assert_promotable(result.checkpoint)


def test_streaming_partial_checkpoint_cannot_promote() -> None:
    with pytest.raises(PartialCheckpointPromotionError):
        StreamingCheckpoint(
            config_digest="a" * 64,
            build_id="partial-fixture",
            units={
                "OR/corpus": JurisdictionUnitRecord(
                    jurisdiction="OR",
                    family="corpus",
                    status=WorkUnitStatus.PENDING,
                    input_hash="b" * 64,
                )
            },
            sealed=True,
        )


# ---------------------------------------------------------------------------
# Hostile parquet / honest admission
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["truncated_magic", "hostile_footer", "too_many_rows"])
def test_hostile_parquet_fails_closed(
    kind: str, tmp_path: Path, checker: ModuleType
) -> None:
    if kind == "too_many_rows":
        pytest.importorskip("pyarrow")
    target = tmp_path / f"{kind}.parquet"
    checker.write_hostile_parquet(target, kind=kind, max_rows=2)
    with pytest.raises(
        (checker.HostileParquetError, ArtifactIntegrityError, PhysicalBoundError)
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
# Sealed report + checker recipes
# ---------------------------------------------------------------------------


def test_fail_closed_recipe_suite_covers_every_category(
    tmp_path: Path, checker: ModuleType
) -> None:
    pytest.importorskip("pyarrow")
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
    assert payload["task_id"] == "LCR-037"
    assert payload["goal_id"] == "LCR-G060"
    assert payload["program_id"] == "legal-corpora-reindex-v1"
    assert payload["authorizing_for_publication"] is False
    assert payload["authorizing_for_release"] is False
    assert payload["authorizing_hub_upload"] is False
    assert payload["hub_upload"] is False
    assert payload["secrets_absent"] is True
    assert payload["fixture_only"] is True
    assert payload["proves_software_contract_only"] is True
    assert payload["resource_class"] == "memory-large"
    assert set(payload["fail_closed"]["categories"]) == REQUIRED_CATEGORIES
    rendered = json.dumps(payload, sort_keys=True)
    assert "hf_" not in rendered
    assert "/home/" not in rendered
    assert "file://" not in rendered
    assert "Bearer " not in rendered
    assert "HF_TOKEN" not in rendered
    assert payload["report_digest_sha256"] == checker.report_digest(payload)
