from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from io import BytesIO

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")

import pytest

import ipfs_datasets_py.wallet.analytics as wallet_analytics
from ipfs_datasets_py.wallet import (
    AccessDeniedError,
    ApprovalRequiredError,
    DataWalletError,
    DeterministicLocationDistanceProofBackend,
    DeterministicLocationRegionProofBackend,
    ProofReceipt,
    WalletInvocation,
    WalletService,
)
from ipfs_datasets_py.wallet.manifest import canonical_bytes
from ipfs_datasets_py.wallet.privacy import noisy_count
from ipfs_datasets_py.wallet.storage import (
    FilecoinEncryptedBlobStore,
    IPFSEncryptedBlobStore,
    LocalEncryptedBlobStore,
    ReplicatedEncryptedBlobStore,
    S3EncryptedBlobStore,
)
from ipfs_datasets_py.wallet.ucan import (
    WALLET_UCAN_CONFORMANCE_FIXTURE_ID,
    WALLET_UCAN_TOKEN_PREFIX,
    invocation_from_token,
    invocation_to_token,
    invocation_to_ucan_profile_payload,
    resource_for_export,
    resource_for_location,
    resource_for_record,
    resource_for_wallet,
    sign_invocation,
    validate_ucan_profile_payload,
    validate_wallet_ucan_conformance_fixture,
    wallet_ucan_conformance_fixture,
    wallet_ucan_profile,
)


OWNER = "did:key:owner"
ADVOCATE = "did:key:advocate"
CASE_MANAGER = "did:key:case-manager"
SECOND_CONTROLLER = "did:key:second-controller"


class FakeIPFSBackend:
    def __init__(self) -> None:
        self.blocks: dict[str, bytes] = {}
        self.pinned: list[str] = []

    def add_bytes(self, data: bytes, *, pin: bool = True) -> str:
        cid = f"fakecid-{len(self.blocks) + 1}"
        self.blocks[cid] = data
        if pin:
            self.pinned.append(cid)
        return cid

    def cat(self, cid: str) -> bytes:
        return self.blocks[cid]


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.metadata: dict[tuple[str, str], dict[str, str]] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, Metadata: dict[str, str]):
        self.objects[(Bucket, Key)] = Body
        self.metadata[(Bucket, Key)] = Metadata

    def get_object(self, *, Bucket: str, Key: str):
        return {"Body": BytesIO(self.objects[(Bucket, Key)])}


class FakeFilecoinBackend:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def store_bytes(self, data: bytes, *, sha256: str) -> str:
        locator = f"piece-{len(self.objects) + 1}-{sha256[:12]}"
        self.objects[locator] = data
        return locator

    def retrieve_bytes(self, locator: str) -> bytes:
        return self.objects[locator]


def test_wallet_add_document_encrypts_and_decrypts_for_owner(tmp_path):
    service = WalletService(storage_dir=tmp_path / "wallet-store")
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "benefits.txt"
    source.write_text("SNAP approval letter for household benefits", encoding="utf-8")

    record = service.add_document(wallet.wallet_id, source)

    assert record.data_type == "document"
    assert service.decrypt_record(wallet.wallet_id, record.record_id, actor_did=OWNER) == source.read_bytes()
    manifest = service.get_wallet_manifest(wallet.wallet_id)
    assert manifest["records"][0]["public_descriptor"] == "document"
    assert "benefits.txt" not in service.get_wallet_manifest_canonical(wallet.wallet_id)


def test_unauthorized_delegate_cannot_decrypt_without_grant(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "id.txt"
    source.write_text("private identifier", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)

    with pytest.raises(AccessDeniedError):
        service.decrypt_record(wallet.wallet_id, record.record_id, actor_did=ADVOCATE)


def test_analyze_grant_does_not_allow_plaintext_decrypt(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "case-note.txt"
    source.write_text("Housing instability and utility shutoff risk.", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, record.record_id)],
        abilities=["record/analyze"],
        caveats={"purpose": "service_matching"},
    )

    artifact = service.analyze_record_summary(
        wallet.wallet_id,
        record.record_id,
        actor_did=ADVOCATE,
        grant_id=grant.grant_id,
    )

    assert artifact.artifact_type == "summary"
    with pytest.raises(AccessDeniedError):
        service.decrypt_record(
            wallet.wallet_id,
            record.record_id,
            actor_did=ADVOCATE,
            grant_id=grant.grant_id,
        )


def test_redacted_document_analysis_masks_sensitive_fields(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "intake.txt"
    source.write_text(
        "Jane can be reached at jane@example.org or 503-555-1212. "
        "SSN 123-45-6789. Lives at 123 Main St. Needs rent and SNAP help.",
        encoding="utf-8",
    )
    record = service.add_document(wallet.wallet_id, source)

    result = service.analyze_document_with_redaction(
        wallet.wallet_id,
        record.record_id,
        actor_did=OWNER,
    )

    output = result["output"]
    serialized = json.dumps(output)
    assert result["artifact"].artifact_type == "redacted_document_analysis"
    assert output["output_policy"] == "redacted_derived_only"
    assert "jane@example.org" not in serialized
    assert "503-555-1212" not in serialized
    assert "123-45-6789" not in serialized
    assert "123 Main St" not in serialized
    assert output["redaction_counts"]["email"] == 1
    assert output["redaction_counts"]["phone"] == 1
    assert output["redaction_counts"]["ssn"] == 1
    assert output["redaction_counts"]["address"] == 1
    assert set(output["derived_facts"]["need_categories"]) >= {"housing", "food"}
    actions = [event.action for event in service.get_audit_log(wallet.wallet_id)]
    assert "record/analyze_redacted" in actions


def test_document_vector_profile_is_redacted_and_hashed(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "case-plan.txt"
    source.write_text(
        "Jane can be reached at jane@example.org or 503-555-1212. "
        "She needs rent assistance, SNAP support, and a clinic appointment.",
        encoding="utf-8",
    )
    record = service.add_document(wallet.wallet_id, source)

    result = service.create_document_vector_profile(
        wallet.wallet_id,
        record.record_id,
        actor_did=OWNER,
        chunk_size_words=10,
    )

    output = result["output"]
    serialized = json.dumps(output)
    assert result["artifact"].artifact_type == "redacted_document_vector_profile"
    assert output["output_policy"] == "encrypted_vector_profile"
    assert "jane@example.org" not in serialized
    assert "503-555-1212" not in serialized
    assert "Jane" not in serialized
    assert output["profile"]["profile_type"] == "redacted_lexical_hash_vector"
    assert output["profile"]["chunk_count"] >= 1
    assert all(len(chunk_hash) == 64 for chunk_hash in output["profile"]["chunk_hashes"])
    assert output["profile"]["feature_vector"]["housing"] >= 1
    assert output["profile"]["feature_vector"]["food"] >= 1
    assert output["profile"]["feature_vector"]["health"] >= 1
    actions = [event.action for event in service.get_audit_log(wallet.wallet_id)]
    assert "record/vector_profile" in actions


def test_cross_record_redacted_analysis_respects_grant_scope(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    housing = tmp_path / "housing.txt"
    housing.write_text(
        "Jane at jane@example.org needs rent support after a utility shutoff notice.",
        encoding="utf-8",
    )
    food_health = tmp_path / "food-health.txt"
    food_health.write_text(
        "Call 503-555-1212 about SNAP enrollment and medical clinic transportation.",
        encoding="utf-8",
    )
    excluded = tmp_path / "excluded.txt"
    excluded.write_text("SSN 123-45-6789 and a private income appeal.", encoding="utf-8")
    housing_record = service.add_document(wallet.wallet_id, housing)
    food_health_record = service.add_document(wallet.wallet_id, food_health)
    excluded_record = service.add_document(wallet.wallet_id, excluded)
    allowed_ids = [housing_record.record_id, food_health_record.record_id]
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, record_id) for record_id in allowed_ids],
        abilities=["record/analyze"],
        caveats={"output_types": ["redacted_derived_only"], "record_ids": allowed_ids},
    )

    result = service.analyze_documents_with_redaction(
        wallet.wallet_id,
        allowed_ids,
        actor_did=ADVOCATE,
        grant_id=grant.grant_id,
    )

    output = result["output"]
    serialized = json.dumps(output)
    assert result["artifact"].artifact_type == "redacted_cross_document_analysis"
    assert result["artifact"].source_record_ids == allowed_ids
    assert output["output_policy"] == "redacted_derived_only"
    assert output["source_record_count"] == 2
    assert "Jane" not in serialized
    assert "jane@example.org" not in serialized
    assert "503-555-1212" not in serialized
    assert "123-45-6789" not in serialized
    assert set(output["derived_facts"]["need_categories"]) >= {"housing", "food", "health"}
    assert output["derived_facts"]["category_record_counts"]["housing"] == 1
    assert output["derived_facts"]["category_record_counts"]["food"] == 1
    assert output["derived_facts"]["category_record_counts"]["health"] == 1
    actions = [event.action for event in service.get_audit_log(wallet.wallet_id)]
    assert "record/analyze_redacted_batch" in actions

    with pytest.raises(AccessDeniedError):
        service.analyze_documents_with_redaction(
            wallet.wallet_id,
            [*allowed_ids, excluded_record.record_id],
            actor_did=ADVOCATE,
            grant_id=grant.grant_id,
        )


