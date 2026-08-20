"""Unit tests for proof-corpus DuckDB repository projection (DQK-028).

Acceptance coverage:

* Envelope bytes and CIDs remain unchanged
* Revoked or contradicted evidence is excluded from authoritative hits
* Tampered objects fail closed
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

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

from ipfs_datasets_py.logic.formalization.compiler import FormalizationArtifact
from ipfs_datasets_py.logic.ir_core.identity import cid_v1_from_digest
from ipfs_datasets_py.logic.ir_core.protocols import AuthorityKind
from ipfs_datasets_py.logic.proof_corpus.duckdb_repository import (
    CORPUS_CATALOG_DDL,
    CORPUS_CATALOG_TABLES,
    PROOF_CORPUS_DUCKDB_REPOSITORY_INTERFACE,
    PROOF_CORPUS_DUCKDB_REPOSITORY_SCHEMA_VERSION,
    AuthoritativeHitReason,
    ContentAddressedBlobStore,
    CorpusObjectKind,
    ProofCorpusDuckDBRepository,
    ProofCorpusDuckDBRepositoryAuthorityError,
    ProofCorpusDuckDBRepositoryError,
    ProofCorpusDuckDBRepositoryIntegrityError,
    build_proof_corpus_duckdb_repository,
    project_envelopes,
    repository_canonical_bytes,
)
from ipfs_datasets_py.logic.proof_corpus.manifest import (
    DEFAULT_MAX_ENTRY_BYTES,
    IndexManifestKind,
    PolicyBinding,
    PromotionReceipt,
    ProofCorpusManifest,
    RegistryBinding,
    RegistryKind,
    SourceBinding,
    build_index_manifest_ref,
    build_manifest_entry,
)
from ipfs_datasets_py.logic.proof_corpus.model import (
    AttestationKind,
    AttestedProofEnvelope,
    CircuitBinding,
    CoverageDeclaration,
    PipelineIdentity,
    ProofResultStatus,
    ScopeBinding,
    TemporalWindow,
    build_attested_proof_envelope,
)
from ipfs_datasets_py.logic.proof_corpus.revocation import (
    RevocationReasonKind,
    build_revocation_entry,
    build_revocation_snapshot,
)
from ipfs_datasets_py.logic.proof_corpus.schemas import (
    ArtifactEnvelope,
    ProofCorpusFamily,
    canonical_bytes,
)


FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures"
INTENT_FIXTURES = FIXTURE_ROOT / "intent_ir" / "admissibility"
LEGAL_FIXTURES = FIXTURE_ROOT / "legal_ir" / "proof_cache"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _cid(label: str) -> str:
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    return cid_v1_from_digest(bytes.fromhex(digest))


def _intent_envelope() -> ArtifactEnvelope:
    artifact = FormalizationArtifact.from_dict(
        _load_json(
            INTENT_FIXTURES / "formal_artifacts" / "benign_skill.json"
        )
    )
    case = next(
        item
        for item in _load_json(INTENT_FIXTURES / "manifest.json")["cases"]
        if item["case_id"] == "benign_skill"
    )
    return ArtifactEnvelope.from_intent_artifact(
        artifact, profile=str(case["profile_id"])
    )


def _legal_envelope() -> ArtifactEnvelope:
    return ArtifactEnvelope.from_legal_record(
        _load_json(LEGAL_FIXTURES / "us_code_552_record.json")
    )


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


def _honest_manifest(**overrides: Any) -> ProofCorpusManifest:
    bodies = {
        "bodies/envelope-a.json": _body("envelope-a"),
        "bodies/envelope-b.json": _body("envelope-b"),
    }
    entries = []
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
    approved = (
        _cid("compiler-reg"),
        _cid("solver-reg"),
        _cid("circuit-reg"),
        _cid("vk-reg"),
    )
    base: dict[str, Any] = {
        "domain": "legal",
        "namespace": "proof-corpus.legal.v1",
        "entries": tuple(entries),
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
        "index_manifests": (
            build_index_manifest_ref(
                index_id="family_index",
                content=b'{"family":["legal"]}',
                index_kind=IndexManifestKind.FAMILY,
            ),
        ),
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


def _honest_attested_envelope(**overrides: Any) -> AttestedProofEnvelope:
    base: dict[str, Any] = {
        "statement_digest": _digest("statement"),
        "assumption_digest": _digest("assumption"),
        "obligation_digest": _digest("obligation"),
        "domain": "legal",
        "logic_family": "deontic",
        "result_authority": AuthorityKind.THEOREM_PROOF,
        "attestation_kind": AttestationKind.DIRECT_PROOF_VERIFICATION,
        "family": ProofCorpusFamily.LEGAL,
        "result_status": ProofResultStatus.PROVED,
        "proof_artifact_cid": _cid("proof-artifact"),
        "proof_bytes_digest": _digest("proof-bytes"),
        "source_snapshot_cid": _cid("source-snapshot"),
        "corpus_root_cid": _cid("corpus-root"),
        "revocation_root_cid": _cid("revocation-root"),
        "policy_id": "policy-legal-strict",
        "ontology_id": "ontology-us-code",
        "adapter_id": "adapter-legal-v1",
        "compiler_id": "compiler-canonical-v1",
        "translation_id": "translation-none",
        "solver_id": "solver-z3",
        "reconstruction_id": "reconstruction-v1",
        "build_manifest_cid": _cid("build-manifest"),
        "source_map_cid": _cid("source-map"),
        "backend_id": "provekit",
        "security_profile": "legal-strict",
        "public_inputs": {
            "statement_digest": _digest("statement"),
            "corpus_root": _cid("corpus-root"),
        },
        "circuit": CircuitBinding(
            circuit_id="legal_constraint",
            circuit_version=1,
            circuit_digest=_digest("circuit"),
            vk_id="legal_constraint_vk",
            vk_version=1,
            vk_digest=_digest("vk"),
            backend_id="provekit",
            proof_system="groth16",
            public_inputs={
                "statement_digest": _digest("statement"),
                "corpus_root": _cid("corpus-root"),
            },
            security_profile="legal-strict",
        ),
        "pipeline": PipelineIdentity(
            source_id="source-us-code-552",
            corpus_id="corpus-legal-v1",
            policy_id="policy-legal-strict",
            ontology_id="ontology-us-code",
            adapter_id="adapter-legal-v1",
            compiler_id="compiler-canonical-v1",
            translation_id="translation-none",
            solver_id="solver-z3",
            reconstruction_id="reconstruction-v1",
        ),
        "scope": ScopeBinding(
            jurisdiction="us-federal",
            tenant="tenant-a",
            subject_ids=("subject-alice",),
            resource_ids=("resource-records",),
            purpose_ids=("purpose-disclosure",),
        ),
        "temporal": TemporalWindow(
            effective_at="2026-01-01T00:00:00Z",
            expires_at="2027-01-01T00:00:00Z",
        ),
        "coverage": CoverageDeclaration(
            covered_selectors=("jurisdiction", "subject", "resource"),
            complete=True,
        ),
        "parent_cids": (_cid("parent-envelope"),),
        "diagnostics": {"notes": "honest fixture"},
        "producer_id": "lig-029-test",
    }
    base.update(overrides)
    return build_attested_proof_envelope(**base)


def _revocation_for(*target_cids: str):
    entries = tuple(
        build_revocation_entry(
            target_cid=cid,
            reason_kind=RevocationReasonKind.WITHDRAWN,
            reason=f"withdrawn:{cid[:12]}",
            revoked_at="2026-06-01T00:00:00Z",
            issuer_id="issuer-authority",
            ordinal=index,
        )
        for index, cid in enumerate(target_cids)
    )
    return build_revocation_snapshot(
        corpus_root_cid=_cid("corpus-root"),
        entries=entries,
        producer_id="issuer-authority",
        generation=1,
    )


# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------


def test_interface_and_schema_versions_are_pinned() -> None:
    repo = build_proof_corpus_duckdb_repository()
    assert repo.interface == PROOF_CORPUS_DUCKDB_REPOSITORY_INTERFACE
    assert repo.schema_version == PROOF_CORPUS_DUCKDB_REPOSITORY_SCHEMA_VERSION
    assert PROOF_CORPUS_DUCKDB_REPOSITORY_INTERFACE == (
        "ProofCorpusDuckDBRepository@1"
    )
    assert (
        PROOF_CORPUS_DUCKDB_REPOSITORY_SCHEMA_VERSION
        == "proof-corpus-duckdb-repository/v1"
    )
    assert repo.catalog_tables() == CORPUS_CATALOG_TABLES
    for table in (
        "corpus_objects",
        "corpus_blob_refs",
        "corpus_revocation_targets",
        "corpus_contradictions",
        "corpus_access_statistics",
    ):
        assert table in CORPUS_CATALOG_TABLES
        assert table in CORPUS_CATALOG_DDL


def test_install_schema_on_fake_connection() -> None:
    statements: list[str] = []

    class _Fake:
        def execute(self, sql: str, params: Any = None) -> None:
            statements.append(sql if params is None else f"{sql}|{params}")

    repo = ProofCorpusDuckDBRepository(connection=_Fake())
    assert any("corpus_objects" in item for item in statements)
    assert repo.stats()["size"] == 0


# ---------------------------------------------------------------------------
# Envelope bytes and CIDs remain unchanged
# ---------------------------------------------------------------------------


def test_envelope_bytes_and_cids_remain_unchanged() -> None:
    envelope = _intent_envelope()
    original_cid = envelope.content_cid
    original_digest = envelope.content_digest
    original_bytes = canonical_bytes(envelope.to_dict())

    repo = build_proof_corpus_duckdb_repository()
    record = repo.put_envelope(envelope)

    assert record.content_cid == original_cid
    assert record.content_digest == original_digest
    assert record.object_kind is CorpusObjectKind.ENVELOPE
    assert record.byte_size == len(original_bytes)

    stored = repo.get_bytes(original_cid)
    assert stored == original_bytes
    assert stored is not original_bytes  # defensive copy

    loaded = repo.get_envelope(original_cid)
    assert loaded.content_cid == original_cid
    assert loaded.content_digest == original_digest
    assert canonical_bytes(loaded.to_dict()) == original_bytes


def test_envelope_put_is_idempotent_for_identical_bytes() -> None:
    envelope = _intent_envelope()
    repo = build_proof_corpus_duckdb_repository()
    first = repo.put_envelope(envelope)
    second = repo.put_envelope(envelope)
    assert first.content_cid == second.content_cid
    assert first.content_digest == second.content_digest
    assert repo.get_bytes(first.content_cid) == canonical_bytes(
        envelope.to_dict()
    )


def test_conflicting_envelope_bytes_for_same_cid_fail_closed() -> None:
    envelope = _intent_envelope()
    repo = build_proof_corpus_duckdb_repository()
    repo.put_envelope(envelope)
    # Force a CA conflict by trying to re-bind the CID with different bytes
    # through the blob store directly.
    with pytest.raises(ProofCorpusDuckDBRepositoryIntegrityError):
        repo.blob_store.put(
            content_cid=envelope.content_cid,
            content_digest=_digest("different"),
            data=b'{"not":"the-envelope"}',
        )


def test_project_envelopes_batch_preserves_identity() -> None:
    intent = _intent_envelope()
    legal = _legal_envelope()
    repo = build_proof_corpus_duckdb_repository()
    records = project_envelopes(repo, (intent, legal))
    assert len(records) == 2
    assert {item.content_cid for item in records} == {
        intent.content_cid,
        legal.content_cid,
    }
    assert repo.get_bytes(intent.content_cid) == canonical_bytes(
        intent.to_dict()
    )
    assert repo.get_bytes(legal.content_cid) == canonical_bytes(legal.to_dict())


def test_manifest_bytes_and_cid_stable() -> None:
    manifest = _honest_manifest()
    original_cid = manifest.content_cid
    original_digest = manifest.content_digest
    original_bytes = repository_canonical_bytes(manifest.to_dict())

    repo = build_proof_corpus_duckdb_repository()
    record = repo.put_manifest(manifest)
    assert record.content_cid == original_cid
    assert record.content_digest == original_digest
    assert repo.get_bytes(original_cid) == original_bytes
    loaded = repo.get_manifest(original_cid)
    assert loaded.content_cid == original_cid
    assert loaded.content_digest == original_digest


def test_attested_envelope_and_attestation_indexed_by_verified_cid() -> None:
    attested = _honest_attested_envelope()
    repo = build_proof_corpus_duckdb_repository()
    att_record = repo.put_attested_envelope(attested)
    assert att_record.content_cid == attested.content_cid
    assert att_record.object_kind is CorpusObjectKind.ATTESTED_ENVELOPE
    assert repo.get_bytes(attested.content_cid) == repository_canonical_bytes(
        attested.to_dict()
    )

    payload = {
        "backend": "simulated",
        "envelope_cid": attested.content_cid,
        "status": "pass",
        "statement_digest": attested.statement_digest,
    }
    att = repo.put_attestation(payload, subject_cid=attested.content_cid)
    assert att.object_kind is CorpusObjectKind.ATTESTATION
    assert att.subject_cid == attested.content_cid
    loaded = repo.get_attestation_payload(att.content_cid)
    assert loaded["envelope_cid"] == attested.content_cid
    assert loaded["status"] == "pass"


# ---------------------------------------------------------------------------
# Revoked or contradicted evidence excluded from authoritative hits
# ---------------------------------------------------------------------------


def test_revoked_evidence_excluded_from_authoritative_hits() -> None:
    envelope = _intent_envelope()
    repo = build_proof_corpus_duckdb_repository()
    repo.put_envelope(envelope)

    before = repo.get_authoritative(envelope.content_cid)
    assert before.hit and before.authoritative
    assert before.reason is AuthoritativeHitReason.HIT
    assert envelope.content_cid in repo.list_authoritative_cids()

    snapshot = _revocation_for(envelope.content_cid)
    rev_record = repo.put_revocation(snapshot)
    assert rev_record.object_kind is CorpusObjectKind.REVOCATION
    assert repo.is_revoked(envelope.content_cid)

    after = repo.get_authoritative(envelope.content_cid)
    assert after.hit is True
    assert after.authoritative is False
    assert after.reason is AuthoritativeHitReason.REVOKED
    assert envelope.content_cid not in repo.list_authoritative_cids()

    with pytest.raises(ProofCorpusDuckDBRepositoryAuthorityError):
        repo.get_envelope(envelope.content_cid)

    # Audit path still returns exact original bytes / typed envelope.
    audited = repo.get_envelope(envelope.content_cid, authoritative_only=False)
    assert audited.content_cid == envelope.content_cid
    assert repo.get_bytes(envelope.content_cid) == canonical_bytes(
        envelope.to_dict()
    )


def test_contradicted_evidence_excluded_from_authoritative_hits() -> None:
    a = _intent_envelope()
    b = _legal_envelope()
    repo = build_proof_corpus_duckdb_repository()
    repo.put_envelope(a)
    repo.put_envelope(b)

    repo.record_contradiction(
        a.content_cid,
        b.content_cid,
        reason="opposing-family-conflict",
    )
    assert repo.is_contradicted(a.content_cid)
    assert not repo.is_contradicted(b.content_cid)

    hit_a = repo.get_authoritative(a.content_cid)
    assert hit_a.hit and not hit_a.authoritative
    assert hit_a.reason is AuthoritativeHitReason.CONTRADICTED

    hit_b = repo.get_authoritative(b.content_cid)
    assert hit_b.hit and hit_b.authoritative

    authoritative = repo.list_authoritative_cids(
        object_kind=CorpusObjectKind.ENVELOPE
    )
    assert a.content_cid not in authoritative
    assert b.content_cid in authoritative

    with pytest.raises(ProofCorpusDuckDBRepositoryAuthorityError):
        repo.get_envelope(a.content_cid)


def test_revocation_of_attestation_subject_does_not_rewrite_bytes() -> None:
    envelope = _legal_envelope()
    repo = build_proof_corpus_duckdb_repository()
    repo.put_envelope(envelope)
    att = repo.put_attestation(
        {"kind": "legal-constraint", "status": "pass", "v": 1},
        subject_cid=envelope.content_cid,
        family="legal",
        profile=envelope.profile,
    )
    original_att_bytes = repo.get_bytes(att.content_cid)

    repo.put_revocation(_revocation_for(att.content_cid))
    assert repo.get_authoritative(att.content_cid).reason is (
        AuthoritativeHitReason.REVOKED
    )
    assert repo.get_bytes(att.content_cid) == original_att_bytes


def test_list_authoritative_filters_kind_family_profile() -> None:
    intent = _intent_envelope()
    legal = _legal_envelope()
    repo = build_proof_corpus_duckdb_repository()
    repo.put_envelope(intent)
    repo.put_envelope(legal)
    repo.put_manifest(_honest_manifest())

    only_intent = repo.list_authoritative_cids(
        object_kind=CorpusObjectKind.ENVELOPE,
        family="intent",
    )
    assert only_intent == (intent.content_cid,)

    by_profile = repo.list_authoritative_cids(profile=legal.profile)
    assert legal.content_cid in by_profile
    assert intent.content_cid not in by_profile or intent.profile == legal.profile


# ---------------------------------------------------------------------------
# Tampered objects fail closed
# ---------------------------------------------------------------------------


def test_tampered_blob_fails_closed_on_lookup() -> None:
    envelope = _intent_envelope()
    repo = build_proof_corpus_duckdb_repository()
    repo.put_envelope(envelope)

    repo.inject_tampered_blob_for_tests(
        envelope.content_cid, b'{"tampered":true,"payload":"nope"}'
    )
    hit = repo.lookup(envelope.content_cid)
    assert hit.hit is False
    assert hit.authoritative is False
    assert hit.reason is AuthoritativeHitReason.TAMPERED
    assert repo.stats()["tamper_rejections"] >= 1

    with pytest.raises(ProofCorpusDuckDBRepositoryIntegrityError):
        repo.get_envelope(envelope.content_cid)


def test_tampered_blob_fails_closed_on_get_bytes() -> None:
    envelope = _intent_envelope()
    repo = build_proof_corpus_duckdb_repository()
    repo.put_envelope(envelope)
    repo.inject_tampered_blob_for_tests(envelope.content_cid, b"corrupt")

    # get_bytes re-verifies via ContentAddressedBlobStore.get
    with pytest.raises(ProofCorpusDuckDBRepositoryIntegrityError):
        repo.get_bytes(envelope.content_cid)


def test_malformed_envelope_put_fails_closed() -> None:
    repo = build_proof_corpus_duckdb_repository()
    with pytest.raises(ProofCorpusDuckDBRepositoryIntegrityError):
        repo.put_envelope({"family": "intent", "not": "an-envelope"})


def test_attestation_claimed_digest_mismatch_fails_closed() -> None:
    envelope = _intent_envelope()
    repo = build_proof_corpus_duckdb_repository()
    repo.put_envelope(envelope)
    with pytest.raises(ProofCorpusDuckDBRepositoryIntegrityError):
        repo.put_attestation(
            {"status": "pass"},
            subject_cid=envelope.content_cid,
            content_digest=_digest("wrong"),
        )


def test_unknown_cid_is_miss_not_authoritative() -> None:
    repo = build_proof_corpus_duckdb_repository()
    missing = _cid("never-indexed")
    hit = repo.get_authoritative(missing)
    assert not hit.hit
    assert not hit.authoritative
    assert hit.reason is AuthoritativeHitReason.MISS
    with pytest.raises(ProofCorpusDuckDBRepositoryError):
        repo.get_bytes(missing)


# ---------------------------------------------------------------------------
# Content-addressed store isolation
# ---------------------------------------------------------------------------


def test_blob_store_never_holds_index_authority() -> None:
    """Index rows exclude identity-bearing body bytes."""

    envelope = _intent_envelope()
    repo = build_proof_corpus_duckdb_repository()
    record = repo.put_envelope(envelope)
    payload = record.to_dict()
    # Projection metadata only — no full envelope body.
    assert "artifact" not in payload
    assert "data" not in payload
    assert payload["content_cid"] == envelope.content_cid
    assert "metadata" in payload
    assert "artifact_cid" in payload["metadata"]


def test_content_addressed_blob_store_standalone() -> None:
    store = ContentAddressedBlobStore()
    data = b'{"hello":"world"}'
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
    blob = store.put(content_cid=cid, content_digest=digest, data=data)
    assert store.get_bytes(cid) == data
    assert blob.byte_size == len(data)
    # Idempotent identical put.
    again = store.put(content_cid=cid, content_digest=digest, data=data)
    assert again.data == data
    with pytest.raises(ProofCorpusDuckDBRepositoryIntegrityError):
        store.put(
            content_cid=cid,
            content_digest=_digest("other"),
            data=b"other",
        )


def test_clear_resets_index_and_blobs() -> None:
    repo = build_proof_corpus_duckdb_repository()
    envelope = _intent_envelope()
    repo.put_envelope(envelope)
    repo.put_revocation(_revocation_for(envelope.content_cid))
    repo.clear()
    assert repo.stats()["size"] == 0
    assert repo.stats()["blobs"] == 0
    assert repo.list_authoritative_cids() == ()
    assert not repo.is_revoked(envelope.content_cid)


def test_kind_mismatch_is_not_authoritative() -> None:
    envelope = _intent_envelope()
    repo = build_proof_corpus_duckdb_repository()
    repo.put_envelope(envelope)
    hit = repo.lookup(
        envelope.content_cid,
        expected_kind=CorpusObjectKind.MANIFEST,
    )
    assert hit.hit
    assert not hit.authoritative
    assert hit.reason is AuthoritativeHitReason.KIND_MISMATCH


def test_revocation_snapshot_round_trip() -> None:
    envelope = _intent_envelope()
    snapshot = _revocation_for(envelope.content_cid)
    original_bytes = repository_canonical_bytes(snapshot.to_dict())
    repo = build_proof_corpus_duckdb_repository()
    repo.put_envelope(envelope)
    repo.put_revocation(snapshot)
    loaded = repo.get_revocation(snapshot.content_cid)
    assert loaded.content_cid == snapshot.content_cid
    assert loaded.content_digest == snapshot.content_digest
    assert repo.get_bytes(snapshot.content_cid) == original_bytes
    assert list(loaded.entries)[0].target_cid == envelope.content_cid
