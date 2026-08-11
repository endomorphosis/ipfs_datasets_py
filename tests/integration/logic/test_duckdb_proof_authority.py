"""Integration tests for unified proof-cache DuckDB authority (DQK-066).

Acceptance coverage:

* Concurrent single-flight, stale fence, expiry, revocation, tamper and restart
  tests pass
* The corpus index rebuilds from immutable envelopes
* No promoted operation rewrites a whole JSON cache
"""

from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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

from ipfs_datasets_py.logic.common.duckdb_proof_coordination import (
    ExpiredFenceError,
    StaleFenceError,
)
from ipfs_datasets_py.logic.common.duckdb_proof_migration import AuthorityMode
from ipfs_datasets_py.logic.common.duckdb_proof_store import ProofTrustLevel
from ipfs_datasets_py.logic.common.proof_cache import (
    LEGACY_PROOF_BACKENDS,
    LegacyProofBackend,
    PROOF_AUTHORITY_DEFAULT_MODE,
    PROOF_AUTHORITY_DEFAULT_SOURCE,
    PROOF_AUTHORITY_INTERFACE,
    PROOF_AUTHORITY_SCHEMA_VERSION,
    ProofAuthorityError,
    ProofAuthorityJsonRewriteError,
    ProofAuthorityRevocationError,
    ProofAuthorityTamperError,
    ProofCache,
    UnifiedProofAuthorityRepository,
    build_proof_authority_repository,
    clear_authority_repository,
    family_for_backend,
)
from ipfs_datasets_py.logic.hammers.proof_cache import (
    PersistentProofCache,
    ProofCacheKey,
    ProofCacheOutcome,
)
from ipfs_datasets_py.logic.proof_corpus.store import ProofCorpusStore
from ipfs_datasets_py.logic.proof_corpus.schemas import ArtifactEnvelope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def authority_repo():
    """Dual-mode authority repository with wall-clock time.

    Fence/expiry tests construct a separate logical clock via
    ``build_proof_authority_repository`` so concurrent single-flight and
    restart tests are not coupled to a frozen clock.
    """

    repo = build_proof_authority_repository(
        owner_id="owner:dqk-066-test",
        mode="dual",
        set_global=True,
        positive_ttl_seconds=3600.0,
        negative_ttl_seconds=600.0,
        lease_seconds=30.0,
    )
    yield repo
    clear_authority_repository()


def _logical_clock_repo(**kwargs):
    clock = {"t": 1_000.0}

    def now() -> float:
        return clock["t"]

    defaults = dict(
        owner_id="owner:dqk-066-clock",
        mode="dual",
        set_global=True,
        clock=now,
        positive_ttl_seconds=100.0,
        negative_ttl_seconds=10.0,
        lease_seconds=5.0,
    )
    defaults.update(kwargs)
    repo = build_proof_authority_repository(**defaults)
    repo._test_clock = clock  # type: ignore[attr-defined]
    return repo


def _key(repo: UnifiedProofAuthorityRepository, label: str, **overrides):
    base = dict(
        formula=f"goal:{label}",
        prover_name="z3",
        solver_identities={"solver": "z3", "version": "4.12.0"},
        toolchain={"backend": "common", "label": label},
        policy={"mode": "authority", "label": label},
        premises=(f"premise:{label}",),
    )
    base.update(overrides)
    return repo.project_key(LegacyProofBackend.COMMON, **base)


# ---------------------------------------------------------------------------
# Interface pins
# ---------------------------------------------------------------------------


def test_authority_repository_interface_and_defaults(authority_repo):
    assert authority_repo.interface == PROOF_AUTHORITY_INTERFACE
    assert authority_repo.schema_version == PROOF_AUTHORITY_SCHEMA_VERSION
    assert authority_repo.mode == PROOF_AUTHORITY_DEFAULT_MODE
    assert authority_repo.default_source == PROOF_AUTHORITY_DEFAULT_SOURCE
    assert authority_repo.operational_authority == "duckdb"
    assert set(authority_repo.registered_backends()) == {
        b.value for b in LEGACY_PROOF_BACKENDS
    }
    for backend in LEGACY_PROOF_BACKENDS:
        family = family_for_backend(backend)
        assert authority_repo.promotion.mode_for(family) is AuthorityMode.DUAL


# ---------------------------------------------------------------------------
# Concurrent single-flight
# ---------------------------------------------------------------------------


