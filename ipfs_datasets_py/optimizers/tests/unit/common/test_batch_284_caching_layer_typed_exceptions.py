"""Regression coverage for typed exception handling in caching_layer."""

from __future__ import annotations

import pickle

from ipfs_datasets_py.optimizers.common.caching_layer import CacheL2


def test_cache_l2_get_unpickling_error_returns_none_and_counts_miss(
    tmp_path, monkeypatch
) -> None:
    cache = CacheL2(path=str(tmp_path))
    cache.set("k1", {"value": 1})

    def _raise_unpickle(_file):
        raise pickle.UnpicklingError("bad pickle payload")

    monkeypatch.setattr(pickle, "load", _raise_unpickle)

    assert cache.get("k1") is None
    assert cache.metrics.misses >= 1


def test_cache_l2_set_pickling_error_is_swallowed(tmp_path, monkeypatch) -> None:
    cache = CacheL2(path=str(tmp_path))

    def _raise_pickling(_value, _file):
        raise pickle.PicklingError("cannot pickle")

    monkeypatch.setattr(pickle, "dump", _raise_pickling)

    cache.set("k2", {"value": 2})
    assert cache._load_index() == {}


def test_cache_l2_load_index_invalid_json_returns_empty_dict(tmp_path) -> None:
    cache = CacheL2(path=str(tmp_path))
    cache.index_path.write_text("{invalid json", encoding="utf-8")

    assert cache._load_index() == {}
