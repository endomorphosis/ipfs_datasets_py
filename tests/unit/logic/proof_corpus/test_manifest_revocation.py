"""Unit tests for immutable proof-corpus manifests and revocation (LIG-030).

Acceptance:

* Bind corpus domain/namespace/schema/root/parent, ordered entries, source set,
  compiler/solver/circuit/VK registries, index manifests, revocation root,
  coverage/licensing/privacy/tenant policy, producer and promotion receipt.
* Separate bodies from indices.
* Reject mutable latest, duplicate/missing/unbound bodies, path traversal,
  oversize content, hash/CID mismatch, parent/revocation cycles,
  rollback/downgrade and unapproved registry roots.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any

import pytest

from ipfs_datasets_py.logic.ir_core.identity import cid_v1_from_digest
from ipfs_datasets_py.logic.proof_corpus.manifest import (
    DEFAULT_MAX_ENTRY_BYTES,
    PROOF_CORPUS_MANIFEST_INTERFACE,
    PROOF_CORPUS_MANIFEST_SCHEMA_VERSION,
    EntryKind,
    IndexManifestKind,
    IndexManifestRef,
    ManifestEntry,
    PolicyBinding,
    PromotionReceipt,
    ProofCorpusManifest,
    ProofCorpusManifestError,
    ProofCorpusManifestIntegrityError,
    RegistryBinding,
    RegistryKind,
    SourceBinding,
    build_index_manifest_ref,
    build_manifest_entry,
    build_proof_corpus_manifest,
    check_append_only_lineage,
    cid_for_digest,
    detect_parent_cycle,
    deterministic_rebuild_root,
    digest_bytes,
    require_safe_relative_path,
    verify_manifest_bodies,
)
from ipfs_datasets_py.logic.proof_corpus.revocation import (
    PROOF_REVOCATION_SNAPSHOT_INTERFACE,
    PROOF_REVOCATION_SNAPSHOT_SCHEMA_VERSION,
    ProofRevocationError,
    ProofRevocationIntegrityError,
    ProofRevocationSnapshot,
    RevocationEntry,
    RevocationReasonKind,
    bind_manifest_revocation_root,
    build_revocation_entry,
    build_revocation_snapshot,
    check_revocation_lineage,
    cumulative_revoked_cids,
    detect_revocation_cycle,
)


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _cid(label: str) -> str:
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    return cid_v1_from_digest(bytes.fromhex(digest))


def _body(label: str) -> bytes:
    return f"body:{label}".encode("utf-8")


def _registry(
    kind: RegistryKind,
    registry_id: str,
    root_label: str,
    version: int = 1,
) -> RegistryBinding:
    return RegistryBinding(
        registry_kind=kind,
        registry_id=registry_id,
        root_cid=_cid(root_label),
        version=version,
        digest=_digest(root_label),
    )


def _honest_bodies() -> dict[str, bytes]:
    return {
        "bodies/envelope-a.json": _body("envelope-a"),
        "bodies/envelope-b.json": _body("envelope-b"),
    }


def _honest_entries(
    bodies: dict[str, bytes] | None = None,
) -> tuple[ManifestEntry, ...]:
    bodies = bodies or _honest_bodies()
    entries: list[ManifestEntry] = []
    for ordinal, (path, content) in enumerate(sorted(bodies.items())):
        entry_id = path.split("/")[-1].replace(".", "_").replace("-", "_")
        entries.append(
            build_manifest_entry(
                entry_id=entry_id,
                path=path,
                content=content,
                ordinal=ordinal,
                source_id="source-us-code",
                media_type="application/json",
            )
        )
    return tuple(entries)


def _honest_index() -> IndexManifestRef:
    return build_index_manifest_ref(
        index_id="family_index",
        content=b'{"family":["legal"]}',
        index_kind=IndexManifestKind.FAMILY,
    )


def _honest_manifest(**overrides: Any) -> ProofCorpusManifest:
    approved = (
        _cid("compiler-reg"),
        _cid("solver-reg"),
        _cid("circuit-reg"),
        _cid("vk-reg"),
    )
    base: dict[str, Any] = {
        "domain": "legal",
        "namespace": "proof-corpus.legal.v1",
        "entries": _honest_entries(),
        "sources": (
            SourceBinding(
                source_id="source-us-code",
                snapshot_cid=_cid("source-snapshot"),
                snapshot_digest=_digest("source-snapshot"),
                license_id="license-cc0",
            ),
        ),
        "compiler_registry": (
            _registry(RegistryKind.COMPILER, "compiler-canonical-v1", "compiler-reg"),
        ),
        "solver_registry": (
            _registry(RegistryKind.SOLVER, "solver-z3", "solver-reg"),
        ),
        "circuit_registry": (
            _registry(RegistryKind.CIRCUIT, "legal_constraint", "circuit-reg"),
        ),
        "vk_registry": (
            _registry(RegistryKind.VK, "legal_constraint_vk", "vk-reg"),
        ),
        "index_manifests": (_honest_index(),),
        "revocation_root_cid": "",
        "policy": PolicyBinding(
            coverage_policy_id="coverage-full",
            licensing_policy_id="license-cc0",
            privacy_policy_id="privacy-redact",
            tenant_policy_id="tenant-strict",
            policy_root_cid=_cid("policy-root"),
        ),
        "producer_id": "lig-030-producer",
        "promotion_receipt": PromotionReceipt(
            receipt_id="promo-001",
            producer_id="lig-030-producer",
            promoted_at="2026-07-01T00:00:00Z",
            source_manifest_cid=_cid("prior-manifest"),
            target_namespace="proof-corpus.legal.v1",
            reviewer_id="reviewer-a",
            approval_digest=_digest("approval"),
        ),
        "parent_cid": "",
        "generation": 1,
        "approved_registry_roots": approved,
        "max_entry_bytes": DEFAULT_MAX_ENTRY_BYTES,
    }
    base.update(overrides)
    return ProofCorpusManifest(**base)


def _child_manifest(parent: ProofCorpusManifest, **overrides: Any) -> ProofCorpusManifest:
    bodies = {
        "bodies/envelope-a.json": _body("envelope-a"),
        "bodies/envelope-b.json": _body("envelope-b"),
        "bodies/envelope-c.json": _body("envelope-c"),
    }
    kwargs: dict[str, Any] = {
        "domain": parent.domain,
        "namespace": parent.namespace,
        "entries": _honest_entries(bodies),
        "sources": parent.sources,
        "compiler_registry": (
            _registry(
                RegistryKind.COMPILER,
                "compiler-canonical-v1",
                "compiler-reg",
                version=2,
            ),
        ),
        "solver_registry": parent.solver_registry,
        "circuit_registry": parent.circuit_registry,
        "vk_registry": parent.vk_registry,
        "index_manifests": parent.index_manifests,
        "policy": parent.policy,
        "producer_id": parent.producer_id,
        "promotion_receipt": parent.promotion_receipt,
        "parent_cid": parent.root_cid,
        "generation": parent.generation + 1,
        "approved_registry_roots": parent.approved_registry_roots,
        "max_entry_bytes": parent.max_entry_bytes,
    }
    kwargs.update(overrides)
    return ProofCorpusManifest(**kwargs)


def _honest_revocation(
    corpus_root_cid: str,
    *,
    targets: list[str] | None = None,
    **overrides: Any,
) -> ProofRevocationSnapshot:
    if targets is None:
        target_list = [_cid("envelope-revoked")]
    else:
        target_list = list(targets)
    entries = tuple(
        build_revocation_entry(
            target_cid=target,
            reason_kind=RevocationReasonKind.POLICY,
            reason="policy withdrawal",
            revoked_at="2026-07-02T00:00:00Z",
            issuer_id="issuer-legal",
            ordinal=index,
        )
        for index, target in enumerate(target_list)
    )
    base: dict[str, Any] = {
        "corpus_root_cid": corpus_root_cid,
        "entries": entries,
        "parent_cid": "",
        "generation": 1,
        "producer_id": "lig-030-revoker",
    }
    base.update(overrides)
    return ProofRevocationSnapshot(**base)


# ---------------------------------------------------------------------------
# Manifest bindings
# ---------------------------------------------------------------------------


def test_manifest_binds_all_acceptance_fields() -> None:
    manifest = _honest_manifest()
    manifest.verify_integrity()

    assert manifest.interface == PROOF_CORPUS_MANIFEST_INTERFACE
    assert manifest.schema_version == PROOF_CORPUS_MANIFEST_SCHEMA_VERSION
    assert manifest.domain == "legal"
    assert manifest.namespace == "proof-corpus.legal.v1"
    assert manifest.root_cid.startswith("b")
    assert manifest.content_cid == manifest.root_cid
    assert manifest.content_digest.startswith("sha256:")
    assert manifest.parent_cid == ""
    assert manifest.generation == 1

    assert len(manifest.entries) == 2
    assert [e.ordinal for e in manifest.entries] == [0, 1]
    assert all(e.kind is EntryKind.BODY for e in manifest.entries)

    assert len(manifest.sources) == 1
    assert manifest.sources[0].source_id == "source-us-code"

    assert manifest.compiler_registry[0].registry_id == "compiler-canonical-v1"
    assert manifest.solver_registry[0].registry_id == "solver-z3"
    assert manifest.circuit_registry[0].registry_id == "legal_constraint"
    assert manifest.vk_registry[0].registry_id == "legal_constraint_vk"

    assert len(manifest.index_manifests) == 1
    assert manifest.index_manifests[0].index_kind is IndexManifestKind.FAMILY

    assert isinstance(manifest.policy, PolicyBinding)
    assert manifest.policy.coverage_policy_id == "coverage-full"
    assert manifest.policy.licensing_policy_id == "license-cc0"
    assert manifest.policy.privacy_policy_id == "privacy-redact"
    assert manifest.policy.tenant_policy_id == "tenant-strict"

    assert manifest.producer_id == "lig-030-producer"
    assert isinstance(manifest.promotion_receipt, PromotionReceipt)
    assert manifest.promotion_receipt.receipt_id == "promo-001"


def test_manifest_round_trip_preserves_root() -> None:
    original = _honest_manifest()
    restored = ProofCorpusManifest.from_dict(original.to_dict())
    assert restored.root_cid == original.root_cid
    assert restored.content_digest == original.content_digest
    assert restored.to_dict() == original.to_dict()
    restored.verify_integrity()


def test_manifest_identity_is_mutation_sensitive() -> None:
    honest = _honest_manifest()
    # producer changes require matching promotion receipt
    with pytest.raises(ProofCorpusManifestIntegrityError):
        _honest_manifest(
            producer_id="other-producer",
            # keep original promotion receipt with different producer
        )
    mutated = _honest_manifest(
        producer_id="other-producer",
        promotion_receipt=PromotionReceipt(
            receipt_id="promo-002",
            producer_id="other-producer",
            promoted_at="2026-07-01T00:00:00Z",
        ),
    )
    assert honest.root_cid != mutated.root_cid


def test_bodies_and_indices_are_separate() -> None:
    manifest = _honest_manifest()
    body_ids = {e.entry_id for e in manifest.entries}
    index_ids = {i.index_id for i in manifest.index_manifests}
    assert body_ids.isdisjoint(index_ids)
    body_cids = set(manifest.body_cids())
    index_cids = {i.index_cid for i in manifest.index_manifests}
    assert body_cids.isdisjoint(index_cids)

    # Index must not be inventable as a body entry kind.
    with pytest.raises(ProofCorpusManifestError, match="kind"):
        ManifestEntry(
            entry_id="bad_index",
            path="indices/family.json",
            content_cid=cid_for_digest(digest_bytes(b"x")),
            content_digest=digest_bytes(b"x"),
            size_bytes=1,
            kind="index",  # type: ignore[arg-type]
        )


def test_body_id_collision_with_index_rejected() -> None:
    index = _honest_index()
    body = build_manifest_entry(
        entry_id=index.index_id,
        path="bodies/collide.json",
        content=_body("collide"),
        ordinal=0,
        source_id="source-us-code",
    )
    with pytest.raises(ProofCorpusManifestIntegrityError, match="separate"):
        _honest_manifest(entries=(body,), index_manifests=(index,))


# ---------------------------------------------------------------------------
# Body verification / rebuild
# ---------------------------------------------------------------------------


def test_verify_manifest_bodies_and_deterministic_rebuild() -> None:
    bodies = _honest_bodies()
    manifest = _honest_manifest(entries=_honest_entries(bodies))
    verify_manifest_bodies(manifest, bodies)
    root = deterministic_rebuild_root(manifest, bodies)
    assert root == manifest.root_cid


def test_missing_body_rejected() -> None:
    bodies = _honest_bodies()
    manifest = _honest_manifest(entries=_honest_entries(bodies))
    incomplete = {"bodies/envelope-a.json": bodies["bodies/envelope-a.json"]}
    with pytest.raises(ProofCorpusManifestIntegrityError, match="missing bodies"):
        verify_manifest_bodies(manifest, incomplete)


def test_unbound_body_rejected() -> None:
    bodies = _honest_bodies()
    manifest = _honest_manifest(entries=_honest_entries(bodies))
    extra = dict(bodies)
    extra["bodies/unbound.json"] = _body("unbound")
    with pytest.raises(ProofCorpusManifestIntegrityError, match="unbound bodies"):
        verify_manifest_bodies(manifest, extra)


def test_duplicate_body_entry_id_rejected() -> None:
    content = _body("dup")
    entry_a = build_manifest_entry(
        entry_id="same_id",
        path="bodies/a.json",
        content=content,
        ordinal=0,
        source_id="source-us-code",
    )
    entry_b = build_manifest_entry(
        entry_id="same_id",
        path="bodies/b.json",
        content=_body("other"),
        ordinal=1,
        source_id="source-us-code",
    )
    with pytest.raises(ProofCorpusManifestIntegrityError, match="duplicate entry_id"):
        _honest_manifest(entries=(entry_a, entry_b))


def test_duplicate_body_path_rejected() -> None:
    entry_a = build_manifest_entry(
        entry_id="a",
        path="bodies/same.json",
        content=_body("a"),
        ordinal=0,
        source_id="source-us-code",
    )
    entry_b = build_manifest_entry(
        entry_id="b",
        path="bodies/same.json",
        content=_body("b"),
        ordinal=1,
        source_id="source-us-code",
    )
    with pytest.raises(ProofCorpusManifestIntegrityError, match="duplicate path"):
        _honest_manifest(entries=(entry_a, entry_b))


def test_hash_and_cid_mismatch_on_body_rejected() -> None:
    bodies = _honest_bodies()
    manifest = _honest_manifest(entries=_honest_entries(bodies))
    tampered = dict(bodies)
    tampered["bodies/envelope-a.json"] = _body("tampered")
    with pytest.raises(ProofCorpusManifestIntegrityError, match="mismatch"):
        verify_manifest_bodies(manifest, tampered)


def test_manifest_content_digest_drift_fails_closed() -> None:
    honest = _honest_manifest()
    payload = honest.to_dict()
    payload["content_digest"] = _digest("tampered")
    with pytest.raises(ProofCorpusManifestIntegrityError, match="content_digest"):
        ProofCorpusManifest.from_dict(payload)


def test_manifest_root_cid_drift_fails_closed() -> None:
    honest = _honest_manifest()
    payload = honest.to_dict()
    payload["root_cid"] = _cid("tampered-root")
    with pytest.raises(ProofCorpusManifestIntegrityError, match="root_cid"):
        ProofCorpusManifest.from_dict(payload)


def test_entry_cid_digest_mismatch_rejected() -> None:
    content = _body("x")
    digest = digest_bytes(content)
    with pytest.raises(ProofCorpusManifestIntegrityError, match="content_cid"):
        ManifestEntry(
            entry_id="bad",
            path="bodies/x.json",
            content_cid=_cid("wrong"),
            content_digest=digest,
            size_bytes=len(content),
        )


# ---------------------------------------------------------------------------
# Path traversal / latest / oversize
# ---------------------------------------------------------------------------


def test_path_traversal_rejected() -> None:
    with pytest.raises(ProofCorpusManifestIntegrityError, match="traversal"):
        require_safe_relative_path("../etc/passwd")
    with pytest.raises(ProofCorpusManifestIntegrityError, match="traversal"):
        require_safe_relative_path("/absolute/path")
    with pytest.raises(ProofCorpusManifestIntegrityError, match="POSIX"):
        require_safe_relative_path("bodies\\win.json")
    with pytest.raises(ProofCorpusManifestIntegrityError, match="traversal"):
        build_manifest_entry(
            entry_id="evil",
            path="bodies/../../secret.json",
            content=b"x",
            ordinal=0,
        )


def test_mutable_latest_rejected() -> None:
    with pytest.raises(ProofCorpusManifestIntegrityError, match="latest"):
        require_safe_relative_path("bodies/latest")
    with pytest.raises(ProofCorpusManifestIntegrityError, match="latest"):
        require_safe_relative_path("latest/envelope.json")
    with pytest.raises(ProofCorpusManifestIntegrityError, match="latest"):
        _honest_manifest(namespace="proof-corpus.latest")
    with pytest.raises(ProofCorpusManifestIntegrityError, match="latest"):
        build_manifest_entry(
            entry_id="latest",
            path="bodies/ok.json",
            content=b"x",
            ordinal=0,
        )


def test_oversize_content_rejected() -> None:
    content = b"x" * 100
    entry = build_manifest_entry(
        entry_id="big",
        path="bodies/big.json",
        content=content,
        ordinal=0,
        source_id="source-us-code",
    )
    with pytest.raises(ProofCorpusManifestIntegrityError, match="oversize"):
        _honest_manifest(entries=(entry,), max_entry_bytes=50)

    # verify_manifest_bodies also rejects oversize even if entry slipped through
    # with a larger declared max that we lower... construction already rejects.
    small = _honest_manifest(max_entry_bytes=10_000)
    huge_bodies = {
        path: b"y" * 20_000 for path in small.body_paths()
    }
    # size mismatch / oversize
    with pytest.raises(ProofCorpusManifestIntegrityError):
        verify_manifest_bodies(small, huge_bodies)


def test_unapproved_registry_root_rejected() -> None:
    with pytest.raises(
        ProofCorpusManifestIntegrityError, match="unapproved registry root"
    ):
        _honest_manifest(
            approved_registry_roots=(_cid("compiler-reg"),),  # incomplete allowlist
        )


def test_unordered_ordinals_rejected() -> None:
    bodies = _honest_bodies()
    entries = list(_honest_entries(bodies))
    # Swap ordinals so list is not non-decreasing by ordinal.
    entries[0] = build_manifest_entry(
        entry_id=entries[0].entry_id,
        path=entries[0].path,
        content=bodies[entries[0].path],
        ordinal=5,
        source_id="source-us-code",
    )
    entries[1] = build_manifest_entry(
        entry_id=entries[1].entry_id,
        path=entries[1].path,
        content=bodies[entries[1].path],
        ordinal=1,
        source_id="source-us-code",
    )
    with pytest.raises(ProofCorpusManifestIntegrityError, match="ordered"):
        _honest_manifest(entries=tuple(entries))


def test_entry_source_not_in_source_set_rejected() -> None:
    entry = build_manifest_entry(
        entry_id="orphan",
        path="bodies/orphan.json",
        content=_body("orphan"),
        ordinal=0,
        source_id="unknown-source",
    )
    with pytest.raises(ProofCorpusManifestIntegrityError, match="source set"):
        _honest_manifest(entries=(entry,))


# ---------------------------------------------------------------------------
# Parent lineage / rollback
# ---------------------------------------------------------------------------


def test_append_only_lineage_accepts_valid_child() -> None:
    parent = _honest_manifest()
    child = _child_manifest(parent)
    check_append_only_lineage(child, parent)
    assert child.generation == parent.generation + 1
    assert child.parent_cid == parent.root_cid


def test_rollback_downgrade_generation_rejected() -> None:
    parent = _honest_manifest(generation=3)
    child = _child_manifest(parent, generation=2)
    with pytest.raises(
        ProofCorpusManifestIntegrityError, match="rollback/downgrade"
    ):
        check_append_only_lineage(child, parent)


def test_registry_version_downgrade_rejected() -> None:
    parent = _honest_manifest()
    child = _child_manifest(
        parent,
        compiler_registry=(
            _registry(
                RegistryKind.COMPILER,
                "compiler-canonical-v1",
                "compiler-reg",
                version=1,  # parent already has v1; child of rebuild with same
            ),
        ),
    )
    # Same version is OK (not a downgrade). Force parent to v2 then child v1.
    parent_v2 = _honest_manifest(
        compiler_registry=(
            _registry(
                RegistryKind.COMPILER,
                "compiler-canonical-v1",
                "compiler-reg",
                version=2,
            ),
        ),
    )
    child_down = _child_manifest(
        parent_v2,
        compiler_registry=(
            _registry(
                RegistryKind.COMPILER,
                "compiler-canonical-v1",
                "compiler-reg",
                version=1,
            ),
        ),
    )
    with pytest.raises(
        ProofCorpusManifestIntegrityError, match="downgrade"
    ):
        check_append_only_lineage(child_down, parent_v2)


def test_parent_cycle_rejected() -> None:
    parent = _honest_manifest()
    with pytest.raises(ProofCorpusManifestIntegrityError, match="cycle"):
        detect_parent_cycle(parent.root_cid, parent.root_cid)

    # A→B→A cycle via lineage map
    a = parent.root_cid
    b = _cid("other-manifest")
    with pytest.raises(ProofCorpusManifestIntegrityError, match="cycle"):
        detect_parent_cycle(a, b, lineage={b: a, a: b})


def test_child_parent_cid_mismatch_rejected() -> None:
    parent = _honest_manifest()
    child = _child_manifest(parent, parent_cid=_cid("wrong-parent"))
    with pytest.raises(ProofCorpusManifestIntegrityError, match="parent_cid"):
        check_append_only_lineage(child, parent)


# ---------------------------------------------------------------------------
# Revocation snapshots
# ---------------------------------------------------------------------------


def test_revocation_snapshot_binds_fields() -> None:
    manifest = _honest_manifest()
    snap = _honest_revocation(manifest.root_cid)
    snap.verify_integrity()

    assert snap.interface == PROOF_REVOCATION_SNAPSHOT_INTERFACE
    assert snap.schema_version == PROOF_REVOCATION_SNAPSHOT_SCHEMA_VERSION
    assert snap.corpus_root_cid == manifest.root_cid
    assert snap.root_cid.startswith("b")
    assert snap.content_digest.startswith("sha256:")
    assert len(snap.entries) == 1
    assert snap.is_revoked(_cid("envelope-revoked"))
    assert not snap.is_revoked(_cid("still-valid"))


def test_revocation_round_trip() -> None:
    snap = _honest_revocation(_cid("corpus"))
    restored = ProofRevocationSnapshot.from_dict(snap.to_dict())
    assert restored.root_cid == snap.root_cid
    assert restored.to_dict() == snap.to_dict()
    restored.verify_integrity()


def test_revocation_hash_cid_mismatch_fails_closed() -> None:
    snap = _honest_revocation(_cid("corpus"))
    payload = snap.to_dict()
    payload["content_digest"] = _digest("tampered")
    with pytest.raises(ProofRevocationIntegrityError, match="content_digest"):
        ProofRevocationSnapshot.from_dict(payload)

    payload = snap.to_dict()
    payload["root_cid"] = _cid("wrong")
    with pytest.raises(ProofRevocationIntegrityError, match="root_cid"):
        ProofRevocationSnapshot.from_dict(payload)


def test_duplicate_revocation_target_rejected() -> None:
    target = _cid("dup-target")
    entries = (
        build_revocation_entry(
            target_cid=target,
            reason_kind=RevocationReasonKind.ERROR,
            reason="first",
            revoked_at="2026-01-01T00:00:00Z",
            issuer_id="issuer",
            ordinal=0,
        ),
        build_revocation_entry(
            target_cid=target,
            reason_kind=RevocationReasonKind.ERROR,
            reason="second",
            revoked_at="2026-01-02T00:00:00Z",
            issuer_id="issuer",
            ordinal=1,
        ),
    )
    with pytest.raises(ProofRevocationIntegrityError, match="duplicate target"):
        ProofRevocationSnapshot(
            corpus_root_cid=_cid("corpus"),
            entries=entries,
        )


def test_revocation_self_cycle_rejected() -> None:
    snap = _honest_revocation(_cid("corpus"))
    with pytest.raises(ProofRevocationIntegrityError, match="cycle"):
        detect_revocation_cycle(snap.root_cid, snap.root_cid)

    # Targeting the snapshot's own eventual root is rejected at construction
    # by checking target against computed root after identity assignment.
    # Self-parent is rejected when parent_cid equals the snapshot root.
    with pytest.raises(ProofRevocationIntegrityError, match="cycle"):
        detect_revocation_cycle(snap.root_cid, snap.root_cid, lineage={})

    # Lineage A→B→A cycle
    a = snap.root_cid
    b = _cid("rev-b")
    with pytest.raises(ProofRevocationIntegrityError, match="cycle"):
        detect_revocation_cycle(a, b, lineage={b: a, a: b})

    # Entry targeting parent_cid is a lineage cycle
    parent = _honest_revocation(_cid("corpus"), targets=[_cid("t1")])
    with pytest.raises(ProofRevocationIntegrityError, match="cycle"):
        ProofRevocationSnapshot(
            corpus_root_cid=parent.corpus_root_cid,
            entries=(
                build_revocation_entry(
                    target_cid=parent.root_cid,
                    reason_kind=RevocationReasonKind.POLICY,
                    reason="kill parent",
                    revoked_at="2026-07-03T00:00:00Z",
                    issuer_id="issuer-legal",
                    ordinal=0,
                ),
            ),
            parent_cid=parent.root_cid,
            generation=2,
        )


def test_revocation_append_only_lineage() -> None:
    corpus = _cid("corpus")
    t1 = _cid("target-1")
    t2 = _cid("target-2")
    parent = _honest_revocation(corpus, targets=[t1], generation=1)
    child = _honest_revocation(
        corpus,
        targets=[t1, t2],
        parent_cid=parent.root_cid,
        generation=2,
    )
    check_revocation_lineage(child, parent)
    assert child.union_revoked_with_ancestors((parent,)) == frozenset({t1, t2})
    assert cumulative_revoked_cids((parent, child)) == frozenset({t1, t2})


def test_revocation_rollback_rejected() -> None:
    corpus = _cid("corpus")
    parent = _honest_revocation(corpus, generation=3)
    child = _honest_revocation(
        corpus,
        targets=list(parent.revoked_cids()),
        parent_cid=parent.root_cid,
        generation=2,
    )
    with pytest.raises(
        ProofRevocationIntegrityError, match="rollback/downgrade"
    ):
        check_revocation_lineage(child, parent)


def test_revocation_drop_parent_target_rejected() -> None:
    corpus = _cid("corpus")
    t1 = _cid("target-1")
    t2 = _cid("target-2")
    parent = _honest_revocation(corpus, targets=[t1, t2], generation=1)
    child = _honest_revocation(
        corpus,
        targets=[t1],  # dropped t2
        parent_cid=parent.root_cid,
        generation=2,
    )
    with pytest.raises(
        ProofRevocationIntegrityError, match="append-only"
    ):
        check_revocation_lineage(child, parent)


def test_bind_manifest_revocation_root() -> None:
    # Build manifest first without revocation root, then snapshot, then rebind.
    base = _honest_manifest()
    snap = _honest_revocation(base.root_cid)
    # Manifest without revocation_root still binds on corpus root.
    bind_manifest_revocation_root(base, snap)

    bound = _honest_manifest(revocation_root_cid=snap.root_cid)
    # corpus root changed because revocation_root is in identity payload
    snap2 = _honest_revocation(bound.root_cid)
    bound2 = _honest_manifest(revocation_root_cid=snap2.root_cid)
    # If revocation_root is part of identity, roots shift — bind after both fixed.
    # Simpler path: empty revocation on manifest, bind only corpus equality.
    bind_manifest_revocation_root(base, snap)

    with pytest.raises(ProofRevocationIntegrityError, match="corpus_root_cid"):
        bind_manifest_revocation_root(base, _honest_revocation(_cid("other")))

    # Wrong revocation root on a fixed corpus: craft snapshot for base root
    # then set a mismatched revocation_root_cid on a copy by reconstructing
    # with same bodies but wrong revocation root that still hashes differently.
    wrong = _honest_manifest(revocation_root_cid=_cid("wrong-rev-root"))
    # Snapshot for wrong's root with different snapshot root
    snap_wrong_corpus = _honest_revocation(wrong.root_cid)
    # Manifest claims different revocation root than snapshot
    mismatched = _honest_manifest(
        revocation_root_cid=_cid("not-the-snapshot"),
    )
    snap_m = _honest_revocation(mismatched.root_cid)
    # mismatched.revocation_root_cid != snap_m.root_cid by construction
    assert mismatched.revocation_root_cid != snap_m.root_cid
    with pytest.raises(
        ProofRevocationIntegrityError, match="revocation_root_cid"
    ):
        bind_manifest_revocation_root(mismatched, snap_m)


def test_revocation_entry_digest_drift_fails_closed() -> None:
    entry = build_revocation_entry(
        target_cid=_cid("t"),
        reason_kind=RevocationReasonKind.WITHDRAWN,
        reason="withdrawn",
        revoked_at="2026-01-01T00:00:00Z",
        issuer_id="issuer",
    )
    payload = entry.to_dict()
    payload["entry_digest"] = _digest("nope")
    with pytest.raises(ProofRevocationIntegrityError, match="entry_digest"):
        RevocationEntry.from_dict(payload)


def test_revocation_mutable_latest_rejected() -> None:
    with pytest.raises(ProofRevocationIntegrityError, match="latest"):
        build_revocation_entry(
            target_cid=_cid("t"),
            reason_kind=RevocationReasonKind.OTHER,
            reason="latest",
            revoked_at="2026-01-01T00:00:00Z",
            issuer_id="issuer",
        )


def test_helpers_build_manifest_and_snapshot() -> None:
    entry = build_manifest_entry(
        entry_id="one",
        path="bodies/one.json",
        content=b"one",
        ordinal=0,
        source_id="src",
    )
    manifest = build_proof_corpus_manifest(
        domain="intent",
        namespace="proof-corpus.intent.v1",
        entries=(entry,),
        sources=(
            SourceBinding(
                source_id="src",
                snapshot_cid=_cid("src-snap"),
            ),
        ),
        producer_id="builder",
    )
    assert manifest.domain == "intent"
    snap = build_revocation_snapshot(
        corpus_root_cid=manifest.root_cid,
        entries=(),
        producer_id="builder",
    )
    assert snap.corpus_root_cid == manifest.root_cid
    bind_manifest_revocation_root(manifest, snap)


def test_registry_kind_mismatch_rejected() -> None:
    with pytest.raises(ProofCorpusManifestIntegrityError, match="registry_kind"):
        _honest_manifest(
            compiler_registry=(
                RegistryBinding(
                    registry_kind=RegistryKind.SOLVER,  # wrong kind for field
                    registry_id="solver-in-compiler",
                    root_cid=_cid("compiler-reg"),
                    version=1,
                ),
            ),
        )


def test_unknown_manifest_field_rejected() -> None:
    payload = _honest_manifest().to_dict()
    payload["unexpected"] = True
    with pytest.raises(ProofCorpusManifestError, match="unknown"):
        ProofCorpusManifest.from_dict(payload)


def test_promotion_receipt_producer_mismatch_rejected() -> None:
    with pytest.raises(ProofCorpusManifestIntegrityError, match="producer_id"):
        _honest_manifest(
            producer_id="alice",
            promotion_receipt=PromotionReceipt(
                receipt_id="r1",
                producer_id="bob",
                promoted_at="2026-01-01T00:00:00Z",
            ),
        )


def test_ordered_entries_are_stable_under_copy() -> None:
    manifest = _honest_manifest()
    payload = copy.deepcopy(manifest.to_dict())
    restored = ProofCorpusManifest.from_dict(payload)
    assert [e.entry_id for e in restored.entries] == [
        e.entry_id for e in manifest.entries
    ]
    assert [e.ordinal for e in restored.entries] == [
        e.ordinal for e in manifest.entries
    ]