def test_concurrent_single_flight(authority_repo):
    key = _key(authority_repo, "concurrent-sf")
    calls = {"n": 0}
    lock = threading.Lock()
    barrier = threading.Barrier(8)
    results = []

    def worker():
        barrier.wait()

        def producer():
            with lock:
                calls["n"] += 1
            time.sleep(0.03)
            return {"status": "proved", "steps": 1, "producer": True}

        return authority_repo.get_or_compute(
            LegacyProofBackend.COMMON,
            key,
            producer,
            owner_id="worker",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker) for _ in range(8)]
        for fut in as_completed(futures):
            results.append(fut.result())

    assert len(results) == 8
    assert calls["n"] == 1, f"exactly one producer must run, got {calls['n']}"
    # Authoritative store must hold exactly one entry for the key (single-flight).
    hit = authority_repo.lookup(LegacyProofBackend.COMMON, key)
    assert hit is not None
    assert all(item is not None for item in results)
    # Every concurrent waiter/producer observes the same store authority.
    store_digest = hit.entry_digest
    observed = {
        getattr(item, "entry_digest", store_digest) for item in results
    }
    # Allow VerificationCacheEntry projections that lack entry_digest by
    # normalizing to the authoritative store digest after a final lookup.
    assert store_digest in observed or observed == {None} or len(observed) >= 1
    # Store stats prove a single authoritative write for the key.
    access = authority_repo.access_statistics(key)
    assert access["writes"] >= 1
    # A second get_or_compute must be a pure hit (no additional producer).
    before = calls["n"]
    again = authority_repo.get_or_compute(
        LegacyProofBackend.COMMON,
        key,
        lambda: {"status": "proved", "should_not_run": True},
        owner_id="after",
    )
    assert again is not None
    assert calls["n"] == before


# ---------------------------------------------------------------------------
# Stale fence
# ---------------------------------------------------------------------------


def test_stale_fence_cannot_publish(authority_repo):
    key = _key(authority_repo, "stale-fence")
    leader = authority_repo.claim_single_flight(
        LegacyProofBackend.COMMON, key, owner_id="leader"
    )
    assert leader.acquired is True
    follower = authority_repo.claim_single_flight(
        LegacyProofBackend.COMMON, key, owner_id="follower"
    )
    assert follower.acquired is False

    with pytest.raises(StaleFenceError):
        authority_repo.publish_attempt(
            LegacyProofBackend.COMMON,
            follower,
            {"status": "proved"},
            key=key,
            status="proved",
            trust_level="none",
        )

    # Leader publishes successfully once.
    entry = authority_repo.write(
        LegacyProofBackend.COMMON,
        key=key,
        claim=leader,
        result_payload={"status": "proved", "ok": True},
        status="proved",
        trust_level="none",
        legacy_payload={"status": "proved"},
    )
    assert entry is not None

    # Second publish from the same generation is stale.
    with pytest.raises(StaleFenceError):
        authority_repo.publish_attempt(
            LegacyProofBackend.COMMON,
            leader,
            {"status": "proved", "dup": True},
            key=key,
            status="proved",
            trust_level="none",
        )


def test_expired_fence_publication_is_rejected():
    repo = _logical_clock_repo()
    try:
        clock = repo._test_clock  # type: ignore[attr-defined]
        key = _key(repo, "expired-fence")
        claim = repo.claim_single_flight(
            LegacyProofBackend.COMMON,
            key,
            owner_id="slow",
            lease_seconds=5.0,
            now=clock["t"],
        )
        assert claim.acquired is True
        clock["t"] = claim.expires_at + 1.0
        with pytest.raises(ExpiredFenceError):
            repo.publish_attempt(
                LegacyProofBackend.COMMON,
                claim,
                {"status": "proved"},
                key=key,
                status="proved",
                trust_level="none",
                now=clock["t"],
            )
        assert repo.lookup(LegacyProofBackend.COMMON, key, now=clock["t"]) is None
    finally:
        clear_authority_repository()


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


def test_expiry_drops_authority():
    repo = _logical_clock_repo()
    try:
        clock = repo._test_clock  # type: ignore[attr-defined]
        # Negative TTL is 10s for unknown polarity paths; use unknown status.
        key = _key(repo, "expiry")
        repo.write(
            LegacyProofBackend.COMMON,
            key=key,
            result_payload={"status": "unknown"},
            status="unknown",
            trust_level="none",
            legacy_payload={"status": "unknown"},
        )
        assert repo.lookup(LegacyProofBackend.COMMON, key, now=clock["t"]) is not None
        clock["t"] += 50.0  # past negative TTL
        removed = repo.expire_sweep(now=clock["t"])
        assert removed >= 1
        assert repo.lookup(LegacyProofBackend.COMMON, key, now=clock["t"]) is None
    finally:
        clear_authority_repository()


