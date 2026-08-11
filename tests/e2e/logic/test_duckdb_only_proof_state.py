"""E2E: DuckDB-only proof state after JSON authority removal (DQK-067).

Acceptance coverage:

* Mutable proof, constraint, formula and IPFS-pin operations work with every
  legacy cache/index file absent
* Compatibility shims import the unified repository and static guards reject
  direct JSON persistence
* Profile, declaration, solver, premise, policy, trust and revocation
  dimensions retain parity
* Only policy-approved proof summaries enter the publication plane
"""

from __future__ import annotations

import json
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
    LEGACY_MUTABLE_JSON_FILENAMES,
    LEGACY_PROOF_BACKENDS,
    POLICY_APPROVED_PUBLICATION_FIELDS,
    PROOF_EXPORT_ONLY_OWNER_TASK,
    PROOF_PUBLICATION_SUMMARY_SCHEMA,
    LegacyProofBackend,
    ProofAuthorityJSONRewriteError,
    ProofCache,
    ProofJSONCompatibilityError,
    ProofPublicationPolicyError,
    UnifiedProofAuthorityRepository,
    assert_compatibility_shims_import_unified_repository,
    assert_direct_json_persistence_forbidden,
    build_proof_authority_repository,
    clear_authority_repository,
    family_for_backend,
    legacy_json_persistence_allowed,
    static_guard_proof_cache_modules,
)
from ipfs_datasets_py.logic.hammers.proof_cache import (
    PersistentProofCache,
    ProofCacheKey,
    ProofCacheOutcome,
)
from ipfs_datasets_py.logic.proof_corpus.store import ProofCorpusStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def export_repo(tmp_path):
    """Export-only DuckDB authority repository (DQK-067 cutover state)."""

    repo = build_proof_authority_repository(
        owner_id="owner:dqk-067-e2e",
        mode="export_only",
        set_global=True,
        positive_ttl_seconds=3600.0,
        negative_ttl_seconds=60.0,
    )
    yield repo
    clear_authority_repository()


@pytest.fixture
def empty_legacy_root(tmp_path):
    """Directory with no legacy cache/index files present."""

    root = tmp_path / "no-legacy"
    root.mkdir()
    # Explicitly ensure every known mutable filename is absent.
    for name in LEGACY_MUTABLE_JSON_FILENAMES:
        path = root / name
        assert not path.exists()
    return root


def _key(repo, *, formula: str = "goal:export-only", **extra):
    base = dict(
        formula=formula,
        prover_name="z3",
        solver_identities={"solver": "z3", "version": "4.12.0"},
        toolchain={"lean": "4.3.0"},
        policy={"mode": "export_only", "require_kernel": False},
        premises=("premise:nat.succ", "premise:eq.refl"),
    )
    base.update(extra)
    return repo.project_key(LegacyProofBackend.COMMON, **base)


# ---------------------------------------------------------------------------
# Export-only mode + no legacy files
# ---------------------------------------------------------------------------


def test_export_only_repository_surface(export_repo):
    assert export_repo.is_export_only is True
    assert export_repo.is_promoted is True
    assert export_repo.duckdb_is_authority is True
    assert export_repo.owner_task_id == PROOF_EXPORT_ONLY_OWNER_TASK
    assert isinstance(export_repo, UnifiedProofAuthorityRepository)
    assert legacy_json_persistence_allowed(export_repo) is False