def test_document_text_extraction_uses_wallet_boundary_and_redacts(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "extract.txt"
    source.write_text(
        "Jane can be reached at jane@example.org or 503-555-1212. "
        "She needs rent assistance and SNAP enrollment.",
        encoding="utf-8",
    )
    record = service.add_document(wallet.wallet_id, source)

    result = service.extract_document_text_with_redaction(
        wallet.wallet_id,
        record.record_id,
        actor_did=OWNER,
        max_chars=500,
    )

    output = result["output"]
    serialized = json.dumps(output)
    assert result["artifact"].artifact_type == "redacted_document_text_extraction"
    assert output["output_policy"] == "redacted_extracted_text"
    assert output["extraction"]["method"] == "text"
    assert "jane@example.org" not in serialized
    assert "503-555-1212" not in serialized
    assert "[REDACTED_EMAIL]" in output["text"]
    assert "[REDACTED_PHONE]" in output["text"]
    assert set(output["derived_facts"]["need_categories"]) >= {"housing", "food"}
    actions = [event.action for event in service.get_audit_log(wallet.wallet_id)]
    assert "record/extract_text_redacted" in actions


def test_document_form_analysis_returns_redacted_field_metadata(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "intake-form.txt"
    source.write_text(
        "Full name: Jane Example\n"
        "Email: jane@example.org\n"
        "Phone: 503-555-1212\n"
        "Rent assistance required: yes\n"
        "SNAP enrollment: yes\n",
        encoding="utf-8",
    )
    record = service.add_document(wallet.wallet_id, source)

    result = service.analyze_document_form_with_redaction(
        wallet.wallet_id,
        record.record_id,
        actor_did=OWNER,
    )

    output = result["output"]
    serialized = json.dumps(output)
    assert result["artifact"].artifact_type == "redacted_document_form_analysis"
    assert output["output_policy"] == "redacted_form_analysis"
    assert output["form"]["method"] == "text"
    assert output["form"]["field_count"] >= 5
    assert output["form"]["data_type_counts"]["email"] == 1
    assert output["form"]["data_type_counts"]["phone"] == 1
    assert "Jane Example" not in serialized
    assert "jane@example.org" not in serialized
    assert "503-555-1212" not in serialized
    assert set(output["derived_facts"]["need_categories"]) >= {"housing", "food"}
    actions = [event.action for event in service.get_audit_log(wallet.wallet_id)]
    assert "record/analyze_form_redacted" in actions


def test_redacted_graphrag_returns_safe_graph_without_entity_text(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    housing = tmp_path / "housing.txt"
    food = tmp_path / "food.txt"
    housing.write_text(
        "Jane Example emailed jane@example.org about rent assistance and utility shutoff support.",
        encoding="utf-8",
    )
    food.write_text(
        "Call 503-555-1212 about SNAP enrollment and medical clinic referrals.",
        encoding="utf-8",
    )
    housing_record = service.add_document(wallet.wallet_id, housing)
    food_record = service.add_document(wallet.wallet_id, food)

    result = service.create_redacted_graphrag(
        wallet.wallet_id,
        [housing_record.record_id, food_record.record_id],
        actor_did=OWNER,
    )

    output = result["output"]
    serialized = json.dumps(output)
    assert result["artifact"].artifact_type == "redacted_document_graphrag"
    assert output["output_policy"] == "redacted_graphrag"
    assert output["backend_policy"] == {
        "backend_id": "wallet-local-redacted-graphrag-v1",
        "execution_boundary": "wallet-local",
        "model_backed": False,
        "extractor": "processors.graphrag_integrator.GraphRAGIntegrator",
        "extractor_mode": "legacy-regex-compatibility",
        "plaintext_scope": "wallet-service-only",
        "returned_entity_scope": "entity_type_counts_only",
    }
    assert output["source_record_count"] == 2
    assert output["graph"]["graph_type"] == "redacted_category_entity_graph"
    assert output["graph"]["node_count"] >= 4
    assert output["graph"]["category_record_counts"]["housing"] == 1
    assert output["graph"]["category_record_counts"]["food"] == 1
    assert output["graph"]["category_record_counts"]["health"] == 1
    assert "Jane Example" not in serialized
    assert "jane@example.org" not in serialized
    assert "503-555-1212" not in serialized
    assert "SNAP enrollment" not in serialized
    actions = [event.action for event in service.get_audit_log(wallet.wallet_id)]
    assert "record/graphrag_redacted" in actions


def test_redacted_graphrag_rejects_model_backed_extractor(tmp_path, monkeypatch):
    import ipfs_datasets_py.processors.graphrag_integrator as graphrag_integrator

    class ModelBackedGraphRAGIntegrator:
        use_real_models = True

        def __init__(self, *args, **kwargs) -> None:
            pass

        def extract_entities(self, text: str):
            return []

    monkeypatch.setattr(graphrag_integrator, "GraphRAGIntegrator", ModelBackedGraphRAGIntegrator)
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "housing.txt"
    source.write_text("Jane Example needs rent assistance.", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)

    with pytest.raises(RuntimeError, match="model-backed entity extraction"):
        service.create_redacted_graphrag(
            wallet.wallet_id,
            [record.record_id],
            actor_did=OWNER,
        )


def test_document_output_type_caveats_are_enforced_by_operation(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "output-caveat.txt"
    source.write_text("Housing plan with protected plaintext.", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)
    resource = resource_for_record(wallet.wallet_id, record.record_id)
    summary_only = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource],
        abilities=["record/analyze", "record/decrypt"],
        caveats={"output_types": ["summary"]},
    )
    plaintext_only = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=CASE_MANAGER,
        resources=[resource],
        abilities=["record/analyze", "record/decrypt"],
        caveats={"output_types": ["plaintext"]},
    )
    redacted_only = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did="did:key:redacted-reviewer",
        resources=[resource],
        abilities=["record/analyze"],
        caveats={"output_types": ["redacted_derived_only"]},
    )

    assert service.analyze_record_summary(
        wallet.wallet_id,
        record.record_id,
        actor_did=ADVOCATE,
        grant_id=summary_only.grant_id,
    ).artifact_type == "summary"
    assert service.decrypt_record(
        wallet.wallet_id,
        record.record_id,
        actor_did=CASE_MANAGER,
        grant_id=plaintext_only.grant_id,
    ) == source.read_bytes()
    assert service.analyze_document_with_redaction(
        wallet.wallet_id,
        record.record_id,
        actor_did="did:key:redacted-reviewer",
        grant_id=redacted_only.grant_id,
    )["output"]["output_policy"] == "redacted_derived_only"

    vector_profile_grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did="did:key:vector-reviewer",
        resources=[resource],
        abilities=["record/analyze"],
        caveats={"output_types": ["vector_profile"]},
    )
    assert service.create_document_vector_profile(
        wallet.wallet_id,
        record.record_id,
        actor_did="did:key:vector-reviewer",
        grant_id=vector_profile_grant.grant_id,
    )["output"]["output_policy"] == "encrypted_vector_profile"

    extracted_text_grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did="did:key:extractor",
        resources=[resource],
        abilities=["record/analyze"],
        caveats={"output_types": ["redacted_extracted_text"]},
    )
    assert service.extract_document_text_with_redaction(
        wallet.wallet_id,
        record.record_id,
        actor_did="did:key:extractor",
        grant_id=extracted_text_grant.grant_id,
    )["output"]["output_policy"] == "redacted_extracted_text"

    form_analysis_grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did="did:key:form-reviewer",
        resources=[resource],
        abilities=["record/analyze"],
        caveats={"output_types": ["redacted_form_analysis"]},
    )
    assert service.analyze_document_form_with_redaction(
        wallet.wallet_id,
        record.record_id,
        actor_did="did:key:form-reviewer",
        grant_id=form_analysis_grant.grant_id,
    )["output"]["output_policy"] == "redacted_form_analysis"

    graphrag_grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did="did:key:graphrag-reviewer",
        resources=[resource],
        abilities=["record/analyze"],
        caveats={"output_types": ["redacted_graphrag"]},
    )
    assert service.create_redacted_graphrag(
        wallet.wallet_id,
        [record.record_id],
        actor_did="did:key:graphrag-reviewer",
        grant_id=graphrag_grant.grant_id,
    )["output"]["output_policy"] == "redacted_graphrag"

    with pytest.raises(AccessDeniedError, match="output_types"):
        service.decrypt_record(
            wallet.wallet_id,
            record.record_id,
            actor_did=ADVOCATE,
            grant_id=summary_only.grant_id,
        )
    with pytest.raises(AccessDeniedError, match="output_types"):
        service.analyze_record_summary(
            wallet.wallet_id,
            record.record_id,
            actor_did=CASE_MANAGER,
            grant_id=plaintext_only.grant_id,
        )
    with pytest.raises(AccessDeniedError, match="output_types"):
        service.analyze_document_with_redaction(
            wallet.wallet_id,
            record.record_id,
            actor_did=ADVOCATE,
            grant_id=summary_only.grant_id,
        )
    with pytest.raises(AccessDeniedError, match="output_types"):
        service.create_document_vector_profile(
            wallet.wallet_id,
            record.record_id,
            actor_did=ADVOCATE,
            grant_id=summary_only.grant_id,
        )
    with pytest.raises(AccessDeniedError, match="output_types"):
        service.extract_document_text_with_redaction(
            wallet.wallet_id,
            record.record_id,
            actor_did=ADVOCATE,
            grant_id=summary_only.grant_id,
        )
    with pytest.raises(AccessDeniedError, match="output_types"):
        service.analyze_document_form_with_redaction(
            wallet.wallet_id,
            record.record_id,
            actor_did=ADVOCATE,
            grant_id=summary_only.grant_id,
        )
    with pytest.raises(AccessDeniedError, match="output_types"):
        service.create_redacted_graphrag(
            wallet.wallet_id,
            [record.record_id],
            actor_did=ADVOCATE,
            grant_id=summary_only.grant_id,
        )


def test_decrypt_grant_wraps_key_for_delegate(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "medical.txt"
    source.write_text("medical document plaintext", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, record.record_id)],
        abilities=["record/decrypt"],
    )

    assert (
        service.decrypt_record(
            wallet.wallet_id,
            record.record_id,
            actor_did=ADVOCATE,
            grant_id=grant.grant_id,
        )
        == b"medical document plaintext"
    )


def test_delegated_grant_attenuates_and_revokes_with_parent(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "case-plan.txt"
    source.write_text("housing case plan and benefit notes", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)
    resource = resource_for_record(wallet.wallet_id, record.record_id)
    parent = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource],
        abilities=["record/analyze", "record/share"],
        caveats={"purpose": "case_review", "max_delegation_depth": 1},
    )

    child = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=ADVOCATE,
        audience_did=CASE_MANAGER,
        resources=[resource],
        abilities=["record/analyze"],
        caveats={"purpose": "case_review"},
        parent_grant_id=parent.grant_id,
    )
    artifact = service.analyze_record_summary(
        wallet.wallet_id,
        record.record_id,
        actor_did=CASE_MANAGER,
        grant_id=child.grant_id,
    )

    assert child.proof_chain == [parent.grant_id]
    assert artifact.artifact_type == "summary"
    with pytest.raises(AccessDeniedError, match="Delegated ability exceeds"):
        service.create_grant(
            wallet_id=wallet.wallet_id,
            issuer_did=ADVOCATE,
            audience_did=CASE_MANAGER,
            resources=[resource],
            abilities=["record/decrypt"],
            caveats={"purpose": "case_review"},
            parent_grant_id=parent.grant_id,
        )
    with pytest.raises(AccessDeniedError, match="purpose"):
        service.create_grant(
            wallet_id=wallet.wallet_id,
            issuer_did=ADVOCATE,
            audience_did=CASE_MANAGER,
            resources=[resource],
            abilities=["record/analyze"],
            caveats={"purpose": "different"},
            parent_grant_id=parent.grant_id,
        )
    with pytest.raises(AccessDeniedError, match="depth"):
        service.create_grant(
            wallet_id=wallet.wallet_id,
            issuer_did=CASE_MANAGER,
            audience_did="did:key:second-hop",
            resources=[resource],
            abilities=["record/analyze"],
            caveats={"purpose": "case_review"},
            parent_grant_id=child.grant_id,
        )

    snapshot = service.export_wallet_snapshot(wallet.wallet_id)
    restored = WalletService(storage_dir=tmp_path / "restored")
    restored.import_wallet_snapshot(snapshot)
    assert restored.grants[child.grant_id].proof_chain == [parent.grant_id]
    tampered_snapshot = json.loads(json.dumps(snapshot))
    for grant_data in tampered_snapshot["grants"]:
        if grant_data["grant_id"] == child.grant_id:
            grant_data["abilities"] = ["record/decrypt"]
    tampered = WalletService(storage_dir=tmp_path / "tampered")
    tampered.import_wallet_snapshot(tampered_snapshot)
    with pytest.raises(AccessDeniedError, match="exceeds parent"):
        tampered.decrypt_record(
            wallet.wallet_id,
            record.record_id,
            actor_did=CASE_MANAGER,
            grant_id=child.grant_id,
        )

    service.revoke_grant(wallet.wallet_id, parent.grant_id, actor_did=OWNER)

    assert service.grants[parent.grant_id].status == "revoked"
    assert service.grants[child.grant_id].status == "revoked"
    with pytest.raises(AccessDeniedError):
        service.analyze_record_summary(
            wallet.wallet_id,
            record.record_id,
            actor_did=CASE_MANAGER,
            grant_id=child.grant_id,
        )
    assert all(
        wrap.status == "revoked"
        for wrap in service.versions[record.current_version_id].key_wraps
        if wrap.grant_id == child.grant_id
    )


def test_emergency_revoke_requires_threshold_and_rotates_active_records(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(
        owner_did=OWNER,
        controller_dids=[OWNER, SECOND_CONTROLLER],
        governance_policy={"threshold": 2},
    )
    source = tmp_path / "emergency.txt"
    source.write_text("emergency revoke plaintext", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)
    old_version_id = record.current_version_id
    resource = resource_for_record(wallet.wallet_id, record.record_id)
    parent = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource],
        abilities=["record/analyze", "record/share"],
        caveats={"purpose": "case_review", "max_delegation_depth": 1},
    )
    child = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=ADVOCATE,
        audience_did=CASE_MANAGER,
        resources=[resource],
        abilities=["record/analyze"],
        caveats={"purpose": "case_review"},
        parent_grant_id=parent.grant_id,
    )

    with pytest.raises(ApprovalRequiredError):
        service.emergency_revoke(wallet.wallet_id, actor_did=OWNER)

    approval = service.request_approval(
        wallet.wallet_id,
        requested_by=OWNER,
        operation="wallet/emergency_revoke",
        resources=[resource_for_wallet(wallet.wallet_id)],
        abilities=["wallet/admin"],
    )
    service.approve_approval(wallet.wallet_id, approval_id=approval.approval_id, approver_did=OWNER)
    service.approve_approval(
        wallet.wallet_id,
        approval_id=approval.approval_id,
        approver_did=SECOND_CONTROLLER,
    )

    report = service.emergency_revoke(
        wallet.wallet_id,
        actor_did=OWNER,
        approval_id=approval.approval_id,
        reason="suspected_compromise",
    )

    assert report["revoked_grant_ids"] == [parent.grant_id, child.grant_id]
    assert report["rotated_record_ids"] == [record.record_id]
    assert report["rotation_errors"] == {}
    assert service.grants[parent.grant_id].status == "revoked"
    assert service.grants[child.grant_id].status == "revoked"
    assert service.records[record.record_id].current_version_id != old_version_id
    with pytest.raises(AccessDeniedError):
        service.analyze_record_summary(
            wallet.wallet_id,
            record.record_id,
            actor_did=CASE_MANAGER,
            grant_id=child.grant_id,
        )
    actions = [event.action for event in service.get_audit_log(wallet.wallet_id)]
    assert "wallet/emergency_revoke" in actions
    assert "record/key_rotate" in actions


def test_record_key_rotation_reencrypts_current_version_and_preserves_active_grants(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    owner_secret = b"o" * 32
    delegate_secret = b"d" * 32
    source = tmp_path / "rotation.txt"
    source.write_text("rotation plaintext stays encrypted", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)
    old_version = service.versions[record.current_version_id]
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, record.record_id)],
        abilities=["record/decrypt"],
        issuer_secret=owner_secret,
        audience_secret=delegate_secret,
    )

    new_version = service.rotate_record_key(
        wallet.wallet_id,
        record.record_id,
        actor_did=OWNER,
        actor_secret=owner_secret,
    )
    snapshot = service.export_wallet_snapshot(wallet.wallet_id)
    public_snapshot = json.dumps(snapshot)

    assert new_version.version_id != old_version.version_id
    assert new_version.encrypted_payload_ref.sha256 != old_version.encrypted_payload_ref.sha256
    assert service.records[record.record_id].current_version_id == new_version.version_id
    assert any(wrap.recipient_did == ADVOCATE and wrap.grant_id == grant.grant_id for wrap in new_version.key_wraps)
    assert service.decrypt_record(
        wallet.wallet_id,
        record.record_id,
        actor_did=ADVOCATE,
        grant_id=grant.grant_id,
        actor_secret=delegate_secret,
    ) == b"rotation plaintext stays encrypted"
    assert [version["version_id"] for version in snapshot["versions"]] == [new_version.version_id]
    assert "rotation plaintext" not in public_snapshot
    assert service.get_audit_log(wallet.wallet_id)[-1].action == "record/decrypt"
    assert any(event.action == "record/key_rotate" for event in service.get_audit_log(wallet.wallet_id))