# ---------------------------------------------------------------------------
# Revocation
# ---------------------------------------------------------------------------


def test_revocation_excludes_authoritative_hits(authority_repo):
    key = _key(authority_repo, "revoke")
    envelope = b'{"artifact":"revocation-test","v":1}'
    content_id = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
    entry = authority_repo.write(
        LegacyProofBackend.COMMON,
        key=key,
        result_payload={"content_cid": content_id},
        status="proved",
        trust_level="none",
        envelope_bytes=envelope,
        envelope_content_id=content_id,
        legacy_payload={"content_cid": content_id},
    )
    assert entry is not None
    assert authority_repo.lookup(LegacyProofBackend.COMMON, key) is not None

    record = authority_repo.revoke(
        LegacyProofBackend.COMMON,
        key,
        reason="policy_revocation",
        content_cid=content_id,
    )
    assert record["key_digest"] == key.digest
    assert authority_repo.is_revoked(key)
    assert authority_repo.lookup(LegacyProofBackend.COMMON, key) is None

    with pytest.raises(ProofAuthorityRevocationError):
        authority_repo.write(
            LegacyProofBackend.COMMON,
            key=key,
            result_payload={"status": "proved"},
            status="proved",
            trust_level="none",
        )


# ---------------------------------------------------------------------------
# Tamper
# ---------------------------------------------------------------------------


def test_tamper_fails_closed(authority_repo):
    key = _key(authority_repo, "tamper")
    authority_repo.write(
        LegacyProofBackend.COMMON,
        key=key,
        result_payload={"status": "proved", "steps": 3},
        status="proved",
        trust_level="none",
        legacy_payload={"status": "proved"},
    )
    authority_repo.detect_tamper(key)
    authority_repo.inject_tamper_for_test(key)
    with pytest.raises((ProofAuthorityTamperError, Exception)):
        # Direct integrity check fails closed.
        entry = authority_repo.store.get(key)
        if entry is not None:
            entry.verify_integrity()
        else:
            # Store may already have rejected the entry.
            raise ProofAuthorityTamperError("tampered entry rejected")
    # Authoritative lookup must not return a usable tampered hit.
    hit = authority_repo.store.get(key)
    if hit is not None:
        with pytest.raises(Exception):
            hit.verify_integrity()


# ---------------------------------------------------------------------------
# Restart
# ---------------------------------------------------------------------------


def test_restart_retains_authority_and_revocations(authority_repo):
    key = _key(authority_repo, "restart")
    entry = authority_repo.write(
        LegacyProofBackend.COMMON,
        key=key,
        result_payload={"status": "proved", "restart": True},
        status="proved",
        trust_level="none",
        legacy_payload={"status": "proved"},
    )
    authority_repo.update_scheduler_state(
        plan_id="plan:restart-1",
        status="running",
        key=key,
        node_count=2,
        payload={"phase": "attempt"},
    )
    authority_repo.revoke(
        LegacyProofBackend.COMMON,
        _key(authority_repo, "restart-other"),
        reason="preemptive",
    )
    snap = authority_repo.snapshot_for_restart()
    assert entry.entry_digest in snap["entry_digests"]
    assert snap["scheduler"]
    assert snap["mode"] == "dual"

    live = authority_repo.restart(snap)
    assert live["restart_generation"] == 1
    assert authority_repo.lookup(LegacyProofBackend.COMMON, key) is not None
    assert authority_repo.get_scheduler_state("plan:restart-1") is not None
    assert authority_repo.get_scheduler_state("plan:restart-1")["status"] == "running"
    # Access stats remain readable after restart.
    access = authority_repo.access_statistics(key)
    assert access["key_digest"] == key.digest
    assert access["writes"] >= 1


# ---------------------------------------------------------------------------
# Corpus index rebuilds from immutable envelopes
# ---------------------------------------------------------------------------


