import json
from types import SimpleNamespace

import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_data import (
    WorkspaceDatasetBuilder,
    export_workspace_dataset_single_parquet,
    inspect_workspace_dataset_single_parquet,
    load_packaged_workspace_dataset,
    load_workspace_dataset_single_parquet,
    load_workspace_dataset_single_parquet_summary,
    load_packaged_workspace_summary_view,
    package_workspace_dataset,
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
    assert "batch_size" in payload["vector_index"]
    assert "parallel_batches" in payload["vector_index"]
    assert "chunk_counts" in payload["vector_index"]
    assert "device" in payload["vector_index"]
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
    assert bm25_results["group_count"] == 1
    assert bm25_results["grouped_results"][0]["group_id"] == "document:email_1"
    assert vector_results["result_count"] >= 1
    assert vector_results["results"][0]["backend"]
    assert vector_results["group_count"] >= 1
    assert "document:email_1" in {item["group_id"] for item in vector_results["grouped_results"]}
    assert summary["workspace_id"] == "mailbox-01"
    assert summary["bm25_document_count"] == 2


def test_workspace_summary_and_package_manifest_include_logic_artifact_counts(tmp_path):
    dataset = WorkspaceDatasetBuilder().build_from_workspace(
        {
            "workspace_id": "logic-workspace",
            "workspace_name": "Logic Workspace",
            "documents": [
                {
                    "id": "doc_1",
                    "title": "Directive",
                    "text": "HACC must review reasonable accommodation requests.",
                }
            ],
        }
    )
    formal_summary = {
        "processed_document_count": 1,
        "deontic_statement_count": 2,
        "temporal_formula_count": 3,
        "first_order_formula_count": 4,
        "dcec_formula_count": 5,
        "frame_count": 6,
        "proof_count": 7,
        "proof_certificate_count": 8,
        "zkp_certificate_count": 9,
        "zkp_proof_certificate_ids": ["cert-zkp-1"],
        "zkp_backend": "groth16",
        "zkp_available": True,
        "logic_systems": {"first_order_logic": {"backend": "fol_converter", "formula_count": 4}},
    }
    dataset.metadata["formal_logic_summary"] = formal_summary
    dataset.metadata["formal_logic"] = {
        "summary": formal_summary,
        "zkp_proof_certificates": [
            {
                "certificate_id": "cert-zkp-1",
                "backend": "groth16",
                "format": "groth16_zksnark",
                "theorem": "HACC must review requests",
                "payload": {"proof_system": "groth16", "proof": "abc123"},
            }
        ],
    }

    summary = summarize_workspace_dataset(dataset)
    package = package_workspace_dataset(dataset, tmp_path / "bundle", package_name="logic_bundle", include_car=False)
    packaged_summary = load_packaged_workspace_summary_view(package["manifest_json_path"])
    packaged = load_packaged_workspace_dataset(package["manifest_json_path"])

    assert summary["first_order_formula_count"] == 4
    assert summary["proof_certificate_count"] == 8
    assert summary["zkp_certificate_count"] == 9
    assert summary["zkp_backend"] == "groth16"
    assert summary["logic_systems"]["first_order_logic"]["backend"] == "fol_converter"
    assert summary["zkp_proof_certificate_ids"] == ["cert-zkp-1"]
    assert package["summary"]["first_order_formula_count"] == 4
    assert package["summary"]["zkp_certificate_count"] == 9
    assert package["summary"]["zkp_proof_certificate_ids"] == ["cert-zkp-1"]
    assert packaged_summary["proof_certificate_count"] == 8
    assert packaged_summary["logic_systems"]["first_order_logic"]["formula_count"] == 4
    assert packaged_summary["zkp_proof_certificate_ids"] == ["cert-zkp-1"]
    assert packaged["zkp_proof_certificates"][0]["certificate_id"] == "cert-zkp-1"


def test_formal_enrichment_emits_first_order_logic_and_zkp_counts(monkeypatch):
    from ipfs_datasets_py.logic.integration.reasoning.deontological_reasoning_types import (
        DeonticModality,
        DeonticStatement,
    )
    from ipfs_datasets_py.processors.legal_data import formal_docket_enrichment as enrichment

    class FakeKnowledgeGraph:
        def to_dict(self):
            return {"entities": [], "relationships": []}

    class FakeExtractor:
        def extract_knowledge_graph(self, *_args, **_kwargs):
            return FakeKnowledgeGraph()

    class FakeDeonticExtractor:
        def extract_statements(self, _text, document_id):
            return [
                DeonticStatement(
                    id="stmt-1",
                    entity="HACC",
                    action="review reasonable accommodation requests",
                    modality=DeonticModality.OBLIGATION,
                    source_document=document_id,
                    source_text="HACC must review reasonable accommodation requests.",
                )
            ]

    class FakeConflictDetector:
        def detect_conflicts(self, _statements):
            return []

    class FakeFOLConverter:
        def convert(self, _sentence, use_cache=True):
            return SimpleNamespace(
                success=True,
                status=SimpleNamespace(value="success"),
                confidence=0.91,
                warnings=[],
                errors=[],
                metadata={"use_cache": use_cache},
                output=SimpleNamespace(
                    formula_string="Obligation(hacc, review_reasonable_accommodation_requests)",
                    predicates=[],
                    quantifiers=[],
                    operators=[],
                    variables=[],
                    confidence=0.91,
                    metadata={},
                ),
            )

    class FakeZKPProof:
        metadata = {"backend": "groth16"}

        def to_dict(self):
            return {"proof_system": "groth16", "proof": "test-proof"}

    class FakeZKPProver:
        def generate_proof(self, **_kwargs):
            return FakeZKPProof()

    monkeypatch.setattr(
        enrichment,
        "_FORMAL_SINGLETONS",
        {
            "extractor": FakeExtractor(),
            "deontic_extractor": FakeDeonticExtractor(),
            "conflict_detector": FakeConflictDetector(),
            "dcec_wrapper": None,
            "dcec_ready": False,
            "fol_converter": FakeFOLConverter(),
            "zkp_prover": FakeZKPProver(),
            "zkp_status": {"backend": "groth16", "available": True},
        },
    )

    payload = enrichment.enrich_docket_documents_with_formal_logic(
        [
            SimpleNamespace(
                document_id="doc-1",
                title="Directive",
                text="HACC must review reasonable accommodation requests.",
                date_filed="2026-01-01",
            )
        ],
        docket_id="workspace",
        case_name="Workspace",
        court="workspace",
        max_documents=1,
    )

    assert payload["first_order_logic"]["backend"] == "fol_converter"
    assert payload["first_order_logic"]["formulas"][0]["formula"] == "Obligation(hacc, review_reasonable_accommodation_requests)"
    assert payload["summary"]["first_order_formula_count"] == 1
    assert payload["summary"]["zkp_certificate_count"] == 1
    assert payload["summary"]["zkp_proof_certificate_ids"]
    assert payload["zkp_proof_certificates"][0]["format"] == "groth16_zksnark"
    assert payload["summary"]["logic_systems"]["zero_knowledge_proofs"]["backend"] == "groth16"
    assert payload["document_analyses"]["doc-1"]["first_order_formulas"]


def test_workspace_dataset_search_groups_google_voice_bundle_results(tmp_path):
    bundle_dir = tmp_path / "google_voice_bundle_search"
    bundle_dir.mkdir()
    transcript_path = bundle_dir / "transcript.txt"
    event_json_path = bundle_dir / "event.json"
    notes_path = bundle_dir / "inspection_notes.txt"

    transcript_path.write_text("Tenant asked for the inspection notice during the call.", encoding="utf-8")
    notes_path.write_text("Inspection notes from the attached text file.", encoding="utf-8")
    event_json_path.write_text(
        json.dumps(
            {
                "event_id": "voice_search_1",
                "event_type": "text_message",
                "title": "Inspection follow-up",
                "timestamp": "2026-03-24T04:56:14Z",
                "attachments": [
                    {
                        "filename": "inspection_notes.txt",
                        "path": str(notes_path),
                        "kind": "document",
                        "content_type": "text/plain",
                    }
                ],
                "source_kind": "takeout",
            }
        ),
        encoding="utf-8",
    )
    manifest = {
        "status": "success",
        "source_kind": "takeout",
        "manifest_path": str(tmp_path / "google_voice_manifest.json"),
        "bundles": [
            {
                "event_id": "voice_search_1",
                "bundle_dir": str(bundle_dir),
                "event_json_path": str(event_json_path),
                "parsed_path": str(event_json_path),
                "transcript_path": str(transcript_path),
            }
        ],
    }

    dataset = WorkspaceDatasetBuilder().build_from_google_voice_manifest(manifest)

    bm25_results = search_workspace_dataset_bm25(dataset, "inspection", top_k=5)
    vector_results = search_workspace_dataset_vector(dataset, "inspection", top_k=5)

    assert bm25_results["result_count"] == 2
    assert bm25_results["group_count"] == 1
    assert bm25_results["grouped_results"][0]["group_id"] == "google_voice_bundle_voice_search_1"
    assert bm25_results["grouped_results"][0]["source_type"] == "google_voice_bundle"
    assert bm25_results["grouped_results"][0]["document_ids"] == ["voice_search_1", "voice_search_1_attachment_1"]
    assert bm25_results["grouped_results"][0]["match_count"] == 2
    assert [item["document_id"] for item in bm25_results["grouped_results"][0]["matched_results"]] == [
        "voice_search_1",
        "voice_search_1_attachment_1",
    ]

    assert vector_results["result_count"] == 2
    assert vector_results["group_count"] == 1
    assert vector_results["grouped_results"][0]["group_id"] == "google_voice_bundle_voice_search_1"
    assert vector_results["grouped_results"][0]["document_ids"] == ["voice_search_1", "voice_search_1_attachment_1"]


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
    assert len(payload["collections"]) == 2
    assert payload["documents"][0]["document_id"] == "voice_1"
    assert payload["documents"][0]["metadata"]["collection_id"] == "google_voice_bundle_voice_1"
    assert payload["documents"][0]["metadata"]["participants"] == ["(503) 555-0100"]
    assert payload["bm25_index"]["document_count"] == 1


def test_workspace_dataset_builder_uses_google_voice_materialized_bundle_files(tmp_path):
    bundle_dir = tmp_path / "google_voice_bundle_1"
    bundle_dir.mkdir()
    transcript_path = bundle_dir / "transcript.txt"
    event_json_path = bundle_dir / "event.json"
    source_html_path = bundle_dir / "source.html"
    enrichment_path = bundle_dir / "audio.whisper.txt"

    transcript_path.write_text(
        "Tenant: Please send the inspection notice.\nAdvocate: I will send it tonight.\n",
        encoding="utf-8",
    )
    enrichment_path.write_text("Generated voicemail transcription text.", encoding="utf-8")
    source_html_path.write_text("<html><body>voice event</body></html>", encoding="utf-8")
    event_json_path.write_text(
        json.dumps(
            {
                "event_id": "voice_1",
                "event_type": "voicemail",
                "title": "Voicemail from advocate",
                "timestamp": "2026-03-24T04:56:14Z",
                "phone_numbers": ["(503) 555-0100"],
                "attachments": [{"path": str(bundle_dir / "audio.mp3"), "kind": "audio"}],
                "enrichments": [{"path": str(enrichment_path), "kind": "transcription", "source_attachment": str(bundle_dir / "audio.mp3")}],
                "deduped_gmail_message_ids": ["gmail_1"],
                "source_kind": "takeout",
                "source_html_path": str(source_html_path),
            }
        ),
        encoding="utf-8",
    )
    manifest = {
        "status": "success",
        "source_kind": "takeout",
        "manifest_path": str(tmp_path / "google_voice_manifest.json"),
        "bundles": [
            {
                "event_id": "voice_1",
                "bundle_dir": str(bundle_dir),
                "event_json_path": str(event_json_path),
                "parsed_path": str(event_json_path),
                "transcript_path": str(transcript_path),
                "source_html_path": str(source_html_path),
            }
        ],
    }

    dataset = WorkspaceDatasetBuilder().build_from_google_voice_manifest(manifest)
    payload = dataset.to_dict()

    assert len(payload["collections"]) == 2
    assert payload["collections"][1]["document_ids"] == ["voice_1", "voice_1_enrichment_1"]
    assert payload["documents"][0]["title"] == "Voicemail from advocate"
    assert "inspection notice" in payload["documents"][0]["text"]
    assert payload["documents"][0]["metadata"]["enrichment_document_ids"] == ["voice_1_enrichment_1"]
    assert payload["documents"][0]["metadata"]["parsed"]["event_type"] == "voicemail"
    assert payload["documents"][0]["metadata"]["attachments"][0]["kind"] == "audio"
    assert payload["documents"][0]["metadata"]["deduped_gmail_message_ids"] == ["gmail_1"]
    assert payload["documents"][1]["metadata"]["parent_document_id"] == "voice_1"
    assert payload["documents"][1]["metadata"]["collection_id"] == "google_voice_bundle_voice_1"
    assert payload["documents"][1]["metadata"]["enrichment_kind"] == "transcription"
    assert "Generated voicemail transcription text" in payload["documents"][1]["text"]
    assert payload["bm25_index"]["document_count"] == 2


def test_workspace_dataset_builder_promotes_text_google_voice_attachments(tmp_path):
    bundle_dir = tmp_path / "google_voice_bundle_attachments"
    bundle_dir.mkdir()
    transcript_path = bundle_dir / "transcript.txt"
    event_json_path = bundle_dir / "event.json"
    notes_path = bundle_dir / "inspection_notes.txt"

    transcript_path.write_text("Voice event transcript text.", encoding="utf-8")
    notes_path.write_text("Inspection notes from the attached text file.", encoding="utf-8")
    event_json_path.write_text(
        json.dumps(
            {
                "event_id": "voice_2",
                "event_type": "text_message",
                "title": "Text conversation with attachment",
                "timestamp": "2026-03-24T04:56:14Z",
                "phone_numbers": ["(503) 555-0100"],
                "attachments": [
                    {
                        "filename": "inspection_notes.txt",
                        "path": str(notes_path),
                        "kind": "document",
                        "content_type": "text/plain",
                    }
                ],
                "source_kind": "takeout",
            }
        ),
        encoding="utf-8",
    )
    manifest = {
        "status": "success",
        "source_kind": "takeout",
        "manifest_path": str(tmp_path / "google_voice_manifest.json"),
        "bundles": [
            {
                "event_id": "voice_2",
                "bundle_dir": str(bundle_dir),
                "event_json_path": str(event_json_path),
                "parsed_path": str(event_json_path),
                "transcript_path": str(transcript_path),
            }
        ],
    }

    dataset = WorkspaceDatasetBuilder().build_from_google_voice_manifest(manifest)
    payload = dataset.to_dict()

    assert len(payload["documents"]) == 2
    assert len(payload["collections"]) == 2
    assert payload["collections"][1]["document_ids"] == ["voice_2", "voice_2_attachment_1"]
    assert payload["documents"][0]["metadata"]["attachment_document_ids"] == ["voice_2_attachment_1"]
    assert payload["documents"][1]["metadata"]["parent_document_id"] == "voice_2"
    assert payload["documents"][1]["metadata"]["collection_id"] == "google_voice_bundle_voice_2"
    assert payload["documents"][1]["metadata"]["attachment_kind"] == "document"
    assert "Inspection notes from the attached text file" in payload["documents"][1]["text"]
    assert payload["bm25_index"]["document_count"] == 2


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


def test_workspace_dataset_builder_uses_parsed_email_payload_when_body_missing(tmp_path):
    parsed_path = tmp_path / "parsed_email.json"
    parsed_path.write_text(
        json.dumps(
            {
                "subject": "Parsed subject",
                "body_text": "Parsed body text for the email import manifest.",
                "date": "2026-03-25T07:00:00Z",
                "message_id": "<parsed-message@example.com>",
            }
        ),
        encoding="utf-8",
    )
    email_export = {
        "status": "success",
        "protocol": "imap",
        "server": "mail.example.com",
        "folder": "INBOX",
        "emails": [
            {
                "message_id_header": "<manifest-message@example.com>",
                "subject": "Manifest subject",
                "from": "tenant@example.com",
                "to": "advocate@example.com",
                "date": "2026-03-24T06:00:00Z",
                "parsed_path": str(parsed_path),
                "attachments": [],
            }
        ],
    }

    dataset = WorkspaceDatasetBuilder().build_from_email_export(email_export)
    payload = dataset.to_dict()

    assert payload["documents"][0]["title"] == "Manifest subject"
    assert "Parsed body text" in payload["documents"][0]["text"]
    assert payload["bm25_index"]["document_count"] == 1


def test_workspace_dataset_builder_accepts_imap_snippet_summary(tmp_path):
    body_path = tmp_path / "body.txt"
    headers_path = tmp_path / "headers.txt"
    body_path.write_text("IMAP snippet body text.", encoding="utf-8")
    headers_path.write_text("From: tenant@example.com\nSubject: Snippet\n", encoding="utf-8")

    summary_payload = [
        {"seq": 1, "body_path": str(body_path), "headers_path": str(headers_path)},
        {"seq": 2, "body_path": str(body_path), "headers_path": str(headers_path)},
    ]

    dataset = WorkspaceDatasetBuilder().build_from_imap_snippet_summary(summary_payload)
    payload = dataset.to_dict()

    assert payload["source_type"] == "imap_snippets"
    assert len(payload["documents"]) == 2
    assert "IMAP snippet body text" in payload["documents"][0]["text"]


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
    dataset.metadata["formal_logic"] = {
        "zkp_proof_certificates": [
            {
                "certificate_id": "single-zkp-1",
                "backend": "groth16",
                "format": "groth16_zksnark",
                "payload": {"proof_system": "groth16"},
            }
        ]
    }

    export_result = export_workspace_dataset_single_parquet(dataset, tmp_path / "workspace_bundle.parquet")
    rows = pq.read_table(tmp_path / "workspace_bundle.parquet").to_pylist()
    loaded = load_workspace_dataset_single_parquet(tmp_path / "workspace_bundle.parquet")

    assert export_result["row_count"] == len(rows)
    assert any(row["section"] == "documents" for row in rows)
    assert any(row["section"] == "bm25_documents" for row in rows)
    assert any(row["section"] == "vector_items" for row in rows)
    assert any(row["section"] == "knowledge_graph_entities" for row in rows)
    assert any(row["section"] == "zkp_proof_certificates" for row in rows)
    assert loaded["zkp_proof_certificates"][0]["certificate_id"] == "single-zkp-1"


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