def test_threshold_approval_required_for_sensitive_decrypt_grant(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(
        owner_did=OWNER,
        controller_dids=[OWNER, SECOND_CONTROLLER],
        governance_policy={"threshold": 2},
    )
    source = tmp_path / "identity.txt"
    source.write_text("identity document plaintext", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)
    resource = resource_for_record(wallet.wallet_id, record.record_id)

    with pytest.raises(ApprovalRequiredError):
        service.create_grant(
            wallet_id=wallet.wallet_id,
            issuer_did=OWNER,
            audience_did=ADVOCATE,
            resources=[resource],
            abilities=["record/decrypt"],
        )

    approval = service.request_approval(
        wallet.wallet_id,
        requested_by=OWNER,
        operation="grant/create",
        resources=[resource],
        abilities=["record/decrypt"],
    )
    service.approve_approval(wallet.wallet_id, approval_id=approval.approval_id, approver_did=OWNER)

    with pytest.raises(ApprovalRequiredError):
        service.create_grant(
            wallet_id=wallet.wallet_id,
            issuer_did=OWNER,
            audience_did=ADVOCATE,
            resources=[resource],
            abilities=["record/decrypt"],
            approval_id=approval.approval_id,
        )

    service.approve_approval(
        wallet.wallet_id,
        approval_id=approval.approval_id,
        approver_did=SECOND_CONTROLLER,
    )
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource],
        abilities=["record/decrypt"],
        approval_id=approval.approval_id,
    )

    assert approval.status == "approved"
    assert service.decrypt_record(
        wallet.wallet_id,
        record.record_id,
        actor_did=ADVOCATE,
        grant_id=grant.grant_id,
    ) == b"identity document plaintext"
    manifest = service.get_wallet_manifest(wallet.wallet_id)
    assert manifest["approvals"][0]["approval_id"] == approval.approval_id


def test_controller_changes_require_wallet_admin_threshold_approval(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(
        owner_did=OWNER,
        controller_dids=[OWNER, SECOND_CONTROLLER],
        governance_policy={"threshold": 2},
    )
    new_controller = "did:key:new-controller"
    wallet_resource = resource_for_wallet(wallet.wallet_id)

    with pytest.raises(ApprovalRequiredError):
        service.add_controller(
            wallet.wallet_id,
            actor_did=OWNER,
            controller_did=new_controller,
        )

    approval = service.request_approval(
        wallet.wallet_id,
        requested_by=OWNER,
        operation="wallet/controller_add",
        resources=[wallet_resource],
        abilities=["wallet/admin"],
    )
    service.approve_approval(wallet.wallet_id, approval_id=approval.approval_id, approver_did=OWNER)
    service.approve_approval(
        wallet.wallet_id,
        approval_id=approval.approval_id,
        approver_did=SECOND_CONTROLLER,
    )
    updated = service.add_controller(
        wallet.wallet_id,
        actor_did=OWNER,
        controller_did=new_controller,
        approval_id=approval.approval_id,
    )

    assert new_controller in updated.controller_dids
    assert new_controller in updated.governance_policy["approver_dids"]

    remove_approval = service.request_approval(
        wallet.wallet_id,
        requested_by=OWNER,
        operation="wallet/controller_remove",
        resources=[wallet_resource],
        abilities=["wallet/admin"],
    )
    service.approve_approval(wallet.wallet_id, approval_id=remove_approval.approval_id, approver_did=OWNER)
    service.approve_approval(
        wallet.wallet_id,
        approval_id=remove_approval.approval_id,
        approver_did=SECOND_CONTROLLER,
    )
    service.remove_controller(
        wallet.wallet_id,
        actor_did=OWNER,
        controller_did=new_controller,
        approval_id=remove_approval.approval_id,
    )
    actions = [event.action for event in service.get_audit_log(wallet.wallet_id)]

    assert new_controller not in service.wallets[wallet.wallet_id].controller_dids
    assert "wallet/controller_add" in actions
    assert "wallet/controller_remove" in actions


def test_device_add_and_revoke_updates_wallet_manifest(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    device_did = "did:key:phone-device"

    assert service.get_wallet(wallet.wallet_id).wallet_id == wallet.wallet_id
    service.add_device(wallet.wallet_id, actor_did=OWNER, device_did=device_did)
    assert device_did in service.wallets[wallet.wallet_id].device_dids

    service.revoke_device(wallet.wallet_id, actor_did=OWNER, device_did=device_did)
    snapshot = service.export_wallet_snapshot(wallet.wallet_id)
    restored = WalletService(storage_dir=tmp_path / "restored")
    restored.import_wallet_snapshot(snapshot)
    actions = [event.action for event in service.get_audit_log(wallet.wallet_id)]

    assert device_did not in snapshot["wallet"]["device_dids"]
    assert restored.wallets[wallet.wallet_id].device_dids == [OWNER]
    assert "wallet/device_add" in actions
    assert "wallet/device_revoke" in actions


def test_recovery_policy_requires_threshold_and_recovers_controller(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(
        owner_did=OWNER,
        controller_dids=[OWNER, SECOND_CONTROLLER],
        governance_policy={"threshold": 2},
    )
    wallet_resource = resource_for_wallet(wallet.wallet_id)
    recovery_contacts = ["did:key:recovery-a", "did:key:recovery-b"]
    recovered_controller = "did:key:recovered-controller"

    with pytest.raises(ApprovalRequiredError):
        service.set_recovery_policy(
            wallet.wallet_id,
            actor_did=OWNER,
            contact_dids=recovery_contacts,
            threshold=2,
        )

    approval = service.request_approval(
        wallet.wallet_id,
        requested_by=OWNER,
        operation="wallet/recovery_policy_set",
        resources=[wallet_resource],
        abilities=["wallet/admin"],
    )
    service.approve_approval(wallet.wallet_id, approval_id=approval.approval_id, approver_did=OWNER)
    service.approve_approval(
        wallet.wallet_id,
        approval_id=approval.approval_id,
        approver_did=SECOND_CONTROLLER,
    )
    updated = service.set_recovery_policy(
        wallet.wallet_id,
        actor_did=OWNER,
        contact_dids=recovery_contacts,
        threshold=2,
        approval_id=approval.approval_id,
    )
    recovery_policy = updated.governance_policy["recovery_policy"]
    assert recovery_policy["contact_dids"] == recovery_contacts
    assert recovery_policy["threshold"] == 2
    assert recovery_policy["status"] == "active"

    snapshot = service.export_wallet_snapshot(wallet.wallet_id)
    restored = WalletService(storage_dir=tmp_path / "restored-recovery")
    restored.import_wallet_snapshot(snapshot)
    assert restored.wallets[wallet.wallet_id].governance_policy["recovery_policy"]["contact_dids"] == recovery_contacts

    with pytest.raises(ApprovalRequiredError):
        service.recover_controller(
            wallet.wallet_id,
            actor_did=recovery_contacts[0],
            controller_did=recovered_controller,
        )

    recovery_approval = service.request_approval(
        wallet.wallet_id,
        requested_by=recovery_contacts[0],
        operation="wallet/controller_recover",
        resources=[wallet_resource],
        abilities=["wallet/admin"],
    )
    assert recovery_approval.approver_dids == recovery_contacts
    assert recovery_approval.threshold == 2
    assert recovery_approval.details["approval_scope"] == "wallet_recovery"

    service.approve_approval(
        wallet.wallet_id,
        approval_id=recovery_approval.approval_id,
        approver_did=recovery_contacts[0],
    )
    with pytest.raises(ApprovalRequiredError):
        service.recover_controller(
            wallet.wallet_id,
            actor_did=recovery_contacts[0],
            controller_did=recovered_controller,
            approval_id=recovery_approval.approval_id,
        )

    service.approve_approval(
        wallet.wallet_id,
        approval_id=recovery_approval.approval_id,
        approver_did=recovery_contacts[1],
    )
    recovered = service.recover_controller(
        wallet.wallet_id,
        actor_did=recovery_contacts[0],
        controller_did=recovered_controller,
        approval_id=recovery_approval.approval_id,
    )
    actions = [event.action for event in service.get_audit_log(wallet.wallet_id)]

    assert recovered_controller in recovered.controller_dids
    assert recovered_controller in recovered.governance_policy["approver_dids"]
    assert "wallet/recovery_policy_set" in actions
    assert "wallet/controller_recover" in actions


def test_grant_receipt_tracks_sharing_and_survives_snapshot(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "receipt.txt"
    source.write_text("receipt tracked sharing", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)
    resource = resource_for_record(wallet.wallet_id, record.record_id)

    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource],
        abilities=["record/analyze"],
        caveats={"purpose": "benefits_screening"},
    )
    [receipt] = service.list_grant_receipts(wallet.wallet_id, audience_did=ADVOCATE)

    assert receipt.grant_id == grant.grant_id
    assert receipt.wallet_id == wallet.wallet_id
    assert receipt.audience_did == ADVOCATE
    assert receipt.resources == [resource]
    assert receipt.abilities == ["record/analyze"]
    assert receipt.purpose == "benefits_screening"
    assert receipt.receipt_hash
    assert service.get_wallet_manifest(wallet.wallet_id)["grant_receipts"][0]["receipt_id"] == receipt.receipt_id

    restored = WalletService(storage_dir=tmp_path)
    restored.import_wallet_snapshot(service.export_wallet_snapshot(wallet.wallet_id))
    [restored_receipt] = restored.list_grant_receipts(wallet.wallet_id, status="active")
    assert restored_receipt.to_dict() == receipt.to_dict()

    service.revoke_grant(wallet.wallet_id, grant.grant_id, actor_did=OWNER)
    [revoked_receipt] = service.list_grant_receipts(wallet.wallet_id, status="revoked")
    assert revoked_receipt.receipt_id == receipt.receipt_id
    version = service.versions[record.current_version_id]
    revoked_wraps = [wrap for wrap in version.key_wraps if wrap.grant_id == grant.grant_id]
    assert revoked_wraps
    assert all(wrap.status == "revoked" for wrap in revoked_wraps)


def test_location_claims_are_coarse_and_proof_receipts_hide_precise_point(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    location = service.add_location(wallet.wallet_id, lat=45.515232, lon=-122.678385)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_location(wallet.wallet_id, location.record_id)],
        abilities=["location/read_coarse", "location/prove_region"],
    )

    claim = service.create_coarse_location_claim(
        wallet.wallet_id,
        location.record_id,
        actor_did=ADVOCATE,
        grant_id=grant.grant_id,
    )
    receipt = service.create_location_region_proof(
        wallet.wallet_id,
        location.record_id,
        actor_did=ADVOCATE,
        region_id="multnomah_county",
        grant_id=grant.grant_id,
    )

    assert claim.public_value == {"lat": 45.52, "lon": -122.68}
    assert receipt.is_simulated is True
    assert receipt.proof_system == "simulated"
    assert receipt.verification_status == "verified"
    assert receipt.public_inputs["region_id"] == "multnomah_county"
    assert receipt.public_inputs["claim"] == "location_in_region"
    assert receipt.public_inputs["region_policy_hash"]
    public_receipt = json.dumps(receipt.to_dict())
    assert "45.515232" not in public_receipt
    assert "-122.678385" not in public_receipt


class FakeLocationRegionProofBackend:
    verifier_id = "fake-location-region-v1"
    proof_system = "fake-zkp"
    mode = "production"
    is_simulated = False

    def __init__(self, *, verifies: bool = True) -> None:
        self.verifies = verifies
        self.last_witness: dict[str, object] | None = None

    def prove_location_region(
        self,
        *,
        wallet_id: str,
        statement: dict[str, object],
        public_inputs: dict[str, object],
        witness: dict[str, object],
        witness_record_ids: list[str],
    ) -> ProofReceipt:
        self.last_witness = dict(witness)
        digest = hashlib.sha256(f"{self.proof_system}:{self.verifier_id}".encode("utf-8")).hexdigest()
        proof_hash = hashlib.sha256(json.dumps(public_inputs, sort_keys=True).encode("utf-8")).hexdigest()
        return ProofReceipt(
            proof_id=f"proof-{uuid.uuid4().hex}",
            wallet_id=wallet_id,
            proof_type="location_region",
            statement=dict(statement),
            verifier_id=self.verifier_id,
            public_inputs=dict(public_inputs),
            proof_hash=proof_hash,
            witness_record_ids=list(witness_record_ids),
            is_simulated=False,
            proof_system=self.proof_system,
            circuit_id="fake-location-region-circuit",
            verifier_digest=digest,
            proof_artifact_ref="memory://fake-location-region-proof",
            verification_status="verified" if self.verifies else "failed",
        )

    def verify(self, receipt: ProofReceipt) -> bool:
        return self.verifies and receipt.verifier_id == self.verifier_id and not receipt.is_simulated


def test_location_region_proof_fails_closed_when_simulated_disabled(tmp_path):
    service = WalletService(storage_dir=tmp_path, allow_simulated_proofs=False)
    wallet = service.create_wallet(owner_did=OWNER)
    location = service.add_location(wallet.wallet_id, lat=45.515232, lon=-122.678385)

    with pytest.raises(DataWalletError, match="Simulated proofs are disabled"):
        service.create_location_region_proof(
            wallet.wallet_id,
            location.record_id,
            actor_did=OWNER,
            region_id="multnomah_county",
        )

    assert service.proofs == {}


def test_location_region_proof_accepts_verified_non_simulated_backend(tmp_path):
    backend = FakeLocationRegionProofBackend()
    service = WalletService(
        storage_dir=tmp_path,
        proof_backend=backend,
        allow_simulated_proofs=False,
    )
    wallet = service.create_wallet(owner_did=OWNER)
    location = service.add_location(wallet.wallet_id, lat=45.515232, lon=-122.678385)

    receipt = service.create_location_region_proof(
        wallet.wallet_id,
        location.record_id,
        actor_did=OWNER,
        region_id="multnomah_county",
    )

    assert receipt.is_simulated is False
    assert receipt.proof_system == "fake-zkp"
    assert receipt.verification_status == "verified"
    assert receipt.proof_artifact_ref == "memory://fake-location-region-proof"
    assert backend.last_witness and backend.last_witness["lat"] == 45.515232
    public_receipt = json.dumps(receipt.to_dict())
    assert "45.515232" not in public_receipt
    assert "-122.678385" not in public_receipt


def test_location_region_proof_accepts_deterministic_integration_backend(tmp_path):
    service = WalletService(
        storage_dir=tmp_path,
        proof_backend=DeterministicLocationRegionProofBackend(),
        allow_simulated_proofs=False,
    )
    wallet = service.create_wallet(owner_did=OWNER)
    location = service.add_location(wallet.wallet_id, lat=45.515232, lon=-122.678385)

    receipt = service.create_location_region_proof(
        wallet.wallet_id,
        location.record_id,
        actor_did=OWNER,
        region_id="multnomah_county",
    )

    assert receipt.is_simulated is False
    assert receipt.proof_system == "deterministic-test-proof"
    assert receipt.circuit_id == "deterministic-location-region-v0.1"
    assert receipt.proof_artifact_ref and receipt.proof_artifact_ref.startswith("deterministic-proof://")
    assert service.proof_backend.verify(receipt) is True
    public_receipt = json.dumps(receipt.to_dict())
    assert "45.515232" not in public_receipt
    assert "-122.678385" not in public_receipt


def test_location_distance_proof_hides_precise_point_and_target_coordinates(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    location = service.add_location(wallet.wallet_id, lat=45.515232, lon=-122.678385)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_location(wallet.wallet_id, location.record_id)],
        abilities=["location/prove_distance"],
        caveats={"purpose": "service_matching", "proof_type": "location_distance"},
    )

    receipt = service.create_location_distance_proof(
        wallet.wallet_id,
        location.record_id,
        actor_did=ADVOCATE,
        target_id="shelter-west",
        target_lat=45.516,
        target_lon=-122.679,
        max_distance_km=1.0,
        grant_id=grant.grant_id,
    )

    assert receipt.is_simulated is True
    assert receipt.proof_type == "location_distance"
    assert receipt.public_inputs["claim"] == "location_within_distance"
    assert receipt.public_inputs["target_id"] == "shelter-west"
    assert receipt.public_inputs["max_distance_km"] == 1.0
    assert receipt.public_inputs["target_policy_hash"]
    public_receipt = json.dumps(receipt.to_dict())
    for secret in ("45.515232", "-122.678385", "45.516", "-122.679"):
        assert secret not in public_receipt