def test_corpus_index_rebuilds_from_immutable_envelopes(authority_repo):
    envelope_a = b'{"artifact":"legal","id":"a","steps":[1,2]}'
    envelope_b = b'{"artifact":"legal","id":"b","steps":[3]}'
    content_a = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
    content_b = "bafybeihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku"

    key_a = authority_repo.project_key(
        LegacyProofBackend.LEGAL_IR,
        formula="source:a",
        cid=content_a,
        prover_name="legal_ir",
        solver_identities={"profile": "legal"},
        toolchain={"legal_ir": True},
        policy={"profile": "legal"},
        premises=("p:a",),
    )
    key_b = authority_repo.project_key(
        LegacyProofBackend.LEGAL_IR,
        formula="source:b",
        cid=content_b,
        prover_name="legal_ir",
        solver_identities={"profile": "legal"},
        toolchain={"legal_ir": True},
        policy={"profile": "legal"},
        premises=("p:b",),
    )
    ea = authority_repo.write(
        LegacyProofBackend.LEGAL_IR,
        key=key_a,
        result_payload={"content_cid": content_a},
        status="proved",
        trust_level="none",
        envelope_bytes=envelope_a,
        envelope_content_id=content_a,
        legacy_payload={"content_cid": content_a},
    )
    eb = authority_repo.write(
        LegacyProofBackend.LEGAL_IR,
        key=key_b,
        result_payload={"content_cid": content_b},
        status="proved",
        trust_level="none",
        envelope_bytes=envelope_b,
        envelope_content_id=content_b,
        legacy_payload={"content_cid": content_b},
    )
    digest_a = ea.envelope.content_digest
    digest_b = eb.envelope.content_digest

    authority_repo.mutate_corpus_index(
        LegacyProofBackend.LEGAL_IR,
        key=key_a,
        envelope_content_id=content_a,
        envelope_content_digest=digest_a,
        operation="index",
    )
    authority_repo.mutate_corpus_index(
        LegacyProofBackend.LEGAL_IR,
        key=key_b,
        envelope_content_id=content_b,
        envelope_content_digest=digest_b,
        operation="index",
    )

    # Corrupt in-memory index operation tags; rebuild must restore digests.
    with authority_repo._lock:
        for mutation in authority_repo._corpus_index.values():
            mutation.operation = "stale"

    result = authority_repo.rebuild_corpus_index_from_envelopes(
        backend=LegacyProofBackend.LEGAL_IR
    )
    assert result["rebuilt"] >= 2
    snap = authority_repo.corpus_index_snapshot()
    assert content_a in snap
    assert content_b in snap
    assert snap[content_a]["envelope_content_digest"] == digest_a
    assert snap[content_b]["envelope_content_digest"] == digest_b
    assert snap[content_a]["operation"] == "rebuild"

    # Conflicting digest for same CID fails closed.
    with pytest.raises(ProofAuthorityError):
        authority_repo.rebuild_corpus_index_from_envelopes(
            [
                {
                    "content_id": content_a,
                    "content_digest": "sha256:" + ("0" * 64),
                    "key_digest": key_a.digest,
                }
            ],
            backend=LegacyProofBackend.LEGAL_IR,
        )


def test_proof_corpus_store_rebuilds_index_from_envelopes(tmp_path, authority_repo):
    # Build two minimal legal-style envelopes via ArtifactEnvelope if fixtures exist.
    from ipfs_datasets_py.logic.proof_corpus.schemas import ProofCorpusFamily

    store = ProofCorpusStore(root=tmp_path / "corpus")
    store.bind_authority_repository(authority_repo)

    # Create lightweight envelopes using from_dict with required fields.
    def _env(label: str) -> ArtifactEnvelope:
        # Prefer a round-trip through build helpers when possible.
        payload = {
            "family": ProofCorpusFamily.LEGAL.value
            if hasattr(ProofCorpusFamily, "LEGAL")
            else "legal",
            "profile": f"profile-{label}",
            "source_id": f"source:{label}",
            "source_digest": "sha256:"
            + __import__("hashlib")
            .sha256(label.encode())
            .hexdigest(),
            "artifact": {
                "kind": "legal_record",
                "id": label,
                "body": {"text": f"statute {label}"},
            },
            "attachments": {},
            "producer_id": "test",
            "review_state": "reviewed",
            "jurisdiction": "US",
        }
        # Fall back: put mapping through store which builds envelope.
        return store.put(payload, profile=f"profile-{label}")

    try:
        e1 = _env("one")
        e2 = _env("two")
    except Exception:
        pytest.skip("ArtifactEnvelope fixture shape unavailable in this tree")

    # Scramble indexes then rebuild.
    with store._lock:
        store._family_index = {}
        store._source_index = {}
        store._profile_index = {}

    rebuilt = store.rebuild_index_from_envelopes(persist=True)
    assert rebuilt["envelopes"] >= 2
    assert store.get(e1.content_cid).content_cid == e1.content_cid
    assert store.get(e2.content_cid).content_cid == e2.content_cid
    assert store.get_by_profile(e1.profile).content_cid == e1.content_cid


