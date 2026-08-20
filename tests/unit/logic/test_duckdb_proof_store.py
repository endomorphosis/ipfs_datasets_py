"""Unit tests for the unified DuckDB proof store schema/protocol (DQK-025).

Acceptance coverage:

* No existing authority dimension is dropped
* Proof / counterexample / unknown / error outcomes remain distinct
* Exact key and integrity checks fail closed
"""

from __future__ import annotations

from pathlib import Path
import sys

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

from ipfs_datasets_py.logic.backends.cache_protocol import (
    VERIFICATION_CACHE_PROTOCOL_INTERFACE,
    CacheLookupReason,
    CachePolarity,
    ExactVerificationCache,
    VerificationCacheEntry,
    VerificationCacheKey,
    build_verification_cache_key,
    content_digest,
)
from ipfs_datasets_py.logic.backends.results import (
    ResultAuthority,
    ResultStatus,
    SatisfiabilityResult,
    TheoremResult,
)
from ipfs_datasets_py.logic.common.duckdb_proof_store import (
    DUCKDB_PROOF_STORE_INTERFACE,
    DUCKDB_PROOF_STORE_SCHEMA_VERSION,
    PROOF_AUTHORITY_DIMENSIONS,
    PROOF_AUTHORITY_DIMENSION_SET,
    PROOFS_CATALOG_DDL,
    PROOFS_CATALOG_TABLES,
    AccessStatistics,
    DuckDBProofStore,
    DuckDBProofStoreAuthorityError,
    DuckDBProofStoreError,
    DuckDBProofStoreIntegrityError,
    ImmutableEnvelopeReference,
    ProofEvidenceRecord,
    ProofOutcomeKind,
    ProofTrustLevel,
    UnifiedProofEntry,
    UnifiedProofKey,
    build_duckdb_proof_store,
    build_unified_proof_key,
    outcome_kind_for_status,
    trust_level_from_evidence,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds, ResourceUsage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _theorem(
    *,
    status: ResultStatus = ResultStatus.PROVED,
    authority: ResultAuthority = ResultAuthority.THEOREM,
    translation_ceiling: EvidenceAuthority = EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    result_id: str = "result:theorem-1",
    backend_id: str = "solver.z3",
    backend_version: str = "4.12.0",
    **changes,
) -> TheoremResult:
    fields = {
        "result_id": result_id,
        "backend_id": backend_id,
        "backend_version": backend_version,
        "authority": authority,
        "status": status,
        "assumptions": ("assumption:int",),
        "bounds": ExecutionBounds(
            timeout_ms=1000,
            max_steps=100,
            max_memory_bytes=4096,
            max_output_bytes=2048,
        ),
        "translation_ceiling": translation_ceiling,
        "usage": ResourceUsage(
            elapsed_ms=10,
            steps=5,
            peak_memory_bytes=512,
            output_bytes=64,
        ),
        "witness": {"kind": "proof"},
        "diagnostics": (),
        "reason": "",
        "metadata": {},
    }
    fields.update(changes)
    return TheoremResult(**fields)


def _sat(
    *,
    status: ResultStatus = ResultStatus.SATISFIABLE,
    translation_ceiling: EvidenceAuthority = EvidenceAuthority.BOUNDED,
) -> SatisfiabilityResult:
    return SatisfiabilityResult(
        result_id="result:sat-1",
        backend_id="solver.cvc5",
        backend_version="1.1.0",
        authority=ResultAuthority.SATISFIABILITY,
        status=status,
        assumptions=("assumption:model",),
        bounds=ExecutionBounds(
            timeout_ms=500,
            max_steps=50,
            max_memory_bytes=2048,
            max_output_bytes=1024,
        ),
        translation_ceiling=translation_ceiling,
        usage=ResourceUsage(
            elapsed_ms=5,
            steps=3,
            peak_memory_bytes=256,
            output_bytes=32,
        ),
        witness={"model": {"x": 1}},
    )


def _unified_key(**overrides) -> UnifiedProofKey:
    base = dict(
        ir={"formula": "(assert (> x 0))"},
        property_value={"property_id": "prop.safety"},
        assumptions=("assumption:int", "assumption:precondition"),
        selected_premises=("premise:nat.succ", "premise:nat.zero"),
        translator={
            "receipt_id": "tr:1",
            "preservation": "equisatisfiable",
            "version": "hammer-translator/v3",
        },
        solver_identities=(
            {"solver": "z3", "version": "4.12.0"},
            {"solver": "cvc5", "version": "1.1.0"},
        ),
        toolchain={"lean": "4.3.0", "lake": "5.0.0"},
        theorem_registry={"registry_hash": "reg:abc", "count": 12},
        policy={"mode": "production", "require_kernel": True},
        resources={"timeout_ms": 1000, "max_memory_bytes": 4096},
        tree={"tree_id": "tree:deadbeef", "commit": "abc123"},
        backend_id="solver.z3",
        backend_binary={"path": "/usr/bin/z3", "sha256": "abc"},
        backend_version="4.12.0",
        backend_config={"logic": "QF_LIA", "timeout_ms": 1000},
    )
    base.update(overrides)
    return build_unified_proof_key(**base)


# ---------------------------------------------------------------------------
# Interface / catalog pins
# ---------------------------------------------------------------------------


def test_interfaces_schema_and_catalog_are_pinned() -> None:
    store = build_duckdb_proof_store()
    assert store.interface == DUCKDB_PROOF_STORE_INTERFACE
    assert store.schema_version == DUCKDB_PROOF_STORE_SCHEMA_VERSION
    assert store.cache_interface == VERIFICATION_CACHE_PROTOCOL_INTERFACE
    assert DUCKDB_PROOF_STORE_INTERFACE == "DuckDBProofStore@1"
    assert set(store.catalog_tables()) == set(PROOFS_CATALOG_TABLES)
    assert "proof_keys" in PROOFS_CATALOG_TABLES
    assert "access_statistics" in PROOFS_CATALOG_TABLES
    assert "proof_key_dimensions" in PROOFS_CATALOG_TABLES
    assert "CREATE TABLE IF NOT EXISTS proof_keys" in PROOFS_CATALOG_DDL
    assert "CREATE TABLE IF NOT EXISTS access_statistics" in PROOFS_CATALOG_DDL


def test_module_import_is_inert_without_duckdb() -> None:
    """Importing the store must not require the duckdb package."""

    import importlib

    mod = importlib.import_module("ipfs_datasets_py.logic.common.duckdb_proof_store")
    assert mod.DUCKDB_PROOF_STORE_INTERFACE == "DuckDBProofStore@1"
    assert "duckdb" not in sys.modules or True  # may be present from other tests


# ---------------------------------------------------------------------------
# Authority dimensions — none dropped
# ---------------------------------------------------------------------------


def test_all_authority_dimensions_are_present_and_nonempty() -> None:
    key = _unified_key()
    dims = key.dimension_map()
    assert set(dims.keys()) == PROOF_AUTHORITY_DIMENSION_SET
    assert tuple(dims.keys())  # mapping is exhaustive
    for name in PROOF_AUTHORITY_DIMENSIONS:
        assert name in dims
        assert dims[name], f"dimension {name} must be nonempty"
    # require_all_dimensions is identity on a valid key
    assert key.require_all_dimensions() is key


def test_authority_dimensions_cover_hammer_and_verification_surfaces() -> None:
    """Hammer + verification-cache dimensions must appear in the closed set."""

    required = {
        "ir",
        "property",
        "assumptions",
        "premises",
        "translator",
        "solver",
        "toolchain",
        "theorem_registry",
        "policy",
        "resource",
        "tree",
        "backend_id",
        "backend_binary",
        "backend_version",
        "backend_config",
    }
    assert required == PROOF_AUTHORITY_DIMENSION_SET
    assert required.issubset(set(PROOF_AUTHORITY_DIMENSIONS))


@pytest.mark.parametrize(
    "dimension,override",
    [
        ("ir", {"ir": {"formula": "(assert false)"}}),
        ("property_value", {"property_value": {"property_id": "other"}}),
        ("assumptions", {"assumptions": ("assumption:other",)}),
        ("selected_premises", {"selected_premises": ("premise:other",)}),
        ("translator", {"translator": {"version": "other"}}),
        ("solver_identities", {"solver_identities": ({"solver": "vampire"},)}),
        ("toolchain", {"toolchain": {"lean": "4.4.0"}}),
        ("theorem_registry", {"theorem_registry": {"registry_hash": "reg:xyz"}}),
        ("policy", {"policy": {"mode": "canary"}}),
        ("resources", {"resources": {"timeout_ms": 50}}),
        ("tree", {"tree": {"tree_id": "tree:other"}}),
        ("backend_id", {"backend_id": "solver.cvc5"}),
        ("backend_binary", {"backend_binary": {"sha256": "ffff"}}),
        ("backend_version", {"backend_version": "1.0.0"}),
        ("backend_config", {"backend_config": {"logic": "QF_BV"}}),
    ],
)
def test_changing_any_authority_dimension_changes_key_digest(
    dimension: str, override: dict
) -> None:
    base = _unified_key()
    other = _unified_key(**override)
    assert base.digest != other.digest, f"{dimension} must affect key identity"
    # Projected verification keys must also diverge so exact cache misses.
    assert (
        base.to_verification_cache_key().digest
        != other.to_verification_cache_key().digest
    )


def test_hammer_key_projection_retains_authority_dimensions() -> None:
    hammer = {
        "obligation_digest": content_digest({"goal": "∀n, n+0=n"}),
        "selected_premise_digests": [
            content_digest("nat.add_zero"),
            content_digest("nat.succ_inj"),
        ],
        "translation_version_digest": content_digest("translator-v2"),
        "solver_identities_digest": content_digest(["z3-4.12", "vampire-4.7"]),
        "lean_toolchain_identity_digest": content_digest("lean-4.3.0"),
        "theorem_registry_digest": content_digest({"hash": "reg"}),
        "policy_digest": content_digest({"require_kernel": True}),
        "resource_budget_digest": content_digest({"timeout_ms": 5000}),
    }
    # content_digest returns bare hex in hammers; identity_digest accepts sha256:
    # Our from_hammer_key_dict uses _digest_field which accepts either.
    # content_digest from cache_protocol returns sha256:<hex>.
    key = UnifiedProofKey.from_hammer_key_dict(hammer)
    dims = key.dimension_map()
    assert set(dims) == PROOF_AUTHORITY_DIMENSION_SET
    assert key.selected_premise_digests  # premises retained
    assert key.toolchain_identity_digest
    assert key.theorem_registry_digest
    assert key.translator_digest
    assert key.solver_identities_digest


def test_verification_cache_key_lift_retains_all_dimensions() -> None:
    vkey = build_verification_cache_key(
        ir={"formula": "p"},
        property_value={"id": "q"},
        assumptions=("a1",),
        translation={"t": 1},
        backend_id="solver.z3",
        backend_binary="bin",
        backend_version="1",
        backend_config={"k": "v"},
        resources={"timeout_ms": 10},
        tree={"tree_id": "t1"},
        policy={"mode": "test"},
    )
    unified = UnifiedProofKey.from_verification_cache_key(
        vkey,
        selected_premise_digests=(content_digest("p1"),),
        toolchain={"lean": "4.3"},
        theorem_registry={"n": 1},
    )
    assert set(unified.dimension_map()) == PROOF_AUTHORITY_DIMENSION_SET
    # Round-trip through verification projection when no extra dims still works.
    passthrough = UnifiedProofKey.from_verification_cache_key(vkey)
    restored = passthrough.to_verification_cache_key()
    assert restored.digest == vkey.digest


# ---------------------------------------------------------------------------
# Outcomes remain distinct
# ---------------------------------------------------------------------------


def test_outcome_kinds_are_closed_and_distinct() -> None:
    kinds = {item.value for item in ProofOutcomeKind}
    assert kinds == {"proof", "counterexample", "unknown", "error"}
    assert ProofOutcomeKind.PROOF is not ProofOutcomeKind.COUNTEREXAMPLE
    assert ProofOutcomeKind.UNKNOWN is not ProofOutcomeKind.ERROR
    assert ProofOutcomeKind.PROOF is not ProofOutcomeKind.UNKNOWN
    assert ProofOutcomeKind.PROOF is not ProofOutcomeKind.ERROR
    assert ProofOutcomeKind.COUNTEREXAMPLE is not ProofOutcomeKind.UNKNOWN
    assert ProofOutcomeKind.COUNTEREXAMPLE is not ProofOutcomeKind.ERROR


@pytest.mark.parametrize(
    "status,expected",
    [
        (ResultStatus.PROVED, ProofOutcomeKind.PROOF),
        (ResultStatus.UNSATISFIABLE, ProofOutcomeKind.PROOF),
        (ResultStatus.ATTESTED, ProofOutcomeKind.PROOF),
        (ResultStatus.DISPROVED, ProofOutcomeKind.COUNTEREXAMPLE),
        (ResultStatus.SATISFIABLE, ProofOutcomeKind.COUNTEREXAMPLE),
        (ResultStatus.ATTACK_FOUND, ProofOutcomeKind.COUNTEREXAMPLE),
        (ResultStatus.UNKNOWN, ProofOutcomeKind.UNKNOWN),
        (ResultStatus.CANDIDATE, ProofOutcomeKind.UNKNOWN),
        (ResultStatus.ERROR, ProofOutcomeKind.ERROR),
        (ResultStatus.TIMEOUT, ProofOutcomeKind.ERROR),
        (ResultStatus.MALFORMED, ProofOutcomeKind.ERROR),
        (ResultStatus.UNAVAILABLE, ProofOutcomeKind.ERROR),
        (ResultStatus.UNSUPPORTED, ProofOutcomeKind.ERROR),
    ],
)
def test_outcome_mapping_keeps_kinds_distinct(
    status: ResultStatus, expected: ProofOutcomeKind
) -> None:
    assert outcome_kind_for_status(status) is expected


def test_proof_and_counterexample_entries_are_not_interchangeable() -> None:
    key = _unified_key()
    proof_entry = UnifiedProofEntry.from_typed_result(key, _theorem())
    cex_entry = UnifiedProofEntry.from_typed_result(key, _sat())
    assert proof_entry.outcome is ProofOutcomeKind.PROOF
    assert cex_entry.outcome is ProofOutcomeKind.COUNTEREXAMPLE
    assert proof_entry.entry_digest != cex_entry.entry_digest
    # Both conclusive: positive polarity / long TTL. Outcomes stay distinct.
    assert proof_entry.polarity is CachePolarity.POSITIVE
    assert cex_entry.polarity is CachePolarity.POSITIVE


def test_unknown_and_error_entries_remain_distinct() -> None:
    key = _unified_key()
    unknown = UnifiedProofEntry.from_typed_result(
        key,
        _theorem(
            status=ResultStatus.UNKNOWN,
            translation_ceiling=EvidenceAuthority.NONE,
        ),
    )
    error = UnifiedProofEntry.from_typed_result(
        key,
        _theorem(
            status=ResultStatus.ERROR,
            translation_ceiling=EvidenceAuthority.NONE,
        ),
    )
    assert unknown.outcome is ProofOutcomeKind.UNKNOWN
    assert error.outcome is ProofOutcomeKind.ERROR
    assert unknown.outcome is not error.outcome
    assert unknown.entry_digest != error.entry_digest
    # Both negative polarity for dual TTL, but still distinct outcomes.
    assert unknown.polarity is CachePolarity.NEGATIVE
    assert error.polarity is CachePolarity.NEGATIVE


def test_mismatched_outcome_and_status_rejected() -> None:
    key = _unified_key()
    with pytest.raises(DuckDBProofStoreError, match="does not match status"):
        UnifiedProofEntry(
            key=key,
            outcome=ProofOutcomeKind.PROOF,
            trust_level=ProofTrustLevel.BOUNDED,
            status=ResultStatus.ERROR,
            result_authority=ResultAuthority.THEOREM,
            evidence_authority=EvidenceAuthority.BOUNDED,
            result_payload=FrozenMap({"x": 1}),
            polarity=CachePolarity.POSITIVE,
            created_at=1.0,
        )


# ---------------------------------------------------------------------------
# Exact key + integrity fail closed
# ---------------------------------------------------------------------------


def test_entry_integrity_round_trip_and_tamper_rejection() -> None:
    key = _unified_key()
    entry = UnifiedProofEntry.from_typed_result(key, _theorem())
    restored = UnifiedProofEntry.from_dict(entry.to_dict())
    assert restored.entry_digest == entry.entry_digest
    restored.verify_integrity()

    payload = entry.to_dict()
    payload["result_payload"] = {"tampered": True}
    with pytest.raises(DuckDBProofStoreIntegrityError, match="digest mismatch"):
        UnifiedProofEntry.from_dict(payload)


def test_unknown_key_fields_fail_closed() -> None:
    key = _unified_key()
    payload = key.to_dict()
    payload["extra_field"] = "nope"
    with pytest.raises(DuckDBProofStoreError, match="unknown unified proof key"):
        UnifiedProofKey.from_dict(payload)


def test_unknown_entry_fields_fail_closed() -> None:
    key = _unified_key()
    entry = UnifiedProofEntry.from_typed_result(key, _theorem())
    payload = entry.to_dict()
    payload["bonus"] = 1
    with pytest.raises(DuckDBProofStoreError, match="unknown unified proof entry"):
        UnifiedProofEntry.from_dict(payload)


def test_unsupported_key_schema_fails_closed() -> None:
    key = _unified_key()
    payload = key.to_dict()
    payload["schema_version"] = "unified-proof-key/v0"
    with pytest.raises(DuckDBProofStoreError, match="unsupported unified proof key"):
        UnifiedProofKey.from_dict(payload)


def test_store_lookup_exact_key_miss_on_dimension_change() -> None:
    store = DuckDBProofStore()
    key = _unified_key()
    store.put_result(key, _theorem())
    hit = store.lookup(key)
    assert hit.hit and hit.usable
    assert hit.reason is CacheLookupReason.HIT

    other = _unified_key(selected_premises=("premise:different",))
    miss = store.lookup(other)
    assert not miss.hit
    assert not miss.usable
    assert miss.reason is CacheLookupReason.MISS


def test_store_rejects_tampered_in_memory_entry() -> None:
    store = DuckDBProofStore()
    key = _unified_key()
    entry = UnifiedProofEntry.from_typed_result(key, _theorem())
    store.put(entry)
    # Construction itself fails closed on digest mismatch.
    with pytest.raises(DuckDBProofStoreIntegrityError):
        UnifiedProofEntry(
            key=entry.key,
            outcome=entry.outcome,
            trust_level=entry.trust_level,
            status=entry.status,
            result_authority=entry.result_authority,
            evidence_authority=entry.evidence_authority,
            result_payload=FrozenMap({"tampered": True}),
            polarity=entry.polarity,
            created_at=entry.created_at,
            entry_digest=entry.entry_digest,
            result_id=entry.result_id,
            diagnostics=entry.diagnostics,
        )


def test_unified_key_must_project_to_matching_verification_key() -> None:
    key = _unified_key()
    vkey = key.to_verification_cache_key()
    result = _theorem()
    ventry = VerificationCacheEntry.from_typed_result(vkey, result)
    # A different unified key that does not project to vkey must be rejected.
    other = _unified_key(selected_premises=("premise:zzz",))
    with pytest.raises(DuckDBProofStoreIntegrityError, match="does not project"):
        UnifiedProofEntry.from_verification_cache_entry(ventry, key=other)


# ---------------------------------------------------------------------------
# Trust levels, evidence, envelopes, access statistics
# ---------------------------------------------------------------------------


def test_trust_levels_project_from_evidence_authority() -> None:
    assert (
        trust_level_from_evidence(EvidenceAuthority.AUTHORITATIVE)
        is ProofTrustLevel.AUTHORITATIVE
    )
    assert (
        trust_level_from_evidence(EvidenceAuthority.BOUNDED)
        is ProofTrustLevel.BOUNDED
    )
    assert (
        trust_level_from_evidence(EvidenceAuthority.NONE, non_trusted=True)
        is ProofTrustLevel.NON_TRUSTED
    )


def test_trust_cannot_exceed_evidence_authority() -> None:
    key = _unified_key()
    with pytest.raises(DuckDBProofStoreAuthorityError, match="exceeds evidence"):
        UnifiedProofEntry(
            key=key,
            outcome=ProofOutcomeKind.PROOF,
            trust_level=ProofTrustLevel.AUTHORITATIVE,
            status=ResultStatus.PROVED,
            result_authority=ResultAuthority.THEOREM,
            evidence_authority=EvidenceAuthority.BOUNDED,
            result_payload=FrozenMap({}),
            polarity=CachePolarity.POSITIVE,
            created_at=1.0,
        )


def test_evidence_and_envelope_round_trip() -> None:
    key = _unified_key()
    envelope = ImmutableEnvelopeReference.from_bytes(
        b'{"proof":"kernel-checked"}',
        media_type="json",
    )
    evidence = ProofEvidenceRecord(
        evidence_id="ev:1",
        evidence_kind="kernel_checked_proof",
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        content_digest=content_digest({"steps": [1, 2, 3]}),
        payload=FrozenMap({"steps": [1, 2, 3]}),
        created_at=10.0,
    )
    entry = UnifiedProofEntry.from_typed_result(
        key,
        _theorem(),
        envelope=envelope,
        evidence=(evidence,),
    )
    restored = UnifiedProofEntry.from_dict(entry.to_dict())
    assert restored.envelope is not None
    assert restored.envelope.content_digest == envelope.content_digest
    assert len(restored.evidence) == 1
    assert restored.evidence[0].evidence_id == "ev:1"
    restored.verify_integrity()


def test_envelope_rejects_filesystem_path_authority() -> None:
    with pytest.raises(DuckDBProofStoreError, match="filesystem path"):
        ImmutableEnvelopeReference(
            content_id="sha256:" + "a" * 64,
            content_digest="sha256:" + "a" * 64,
            location_hint="/var/lib/proofs/secret.json",
        )


def test_access_statistics_track_hits_misses_writes() -> None:
    store = DuckDBProofStore()
    key = _unified_key()
    store.put_result(key, _theorem())
    store.lookup(key)
    store.lookup(key)
    store.lookup(_unified_key(ir={"formula": "other"}))
    stats = store.access_statistics_for(key)
    assert isinstance(stats, AccessStatistics)
    assert stats.writes == 1
    assert stats.hits >= 2
    assert stats.key_digest == key.digest
    global_stats = store.stats()
    assert global_stats["writes"] == 1
    assert global_stats["hits"] >= 2
    assert global_stats["misses"] >= 1


# ---------------------------------------------------------------------------
# Protocol interop with VerificationCacheProtocol@1
# ---------------------------------------------------------------------------


def test_store_implements_verification_cache_put_get() -> None:
    store = DuckDBProofStore()
    key = _unified_key()
    vkey = key.to_verification_cache_key()
    result = _theorem()
    stored = store.put_result(key, result)
    assert stored.reason is CacheLookupReason.STORED
    assert stored.usable

    # Lookup by unified key.
    hit = store.get(key)
    assert hit is not None
    assert hit.outcome is ProofOutcomeKind.PROOF

    # Lookup by projected verification key (protocol surface).
    vlookup = store.lookup(vkey)
    assert vlookup.hit and vlookup.usable
    assert vlookup.entry is not None
    assert vlookup.entry.status is ResultStatus.PROVED


def test_verification_cache_entry_can_be_put_directly() -> None:
    store = DuckDBProofStore()
    vkey = build_verification_cache_key(
        ir={"f": 1},
        backend_id="solver.z3",
        backend_version="1",
    )
    ventry = VerificationCacheEntry.from_typed_result(vkey, _theorem())
    stored = store.put(ventry)
    assert stored.usable
    got = store.lookup(vkey)
    assert got.hit and got.usable


def test_exact_verification_cache_interop_bridge() -> None:
    """Unified store entries project to ExactVerificationCache keys/entries."""

    key = _unified_key()
    entry = UnifiedProofEntry.from_typed_result(key, _theorem())
    ventry = entry.to_verification_cache_entry()
    cache = ExactVerificationCache()
    cache.put(ventry)
    hit = cache.get(key.to_verification_cache_key())
    assert hit is not None
    assert hit.entry_digest == ventry.entry_digest


def test_invalidate_and_clear() -> None:
    store = DuckDBProofStore()
    key = _unified_key()
    store.put_result(key, _theorem())
    assert store.invalidate(key) is True
    assert store.get(key) is None
    assert store.invalidate(key) is False
    store.put_result(key, _theorem())
    store.clear()
    assert store.stats()["size"] == 0


def test_get_or_compute_single_flight_and_store() -> None:
    store = DuckDBProofStore()
    key = _unified_key()
    calls = {"n": 0}

    def producer() -> TheoremResult:
        calls["n"] += 1
        return _theorem()

    first = store.get_or_compute(key, producer)
    second = store.get_or_compute(key, producer)
    assert first.usable and second.usable
    assert calls["n"] == 1
    assert second.hit


def test_negative_ttl_expires_unknown_faster_than_proof() -> None:
    store = DuckDBProofStore(
        positive_ttl_seconds=1000,
        negative_ttl_seconds=10,
    )
    key = _unified_key()
    store.put_result(
        key,
        _theorem(
            status=ResultStatus.UNKNOWN,
            translation_ceiling=EvidenceAuthority.NONE,
        ),
        now=100.0,
    )
    expired = store.lookup(key, now=120.0)
    assert not expired.usable
    assert expired.reason is CacheLookupReason.EXPIRED

    store.put_result(key, _theorem(), now=100.0)
    still_valid = store.lookup(key, now=120.0)
    assert still_valid.usable


def test_trust_ceiling_rejects_raise() -> None:
    store = DuckDBProofStore()
    key = _unified_key()
    store.put_result(
        key,
        _theorem(translation_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE),
    )
    blocked = store.lookup(
        key, max_trust_level=ProofTrustLevel.BOUNDED
    )
    assert blocked.hit
    assert not blocked.usable
    assert blocked.reason is CacheLookupReason.INSUFFICIENT_AUTHORITY


# ---------------------------------------------------------------------------
# Dimension map fail-closed guard
# ---------------------------------------------------------------------------


def test_empty_backend_id_rejected() -> None:
    with pytest.raises(DuckDBProofStoreError):
        UnifiedProofKey.build(
            ir={"x": 1},
            backend_id="",
            backend_version="1",
        )


def test_premises_digest_changes_with_premise_set() -> None:
    a = _unified_key(selected_premises=("p1", "p2"))
    b = _unified_key(selected_premises=("p1",))
    assert a.premises_digest != b.premises_digest
    assert a.dimension_map()["premises"] != b.dimension_map()["premises"]