def test_location_distance_proof_enforces_target_and_threshold_caveats(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    location = service.add_location(wallet.wallet_id, lat=45.515232, lon=-122.678385)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_location(wallet.wallet_id, location.record_id)],
        abilities=["location/prove_distance"],
        caveats={
            "purpose": "service_matching",
            "proof_type": "location_distance",
            "target_id": "shelter-west",
            "max_distance_km": 1.0,
        },
    )

    with pytest.raises(AccessDeniedError, match="target_id"):
        service.create_location_distance_proof(
            wallet.wallet_id,
            location.record_id,
            actor_did=ADVOCATE,
            target_id="shelter-east",
            target_lat=45.516,
            target_lon=-122.679,
            max_distance_km=1.0,
            grant_id=grant.grant_id,
        )

    with pytest.raises(AccessDeniedError, match="max_distance_km"):
        service.create_location_distance_proof(
            wallet.wallet_id,
            location.record_id,
            actor_did=ADVOCATE,
            target_id="shelter-west",
            target_lat=45.516,
            target_lon=-122.679,
            max_distance_km=2.0,
            grant_id=grant.grant_id,
        )

    assert service.proofs == {}


def test_location_distance_proof_rejects_out_of_range_claim(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    location = service.add_location(wallet.wallet_id, lat=45.515232, lon=-122.678385)

    with pytest.raises(DataWalletError, match="outside"):
        service.create_location_distance_proof(
            wallet.wallet_id,
            location.record_id,
            actor_did=OWNER,
            target_id="far-service",
            target_lat=47.6062,
            target_lon=-122.3321,
            max_distance_km=1.0,
        )

    assert service.proofs == {}


def test_location_distance_proof_accepts_deterministic_integration_backend(tmp_path):
    service = WalletService(
        storage_dir=tmp_path,
        proof_backend=DeterministicLocationDistanceProofBackend(),
        allow_simulated_proofs=False,
    )
    wallet = service.create_wallet(owner_did=OWNER)
    location = service.add_location(wallet.wallet_id, lat=45.515232, lon=-122.678385)

    receipt = service.create_location_distance_proof(
        wallet.wallet_id,
        location.record_id,
        actor_did=OWNER,
        target_id="shelter-west",
        target_lat=45.516,
        target_lon=-122.679,
        max_distance_km=1.0,
    )

    assert receipt.is_simulated is False
    assert receipt.proof_type == "location_distance"
    assert receipt.proof_system == "deterministic-test-proof"
    assert receipt.circuit_id == "deterministic-location-distance-v0.1"
    assert receipt.proof_artifact_ref and receipt.proof_artifact_ref.startswith("deterministic-proof://")
    assert service.proof_backend.verify(receipt) is True
    public_receipt = json.dumps(receipt.to_dict())
    for secret in ("45.515232", "-122.678385", "45.516", "-122.679"):
        assert secret not in public_receipt


def test_proof_receipt_snapshot_import_accepts_legacy_receipt_schema(tmp_path):
    service = WalletService(
        storage_dir=tmp_path,
        proof_backend=DeterministicLocationRegionProofBackend(),
        allow_simulated_proofs=False,
    )
    wallet = service.create_wallet(owner_did=OWNER)
    location = service.add_location(wallet.wallet_id, lat=45.515232, lon=-122.678385)
    receipt = service.create_location_region_proof(
        wallet.wallet_id,
        location.record_id,
        actor_did=OWNER,
        region_id="multnomah_county",
    )
    snapshot = service.export_wallet_snapshot(wallet.wallet_id)
    legacy_proof = dict(snapshot["proofs"][0])
    for key in (
        "proof_system",
        "circuit_id",
        "verifier_digest",
        "proof_artifact_ref",
        "verification_status",
    ):
        legacy_proof.pop(key, None)
    snapshot["proofs"] = [legacy_proof]

    restored = WalletService(storage_dir=tmp_path)
    restored.import_wallet_snapshot(snapshot)
    restored_receipt = restored.proofs[receipt.proof_id]

    assert restored_receipt.proof_system == "simulated"
    assert restored_receipt.verification_status == "verified"
    assert restored_receipt.proof_hash == receipt.proof_hash
    public_receipt = json.dumps(restored_receipt.to_dict())
    assert "45.515232" not in public_receipt
    assert "-122.678385" not in public_receipt


def test_location_region_proof_rejects_failed_backend_verification(tmp_path):
    service = WalletService(
        storage_dir=tmp_path,
        proof_backend=FakeLocationRegionProofBackend(verifies=False),
        allow_simulated_proofs=False,
    )
    wallet = service.create_wallet(owner_did=OWNER)
    location = service.add_location(wallet.wallet_id, lat=45.515232, lon=-122.678385)

    with pytest.raises(DataWalletError, match="Proof verification failed"):
        service.create_location_region_proof(
            wallet.wallet_id,
            location.record_id,
            actor_did=OWNER,
            region_id="multnomah_county",
        )

    assert service.proofs == {}


def test_revoked_grant_fails_future_invocations(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "note.txt"
    source.write_text("private note", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, record.record_id)],
        abilities=["record/analyze"],
    )

    service.revoke_grant(wallet.wallet_id, grant.grant_id, actor_did=OWNER)

    with pytest.raises(AccessDeniedError):
        service.analyze_record_summary(
            wallet.wallet_id,
            record.record_id,
            actor_did=ADVOCATE,
            grant_id=grant.grant_id,
        )


def test_export_bundle_requires_grant_and_excludes_plaintext_location(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "notice.txt"
    source.write_text("Eviction notice with confidential case facts", encoding="utf-8")
    document = service.add_document(wallet.wallet_id, source)
    location = service.add_location(wallet.wallet_id, actor_did=OWNER, lat=45.515232, lon=-122.678385)

    with pytest.raises(AccessDeniedError):
        service.create_export_bundle(
            wallet.wallet_id,
            actor_did=ADVOCATE,
            record_ids=[document.record_id, location.record_id],
        )

    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[
            resource_for_record(wallet.wallet_id, document.record_id),
            resource_for_record(wallet.wallet_id, location.record_id),
        ],
        abilities=["export/create"],
    )
    bundle = service.create_export_bundle(
        wallet.wallet_id,
        actor_did=ADVOCATE,
        grant_id=grant.grant_id,
        record_ids=[document.record_id, location.record_id],
    )

    assert bundle["bundle_type"] == "wallet_export_v1"
    assert bundle["bundle_id"] == f"export-{bundle['bundle_hash'][:24]}"
    assert service.verify_export_bundle(bundle) is True
    assert "controller_dids" not in bundle["wallet"]
    assert "device_dids" not in bundle["wallet"]
    assert [record["record_id"] for record in bundle["records"]] == [document.record_id, location.record_id]
    assert all(version["key_wraps"] == [] for version in bundle["versions"])
    public_export = json.dumps(bundle)
    assert "Eviction notice" not in public_export
    assert "45.515232" not in public_export
    assert "-122.678385" not in public_export
    tampered = {**bundle, "records": []}
    assert service.verify_export_bundle(tampered) is False

    imported = WalletService(storage_dir=tmp_path / "imported")
    available_storage = imported.verify_export_bundle_storage(bundle)
    assert available_storage["ok"] is True
    assert available_storage["record_count"] == 2
    broken_storage_bundle = json.loads(json.dumps(bundle))
    broken_storage_bundle["versions"][0]["encrypted_payload_ref"]["uri"] = "local:///missing/export-payload.bin"
    broken_storage_bundle["versions"][0]["encrypted_payload_ref"]["mirrors"] = []
    broken_storage_bundle["bundle_hash"] = imported.export_bundle_hash(broken_storage_bundle)
    broken_storage_bundle["bundle_id"] = f"export-{broken_storage_bundle['bundle_hash'][:24]}"
    missing_storage = imported.verify_export_bundle_storage(broken_storage_bundle)
    assert missing_storage["ok"] is False
    summary = imported.import_export_bundle(bundle)
    assert summary["record_count"] == 2
    assert summary["version_count"] == 2
    assert imported.records[document.record_id].data_type == "document"
    assert imported.records[location.record_id].data_type == "location"
    assert imported.get_audit_log(wallet.wallet_id)[-1].action == "export/import"
    with pytest.raises(AccessDeniedError):
        imported.import_export_bundle(tampered)
    wrong_type = {**bundle, "bundle_type": "not_wallet_export"}
    wrong_type["bundle_hash"] = imported.export_bundle_hash(wrong_type)
    wrong_type["bundle_id"] = f"export-{wrong_type['bundle_hash'][:24]}"
    with pytest.raises(ValueError, match="Unsupported"):
        imported.import_export_bundle(wrong_type)
    missing_versions = {**bundle, "versions": []}
    missing_versions["bundle_hash"] = imported.export_bundle_hash(missing_versions)
    missing_versions["bundle_id"] = f"export-{missing_versions['bundle_hash'][:24]}"
    with pytest.raises(ValueError, match="version"):
        imported.import_export_bundle(missing_versions)

    service.revoke_grant(wallet.wallet_id, grant.grant_id, actor_did=OWNER)
    with pytest.raises(AccessDeniedError):
        service.create_export_bundle(
            wallet.wallet_id,
            actor_did=ADVOCATE,
            grant_id=grant.grant_id,
            record_ids=[document.record_id],
        )


def test_export_bundle_output_type_caveat_must_allow_encrypted_bundle(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "export-output.txt"
    source.write_text("Export output caveat content", encoding="utf-8")
    document = service.add_document(wallet.wallet_id, source)
    export_resource = resource_for_export(wallet.wallet_id)
    good_grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[export_resource],
        abilities=["export/create"],
        caveats={"record_ids": [document.record_id], "output_types": ["encrypted_export_bundle"]},
    )
    wrong_output_grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=CASE_MANAGER,
        resources=[export_resource],
        abilities=["export/create"],
        caveats={"record_ids": [document.record_id], "output_types": ["summary"]},
    )

    bundle = service.create_export_bundle(
        wallet.wallet_id,
        actor_did=ADVOCATE,
        grant_id=good_grant.grant_id,
        record_ids=[document.record_id],
    )

    assert bundle["bundle_type"] == "wallet_export_v1"
    with pytest.raises(AccessDeniedError, match="output_types"):
        service.create_export_bundle(
            wallet.wallet_id,
            actor_did=CASE_MANAGER,
            grant_id=wrong_output_grant.grant_id,
            record_ids=[document.record_id],
        )


