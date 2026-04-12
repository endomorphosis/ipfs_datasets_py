import json

import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_data import (
    WorkspaceDatasetBuilder,
    export_workspace_dataset_single_parquet,
    inspect_workspace_dataset_single_parquet,
    load_workspace_dataset_single_parquet,
    load_workspace_dataset_single_parquet_summary,
    search_workspace_dataset_bm25,
    search_workspace_dataset_vector,
    summarize_workspace_dataset,
)


def test_workspace_dataset_builder_creates_indexed_dataset_for_generic_corpus():
    workspace = {
        "workspace_id": "voice-mailbox-01",
        "workspace_name": "Voice Mailbox 01",
        "source_type": "google_voice",
        "collections": [{"id": "calls", "title": "Calls"}],
        "documents": [
            {
                "id": "msg_1",
                "title": "Call transcript",
                "text": "Caller describes a breach of contract and asks about payment.",
                "timestamp": "2024-08-01T12:00:00Z",
                "document_type": "transcript",
            },
            {
                "id": "msg_2",
                "subject": "Voicemail follow-up",
                "body": "Second message repeats the contract dispute and references invoices.",
                "timestamp": "2024-08-02T12:00:00Z",
                "item_type": "voicemail",
            },
        ],
    }

    dataset = WorkspaceDatasetBuilder().build_from_workspace(workspace)
    payload = dataset.to_dict()

    assert payload["metadata"]["document_count"] == 2
    assert payload["metadata"]["collection_count"] == 1
    assert payload["bm25_index"]["backend"] == "local_bm25"
    assert payload["bm25_index"]["document_count"] == 2
    assert payload["vector_index"]["document_count"] == 2
    assert payload["knowledge_graph"]["entities"]


def test_workspace_dataset_search_and_summary_helpers_return_ranked_results():
    workspace = {
        "workspace_id": "mailbox-01",
        "workspace_name": "Inbox",
        "source_type": "email",
        "documents": [
            {"id": "email_1", "subject": "Contract dispute", "body": "Breach of contract allegations and damages."},
            {"id": "email_2", "subject": "Travel", "body": "Logistics for next week's trip."},
        ],
    }
    dataset = WorkspaceDatasetBuilder().build_from_workspace(workspace)

    bm25_results = search_workspace_dataset_bm25(dataset, "breach contract", top_k=2)
    vector_results = search_workspace_dataset_vector(dataset, "breach contract", top_k=2)
    summary = summarize_workspace_dataset(dataset)

    assert bm25_results["result_count"] >= 1
    assert bm25_results["results"][0]["id"] == "email_1"
    assert vector_results["result_count"] >= 1
    assert vector_results["results"][0]["backend"] == "local_hashed_term_projection"
    assert summary["workspace_id"] == "mailbox-01"
    assert summary["bm25_document_count"] == 2


def test_workspace_dataset_preview_and_directory_ingestion_select_textual_documents(tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "chat.txt").write_text("Discord messages about the billing dispute.", encoding="utf-8")
    (evidence_dir / "metadata.json").write_text(
        json.dumps({"id": "email_1", "subject": "Invoice", "body": "Invoice thread and payment dispute."}),
        encoding="utf-8",
    )

    builder = WorkspaceDatasetBuilder()
    dataset = builder.build_from_directory(evidence_dir, workspace_id="dir-1", workspace_name="Directory Workspace")
    preview = builder.preview_retrieval_index(
        {
            "workspace_id": "dir-1",
            "documents": [
                {"id": "meta_only", "title": "Metadata only", "text": ""},
                {"id": "plain_text", "title": "Plain text", "text": "Substantive evidence body."},
            ],
        },
        min_evidence_quality="plain_text",
    )

    assert dataset.workspace_id == "dir-1"
    assert len(dataset.documents) == 2
    assert preview["selected_document_count"] == 1
    assert preview["documents"][0]["document_id"] == "plain_text"


def test_workspace_dataset_builder_accepts_google_voice_manifest_shape():
    manifest = {
        "status": "success",
        "source_kind": "takeout",
        "manifest_path": "/tmp/google_voice_manifest.json",
        "bundles": [
            {
                "event_id": "voice_1",
                "event_type": "text_message",
                "title": "Text conversation",
                "evidence_title": "Text conversation with advocate",
                "timestamp": "2026-03-24T04:56:14Z",
                "bundle_dir": "/tmp/google_voice_bundle_1",
                "text_content": "Tenant: Please send the inspection notice.\nAdvocate: I will send it tonight.",
                "participants": ["(503) 555-0100"],
                "phone_numbers": ["(503) 555-0100"],
            }
        ],
    }

    dataset = WorkspaceDatasetBuilder().build_from_google_voice_manifest(manifest)
    payload = dataset.to_dict()

    assert payload["workspace_id"] == "takeout"
    assert payload["source_type"] == "google_voice"
    assert payload["documents"][0]["document_id"] == "voice_1"
    assert payload["documents"][0]["metadata"]["participants"] == ["(503) 555-0100"]
    assert payload["bm25_index"]["document_count"] == 1


