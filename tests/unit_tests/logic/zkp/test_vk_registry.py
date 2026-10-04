import pytest

from ipfs_datasets_py.logic.zkp.vk_registry import (
    VKRegistry,
    compute_vk_hash,
)


def test_compute_vk_hash_stable_for_dict_key_order():
    vk_a = {"alpha": 1, "beta": {"z": 9, "y": 8}}
    vk_b = {"beta": {"y": 8, "z": 9}, "alpha": 1}
    assert compute_vk_hash(vk_a) == compute_vk_hash(vk_b)


def test_registry_register_and_get():
    reg = VKRegistry()
    reg.register("knowledge_of_axioms", 1, "0" * 64)
    assert reg.get("knowledge_of_axioms", 1) == "0" * 64


def test_registry_ref_lookup_supports_versioned_and_legacy():
    reg = VKRegistry()
    reg.register("knowledge_of_axioms", 1, "a" * 64)
    assert reg.get_by_ref("knowledge_of_axioms@v1") == "a" * 64
    # Legacy format defaults to v1 via parse_circuit_ref_lenient
    assert reg.get_by_ref("knowledge_of_axioms") == "a" * 64


def test_registry_duplicate_registration_requires_overwrite_if_hash_differs():
    reg = VKRegistry()
    reg.register("knowledge_of_axioms", 1, "1" * 64)
    with pytest.raises(ValueError, match="already registered"):
        reg.register("knowledge_of_axioms", 1, "2" * 64)

    reg.register("knowledge_of_axioms", 1, "2" * 64, overwrite=True)
    assert reg.get("knowledge_of_axioms", 1) == "2" * 64


def test_registry_list_versions_sorted():
    reg = VKRegistry()
    reg.register("c", 2, "1" * 64)
    reg.register("c", 1, "2" * 64)
    assert reg.list_versions("c") == [1, 2]