def test_export_bundle_accepts_signed_invocation_and_invocation_caveats(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "export-note.txt"
    source.write_text("Export through invocation", encoding="utf-8")
    document = service.add_document(wallet.wallet_id, source)
    location = service.add_location(wallet.wallet_id, actor_did=OWNER, lat=45.515232, lon=-122.678385)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_export(wallet.wallet_id)],
        abilities=["export/create"],
        caveats={"record_ids": [document.record_id, location.record_id]},
        audience_secret=delegate_secret,
    )
    invocation = service.issue_invocation(
        wallet.wallet_id,
        grant_id=grant.grant_id,
        actor_did=ADVOCATE,
        resource=resource_for_export(wallet.wallet_id),
        ability="export/create",
        actor_secret=delegate_secret,
        caveats={"record_ids": [document.record_id]},
    )

    bundle = service.create_export_bundle_with_invocation(
        wallet.wallet_id,
        actor_did=ADVOCATE,
        invocation=invocation,
        actor_secret=delegate_secret,
        record_ids=[document.record_id],
    )

    assert [record["record_id"] for record in bundle["records"]] == [document.record_id]
    with pytest.raises(AccessDeniedError):
        service.create_export_bundle_with_invocation(
            wallet.wallet_id,
            actor_did=ADVOCATE,
            invocation=invocation,
            actor_secret=delegate_secret,
            record_ids=[location.record_id],
        )


def test_revoked_export_grant_blocks_existing_invocation(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "export-revoke.txt"
    source.write_text("Export should stop after revoke", encoding="utf-8")
    document = service.add_document(wallet.wallet_id, source)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_export(wallet.wallet_id)],
        abilities=["export/create"],
        caveats={"record_ids": [document.record_id]},
        audience_secret=delegate_secret,
    )
    invocation = service.issue_invocation(
        wallet.wallet_id,
        grant_id=grant.grant_id,
        actor_did=ADVOCATE,
        resource=resource_for_export(wallet.wallet_id),
        ability="export/create",
        actor_secret=delegate_secret,
        caveats={"record_ids": [document.record_id]},
    )

    service.revoke_grant(wallet.wallet_id, grant.grant_id, actor_did=OWNER)

    with pytest.raises(AccessDeniedError, match="not active"):
        service.create_export_bundle_with_invocation(
            wallet.wallet_id,
            actor_did=ADVOCATE,
            invocation=invocation,
            actor_secret=delegate_secret,
            record_ids=[document.record_id],
        )


def test_export_grant_requires_threshold_approval(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(
        owner_did=OWNER,
        controller_dids=[OWNER, SECOND_CONTROLLER],
        governance_policy={"threshold": 2, "approver_dids": [OWNER, SECOND_CONTROLLER]},
    )
    source = tmp_path / "export-approval.txt"
    source.write_text("Export requires approval", encoding="utf-8")
    document = service.add_document(wallet.wallet_id, source)
    export_resource = resource_for_export(wallet.wallet_id)

    with pytest.raises(ApprovalRequiredError):
        service.create_grant(
            wallet_id=wallet.wallet_id,
            issuer_did=OWNER,
            audience_did=ADVOCATE,
            resources=[export_resource],
            abilities=["export/create"],
            caveats={"record_ids": [document.record_id]},
        )

    approval = service.request_approval(
        wallet.wallet_id,
        requested_by=OWNER,
        operation="grant/create",
        resources=[export_resource],
        abilities=["export/create"],
    )
    service.approve_approval(wallet.wallet_id, approval_id=approval.approval_id, approver_did=OWNER)
    service.approve_approval(wallet.wallet_id, approval_id=approval.approval_id, approver_did=SECOND_CONTROLLER)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[export_resource],
        abilities=["export/create"],
        caveats={"record_ids": [document.record_id]},
        approval_id=approval.approval_id,
    )

    assert grant.grant_id.startswith("grant-")
    assert grant.abilities == ["export/create"]


def test_signed_invocation_allows_delegate_analysis_and_round_trips_token(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    owner_secret = b"o" * 32
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "case-note.txt"
    source.write_text("Eligible for rental assistance and utility support.", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, record.record_id)],
        abilities=["record/analyze"],
        issuer_secret=owner_secret,
        audience_secret=delegate_secret,
    )
    invocation = service.issue_invocation(
        wallet.wallet_id,
        grant_id=grant.grant_id,
        actor_did=ADVOCATE,
        resource=resource_for_record(wallet.wallet_id, record.record_id),
        ability="record/analyze",
        actor_secret=delegate_secret,
    )
    token_invocation = invocation_from_token(invocation_to_token(invocation))

    artifact = service.analyze_record_summary_with_invocation(
        wallet.wallet_id,
        record.record_id,
        actor_did=ADVOCATE,
        invocation=token_invocation,
        actor_secret=delegate_secret,
    )
    manifest = service.get_wallet_manifest(wallet.wallet_id)
    actions = [event.action for event in service.get_audit_log(wallet.wallet_id)]

    assert artifact.artifact_type == "summary"
    assert manifest["invocations"][0]["invocation_id"] == invocation.invocation_id
    assert "invocation/issue" in actions
    assert "invocation/verify" in actions


def test_wallet_ucan_profile_payload_exports_capability_without_plaintext(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    owner_secret = b"o" * 32
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "profile-case-note.txt"
    source.write_text("Tenant needs confidential rental assistance.", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)
    resource = resource_for_record(wallet.wallet_id, record.record_id)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource],
        abilities=["record/analyze"],
        caveats={"purpose": "case_review", "output_types": ["summary"]},
        issuer_secret=owner_secret,
        audience_secret=delegate_secret,
    )
    invocation = service.issue_invocation(
        wallet.wallet_id,
        grant_id=grant.grant_id,
        actor_did=ADVOCATE,
        resource=resource,
        ability="record/analyze",
        actor_secret=delegate_secret,
        caveats={"purpose": "case_review", "output_types": ["summary"]},
    )

    token_invocation = invocation_from_token(invocation_to_token(invocation))
    profile = wallet_ucan_profile()
    payload = invocation_to_ucan_profile_payload(token_invocation, grant=grant)
    serialized = json.dumps(payload)

    assert token_invocation.issuer_did == OWNER
    assert profile["token_prefix"] == WALLET_UCAN_TOKEN_PREFIX.rstrip(".")
    assert payload["profile"] == profile["profile"]
    assert payload["ucan"]["iss"] == OWNER
    assert payload["ucan"]["aud"] == ADVOCATE
    assert payload["ucan"]["att"] == [
        {
            "with": resource,
            "can": "record/analyze",
            "nb": {"purpose": "case_review", "output_types": ["summary"]},
        }
    ]
    assert "confidential rental assistance" not in serialized


def test_wallet_ucan_conformance_fixture_validates_profile_payload(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    owner_secret = b"o" * 32
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "interop-case-note.txt"
    source.write_text("Interop fixture must not expose this document text.", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)
    resource = resource_for_record(wallet.wallet_id, record.record_id)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource],
        abilities=["record/analyze"],
        caveats={"purpose": "case_review", "output_types": ["summary"]},
        issuer_secret=owner_secret,
        audience_secret=delegate_secret,
    )
    invocation = service.issue_invocation(
        wallet.wallet_id,
        grant_id=grant.grant_id,
        actor_did=ADVOCATE,
        resource=resource,
        ability="record/analyze",
        actor_secret=delegate_secret,
        caveats={"purpose": "case_review", "output_types": ["summary"]},
    )

    fixture = wallet_ucan_conformance_fixture(invocation, grant=grant)
    normalized = validate_ucan_profile_payload(fixture["profile_payload"])
    fixture_normalized = validate_wallet_ucan_conformance_fixture(fixture)
    serialized = json.dumps(fixture)

    assert fixture["fixture"] == WALLET_UCAN_CONFORMANCE_FIXTURE_ID
    assert fixture["token"].startswith(WALLET_UCAN_TOKEN_PREFIX)
    assert fixture["expected"]["issuer"] == OWNER
    assert fixture["expected"]["audience"] == ADVOCATE
    assert fixture["expected"]["capability"] == {
        "with": resource,
        "can": "record/analyze",
        "nb": {"purpose": "case_review", "output_types": ["summary"]},
    }
    assert normalized["issuer_did"] == OWNER
    assert normalized["audience_did"] == ADVOCATE
    assert normalized["resource"] == resource
    assert normalized["ability"] == "record/analyze"
    assert fixture_normalized["issuer_did"] == OWNER
    assert fixture_normalized["resource"] == resource
    assert fixture_normalized["signature_payload_sha256"] == fixture["signature_payload_sha256"]
    assert "Interop fixture must not expose this document text" not in serialized

    tampered = json.loads(json.dumps(fixture["profile_payload"]))
    tampered["ucan"]["att"][0]["can"] = "record/decrypt"
    with pytest.raises(ValueError, match="ability"):
        validate_ucan_profile_payload(tampered)

    tampered_fixture = json.loads(json.dumps(fixture))
    tampered_fixture["expected"]["capability"]["can"] = "record/decrypt"
    with pytest.raises(ValueError, match="capability.can"):
        validate_wallet_ucan_conformance_fixture(tampered_fixture)

    tampered_fixture = json.loads(json.dumps(fixture))
    tampered_fixture["signature_payload_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="signature_payload_sha256"):
        validate_wallet_ucan_conformance_fixture(tampered_fixture)

    other_invocation = service.issue_invocation(
        wallet.wallet_id,
        grant_id=grant.grant_id,
        actor_did=ADVOCATE,
        resource=resource,
        ability="record/analyze",
        actor_secret=delegate_secret,
        caveats={"purpose": "case_review", "output_types": ["summary"]},
    )
    with pytest.raises(ValueError, match="token does not encode"):
        wallet_ucan_conformance_fixture(
            invocation,
            grant=grant,
            token=invocation_to_token(other_invocation),
        )


def test_wallet_ucan_conformance_fixture_cli_round_trip(tmp_path, capsys):
    from ipfs_datasets_py.wallet.cli import main as wallet_cli_main

    service = WalletService(storage_dir=tmp_path)
    owner_secret = b"o" * 32
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "cli-interop-case-note.txt"
    source.write_text("CLI fixture must not expose this document text.", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)
    resource = resource_for_record(wallet.wallet_id, record.record_id)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource],
        abilities=["record/analyze"],
        caveats={"purpose": "case_review", "output_types": ["summary"]},
        issuer_secret=owner_secret,
        audience_secret=delegate_secret,
    )
    invocation = service.issue_invocation(
        wallet.wallet_id,
        grant_id=grant.grant_id,
        actor_did=ADVOCATE,
        resource=resource,
        ability="record/analyze",
        actor_secret=delegate_secret,
        caveats={"purpose": "case_review", "output_types": ["summary"]},
    )
    token = invocation_to_token(invocation)
    grant_path = tmp_path / "grant.json"
    fixture_path = tmp_path / "ucan-fixture.json"
    profile_payload_path = tmp_path / "ucan-profile-payload.json"
    grant_path.write_text(json.dumps(grant.to_dict(), sort_keys=True), encoding="utf-8")

    assert wallet_cli_main(["--json", "ucan-profile"]) == 0
    profile_output = json.loads(capsys.readouterr().out)
    assert profile_output["profile"]["profile"] == "wallet-ucan-v1"
    assert profile_output["profile"]["token_prefix"] == WALLET_UCAN_TOKEN_PREFIX.rstrip(".")

    assert (
        wallet_cli_main(
            [
                "--json",
                "ucan-conformance-fixture",
                "--invocation-token",
                token,
                "--grant-path",
                str(grant_path),
                "--out",
                str(fixture_path),
            ]
        )
        == 0
    )
    fixture_summary = json.loads(capsys.readouterr().out)
    assert fixture_summary["fixture"] == WALLET_UCAN_CONFORMANCE_FIXTURE_ID
    assert fixture_summary["resource"] == resource
    assert fixture_summary["ability"] == "record/analyze"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    serialized = json.dumps(fixture)
    assert "CLI fixture must not expose this document text" not in serialized

    assert wallet_cli_main(["--json", "ucan-validate-fixture", "--path", str(fixture_path)]) == 0
    validation_output = json.loads(capsys.readouterr().out)
    assert validation_output["valid"] is True
    assert validation_output["resource"] == resource

    profile_payload_path.write_text(
        json.dumps(fixture["profile_payload"], sort_keys=True),
        encoding="utf-8",
    )
    assert wallet_cli_main(["--json", "ucan-validate-profile", "--path", str(profile_payload_path)]) == 0
    profile_validation = json.loads(capsys.readouterr().out)
    assert profile_validation["valid"] is True
    assert profile_validation["ability"] == "record/analyze"

    tampered_fixture = json.loads(json.dumps(fixture))
    tampered_fixture["expected"]["capability"]["can"] = "record/decrypt"
    fixture_path.write_text(json.dumps(tampered_fixture, sort_keys=True), encoding="utf-8")
    assert wallet_cli_main(["--json", "ucan-validate-fixture", "--path", str(fixture_path)]) == 1
    error_output = json.loads(capsys.readouterr().out)
    assert error_output["status"] == "error"
    assert "capability.can" in error_output["error"]


def test_legacy_invocation_token_without_issuer_remains_verifiable(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    owner_secret = b"o" * 32
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "legacy-invocation.txt"
    source.write_text("Legacy invocation should still work.", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)
    resource = resource_for_record(wallet.wallet_id, record.record_id)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource],
        abilities=["record/analyze"],
        issuer_secret=owner_secret,
        audience_secret=delegate_secret,
    )
    invocation = service.issue_invocation(
        wallet.wallet_id,
        grant_id=grant.grant_id,
        actor_did=ADVOCATE,
        resource=resource,
        ability="record/analyze",
        actor_secret=delegate_secret,
    )
    legacy_invocation = WalletInvocation(
        **(invocation.to_dict() | {"issuer_did": None, "signature": ""})
    )
    legacy_invocation.signature = sign_invocation(legacy_invocation, delegate_secret)
    legacy_payload = legacy_invocation.to_dict()
    legacy_payload.pop("issuer_did", None)
    legacy_token = (
        WALLET_UCAN_TOKEN_PREFIX
        + base64.urlsafe_b64encode(canonical_bytes(legacy_payload)).decode("ascii")
    )
    restored = invocation_from_token(legacy_token)

    artifact = service.analyze_record_summary_with_invocation(
        wallet.wallet_id,
        record.record_id,
        actor_did=ADVOCATE,
        invocation=restored,
        actor_secret=delegate_secret,
    )

    assert restored.issuer_did is None
    assert artifact.artifact_type == "summary"