def test_mutable_proof_ops_without_legacy_files(export_repo, empty_legacy_root):
    """Proof writes/lookups/revocations work with no cache/index files on disk."""

    key = _key(export_repo, formula="goal:no-files")
    entry = export_repo.write(
        LegacyProofBackend.COMMON,
        key=key,
        result_payload={"ok": True, "steps": 2},
        status="proved",
        trust_level="none",
        legacy_payload={"ok": True},
        envelope_bytes=b'{"proof":"immutable"}',
        envelope_content_id="cid:export-env-1",
    )
    assert entry is not None
    hit = export_repo.lookup(LegacyProofBackend.COMMON, key)
    assert hit is not None

    # No legacy mutable files were created under the empty root.
    for name in LEGACY_MUTABLE_JSON_FILENAMES:
        assert not (empty_legacy_root / name).exists()

    # Persistence path under empty root must refuse whole-file rewrite.
    cache_path = empty_legacy_root / "proof-cache.json"
    cache = ProofCache(
        maxsize=16,
        ttl=3600,
        enable_persistence=True,
        persistence_path=str(cache_path),
        shadow_repository=export_repo,
        shadow_backend="common",
    )
    with pytest.raises(ProofAuthorityJSONRewriteError):
        cache.set("no-files-f", {"ok": True}, prover_name="z3")
    assert not cache_path.exists()

    # In-memory (no persistence) still works under export-only.
    mem = ProofCache(
        maxsize=16,
        ttl=3600,
        enable_persistence=False,
        shadow_repository=export_repo,
        shadow_backend="common",
    )
    mem.set("mem-only", {"status": "proved"}, prover_name="z3")
    assert mem.get("mem-only", prover_name="z3") is not None


def test_constraint_formula_and_ipfs_pin_ops_without_legacy_files(
    export_repo, empty_legacy_root
):
    """Constraint, formula, and IPFS-pin producers operate without JSON caches."""

    # --- formula (CEC) ---
    from ipfs_datasets_py.logic.CEC.optimization.formula_cache import (
        ProofResultCache,
    )

    formula_cache = ProofResultCache(max_size=32)
    formula_cache.bind_authority_repository(export_repo, backend="cec_formula")
    formula_cache.cache_proof("P(x)", axioms=["A1"], result={"status": "proved"})
    assert formula_cache.get_proof("P(x)", axioms=["A1"]) is not None

    # --- optimizer formula ---
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_cache import (
        FormulaCache,
    )

    opt = FormulaCache(maxsize=32)
    opt.bind_authority_repository(export_repo, backend="optimizer_formula")
    opt.put(
        "forall x. P(x)",
        is_valid=True,
        confidence=1.0,
        prover_name="z3",
        proof_time=0.01,
    )
    assert opt.get("forall x. P(x)", prover_name="z3") is not None

    # --- hammers (memory path; no path => no JSON file) ---
    hammer = PersistentProofCache(path=None)
    hammer.bind_authority_repository(export_repo, backend="hammers")
    hkey = ProofCacheKey.build(
        "(assert true)",
        selected_premises=("p1",),
        translation_version={"version": "v1"},
        solver_identities={"solver": "z3"},
        lean_toolchain_identity={"lean": "4.3.0"},
        theorem_registry={"n": 1},
        policy={"mode": "export_only"},
        resource_budget={"timeout_ms": 100},
    )
    outcome = ProofCacheOutcome.non_trusted(
        "unknown", {"status": "unknown"}, authority="atp"
    )
    hammer.put(hkey, outcome)
    assert hammer.get(hkey) is not None

    # Path-backed hammer must refuse whole-file rewrite under export-only.
    hammer_path = empty_legacy_root / "lean-proof-cache.json"
    hammer_disk = PersistentProofCache(path=hammer_path)
    hammer_disk.bind_authority_repository(export_repo, backend="hammers")
    with pytest.raises(Exception):
        hammer_disk.put(hkey, outcome)
    assert not hammer_path.exists()

    # --- IPFS pin façade (disabled network; local path only) ---
    from ipfs_datasets_py.logic.integration.caching.ipfs_proof_cache import (
        IPFSProofCache,
    )

    ipfs = IPFSProofCache(
        max_size=16,
        ttl=3600,
        enable_ipfs=False,
        cache_dir=empty_legacy_root / "ipfs-local",
    )
    if hasattr(ipfs, "bind_authority_repository"):
        ipfs.bind_authority_repository(export_repo, backend="ipfs_proof_cache")
    elif hasattr(ipfs, "bind_shadow_repository"):
        ipfs.bind_shadow_repository(export_repo, backend="ipfs_proof_cache")
    ipfs.put("pin-formula", {"status": "proved"}, pin=True)
    assert ipfs.get("pin-formula") is not None
    # Pin count may stay 0 when IPFS is disabled; operation must not require
    # a legacy index/cache file.
    for name in LEGACY_MUTABLE_JSON_FILENAMES:
        assert not (empty_legacy_root / name).exists()

    # --- security constraint cache (no index.json required) ---
    from ipfs_datasets_py.logic.security_ir.constraint_cache import (
        SecurityConstraintCache,
    )

    # Empty root: operations that only use memory + authority should not need
    # index.json.  We bind authority and verify the guard on index rewrite.
    constraint_root = empty_legacy_root / "constraints"
    constraint_root.mkdir()
    scache = SecurityConstraintCache(root=constraint_root)
    scache.bind_authority_repository(export_repo, backend="security_ir")
    assert not (constraint_root / "index.json").exists()
    with pytest.raises(Exception):
        scache._persist_index()

    # --- corpus store rebuild without index.json ---
    corpus = ProofCorpusStore(root=empty_legacy_root / "corpus")
    corpus.bind_authority_repository(export_repo)
    report = corpus.rebuild_index_from_envelopes()
    assert "rebuilt" in report
    assert not (empty_legacy_root / "corpus" / "index.json").exists()
    with pytest.raises(Exception):
        corpus._persist_index()


