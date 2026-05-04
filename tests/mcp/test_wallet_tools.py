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
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_analyze_documents_redacted import (
    wallet_analyze_documents_redacted,
)
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_create import wallet_create
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_create_document_vector_profile import (
    wallet_create_document_vector_profile,
)
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_create_location_region_proof import (
    wallet_create_location_region_proof,
)
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_extract_document_text_redacted import (
    wallet_extract_document_text_redacted,
)
from ipfs_datasets_py.mcp_server.tools.wallet_tools.wallet_list_records import wallet_list_records
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
