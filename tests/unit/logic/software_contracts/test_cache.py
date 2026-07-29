"""Immutable software-contract analysis cache tests (DSCON-G100)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_contracts.cache import (
    INDEX_SCHEMA,
    OUTCOME_NEGATIVE,
    OUTCOME_PROVED,
    OUTCOME_UNKNOWN,
    AnalysisCache,
    AnalysisCacheKey,
    CacheIntegrityError,
    CacheKeyError,
    CacheLeaseError,
    FormalVerificationCache,
    ImmutableCAS,
    ProofCache,
    cache_profile_descriptor,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
)


RESULT_SCHEMA = "tests/software-contract-result@1"


def identity(name: str) -> str:
    return cid_for_structured({"identity": name})


def key(
    source: bytes = b"source",
    dependencies: tuple[bytes, ...] = (b"dependency",),
    **overrides: Any,
) -> AnalysisCacheKey:
    values: dict[str, Any] = {
        "source_cid": cid_for_bytes(source),
        "dependency_cids": tuple(cid_for_bytes(item) for item in dependencies),
        "analyzer_cid": identity("analyzer-v1"),
        "configuration_cid": identity("configuration-v1"),
        "semantics_cid": identity("semantics-v1"),
        "policy_cid": identity("policy-v1"),
        "solver_cid": identity("solver-v1"),
        "toolchain_cid": identity("toolchain-v1"),
        "result_schema": RESULT_SCHEMA,
    }
    values.update(overrides)
    return AnalysisCacheKey(**values)


def result(label: str = "ok") -> dict[str, Any]:
    return {"schema": RESULT_SCHEMA, "label": label, "proved": True}


def test_cache_profile_and_key_bind_every_reusable_dimension_without_tree() -> None:
    descriptor = cache_profile_descriptor()
    assert descriptor["global_tree_in_reusable_key"] is False
    assert descriptor["global_tree_in_snapshot_receipt"] is True
    assert descriptor["read_integrity"] == "decode-and-recompute"

    base = key()
    payload = base.to_dict()
    assert "repository_tree_cid" not in payload
    assert "repository_tree" not in canonical_dag_json_bytes(payload).decode()
    assert base.dependency_cids == tuple(sorted(base.dependency_cids))

    dimensions = {
        "source_cid": cid_for_bytes(b"changed source"),
        "dependency_cids": (cid_for_bytes(b"changed dependency"),),
        "analyzer_cid": identity("analyzer-v2"),
        "configuration_cid": identity("configuration-v2"),
        "semantics_cid": identity("semantics-v2"),
        "policy_cid": identity("policy-v2"),
        "solver_cid": identity("solver-v2"),
        "toolchain_cid": identity("toolchain-v2"),
        "result_schema": "tests/software-contract-result@2",
    }
    for field, changed in dimensions.items():
        assert key(**{field: changed}).cid != base.cid, field


def test_key_rejects_bad_closure_and_unprofiled_identities() -> None:
    source = cid_for_bytes(b"same")
    with pytest.raises(CacheKeyError):
        key(source_cid=source, dependency_cids=(source,))
    dependency = cid_for_bytes(b"duplicate")
    with pytest.raises(CacheKeyError):
        key(dependency_cids=(dependency, dependency))
    with pytest.raises(CacheKeyError):
        key(policy_cid="sha256:not-a-profile-cid")
    with pytest.raises(CacheKeyError):
        key(source_cid=identity("structured-is-not-source"))
    with pytest.raises(CacheKeyError):
        key(policy_cid=cid_for_bytes(b"raw-is-not-policy"))


def test_immutable_cas_round_trips_source_and_structured_with_schema(
    tmp_path: Path,
) -> None:
    cas = ImmutableCAS(tmp_path)
    source_cid = cas.put_bytes(b"\x00source\xff")
    assert cas.get_bytes(source_cid) == b"\x00source\xff"

    value = result()
    object_cid = cas.put(value)
    assert cas.get(object_cid, expected_schema=RESULT_SCHEMA) == value
    with pytest.raises(CacheIntegrityError):
        cas.get(object_cid, expected_schema="wrong@1")


def test_immutable_cas_rejects_poisoning_truncation_and_noncanonical_json(
    tmp_path: Path,
) -> None:
    cas = ImmutableCAS(tmp_path)
    object_cid = cas.put(result())
    path = cas.path_for(object_cid)

    # Existing CAS names are immutable: put cannot overwrite a poisoned name.
    path.write_bytes(b'{"schema":"poison@1"}')
    with pytest.raises(CacheIntegrityError):
        cas.put(result())
    assert path.read_bytes() == b'{"schema":"poison@1"}'

    object_cid = cas.put({"schema": RESULT_SCHEMA, "n": 1})
    path = cas.path_for(object_cid)
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(CacheIntegrityError):
        cas.get(object_cid)

    canonical_value = {"schema": RESULT_SCHEMA, "a": 1, "b": 2}
    object_cid = cas.put(canonical_value)
    cas.path_for(object_cid).write_bytes(
        json.dumps(canonical_value, indent=2).encode("utf-8")
    )
    with pytest.raises(CacheIntegrityError, match="not canonical"):
        cas.get(object_cid)


def test_exact_key_lookup_misses_on_dependency_toolchain_and_policy_changes(
    tmp_path: Path,
) -> None:
    cache = AnalysisCache(tmp_path, clock=lambda: 100)
    original = key()
    receipt = cache.put(original, result())
    lookup = cache.lookup(original)
    assert lookup.hit
    assert lookup.result == result()
    assert lookup.receipt == receipt
    assert lookup.satisfies_completion

    changed_keys = (
        key(dependency_cids=(cid_for_bytes(b"new dependency"),)),
        key(toolchain_cid=identity("toolchain-v2")),
        key(policy_cid=identity("policy-v2")),
    )
    for changed in changed_keys:
        miss = cache.lookup(changed)
        assert not miss.hit
        assert miss.result is None
        assert not miss.satisfies_completion


def test_result_schema_is_bound_on_write_and_recomputed_on_read(
    tmp_path: Path,
) -> None:
    cache = AnalysisCache(tmp_path, clock=lambda: 100)
    cache_key = key()
    with pytest.raises(CacheIntegrityError):
        cache.put(cache_key, {"schema": "wrong@1", "proved": True})

    receipt = cache.put(cache_key, result())
    result_path = cache.cas.path_for(receipt.result_cid)
    poisoned = {"schema": RESULT_SCHEMA, "label": "poisoned", "proved": True}
    result_path.write_bytes(canonical_dag_json_bytes(poisoned))
    with pytest.raises(CacheIntegrityError, match="CID mismatch"):
        cache.lookup(cache_key)


def test_index_poisoning_and_wrong_key_membership_are_rejected(
    tmp_path: Path,
) -> None:
    cache = AnalysisCache(tmp_path, clock=lambda: 100)
    first_key = key(source=b"first")
    second_key = key(source=b"second")
    cache.put(first_key, result("first"))
    second_receipt = cache.put(second_key, result("second"))

    # Point the first replaceable index at a valid receipt for another key.
    poisoned = {
        "schema": INDEX_SCHEMA,
        "key_cid": first_key.cid,
        "receipt_cid": second_receipt.cid,
    }
    cache._index_path(first_key.cid).write_bytes(
        canonical_dag_json_bytes(poisoned)
    )
    with pytest.raises(CacheIntegrityError, match="wrong shard key"):
        cache.lookup(first_key)

    # A noncanonical or truncated index is also rejected before it is trusted.
    cache._index_path(first_key.cid).write_bytes(b"{")
    with pytest.raises(CacheIntegrityError, match="index record is invalid"):
        cache.lookup(first_key)


def test_unknown_results_require_bounded_leases_and_never_complete(
    tmp_path: Path,
) -> None:
    now = [100]
    cache = AnalysisCache(
        tmp_path,
        clock=lambda: now[0],
        max_lease_seconds=10,
    )
    cache_key = key()
    with pytest.raises(CacheLeaseError):
        cache.put(cache_key, result("unknown"), outcome=OUTCOME_UNKNOWN)
    with pytest.raises(CacheLeaseError):
        cache.put(cache_key, result("negative"), outcome=OUTCOME_NEGATIVE)
    negative = cache.put(
        cache_key,
        result("negative"),
        outcome=OUTCOME_NEGATIVE,
        lease_seconds=5,
    )
    assert not negative.satisfies_completion(now[0])
    with pytest.raises(CacheLeaseError):
        cache.put(
            cache_key,
            result("unknown"),
            outcome=OUTCOME_UNKNOWN,
            lease_seconds=11,
        )
    receipt = cache.put(
        cache_key,
        result("unknown"),
        outcome=OUTCOME_UNKNOWN,
        lease_seconds=10,
    )
    assert receipt.lease_expires_at == 110
    lookup = cache.lookup(cache_key)
    assert lookup.hit
    assert not lookup.satisfies_completion
    assert not receipt.satisfies_completion(now[0])

    now[0] = 110
    expired = cache.lookup(cache_key)
    assert not expired.hit
    assert expired.reason == "expired"

    with pytest.raises(CacheLeaseError):
        cache.put(
            cache_key,
            result(),
            outcome=OUTCOME_PROVED,
            lease_seconds=1,
        )


def test_one_blob_mutation_invalidates_only_reverse_dependency_closure(
    tmp_path: Path,
) -> None:
    cache = AnalysisCache(tmp_path, clock=lambda: 100)
    changed = b"shared-dependency"
    affected_direct = key(source=b"direct", dependencies=(changed,))
    affected_transitive = key(
        source=b"transitive",
        dependencies=(b"middle", changed),  # key stores transitive closure
    )
    unaffected = key(source=b"other", dependencies=(b"other-dependency",))
    for item in (affected_direct, affected_transitive, unaffected):
        cache.put(item, result(item.source_cid))

    invalidated = cache.invalidate_source_closure(cid_for_bytes(changed))
    assert set(invalidated) == {
        affected_direct.cid,
        affected_transitive.cid,
    }
    assert not cache.lookup(affected_direct).hit
    assert not cache.lookup(affected_transitive).hit
    assert cache.lookup(unaffected).hit

    # Invalidation removes replaceable indexes, never immutable evidence.
    assert any((tmp_path / "cas" / "structured").glob("*/*"))


def test_snapshot_receipt_binds_tree_and_exact_shard_membership(
    tmp_path: Path,
) -> None:
    cache = AnalysisCache(tmp_path, clock=lambda: 100)
    first = cache.put(key(source=b"first"), result("first"))
    second = cache.put(key(source=b"second"), result("second"))
    tree_cid = cid_for_structured({"repository": "tree-a"})
    snapshot = cache.create_snapshot_receipt(tree_cid, (first, second))

    assert snapshot.repository_tree_cid == tree_cid
    assert "repository_tree_cid" in snapshot.to_dict()
    assert "repository_tree_cid" not in first.key.to_dict()
    assert cache.read_snapshot_receipt(
        snapshot.cid,
        expected_repository_tree_cid=tree_cid,
        expected_key_cids=(first.key_cid, second.key_cid),
    ) == snapshot

    with pytest.raises(CacheIntegrityError, match="repository-tree"):
        cache.read_snapshot_receipt(
            snapshot.cid,
            expected_repository_tree_cid=cid_for_structured(
                {"repository": "tree-b"}
            ),
        )
    with pytest.raises(CacheIntegrityError, match="shard membership"):
        cache.read_snapshot_receipt(
            snapshot.cid,
            expected_key_cids=(first.key_cid,),
        )


def test_formal_cache_names_are_strict_contract_analysis_aliases(
    tmp_path: Path,
) -> None:
    assert ProofCache is FormalVerificationCache
    cache = FormalVerificationCache(tmp_path, clock=lambda: 100)
    assert cache.put(key(), result()).outcome == OUTCOME_PROVED