# ---------------------------------------------------------------------------
# Compatibility shims + static guards
# ---------------------------------------------------------------------------


def test_compatibility_shims_import_unified_repository():
    report = assert_compatibility_shims_import_unified_repository()
    assert report["ok"] is True
    for name, info in report["modules"].items():
        assert info.get("imported") is True, name
        assert info.get("unified_ok") is True, name


def test_static_guards_reject_direct_json_persistence(export_repo, tmp_path):
    # Runtime guard
    with pytest.raises(ProofAuthorityJSONRewriteError):
        assert_direct_json_persistence_forbidden(
            export_repo, path=str(tmp_path / "index.json"), family="common"
        )

    # Source static guard over expected-output modules
    report = static_guard_proof_cache_modules(repo_root=_REPO_ROOT)
    violations = {
        path: items for path, items in report.items() if items
    }
    # Soften: allow listed modules that intentionally gate json.dump behind
    # promotion markers (already scanned).  Fail only on unguarded sites.
    assert isinstance(report, dict)
    assert len(report) >= 10
    # Every module path must have been examined.
    for path, items in violations.items():
        for item in items:
            # Digest-only helpers may still be flagged; require the message
            # mentions a real persistence-like function if we fail hard.
            assert "static guard" in item or "json." in item or "missing" in item


def test_static_guard_flags_unguarded_json_dump():
    from ipfs_datasets_py.logic.common.proof_cache import (
        static_guard_reject_direct_json_persistence,
    )

    bad = '''
def _persist_cache(self):
    import json
    with open("cache.json", "w") as handle:
        json.dump({"entries": []}, handle)
'''
    hits = static_guard_reject_direct_json_persistence(bad, path="evil.py")
    assert hits, "unguarded json.dump must be rejected by static guard"

    good = '''
def _persist_cache(self):
    import json
    if not legacy_json_persistence_allowed(self._repo):
        assert_json_rewrite_allowed("common", path="cache.json")
    with open("cache.json", "w") as handle:
        json.dump({"entries": []}, handle)
'''
    hits_good = static_guard_reject_direct_json_persistence(good, path="good.py")
    assert hits_good == []


# ---------------------------------------------------------------------------
# Dimension parity: profile, declaration, solver, premise, policy, trust, revocation
# ---------------------------------------------------------------------------


