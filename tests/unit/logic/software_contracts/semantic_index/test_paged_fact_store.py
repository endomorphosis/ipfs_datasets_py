"""Private, small fixtures for bounded raw-fact storage; no target imports."""
from dataclasses import replace
import errno
import os

import pytest

from ipfs_datasets_py.logic.software_contracts.content import canonical_dag_json_bytes, cid_for_structured
from ipfs_datasets_py.logic.software_contracts.semantic_index import paged_fact_store as p


def budget(**overrides):
    return p.FactSpoolBudget(**(dict(max_stored_bytes=8*1024*1024, max_blocks=5000,
        max_records=10000, max_io_bytes=128*1024*1024, max_work_items=100000) | overrides))


def opened(path, **overrides):
    store = p.OwnedFactStore(path, profile=p.PagedFactProfile(), budget=budget(**overrides))
    store.bind_request({"schema": "fixture/raw-request@1"})
    return store


@pytest.mark.parametrize("field", ["working_bytes", "frame_bytes", "page_items", "max_depth"])
def test_profile_cannot_silently_widen_or_accept_boolean(field):
    with pytest.raises(p.PagedFactError):
        p.PagedFactProfile(**{field: True})
    with pytest.raises(p.PagedFactError):
        p.PagedFactProfile(**{field: getattr(p.PagedFactProfile(), field) + 1})


@pytest.mark.parametrize("field", list(p.FactSpoolBudget.__dataclass_fields__))
@pytest.mark.parametrize("value", [True, 0, -1, 2**63])
def test_budget_is_explicit_strict_and_bounded(field, value):
    with pytest.raises(p.PagedFactError):
        budget(**{field: value})


def test_store_refuses_existing_directory_and_symlink_without_touching_them(tmp_path):
    existing = tmp_path / "prior"
    existing.mkdir()
    marker = existing / "preserve"
    marker.write_bytes(b"evidence")
    alias = tmp_path / "alias"
    alias.symlink_to(existing, target_is_directory=True)
    for path in (existing, alias):
        with pytest.raises(FileExistsError):
            p.OwnedFactStore(path, profile=p.PagedFactProfile(), budget=budget())
    assert marker.read_bytes() == b"evidence"
    assert sorted(x.name for x in existing.iterdir()) == ["preserve"]


def test_directory_replacement_and_frozen_budget_mutation_refuse(tmp_path):
    with opened(tmp_path / "facts") as store:
        store.path.rename(tmp_path / "moved")
        store.path.mkdir()
        with pytest.raises(p.PagedFactError, match="store_directory_changed"):
            store.put({"item": 1})
    with opened(tmp_path / "second") as store:
        object.__setattr__(store.budget, "max_records", store.budget.max_records + 1)
        with pytest.raises(p.PagedFactError, match="store_admission_changed"):
            store.put({"item": 2})


def test_canonical_record_and_duplicate_write_reverify(tmp_path):
    with opened(tmp_path / "facts") as store:
        cid = store.put({"item": [1, 2]})
        usage = store.usage()
        assert store.get(cid) == {"item": [1, 2]}
        assert store.put({"item": [1, 2]}) == cid
        assert store.usage()["stored_bytes"] == usage["stored_bytes"]
        (store.path / cid).write_bytes(b'{"item": [1, 2]}')
        with pytest.raises(p.PagedFactError, match="fact_canonical_or_cid"):
            store.get(cid)
        with pytest.raises(p.PagedFactError):
            store.put({"item": [1, 2]})


@pytest.mark.parametrize("attack", ["symlink", "hardlink", "oversized", "missing", "wrong-cid"])
def test_block_substitution_denied(tmp_path, attack):
    with opened(tmp_path / "facts") as store:
        cid = store.put({"item": 1})
        path = store.path / cid
        path.unlink()
        other = tmp_path / "other"
        other.write_bytes(canonical_dag_json_bytes({"item": 1}))
        if attack == "symlink":
            path.symlink_to(other)
        elif attack == "hardlink":
            os.link(other, path)
        elif attack == "oversized":
            with path.open("wb") as stream:
                stream.truncate(p.FRAME_BYTES + 1)
        elif attack == "wrong-cid":
            path.write_bytes(canonical_dag_json_bytes({"item": 2}))
        with pytest.raises((p.PagedFactError, OSError)):
            store.get(cid)


def test_index_crosses_pages_and_has_deterministic_order(tmp_path):
    with opened(tmp_path / "facts") as store:
        pairs = [(f"{i:05d}", store.put({"value": i})) for i in range(700)]
        desc = p.build_fact_index(store, iter(pairs))
        assert desc["level"] == 1 and desc["count"] == 700
        assert list(p.iter_fact_index(store, desc)) == pairs
        assert p.verify_fact_index(store, desc) == desc
        assert p.build_fact_index(store, iter(pairs)) == desc
        assert all(path.stat().st_size <= p.FRAME_BYTES for path in store.path.iterdir())
        with pytest.raises(p.PagedFactError, match="index_order"):
            p.build_fact_index(store, iter([pairs[0], pairs[0]]))


