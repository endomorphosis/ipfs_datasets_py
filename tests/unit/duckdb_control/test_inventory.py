"""Unit tests for DQK-001 bounded streaming inventory scanner."""

from __future__ import annotations

import hashlib
import tracemalloc
from pathlib import Path

import pytest

from ipfs_datasets_py.duckdb_control.inventory import (
    DEFAULT_CHUNK_SIZE,
    REQUIRED_RECORD_FIELDS,
    SCHEMA_VERSION,
    ClassificationRule,
    InventoryKind,
    InventoryRecord,
    InventoryRegistry,
    classify_path,
    digest_file,
    format_digest,
    inventory_snapshot,
    normalize_relative_path,
    scan_inventory,
)

# Production-hardening corpus size referenced by the control-plane plan.
PRODUCTION_HARDENING_BYTES = 970 * 1024 * 1024


def _write(path: Path, content: bytes | str = b"") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)
    return path


def _fixture_tree(root: Path) -> dict[str, Path]:
    """Create a small multi-kind tree under datasets + supervisor paths."""

    files = {
        "doc": _write(
            root / "docs" / "architecture" / "control_plane.md",
            "# plan\n",
        ),
        "state": _write(
            root / "data" / "agent_supervisor" / "control.duckdb",
            b"duckdb-stub",
        ),
        "state_json": _write(
            root / "data" / "agent_supervisor" / "state" / "leases.json",
            '{"lease":1}\n',
        ),
        "evidence": _write(
            root / "data" / "agent_supervisor" / "evidence" / "import.receipt.json",
            '{"cid":"bafy"}\n',
        ),
        "evidence_car": _write(
            root / "data" / "datasets" / "corpus" / "shard.car",
            b"car-bytes",
        ),
        "export": _write(
            root / "workspace" / "exports" / "goals.export.json",
            '{"goals":[]}\n',
        ),
        "unsafe": _write(
            root / "data" / "datasets" / "vectors" / "index.pkl",
            b"pickle-stub",
        ),
        "parquet": _write(
            root / "data" / "datasets" / "corpus" / "nodes.parquet",
            b"PAR1",
        ),
    }
    # Skipped directory content must not appear in the inventory.
    _write(root / ".git" / "objects" / "pack" / "secret", b"nope")
    _write(root / "data" / "__pycache__" / "mod.cpython-312.pyc", b"bytecode")
    return files


def test_schema_and_kind_surface() -> None:
    assert SCHEMA_VERSION == "DuckDBControlInventory@1"
    assert InventoryKind.values() == frozenset(
        {
            "authored_documentation",
            "mutable_state",
            "immutable_evidence",
            "derived_export",
            "unsafe_serialization",
        }
    )
    assert REQUIRED_RECORD_FIELDS == frozenset(
        {
            "path",
            "kind",
            "size",
            "digest",
            "producer",
            "consumer",
            "proposed_authority",
        }
    )


def test_classify_path_distinguishes_five_kinds() -> None:
    cases = {
        "docs/architecture/plan.md": InventoryKind.AUTHORED_DOCUMENTATION,
        "README.md": InventoryKind.AUTHORED_DOCUMENTATION,
        "data/agent_supervisor/control.duckdb": InventoryKind.MUTABLE_STATE,
        "data/agent_supervisor/state/leases.json": InventoryKind.MUTABLE_STATE,
        "state/runtime/heartbeats.json": InventoryKind.MUTABLE_STATE,
        "data/agent_supervisor/evidence/import.receipt.json": (
            InventoryKind.IMMUTABLE_EVIDENCE
        ),
        "data/datasets/corpus/shard.car": InventoryKind.IMMUTABLE_EVIDENCE,
        "data/datasets/corpus/nodes.parquet": InventoryKind.IMMUTABLE_EVIDENCE,
        "workspace/exports/goals.export.json": InventoryKind.DERIVED_EXPORT,
        "archive/results/report.json": InventoryKind.DERIVED_EXPORT,
        "data/datasets/vectors/index.pkl": InventoryKind.UNSAFE_SERIALIZATION,
        "data/datasets/vectors/model.joblib": InventoryKind.UNSAFE_SERIALIZATION,
        "workspace/cache/faiss_index.bin": InventoryKind.UNSAFE_SERIALIZATION,
    }
    for path, expected in cases.items():
        kind, producer, consumer, authority = classify_path(path)
        assert kind is expected, path
        assert producer
        assert consumer
        assert authority
        assert authority in {
            "git_authored",
            "control",
            "content_addressed_store",
            "export_only",
            "quarantine",
        }


def test_inventory_record_requires_complete_fields() -> None:
    digest = format_digest(hashlib.sha256(b"x").hexdigest())
    record = InventoryRecord(
        path="docs/a.md",
        kind=InventoryKind.AUTHORED_DOCUMENTATION.value,
        size=1,
        digest=digest,
        producer="human_author",
        consumer="documentation_consumers",
        proposed_authority="git_authored",
    )
    payload = record.as_dict()
    assert set(payload) == REQUIRED_RECORD_FIELDS
    assert InventoryRecord.from_mapping(payload) == record

    with pytest.raises(ValueError):
        InventoryRecord.from_mapping({"path": "x"})
    with pytest.raises(ValueError):
        InventoryRecord(
            path="/absolute",
            kind=InventoryKind.MUTABLE_STATE.value,
            size=0,
            digest=digest,
            producer="p",
            consumer="c",
            proposed_authority="control",
        )