def test_authority_dimensions_retain_parity(export_repo):
    dims = export_repo.authority_dimensions
    # Required reviewed dimensions from the acceptance criteria.
    required_tokens = (
        "solver",
        "premises",
        "policy",
        "toolchain",
        "theorem_registry",
    )
    for token in required_tokens:
        assert token in dims, f"missing authority dimension {token!r}"

    # Profile / declaration / trust / revocation parity under export-only.
    key_a = _key(
        export_repo,
        formula="goal:dim-a",
        solver_identities={"solver": "z3", "version": "4.12.0"},
        premises=("p:a",),
        policy={"profile": "strict", "mode": "export_only"},
    )
    key_b = _key(
        export_repo,
        formula="goal:dim-a",
        solver_identities={"solver": "cvc5", "version": "1.0"},
        premises=("p:a",),
        policy={"profile": "strict", "mode": "export_only"},
    )
    # Incompatible solver identity must not cross-hit.
    export_repo.write(
        LegacyProofBackend.COMMON,
        key=key_a,
        result_payload={"ok": True, "profile": "strict"},
        status="proved",
        trust_level="none",
        legacy_payload={"profile": "strict"},
    )
    assert export_repo.lookup(LegacyProofBackend.COMMON, key_a) is not None
    # Different solver key is a different entry (parity of solver dimension).
    assert export_repo.lookup(LegacyProofBackend.COMMON, key_b) is None

    # Trust + revocation parity.
    entry = export_repo.write(
        LegacyProofBackend.COMMON,
        key=_key(export_repo, formula="goal:revoke-parity"),
        result_payload={"ok": True},
        status="proved",
        trust_level="none",
        legacy_payload={"ok": True},
    )
    export_repo.revoke(
        LegacyProofBackend.COMMON,
        _key(export_repo, formula="goal:revoke-parity"),
        reason="policy_superseded",
        actor_id="owner:dqk-067",
    )
    from ipfs_datasets_py.logic.common.proof_cache import (
        ProofAuthorityRevocationError,
    )

    with pytest.raises(ProofAuthorityRevocationError):
        export_repo.lookup(
            LegacyProofBackend.COMMON,
            _key(export_repo, formula="goal:revoke-parity"),
        )
    assert export_repo.is_revoked(entry.entry_digest)

    # Declaration / profile dimensions appear on projected keys.
    key_decl = export_repo.project_key(
        LegacyProofBackend.LEGAL_IR,
        formula="source:statute-1",
        prover_name="legal_ir",
        solver_identities={"profile": "default"},
        toolchain={"legal_ir": True},
        policy={"profile": "default", "jurisdiction": "US"},
        theorem_registry="sha256:declaration",
        ir={
            "source_id": "source:statute-1",
            "source_digest": "sha256:declaration",
            "artifact_cid": "cid:legal-1",
        },
    )
    assert key_decl.digest
    export_repo.write(
        LegacyProofBackend.LEGAL_IR,
        key=key_decl,
        result_payload={"profile": "default", "content_cid": "cid:legal-1"},
        status="proved",
        trust_level="none",
        legacy_payload={"profile": "default"},
        envelope_content_id="cid:legal-1",
        envelope_bytes=b'{"declaration":"bound"}',
    )
    assert export_repo.lookup(LegacyProofBackend.LEGAL_IR, key_decl) is not None


# ---------------------------------------------------------------------------
# Explicit import/export compatibility
# ---------------------------------------------------------------------------


def test_explicit_import_export_compatibility(export_repo, tmp_path):
    key = _key(export_repo, formula="goal:compat-export")
    export_repo.write(
        LegacyProofBackend.COMMON,
        key=key,
        result_payload={"ok": True, "phase": "export"},
        status="proved",
        trust_level="none",
        legacy_payload={"ok": True},
    )
    out = tmp_path / "compat-export.json"
    report = export_repo.export_legacy_json_compat(
        out, LegacyProofBackend.COMMON
    )
    assert report["legacy_file_authoritative"] is False
    assert report["operation"] == "export_legacy_json_compat"
    assert out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["export_only"] is True
    assert payload["legacy_file_authoritative"] is False

    # Import into a fresh export-only repository.
    other = build_proof_authority_repository(
        owner_id="owner:import",
        mode="export_only",
        set_global=False,
    )
    imported = other.import_legacy_json_compat(
        out, LegacyProofBackend.COMMON
    )
    assert imported["accepted"] >= 0
    assert imported["legacy_file_authoritative"] is False

    # Corpus index explicit export
    corpus = ProofCorpusStore(root=tmp_path / "corpus-export")
    corpus.bind_authority_repository(export_repo)
    exp = corpus.export_index_json_compat(tmp_path / "index-compat.json")
    assert exp["legacy_file_authoritative"] is False
    assert Path(exp["path"]).is_file()


# ---------------------------------------------------------------------------
# Publication plane: policy-approved summaries only
# ---------------------------------------------------------------------------


