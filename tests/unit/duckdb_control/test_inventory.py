"""Unit tests for the bounded streaming inventory scanner (DQK-001).

These tests never load multi-hundred-MB corpora into memory. Large-file
behavior is proven with a deliberately small chunk size and a file larger
than that chunk, plus an explicit peak-buffer assertion on the streaming
hasher.
"""

from __future__ import annotations

import hashlib
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

from ipfs_datasets_py.duckdb_control.inventory import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_RULES,
    INVENTORY_SCHEMA,
    ArtifactKind,
    ClassificationRule,
    InventoryRecord,
    InventoryRegistry,
    ProposedAuthority,
    build_registry,
    classify_path,
    default_scan_roots,
    digest_file_streaming,
    inventory_snapshot_digest,
    iter_inventory,
    iter_sorted_files,
    normalize_rel_path,
    record_required_fields,
    scan_inventory,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write(path: Path, data: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    return path


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """Synthetic datasets + supervisor tree covering every artifact kind."""
    root = tmp_path / "repo"
    _write(
        root / "docs" / "architecture" / "PLAN.md",
        "# Plan\nAuthored documentation.\n",
    )
    _write(
        root / "docs" / "exports" / "snapshot.md",
        "Derived export projection.\n",
    )
    _write(
        root / "data" / "agent_supervisor" / "control.duckdb",
        b"DUCKDB_CONTROL_STATE",
    )
    _write(
        root
        / "data"
        / "agent_supervisor"
        / "state"
        / "lane-1"
        / "implementation_checkpoints"
        / "ckpt.json",
        '{"cursor": 1}\n',
    )
    _write(
        root / "data" / "agent_supervisor" / "receipts" / "merge-receipt.json",
        '{"ok": true}\n',
    )
    _write(
        root / "ipfs_datasets_py" / "vector_stores" / "index.pkl",
        b"\x80\x04pickle-bytes",
    )
    _write(
        root / "ipfs_datasets_py" / "processors" / "wallet" / "records.jsonl",
        '{"tx": 1}\n',
    )
    _write(
        root / "workspace" / "datasets" / "sample.meta.json",
        '{"rows": 3}\n',
    )
    _write(
        root / "archive" / "evidence" / "bundle.car",
        b"CAR\x00bytes",
    )
    _write(root / "README.md", "Root readme.\n")
    # Nested ignore candidate
    _write(root / "docs" / "__pycache__" / "x.pyc", b"ignored")
    return root


# ---------------------------------------------------------------------------
# Record contract
# ---------------------------------------------------------------------------


def test_required_fields_match_acceptance_contract() -> None:
    assert record_required_fields() == (
        "path",
        "kind",
        "size",
        "digest",
        "producer",
        "consumer",
        "proposed_authority",
    )


def test_inventory_record_validates_and_round_trips() -> None:
    digest = hashlib.sha256(b"abc").hexdigest()
    record = InventoryRecord(
        path="docs/PLAN.md",
        kind=ArtifactKind.AUTHORED_DOCUMENTATION,
        size=3,
        digest=digest,
        producer="human authors",
        consumer="reviewers",
        proposed_authority=ProposedAuthority.GIT_AUTHORED,
        rule_id="docs",
    )
    payload = record.to_dict()
    for field in record_required_fields():
        assert field in payload
        assert payload[field] not in (None, "")

    restored = InventoryRecord.from_mapping(payload)
    assert restored == record

    with pytest.raises(ValueError):
        InventoryRecord(
            path="",
            kind=ArtifactKind.UNKNOWN,
            size=0,
            digest=digest,
            producer="p",
            consumer="c",
            proposed_authority=ProposedAuthority.RETAIN_FILE,
        )
    with pytest.raises(ValueError):
        InventoryRecord(
            path="x",
            kind=ArtifactKind.UNKNOWN,
            size=-1,
            digest=digest,
            producer="p",
            consumer="c",
            proposed_authority=ProposedAuthority.RETAIN_FILE,
        )
    with pytest.raises(ValueError):
        InventoryRecord(
            path="x",
            kind=ArtifactKind.UNKNOWN,
            size=0,
            digest="not-a-digest",
            producer="p",
            consumer="c",
            proposed_authority=ProposedAuthority.RETAIN_FILE,
        )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rel_path", "kind", "authority"),
    [
        (
            "docs/architecture/PLAN.md",
            ArtifactKind.AUTHORED_DOCUMENTATION,
            ProposedAuthority.GIT_AUTHORED,
        ),
        (
            "data/agent_supervisor/control.duckdb",
            ArtifactKind.MUTABLE_STATE,
            ProposedAuthority.CONTROL_DUCKDB,
        ),
        (
            "data/agent_supervisor/receipts/merge-receipt.json",
            ArtifactKind.IMMUTABLE_EVIDENCE,
            ProposedAuthority.CONTENT_ADDRESSED,
        ),
        (
            "docs/exports/snapshot.md",
            ArtifactKind.DERIVED_EXPORT,
            ProposedAuthority.EXPORT_ONLY,
        ),
        (
            "ipfs_datasets_py/vector_stores/index.pkl",
            ArtifactKind.UNSAFE_SERIALIZATION,
            ProposedAuthority.ONE_TIME_IMPORT,
        ),
        (
            "ipfs_datasets_py/processors/wallet/records.jsonl",
            ArtifactKind.UNSAFE_SERIALIZATION,
            ProposedAuthority.ONE_TIME_IMPORT,
        ),
        (
            "workspace/datasets/sample.meta.json",
            ArtifactKind.UNSAFE_SERIALIZATION,
            ProposedAuthority.ONE_TIME_IMPORT,
        ),
        (
            "archive/evidence/bundle.car",
            ArtifactKind.IMMUTABLE_EVIDENCE,
            ProposedAuthority.CONTENT_ADDRESSED,
        ),
        (
            "plans/feature.todo.md",
            ArtifactKind.UNSAFE_SERIALIZATION,
            ProposedAuthority.CONTROL_DUCKDB,
        ),
    ],
)
def test_classify_path_distinguishes_kinds(
    rel_path: str,
    kind: ArtifactKind,
    authority: ProposedAuthority,
) -> None:
    rule = classify_path(rel_path)
    assert rule.kind is kind
    assert rule.proposed_authority is authority
    assert rule.producer
    assert rule.consumer