def test_digest_file_is_chunked_and_matches_sha256(tmp_path: Path) -> None:
    path = _write(tmp_path / "blob.bin", b"abcdefghijklmnopqrstuvwxyz" * 1000)
    chunk_sizes: list[int] = []

    def on_chunk(chunk: bytes) -> None:
        chunk_sizes.append(len(chunk))

    size, digest = digest_file(path, chunk_size=64, on_chunk=on_chunk)
    expected = format_digest(hashlib.sha256(path.read_bytes()).hexdigest())
    assert size == path.stat().st_size
    assert digest == expected
    assert chunk_sizes
    assert max(chunk_sizes) <= 64
    assert sum(chunk_sizes) == size


def test_scan_is_streaming_and_deterministic(tmp_path: Path) -> None:
    _fixture_tree(tmp_path)

    first = list(scan_inventory(tmp_path, relative_to=tmp_path))
    second = list(scan_inventory(tmp_path, relative_to=tmp_path))

    assert first == second
    paths = [record.path for record in first]
    assert paths == sorted(paths, key=lambda value: value.encode("utf-8"))
    assert len(paths) == len(set(paths))

    # Skipped trees must not appear.
    assert all(not path.startswith(".git/") for path in paths)
    assert all("__pycache__" not in path for path in paths)

    # Streaming: the iterator yields before materializing a second full pass.
    iterator = scan_inventory(tmp_path, relative_to=tmp_path)
    first_item = next(iterator)
    assert isinstance(first_item, InventoryRecord)
    # Remaining items still stream without requiring list() first.
    rest = list(iterator)
    assert [first_item, *rest] == first


def test_every_record_includes_required_control_plane_fields(tmp_path: Path) -> None:
    _fixture_tree(tmp_path)
    records = list(scan_inventory(tmp_path, relative_to=tmp_path))
    assert records

    kinds_seen: set[str] = set()
    for record in records:
        payload = record.as_dict()
        assert set(payload) >= REQUIRED_RECORD_FIELDS
        for field in REQUIRED_RECORD_FIELDS:
            assert payload[field] not in (None, ""), field
        assert record.kind in InventoryKind.values()
        assert record.size >= 0
        assert record.digest.startswith("sha256:")
        kinds_seen.add(record.kind)

    # Fixture tree intentionally covers every classification kind.
    assert kinds_seen == InventoryKind.values()


def test_fixture_tree_classification_mapping(tmp_path: Path) -> None:
    files = _fixture_tree(tmp_path)
    by_path = {
        record.path: record
        for record in scan_inventory(tmp_path, relative_to=tmp_path)
    }

    assert by_path["docs/architecture/control_plane.md"].kind == (
        InventoryKind.AUTHORED_DOCUMENTATION.value
    )
    assert by_path["data/agent_supervisor/control.duckdb"].kind == (
        InventoryKind.MUTABLE_STATE.value
    )
    assert by_path["data/agent_supervisor/state/leases.json"].kind == (
        InventoryKind.MUTABLE_STATE.value
    )
    assert by_path["data/agent_supervisor/evidence/import.receipt.json"].kind == (
        InventoryKind.IMMUTABLE_EVIDENCE.value
    )
    assert by_path["data/datasets/corpus/shard.car"].kind == (
        InventoryKind.IMMUTABLE_EVIDENCE.value
    )
    assert by_path["data/datasets/corpus/nodes.parquet"].kind == (
        InventoryKind.IMMUTABLE_EVIDENCE.value
    )
    assert by_path["workspace/exports/goals.export.json"].kind == (
        InventoryKind.DERIVED_EXPORT.value
    )
    assert by_path["data/datasets/vectors/index.pkl"].kind == (
        InventoryKind.UNSAFE_SERIALIZATION.value
    )
    assert by_path["data/datasets/vectors/index.pkl"].proposed_authority == "quarantine"
    assert by_path["data/agent_supervisor/control.duckdb"].proposed_authority == "control"
    assert (
        by_path["workspace/exports/goals.export.json"].proposed_authority == "export_only"
    )

    # Digests match real file bytes for every fixture artifact.
    for key, path in files.items():
        rel = path.relative_to(tmp_path).as_posix()
        expected = format_digest(hashlib.sha256(path.read_bytes()).hexdigest())
        assert by_path[rel].digest == expected, key
        assert by_path[rel].size == path.stat().st_size