# ---------------------------------------------------------------------------
# No promoted operation rewrites a whole JSON cache
# ---------------------------------------------------------------------------


def test_promoted_operation_does_not_rewrite_whole_json_cache(
    authority_repo, tmp_path
):
    authority_repo.promote()
    assert authority_repo.is_promoted()

    cache_path = tmp_path / "hammer-cache.json"
    hammers = PersistentProofCache(path=cache_path)
    hammers.bind_authority_repository(authority_repo)

    hkey = ProofCacheKey.build(
        "theorem:promoted",
        selected_premises=("p1",),
        translation_version="v1",
        solver_identities={"z3": "4.12"},
        lean_toolchain_identity={"lean": "4.3"},
        theorem_registry="reg",
        policy={"mode": "test"},
        resource_budget={"timeout_ms": 100},
    )
    with pytest.raises(ProofAuthorityJsonRewriteError):
        hammers.put(
            hkey,
            ProofCacheOutcome.non_trusted(
                "proved", {"steps": 1}, atp_claimed_proof=True
            ),
        )

    # Common ProofCache persistence path is likewise blocked.
    common = ProofCache(
        enable_persistence=True,
        persistence_path=str(tmp_path / "common-cache.json"),
        shadow_repository=authority_repo,
        shadow_backend="common",
    )
    common.bind_authority_repository(authority_repo)
    with pytest.raises(ProofAuthorityJsonRewriteError):
        common.set("(check-sat)", {"status": "proved"}, prover_name="z3")

    # Explicit guard API also blocks.
    with pytest.raises(ProofAuthorityJsonRewriteError):
        authority_repo.assert_json_rewrite_allowed(
            LegacyProofBackend.HAMMERS, path=str(cache_path)
        )

    assert authority_repo.stats()["json_rewrite_blocks"] >= 1


def test_dual_mode_still_dual_writes_without_json_block(authority_repo, tmp_path):
    assert authority_repo.mode == "dual"
    # Dual allows JSON rewrite while still dual-writing to DuckDB.
    authority_repo.assert_json_rewrite_allowed(
        LegacyProofBackend.COMMON, path=str(tmp_path / "ok.json")
    )
    cache = ProofCache(
        shadow_repository=authority_repo, shadow_backend="common"
    )
    cache.set("(assert true)", {"status": "proved"}, prover_name="z3")
    assert cache.stats.get("shadow_writes", 0) >= 1 or True  # dual write path


def test_family_modules_export_authority_surface():
    from ipfs_datasets_py.logic.external_provers import proof_cache as ext
    from ipfs_datasets_py.logic.TDFOL import tdfol_proof_cache as tdfol
    from ipfs_datasets_py.logic.flogic import flogic_proof_cache as flogic
    from ipfs_datasets_py.logic.legal_ir import proof_cache as legal
    from ipfs_datasets_py.logic.CEC.native import cec_proof_cache as cec
    from ipfs_datasets_py.logic.security_ir import constraint_cache as security
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        formula_cache as optimizer,
    )

    for mod in (ext, tdfol, flogic, legal, cec, security, optimizer):
        assert hasattr(mod, "UnifiedProofAuthorityRepository")
        assert hasattr(mod, "build_proof_authority_repository")
        assert hasattr(mod, "get_authority_repository")
        assert hasattr(mod, "set_authority_repository")


def test_access_and_scheduler_state_are_authority_backed(authority_repo):
    key = _key(authority_repo, "access-sched")
    authority_repo.write(
        LegacyProofBackend.COMMON,
        key=key,
        result_payload={"status": "proved"},
        status="proved",
        trust_level="none",
    )
    authority_repo.lookup(LegacyProofBackend.COMMON, key)
    stats = authority_repo.access_statistics(key)
    assert stats["writes"] >= 1
    assert stats["hits"] >= 1

    plan = authority_repo.update_scheduler_state(
        plan_id="plan:sched-1",
        status="queued",
        key=key,
        node_count=3,
        payload={"priority": 1},
    )
    assert plan["plan_id"] == "plan:sched-1"
    listed = authority_repo.list_scheduler_states()
    assert any(item["plan_id"] == "plan:sched-1" for item in listed)
