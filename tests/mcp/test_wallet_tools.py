from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_analytics_contribute import wallet_analytics_contribute
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_analytics_create_consent import wallet_analytics_create_consent
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_analytics_create_template import wallet_analytics_create_template
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_analytics_private_count import wallet_analytics_private_count
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_add_document import wallet_add_document
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_add_location import wallet_add_location
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_analyze_document_redacted import wallet_analyze_document_redacted
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_analyze_document_form_redacted import (
    wallet_analyze_document_form_redacted,
)
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_analyze_documents_redacted import (
    wallet_analyze_documents_redacted,
)
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_create import wallet_create
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_create_document_vector_profile import (
    wallet_create_document_vector_profile,
)
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_create_export_bundle import wallet_create_export_bundle
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_create_export_grant import wallet_create_export_grant
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_create_location_region_proof import (
    wallet_create_location_region_proof,
)
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_create_record_grant import wallet_create_record_grant
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_create_redacted_graphrag import (
    wallet_create_redacted_graphrag,
)
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_decrypt_document import wallet_decrypt_document
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_export_bundle_storage import wallet_export_bundle_storage
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_extract_document_text_redacted import (
    wallet_extract_document_text_redacted,
)
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_grant_receipts import wallet_grant_receipts
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_import_export_bundle import wallet_import_export_bundle
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_issue_export_invocation import wallet_issue_export_invocation
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_issue_record_invocation import wallet_issue_record_invocation
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_list_records import wallet_list_records
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_revoke_grant import wallet_revoke_grant
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_verify_export_bundle import wallet_verify_export_bundle
from ipfs_datasets_py.wallet.crypto import random_key


pytestmark = pytest.mark.anyio


