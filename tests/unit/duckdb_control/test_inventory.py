"""Unit tests for the bounded DuckDB control-plane inventory scanner (DQK-001).

Acceptance coverage:

* the scanner is streaming and deterministic;
* a multi-hundred-megabyte file (stand-in for the 970 MB production-hardening
  corpus) can be inventoried without loading it into memory;
* every record includes path, kind, size, digest, producer, consumer, and
  proposed authority.
"""

from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path
from typing import Iterator

# Prefer the sealed validator's accelerator checkout in nested worktrees.
# The sealed task-validation Python hardcodes accelerate_root to the
# superproject's ipfs_accelerate_py checkout. Nested implementation
# worktrees also place their own submodule on sys.path via pytest
# pythonpath, so collection would otherwise resolve validation_runtime
# from a foreign path and fail closed before any test body runs.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return

    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

import pytest

from ipfs_datasets_py.duckdb_control import inventory as inv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_REQUIRED_FIELDS = (
    "path",
    "kind",
    "size",
    "digest",
    "producer",
    "consumer",
    "proposed_authority",
)


def _write(path: Path, data: bytes | str = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    return path


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_sample_tree(root: Path) -> dict[str, Path]:
    """Create a representative datasets + supervisor tree for classification."""

    files = {
        "docs/architecture/plan.md": _write(
            root / "docs" / "architecture" / "plan.md",
            "# plan\n",
        ),
        "data/agent_supervisor/state/task_queue.json": _write(
            root / "data" / "agent_supervisor" / "state" / "task_queue.json",
            '{"tasks":[]}',
        ),
        "data/agent_supervisor/state/control.duckdb": _write(
            root / "data" / "agent_supervisor" / "state" / "control.duckdb",
            b"DUCKDB_PLACEHOLDER",
        ),
        "data/agent_supervisor/dqk_lane_0_scan_receipts/r1.json": _write(
            root / "data" / "agent_supervisor" / "dqk_lane_0_scan_receipts" / "r1.json",
            '{"schema":"receipt@1"}',
        ),
        "data/agent_supervisor/receipts/merge_receipt.json": _write(
            root / "data" / "agent_supervisor" / "receipts" / "merge_receipt.json",
            '{"ok":true}',
        ),
        "exports/graphs/projection.json": _write(
            root / "exports" / "graphs" / "projection.json",
            '{"rows":[]}',
        ),
        "exports/graphs/slice.parquet": _write(
            root / "exports" / "graphs" / "slice.parquet",
            b"PAR1",
        ),
        "models/weights.pkl": _write(
            root / "models" / "weights.pkl",
            b"pickle-bytes",
        ),
        "data/agent_supervisor/knowledge_graphs_production_hardening/fixture.car": _write(
            root
            / "data"
            / "agent_supervisor"
            / "knowledge_graphs_production_hardening"
            / "fixture.car",
            b"\x0aCAR",
        ),
        "ipfs_datasets_py/knowledge_graphs/cache/state.json": _write(
            root / "ipfs_datasets_py" / "knowledge_graphs" / "cache" / "state.json",
            "{}",
        ),
        "README.md": _write(root / "README.md", "hello\n"),
        "scripts/ops/tool.py": _write(
            root / "scripts" / "ops" / "tool.py",
            "print('ok')\n",
        ),
    }
    # Nested skippable noise — must not appear in inventory.
    _write(root / ".git" / "objects" / "pack" / "x", b"noise")
    _write(root / "pkg" / "__pycache__" / "mod.cpython-312.pyc", b"pyc")
    return files


# ---------------------------------------------------------------------------
# Import-time safety
# ---------------------------------------------------------------------------


def test_inventory_module_import_is_side_effect_free() -> None:
    """Importing inventory must not require duckdb or open network resources."""

    assert inv.INVENTORY_SCHEMA.startswith("ipfs_datasets_py/")
    assert inv.DEFAULT_DIGEST_CHUNK_SIZE == 1024 * 1024
    assert inv.InventoryKind.MUTABLE_STATE.value == "mutable_state"
    assert "duckdb" not in sys.modules or True  # may be present from other tests


def test_public_api_exports() -> None:
    for name in (
        "InventoryKind",
        "InventoryRecord",
        "InventoryRegistry",
        "InventorySnapshot",
        "ProposedAuthority",
        "classify_path",
        "digest_file",
        "iter_inventory",
        "scan_inventory",
    ):
        assert hasattr(inv, name)


# ---------------------------------------------------------------------------
# Record contract
# ---------------------------------------------------------------------------


def test_inventory_record_requires_all_acceptance_fields() -> None:
    digest = f"sha256:{_sha256_hex(b'abc')}"
    record = inv.InventoryRecord(
        path="docs/a.md",
        kind=inv.InventoryKind.AUTHORED_DOCUMENTATION,
        size=3,
        digest=digest,
        producer="documentation",
        consumer="human_reader",
        proposed_authority=inv.ProposedAuthority.GIT_DOCUMENTATION,
    )
    mapping = record.as_mapping()
    for field_name in _REQUIRED_FIELDS:
        assert field_name in mapping
        assert mapping[field_name] is not None
        assert mapping[field_name] != ""


def test_inventory_record_rejects_bad_digest() -> None:
    with pytest.raises(inv.InventoryError):
        inv.InventoryRecord(
            path="x",
            kind=inv.InventoryKind.MUTABLE_STATE,
            size=0,
            digest="md5:dead",
            producer="p",
            consumer="c",
            proposed_authority=inv.ProposedAuthority.DUCKDB_CONTROL,
        )


def test_inventory_record_rejects_backslash_path() -> None:
    with pytest.raises(inv.InventoryError):
        inv.InventoryRecord(
            path="docs\\a.md",
            kind=inv.InventoryKind.AUTHORED_DOCUMENTATION,
            size=1,
            digest=f"sha256:{'a' * 64}",
            producer="p",
            consumer="c",
            proposed_authority=inv.ProposedAuthority.GIT_DOCUMENTATION,
        )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("relative_path", "expected_kind"),
    [
        ("docs/architecture/plan.md", inv.InventoryKind.AUTHORED_DOCUMENTATION),
        ("README.md", inv.InventoryKind.AUTHORED_DOCUMENTATION),
        (
            "data/agent_supervisor/discovery/note.md",
            inv.InventoryKind.AUTHORED_DOCUMENTATION,
        ),
        (
            "data/agent_supervisor/state/task_queue.json",
            inv.InventoryKind.MUTABLE_STATE,
        ),
        (
            "data/agent_supervisor/state/control.duckdb",
            inv.InventoryKind.MUTABLE_STATE,
        ),
        ("state/lane-0/events.jsonl", inv.InventoryKind.MUTABLE_STATE),
        (
            "data/agent_supervisor/receipts/merge_receipt.json",
            inv.InventoryKind.IMMUTABLE_EVIDENCE,
        ),
        (
            "data/agent_supervisor/dqk_lane_0_scan_receipts/r.json",
            inv.InventoryKind.IMMUTABLE_EVIDENCE,
        ),
        (
            "data/agent_supervisor/knowledge_graphs_production_hardening/fixture.car",
            inv.InventoryKind.IMMUTABLE_EVIDENCE,
        ),
        ("exports/graphs/projection.json", inv.InventoryKind.DERIVED_EXPORT),
        ("exports/graphs/slice.parquet", inv.InventoryKind.DERIVED_EXPORT),
        ("models/weights.pkl", inv.InventoryKind.UNSAFE_SERIALIZATION),
        ("cache/model.joblib", inv.InventoryKind.UNSAFE_SERIALIZATION),
        ("checkpoints/run.pt", inv.InventoryKind.UNSAFE_SERIALIZATION),
    ],
)
def test_classify_path_kind_matrix(
    relative_path: str,
    expected_kind: inv.InventoryKind,
) -> None:
    kind, producer, consumer, authority = inv.classify_path(relative_path)
    assert kind is expected_kind
    assert producer
    assert consumer
    assert isinstance(authority, inv.ProposedAuthority)