@pytest.mark.parametrize("attack", ["count", "range", "level", "duplicate-child", "missing-child", "packing"])
def test_rehashed_forged_index_structure_denied(tmp_path, attack):
    with opened(tmp_path / "facts") as store:
        pair = ["a", store.put({"value": 1})]
        leaf = p._page(0, [pair])
        desc = p._descriptor(store.put(leaf), 0, leaf["items"])
        if attack == "count":
            desc["count"] += 1
        elif attack == "range":
            desc["last"] = "z"
        elif attack == "level":
            desc["level"] = True
        elif attack in {"duplicate-child", "packing"}:
            children = [desc, desc] if attack == "duplicate-child" else [desc]
            root = p._page(1, children)
            desc = p._descriptor(store.put(root), 1, children)
        else:
            (store.path / desc["cid"]).unlink()
        with pytest.raises((p.PagedFactError, FileNotFoundError)):
            p.verify_fact_index(store, desc)


def test_empty_index_and_oversized_single_key(tmp_path):
    with opened(tmp_path / "facts") as store:
        empty = p.build_fact_index(store, ())
        assert empty["count"] == 0 and list(p.iter_fact_index(store, empty)) == []
        p.verify_fact_index(store, empty)
        with pytest.raises(p.PagedFactError, match="index_item_frame"):
            p.build_fact_index(store, [("k" * p.FRAME_BYTES, cid_for_structured({}))])


def test_byte_budget_refuses_before_block_allocation(tmp_path):
    with opened(tmp_path / "facts", max_stored_bytes=128) as store:
        before = sorted(x.name for x in store.path.iterdir())
        with pytest.raises(p.PagedFactError, match="spool_stored_bytes"):
            store.put({"value": "x" * 256})
        assert sorted(x.name for x in store.path.iterdir()) == before
        assert not (store.path / "raw-coverage.json").exists()


def test_storage_failure_retains_unpublished_evidence_and_charges(tmp_path, monkeypatch):
    with opened(tmp_path / "facts") as store:
        original = os.write
        def disk_full(fd, wire):
            original(fd, wire[:min(3, len(wire))])
            raise OSError(errno.ENOSPC, "fixture disk full")
        monkeypatch.setattr(p.os, "write", disk_full)
        with pytest.raises(OSError, match="fixture disk full"):
            store.put({"value": 1})
        assert store.usage()["stored_bytes"] > len(canonical_dag_json_bytes({"schema": "fixture/raw-request@1"}))
        assert not (store.path / "raw-coverage.json").exists()
        assert (store.path / "request.json").exists()


def test_consumed_store_cannot_bind_another_request_or_write_after_publication(tmp_path):
    with opened(tmp_path / "facts") as store:
        with pytest.raises(p.PagedFactError, match="already_consumed"):
            store.bind_request({"different": True})
        root = store.put({"fixture": "raw-descriptor", "completion_authority": False})
        store.publish_raw_coverage(root)
        with pytest.raises(p.PagedFactError, match="not_writable"):
            store.put({"late": 1})
        with pytest.raises(p.PagedFactError, match="already_consumed"):
            store.publish_raw_coverage(root)


def test_long_raw_path_refusal_is_bounded_without_losing_identity():
    raw = "ab" * 20000
    error = p.PagedFactError("fixture", path=raw, progress={"raw_path_hex": raw, "entries_completed": 3})
    report = error.observation()
    assert report["raw_path_hex"] is None
    assert report["progress"]["raw_path_hex_length"] == len(raw)
    assert report["progress"]["raw_path_hex_prefix"] == raw[:2048]
    assert len(canonical_dag_json_bytes(report)) < 4096


def test_bounded_encoder_preserves_canonical_bytes_at_exact_limit():
    for value in ({}, {'a': 1}, {'é': '\\n\u0000雪'}, [None, False, True, -123, {'x': []}]):
        wire = canonical_dag_json_bytes(value)
        assert p._bounded_wire(value, len(wire)) == wire
        with pytest.raises(p.PagedFactError, match='fact_frame'):
            p._bounded_wire(value, len(wire)-1)


def test_bounded_encoder_rejects_cycles_and_oversize_before_serializing(monkeypatch):
    cyclic = []
    cyclic.append(cyclic)
    monkeypatch.setattr(p, 'canonical_dag_json_bytes', lambda value: pytest.fail('unbounded serializer reached'))
    with pytest.raises(p.PagedFactError, match='fact_structure_depth'):
        p._bounded_wire(cyclic, p.FRAME_BYTES)
    with pytest.raises(p.PagedFactError, match='fact_frame'):
        p._bounded_wire({'value': 'x' * (p.FRAME_BYTES+1)}, p.FRAME_BYTES)