def test_access_request_approval_can_issue_invocation(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    owner_secret = b"o" * 32
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "requested.txt"
    source.write_text("requested access summary", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)

    request = service.request_access(
        wallet.wallet_id,
        requester_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, record.record_id)],
        abilities=["record/analyze"],
        purpose="eligibility_review",
    )
    approved = service.approve_access_request(
        wallet.wallet_id,
        request_id=request.request_id,
        actor_did=OWNER,
        issuer_secret=owner_secret,
        audience_secret=delegate_secret,
        issue_invocation=True,
    )
    restored = WalletService(storage_dir=tmp_path)
    restored.import_wallet_snapshot(service.export_wallet_snapshot(wallet.wallet_id))

    artifact = restored.analyze_record_summary_with_invocation(
        wallet.wallet_id,
        record.record_id,
        actor_did=ADVOCATE,
        invocation=restored.invocations[approved.invocation_id],
        actor_secret=delegate_secret,
    )
    manifest = restored.get_wallet_manifest(wallet.wallet_id)

    assert approved.status == "approved"
    assert approved.grant_id in restored.grants
    assert approved.invocation_id in restored.invocations
    assert manifest["access_requests"][0]["request_id"] == request.request_id
    assert artifact.artifact_type == "summary"


def test_access_request_rejection_records_decision(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    request = service.request_access(
        wallet.wallet_id,
        requester_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, "rec-missing")],
        abilities=["record/analyze"],
        purpose="screening",
    )

    rejected = service.reject_access_request(
        wallet.wallet_id,
        request_id=request.request_id,
        actor_did=OWNER,
        reason="insufficient purpose",
    )

    assert rejected.status == "rejected"
    assert rejected.decided_by == OWNER
    assert rejected.details["rejection_reason"] == "insufficient purpose"
    assert service.get_wallet_manifest(wallet.wallet_id)["access_requests"][0]["status"] == "rejected"


def test_access_request_revocation_updates_request_and_blocks_invocation(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    owner_secret = b"o" * 32
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "revocable.txt"
    source.write_text("revocable access", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)
    request = service.request_access(
        wallet.wallet_id,
        requester_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, record.record_id)],
        abilities=["record/decrypt"],
        purpose="identity_verification",
    )
    approved = service.approve_access_request(
        wallet.wallet_id,
        request_id=request.request_id,
        actor_did=OWNER,
        issuer_secret=owner_secret,
        audience_secret=delegate_secret,
        issue_invocation=True,
    )

    revoked = service.revoke_access_request(
        wallet.wallet_id,
        request_id=approved.request_id,
        actor_did=OWNER,
        reason="user withdrew consent",
    )

    assert revoked.status == "revoked"
    assert revoked.details["revocation_reason"] == "user withdrew consent"
    assert service.grants[approved.grant_id].status == "revoked"
    assert service.list_access_requests(wallet.wallet_id, status="revoked")[0].request_id == request.request_id
    restored = WalletService(storage_dir=tmp_path)
    restored.import_wallet_snapshot(service.export_wallet_snapshot(wallet.wallet_id))
    assert restored.access_requests[request.request_id].status == "revoked"
    assert restored.grants[approved.grant_id].status == "revoked"
    with pytest.raises(AccessDeniedError, match="not active"):
        service.decrypt_record_with_invocation(
            wallet.wallet_id,
            record.record_id,
            actor_did=ADVOCATE,
            invocation=service.invocations[approved.invocation_id],
            actor_secret=delegate_secret,
        )


def test_access_request_listing_filters_for_review_inbox(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    first = service.request_access(
        wallet.wallet_id,
        requester_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, "rec-one")],
        abilities=["record/analyze"],
        purpose="screening",
    )
    second = service.request_access(
        wallet.wallet_id,
        requester_did="did:key:researcher",
        audience_did="did:key:analytics-service",
        resources=[resource_for_record(wallet.wallet_id, "rec-two")],
        abilities=["record/analyze"],
        purpose="aggregate_planning",
    )
    service.reject_access_request(
        wallet.wallet_id,
        request_id=second.request_id,
        actor_did=OWNER,
        reason="not needed",
    )

    assert [request.request_id for request in service.list_access_requests(wallet.wallet_id)] == [
        first.request_id,
        second.request_id,
    ]
    assert [request.request_id for request in service.list_access_requests(wallet.wallet_id, status="pending")] == [
        first.request_id,
    ]
    assert [
        request.request_id
        for request in service.list_access_requests(
            wallet.wallet_id,
            status="rejected",
            audience_did="did:key:analytics-service",
        )
    ] == [second.request_id]


def test_access_request_review_items_include_approval_and_grant_state(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    owner_secret = b"o" * 32
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(
        owner_did=OWNER,
        controller_dids=[OWNER, SECOND_CONTROLLER],
        governance_policy={"threshold": 2, "approver_dids": [OWNER, SECOND_CONTROLLER]},
    )
    source = tmp_path / "threshold-access.txt"
    source.write_text("threshold access text", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)
    resource = resource_for_record(wallet.wallet_id, record.record_id)
    access_request = service.request_access(
        wallet.wallet_id,
        requester_did=ADVOCATE,
        resources=[resource],
        abilities=["record/decrypt"],
        purpose="identity_verification",
    )

    [pending_item] = service.access_request_review_items(wallet.wallet_id, status="pending")
    assert pending_item["request_id"] == access_request.request_id
    assert pending_item["approval_required"] is True
    assert pending_item["approval_id"] is None
    assert pending_item["approval_count"] == 0
    assert pending_item["grant_status"] is None

    approval = service.request_approval(
        wallet.wallet_id,
        requested_by=OWNER,
        operation="grant/create",
        resources=[resource],
        abilities=["record/decrypt"],
    )
    service.approve_approval(wallet.wallet_id, approval_id=approval.approval_id, approver_did=OWNER)

    [partial_item] = service.access_request_review_items(wallet.wallet_id, status="pending")
    assert partial_item["approval_id"] == approval.approval_id
    assert partial_item["approval_status"] == "pending"
    assert partial_item["approval_threshold"] == 2
    assert partial_item["approval_count"] == 1

    service.approve_approval(wallet.wallet_id, approval_id=approval.approval_id, approver_did=SECOND_CONTROLLER)
    service.approve_access_request(
        wallet.wallet_id,
        request_id=access_request.request_id,
        actor_did=OWNER,
        issuer_secret=owner_secret,
        audience_secret=delegate_secret,
        approval_id=approval.approval_id,
    )

    [approved_item] = service.access_request_review_items(wallet.wallet_id, status="approved")
    assert approved_item["approval_status"] == "approved"
    assert approved_item["approval_count"] == 2
    assert approved_item["grant_status"] == "active"


def test_invocation_rejects_tampering_wrong_ability_and_revoked_grant(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    owner_secret = b"o" * 32
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "case-note.txt"
    source.write_text("Private document", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, record.record_id)],
        abilities=["record/analyze"],
        issuer_secret=owner_secret,
        audience_secret=delegate_secret,
    )
    invocation = service.issue_invocation(
        wallet.wallet_id,
        grant_id=grant.grant_id,
        actor_did=ADVOCATE,
        resource=resource_for_record(wallet.wallet_id, record.record_id),
        ability="record/analyze",
        actor_secret=delegate_secret,
    )
    tampered = WalletInvocation(**(invocation.to_dict() | {"caveats": {"tampered": True}}))
    tampered_issuer = WalletInvocation(
        **(invocation.to_dict() | {"issuer_did": "did:key:other", "signature": ""})
    )
    tampered_issuer.signature = sign_invocation(tampered_issuer, delegate_secret)

    with pytest.raises(AccessDeniedError, match="capability"):
        service.verify_invocation(
            wallet.wallet_id,
            invocation,
            actor_did=ADVOCATE,
            resource=resource_for_record(wallet.wallet_id, record.record_id),
            ability="record/decrypt",
            actor_secret=delegate_secret,
        )
    with pytest.raises(AccessDeniedError, match="signature"):
        service.verify_invocation(
            wallet.wallet_id,
            tampered,
            actor_did=ADVOCATE,
            resource=resource_for_record(wallet.wallet_id, record.record_id),
            ability="record/analyze",
            actor_secret=delegate_secret,
        )
    with pytest.raises(AccessDeniedError, match="issuer"):
        service.verify_invocation(
            wallet.wallet_id,
            tampered_issuer,
            actor_did=ADVOCATE,
            resource=resource_for_record(wallet.wallet_id, record.record_id),
            ability="record/analyze",
            actor_secret=delegate_secret,
        )

    service.revoke_grant(wallet.wallet_id, grant.grant_id, actor_did=OWNER)
    with pytest.raises(AccessDeniedError, match="not active"):
        service.verify_invocation(
            wallet.wallet_id,
            invocation,
            actor_did=ADVOCATE,
            resource=resource_for_record(wallet.wallet_id, record.record_id),
            ability="record/analyze",
            actor_secret=delegate_secret,
        )