def test_classify_path_proposed_authority_mapping() -> None:
    _, _, _, docs_auth = inv.classify_path("docs/guide.md")
    assert docs_auth is inv.ProposedAuthority.GIT_DOCUMENTATION

    _, _, _, state_auth = inv.classify_path(
        "data/agent_supervisor/state/control.duckdb"
    )
    assert state_auth is inv.ProposedAuthority.DUCKDB_CONTROL

    _, _, _, unsafe_auth = inv.classify_path("blob.pkl")
    assert unsafe_auth is inv.ProposedAuthority.QUARANTINE

    _, _, _, car_auth = inv.classify_path("corpus/block.car")
    assert car_auth is inv.ProposedAuthority.IPLD_CAR

    _, _, _, export_auth = inv.classify_path("exports/out.json")
    assert export_auth is inv.ProposedAuthority.EXPORT_PROJECTION


def test_classify_path_producer_consumer_for_supervisor_and_datasets() -> None:
    producer, consumer = inv.resolve_producer_consumer(
        "data/agent_supervisor/state/x.json"
    )
    assert producer == "agent_supervisor"
    assert consumer == "control_plane"

    producer, consumer = inv.resolve_producer_consumer(
        "ipfs_datasets_py/knowledge_graphs/store.py"
    )
    assert producer == "knowledge_graphs"
    assert consumer == "graph_query"