async def test_wallet_tools_create_ingest_and_prove(tmp_path) -> None:
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    owner_key = random_key().hex()
    document = tmp_path / "note.txt"
    document.write_text("Benefits note for housing assistance.", encoding="utf-8")

    created = await wallet_create(
        owner_did="did:key:owner",
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert created["status"] == "success"
    wallet_id = created["wallet_id"]

    added_document = await wallet_add_document(
        wallet_id=wallet_id,
        actor_did="did:key:owner",
        actor_key_hex=owner_key,
        path=str(document),
        title="Benefits note",
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert added_document["status"] == "success"

    added_location = await wallet_add_location(
        wallet_id=wallet_id,
        actor_did="did:key:owner",
        lat=45.515232,
        lon=-122.678385,
        actor_key_hex=owner_key,
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert added_location["status"] == "success"

    proof = await wallet_create_location_region_proof(
        wallet_id=wallet_id,
        record_id=added_location["record_id"],
        actor_did="did:key:owner",
        region_id="multnomah_county",
        actor_key_hex=owner_key,
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert proof["status"] == "success"
    assert proof["proof"]["proof_type"] == "location_region"
    assert proof["proof"]["public_inputs"]["region_id"] == "multnomah_county"
    assert "lat" not in str(proof["proof"]["public_inputs"]).lower()

    listed = await wallet_list_records(
        wallet_id=wallet_id,
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert listed["status"] == "success"
    assert {record["data_type"] for record in listed["records"]} == {"document", "location"}


async def test_wallet_tools_redacted_document_analysis_masks_sensitive_fields(tmp_path) -> None:
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    owner_key = random_key().hex()
    document = tmp_path / "intake.txt"
    document.write_text(
        "Call 503-555-1212 or jane@example.org. SSN 123-45-6789. "
        "Address 123 Main St. Needs utility shutoff and SNAP support.",
        encoding="utf-8",
    )
    created = await wallet_create(
        owner_did="did:key:owner",
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    added = await wallet_add_document(
        wallet_id=created["wallet_id"],
        actor_did="did:key:owner",
        actor_key_hex=owner_key,
        path=str(document),
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )

    analysis = await wallet_analyze_document_redacted(
        wallet_id=created["wallet_id"],
        record_id=added["record_id"],
        actor_did="did:key:owner",
        actor_key_hex=owner_key,
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )

    assert analysis["status"] == "success"
    serialized = json.dumps(analysis["output"])
    assert "503-555-1212" not in serialized
    assert "jane@example.org" not in serialized
    assert "123-45-6789" not in serialized
    assert "123 Main St" not in serialized
    assert analysis["artifact"]["artifact_type"] == "redacted_document_analysis"
    assert set(analysis["output"]["derived_facts"]["need_categories"]) >= {"housing", "food"}


async def test_wallet_tools_create_document_vector_profile_returns_only_safe_features(tmp_path) -> None:
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    owner_key = random_key().hex()
    document = tmp_path / "profile.txt"
    document.write_text(
        "Jane uses jane@example.org and 503-555-1212. "
        "The household needs rent assistance, SNAP, and medical clinic support.",
        encoding="utf-8",
    )
    created = await wallet_create(
        owner_did="did:key:owner",
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    added = await wallet_add_document(
        wallet_id=created["wallet_id"],
        actor_did="did:key:owner",
        actor_key_hex=owner_key,
        path=str(document),
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )

    profile = await wallet_create_document_vector_profile(
        wallet_id=created["wallet_id"],
        record_id=added["record_id"],
        actor_did="did:key:owner",
        actor_key_hex=owner_key,
        chunk_size_words=8,
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )

    assert profile["status"] == "success"
    serialized = json.dumps(profile["output"])
    assert "jane@example.org" not in serialized
    assert "503-555-1212" not in serialized
    assert "Jane" not in serialized
    assert profile["artifact"]["artifact_type"] == "redacted_document_vector_profile"
    assert profile["output"]["output_policy"] == "encrypted_vector_profile"
    assert profile["output"]["profile"]["chunk_count"] >= 1
    assert profile["output"]["profile"]["feature_vector"]["housing"] >= 1
    assert profile["output"]["profile"]["feature_vector"]["food"] >= 1
    assert profile["output"]["profile"]["feature_vector"]["health"] >= 1


async def test_wallet_tools_analyze_documents_redacted_batches_safe_facts(tmp_path) -> None:
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    owner_key = random_key().hex()
    housing = tmp_path / "housing.txt"
    food = tmp_path / "food.txt"
    housing.write_text(
        "Jane uses jane@example.org for rent assistance and utility shutoff support.",
        encoding="utf-8",
    )
    food.write_text(
        "Call 503-555-1212 about SNAP and medical clinic referrals.",
        encoding="utf-8",
    )
    created = await wallet_create(
        owner_did="did:key:owner",
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    first = await wallet_add_document(
        wallet_id=created["wallet_id"],
        actor_did="did:key:owner",
        actor_key_hex=owner_key,
        path=str(housing),
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    second = await wallet_add_document(
        wallet_id=created["wallet_id"],
        actor_did="did:key:owner",
        actor_key_hex=owner_key,
        path=str(food),
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )

    analysis = await wallet_analyze_documents_redacted(
        wallet_id=created["wallet_id"],
        record_ids=[first["record_id"], second["record_id"]],
        actor_did="did:key:owner",
        actor_key_hex=owner_key,
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )

    assert analysis["status"] == "success"
    serialized = json.dumps(analysis["output"])
    assert "Jane" not in serialized
    assert "jane@example.org" not in serialized
    assert "503-555-1212" not in serialized
    assert analysis["artifact"]["artifact_type"] == "redacted_cross_document_analysis"
    assert analysis["output"]["source_record_count"] == 2
    assert set(analysis["output"]["derived_facts"]["need_categories"]) >= {"housing", "food", "health"}


async def test_wallet_tools_extract_document_text_redacted(tmp_path) -> None:
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    owner_key = random_key().hex()
    document = tmp_path / "extract.txt"
    document.write_text(
        "Jane uses jane@example.org and 503-555-1212 for rent and SNAP support.",
        encoding="utf-8",
    )
    created = await wallet_create(
        owner_did="did:key:owner",
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    added = await wallet_add_document(
        wallet_id=created["wallet_id"],
        actor_did="did:key:owner",
        actor_key_hex=owner_key,
        path=str(document),
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )

    extraction = await wallet_extract_document_text_redacted(
        wallet_id=created["wallet_id"],
        record_id=added["record_id"],
        actor_did="did:key:owner",
        actor_key_hex=owner_key,
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )

    assert extraction["status"] == "success"
    serialized = json.dumps(extraction["output"])
    assert "jane@example.org" not in serialized
    assert "503-555-1212" not in serialized
    assert extraction["artifact"]["artifact_type"] == "redacted_document_text_extraction"
    assert extraction["output"]["output_policy"] == "redacted_extracted_text"
    assert extraction["output"]["extraction"]["method"] == "text"
    assert set(extraction["output"]["derived_facts"]["need_categories"]) >= {"housing", "food"}


async def test_wallet_tools_analyze_document_form_redacted(tmp_path) -> None:
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    owner_key = random_key().hex()
    document = tmp_path / "intake-form.txt"
    document.write_text(
        "Full name: Jane Example\n"
        "Email: jane@example.org\n"
        "Phone: 503-555-1212\n"
        "Rent assistance required: yes\n"
        "SNAP enrollment: yes\n",
        encoding="utf-8",
    )
    created = await wallet_create(
        owner_did="did:key:owner",
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    added = await wallet_add_document(
        wallet_id=created["wallet_id"],
        actor_did="did:key:owner",
        actor_key_hex=owner_key,
        path=str(document),
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )

    analysis = await wallet_analyze_document_form_redacted(
        wallet_id=created["wallet_id"],
        record_id=added["record_id"],
        actor_did="did:key:owner",
        actor_key_hex=owner_key,
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )

    assert analysis["status"] == "success"
    serialized = json.dumps(analysis["output"])
    assert "Jane Example" not in serialized
    assert "jane@example.org" not in serialized
    assert "503-555-1212" not in serialized
    assert analysis["artifact"]["artifact_type"] == "redacted_document_form_analysis"
    assert analysis["output"]["output_policy"] == "redacted_form_analysis"
    assert analysis["output"]["form"]["field_count"] >= 5
    assert analysis["output"]["form"]["data_type_counts"]["email"] == 1
    assert analysis["output"]["form"]["data_type_counts"]["phone"] == 1


async def test_wallet_tools_create_redacted_graphrag(tmp_path) -> None:
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    owner_key = random_key().hex()
    first_doc = tmp_path / "housing.txt"
    second_doc = tmp_path / "food-health.txt"
    first_doc.write_text(
        "Jane Example uses jane@example.org for rent assistance and utility shutoff support.",
        encoding="utf-8",
    )
    second_doc.write_text(
        "Call 503-555-1212 about SNAP and medical clinic referrals.",
        encoding="utf-8",
    )
    created = await wallet_create(
        owner_did="did:key:owner",
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    first = await wallet_add_document(
        wallet_id=created["wallet_id"],
        actor_did="did:key:owner",
        actor_key_hex=owner_key,
        path=str(first_doc),
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    second = await wallet_add_document(
        wallet_id=created["wallet_id"],
        actor_did="did:key:owner",
        actor_key_hex=owner_key,
        path=str(second_doc),
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )

    graph = await wallet_create_redacted_graphrag(
        wallet_id=created["wallet_id"],
        record_ids=[first["record_id"], second["record_id"]],
        actor_did="did:key:owner",
        actor_key_hex=owner_key,
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )

    assert graph["status"] == "success"
    serialized = json.dumps(graph["output"])
    assert graph["artifact"]["artifact_type"] == "redacted_document_graphrag"
    assert graph["output"]["output_policy"] == "redacted_graphrag"
    assert graph["output"]["graph"]["graph_type"] == "redacted_category_entity_graph"
    assert graph["output"]["graph"]["category_record_counts"]["housing"] == 1
    assert graph["output"]["graph"]["category_record_counts"]["food"] == 1
    assert graph["output"]["graph"]["category_record_counts"]["health"] == 1
    assert "Jane Example" not in serialized
    assert "jane@example.org" not in serialized
    assert "503-555-1212" not in serialized


async def test_wallet_tools_support_private_analytics_workflow(tmp_path) -> None:
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    created = await wallet_create(
        owner_did="did:key:owner",
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    wallet_id = created["wallet_id"]

    template = await wallet_analytics_create_template(
        wallet_id=wallet_id,
        template_id="housing_gap_v1",
        title="Housing gap",
        purpose="County planning",
        created_by="did:key:analyst",
        allowed_record_types=["location", "need"],
        allowed_derived_fields=["county", "need_category"],
        min_cohort_size=1,
        epsilon_budget=0.5,
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert template["status"] == "success"
    assert template["template"]["status"] == "approved"

    consent = await wallet_analytics_create_consent(
        wallet_id=wallet_id,
        actor_did="did:key:owner",
        template_id="housing_gap_v1",
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert consent["status"] == "success"

    contribution = await wallet_analytics_contribute(
        wallet_id=wallet_id,
        actor_did="did:key:owner",
        consent_id=consent["consent"]["consent_id"],
        template_id="housing_gap_v1",
        fields={"county": "Multnomah", "need_category": "housing"},
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert contribution["status"] == "success"

    result = await wallet_analytics_private_count(
        wallet_id=wallet_id,
        template_id="housing_gap_v1",
        epsilon=0.25,
        min_cohort_size=1,
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert result["status"] == "success"
    assert result["metric"] == "count"
    assert result["released"] is True


async def test_wallet_tools_share_export_import_and_revoke_end_to_end(tmp_path) -> None:
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    owner_key = random_key().hex()
    delegate_key = random_key().hex()
    owner_did = "did:key:mcp-owner"
    delegate_did = "did:key:mcp-delegate"
    document = tmp_path / "mcp-share.txt"
    plaintext = "MCP delegate may read this document after explicit authorization."
    document.write_text(plaintext, encoding="utf-8")

    created = await wallet_create(
        owner_did=owner_did,
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert created["status"] == "success"
    wallet_id = created["wallet_id"]

    added = await wallet_add_document(
        wallet_id=wallet_id,
        actor_did=owner_did,
        actor_key_hex=owner_key,
        path=str(document),
        title="MCP shared document",
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert added["status"] == "success"
    record_id = added["record_id"]

    denied = await wallet_decrypt_document(
        wallet_id=wallet_id,
        record_id=record_id,
        actor_did=delegate_did,
        actor_key_hex=delegate_key,
        out_path=str(tmp_path / "denied.txt"),
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert denied["status"] == "error"
    assert "grant" in denied["message"]

    grant = await wallet_create_record_grant(
        wallet_id=wallet_id,
        record_id=record_id,
        issuer_did=owner_did,
        audience_did=delegate_did,
        abilities=["record/decrypt"],
        issuer_key_hex=owner_key,
        audience_key_hex=delegate_key,
        purpose="benefits_application",
        output_types=["plaintext"],
        user_presence_required=True,
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert grant["status"] == "success"
    assert grant["grant"]["caveats"]["user_presence_required"] is True

    missing_presence = await wallet_issue_record_invocation(
        wallet_id=wallet_id,
        record_id=record_id,
        grant_id=grant["grant_id"],
        actor_did=delegate_did,
        ability="record/decrypt",
        actor_key_hex=delegate_key,
        purpose="benefits_application",
        output_types=["plaintext"],
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert missing_presence["status"] == "error"
    assert "user presence" in missing_presence["message"]

    invocation = await wallet_issue_record_invocation(
        wallet_id=wallet_id,
        record_id=record_id,
        grant_id=grant["grant_id"],
        actor_did=delegate_did,
        ability="record/decrypt",
        actor_key_hex=delegate_key,
        purpose="benefits_application",
        output_types=["plaintext"],
        user_present=True,
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert invocation["status"] == "success"
    assert invocation["invocation_token"].startswith("wallet-ucan-v1.")

    delegated_out = tmp_path / "delegated.txt"
    decrypted = await wallet_decrypt_document(
        wallet_id=wallet_id,
        record_id=record_id,
        actor_did=delegate_did,
        actor_key_hex=delegate_key,
        invocation_token=invocation["invocation_token"],
        out_path=str(delegated_out),
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert decrypted["status"] == "success"
    assert delegated_out.read_text(encoding="utf-8") == plaintext

    receipts = await wallet_grant_receipts(
        wallet_id=wallet_id,
        audience_did=delegate_did,
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert receipts["status"] == "success"
    assert any(receipt["grant_id"] == grant["grant_id"] for receipt in receipts["receipts"])

    export_grant = await wallet_create_export_grant(
        wallet_id=wallet_id,
        record_ids=[record_id],
        issuer_did=owner_did,
        audience_did=delegate_did,
        issuer_key_hex=owner_key,
        audience_key_hex=delegate_key,
        purpose="benefits_portability",
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert export_grant["status"] == "success"
    export_invocation = await wallet_issue_export_invocation(
        wallet_id=wallet_id,
        grant_id=export_grant["grant_id"],
        actor_did=delegate_did,
        actor_key_hex=delegate_key,
        record_ids=[record_id],
        purpose="benefits_portability",
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert export_invocation["status"] == "success"

    bundle_path = tmp_path / "mcp-export.json"
    bundle = await wallet_create_export_bundle(
        wallet_id=wallet_id,
        actor_did=delegate_did,
        actor_key_hex=delegate_key,
        invocation_token=export_invocation["invocation_token"],
        record_ids=[record_id],
        out_path=str(bundle_path),
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert bundle["status"] == "success"
    assert bundle["record_count"] == 1
    serialized_bundle = json.dumps(bundle["bundle"], sort_keys=True)
    assert plaintext not in serialized_bundle

    verified = await wallet_verify_export_bundle(path=str(bundle_path), blob_dir=str(blob_dir))
    assert verified["status"] == "success"
    assert verified["valid"] is True
    storage = await wallet_export_bundle_storage(
        path=str(bundle_path),
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert storage["status"] == "success"
    assert storage["ok"] is True
    imported = await wallet_import_export_bundle(
        path=str(bundle_path),
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert imported["status"] == "success"
    assert imported["record_count"] == 1

    revoked = await wallet_revoke_grant(
        wallet_id=wallet_id,
        grant_id=grant["grant_id"],
        actor_did=owner_did,
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert revoked["status"] == "success"
    assert revoked["grant_status"] == "revoked"

    blocked = await wallet_decrypt_document(
        wallet_id=wallet_id,
        record_id=record_id,
        actor_did=delegate_did,
        actor_key_hex=delegate_key,
        invocation_token=invocation["invocation_token"],
        out_path=str(tmp_path / "blocked.txt"),
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert blocked["status"] == "error"
    assert "not active" in blocked["message"]

    revoked_receipts = await wallet_grant_receipts(
        wallet_id=wallet_id,
        audience_did=delegate_did,
        status_filter="revoked",
        wallet_dir=str(wallet_dir),
        blob_dir=str(blob_dir),
    )
    assert any(receipt["grant_id"] == grant["grant_id"] for receipt in revoked_receipts["receipts"])


async def test_hierarchical_manager_discovers_wallet_tools() -> None:
    manager = HierarchicalToolManager()
    categories = await manager.list_categories()
    names = {entry["name"] for entry in categories}
    assert "wallet_tools" in names


async def test_hierarchical_manager_dispatches_wallet_tool(tmp_path) -> None:
    manager = HierarchicalToolManager()
    result = await manager.dispatch(
        "wallet_tools",
        "wallet_create",
        {
            "owner_did": "did:key:owner",
            "wallet_dir": str(tmp_path / "wallets"),
            "blob_dir": str(tmp_path / "blobs"),
        },
    )
    assert result["status"] == "success"
    assert result["wallet_id"].startswith("wallet-")

    tools = await manager.list_tools("wallet_tools")
    assert tools["status"] == "success"
    tool_names = {entry["name"] for entry in tools["tools"]}
    assert "wallet_create_export_bundle" in tool_names
    assert "wallet_revoke_grant" in tool_names


async def test_hierarchical_manager_dispatches_wallet_analytics_workflow(tmp_path) -> None:
    manager = HierarchicalToolManager()
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    created = await manager.dispatch(
        "wallet_tools",
        "wallet_create",
        {
            "owner_did": "did:key:analytics-owner",
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert created["status"] == "success"
    wallet_id = created["wallet_id"]

    template = await manager.dispatch(
        "wallet_tools",
        "wallet_analytics_create_template",
        {
            "wallet_id": wallet_id,
            "template_id": "dispatch_housing_gap_v1",
            "title": "Dispatch housing gap",
            "purpose": "County planning",
            "created_by": "did:key:analytics-operator",
            "allowed_record_types": ["location", "need"],
            "allowed_derived_fields": ["county", "need_category"],
            "min_cohort_size": 1,
            "epsilon_budget": 0.5,
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert template["status"] == "success"
    assert template["template"]["template_id"] == "dispatch_housing_gap_v1"
    assert template["template"]["status"] == "approved"

    consent = await manager.dispatch(
        "wallet_tools",
        "wallet_analytics_create_consent",
        {
            "wallet_id": wallet_id,
            "actor_did": "did:key:analytics-owner",
            "template_id": "dispatch_housing_gap_v1",
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert consent["status"] == "success"
    assert consent["consent"]["status"] == "active"

    contribution = await manager.dispatch(
        "wallet_tools",
        "wallet_analytics_contribute",
        {
            "wallet_id": wallet_id,
            "actor_did": "did:key:analytics-owner",
            "consent_id": consent["consent"]["consent_id"],
            "template_id": "dispatch_housing_gap_v1",
            "fields": {"county": "Multnomah", "need_category": "housing"},
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert contribution["status"] == "success"
    assert contribution["contribution"]["fields"]["need_category"] == "housing"

    result = await manager.dispatch(
        "wallet_tools",
        "wallet_analytics_private_count",
        {
            "wallet_id": wallet_id,
            "template_id": "dispatch_housing_gap_v1",
            "epsilon": 0.25,
            "min_cohort_size": 1,
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert result["status"] == "success"
    assert result["metric"] == "count"
    assert result["released"] is True
    assert result["suppressed"] is False
    assert result["privacy_budget_spent"] == 0.25


async def test_hierarchical_manager_dispatches_wallet_redacted_analysis_tools(tmp_path) -> None:
    manager = HierarchicalToolManager()
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    owner_did = "did:key:dispatch-owner"
    owner_key = random_key().hex()
    intake = tmp_path / "dispatch-intake.txt"
    second_note = tmp_path / "dispatch-clinic.txt"
    intake.write_text(
        "Full name: Jane Example\n"
        "Email: jane@example.org\n"
        "Phone: 503-555-1212\n"
        "SSN: 123-45-6789\n"
        "Address: 123 Main St\n"
        "Rent assistance required: yes\n"
        "SNAP enrollment: yes\n",
        encoding="utf-8",
    )
    second_note.write_text(
        "Jane Example needs a medical clinic referral and utility shutoff support.",
        encoding="utf-8",
    )

    created = await manager.dispatch(
        "wallet_tools",
        "wallet_create",
        {
            "owner_did": owner_did,
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert created["status"] == "success"
    wallet_id = created["wallet_id"]
    first = await manager.dispatch(
        "wallet_tools",
        "wallet_add_document",
        {
            "wallet_id": wallet_id,
            "actor_did": owner_did,
            "actor_key_hex": owner_key,
            "path": str(intake),
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert first["status"] == "success"
    second = await manager.dispatch(
        "wallet_tools",
        "wallet_add_document",
        {
            "wallet_id": wallet_id,
            "actor_did": owner_did,
            "actor_key_hex": owner_key,
            "path": str(second_note),
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert second["status"] == "success"

    common_request = {
        "wallet_id": wallet_id,
        "record_id": first["record_id"],
        "actor_did": owner_did,
        "actor_key_hex": owner_key,
        "wallet_dir": str(wallet_dir),
        "blob_dir": str(blob_dir),
    }
    analysis = await manager.dispatch("wallet_tools", "wallet_analyze_document_redacted", common_request)
    assert analysis["status"] == "success"
    assert analysis["artifact"]["artifact_type"] == "redacted_document_analysis"
    analysis_output = json.dumps(analysis["output"], sort_keys=True)
    assert "Jane Example" not in analysis_output
    assert "jane@example.org" not in analysis_output
    assert "503-555-1212" not in analysis_output
    assert "123-45-6789" not in analysis_output
    assert "123 Main St" not in analysis_output

    extraction = await manager.dispatch("wallet_tools", "wallet_extract_document_text_redacted", common_request)
    assert extraction["status"] == "success"
    assert extraction["artifact"]["artifact_type"] == "redacted_document_text_extraction"
    extraction_output = json.dumps(extraction["output"], sort_keys=True)
    assert "Jane Example" not in extraction_output
    assert "jane@example.org" not in extraction_output
    assert "503-555-1212" not in extraction_output

    form = await manager.dispatch("wallet_tools", "wallet_analyze_document_form_redacted", common_request)
    assert form["status"] == "success"
    assert form["artifact"]["artifact_type"] == "redacted_document_form_analysis"
    assert form["output"]["form"]["field_count"] >= 5
    assert form["output"]["form"]["data_type_counts"]["email"] == 1
    assert form["output"]["form"]["data_type_counts"]["phone"] == 1
    form_output = json.dumps(form["output"], sort_keys=True)
    assert "Jane Example" not in form_output
    assert "jane@example.org" not in form_output
    assert "503-555-1212" not in form_output

    profile = await manager.dispatch(
        "wallet_tools",
        "wallet_create_document_vector_profile",
        {**common_request, "chunk_size_words": 8},
    )
    assert profile["status"] == "success"
    assert profile["artifact"]["artifact_type"] == "redacted_document_vector_profile"
    profile_output = json.dumps(profile["output"], sort_keys=True)
    assert "Jane Example" not in profile_output
    assert "jane@example.org" not in profile_output
    assert "503-555-1212" not in profile_output
    assert profile["output"]["profile"]["feature_vector"]["redacted_person_name"] == 1

    batch = await manager.dispatch(
        "wallet_tools",
        "wallet_analyze_documents_redacted",
        {
            "wallet_id": wallet_id,
            "record_ids": [first["record_id"], second["record_id"]],
            "actor_did": owner_did,
            "actor_key_hex": owner_key,
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert batch["status"] == "success"
    assert batch["artifact"]["artifact_type"] == "redacted_cross_document_analysis"
    assert batch["output"]["source_record_count"] == 2
    batch_output = json.dumps(batch["output"], sort_keys=True)
    assert "Jane Example" not in batch_output
    assert "jane@example.org" not in batch_output
    assert "503-555-1212" not in batch_output

    graph = await manager.dispatch(
        "wallet_tools",
        "wallet_create_redacted_graphrag",
        {
            "wallet_id": wallet_id,
            "record_ids": [first["record_id"], second["record_id"]],
            "actor_did": owner_did,
            "actor_key_hex": owner_key,
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert graph["status"] == "success"
    assert graph["artifact"]["artifact_type"] == "redacted_document_graphrag"
    assert graph["output"]["graph"]["graph_type"] == "redacted_category_entity_graph"
    graph_output = json.dumps(graph["output"], sort_keys=True)
    assert "Jane Example" not in graph_output
    assert "jane@example.org" not in graph_output
    assert "503-555-1212" not in graph_output


async def test_hierarchical_manager_dispatches_wallet_share_export_revoke_workflow(tmp_path) -> None:
    manager = HierarchicalToolManager()
    wallet_dir = tmp_path / "wallets"
    blob_dir = tmp_path / "blobs"
    owner_did = "did:key:dispatch-owner"
    delegate_did = "did:key:dispatch-delegate"
    owner_key = random_key().hex()
    delegate_key = random_key().hex()
    document = tmp_path / "dispatch-share.txt"
    plaintext = "Dispatch delegate access is bounded by grant and revocation."
    document.write_text(plaintext, encoding="utf-8")

    created = await manager.dispatch(
        "wallet_tools",
        "wallet_create",
        {
            "owner_did": owner_did,
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert created["status"] == "success"
    assert created["request_id"]
    wallet_id = created["wallet_id"]

    added = await manager.dispatch(
        "wallet_tools",
        "wallet_add_document",
        {
            "wallet_id": wallet_id,
            "actor_did": owner_did,
            "actor_key_hex": owner_key,
            "path": str(document),
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert added["status"] == "success"
    record_id = added["record_id"]

    denied = await manager.dispatch(
        "wallet_tools",
        "wallet_decrypt_document",
        {
            "wallet_id": wallet_id,
            "record_id": record_id,
            "actor_did": delegate_did,
            "actor_key_hex": delegate_key,
            "out_path": str(tmp_path / "denied.txt"),
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert denied["status"] == "error"
    assert "grant" in denied["message"]

    grant = await manager.dispatch(
        "wallet_tools",
        "wallet_create_record_grant",
        {
            "wallet_id": wallet_id,
            "record_id": record_id,
            "issuer_did": owner_did,
            "audience_did": delegate_did,
            "abilities": ["record/decrypt"],
            "issuer_key_hex": owner_key,
            "audience_key_hex": delegate_key,
            "purpose": "benefits_application",
            "output_types": ["plaintext"],
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert grant["status"] == "success"

    invocation = await manager.dispatch(
        "wallet_tools",
        "wallet_issue_record_invocation",
        {
            "wallet_id": wallet_id,
            "record_id": record_id,
            "grant_id": grant["grant_id"],
            "actor_did": delegate_did,
            "ability": "record/decrypt",
            "actor_key_hex": delegate_key,
            "purpose": "benefits_application",
            "output_types": ["plaintext"],
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert invocation["status"] == "success"

    delegated_out = tmp_path / "delegated.txt"
    decrypted = await manager.dispatch(
        "wallet_tools",
        "wallet_decrypt_document",
        {
            "wallet_id": wallet_id,
            "record_id": record_id,
            "actor_did": delegate_did,
            "actor_key_hex": delegate_key,
            "invocation_token": invocation["invocation_token"],
            "out_path": str(delegated_out),
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert decrypted["status"] == "success"
    assert delegated_out.read_text(encoding="utf-8") == plaintext

    export_grant = await manager.dispatch(
        "wallet_tools",
        "wallet_create_export_grant",
        {
            "wallet_id": wallet_id,
            "record_ids": [record_id],
            "issuer_did": owner_did,
            "audience_did": delegate_did,
            "issuer_key_hex": owner_key,
            "audience_key_hex": delegate_key,
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert export_grant["status"] == "success"

    export_invocation = await manager.dispatch(
        "wallet_tools",
        "wallet_issue_export_invocation",
        {
            "wallet_id": wallet_id,
            "grant_id": export_grant["grant_id"],
            "actor_did": delegate_did,
            "actor_key_hex": delegate_key,
            "record_ids": [record_id],
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert export_invocation["status"] == "success"

    bundle_path = tmp_path / "dispatch-export.json"
    bundle = await manager.dispatch(
        "wallet_tools",
        "wallet_create_export_bundle",
        {
            "wallet_id": wallet_id,
            "actor_did": delegate_did,
            "actor_key_hex": delegate_key,
            "invocation_token": export_invocation["invocation_token"],
            "record_ids": [record_id],
            "out_path": str(bundle_path),
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert bundle["status"] == "success"
    assert bundle["record_count"] == 1
    assert plaintext not in json.dumps(bundle["bundle"], sort_keys=True)

    verified = await manager.dispatch(
        "wallet_tools",
        "wallet_verify_export_bundle",
        {"path": str(bundle_path), "blob_dir": str(blob_dir)},
    )
    assert verified["status"] == "success"
    assert verified["valid"] is True
    assert verified["hash_valid"] is True
    assert verified["schema_valid"] is True

    imported = await manager.dispatch(
        "wallet_tools",
        "wallet_import_export_bundle",
        {
            "path": str(bundle_path),
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert imported["status"] == "success"
    assert imported["record_count"] == 1

    revoked = await manager.dispatch(
        "wallet_tools",
        "wallet_revoke_grant",
        {
            "wallet_id": wallet_id,
            "grant_id": grant["grant_id"],
            "actor_did": owner_did,
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert revoked["status"] == "success"
    assert revoked["grant_status"] == "revoked"

    blocked = await manager.dispatch(
        "wallet_tools",
        "wallet_decrypt_document",
        {
            "wallet_id": wallet_id,
            "record_id": record_id,
            "actor_did": delegate_did,
            "actor_key_hex": delegate_key,
            "invocation_token": invocation["invocation_token"],
            "out_path": str(tmp_path / "blocked.txt"),
            "wallet_dir": str(wallet_dir),
            "blob_dir": str(blob_dir),
        },
    )
    assert blocked["status"] == "error"
    assert "not active" in blocked["message"]