def test_workspace_dataset_builder_accepts_discord_export_shape():
    discord_export = {
        "guild_id": "guild_1",
        "guild_name": "Tenant Support",
        "channel_id": "channel_9",
        "channel_name": "housing-help",
        "messages": [
            {
                "id": "message_1",
                "timestamp": "2026-03-24T05:00:00Z",
                "author": "advocate",
                "content": "Please upload the lease and all inspection notices.",
                "attachments": [{"url": "https://example.com/lease.pdf"}],
            }
        ],
    }

    dataset = WorkspaceDatasetBuilder().build_from_discord_export(discord_export)
    payload = dataset.to_dict()

    assert payload["workspace_id"] == "channel_9"
    assert payload["workspace_name"] == "housing-help"
    assert payload["source_type"] == "discord"
    assert payload["documents"][0]["title"] == "advocate"
    assert payload["documents"][0]["metadata"]["guild_name"] == "Tenant Support"
    assert payload["vector_index"]["document_count"] == 1


def test_workspace_dataset_builder_accepts_email_export_shape():
    email_export = {
        "status": "success",
        "protocol": "imap",
        "server": "mail.example.com",
        "folder": "INBOX",
        "emails": [
            {
                "message_id_header": "<message-1@example.com>",
                "subject": "Inspection notice",
                "from": "tenant@example.com",
                "to": "advocate@example.com",
                "date": "2026-03-24T06:00:00Z",
                "body_text": "Please review the attached inspection notice and lease.",
                "attachments": [{"filename": "notice.pdf", "size": 1234}],
            }
        ],
    }

    dataset = WorkspaceDatasetBuilder().build_from_email_export(email_export)
    payload = dataset.to_dict()

    assert payload["workspace_name"] == "INBOX"
    assert payload["source_type"] == "email"
    assert payload["documents"][0]["document_id"] == "<message-1@example.com>"
    assert payload["documents"][0]["metadata"]["from"] == "tenant@example.com"
    assert payload["documents"][0]["metadata"]["attachments"][0]["filename"] == "notice.pdf"
    assert payload["bm25_index"]["document_count"] == 1


def test_workspace_dataset_single_parquet_export_contains_index_sections(tmp_path):
    dataset = WorkspaceDatasetBuilder().build_from_workspace(
        {
            "workspace_id": "search-01",
            "workspace_name": "Search Results",
            "source_type": "search_results",
            "documents": [
                {
                    "id": "result_1",
                    "title": "Search result",
                    "text": "Substantive search result text.",
                    "source_url": "https://example.com/result-1",
                    "document_type": "search_result",
                }
            ],
        }
    )

    export_result = export_workspace_dataset_single_parquet(dataset, tmp_path / "workspace_bundle.parquet")
    rows = pq.read_table(tmp_path / "workspace_bundle.parquet").to_pylist()

    assert export_result["row_count"] == len(rows)
    assert any(row["section"] == "documents" for row in rows)
    assert any(row["section"] == "bm25_documents" for row in rows)
    assert any(row["section"] == "vector_items" for row in rows)
    assert any(row["section"] == "knowledge_graph_entities" for row in rows)


def test_workspace_dataset_single_parquet_helpers_round_trip_bundle(tmp_path):
    dataset = WorkspaceDatasetBuilder().build_from_workspace(
        {
            "workspace_id": "bundle-01",
            "workspace_name": "Bundle Workspace",
            "source_type": "discord",
            "collections": [{"id": "thread-1", "title": "Thread 1"}],
            "documents": [
                {
                    "id": "message_1",
                    "title": "Message 1",
                    "text": "Discord discussion about invoice disputes and breach claims.",
                    "document_type": "message",
                }
            ],
        }
    )
    bundle_path = tmp_path / "bundle_roundtrip.parquet"
    export_workspace_dataset_single_parquet(dataset, bundle_path)

    loaded = load_workspace_dataset_single_parquet(bundle_path)
    summary = load_workspace_dataset_single_parquet_summary(bundle_path)
    inspection = inspect_workspace_dataset_single_parquet(bundle_path)

    assert loaded["workspace_id"] == "bundle-01"
    assert len(loaded["documents"]) == 1
    assert loaded["bm25_index"]["document_count"] == 1
    assert summary["workspace_name"] == "Bundle Workspace"
    assert summary["document_count"] == 1
    assert inspection["workspace_id"] == "bundle-01"
    assert "documents" in inspection["sections"]
    assert inspection["row_count"] >= 1