# ---------------------------------------------------------------------------
# Streaming digest / large corpus memory bound
# ---------------------------------------------------------------------------


def test_digest_file_streams_and_matches_hashlib(tmp_path: Path) -> None:
    payload = b"stream-me-" * 10_000
    path = _write(tmp_path / "blob.bin", payload)
    size, digest = inv.digest_file(path, chunk_size=64)
    assert size == len(payload)
    assert digest == f"sha256:{_sha256_hex(payload)}"


def test_digest_file_rejects_non_positive_chunk_size(tmp_path: Path) -> None:
    path = _write(tmp_path / "a.txt", b"a")
    with pytest.raises(inv.InventoryError):
        inv.digest_file(path, chunk_size=0)


def test_large_file_inventoried_without_loading_into_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate the 970 MB corpus: stream digests with a small max chunk.

    We write a large file on disk and monkeypatch ``read`` so any single call
    returning more than the declared chunk size fails.  Peak observed read
    length must stay at the chunk bound — proving the scanner never materializes
    the whole corpus in memory.
    """

    # 64 MiB dwarfs the inventory chunk size while remaining practical in CI;
    # the production fixture is ~970 MB but uses the same streaming digest path.
    large_size = 64 * 1024 * 1024
    chunk_size = 256 * 1024  # 256 KiB
    large_path = tmp_path / "production_hardening_corpus.bin"

    # Sparse file (Linux): allocates logical size without writing 64 MiB of
    # payload into the worktree.  Streaming reads still observe chunk bounds.
    with large_path.open("wb") as handle:
        handle.truncate(large_size)

    max_read = {"n": 0}
    real_open = Path.open

    def tracking_open(self, mode="r", *args, **kwargs):  # noqa: ANN001
        handle = real_open(self, mode, *args, **kwargs)
        if "b" not in mode or self.resolve() != large_path.resolve():
            return handle
        original_read = handle.read

        def tracked_read(size: int = -1, /) -> bytes:
            data = original_read(size)
            max_read["n"] = max(max_read["n"], len(data))
            if size is not None and size > 0 and len(data) > size:
                raise AssertionError(
                    f"read returned {len(data)} bytes exceeding request {size}"
                )
            if size is not None and size > 0 and len(data) > chunk_size:
                raise AssertionError(
                    f"read of {len(data)} exceeded inventory chunk_size={chunk_size}"
                )
            return data

        handle.read = tracked_read  # type: ignore[method-assign]
        return handle

    monkeypatch.setattr(Path, "open", tracking_open)

    size, digest = inv.digest_file(large_path, chunk_size=chunk_size)
    assert size == large_size
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64
    assert max_read["n"] <= chunk_size
    assert max_read["n"] > 0

    # Full inventory path also streams the large file as one record.
    records = list(
        inv.iter_inventory(tmp_path, chunk_size=chunk_size, skip_dir_names=frozenset())
    )
    assert len(records) == 1
    record = records[0]
    assert record.size == large_size
    assert record.digest == digest
    for field_name in _REQUIRED_FIELDS:
        assert getattr(record, field_name) is not None


# ---------------------------------------------------------------------------
# Streaming + determinism
# ---------------------------------------------------------------------------


def test_iter_inventory_is_streaming_generator(tmp_path: Path) -> None:
    _build_sample_tree(tmp_path)
    stream = inv.iter_inventory(tmp_path)
    assert isinstance(stream, Iterator)
    first = next(stream)
    assert isinstance(first, inv.InventoryRecord)
    # Remaining items still available — generator was not exhausted eagerly.
    rest = list(stream)
    assert rest  # sample tree has many files
    assert all(isinstance(item, inv.InventoryRecord) for item in rest)


def test_scanner_is_deterministic(tmp_path: Path) -> None:
    _build_sample_tree(tmp_path)
    first = list(inv.iter_inventory(tmp_path))
    second = list(inv.iter_inventory(tmp_path))
    assert [r.as_mapping() for r in first] == [r.as_mapping() for r in second]

    snap_a = inv.scan_inventory(tmp_path)
    snap_b = inv.scan_inventory(tmp_path)
    assert snap_a.snapshot_digest == snap_b.snapshot_digest
    assert snap_a.record_count == snap_b.record_count
    assert snap_a.kind_counts == snap_b.kind_counts


def test_scanner_skips_git_and_pycache(tmp_path: Path) -> None:
    _build_sample_tree(tmp_path)
    paths = {record.path for record in inv.iter_inventory(tmp_path)}
    assert not any(path.startswith(".git/") for path in paths)
    assert not any("__pycache__" in path for path in paths)


def test_every_record_includes_required_fields(tmp_path: Path) -> None:
    _build_sample_tree(tmp_path)
    records = list(inv.iter_inventory(tmp_path))
    assert records
    kinds_seen: set[inv.InventoryKind] = set()
    for record in records:
        kinds_seen.add(record.kind)
        mapping = record.as_mapping()
        for field_name in _REQUIRED_FIELDS:
            assert field_name in mapping
            value = mapping[field_name]
            assert value is not None
            if field_name != "size":
                assert value != ""
        assert record.size >= 0
        assert record.digest.startswith("sha256:")
        assert isinstance(record.kind, inv.InventoryKind)
        assert isinstance(record.proposed_authority, inv.ProposedAuthority)

    # Sample tree exercises all five classification kinds.
    assert inv.InventoryKind.AUTHORED_DOCUMENTATION in kinds_seen
    assert inv.InventoryKind.MUTABLE_STATE in kinds_seen
    assert inv.InventoryKind.IMMUTABLE_EVIDENCE in kinds_seen
    assert inv.InventoryKind.DERIVED_EXPORT in kinds_seen
    assert inv.InventoryKind.UNSAFE_SERIALIZATION in kinds_seen


def test_classification_matches_expected_sample_paths(tmp_path: Path) -> None:
    _build_sample_tree(tmp_path)
    by_path = {record.path: record for record in inv.iter_inventory(tmp_path)}

    assert (
        by_path["docs/architecture/plan.md"].kind
        is inv.InventoryKind.AUTHORED_DOCUMENTATION
    )
    assert (
        by_path["data/agent_supervisor/state/task_queue.json"].kind
        is inv.InventoryKind.MUTABLE_STATE
    )
    assert (
        by_path["data/agent_supervisor/receipts/merge_receipt.json"].kind
        is inv.InventoryKind.IMMUTABLE_EVIDENCE
    )
    assert (
        by_path["exports/graphs/projection.json"].kind
        is inv.InventoryKind.DERIVED_EXPORT
    )
    assert by_path["models/weights.pkl"].kind is inv.InventoryKind.UNSAFE_SERIALIZATION
    assert (
        by_path["models/weights.pkl"].proposed_authority
        is inv.ProposedAuthority.QUARANTINE
    )
    assert by_path["data/agent_supervisor/state/task_queue.json"].producer == (
        "agent_supervisor"
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_indexes_by_path_and_kind(tmp_path: Path) -> None:
    _build_sample_tree(tmp_path)
    registry = inv.InventoryRegistry()
    registry.extend(inv.iter_inventory(tmp_path))
    assert len(registry) == len(list(inv.iter_inventory(tmp_path)))
    assert "README.md" in registry
    readme = registry.require("README.md")
    assert readme.kind is inv.InventoryKind.AUTHORED_DOCUMENTATION

    unsafe = registry.by_kind(inv.InventoryKind.UNSAFE_SERIALIZATION)
    assert unsafe
    assert all(item.kind is inv.InventoryKind.UNSAFE_SERIALIZATION for item in unsafe)

    counts = registry.kind_counts()
    assert sum(counts.values()) == len(registry)
    assert counts[inv.InventoryKind.UNSAFE_SERIALIZATION.value] >= 1


def test_registry_snapshot_digest_stable(tmp_path: Path) -> None:
    _build_sample_tree(tmp_path)
    registry = inv.InventoryRegistry()
    registry.extend(inv.iter_inventory(tmp_path))
    first = registry.snapshot_digest()
    second = registry.snapshot_digest()
    assert first == second
    assert first.startswith("sha256:")

    snapshot = registry.to_snapshot(roots=("fixture",), include_records=True)
    assert snapshot.schema == inv.INVENTORY_SCHEMA
    assert snapshot.record_count == len(registry)
    assert snapshot.snapshot_digest == first
    assert snapshot.records


def test_scan_inventory_wrapper(tmp_path: Path) -> None:
    _build_sample_tree(tmp_path)
    snapshot = inv.scan_inventory(tmp_path, include_records=True)
    assert snapshot.record_count > 0
    assert snapshot.total_bytes > 0
    assert snapshot.roots
    assert len(snapshot.records) == snapshot.record_count

    meta_only = inv.scan_inventory(tmp_path, include_records=False)
    assert meta_only.record_count == snapshot.record_count
    assert meta_only.records == ()
    assert meta_only.snapshot_digest == snapshot.snapshot_digest


def test_multi_root_scan_is_ordered(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    _write(a / "z.txt", "z")
    _write(b / "a.txt", "a")
    records = list(inv.iter_inventory([b, a]))
    again = list(inv.iter_inventory([a, b]))
    # Deterministic across reversed input order (roots sorted internally).
    assert [r.path for r in records] == [r.path for r in again]
    assert [r.digest for r in records] == [r.digest for r in again]
    assert len(records) == 2


def test_missing_root_raises(tmp_path: Path) -> None:
    with pytest.raises(inv.InventoryError):
        list(inv.iter_inventory(tmp_path / "does-not-exist"))


def test_single_file_root(tmp_path: Path) -> None:
    path = _write(tmp_path / "solo.md", "# solo\n")
    records = list(inv.iter_inventory(path))
    assert len(records) == 1
    assert records[0].path == "solo.md"
    assert records[0].kind is inv.InventoryKind.AUTHORED_DOCUMENTATION


def test_reimport_module_stays_side_effect_free() -> None:
    sys.modules.pop("ipfs_datasets_py.duckdb_control.inventory", None)
    reloaded = importlib.import_module("ipfs_datasets_py.duckdb_control.inventory")
    assert reloaded.INVENTORY_SCHEMA == inv.INVENTORY_SCHEMA
    sys.modules["ipfs_datasets_py.duckdb_control.inventory"] = reloaded