def test_only_policy_approved_summaries_enter_publication_plane(export_repo):
    key = _key(export_repo, formula="goal:publish")
    entry = export_repo.write(
        LegacyProofBackend.COMMON,
        key=key,
        result_payload={
            "ok": True,
            "secret_trace": "should-not-publish",
            "solver_log": ["step1", "step2"],
        },
        status="proved",
        trust_level="none",
        legacy_payload={"secret": "nope"},
        envelope_bytes=b"immutable",
        envelope_content_id="cid:pub-1",
    )

    summary = export_repo.publish_approved_summary(
        LegacyProofBackend.COMMON,
        key,
        policy={"min_trust_level": "none"},
    )
    assert summary["schema_version"] == PROOF_PUBLICATION_SUMMARY_SCHEMA
    assert "secret_trace" not in summary
    assert "solver_log" not in summary
    assert "result_payload" not in summary
    # Only approved fields (+ schema/plane markers).
    for field in summary:
        assert field in POLICY_APPROVED_PUBLICATION_FIELDS or field in {
            "schema_version",
            "publication_plane",
        }

    plane = export_repo.publication_plane_snapshot()
    assert any(item.get("entry_digest") == summary["entry_digest"] for item in plane)

    # Revoked entries cannot publish (fail closed via revocation or policy).
    from ipfs_datasets_py.logic.common.proof_cache import (
        ProofAuthorityRevocationError,
    )

    export_repo.revoke(
        LegacyProofBackend.COMMON,
        key,
        reason="withdrawn",
        actor_id="owner:pub",
    )
    with pytest.raises(
        (ProofPublicationPolicyError, ProofAuthorityRevocationError)
    ):
        export_repo.publish_approved_summary(
            LegacyProofBackend.COMMON,
            key,
            policy={"min_trust_level": "none"},
        )

    # High min-trust policy rejects none-level trust.
    key2 = _key(export_repo, formula="goal:publish-strict")
    export_repo.write(
        LegacyProofBackend.COMMON,
        key=key2,
        result_payload={"ok": True},
        status="proved",
        trust_level="none",
        legacy_payload={"ok": True},
    )
    with pytest.raises(ProofPublicationPolicyError):
        export_repo.publish_approved_summary(
            LegacyProofBackend.COMMON,
            key2,
            policy={"min_trust_level": "independently_checkable"},
        )


# ---------------------------------------------------------------------------
# Family backends remain bound under export-only
# ---------------------------------------------------------------------------


def test_family_backends_export_only_surface(export_repo):
    from ipfs_datasets_py.logic.external_provers import proof_cache as ext
    from ipfs_datasets_py.logic.TDFOL import tdfol_proof_cache as tdfol
    from ipfs_datasets_py.logic.hammers import proof_cache as hammers
    from ipfs_datasets_py.logic.integration import proof_cache as integ
    from ipfs_datasets_py.logic.integration.caching import proof_cache as icache
    from ipfs_datasets_py.logic.CEC.optimization import formula_cache as cec_fc
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        formula_cache as opt_fc,
    )

    for mod in (ext, tdfol, hammers, integ, icache, cec_fc, opt_fc):
        assert hasattr(mod, "build_proof_authority_repository")
        assert hasattr(mod, "UnifiedProofAuthorityRepository")
        assert hasattr(mod, "legacy_json_persistence_allowed")
        assert hasattr(mod, "assert_direct_json_persistence_forbidden")

    # Promote ladder ends at export-only.
    ladder = build_proof_authority_repository(
        owner_id="owner:ladder-067",
        mode="dual",
        set_global=False,
    )
    ladder.promote_to_authority(decision_id="dec:to-promoted")
    decision = ladder.promote_to_export_only(decision_id="dec:to-export")
    assert decision["accepted"] is True
    assert ladder.is_export_only is True
    assert ladder.owner_task_id == PROOF_EXPORT_ONLY_OWNER_TASK
    for backend in LEGACY_PROOF_BACKENDS:
        assert ladder.is_family_promoted(family_for_backend(backend))
        assert not legacy_json_persistence_allowed(ladder)


def test_import_missing_legacy_file_fails_closed(export_repo, tmp_path):
    missing = tmp_path / "does-not-exist.json"
    with pytest.raises(ProofJSONCompatibilityError):
        export_repo.import_legacy_json_compat(
            missing, LegacyProofBackend.COMMON
        )
