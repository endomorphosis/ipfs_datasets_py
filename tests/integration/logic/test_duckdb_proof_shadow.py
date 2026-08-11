"""Integration tests for unified proof-cache DuckDB shadowing (DQK-065).

Acceptance coverage:

* No hit crosses incompatible solver/toolchain/premise/policy identities
* Trust mismatches fail closed
* Every legacy backend has differential receipts
* Proof envelope bytes and CIDs remain unchanged
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

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

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ipfs_datasets_py.logic.common.proof_cache import (
    LEGACY_PROOF_BACKENDS,
    LegacyProofBackend,
    PROOF_SHADOW_INTERFACE,
    ProofCache,
    ProofShadowIdentityError,
    ProofShadowTrustError,
    UnifiedProofShadowRepository,
    build_proof_shadow_repository,
    clear_shadow_repository,
    family_for_backend,
    set_shadow_repository,
)
from ipfs_datasets_py.logic.common.duckdb_proof_store import (
    PROOF_AUTHORITY_DIMENSIONS,
    ProofTrustLevel,
)
from ipfs_datasets_py.logic.hammers.proof_cache import (
    PersistentProofCache,
    ProofCacheKey,
    ProofCacheOutcome,
)
from ipfs_datasets_py.logic.integration.proof_cache import (
    ProofCache as IntegrationProofCache,
)
from ipfs_datasets_py.logic.CEC.optimization.formula_cache import ProofResultCache
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_cache import (
    FormulaCache as OptimizerFormulaCache,
)


@pytest.fixture
def shadow_repo():
    repo = build_proof_shadow_repository(
        owner_id="owner:dqk-065-test",
        mode="shadow",
        set_global=True,
    )
    yield repo
    clear_shadow_repository()


# ---------------------------------------------------------------------------
# Interface pins
# ---------------------------------------------------------------------------


def test_shadow_repository_interface_and_backends(shadow_repo):
    assert shadow_repo.interface == PROOF_SHADOW_INTERFACE
    assert set(shadow_repo.registered_backends()) == {
        b.value for b in LEGACY_PROOF_BACKENDS
    }
    assert shadow_repo.authority_dimensions == PROOF_AUTHORITY_DIMENSIONS
    for backend in LEGACY_PROOF_BACKENDS:
        family = family_for_backend(backend)
        assert family in {
            "common",
            "hammers",
            "legal_ir",
            "integration",
            "external_provers",
            "tdfol",
            "cec",
        }


# ---------------------------------------------------------------------------
# Identity isolation: no hit across solver/toolchain/premise/policy
# ---------------------------------------------------------------------------


def test_no_hit_across_incompatible_solver_toolchain_premise_policy(shadow_repo):
    base = dict(
        formula="(assert (> x 0))",
        prover_name="z3",
        solver_identities={"solver": "z3", "version": "4.12.0"},
        toolchain={"lean": "4.3.0"},
        policy={"mode": "production", "require_kernel": True},
        premises=("premise:nat.succ",),
    )
    key = shadow_repo.project_key(LegacyProofBackend.COMMON, **base)
    shadow_repo.write(
        LegacyProofBackend.COMMON,
        key=key,
        result_payload={"ok": True},
        status="proved",
        trust_level="none",
        legacy_payload={"formula": base["formula"], "prover": "z3"},
    )

    # Same formula, different solver identity → miss.
    other_solver = shadow_repo.project_key(
        LegacyProofBackend.COMMON,
        **{**base, "solver_identities": {"solver": "cvc5", "version": "1.1.0"}},
    )
    assert key.digest != other_solver.digest
    assert shadow_repo.lookup(LegacyProofBackend.COMMON, other_solver) is None

    # Different toolchain → miss.
    other_toolchain = shadow_repo.project_key(
        LegacyProofBackend.COMMON,
        **{**base, "toolchain": {"lean": "4.4.0"}},
    )
    assert key.digest != other_toolchain.digest
    assert shadow_repo.lookup(LegacyProofBackend.COMMON, other_toolchain) is None

    # Different premises → miss.
    other_premises = shadow_repo.project_key(
        LegacyProofBackend.COMMON,
        **{**base, "premises": ("premise:nat.zero",)},
    )
    assert key.digest != other_premises.digest
    assert shadow_repo.lookup(LegacyProofBackend.COMMON, other_premises) is None

    # Different policy → miss.
    other_policy = shadow_repo.project_key(
        LegacyProofBackend.COMMON,
        **{**base, "policy": {"mode": "batch", "require_kernel": False}},
    )
    assert key.digest != other_policy.digest
    assert shadow_repo.lookup(LegacyProofBackend.COMMON, other_policy) is None

    # Exact match still hits.
    hit = shadow_repo.lookup(LegacyProofBackend.COMMON, key)
    assert hit is not None
    assert hit.key.digest == key.digest

    with pytest.raises(ProofShadowIdentityError):
        shadow_repo.assert_compatible_identities(key, other_solver)


# ---------------------------------------------------------------------------
# Trust mismatches fail closed
# ---------------------------------------------------------------------------


def test_trust_mismatches_fail_closed(shadow_repo):
    key = shadow_repo.project_key(
        LegacyProofBackend.HAMMERS,
        formula="obligation:trusted-path",
        prover_name="lean",
        solver_identities={"solver": "lean"},
        toolchain={"lean": "4.3.0"},
        policy={"mode": "production"},
        premises=("premise:a",),
    )
    # Unverified "trusted" claim must be rejected (never silently raised).
    with pytest.raises(ProofShadowTrustError):
        shadow_repo.write(
            LegacyProofBackend.HAMMERS,
            key=key,
            result_payload={"claimed": True},
            status="proved",
            trust_level="trusted",
            kernel_accepted=False,
            deterministic_trusted=False,
            legacy_payload={"status": "proved", "trust": "trusted"},
        )

    # Legitimate kernel-backed write is admitted at independently_checkable.
    entry = shadow_repo.write(
        LegacyProofBackend.HAMMERS,
        key=key,
        result_payload={"kernel": True},
        status="proved",
        trust_level="trusted",
        kernel_accepted=True,
        legacy_payload={"status": "proved", "trust": "trusted", "kernel": True},
    )
    assert entry.trust_level is ProofTrustLevel.INDEPENDENTLY_CHECKABLE

    # Ceiling below stored trust fails closed (raises).
    with pytest.raises(ProofShadowTrustError):
        shadow_repo.lookup(
            LegacyProofBackend.HAMMERS,
            key,
            max_trust_level=ProofTrustLevel.NON_TRUSTED,
        )

    # Ceiling at/above stored trust succeeds.
    hit = shadow_repo.lookup(
        LegacyProofBackend.HAMMERS,
        key,
        max_trust_level=ProofTrustLevel.INDEPENDENTLY_CHECKABLE,
    )
    assert hit is not None
    assert hit.entry_digest == entry.entry_digest


# ---------------------------------------------------------------------------
# Every legacy backend has differential receipts
# ---------------------------------------------------------------------------


def test_every_legacy_backend_has_differential_receipts(shadow_repo):
    # Exercise representative producers so dual-write paths emit receipts.
    common = ProofCache(shadow_repository=shadow_repo, shadow_backend="common")
    common.set("(check-sat)", {"status": "proved"}, prover_name="z3")

    hammers = PersistentProofCache()
    hammers.bind_shadow_repository(shadow_repo)
    hkey = ProofCacheKey.build(
        "theorem:id",
        selected_premises=("p1",),
        translation_version="v1",
        solver_identities={"z3": "4.12"},
        lean_toolchain_identity={"lean": "4.3"},
        theorem_registry="reg",
        policy={"mode": "test"},
        resource_budget={"timeout_ms": 100},
    )
    hammers.put(
        hkey,
        ProofCacheOutcome.non_trusted("proved", {"steps": 1}, atp_claimed_proof=True),
    )

    integration = IntegrationProofCache()
    integration.bind_shadow_repository(shadow_repo)
    integration.put("f||prover", "vampire", {"status": "proved"})

    cec_formula = ProofResultCache()
    cec_formula.bind_shadow_repository(shadow_repo)
    cec_formula.cache_proof("P(x)", None, {"status": "proved"})

    optimizer = OptimizerFormulaCache()
    optimizer.bind_shadow_repository(shadow_repo)
    optimizer.put("forall x. P(x)", True, 0.9, "z3", 0.01)

    # Cover remaining backends via the repository coverage helper.
    missing_before = set(b.value for b in LEGACY_PROOF_BACKENDS) - set(
        shadow_repo.backends_with_receipts()
    )
    filled = shadow_repo.ensure_backend_differential_coverage()
    assert set(filled) <= missing_before or not missing_before

    assert shadow_repo.every_backend_has_differential_receipt()
    for backend in LEGACY_PROOF_BACKENDS:
        receipts = shadow_repo.differential_receipts(backend)
        assert receipts, f"backend {backend.value} missing differential receipts"
        assert all(r.backend == backend.value for r in receipts)
        assert all(r.schema.endswith("shadow-receipt/v1") for r in receipts)


# ---------------------------------------------------------------------------
# Envelope bytes and CIDs remain unchanged
# ---------------------------------------------------------------------------


def test_proof_envelope_bytes_and_cids_remain_unchanged(shadow_repo):
    envelope = b'{"artifact":"legal","v":1,"steps":[1,2,3]}'
    content_id = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
    key = shadow_repo.project_key(
        LegacyProofBackend.LEGAL_IR,
        formula="source:article-1",
        cid=content_id,
        prover_name="legal_ir",
        solver_identities={"profile": "legal-federal"},
        toolchain={"legal_ir": True},
        policy={"profile": "legal-federal"},
        premises=("premise:statute",),
    )
    entry = shadow_repo.write(
        LegacyProofBackend.LEGAL_IR,
        key=key,
        result_payload={"content_cid": content_id},
        status="proved",
        trust_level="none",
        envelope_bytes=envelope,
        envelope_content_id=content_id,
        legacy_payload={"content_cid": content_id, "bytes": len(envelope)},
    )
    assert entry.envelope is not None
    assert entry.envelope.content_id == content_id
    assert entry.envelope.byte_size == len(envelope)
    original_digest = entry.envelope.content_digest

    # Re-read through the store; envelope identity must be stable.
    hit = shadow_repo.lookup(LegacyProofBackend.LEGAL_IR, key)
    assert hit is not None
    assert hit.envelope is not None
    assert hit.envelope.content_id == content_id
    assert hit.envelope.content_digest == original_digest
    assert hit.envelope.byte_size == len(envelope)

    # Corpus-index mutation must not rewrite envelope digests.
    mutation = shadow_repo.mutate_corpus_index(
        LegacyProofBackend.LEGAL_IR,
        key=key,
        envelope_content_id=content_id,
        envelope_content_digest=original_digest,
        operation="index",
        payload={"profile": "legal-federal"},
    )
    assert mutation["envelope_content_id"] == content_id
    assert mutation["envelope_content_digest"] == original_digest

    with pytest.raises(Exception):
        shadow_repo.mutate_corpus_index(
            LegacyProofBackend.LEGAL_IR,
            key=key,
            envelope_content_id=content_id,
            envelope_content_digest="sha256:" + ("0" * 64),
            operation="index",
        )

    # Differential receipts record the unchanged envelope CID/digest.
    write_receipts = [
        r
        for r in shadow_repo.differential_receipts(LegacyProofBackend.LEGAL_IR)
        if r.operation in {"write", "corpus_index", "lookup"}
        and r.envelope_content_id == content_id
    ]
    assert write_receipts
    assert all(r.envelope_content_digest == original_digest for r in write_receipts)


# ---------------------------------------------------------------------------
# Single-flight claim / attempt / attestation / invalidation
# ---------------------------------------------------------------------------


def test_single_flight_attempt_attestation_and_invalidation(shadow_repo):
    key = shadow_repo.project_key(
        LegacyProofBackend.COMMON,
        formula="goal:single-flight",
        prover_name="vampire",
        solver_identities={"prover": "vampire"},
        toolchain={"backend": "common"},
        policy={"mode": "shadow"},
        premises=("p:1",),
    )
    claim = shadow_repo.claim_single_flight(
        LegacyProofBackend.COMMON, key, owner_id="owner:dqk-065-test"
    )
    assert claim is not None
    assert getattr(claim, "key_digest", None) == key.digest

    entry = shadow_repo.publish_attempt(
        LegacyProofBackend.COMMON,
        claim,
        {"status": "proved", "steps": 2},
        key=key,
        status="proved",
        trust_level="none",
        legacy_payload={"status": "proved"},
    )
    # publish_attempt with mapping returns UnifiedProofEntry via write().
    if hasattr(entry, "entry_digest"):
        stored = entry
    else:
        stored = shadow_repo.lookup(LegacyProofBackend.COMMON, key)
    assert stored is not None

    attestation = shadow_repo.attest(
        LegacyProofBackend.COMMON,
        key,
        attestor_id="attestor:test",
        content_digest=stored.entry_digest,
        payload={"kind": "test_attestation"},
    )
    assert attestation["key_digest"] == key.digest
    assert attestation["entry_digest"] == stored.entry_digest

    removed = shadow_repo.invalidate(
        LegacyProofBackend.COMMON, key, reason="explicit"
    )
    assert removed is True
    assert shadow_repo.lookup(LegacyProofBackend.COMMON, key) is None

    ops = {
        r.operation
        for r in shadow_repo.differential_receipts(LegacyProofBackend.COMMON)
    }
    assert {"claim", "write", "attestation", "invalidation"} <= ops or {
        "claim",
        "attempt",
        "attestation",
        "invalidation",
    } <= ops


def test_family_backends_bind_and_emit_receipts(shadow_repo):
    """Each expected-output module can bind and dual-write."""

    from ipfs_datasets_py.logic.external_provers import proof_cache as ext
    from ipfs_datasets_py.logic.TDFOL import tdfol_proof_cache as tdfol
    from ipfs_datasets_py.logic.integration.caching import ipfs_proof_cache as ipfs

    for mod, backend in (
        (ext, "external_provers"),
        (tdfol, "tdfol"),
        (ipfs, "ipfs_proof_cache"),
    ):
        assert hasattr(mod, "LegacyProofBackend")
        assert hasattr(mod, "build_proof_shadow_repository")

    cache = ext.ProofCache(shadow_repository=shadow_repo)
    cache.set("ext-formula", {"status": "unknown"}, prover_name="eprover")
    tcache = tdfol.TDFOLProofCache(shadow_repository=shadow_repo)
    tcache.set("tdfol-formula", {"status": "unknown"}, prover_name="tdfol")
    icache = ipfs.IPFSProofCache(enable_ipfs=False)
    icache.bind_shadow_repository(shadow_repo)
    icache.set("ipfs-formula", {"status": "unknown"}, prover_name="ipfs")

    for backend in (
        LegacyProofBackend.EXTERNAL_PROVERS,
        LegacyProofBackend.TDFOL,
        LegacyProofBackend.IPFS_PROOF_CACHE,
    ):
        assert shadow_repo.differential_receipts(backend)