def test_registry_custom_rules_override_defaults(tmp_path: Path) -> None:
    _write(tmp_path / "special" / "override.json", '{"x":1}')
    registry = InventoryRegistry()
    registry.register_rule(
        ClassificationRule(
            rule_id="special-override",
            kind=InventoryKind.IMMUTABLE_EVIDENCE,
            producer="custom_producer",
            consumer="custom_consumer",
            proposed_authority="content_addressed_store",
            priority=100,
            path_prefix="special/",
        )
    )
    records = registry.collect(tmp_path, relative_to=tmp_path)
    assert len(records) == 1
    assert records[0].kind == InventoryKind.IMMUTABLE_EVIDENCE.value
    assert records[0].producer == "custom_producer"
    assert records[0].consumer == "custom_consumer"

    with pytest.raises(ValueError, match="duplicate"):
        registry.register_rule(
            ClassificationRule(
                rule_id="special-override",
                kind=InventoryKind.MUTABLE_STATE,
                producer="x",
                consumer="y",
                proposed_authority="control",
                path_prefix="other/",
            )
        )


def test_inventory_snapshot_summary(tmp_path: Path) -> None:
    _fixture_tree(tmp_path)
    payload = inventory_snapshot(tmp_path, relative_to=tmp_path)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["record_count"] == len(payload["records"])
    assert payload["total_bytes"] == sum(item["size"] for item in payload["records"])
    assert sum(payload["kind_counts"].values()) == payload["record_count"]


def test_normalize_relative_path_rejects_unsafe_values() -> None:
    assert normalize_relative_path("docs/a.md") == "docs/a.md"
    with pytest.raises(ValueError):
        normalize_relative_path("/abs/path")
    with pytest.raises(ValueError):
        normalize_relative_path("../escape")
    with pytest.raises(ValueError):
        normalize_relative_path("")


def test_production_hardening_corpus_inventoried_without_loading_into_memory(
    tmp_path: Path,
) -> None:
    """Accept that a 970 MB corpus is hashed via bounded chunks only.

    Creates a sparse 970 MiB file (no full physical allocation required on
    Linux) and verifies:

    * inventory completes
    * every read chunk is <= DEFAULT_CHUNK_SIZE
    * peak traced Python memory stays far below the corpus size
    """

    corpus_dir = tmp_path / "data" / "datasets" / "production_hardening"
    corpus_dir.mkdir(parents=True)
    corpus = corpus_dir / "corpus.bin"

    # Sparse file: logical size 970 MiB, no need to write 970 MiB of data.
    with corpus.open("wb") as handle:
        handle.truncate(PRODUCTION_HARDENING_BYTES)
    assert corpus.stat().st_size == PRODUCTION_HARDENING_BYTES

    chunk_sizes: list[int] = []

    def on_chunk(chunk: bytes) -> None:
        chunk_sizes.append(len(chunk))
        # Hard fail if a single chunk could hold the corpus.
        assert len(chunk) <= DEFAULT_CHUNK_SIZE

    tracemalloc.start()
    try:
        baseline = tracemalloc.get_traced_memory()[1]
        records = list(
            scan_inventory(
                tmp_path,
                relative_to=tmp_path,
                chunk_size=DEFAULT_CHUNK_SIZE,
                on_chunk=on_chunk,
            )
        )
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    assert len(records) == 1
    record = records[0]
    assert record.path == "data/datasets/production_hardening/corpus.bin"
    assert record.size == PRODUCTION_HARDENING_BYTES
    assert record.digest.startswith("sha256:")
    assert len(record.digest) == len("sha256:") + 64
    assert all(field in record.as_dict() for field in REQUIRED_RECORD_FIELDS)

    assert chunk_sizes
    assert max(chunk_sizes) <= DEFAULT_CHUNK_SIZE
    assert sum(chunk_sizes) == PRODUCTION_HARDENING_BYTES

    # Peak traced allocations during the scan stay well under the corpus size.
    # Allow a generous headroom for interpreter overhead while remaining two
    # orders of magnitude below loading the full 970 MB body.
    peak_delta = max(0, peak - baseline)
    assert peak_delta < 64 * 1024 * 1024, (
        f"peak memory delta {peak_delta} exceeded 64 MiB bound"
    )


def test_missing_root_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    with pytest.raises(FileNotFoundError):
        list(scan_inventory(missing))


def test_scan_multiple_roots_is_deterministic(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    _write(a / "docs" / "a.md", "A")
    _write(b / "docs" / "b.md", "B")

    first = list(scan_inventory([b, a], relative_to=tmp_path))
    second = list(scan_inventory([a, b], relative_to=tmp_path))
    assert first == second
    assert [record.path for record in first] == ["a/docs/a.md", "b/docs/b.md"]


def test_producer_consumer_prefix_rules() -> None:
    kind, producer, consumer, authority = classify_path(
        "data/agent_supervisor/state/queue.json"
    )
    assert kind is InventoryKind.MUTABLE_STATE
    assert producer == "agent_supervisor"
    assert consumer == "duckdb_control_importer"
    assert authority == "control"

    kind, producer, consumer, authority = classify_path("docs/README.md")
    assert kind is InventoryKind.AUTHORED_DOCUMENTATION
    assert producer == "human_author"
    assert authority == "git_authored"
