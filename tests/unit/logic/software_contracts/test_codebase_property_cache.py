"""Durable exact candidates stay non-authoritative across restart and tampering."""

from copy import deepcopy
import json
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.software_contracts.cache import (
    CacheIntegrityError, OUTCOME_PROVED, OUTCOME_UNKNOWN,
)
from ipfs_datasets_py.logic.software_contracts.codebase_property_cache import (
    CANDIDATE_LEASE_SECONDS, MAX_RESULT_BYTES, RESULT_SCHEMA,
    CodebasePropertyCache, CodebasePropertyCacheError,
    build_codebase_property_binding, property_analysis_cache_key,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes, cid_for_structured,
)


def inputs(**overrides):
    value = {
        "source_cid": cid_for_bytes(b"def increment(n: int) -> int:\n    return n + 1\n"),
        "snapshot_cid": cid_for_structured({"snapshot": "one"}),
        "profile": {"name": "exact-integer-successor@1", "assumptions": ["exact integer inputs"],
                    "implementation": {"sha256": "a" * 64}},
        "contract_cid": cid_for_structured({"postcondition": "result == n + 1"}),
        "compiled_cid": cid_for_structured({"smt": "negated successor obligation"}),
        "bounds": {"timeout_ms": 1000, "memory_bytes": 64 * 1024 * 1024},
        "environment": {"z3": {"version": "4.15.4", "binary_sha256": "b" * 64}, "platform": "linux"},
        "provider": "native:z3", "checker": "native:cvc5",
    }
    value.update(overrides)
    return value


def binding(**overrides):
    return build_codebase_property_binding(**inputs(**overrides))


def historical_result():
    return {"status": "solver_agreed_unsat", "elapsed_ms": 12,
            "evidence": {"solver": "z3", "checker": "cvc5"}}


def test_put_lookup_reopen_and_rewrite_are_historical_only(tmp_path):
    cache = CodebasePropertyCache(tmp_path)
    request, result = binding(), historical_result()
    assert cache.lookup(request) is None
    cache.put(request, result)
    result["status"] = "caller mutated after storage"
    assert cache.lookup(request) == historical_result()
    key = property_analysis_cache_key(request)
    stored = cache._cache.lookup(key)
    assert stored.receipt.outcome == OUTCOME_UNKNOWN
    assert stored.receipt.lease_expires_at - stored.receipt.created_at == CANDIDATE_LEASE_SECONDS
    assert not stored.satisfies_completion
    assert stored.result["authority"] == "historical_candidate"
    assert stored.result["requires_fresh_native_checks"] is True
    assert stored.receipt.key.configuration_cid == cid_for_structured(request)

    reopened = CodebasePropertyCache(tmp_path)
    restored = reopened.lookup(request)
    assert restored == historical_result()
    restored["status"] = "another caller mutation"
    assert reopened.lookup(request) == historical_result()
    updated = {**historical_result(), "elapsed_ms": 7}
    reopened.put(request, updated)
    assert cache.lookup(request) == updated
    assert reopened._cache.cas.get(stored.receipt.result_cid) == stored.result


def test_actual_fresh_process_recovers_exact_candidate(tmp_path):
    cache = CodebasePropertyCache(tmp_path)
    request = binding()
    cache.put(request, historical_result())
    script = '''
import json, sys
from ipfs_datasets_py.logic.software_contracts.codebase_property_cache import CodebasePropertyCache
cache = CodebasePropertyCache(sys.argv[1])
print(json.dumps(cache.lookup(json.loads(sys.argv[2])), sort_keys=True))
'''
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path), json.dumps(request)],
                               check=True, capture_output=True, text=True, timeout=30)
    assert json.loads(completed.stdout.splitlines()[-1]) == historical_result()


@pytest.mark.parametrize("field,changed", [
    ("source_cid", cid_for_bytes(b"changed source")),
    ("snapshot_cid", cid_for_structured({"snapshot": "different"})),
    ("contract_cid", cid_for_structured({"postcondition": "result == n - 1"})),
    ("compiled_cid", cid_for_structured({"smt": "different"})),
    ("profile", {"name": "changed-profile@2"}),
    ("bounds", {"timeout_ms": 2000}),
    ("environment", {"z3": {"version": "other", "binary_sha256": "c" * 64}}),
    ("provider", "native:other-provider"),
    ("checker", "native:other-checker"),
])
def test_every_bound_dimension_misses_under_another_valid_key(tmp_path, field, changed):
    cache = CodebasePropertyCache(tmp_path)
    original = binding()
    cache.put(original, historical_result())
    different = binding(**{field: changed})
    assert original["canonical_key_id"] != different["canonical_key_id"]
    assert property_analysis_cache_key(original) != property_analysis_cache_key(different)
    assert cache.lookup(different) is None


@pytest.mark.parametrize("field", ["source", "expression", "formalization", "slice", "obligation",
                                  "assumptions", "bounds", "translation", "environment", "policy",
                                  "schema", "network_policy"])
def test_forged_declared_proof_key_dimensions_rejected_on_read_and_write(tmp_path, field):
    cache = CodebasePropertyCache(tmp_path)
    forged = binding()
    forged["canonical_key"][field] = "sha256:" + "f" * 64
    with pytest.raises(CodebasePropertyCacheError, match="recompute"):
        cache.put(forged, historical_result())
    with pytest.raises(CodebasePropertyCacheError, match="recompute"):
        cache.lookup(forged)