def test_invocation_snapshot_preserves_verifiable_invocation(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    owner_secret = b"o" * 32
    delegate_secret = b"d" * 32
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "note.txt"
    source.write_text("Snapshot invocation", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=ADVOCATE,
        resources=[resource_for_record(wallet.wallet_id, record.record_id)],
        abilities=["record/analyze"],
        issuer_secret=owner_secret,
        audience_secret=delegate_secret,
    )
    invocation = service.issue_invocation(
        wallet.wallet_id,
        grant_id=grant.grant_id,
        actor_did=ADVOCATE,
        resource=resource_for_record(wallet.wallet_id, record.record_id),
        ability="record/analyze",
        actor_secret=delegate_secret,
    )
    snapshot = service.export_wallet_snapshot(wallet.wallet_id)
    restored = WalletService(storage_dir=tmp_path)
    restored.import_wallet_snapshot(snapshot)

    restored.verify_invocation(
        wallet.wallet_id,
        restored.invocations[invocation.invocation_id],
        actor_did=ADVOCATE,
        resource=resource_for_record(wallet.wallet_id, record.record_id),
        ability="record/analyze",
        actor_secret=delegate_secret,
    )


def test_manifest_serialization_is_stable(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "doc.txt"
    source.write_text("stable manifest", encoding="utf-8")
    service.add_document(wallet.wallet_id, source)

    assert service.get_wallet_manifest_canonical(wallet.wallet_id) == service.get_wallet_manifest_canonical(
        wallet.wallet_id
    )


def test_audit_events_form_hash_chain(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "doc.txt"
    source.write_text("audit me", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)
    service.decrypt_record(wallet.wallet_id, record.record_id, actor_did=OWNER)

    events = service.get_audit_log(wallet.wallet_id)
    assert len(events) >= 3
    for previous, current in zip(events, events[1:]):
        assert current.hash_prev == previous.hash_self


def test_ipfs_storage_backend_stores_only_encrypted_payloads(tmp_path):
    fake_ipfs = FakeIPFSBackend()
    service = WalletService(storage_backend=IPFSEncryptedBlobStore(fake_ipfs))
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "secret.txt"
    source.write_text("plain secret should not be in ipfs bytes", encoding="utf-8")

    record = service.add_document(wallet.wallet_id, source)
    version = service.versions[record.current_version_id]

    assert version.encrypted_payload_ref.storage_type == "ipfs"
    assert version.encrypted_payload_ref.uri.startswith("ipfs://fakecid-")
    assert fake_ipfs.pinned
    assert b"plain secret" not in b"".join(fake_ipfs.blocks.values())
    assert service.decrypt_record(wallet.wallet_id, record.record_id, actor_did=OWNER) == source.read_bytes()


def test_ipfs_storage_backend_rejects_hash_mismatch():
    fake_ipfs = FakeIPFSBackend()
    store = IPFSEncryptedBlobStore(fake_ipfs)
    ref = store.put(b"encrypted bytes")
    cid = ref.uri.removeprefix("ipfs://")
    fake_ipfs.blocks[cid] = b"tampered bytes"

    with pytest.raises(ValueError, match="hash mismatch"):
        store.get(ref)


def test_s3_and_filecoin_stores_round_trip_encrypted_bytes():
    s3_client = FakeS3Client()
    s3_store = S3EncryptedBlobStore(s3_client, bucket="wallet-test", prefix="encrypted")
    filecoin_backend = FakeFilecoinBackend()
    filecoin_store = FilecoinEncryptedBlobStore(filecoin_backend)

    s3_ref = s3_store.put(b"encrypted payload")
    filecoin_ref = filecoin_store.put(b"encrypted payload")

    assert s3_ref.uri.startswith("s3://wallet-test/encrypted/")
    assert filecoin_ref.uri.startswith("filecoin://piece-")
    assert s3_store.get(s3_ref) == b"encrypted payload"
    assert filecoin_store.get(filecoin_ref) == b"encrypted payload"


def test_replicated_storage_records_mirrors_and_keeps_plaintext_out(tmp_path):
    fake_ipfs = FakeIPFSBackend()
    s3_client = FakeS3Client()
    filecoin_backend = FakeFilecoinBackend()
    storage = ReplicatedEncryptedBlobStore(
        LocalEncryptedBlobStore(tmp_path / "primary"),
        mirrors=[
            IPFSEncryptedBlobStore(fake_ipfs),
            S3EncryptedBlobStore(s3_client, bucket="wallet-test"),
            FilecoinEncryptedBlobStore(filecoin_backend),
        ],
    )
    service = WalletService(storage_backend=storage)
    wallet = service.create_wallet(owner_did=OWNER)
    owner_secret = b"r" * 32
    source = tmp_path / "replicated.txt"
    source.write_text("replicated plaintext must stay encrypted", encoding="utf-8")

    record = service.add_document(wallet.wallet_id, source, actor_secret=owner_secret)
    version = service.versions[record.current_version_id]
    mirror_types = {mirror.storage_type for mirror in version.encrypted_payload_ref.mirrors}

    assert version.encrypted_payload_ref.storage_type == "local"
    assert mirror_types == {"ipfs", "s3", "filecoin"}
    assert b"replicated plaintext" not in b"".join(fake_ipfs.blocks.values())
    assert b"replicated plaintext" not in b"".join(s3_client.objects.values())
    assert b"replicated plaintext" not in b"".join(filecoin_backend.objects.values())
    manifest = service.export_wallet_snapshot(wallet.wallet_id)
    assert {mirror["storage_type"] for mirror in manifest["versions"][0]["encrypted_payload_ref"]["mirrors"]} == mirror_types
    restored = WalletService(storage_backend=storage)
    restored.import_wallet_snapshot(manifest)
    restored.set_principal_secret(OWNER, owner_secret)
    assert restored.decrypt_record(wallet.wallet_id, record.record_id, actor_did=OWNER) == source.read_bytes()


def test_replicated_storage_reads_from_mirror_when_primary_fails():
    fake_ipfs = FakeIPFSBackend()
    s3_client = FakeS3Client()
    storage = ReplicatedEncryptedBlobStore(
        IPFSEncryptedBlobStore(fake_ipfs),
        mirrors=[S3EncryptedBlobStore(s3_client, bucket="wallet-test")],
    )
    ref = storage.put(b"encrypted payload")
    cid = ref.uri.removeprefix("ipfs://")
    fake_ipfs.blocks[cid] = b"tampered primary"

    assert storage.get(ref) == b"encrypted payload"


def test_record_storage_health_detects_and_repairs_bad_mirrors(tmp_path):
    fake_ipfs = FakeIPFSBackend()
    s3_client = FakeS3Client()
    storage = ReplicatedEncryptedBlobStore(
        LocalEncryptedBlobStore(tmp_path / "primary"),
        mirrors=[
            IPFSEncryptedBlobStore(fake_ipfs),
            S3EncryptedBlobStore(s3_client, bucket="wallet-test"),
        ],
    )
    service = WalletService(storage_backend=storage)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "repair.txt"
    source.write_text("repair plaintext must remain encrypted", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source, metadata={"title": "Repair me"})
    version = service.versions[record.current_version_id]

    assert service.verify_record_storage(wallet.wallet_id, record.record_id).ok is True
    ipfs_payload = next(mirror for mirror in version.encrypted_payload_ref.mirrors if mirror.storage_type == "ipfs")
    fake_ipfs.blocks[ipfs_payload.uri.removeprefix("ipfs://")] = b"tampered encrypted payload"
    s3_client.objects.clear()

    broken = service.verify_record_storage(wallet.wallet_id, record.record_id)
    assert broken.ok is False
    assert any(not status.ok and status.storage_type == "ipfs" for status in broken.payload)
    assert any(not status.ok and status.storage_type == "s3" for status in broken.payload)
    wallet_report = service.verify_wallet_storage(wallet.wallet_id)
    assert wallet_report.ok is False
    assert wallet_report.record_count == 1
    assert wallet_report.replica_count == 6
    assert wallet_report.failed_replica_count >= 2
    assert wallet_report.storage_types == {"ipfs": 2, "local": 2, "s3": 2}
    assert wallet_report.to_dict()["reports"][0]["record_id"] == record.record_id
    assert service.get_audit_log(wallet.wallet_id)[-1].action == "storage/verify_wallet"

    repaired = service.repair_record_storage(wallet.wallet_id, record.record_id, actor_did=OWNER)
    assert repaired.ok is True
    assert repaired.repaired is True
    assert any(status.repaired and status.storage_type == "ipfs" for status in repaired.payload)
    assert any(status.repaired and status.storage_type == "s3" for status in repaired.metadata)
    assert b"repair plaintext" not in b"".join(fake_ipfs.blocks.values())
    assert b"repair plaintext" not in b"".join(s3_client.objects.values())
    assert service.verify_record_storage(wallet.wallet_id, record.record_id).ok is True
    assert service.get_audit_log(wallet.wallet_id)[-1].action == "storage/verify"
    assert any(event.action == "storage/repair" for event in service.get_audit_log(wallet.wallet_id))


def test_wallet_storage_repair_repairs_all_record_replicas(tmp_path):
    s3_client = FakeS3Client()
    storage = ReplicatedEncryptedBlobStore(
        LocalEncryptedBlobStore(tmp_path / "primary"),
        mirrors=[S3EncryptedBlobStore(s3_client, bucket="wallet-test")],
    )
    service = WalletService(storage_backend=storage)
    wallet = service.create_wallet(owner_did=OWNER)
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first wallet repair plaintext", encoding="utf-8")
    second.write_text("second wallet repair plaintext", encoding="utf-8")
    record1 = service.add_document(wallet.wallet_id, first, metadata={"title": "First"})
    record2 = service.add_document(wallet.wallet_id, second, metadata={"title": "Second"})

    # Remove one mirror payload and one mirror metadata blob across different records.
    version1 = service.versions[record1.current_version_id]
    version2 = service.versions[record2.current_version_id]
    s3_payload_ref = version1.encrypted_payload_ref.mirrors[0]
    s3_metadata_ref = version2.encrypted_metadata_ref.mirrors[0]
    del s3_client.objects[("wallet-test", s3_payload_ref.uri.split("/", 3)[-1])]
    del s3_client.objects[("wallet-test", s3_metadata_ref.uri.split("/", 3)[-1])]

    broken = service.verify_wallet_storage(wallet.wallet_id)
    assert broken.ok is False
    assert broken.failed_replica_count == 2

    repaired = service.repair_wallet_storage(wallet.wallet_id, actor_did=OWNER)
    assert repaired.ok is True
    assert repaired.record_count == 2
    assert repaired.repaired is True
    assert repaired.repaired_replica_count == 2
    assert repaired.storage_types == {"local": 4, "s3": 4}
    assert service.verify_wallet_storage(wallet.wallet_id).ok is True
    actions = [event.action for event in service.get_audit_log(wallet.wallet_id)]
    assert "storage/repair_wallet" in actions


def test_record_storage_repair_restores_missing_primary_from_mirror(tmp_path):
    s3_client = FakeS3Client()
    storage = ReplicatedEncryptedBlobStore(
        LocalEncryptedBlobStore(tmp_path / "primary"),
        mirrors=[S3EncryptedBlobStore(s3_client, bucket="wallet-test")],
    )
    service = WalletService(storage_backend=storage)
    wallet = service.create_wallet(owner_did=OWNER)
    source = tmp_path / "primary-repair.txt"
    source.write_text("primary repair plaintext", encoding="utf-8")
    record = service.add_document(wallet.wallet_id, source)
    version = service.versions[record.current_version_id]
    primary_path = version.encrypted_payload_ref.uri.removeprefix("local://")

    os.unlink(primary_path)
    broken = service.verify_record_storage(wallet.wallet_id, record.record_id, include_metadata=False)
    assert broken.ok is False
    assert broken.payload[0].role == "primary"

    repaired = service.repair_record_storage(
        wallet.wallet_id,
        record.record_id,
        actor_did=OWNER,
        include_metadata=False,
    )
    assert repaired.ok is True
    assert repaired.payload[0].repaired is True
    assert service.decrypt_record(wallet.wallet_id, record.record_id, actor_did=OWNER) == source.read_bytes()


def test_analytics_contribution_requires_consented_fields(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    consent = service.create_analytics_consent(
        wallet.wallet_id,
        actor_did=OWNER,
        template_id="housing_needs_by_county_v1",
        allowed_record_types=["location", "need"],
        allowed_derived_fields=["county", "need_category"],
        aggregation_policy={"min_cohort_size": 2},
    )

    contribution = service.create_analytics_contribution(
        wallet.wallet_id,
        actor_did=OWNER,
        consent_id=consent.consent_id,
        template_id="housing_needs_by_county_v1",
        fields={"county": "Multnomah", "need_category": "housing"},
    )

    assert service.verify_analytics_contribution(contribution.contribution_id) is True
    assert "wallet_id" not in contribution.to_dict()
    with pytest.raises(AccessDeniedError, match="not consented"):
        service.create_analytics_contribution(
            wallet.wallet_id,
            actor_did=OWNER,
            consent_id=consent.consent_id,
            template_id="housing_needs_by_county_v1",
            fields={"county": "Multnomah", "precise_lat": 45.515232},
        )


def test_analytics_template_constrains_consent_and_snapshot(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    template = service.create_analytics_template(
        template_id="housing_template_v1",
        title="Housing needs",
        purpose="County-level housing service planning",
        allowed_record_types=["location", "need"],
        allowed_derived_fields=["county", "need_category"],
        aggregation_policy={"min_cohort_size": 5, "epsilon_budget": 0.5},
        created_by="did:key:analyst",
    )

    assert template.template_id == "housing_template_v1"
    assert [item.template_id for item in service.list_analytics_templates()] == ["housing_template_v1"]

    with pytest.raises(AccessDeniedError, match="fields exceed template"):
        service.create_analytics_consent(
            wallet.wallet_id,
            actor_did=OWNER,
            template_id=template.template_id,
            allowed_record_types=["location"],
            allowed_derived_fields=["county", "precise_lat"],
        )

    with pytest.raises(AccessDeniedError, match="min_cohort_size"):
        service.create_analytics_consent(
            wallet.wallet_id,
            actor_did=OWNER,
            template_id=template.template_id,
            allowed_record_types=["location"],
            allowed_derived_fields=["county"],
            aggregation_policy={"min_cohort_size": 2, "epsilon_budget": 0.5},
        )

    consent = service.create_analytics_consent(
        wallet.wallet_id,
        actor_did=OWNER,
        template_id=template.template_id,
        allowed_record_types=["location"],
        allowed_derived_fields=["county"],
    )
    assert consent.aggregation_policy["min_cohort_size"] == 5
    assert consent.aggregation_policy["epsilon_budget"] == 0.5

    snapshot = service.export_wallet_snapshot(wallet.wallet_id)
    restored = WalletService(storage_dir=tmp_path / "restored")
    restored.import_wallet_snapshot(snapshot)
    assert restored.list_analytics_templates()[0].template_id == template.template_id


def test_analytics_template_review_states_gate_consent_contribution_and_queries(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    template = service.create_analytics_template(
        template_id="reviewed_template_v1",
        title="Reviewed housing study",
        purpose="Template lifecycle review",
        allowed_record_types=["location"],
        allowed_derived_fields=["county"],
        aggregation_policy={"min_cohort_size": 1, "epsilon_budget": 0.5},
        created_by="did:key:analyst",
        status="draft",
    )

    assert template.status == "draft"
    assert service.list_analytics_templates() == []
    assert service.list_analytics_templates(include_inactive=True)[0].status == "draft"

    with pytest.raises(AccessDeniedError, match="not active"):
        service.create_analytics_consent(
            wallet.wallet_id,
            actor_did=OWNER,
            template_id=template.template_id,
            allowed_record_types=["location"],
            allowed_derived_fields=["county"],
        )

    with pytest.raises(AccessDeniedError, match="Only the template creator"):
        service.set_analytics_template_status(template.template_id, actor_did=OWNER, status="approved")

    service.set_analytics_template_status(template.template_id, actor_did="did:key:analyst", status="approved")
    assert service.list_analytics_templates()[0].template_id == template.template_id
    consent = service.create_analytics_consent(
        wallet.wallet_id,
        actor_did=OWNER,
        template_id=template.template_id,
        allowed_record_types=["location"],
        allowed_derived_fields=["county"],
    )
    service.create_analytics_contribution(
        wallet.wallet_id,
        actor_did=OWNER,
        consent_id=consent.consent_id,
        template_id=template.template_id,
        fields={"county": "Multnomah"},
    )

    service.set_analytics_template_status(template.template_id, actor_did="did:key:analyst", status="paused")
    with pytest.raises(AccessDeniedError, match="not active"):
        service.run_aggregate_count(template.template_id, min_cohort_size=1)
    with pytest.raises(AccessDeniedError, match="not active"):
        service.create_analytics_contribution(
            wallet.wallet_id,
            actor_did=OWNER,
            consent_id=consent.consent_id,
            template_id=template.template_id,
            fields={"county": "Multnomah"},
        )

    with pytest.raises(ValueError, match="status"):
        service.set_analytics_template_status(template.template_id, actor_did="did:key:analyst", status="live")


def test_retired_analytics_template_blocks_new_contributions(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    template = service.create_analytics_template(
        template_id="retired_template_v1",
        title="Retired study",
        purpose="Test retired template behavior",
        allowed_record_types=["location"],
        allowed_derived_fields=["county"],
        aggregation_policy={"min_cohort_size": 2, "epsilon_budget": 0.5},
        created_by="did:key:analyst",
    )
    consent = service.create_analytics_consent(
        wallet.wallet_id,
        actor_did=OWNER,
        template_id=template.template_id,
        allowed_record_types=["location"],
        allowed_derived_fields=["county"],
    )
    service.retire_analytics_template(template.template_id, actor_did="did:key:analyst")

    with pytest.raises(AccessDeniedError, match="not active"):
        service.create_analytics_contribution(
            wallet.wallet_id,
            actor_did=OWNER,
            consent_id=consent.consent_id,
            template_id=template.template_id,
            fields={"county": "Multnomah"},
        )


def test_revoked_analytics_consent_blocks_future_contribution_preserves_aggregate_history(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet1 = service.create_wallet(owner_did="did:key:owner1")
    wallet2 = service.create_wallet(owner_did="did:key:owner2")
    template_id = "revoked_consent_history_v1"
    consents = []

    for wallet, owner in [(wallet1, "did:key:owner1"), (wallet2, "did:key:owner2")]:
        consent = service.create_analytics_consent(
            wallet.wallet_id,
            actor_did=owner,
            template_id=template_id,
            allowed_record_types=["location", "need"],
            allowed_derived_fields=["county"],
            aggregation_policy={"min_cohort_size": 2, "epsilon_budget": 0.5},
        )
        consents.append((wallet, owner, consent))
        service.create_analytics_contribution(
            wallet.wallet_id,
            actor_did=owner,
            consent_id=consent.consent_id,
            template_id=template_id,
            fields={"county": "Multnomah"},
        )

    result = service.run_aggregate_count(template_id, epsilon=0.25)
    assert result.released is True
    assert result.result_id in service.aggregate_results
    service.revoke_analytics_consent(wallet1.wallet_id, consents[0][2].consent_id, actor_did="did:key:owner1")

    with pytest.raises(AccessDeniedError, match="not active"):
        service.create_analytics_contribution(
            wallet1.wallet_id,
            actor_did="did:key:owner1",
            consent_id=consents[0][2].consent_id,
            template_id=template_id,
            fields={"county": "Multnomah"},
        )

    assert service.aggregate_results[result.result_id].to_dict() == result.to_dict()
    query_events = [
        event for event in service.get_audit_log(wallet1.wallet_id) if event.action == "analytics/query"
    ]
    revoke_events = [
        event for event in service.get_audit_log(wallet1.wallet_id) if event.action == "analytics/consent_revoke"
    ]
    assert query_events[-1].details["result_id"] == result.result_id
    assert revoke_events[-1].details["template_id"] == template_id


def test_analytics_duplicate_nullifier_rejected_even_with_new_consent(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    consent1 = service.create_analytics_consent(
        wallet.wallet_id,
        actor_did=OWNER,
        template_id="food_needs_by_county_v1",
        allowed_record_types=["location", "need"],
        allowed_derived_fields=["county"],
    )
    service.create_analytics_contribution(
        wallet.wallet_id,
        actor_did=OWNER,
        consent_id=consent1.consent_id,
        template_id="food_needs_by_county_v1",
        fields={"county": "Lane"},
    )
    consent2 = service.create_analytics_consent(
        wallet.wallet_id,
        actor_did=OWNER,
        template_id="food_needs_by_county_v1",
        allowed_record_types=["location", "need"],
        allowed_derived_fields=["county"],
    )

    with pytest.raises(AccessDeniedError, match="Duplicate"):
        service.create_analytics_contribution(
            wallet.wallet_id,
            actor_did=OWNER,
            consent_id=consent2.consent_id,
            template_id="food_needs_by_county_v1",
            fields={"county": "Lane"},
        )


def test_aggregate_count_suppresses_small_cohorts_and_releases_threshold(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet1 = service.create_wallet(owner_did="did:key:owner1")
    wallet2 = service.create_wallet(owner_did="did:key:owner2")
    template_id = "utility_needs_by_county_v1"

    consent1 = service.create_analytics_consent(
        wallet1.wallet_id,
        actor_did="did:key:owner1",
        template_id=template_id,
        allowed_record_types=["location", "need"],
        allowed_derived_fields=["county"],
        aggregation_policy={"min_cohort_size": 2},
    )
    service.create_analytics_contribution(
        wallet1.wallet_id,
        actor_did="did:key:owner1",
        consent_id=consent1.consent_id,
        template_id=template_id,
        fields={"county": "Multnomah"},
    )

    suppressed = service.run_aggregate_count(template_id)
    assert suppressed.released is False
    assert suppressed.suppressed is True
    assert suppressed.count is None
    assert suppressed.cohort_size == 1

    consent2 = service.create_analytics_consent(
        wallet2.wallet_id,
        actor_did="did:key:owner2",
        template_id=template_id,
        allowed_record_types=["location", "need"],
        allowed_derived_fields=["county"],
        aggregation_policy={"min_cohort_size": 2},
    )
    service.create_analytics_contribution(
        wallet2.wallet_id,
        actor_did="did:key:owner2",
        consent_id=consent2.consent_id,
        template_id=template_id,
        fields={"county": "Multnomah"},
    )

    released = service.run_aggregate_count(template_id)
    assert released.released is True
    assert released.suppressed is False
    assert released.count == 2
    assert released.cohort_size == 2


def test_multi_dimensional_aggregate_suppresses_sparse_cells_without_labels(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    template = service.create_analytics_template(
        template_id="multi_dimensional_sparse_v1",
        title="County and need cohorts",
        purpose="Sparse-cell suppression",
        allowed_record_types=["location", "need"],
        allowed_derived_fields=["county", "need_category"],
        aggregation_policy={"min_cohort_size": 2, "epsilon_budget": 0.5},
        created_by="did:key:analyst",
    )
    rows = [
        ("did:key:cohort-owner1", {"county": "Multnomah", "need_category": "housing"}),
        ("did:key:cohort-owner2", {"county": "Multnomah", "need_category": "housing"}),
        ("did:key:cohort-owner3", {"county": "Lane", "need_category": "food"}),
        ("did:key:cohort-owner4", {"county": "Lane", "need_category": "food"}),
        ("did:key:cohort-owner5", {"county": "Clackamas", "need_category": "rare-need"}),
    ]

    for owner, fields in rows:
        wallet = service.create_wallet(owner_did=owner)
        consent = service.create_analytics_consent(
            wallet.wallet_id,
            actor_did=owner,
            template_id=template.template_id,
            allowed_record_types=["location", "need"],
            allowed_derived_fields=["county", "need_category"],
        )
        service.create_analytics_contribution(
            wallet.wallet_id,
            actor_did=owner,
            consent_id=consent.consent_id,
            template_id=template.template_id,
            fields=fields,
        )

    result = service.run_aggregate_count_by_fields(
        template.template_id,
        group_by=["county", "need_category"],
        min_cohort_size=2,
    )
    serialized = json.dumps(result.to_dict())

    assert result.released is True
    assert result.suppressed is True
    assert result.metric == "count_by_fields"
    assert result.group_by == ["county", "need_category"]
    assert result.count == 4
    assert result.cohort_size == 4
    assert result.suppressed_cohort_count == 1
    assert len(result.cohorts) == 2
    assert {cohort["count"] for cohort in result.cohorts} == {2}
    assert "sparse-cell-suppression" in result.privacy_notes
    assert "suppressed-cohorts:1" in result.privacy_notes
    assert "rare-need" not in serialized
    assert "Clackamas" not in serialized

    with pytest.raises(AccessDeniedError, match="group_by fields exceed template policy"):
        service.run_aggregate_count_by_fields(
            template.template_id,
            group_by=["county", "precise_age"],
            min_cohort_size=2,
        )


def test_differentially_private_aggregate_count_suppresses_exact_counts(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet1 = service.create_wallet(owner_did="did:key:owner1")
    wallet2 = service.create_wallet(owner_did="did:key:owner2")
    template_id = "dp_utility_needs_by_county_v1"

    for wallet, owner in [(wallet1, "did:key:owner1"), (wallet2, "did:key:owner2")]:
        consent = service.create_analytics_consent(
            wallet.wallet_id,
            actor_did=owner,
            template_id=template_id,
            allowed_record_types=["location", "need"],
            allowed_derived_fields=["county"],
            aggregation_policy={"min_cohort_size": 2, "epsilon_budget": 0.5},
        )
        service.create_analytics_contribution(
            wallet.wallet_id,
            actor_did=owner,
            consent_id=consent.consent_id,
            template_id=template_id,
            fields={"county": "Multnomah"},
        )

    result = service.run_aggregate_count(template_id, epsilon=0.25)

    assert result.released is True
    assert result.count is None
    assert result.cohort_size == 0
    assert result.noisy_count is not None
    assert result.noisy_count >= 0
    assert result.epsilon == 0.25
    assert result.privacy_budget_key == f"template:{template_id}"
    assert result.privacy_budget_spent == 0.25
    assert result.exact_count_released is False
    assert result.cohort_size_released is False
    assert "differential-privacy:laplace" in result.privacy_notes
    events = service.get_audit_log(wallet1.wallet_id)
    query_events = [event for event in events if event.action == "analytics/query"]
    assert query_events[-1].decision == "allow"
    assert query_events[-1].details["result_id"] == result.result_id
    assert query_events[-1].details["privacy_budget_spent"] == 0.25


def test_noisy_count_uses_random_noise_unless_explicitly_seeded():
    deterministic = noisy_count(count=10, epsilon=1.0, seed_material="fixed-study")
    assert deterministic == noisy_count(count=10, epsilon=1.0, seed_material="fixed-study")

    left = noisy_count(count=10, epsilon=1.0, random_value=0.25)
    right = noisy_count(count=10, epsilon=1.0, random_value=0.75)

    assert left[1] != right[1]


def test_differentially_private_aggregate_count_uses_unseeded_noise(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_noisy_count(**kwargs):
        captured.update(kwargs)
        return float(kwargs["count"]), 0.0

    monkeypatch.setattr(wallet_analytics, "noisy_count", fake_noisy_count)
    service = WalletService(storage_dir=tmp_path)
    wallets = [
        service.create_wallet(owner_did="did:key:noise-owner1"),
        service.create_wallet(owner_did="did:key:noise-owner2"),
    ]
    template_id = "dp_unseeded_noise_v1"

    for index, wallet in enumerate(wallets, start=1):
        owner = f"did:key:noise-owner{index}"
        consent = service.create_analytics_consent(
            wallet.wallet_id,
            actor_did=owner,
            template_id=template_id,
            allowed_record_types=["location", "need"],
            allowed_derived_fields=["county"],
            aggregation_policy={"min_cohort_size": 2, "epsilon_budget": 0.5},
        )
        service.create_analytics_contribution(
            wallet.wallet_id,
            actor_did=owner,
            consent_id=consent.consent_id,
            template_id=template_id,
            fields={"county": "Multnomah"},
        )

    result = service.run_aggregate_count(template_id, epsilon=0.25)

    assert captured == {"count": 2, "epsilon": 0.25, "sensitivity": 1.0}
    assert result.noisy_count == 2.0
    assert result.noise == 0.0
    assert "noise-source:system-random" in result.privacy_notes


def test_differentially_private_aggregate_count_enforces_query_budget(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet1 = service.create_wallet(owner_did="did:key:owner1")
    wallet2 = service.create_wallet(owner_did="did:key:owner2")
    template_id = "dp_food_needs_by_county_v1"

    for wallet, owner in [(wallet1, "did:key:owner1"), (wallet2, "did:key:owner2")]:
        consent = service.create_analytics_consent(
            wallet.wallet_id,
            actor_did=owner,
            template_id=template_id,
            allowed_record_types=["location", "need"],
            allowed_derived_fields=["county"],
            aggregation_policy={"min_cohort_size": 2, "epsilon_budget": 0.3},
        )
        service.create_analytics_contribution(
            wallet.wallet_id,
            actor_did=owner,
            consent_id=consent.consent_id,
            template_id=template_id,
            fields={"county": "Lane"},
        )

    first = service.run_aggregate_count(template_id, epsilon=0.2)
    assert first.privacy_budget_spent == 0.2

    with pytest.raises(AccessDeniedError, match="privacy budget exceeded"):
        service.run_aggregate_count(template_id, epsilon=0.2)


def test_differentially_private_aggregate_count_suppresses_small_cohorts(tmp_path):
    service = WalletService(storage_dir=tmp_path)
    wallet = service.create_wallet(owner_did=OWNER)
    template_id = "dp_small_cohort_v1"
    consent = service.create_analytics_consent(
        wallet.wallet_id,
        actor_did=OWNER,
        template_id=template_id,
        allowed_record_types=["location", "need"],
        allowed_derived_fields=["county"],
        aggregation_policy={"min_cohort_size": 2, "epsilon_budget": 0.5},
    )
    service.create_analytics_contribution(
        wallet.wallet_id,
        actor_did=OWNER,
        consent_id=consent.consent_id,
        template_id=template_id,
        fields={"county": "Lane"},
    )

    result = service.run_aggregate_count(template_id, epsilon=0.25)

    assert result.released is False
    assert result.suppressed is True
    assert result.count is None
    assert result.noisy_count is None
    assert result.cohort_size == 0
    assert result.exact_count_released is False
    assert result.cohort_size_released is False
    assert "suppressed-small-cohort" in result.privacy_notes
    query_events = [event for event in service.get_audit_log(wallet.wallet_id) if event.action == "analytics/query"]
    assert query_events[-1].decision == "suppress"
    assert query_events[-1].details["suppressed"] is True