def test_default_rules_are_ordered_and_unique() -> None:
    ids = [rule.rule_id for rule in DEFAULT_RULES]
    assert len(ids) == len(set(ids))
    assert DEFAULT_RULES[-1].rule_id == "unknown-fallback"
    assert DEFAULT_RULES[-1].matches("totally/arbitrary.bin")


# ---------------------------------------------------------------------------
# Streaming digest / memory bound
# ---------------------------------------------------------------------------


def test_digest_file_streaming_matches_full_hash(tmp_path: Path) -> None:
    payload = b"0123456789abcdef" * 4096  # 64 KiB
    path = _write(tmp_path / "blob.bin", payload)
    size, digest = digest_file_streaming(path, chunk_size=64)
    assert size == len(payload)
    assert digest == hashlib.sha256(payload).hexdigest()


def test_digest_file_streaming_never_buffers_whole_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prove reads stay chunk-sized even when the file exceeds chunk_size."""
    chunk_size = 256
    payload = b"A" * (chunk_size * 40)  # 10 KiB >> chunk_size
    path = _write(tmp_path / "large.bin", payload)

    max_read = {"n": 0}
    real_open = Path.open

    def tracking_open(self: Path, *args: object, **kwargs: object):  # noqa: ANN001
        handle = real_open(self, *args, **kwargs)
        if self.resolve() != path.resolve():
            return handle
        original_read = handle.read

        def limited_read(size: int = -1) -> bytes:
            data = original_read(size)
            max_read["n"] = max(max_read["n"], len(data))
            return data

        handle.read = limited_read  # type: ignore[method-assign]
        return handle

    monkeypatch.setattr(Path, "open", tracking_open)
    size, digest = digest_file_streaming(path, chunk_size=chunk_size)
    assert size == len(payload)
    assert digest == hashlib.sha256(payload).hexdigest()
    # Every read is at most chunk_size; nothing ever materializes the full file.
    assert max_read["n"] <= chunk_size
    assert max_read["n"] > 0


def test_large_corpus_file_inventoried_with_tiny_chunks(
    tmp_path: Path,
) -> None:
    """Stand-in for the 970 MB production-hardening corpus: multi-chunk file."""
    root = tmp_path / "repo"
    # ~1 MiB payload — larger than the forced 4 KiB chunk size.
    payload = bytes((i * 17) % 256 for i in range(1024 * 1024))
    _write(root / "data" / "agent_supervisor" / "corpus" / "fixture.bin", payload)

    records = list(
        scan_inventory(
            root,
            roots=["data"],
            chunk_size=4096,
        )
    )
    assert len(records) == 1
    record = records[0]
    assert record.size == len(payload)
    assert record.digest == hashlib.sha256(payload).hexdigest()
    for field in record_required_fields():
        assert getattr(record, field) not in (None, "")


# ---------------------------------------------------------------------------
# Scanner determinism + streaming
# ---------------------------------------------------------------------------


def test_scan_is_streaming_iterator(corpus: Path) -> None:
    stream = scan_inventory(corpus)
    assert isinstance(stream, Iterator)
    assert not isinstance(stream, (list, tuple))
    first = next(stream)
    assert isinstance(first, InventoryRecord)
    # Remaining items still streamable without materializing first.
    rest = list(stream)
    assert rest  # corpus has multiple files


def test_scan_is_deterministic(corpus: Path) -> None:
    first = [r.to_dict() for r in scan_inventory(corpus)]
    second = [r.to_dict() for r in scan_inventory(corpus)]
    assert first == second
    paths = [row["path"] for row in first]
    assert paths == sorted(paths, key=lambda value: value.encode("utf-8"))
    assert inventory_snapshot_digest(
        InventoryRecord.from_mapping(row) for row in first  # type: ignore[misc]
    ) == inventory_snapshot_digest(
        InventoryRecord.from_mapping(row) for row in second  # type: ignore[misc]
    )


def test_scan_skips_ignored_directories(corpus: Path) -> None:
    paths = {record.path for record in scan_inventory(corpus)}
    assert not any("__pycache__" in path for path in paths)
    assert not any(path.endswith(".pyc") for path in paths)


def test_scan_skips_egg_info_directories_by_suffix(tmp_path: Path) -> None:
    """Packaging metadata dirs ending in .egg-info must never be inventoried."""
    root = tmp_path / "repo"
    _write(root / "docs" / "visible.md", "keep\n")
    # Nested under a default scan root so the walk must actively prune them.
    _write(
        root / "docs" / "pkg.egg-info" / "PKG-INFO",
        "Name: pkg\n",
    )
    _write(
        root / "ipfs_datasets_py" / "ipfs_datasets_py.egg-info" / "SOURCES.txt",
        "hidden\n",
    )
    _write(root / "ipfs_datasets_py" / "module.py", "x = 1\n")
    paths = {record.path for record in scan_inventory(root)}
    assert any(path.endswith("visible.md") for path in paths)
    assert any(path.endswith("module.py") for path in paths)
    assert not any("egg-info" in path for path in paths)
    assert not any(path.endswith("PKG-INFO") for path in paths)
    assert not any(path.endswith("SOURCES.txt") for path in paths)


def test_every_record_has_required_fields_and_known_kind(corpus: Path) -> None:
    records = list(scan_inventory(corpus))
    assert records
    kinds_seen: set[ArtifactKind] = set()
    for record in records:
        kinds_seen.add(record.kind)
        payload = record.to_dict()
        for field in record_required_fields():
            assert field in payload
            assert payload[field] not in (None, "")
        assert record.kind in ArtifactKind
        assert record.proposed_authority in ProposedAuthority
        # Digest matches on-disk bytes (relative to corpus root).
        absolute = corpus / record.path
        # default_scan_roots may nest under common base; resolve carefully.
        candidates = [
            corpus / record.path,
            *[root / Path(record.path).name for root in default_scan_roots(corpus)],
        ]
        # Prefer full relative path under corpus.
        if absolute.is_file():
            content = absolute.read_bytes()
            assert record.size == len(content)
            assert record.digest == hashlib.sha256(content).hexdigest()
        else:
            # Path is relative to a scan root / common base; search under corpus.
            matches = list(corpus.rglob(Path(record.path).name))
            assert matches, record.path
            # Use the path suffix match.
            found = None
            for match in matches:
                try:
                    rel = match.relative_to(corpus).as_posix()
                except ValueError:
                    continue
                if rel == record.path or rel.endswith(record.path):
                    found = match
                    break
            assert found is not None, record.path
            content = found.read_bytes()
            assert record.size == len(content)
            assert record.digest == hashlib.sha256(content).hexdigest()

    # Corpus must exercise the five primary kinds from the task statement.
    required = {
        ArtifactKind.AUTHORED_DOCUMENTATION,
        ArtifactKind.MUTABLE_STATE,
        ArtifactKind.IMMUTABLE_EVIDENCE,
        ArtifactKind.DERIVED_EXPORT,
        ArtifactKind.UNSAFE_SERIALIZATION,
    }
    assert required.issubset(kinds_seen)


def test_iter_sorted_files_is_deterministic(corpus: Path) -> None:
    a = [rel for _, rel in iter_sorted_files([corpus])]
    b = [rel for _, rel in iter_sorted_files([corpus])]
    assert a == b
    assert a == sorted(a, key=lambda value: value.encode("utf-8"))


def test_normalize_rel_path_is_stable() -> None:
    assert normalize_rel_path("./docs\\architecture//PLAN.md") == (
        "docs/architecture/PLAN.md"
    )
    assert normalize_rel_path("/abs/path") == "abs/path"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_indexes_kinds_and_authorities(corpus: Path) -> None:
    registry = build_registry(corpus)
    assert registry.schema == INVENTORY_SCHEMA
    assert len(registry) > 0

    unsafe = registry.by_kind(ArtifactKind.UNSAFE_SERIALIZATION)
    assert unsafe
    assert all(r.kind is ArtifactKind.UNSAFE_SERIALIZATION for r in unsafe)

    control = registry.by_authority(ProposedAuthority.CONTROL_DUCKDB)
    assert control
    assert all(
        r.proposed_authority is ProposedAuthority.CONTROL_DUCKDB for r in control
    )

    counts = registry.kind_counts()
    assert sum(counts.values()) == len(registry)
    auth_counts = registry.authority_counts()
    assert sum(auth_counts.values()) == len(registry)
    assert set(auth_counts) == {
        record.proposed_authority.value for record in registry
    }
    # Authority keys are sorted for stable snapshots.
    assert list(auth_counts) == sorted(auth_counts)
    assert registry.snapshot_digest() == inventory_snapshot_digest(registry)
    assert registry.paths() == tuple(record.path for record in registry)

    # Deterministic materialization
    again = build_registry(corpus)
    assert registry.to_list() == again.to_list()
    assert again.authority_counts() == auth_counts


def test_registry_get_and_contains(corpus: Path) -> None:
    registry = build_registry(corpus)
    any_record = next(iter(registry))
    assert any_record.path in registry
    assert registry.get(any_record.path) == any_record
    assert registry.get("does/not/exist") is None


def test_include_kinds_filter(corpus: Path) -> None:
    only_unsafe = list(
        scan_inventory(
            corpus,
            include_kinds=[ArtifactKind.UNSAFE_SERIALIZATION],
        )
    )
    assert only_unsafe
    assert all(
        record.kind is ArtifactKind.UNSAFE_SERIALIZATION for record in only_unsafe
    )


def test_iter_inventory_over_explicit_roots(tmp_path: Path) -> None:
    a = _write(tmp_path / "a" / "one.md", "a\n")
    b = _write(tmp_path / "b" / "two.pkl", b"pickle")
    records = list(iter_inventory([tmp_path / "a", tmp_path / "b"]))
    paths = {record.path for record in records}
    # Paths are relative to common base (tmp_path).
    assert any(path.endswith("one.md") for path in paths)
    assert any(path.endswith("two.pkl") for path in paths)
    kinds = {record.kind for record in records}
    assert ArtifactKind.AUTHORED_DOCUMENTATION in kinds
    assert ArtifactKind.UNSAFE_SERIALIZATION in kinds
    # Silence unused warnings in some linters
    assert a.exists() and b.exists()


def test_default_scan_roots_prefer_supervisor_tree(tmp_path: Path) -> None:
    _write(tmp_path / "data" / "agent_supervisor" / "x.txt", "x")
    _write(tmp_path / "docs" / "y.md", "y")
    roots = default_scan_roots(tmp_path)
    root_names = {r.name for r in roots}
    assert "docs" in root_names or any(r.name == "docs" for r in roots)
    # data/agent_supervisor preferred over bare data
    assert any(r.name == "agent_supervisor" for r in roots)
    assert not any(r.name == "data" and r.parent == tmp_path for r in roots)


def test_chunk_size_must_be_positive(tmp_path: Path) -> None:
    path = _write(tmp_path / "f.bin", b"x")
    with pytest.raises(ValueError):
        digest_file_streaming(path, chunk_size=0)


def test_module_import_is_inert() -> None:
    """Re-import does not require duckdb or touch the filesystem."""
    mod_name = "ipfs_datasets_py.duckdb_control.inventory"
    assert mod_name in sys.modules
    # Schema constant stable
    assert INVENTORY_SCHEMA.startswith("ipfs_datasets_py/")


def test_custom_rule_precedence(tmp_path: Path) -> None:
    rules = (
        ClassificationRule(
            rule_id="custom-md-as-state",
            kind=ArtifactKind.MUTABLE_STATE,
            producer="test",
            consumer="test",
            proposed_authority=ProposedAuthority.CONTROL_DUCKDB,
            name_suffixes=(".md",),
        ),
        ClassificationRule(
            rule_id="fallback",
            kind=ArtifactKind.UNKNOWN,
            producer="u",
            consumer="u",
            proposed_authority=ProposedAuthority.RETAIN_FILE,
            path_regexes=(r".*",),
        ),
    )
    rule = classify_path("docs/x.md", rules=rules)
    assert rule.rule_id == "custom-md-as-state"
    assert rule.kind is ArtifactKind.MUTABLE_STATE


def test_build_registry_from_empty_tree(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    registry = build_registry(empty, roots=["."])
    assert len(registry) == 0
    assert registry.kind_counts() == {}
    assert registry.authority_counts() == {}
    assert registry.rule_counts() == {}
    assert registry.paths() == ()
    assert registry.snapshot_digest() == hashlib.sha256().hexdigest()


def test_authority_counts_reflect_control_and_export(corpus: Path) -> None:
    registry = build_registry(corpus)
    auth = registry.authority_counts()
    # Corpus plants control-duckdb state, git docs, content-addressed evidence,
    # export projections, and one-time-import unsafe serializations.
    assert auth.get(ProposedAuthority.CONTROL_DUCKDB.value, 0) >= 1
    assert auth.get(ProposedAuthority.GIT_AUTHORED.value, 0) >= 1
    assert auth.get(ProposedAuthority.CONTENT_ADDRESSED.value, 0) >= 1
    assert auth.get(ProposedAuthority.EXPORT_ONLY.value, 0) >= 1
    assert auth.get(ProposedAuthority.ONE_TIME_IMPORT.value, 0) >= 1


def test_rule_counts_and_by_rule_id(corpus: Path) -> None:
    registry = build_registry(corpus)
    counts = registry.rule_counts()
    assert sum(counts.values()) == len(registry)
    assert list(counts) == sorted(counts)
    # Every non-empty rule_id groups exactly its matching records.
    for rule_id, expected in counts.items():
        matched = registry.by_rule_id(rule_id)
        assert len(matched) == expected
        assert all(record.rule_id == rule_id for record in matched)
        assert [record.path for record in matched] == sorted(
            (record.path for record in matched),
            key=lambda value: value.encode("utf-8"),
        )
    assert registry.by_rule_id("__no_such_rule__") == ()


def test_record_to_dict_preserves_required_field_order() -> None:
    digest = hashlib.sha256(b"order").hexdigest()
    record = InventoryRecord(
        path="docs/order.md",
        kind=ArtifactKind.AUTHORED_DOCUMENTATION,
        size=5,
        digest=digest,
        producer="authors",
        consumer="readers",
        proposed_authority=ProposedAuthority.GIT_AUTHORED,
    )
    keys = list(record.to_dict())
    # Required acceptance fields appear first, in the contract order.
    assert keys[:7] == list(record_required_fields())