@pytest.mark.parametrize("damage", ["id", "interface", "authority", "kind", "missing", "extra"])
def test_declared_identifier_and_authority_cannot_replace_recomputed_key(tmp_path, damage):
    forged = binding()
    if damage == "id":
        forged["canonical_key_id"] = "canonical-proof-cache-key:sha256:" + "d" * 64
    elif damage == "interface":
        forged["canonical_key"]["interface"] = "ForgedProofKey@1"
    elif damage == "authority":
        forged["canonical_key"]["authority_ceiling"] = "authoritative"
    elif damage == "kind":
        forged["canonical_key"]["evidence_kind"] = "kernel_checked_proof"
    elif damage == "missing":
        del forged["canonical_key"]["checker"]
    else:
        forged["canonical_key"]["key_id"] = forged["canonical_key_id"]
    with pytest.raises(CodebasePropertyCacheError, match="recompute"):
        CodebasePropertyCache(tmp_path).lookup(forged)


def test_rehashed_wrong_binding_in_result_is_rejected(tmp_path):
    cache = CodebasePropertyCache(tmp_path)
    request = binding()
    cache.put(request, historical_result())
    key = property_analysis_cache_key(request)
    stored = cache._cache.lookup(key)
    poisoned = deepcopy(stored.result)
    poisoned["binding"] = binding(contract_cid=cid_for_structured({"post": "other"}))
    # All CIDs are recomputed: the failure is exact membership, not bad JSON.
    cache._cache.put(key, poisoned, outcome=OUTCOME_UNKNOWN, lease_seconds=3600)
    with pytest.raises(CodebasePropertyCacheError, match="another exact binding"):
        cache.lookup(request)


def test_rehashed_completion_receipt_cannot_promote_candidate(tmp_path):
    cache = CodebasePropertyCache(tmp_path)
    request = binding()
    cache.put(request, historical_result())
    key = property_analysis_cache_key(request)
    stored = cache._cache.lookup(key)
    cache._cache.put(key, stored.result, outcome=OUTCOME_PROVED)
    with pytest.raises(CodebasePropertyCacheError, match="completion"):
        cache.lookup(request)


@pytest.mark.parametrize("damage", ["authority", "fresh_check", "extra"])
def test_rehashed_envelope_cannot_claim_checked_authority(tmp_path, damage):
    cache = CodebasePropertyCache(tmp_path)
    request = binding()
    cache.put(request, historical_result())
    key = property_analysis_cache_key(request)
    poisoned = deepcopy(cache._cache.lookup(key).result)
    if damage == "authority":
        poisoned["authority"] = "checked_proof"
    elif damage == "fresh_check":
        poisoned["requires_fresh_native_checks"] = False
    else:
        poisoned["checked"] = True
    cache._cache.put(key, poisoned, outcome=OUTCOME_UNKNOWN, lease_seconds=3600)
    with pytest.raises(CodebasePropertyCacheError, match="envelope"):
        cache.lookup(request)


@pytest.mark.parametrize("artifact", ["index", "receipt", "result"])
def test_corrupt_persistent_objects_fail_closed(tmp_path, artifact):
    cache = CodebasePropertyCache(tmp_path)
    request = binding()
    cache.put(request, historical_result())
    key = property_analysis_cache_key(request)
    found = cache._cache.lookup(key)
    if artifact == "index":
        path = cache._cache._index_path(key.cid)
    elif artifact == "receipt":
        path = cache._cache.cas.path_for(found.receipt.cid)
    else:
        path = cache._cache.cas.path_for(found.receipt.result_cid)
    path.write_bytes(b"{}")
    with pytest.raises(CacheIntegrityError):
        CodebasePropertyCache(tmp_path).lookup(request)


def test_candidate_expiration_does_not_become_completion(tmp_path):
    cache = CodebasePropertyCache(tmp_path)
    cache._cache.clock = lambda: 100
    request = binding()
    cache.put(request, historical_result())
    cache._cache.clock = lambda: 100 + CANDIDATE_LEASE_SECONDS
    assert cache.lookup(request) is None


@pytest.mark.parametrize("result", [{"elapsed": 1.25}, {"values": (1, 2)},
                                    {"oversized": "x" * (MAX_RESULT_BYTES + 1)}])
def test_unbounded_or_noncanonical_result_rejected_before_publication(tmp_path, result):
    cache = CodebasePropertyCache(tmp_path)
    request = binding()
    with pytest.raises(CodebasePropertyCacheError, match="bounded canonical JSON"):
        cache.put(request, result)
    assert cache.lookup(request) is None


def test_opaque_historical_status_is_data_and_never_completion(tmp_path):
    cache = CodebasePropertyCache(tmp_path)
    request = binding()
    candidate = {"status": "proved", "checked": True, "created_at": 1}
    cache.put(request, candidate)
    assert cache.lookup(request) == candidate
    underlying = cache._cache.lookup(property_analysis_cache_key(request))
    assert underlying.receipt.outcome == OUTCOME_UNKNOWN
    assert not underlying.satisfies_completion


def test_plain_complete_inputs_required():
    for field in ("profile", "bounds", "environment"):
        with pytest.raises(CodebasePropertyCacheError, match="explicit nonempty"):
            binding(**{field: {}})
    with pytest.raises(CodebasePropertyCacheError, match="source_cid"):
        binding(source_cid=cid_for_structured({"not": "raw bytes"}))
    with pytest.raises(CodebasePropertyCacheError):
        binding(provider="unknown")
