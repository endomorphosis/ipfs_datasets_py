import json
from pathlib import Path
import zipfile

import pytest
from ipfs_datasets_py.processors.legal_data import docket_dataset as docket_dataset_module
from ipfs_datasets_py.processors.legal_data import docket_packaging as docket_packaging_module

from ipfs_datasets_py.processors.legal_data import (
    DocketDatasetBuilder,
    DocketDatasetPackager,
    DocketDatasetObject,
    PackagedDocketQueryAdapter,
    attach_packaged_docket_proof_assistant_packet,
    build_docket_deontic_artifacts,
    build_packaged_docket_proof_assistant_packet,
    build_packaged_docket_proof_evidence_bundle,
    execute_packaged_docket_next_action,
    execute_packaged_docket_query,
    execute_packaged_docket_follow_up_job,
    execute_packaged_docket_follow_up_plan,
    iter_packaged_docket_chain,
    load_packaged_docket_dataset,
    load_packaged_docket_dataset_components,
    package_docket_dataset,
    plan_packaged_docket_query,
    prepare_packaged_docket_follow_up_job,
    search_packaged_docket_dataset_bm25,
    search_packaged_docket_dataset_vector,
    search_packaged_docket_logic_artifacts,
    search_packaged_docket_proof_tasks,
    search_docket_dataset_bm25,
    search_docket_dataset_vector,
    summarize_docket_dataset,
)


@pytest.fixture(autouse=True)
def disable_embeddings_router(monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_PY_DISABLE_EMBEDDINGS_ROUTER", "1")
    monkeypatch.setattr(
        docket_dataset_module,
        "enrich_docket_documents_with_routers",
        lambda *args, **kwargs: {
            "document_analyses": {},
            "knowledge_graph": {"entities": [], "relationships": []},
            "temporal_fol": {"backend": "disabled_for_tests", "formulas": []},
            "deontic_cognitive_event_calculus": {"backend": "disabled_for_tests", "formulas": []},
            "frame_logic": {},
            "proof_store": {
                "proofs": {},
                "summary": {
                    "proof_count": 0,
                    "processed_document_count": 0,
                    "skipped_document_count": 0,
                    "mock_provider_count": 0,
                },
                "metadata": {"backend": "disabled_for_tests", "zkp_status": "not_implemented"},
            },
            "summary": {
                "processed_document_count": 0,
                "skipped_document_count": 0,
                "mock_provider_count": 0,
                "entity_count": 0,
                "relationship_count": 0,
                "temporal_formula_count": 0,
                "dcec_formula_count": 0,
                "frame_count": 0,
                "proof_count": 0,
            },
        },
    )


def test_docket_dataset_builder_creates_dataset_with_kg_bm25_and_vector_index():
    docket = {
        "docket_id": "1:24-cv-1001",
        "case_name": "Doe v. Acme",
        "court": "D. Example",
        "plaintiff_docket": [
            {
                "id": "pl_1",
                "title": "Motion to Compel",
                "text": "Plaintiff moves to compel discovery responses before the deadline.",
            }
        ],
        "defendant_docket": [
            {
                "id": "df_1",
                "title": "Answer",
                "text": "Defendant must answer the complaint within 21 days.",
            }
        ],
        "authorities": [
            {
                "id": "auth_1",
                "title": "Scheduling Order",
                "text": "The parties shall exchange initial disclosures.",
            }
        ],
        "documents": [
            {
                "id": "doc_1",
                "title": "Complaint",
                "text": (
                    "IN THE UNITED STATES DISTRICT COURT\n\n"
                    "Civil Action No. ________________\n\n"
                    "DOE v. ACME\n\n"
                    "COMPLAINT FOR BREACH OF CONTRACT\n\n"
                    "FACTUAL ALLEGATIONS\n"
                    "1. Defendant breached the contract.\n"
                ),
                "date_filed": "2024-05-01",
                "document_number": "1",
            },
            {
                "id": "doc_2",
                "title": "Motion to Dismiss",
                "text": "Defendant moves to dismiss the complaint for failure to state a claim.",
                "date_filed": "2024-06-01",
                "document_number": "12",
            },
        ],
    }

    dataset = DocketDatasetBuilder().build_from_docket(docket)
    payload = dataset.to_dict()

    assert payload["metadata"]["document_count"] == 2
    assert payload["knowledge_graph"]["entities"]
    assert payload["deontic_graph"]["rules"]
    assert payload["deontic_triggers"]["summary"]["pending_analysis_count"] >= 1
    assert payload["proof_assistant"]["summary"]["work_item_count"] >= 3
    assert payload["proof_assistant"]["extractors"]["deontic_temporal_first_order_logic"]["status"] == "ready"
    assert payload["proof_assistant"]["extractors"]["knowledge_graph"]["entity_count"] >= 1
    assert payload["proof_assistant"]["extractors"]["deontic_cognitive_event_calculus"]["formula_count"] >= 1
    assert payload["proof_assistant"]["extractors"]["frame_logic"]["frame_count"] >= 1
    assert payload["proof_assistant"]["temporal_fol"]["formulas"]
    assert payload["proof_assistant"]["deontic_temporal_first_order_logic"]["formulas"]
    assert payload["proof_assistant"]["deontic_cognitive_event_calculus"]["formulas"]
    assert payload["proof_assistant"]["frames"]
    assert payload["proof_assistant"]["frame_logic"]
    assert payload["proof_assistant"]["knowledge_graph"]["entities"]
    assert payload["proof_assistant"]["extractors"]["proof_tactician"]["status"] == "ready"
    assert payload["proof_assistant"]["tactician"]["summary"]["local_first"] is True
    assert payload["proof_assistant"]["tactician"]["plans"]
    assert payload["metadata"]["artifact_provenance"]["knowledge_graph"]["is_mock"] is False
    assert payload["metadata"]["artifact_provenance"]["bm25_index"]["backend"] == "local_bm25"
    assert payload["metadata"]["artifact_provenance"]["vector_index"]["backend"] in {
        "local_hashed_term_projection",
        "embeddings_router",
    }
    assert payload["bm25_index"]["backend"] == "local_bm25"
    assert payload["vector_index"]["backend"] in {
        "local_hashed_term_projection",
        "embeddings_router",
    }
    first_plan = payload["proof_assistant"]["tactician"]["plans"][0]
    assert first_plan["recommended_route"][0] == "local_docket_documents"
    assert first_plan["selected_starting_source_type"] in {
        "local_docket_documents",
        "authority_list",
        "local_bm25_index",
        "local_vector_index",
    }
    assert [stage["stage"] for stage in first_plan["search_stages"]][:2] == ["local", "parser"]
    assert payload["proof_assistant"]["tactician"]["summary"]["starting_source_types"]
    assert payload["bm25_index"]["document_count"] == 2
    assert payload["vector_index"]["document_count"] == 2


def test_docket_dataset_search_helpers_return_ranked_results():
    docket = {
        "docket_id": "1:24-cv-1001",
        "case_name": "Doe v. Acme",
        "documents": [
            {"id": "doc_1", "title": "Complaint", "text": "Breach of contract allegations and damages."},
            {"id": "doc_2", "title": "Answer", "text": "Defendant denies liability."},
        ],
    }
    dataset = DocketDatasetBuilder().build_from_docket(docket)

    bm25_results = search_docket_dataset_bm25(dataset, "breach contract", top_k=2)
    vector_results = search_docket_dataset_vector(dataset, "breach contract", top_k=2)

    assert bm25_results["result_count"] >= 1
    assert bm25_results["results"][0]["id"] == "doc_1"
    assert bm25_results["results"][0]["title"] == "Complaint"
    assert bm25_results["source"] == "local_bm25"
    assert vector_results["result_count"] >= 1
    assert vector_results["results"][0]["backend"] == "local_hashed_term_projection"


def test_docket_dataset_preserves_document_metadata_and_adds_classification():
    docket = {
        "docket_id": "1:24-cv-1003",
        "case_name": "Doe v. Acme",
        "documents": [
            {
                "id": "doc_1",
                "title": "Declaration of Jane Doe",
                "text": "I declare under penalty of perjury.",
                "metadata": {"text_extraction": {"source": "pdf_ocr"}},
                "document_type": "declaration",
            },
        ],
    }

    dataset = DocketDatasetBuilder().build_from_docket(docket)
    document = dataset.to_dict()["documents"][0]

    assert document["metadata"]["text_extraction"]["source"] == "pdf_ocr"
    assert document["metadata"]["classification"]["label"] == "declaration"
    assert document["metadata"]["classification"]["backend"] == "heuristic_legal_document_classifier"


def test_docket_dataset_builds_formal_logic_artifacts():
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-1005",
            "case_name": "Doe v. Formal Logic",
            "documents": [
                {
                    "id": "doc_1",
                    "title": "Tenant Duties Notice",
                    "text": (
                        "Tenant must pay rent on the first of the month. "
                        "Tenant must not pay rent in cash. "
                        "Tenant may request a receipt."
                    ),
                }
            ],
        }
    )
    payload = dataset.to_dict()
    document = payload["documents"][0]

    assert payload["metadata"]["artifact_status"]["formal_logic"] is True
    assert payload["metadata"]["artifact_provenance"]["formal_logic"]["processed_document_count"] >= 1
    assert document["metadata"]["rich_analysis"]["provenance"]["backend"] == "formal_logic_pipeline"
    assert document["metadata"]["rich_analysis"]["deontic_statements"]
    assert payload["proof_assistant"]["temporal_fol"]["formulas"]
    assert payload["proof_assistant"]["deontic_cognitive_event_calculus"]["formulas"] or payload["documents"][0]["metadata"]["rich_analysis"]["dcec_formulas"] == []


def test_docket_dataset_extracts_structured_order_language():
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-2005",
            "case_name": "Doe v. Structured Order",
            "documents": [
                {
                    "id": "doc_order_1",
                    "title": (
                        "TEXT ORDER entered by Magistrate Judge Example. Plaintiff is directed to return the original "
                        "proposed summons to the Clerk as unexecuted. The parties are ordered to submit a proposed "
                        "discovery schedule by 3/11/26. The Rule 16 Scheduling Conference set for 3/17/26 is CONTINUED."
                    ),
                    "text": (
                        "Plaintiff is directed to return the original proposed summons to the Clerk as unexecuted. "
                        "The parties are ordered to submit a proposed discovery schedule by 3/11/26. "
                        "The Rule 16 Scheduling Conference set for 3/17/26 is CONTINUED."
                    ),
                }
            ],
        }
    )

    payload = dataset.to_dict()
    document = payload["documents"][0]
    formal_summary = payload["metadata"]["artifact_provenance"]["formal_logic"]
    analysis = document["metadata"]["rich_analysis"]

    assert formal_summary["deontic_statement_count"] >= 2
    assert formal_summary["temporal_formula_count"] >= 1
    assert formal_summary["frame_count"] >= 2
    assert formal_summary["proof_count"] >= 2
    assert payload["proof_assistant"]["summary"]["substantive_proof_knowledge_graph_entity_count"] >= 1
    assert payload["proof_assistant"]["summary"]["substantive_proof_knowledge_graph_relationship_count"] >= 1
    assert analysis["deontic_statements"]
    assert analysis["frames"]
    assert "doc_order_1:actor:parties" in payload["proof_assistant"]["metadata"]["substantive_views"]["knowledge_graph_entity_ids"]
    assert any("shall" in formula or " O(" in formula or "O_t(" in formula for formula in payload["proof_assistant"]["temporal_fol"]["formulas"])


def test_docket_dataset_normalizes_temporal_prefix_out_of_actor():
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-2006",
            "case_name": "Doe v. Temporal Prefix",
            "documents": [
                {
                    "id": "doc_order_2",
                    "title": "Order",
                    "text": "Within 14 days, Plaintiff is directed to serve the Secretary of the Illinois Department of Human Services.",
                }
            ],
        }
    )

    payload = dataset.to_dict()
    analysis = payload["documents"][0]["metadata"]["rich_analysis"]
    statements = list(analysis["deontic_statements"] or [])
    substantive_entities = list(payload["proof_assistant"]["metadata"]["substantive_views"]["knowledge_graph_entity_ids"] or [])

    assert statements
    assert statements[0]["entity"].lower() == "plaintiff"
    assert "doc_order_2:actor:plaintiff" in substantive_entities


def test_docket_dataset_creates_canonical_deadline_entities():
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-2007",
            "case_name": "Doe v. Deadline Canon",
            "documents": [
                {
                    "id": "doc_deadline_1",
                    "title": "Order",
                    "text": "Defendant shall file an answer by 4/7/2026.",
                },
                {
                    "id": "doc_deadline_2",
                    "title": "Notice",
                    "text": "Answer due 4/7/2026.",
                },
            ],
        }
    )

    proof = dataset.to_dict()["proof_assistant"]
    substantive_entities = list(proof["metadata"]["substantive_views"]["knowledge_graph_entity_ids"] or [])
    substantive_relationships = list(proof["metadata"]["substantive_views"]["knowledge_graph_relationship_ids"] or [])
    deadline_ids = [item for item in substantive_entities if item.startswith("deadline:")]

    assert "deadline:defendant:file_an_answer:2026_04_07" in deadline_ids
    assert len([item for item in deadline_ids if item == "deadline:defendant:file_an_answer:2026_04_07"]) == 1
    assert any("2026_04_07" in item and ":rel:deadline_for:" in item for item in substantive_relationships)
    assert any("2026_04_07" in item and ":rel:imposes_deadline:" in item for item in substantive_relationships)


def test_docket_dataset_splits_compound_deadline_clause():
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-2008",
            "case_name": "Doe v. Compound Deadline",
            "documents": [
                {
                    "id": "doc_deadline_3",
                    "title": "Scheduling Order",
                    "text": (
                        "The following deadlines are set: initial disclosures due 7/3/26, "
                        "amended pleadings and joinder of parties due 8/15/26, "
                        "discovery closes 10/20/26, case dispositive motions due 1/8/27."
                    ),
                }
            ],
        }
    )

    proof = dataset.to_dict()["proof_assistant"]
    deadline_ids = [item for item in (proof["metadata"]["substantive_views"]["knowledge_graph_entity_ids"] or []) if item.startswith("deadline:")]

    assert "deadline:parties:exchange_initial_disclosures:2026_07_03" in deadline_ids
    assert any(item.startswith("deadline:parties:file_amended_pleadings_and_join") and item.endswith(":2026_08_15") for item in deadline_ids)
    assert "deadline:parties:complete_discovery:2026_10_20" in deadline_ids
    assert "deadline:parties:file_dispositive_motions:2027_01_08" in deadline_ids


def test_docket_dataset_creates_canonical_norm_entities():
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-2009",
            "case_name": "Doe v. Norm Canon",
            "documents": [
                {
                    "id": "doc_norm_1",
                    "title": "Order",
                    "text": "Defendant shall file an answer by 4/7/2026.",
                },
                {
                    "id": "doc_norm_2",
                    "title": "Notice",
                    "text": "Answer due 4/7/2026.",
                },
            ],
        }
    )

    proof = dataset.to_dict()["proof_assistant"]
    substantive_entities = list(proof["metadata"]["substantive_views"]["knowledge_graph_entity_ids"] or [])
    substantive_relationships = list(proof["metadata"]["substantive_views"]["knowledge_graph_relationship_ids"] or [])
    norm_ids = [item for item in substantive_entities if item.startswith("norm:")]

    assert "norm:defendant:obligation:file_an_answer" in norm_ids
    assert len([item for item in norm_ids if item == "norm:defendant:obligation:file_an_answer"]) == 1
    assert any(":rel:imposes_norm:" in item and "file_an_answer" in item for item in substantive_relationships)
    assert any(":rel:norm_subject:" in item and "file_an_answer" in item for item in substantive_relationships)
    assert any(":rel:norm_deadline:" in item and "2026_04_07" in item for item in substantive_relationships)


def test_docket_dataset_stamps_synthesized_courtlistener_provenance():
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "cl-1",
            "case_name": "CourtListener Example",
            "documents": [
                {
                    "id": "summary",
                    "title": "CourtListener docket summary",
                    "text": "Summary text",
                    "document_type": "courtlistener_docket_summary",
                },
                {
                    "id": "entry_1",
                    "title": "Docket Entry 1",
                    "text": "Entry text",
                    "document_type": "courtlistener_docket_entry",
                },
            ],
        }
    )
    payload = dataset.to_dict()

    assert payload["documents"][0]["metadata"]["text_extraction"]["source"] == "synthesized_docket_summary"
    assert payload["documents"][1]["metadata"]["text_extraction"]["source"] == "synthesized_docket_entry"


def test_docket_dataset_merges_router_enrichment(monkeypatch):
    def _fake_enrichment(documents, **kwargs):  # noqa: ANN001
        doc_id = documents[0].document_id
        return {
            "document_analyses": {
                doc_id: {
                    "classification": {"label": "motion", "backend": "llm_router"},
                    "entities": [{"id": f"{doc_id}:entity:1", "label": "Jane Doe", "type": "person"}],
                    "relationships": [{"id": f"{doc_id}:rel:1", "source": f"{doc_id}:entity:1", "target": f"{doc_id}:entity:1", "type": "MENTIONED_WITH"}],
                    "deontic_statements": [],
                    "events": [],
                    "frames": [{"frame_id": f"{doc_id}:frame:1", "label": "MotionFrame", "slots": {"party": "plaintiff"}}],
                    "propositions": [{"statement": "Plaintiff filed a motion.", "assumptions": ["The filing text says motion."]}],
                    "temporal_formulas": ["Filed(doc_1, t1)."],
                    "dcec_formulas": ["Happens(DocumentFiled(doc_1), t1)."],
                    "summary": "Router summary",
                    "provenance": {"backend": "llm_router", "provider": "openai", "model_name": "gpt"},
                }
            },
            "knowledge_graph": {
                "entities": [{"id": f"{doc_id}:entity:1", "label": "Jane Doe", "type": "person"}],
                "relationships": [{"id": f"{doc_id}:rel:1", "source": f"{doc_id}:entity:1", "target": f"{doc_id}:entity:1", "type": "MENTIONED_WITH"}],
            },
            "temporal_fol": {"formulas": ["Filed(doc_1, t1)."]},
            "deontic_cognitive_event_calculus": {"formulas": ["Happens(DocumentFiled(doc_1), t1)."]},
            "frame_logic": {f"{doc_id}:frame:1": {"frame_id": f"{doc_id}:frame:1", "label": "MotionFrame", "slots": {"party": "plaintiff"}}},
            "proof_store": {
                "proofs": {"proof_1": {"proof_id": "proof_1"}},
                "certificates": [{"certificate_id": "cert_1"}],
                "summary": {"proof_count": 1},
                "metadata": {"backend": "router_enriched_proof_store", "zkp_status": "not_implemented"},
            },
            "summary": {
                "processed_document_count": 1,
                "mock_provider_count": 0,
                "proof_count": 1,
            },
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.docket_dataset.enrich_docket_documents_with_routers",
        _fake_enrichment,
    )

    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-1004",
            "case_name": "Doe v. Acme",
            "documents": [
                {"id": "doc_1", "title": "Motion to Compel", "text": "Plaintiff files motion to compel."},
            ],
        }
    )
    payload = dataset.to_dict()

    assert payload["documents"][0]["metadata"]["rich_analysis"]["summary"] == "Router summary"
    assert payload["proof_assistant"]["proof_store"]["summary"]["proof_count"] == 1
    assert "Filed(doc_1, t1)." in payload["proof_assistant"]["temporal_fol"]["formulas"]
    assert payload["metadata"]["artifact_status"]["router_enrichment"] is True
    assert payload["proof_assistant"]["metadata"]["substantive_views"]["temporal_formulas"] == ["Filed(doc_1, t1)."]
    assert payload["proof_assistant"]["summary"]["substantive_temporal_formula_count"] == 1
    assert payload["proof_assistant"]["summary"]["substantive_frame_count"] == 1
    assert payload["proof_assistant"]["summary"]["substantive_dcec_formula_count"] == 0
    assert "Happens(DocumentFiled(doc_1), t1)." in payload["proof_assistant"]["metadata"]["generic_views"]["dcec_formulas"]
    assert payload["proof_assistant"]["summary"]["substantive_proof_knowledge_graph_entity_count"] == 0
    assert payload["proof_assistant"]["summary"]["substantive_proof_knowledge_graph_relationship_count"] == 0


def test_docket_dataset_prefers_normative_dcec_in_substantive_view(monkeypatch):
    def _fake_enrichment(documents, **kwargs):  # noqa: ANN001
        doc_id = documents[0].document_id
        return {
            "document_analyses": {doc_id: {"classification": {"label": "order", "backend": "llm_router"}}},
            "knowledge_graph": {"entities": [], "relationships": []},
            "temporal_fol": {"formulas": ["forall t (true and By(t,2026-03-20) and not(false) -> O(frm:1,t))"]},
            "deontic_cognitive_event_calculus": {
                "formulas": [
                    "forall t (true and By(t,2026-03-20) and not(false) -> O(frm:1))",
                    "Happens(DocumentFiled(doc_1), t1).",
                    "raw_title_text(agent:Agent)",
                ]
            },
            "frame_logic": {"frm:1": {"frame_id": "frm:1", "label": "NormFrame", "slots": {"party": "plaintiff"}}},
            "proof_store": {"proofs": {}, "summary": {"proof_count": 0}, "metadata": {"backend": "router"}},
            "summary": {"processed_document_count": 1, "proof_count": 0},
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.docket_dataset.enrich_docket_documents_with_routers",
        _fake_enrichment,
    )

    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-4004",
            "case_name": "Doe v. Normative DCEC",
            "documents": [{"id": "doc_1", "title": "Order", "text": "Plaintiff shall serve defendant by 2026-03-20."}],
        }
    )
    proof = dataset.to_dict()["proof_assistant"]

    assert proof["summary"]["substantive_dcec_formula_count"] >= 1
    assert "forall t (true and By(t,2026-03-20) and not(false) -> O(frm:1))" in proof["metadata"]["substantive_views"]["dcec_formulas"]
    assert "Happens(DocumentFiled(doc_1), t1)." in proof["metadata"]["generic_views"]["dcec_formulas"]
    assert "raw_title_text(agent:Agent)" in proof["metadata"]["generic_views"]["dcec_formulas"]


def test_docket_dataset_tracks_substantive_knowledge_graph_views(monkeypatch):
    def _fake_enrichment(documents, **kwargs):  # noqa: ANN001
        doc_id = documents[0].document_id
        return {
            "document_analyses": {doc_id: {"classification": {"label": "order", "backend": "router"}}},
            "knowledge_graph": {
                "entities": [
                    {"id": f"{doc_id}:actor:plaintiff", "label": "Plaintiff", "type": "legal_actor"},
                    {"id": "event:conference:undated", "label": "Scheduling Conference", "type": "court_event"},
                    {"id": f"{doc_id}:entity:generic", "label": "Generic", "type": "person"},
                ],
                "relationships": [
                    {"id": f"{doc_id}:rel:1", "source": f"{doc_id}:actor:plaintiff", "target": doc_id, "type": "SUBJECT_OF"},
                    {"id": f"{doc_id}:rel:2", "source": doc_id, "target": f"{doc_id}:entity:generic", "type": "MENTIONED_WITH"},
                ],
            },
            "temporal_fol": {"formulas": []},
            "deontic_cognitive_event_calculus": {"formulas": []},
            "frame_logic": {},
            "proof_store": {"proofs": {}, "summary": {"proof_count": 0}, "metadata": {"backend": "router"}},
            "summary": {"processed_document_count": 1, "proof_count": 0},
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.docket_dataset.enrich_docket_documents_with_routers",
        _fake_enrichment,
    )

    proof = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-5005",
            "case_name": "Doe v. KG Split",
            "documents": [{"id": "doc_1", "title": "Order", "text": "Plaintiff is directed to appear."}],
        }
    ).to_dict()["proof_assistant"]

    assert proof["summary"]["substantive_proof_knowledge_graph_entity_count"] >= 2
    assert proof["summary"]["substantive_proof_knowledge_graph_relationship_count"] >= 1
    assert "doc_1:actor:plaintiff" in proof["metadata"]["substantive_views"]["knowledge_graph_entity_ids"]
    assert "event:conference:undated" in proof["metadata"]["substantive_views"]["knowledge_graph_entity_ids"]
    assert "doc_1:rel:1" in proof["metadata"]["substantive_views"]["knowledge_graph_relationship_ids"]
    assert "doc_1:entity:generic" in proof["metadata"]["generic_views"]["knowledge_graph_entity_ids"]
    assert "doc_1:rel:2" in proof["metadata"]["generic_views"]["knowledge_graph_relationship_ids"]


def test_docket_dataset_round_trips_via_json_file(tmp_path):
    docket = {
        "docket_id": "1:24-cv-1002",
        "case_name": "Doe v. Widget",
        "court": "D. Example",
        "documents": [
            {"id": "doc_1", "title": "Complaint", "text": "Breach of contract and damages."},
        ],
    }
    builder = DocketDatasetBuilder()
    dataset = builder.build_from_docket(docket)
    output_path = dataset.write_json(tmp_path / "docket_dataset.json")

    restored = DocketDatasetObject.from_json(output_path)
    summary = summarize_docket_dataset(restored)

    assert restored.dataset_id == dataset.dataset_id
    assert restored.documents[0].title == "Complaint"
    assert summary["documents_with_text"] == 1
    assert summary["bm25_document_count"] == 1


def test_docket_dataset_builder_supports_json_file_and_directory_import(tmp_path):
    docket_json = tmp_path / "docket.json"
    docket_json.write_text(
        """
        {
          "docket_id": "2:24-cv-2001",
          "case_name": "Smith v. Example Corp.",
          "court": "D. Example",
          "documents": [
            {"id": "doc_json_1", "title": "Notice", "text": "Initial notice of filing.", "date_filed": "2024-01-10"}
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    directory = tmp_path / "docket_dir"
    directory.mkdir()
    (directory / "001_complaint.txt").write_text("Complaint text with allegations and timeline.", encoding="utf-8")
    (directory / "002_motion.md").write_text("## Motion\nMotion to dismiss for lack of jurisdiction.", encoding="utf-8")
    (directory / "003_notice.json").write_text(
        '{"id":"doc3","title":"Notice of Hearing","text":"Hearing set for May 1, 2024.","date_filed":"2024-04-15"}',
        encoding="utf-8",
    )

    builder = DocketDatasetBuilder()
    json_dataset = builder.build_from_json_file(docket_json)
    dir_dataset = builder.build_from_directory(directory, docket_id="dir-1", case_name="Directory Docket")

    assert json_dataset.docket_id == "2:24-cv-2001"
    assert json_dataset.metadata["source_type"] == "json_file"
    assert dir_dataset.docket_id == "dir-1"
    assert dir_dataset.metadata["document_count"] == 3
    assert dir_dataset.bm25_index["document_count"] == 3


def test_docket_dataset_can_be_packaged_as_linked_parquet_and_car_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_SAFE_ROOT", str(tmp_path))
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-2222",
            "case_name": "Doe v. Chained Records",
            "court": "D. Example",
            "plaintiff_docket": [{"id": "pl_1", "title": "Motion", "text": "Plaintiff must produce records."}],
            "authorities": [{"id": "auth_1", "title": "Rule 34", "text": "Parties shall produce documents."}],
            "documents": [
                {"id": "doc_1", "title": "Complaint", "text": "Complaint text.", "date_filed": "2024-01-01"},
                {"id": "doc_2", "title": "Exhibit A", "text": "Attached exhibit text.", "date_filed": "2024-01-02"},
            ],
        }
    )

    package_info = dataset.write_package(tmp_path / "bundle", include_car=True)
    restored = DocketDatasetObject.from_package(package_info["manifest_json_path"])
    package_manifest = load_packaged_docket_dataset(package_info["manifest_json_path"])["package_manifest"]
    packaged_again = package_docket_dataset(dataset.to_dict(), tmp_path / "bundle_copy", include_car=True)
    explicit_packager = DocketDatasetPackager().load_package(packaged_again["manifest_json_path"])

    assert (tmp_path / "bundle" / "manifest.parquet").exists()
    assert (tmp_path / "bundle" / "manifest.car").exists()
    assert (tmp_path / "bundle" / "documents.parquet").exists()
    assert (tmp_path / "bundle" / "documents.car").exists()
    assert package_manifest["root_cid"]
    assert package_manifest["tail_cid"]
    assert package_manifest["components"][0]["cid"]
    assert package_manifest["components"][0]["next_cid"]
    assert restored.dataset_id == dataset.dataset_id
    assert restored.documents[0].title == "Complaint"
    assert restored.bm25_index["document_count"] == dataset.bm25_index["document_count"]
    assert restored.vector_index["document_count"] == dataset.vector_index["document_count"]
    assert restored.proof_assistant["summary"]["work_item_count"] >= 1
    assert explicit_packager["package_manifest"]["component_count"] >= 10


def test_packaged_docket_dataset_supports_component_and_chain_loading(tmp_path, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_SAFE_ROOT", str(tmp_path))
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-3333",
            "case_name": "Doe v. Incremental Loader",
            "court": "D. Example",
            "plaintiff_docket": [{"id": "pl_1", "title": "Notice", "text": "Plaintiff must provide notice."}],
            "documents": [
                {"id": "doc_1", "title": "Complaint", "text": "Complaint text.", "date_filed": "2024-03-01"},
                {"id": "doc_2", "title": "Order", "text": "Court order text.", "date_filed": "2024-03-02"},
            ],
        }
    )
    package_info = dataset.write_package(tmp_path / "incremental_bundle", include_car=True)
    manifest_path = package_info["manifest_json_path"]

    components = load_packaged_docket_dataset_components(
        manifest_path,
        piece_ids=["dataset_core", "documents", "bm25_documents"],
    )
    chain = iter_packaged_docket_chain(manifest_path)
    minimal_view = DocketDatasetPackager().load_minimal_dataset_view(manifest_path)
    documents_only = DocketDatasetObject.from_packaged_components(
        manifest_path,
        piece_ids=["documents", "vector_items"],
    )

    assert sorted(components.keys()) == ["bm25_documents", "dataset_core", "documents"]
    assert len(components["documents"]) == 2
    assert chain[0]["piece_id"] == "dataset_core"
    assert chain[1]["piece_id"] == "documents"
    assert minimal_view["dataset_id"] == dataset.dataset_id
    assert len(minimal_view["documents"]) == 2
    assert documents_only["documents"][0]["title"] == "Complaint"
    assert len(documents_only["vector_items"]) == dataset.vector_index["document_count"]


def test_packaged_docket_dataset_supports_lazy_search_without_full_rebuild(tmp_path, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_SAFE_ROOT", str(tmp_path))
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-4444",
            "case_name": "Doe v. Lazy Search",
            "court": "D. Example",
            "plaintiff_docket": [{"id": "pl_1", "title": "Discovery Motion", "text": "Plaintiff must answer discovery."}],
            "documents": [
                {"id": "doc_1", "title": "Complaint", "text": "Breach of contract allegations and damages."},
                {"id": "doc_2", "title": "Answer", "text": "Defendant denies liability and raises defenses."},
            ],
        }
    )
    package_info = dataset.write_package(tmp_path / "lazy_bundle", include_car=True)
    manifest_path = package_info["manifest_json_path"]

    bm25_results = search_packaged_docket_dataset_bm25(manifest_path, "breach contract", top_k=2)
    vector_results = search_packaged_docket_dataset_vector(manifest_path, "breach contract", top_k=2)
    proof_results = search_packaged_docket_proof_tasks(manifest_path, "discovery answer", top_k=5)

    assert bm25_results["result_count"] >= 1
    assert bm25_results["results"][0]["id"] == "doc_1"
    assert bm25_results["results"][0]["title"] == "Complaint"
    assert bm25_results["source"] == "packaged_local_bm25"
    assert vector_results["result_count"] >= 1
    assert vector_results["results"][0]["backend"] == "local_hashed_term_projection"
    assert proof_results["result_count"] >= 1
    assert "Discovery Motion" in {result["title"] for result in proof_results["results"]}


def test_packaged_docket_query_planner_selects_relevant_pieces_and_executes(tmp_path, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_SAFE_ROOT", str(tmp_path))
    observed_parser_calls = []

    async def fake_search_state_law_corpus_from_parameters(parameters, *, tool_version="1.0.0"):
        observed_parser_calls.append((dict(parameters), tool_version))
        return {
            "status": "success",
            "query": parameters.get("query_text"),
            "results": [
                {
                    "id": "state_law_hit_1",
                    "title": "State prohibition rule",
                    "text": "A party may not violate the scheduling prohibition.",
                    "source_type": "state_law_corpus",
                }
            ],
            "count": 1,
        }

    class _FakeLegalDatasetApiModule:
        search_state_law_corpus_from_parameters = staticmethod(fake_search_state_law_corpus_from_parameters)

    real_import_module = docket_packaging_module.importlib.import_module

    def fake_import_module(name):
        if name == "ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api":
            return _FakeLegalDatasetApiModule()
        return real_import_module(name)

    monkeypatch.setattr(docket_packaging_module.importlib, "import_module", fake_import_module)
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-5555",
            "case_name": "Doe v. Planned Search",
            "court": "D. Example",
            "plaintiff_docket": [{"id": "pl_1", "title": "Discovery Motion", "text": "Plaintiff must answer discovery."}],
            "authorities": [{"id": "auth_1", "title": "Scheduling Order", "text": "The parties shall exchange disclosures."}],
            "documents": [
                {"id": "doc_1", "title": "Complaint", "text": "Breach of contract allegations and damages."},
                {"id": "doc_2", "title": "Order", "text": "Court order concerning disclosures and deadlines."},
            ],
        }
    )
    package_info = dataset.write_package(tmp_path / "planned_bundle", include_car=True)
    manifest_path = package_info["manifest_json_path"]

    lexical_plan = plan_packaged_docket_query(manifest_path, "find complaint damages")
    proof_plan = plan_packaged_docket_query(manifest_path, "what obligations and proof tasks exist")
    kg_plan = plan_packaged_docket_query(manifest_path, "show me the knowledge graph entities")

    lexical_result = execute_packaged_docket_query(manifest_path, "find complaint damages", top_k=2)
    proof_result = execute_packaged_docket_query(manifest_path, "what obligations and proof tasks exist", top_k=5)
    kg_result = execute_packaged_docket_query(manifest_path, "show me the knowledge graph entities", top_k=2)
    proof_gap_result = execute_packaged_docket_query(manifest_path, "proof prohibition sanctions", top_k=5)
    proof_job = prepare_packaged_docket_follow_up_job(
        manifest_path,
        "proof prohibition sanctions",
        top_k=5,
        step_index=1,
    )
    parser_job = prepare_packaged_docket_follow_up_job(
        manifest_path,
        "proof prohibition sanctions",
        top_k=5,
        step_index=2,
    )
    proof_noop_job = prepare_packaged_docket_follow_up_job(
        manifest_path,
        "what obligations and proof tasks exist",
        top_k=5,
    )
    proof_job_execution = execute_packaged_docket_follow_up_job(manifest_path, proof_job, top_k=5)
    parser_job_execution = execute_packaged_docket_follow_up_job(manifest_path, parser_job, top_k=5)
    proof_gap_next_action_execution = execute_packaged_docket_next_action(
        manifest_path,
        query_result=proof_gap_result,
        top_k=5,
    )
    proof_gap_chained_next_action_execution = execute_packaged_docket_next_action(
        manifest_path,
        query_result=proof_gap_result,
        top_k=5,
        chain_until_satisfied=True,
    )
    chained_follow_up_execution = execute_packaged_docket_follow_up_plan(
        manifest_path,
        "proof prohibition sanctions",
        top_k=5,
    )
    proof_evidence_bundle = build_packaged_docket_proof_evidence_bundle(
        manifest_path,
        "proof prohibition sanctions",
        follow_up_execution=chained_follow_up_execution,
    )
    proof_assistant_packet = build_packaged_docket_proof_assistant_packet(
        manifest_path,
        "proof prohibition sanctions",
        follow_up_execution=chained_follow_up_execution,
    )
    attached_package_view = attach_packaged_docket_proof_assistant_packet(
        manifest_path,
        "proof prohibition sanctions",
        follow_up_execution=chained_follow_up_execution,
    )
    repackaged_attached_view = package_docket_dataset(
        attached_package_view,
        tmp_path / "planned_bundle_with_packets",
        include_car=True,
    )
    restored_attached_view = load_packaged_docket_dataset(repackaged_attached_view["manifest_json_path"])
    materially_changed_execution = dict(chained_follow_up_execution)
    materially_changed_results = [dict(item) for item in list(chained_follow_up_execution["results"] or [])]
    materially_changed_results.append(
        {
            "id": "state_law_hit_2",
            "title": "Supplemental State Law Authority",
            "text": "Supplemental authority discussing proof sanctions and preservation duties.",
            "score": 0.88,
            "source_type": "legal_dataset_parser",
            "best_support_source": "legal_dataset_parser",
            "supporting_sources": ["legal_dataset_parser"],
            "supporting_steps": [2],
        }
    )
    materially_changed_execution["results"] = materially_changed_results
    materially_changed_execution["result_count"] = len(materially_changed_results)
    materially_changed_execution["proof_evidence_bundle"] = {}
    refreshed_attached_package_view = attach_packaged_docket_proof_assistant_packet(
        repackaged_attached_view["manifest_json_path"],
        "proof prohibition sanctions",
        follow_up_execution=materially_changed_execution,
    )
    repackaged_refreshed_view = package_docket_dataset(
        refreshed_attached_package_view,
        tmp_path / "planned_bundle_with_packets_v2",
        include_car=True,
    )
    restored_refreshed_view = load_packaged_docket_dataset(repackaged_refreshed_view["manifest_json_path"])
    reused_packet_view = attach_packaged_docket_proof_assistant_packet(
        repackaged_refreshed_view["manifest_json_path"],
        "proof prohibition sanctions",
        follow_up_execution=materially_changed_execution,
    )
    persisted_proof_plan = plan_packaged_docket_query(
        repackaged_attached_view["manifest_json_path"],
        "proof prohibition sanctions",
    )
    persisted_proof_result = execute_packaged_docket_query(
        repackaged_attached_view["manifest_json_path"],
        "proof prohibition sanctions",
        top_k=5,
    )
    persisted_follow_up_execution = execute_packaged_docket_follow_up_job(
        repackaged_attached_view["manifest_json_path"],
        {
            "job_ready": True,
            "job": {
                "job_kind": "proof_retrieval_follow_up",
                "source_type": "proof_packet",
                "source_id": proof_assistant_packet["proof_id"],
                "retrieval_query": "proof mystery refresh",
                "label": "Stored proof packet",
                "modules": [],
                "priority": 1,
                "rationale": "Reuse persisted proof evidence before escalating outward.",
            },
        },
        top_k=5,
    )
    persisted_reuse_job = prepare_packaged_docket_follow_up_job(
        repackaged_refreshed_view["manifest_json_path"],
        "proof prohibition sanctions",
        top_k=5,
    )
    persisted_reuse_execution = execute_packaged_docket_follow_up_job(
        repackaged_refreshed_view["manifest_json_path"],
        persisted_reuse_job,
        top_k=5,
    )
    refreshed_proof_result = execute_packaged_docket_query(
        repackaged_refreshed_view["manifest_json_path"],
        "proof prohibition sanctions",
        top_k=5,
    )
    refreshed_next_action_execution = execute_packaged_docket_next_action(
        repackaged_refreshed_view["manifest_json_path"],
        query_result=refreshed_proof_result,
        top_k=5,
    )
    refreshed_packet_for_competitor = refreshed_attached_package_view["attached_proof_assistant_packet"]
    competing_packet_view = load_packaged_docket_dataset(repackaged_refreshed_view["manifest_json_path"])
    weak_packet = dict(refreshed_packet_for_competitor)
    weak_packet["proof_id"] = f"{refreshed_packet_for_competitor['proof_id']}:weak_competitor"
    weak_packet["work_item_id"] = "weak_work_item"
    weak_packet["support_strength"] = "weak"
    weak_packet["query"] = "proof prohibition sanctions"
    weak_packet["matched_work_item"] = {
        "work_item_id": "weak_work_item",
        "title": "Weak Competing Packet",
        "plan": {"plan_id": "weak_plan", "work_item_id": "weak_work_item"},
    }
    weak_packet["matched_plan"] = {"plan_id": "weak_plan", "work_item_id": "weak_work_item"}
    weak_packet["evidence_bundle"] = {
        "bundle_kind": "packaged_docket_proof_evidence",
        "summary": {"evidence_item_count": 1, "satisfied": False},
        "evidence_items": [
            {
                "evidence_id": "weak_auth_hit",
                "title": "Weak Authority",
                "source_type": "authority_list",
                "best_support_source": "authority_list",
            }
        ],
        "retrieval_trace": [],
    }
    weak_proof = dict(
        restored_refreshed_view["proof_assistant"]["proof_store"]["proofs"][refreshed_packet_for_competitor["proof_id"]]
    )
    weak_proof["proof_id"] = weak_packet["proof_id"]
    weak_proof["work_item_id"] = "weak_work_item"
    weak_proof["title"] = "Weak Competing Packet"
    weak_proof["support_strength"] = "weak"
    weak_proof["evidence_ids"] = ["weak_auth_hit"]
    weak_proof["matched_plan"] = {"plan_id": "weak_plan", "work_item_id": "weak_work_item"}
    weak_proof["evidence_bundle"] = dict(weak_packet["evidence_bundle"])
    weak_proof["metadata"] = dict(weak_proof.get("metadata") or {})
    weak_proof["metadata"]["support_strength"] = "weak"
    weak_proof["metadata"]["proof_lineage"] = dict(weak_proof["metadata"].get("proof_lineage") or {})
    weak_proof["metadata"]["proof_lineage"]["packet_version"] = int(weak_packet["packet_version"])
    competing_packet_view["proof_assistant"]["evidence_packets"].append(
        {
            "proof_id": weak_packet["proof_id"],
            "query": "proof prohibition sanctions",
            "work_item_id": "weak_work_item",
            "bundle_kind": "packaged_docket_proof_evidence",
            "evidence_item_count": 1,
            "matched_plan_id": "weak_plan",
            "packet_version": int(weak_packet["packet_version"]),
            "is_current": True,
            "superseded": False,
            "supersedes_proof_ids": [],
            "superseded_by_proof_id": "",
            "support_strength": "weak",
        }
    )
    competing_packet_view["proof_assistant"]["proof_store"]["proofs"][weak_packet["proof_id"]] = weak_proof
    competing_packaged_view = package_docket_dataset(
        competing_packet_view,
        tmp_path / "planned_bundle_with_packets_competing",
        include_car=True,
    )
    competing_proof_result = execute_packaged_docket_query(
        competing_packaged_view["manifest_json_path"],
        "proof prohibition sanctions",
        top_k=5,
    )
    competing_reuse_job = prepare_packaged_docket_follow_up_job(
        competing_packaged_view["manifest_json_path"],
        "proof prohibition sanctions",
        top_k=5,
    )
    document_job_execution = execute_packaged_docket_follow_up_job(
        manifest_path,
        {
            "job_ready": True,
            "job": {
                "job_kind": "proof_retrieval_follow_up",
                "source_type": "local_docket_documents",
                "retrieval_query": "complaint damages",
                "source_id": "manual:documents",
                "label": "Manual local docs",
                "modules": [],
                "priority": 1,
                "rationale": "Direct local docket check.",
            },
        },
        top_k=2,
    )
    bm25_job_execution = execute_packaged_docket_follow_up_job(
        manifest_path,
        {
            "job_ready": True,
            "job": {
                "job_kind": "proof_retrieval_follow_up",
                "source_type": "local_bm25_index",
                "retrieval_query": "complaint damages",
                "source_id": "manual:bm25",
                "label": "Manual BM25",
                "modules": [],
                "priority": 1,
                "rationale": "Direct sparse index check.",
            },
        },
        top_k=2,
    )
    vector_job_execution = execute_packaged_docket_follow_up_job(
        manifest_path,
        {
            "job_ready": True,
            "job": {
                "job_kind": "proof_retrieval_follow_up",
                "source_type": "local_vector_index",
                "retrieval_query": "complaint damages",
                "source_id": "manual:vector",
                "label": "Manual vector",
                "modules": [],
                "priority": 1,
                "rationale": "Direct vector index check.",
            },
        },
        top_k=2,
    )

    assert lexical_plan["target"] == "bm25_search"
    assert lexical_plan["piece_ids"] == ["bm25_documents", "documents"]
    assert lexical_plan["estimated_cost"] >= 1
    assert lexical_plan["piece_costs"]["bm25_documents"] >= 1
    assert lexical_plan["stages"][0]["piece_ids"] == ["bm25_documents"]
    assert lexical_plan["stages"][1]["piece_ids"] == ["bm25_documents", "documents"]
    assert proof_plan["target"] == "proof_tasks"
    assert proof_plan["piece_ids"] == [
        "proof_agenda",
        "proof_tactician_plans",
        "deontic_trigger_entries",
        "proof_evidence_packets",
        "proof_store_entries",
    ]
    assert proof_plan["priority"] == 0
    assert proof_plan["stages"][0]["piece_ids"] == ["proof_agenda"]
    assert proof_plan["stages"][0]["result_policy"]["merge_mode"] == "by_work_item"
    assert proof_plan["stages"][1]["continue_on_success"] is True
    assert proof_plan["stages"][1]["result_policy"]["prefer_authority_sources"] is True
    assert proof_plan["stages"][1]["result_policy"]["prefer_plans"] is True
    assert proof_plan["stages"][1]["piece_ids"] == [
        "proof_agenda",
        "proof_tactician_plans",
        "deontic_trigger_entries",
        "proof_evidence_packets",
        "proof_store_entries",
    ]
    assert kg_plan["target"] == "knowledge_graph"
    assert kg_plan["piece_ids"] == ["knowledge_graph_entities", "knowledge_graph_relationships"]
    assert kg_plan["priority"] == 0
    assert kg_plan["stages"][0]["piece_ids"] == ["knowledge_graph_entities"]
    assert kg_plan["stages"][0]["result_policy"]["piece_priority"] == ["knowledge_graph_entities"]
    assert kg_plan["stages"][1]["continue_on_success"] is True
    assert kg_plan["stages"][1]["result_policy"]["piece_priority"] == [
        "knowledge_graph_entities",
        "knowledge_graph_relationships",
    ]
    assert kg_plan["stages"][1]["piece_ids"] == [
        "knowledge_graph_entities",
        "knowledge_graph_relationships",
    ]
    assert lexical_result["execution_plan"]["target"] == "bm25_search"
    assert lexical_result["result_count"] >= 1
    assert lexical_result["stages_executed"] == 1
    assert lexical_result["execution_stages"][0]["piece_ids"] == ["bm25_documents"]
    assert proof_result["execution_plan"]["target"] == "proof_tasks"
    assert proof_result["result_count"] >= 1
    assert proof_result["stages_executed"] == 2
    assert proof_result["execution_stages"][1]["piece_ids"] == [
        "proof_agenda",
        "proof_tactician_plans",
        "deontic_trigger_entries",
        "proof_evidence_packets",
        "proof_store_entries",
    ]
    assert proof_result["execution_stages"][1]["result_policy"]["prefer_authority_sources"] is True
    assert proof_result["execution_stages"][1]["cumulative_result_count"] >= 1
    assert proof_result["results"][0]["plan"]
    assert proof_result["results"][0]["authority_backed"] is True
    assert proof_result["results"][0]["source_type"] == "authority"
    assert proof_result["escalation"]["should_escalate"] is False
    assert proof_result["escalation"]["recommended_source_types"] == []
    assert proof_result["escalation"]["follow_up_plan"]["step_count"] == 0
    assert proof_result["escalation"]["next_action_summary"]["action_type"] == "none"
    assert proof_result["escalation"]["next_action_summary"]["execution_hint"] == {}
    assert kg_result["execution_plan"]["target"] == "knowledge_graph"
    assert kg_result["result_count"] >= 1
    assert kg_result["stages_executed"] == 2
    returned_piece_ids = {result["piece_id"] for result in kg_result["results"]}
    assert kg_result["results"][0]["piece_id"] == "knowledge_graph_entities"
    assert "knowledge_graph_entities" in returned_piece_ids
    assert "knowledge_graph_relationships" in returned_piece_ids
    assert proof_gap_result["execution_plan"]["target"] == "proof_tasks"
    assert proof_gap_result["result_count"] == 0
    assert proof_gap_result["escalation"]["should_escalate"] is True
    assert proof_gap_result["escalation"]["recommended_source_types"] == [
        "authority_list",
        "legal_dataset_parser",
        "search_engine",
    ]
    assert proof_gap_result["escalation"]["next_action_summary"]["action_type"] == "refresh_local_support"
    assert proof_gap_result["escalation"]["next_action_summary"]["source_type"] == "authority_list"
    assert proof_gap_result["escalation"]["next_action_summary"]["execution_hint"]["job_kind"] == "proof_retrieval_follow_up"
    assert proof_gap_result["escalation"]["next_action_summary"]["execution_hint"]["source_type"] == "authority_list"
    assert proof_gap_result["escalation"]["next_action_summary"]["execution_hint"]["action_type"] == "refresh_local_support"
    assert proof_gap_result["escalation"]["action_candidates"][0]["source_type"] == "authority_list"
    assert proof_gap_result["escalation"]["action_candidates"][1]["source_type"] == "legal_dataset_parser"
    assert proof_gap_result["escalation"]["action_candidates"][2]["source_type"] == "search_engine"
    assert proof_gap_result["escalation"]["recommended_sources"][0]["source_type"] == "authority_list"
    assert proof_gap_result["escalation"]["follow_up_plan"]["step_count"] == 3
    assert proof_gap_result["escalation"]["follow_up_plan"]["steps"][0]["source_type"] == "authority_list"
    assert proof_gap_result["escalation"]["follow_up_plan"]["steps"][0]["action_type"] == "refresh_local_support"
    assert "proof prohibition sanctions" in proof_gap_result["escalation"]["follow_up_plan"]["steps"][0]["retrieval_query"]
    assert proof_gap_result["escalation"]["follow_up_plan"]["steps"][1]["source_type"] == "legal_dataset_parser"
    assert proof_gap_result["escalation"]["follow_up_plan"]["steps"][1]["action_type"] == "refresh_local_support"
    assert proof_gap_result["escalation"]["follow_up_plan"]["steps"][2]["source_type"] == "search_engine"
    assert proof_gap_result["escalation"]["follow_up_plan"]["steps"][2]["action_type"] == "escalate_outward"
    assert proof_job["job_ready"] is True
    assert proof_job["source_type"] == "authority_list"
    assert proof_job["action_type"] == "refresh_local_support"
    assert proof_job["job"]["job_kind"] == "proof_retrieval_follow_up"
    assert proof_job["job"]["source_type"] == "authority_list"
    assert proof_job["job"]["action_type"] == "refresh_local_support"
    assert "proof prohibition sanctions" in proof_job["job"]["retrieval_query"]
    assert parser_job["job_ready"] is True
    assert parser_job["source_type"] == "legal_dataset_parser"
    assert parser_job["job"]["source_type"] == "legal_dataset_parser"
    assert parser_job["job"]["modules"]
    assert proof_noop_job["job_ready"] is False
    assert proof_noop_job["job"] == {}
    assert proof_job_execution["executed"] is True
    assert proof_job_execution["source_type"] == "authority_list"
    assert proof_job_execution["source"] == "packaged_authorities"
    assert proof_job_execution["result_count"] >= 1
    assert proof_job_execution["results"][0]["title"] == "Scheduling Order"
    assert proof_gap_next_action_execution["executed"] is True
    assert proof_gap_next_action_execution["action_type"] == "refresh_local_support"
    assert proof_gap_next_action_execution["source_type"] == "authority_list"
    assert proof_gap_next_action_execution["source"] == "packaged_authorities"
    assert proof_gap_next_action_execution["next_action_summary"]["source_type"] == "authority_list"
    assert proof_gap_next_action_execution["auto_chained"] is False
    assert proof_gap_next_action_execution["successful_action_summary"]["source_type"] == "authority_list"
    assert proof_gap_next_action_execution["successful_action_summary"]["action_type"] == "refresh_local_support"
    assert proof_gap_next_action_execution["successful_action_summary"]["support_strength"] == "weak"
    assert proof_gap_next_action_execution["successful_action_summary"]["evidence_preview"]["kind"] == "result_row"
    assert proof_gap_next_action_execution["successful_action_summary"]["evidence_preview"]["title"] == "Scheduling Order"
    assert proof_gap_chained_next_action_execution["executed"] is True
    assert proof_gap_chained_next_action_execution["auto_chained"] is True
    assert proof_gap_chained_next_action_execution["chained_execution"]["satisfied"] is True
    assert proof_gap_chained_next_action_execution["chained_execution"]["stopped_on_step"] == 2
    assert proof_gap_chained_next_action_execution["chained_execution"]["final_execution"]["source"] == "legal_dataset_parser_execution"
    assert proof_gap_chained_next_action_execution["successful_action_summary"]["source"] == "legal_dataset_parser_execution"
    assert proof_gap_chained_next_action_execution["successful_action_summary"]["source_type"] == "legal_dataset_parser"
    assert proof_gap_chained_next_action_execution["successful_action_summary"]["action_type"] == "refresh_local_support"
    assert proof_gap_chained_next_action_execution["successful_action_summary"]["support_strength"] == "strong"
    assert proof_gap_chained_next_action_execution["successful_action_summary"]["evidence_preview"]["kind"] == "result_row"
    assert proof_gap_chained_next_action_execution["successful_action_summary"]["evidence_preview"]["id"] == "state_law_hit_1"
    assert parser_job_execution["executed"] is True
    assert parser_job_execution["dispatched"] is True
    assert parser_job_execution["source_type"] == "legal_dataset_parser"
    assert parser_job_execution["dispatch"]["dispatch_kind"] == "legal_dataset_parser_request"
    assert parser_job_execution["dispatch"]["modules"]
    assert "proof prohibition sanctions" in parser_job_execution["dispatch"]["retrieval_query"]
    assert parser_job_execution["source"] == "legal_dataset_parser_execution"
    assert parser_job_execution["adapter"]["adapter_ready"] is True
    assert parser_job_execution["adapter"]["callable_name"] == "search_state_law_corpus_from_parameters"
    assert parser_job_execution["adapter"]["capability"] == "state_law_corpus_search"
    assert "proof prohibition sanctions" in parser_job_execution["adapter"]["parameters"]["query_text"]
    assert parser_job_execution["adapter"]["parameters"]["top_k"] == 5
    assert parser_job_execution["result_count"] == 1
    assert parser_job_execution["results"][0]["id"] == "state_law_hit_1"
    assert parser_job_execution["parser_result"]["status"] == "success"
    assert observed_parser_calls
    assert "proof prohibition sanctions" in observed_parser_calls[0][0]["query_text"]
    assert observed_parser_calls[0][0]["top_k"] == 5
    assert chained_follow_up_execution["executed"] is True
    assert chained_follow_up_execution["steps_executed"] == 2
    assert chained_follow_up_execution["stopped_on_step"] == 2
    assert chained_follow_up_execution["satisfied"] is True
    assert chained_follow_up_execution["result_count"] == 2
    assert chained_follow_up_execution["final_result_count"] == 1
    assert chained_follow_up_execution["steps_attempted"][0]["source_type"] == "authority_list"
    assert chained_follow_up_execution["steps_attempted"][0]["result_count"] == 1
    assert chained_follow_up_execution["steps_attempted"][0]["cumulative_result_count"] == 1
    assert chained_follow_up_execution["steps_attempted"][0]["satisfied"] is False
    assert chained_follow_up_execution["steps_attempted"][1]["source_type"] == "legal_dataset_parser"
    assert chained_follow_up_execution["steps_attempted"][1]["result_count"] == 1
    assert chained_follow_up_execution["steps_attempted"][1]["cumulative_result_count"] == 2
    assert chained_follow_up_execution["steps_attempted"][1]["satisfied"] is True
    assert chained_follow_up_execution["final_execution"]["source"] == "legal_dataset_parser_execution"
    assert chained_follow_up_execution["results"][0]["id"] == "state_law_hit_1"
    assert chained_follow_up_execution["results"][1]["id"] == "auth_1"
    returned_ids = {item["id"] for item in chained_follow_up_execution["results"]}
    assert "state_law_hit_1" in returned_ids
    assert "auth_1" in returned_ids
    parser_row = next(item for item in chained_follow_up_execution["results"] if item["id"] == "state_law_hit_1")
    authority_row = next(item for item in chained_follow_up_execution["results"] if item["id"] == "auth_1")
    assert parser_row["best_support_source"] == "legal_dataset_parser"
    assert authority_row["best_support_source"] == "authority_list"
    assert parser_row["supporting_sources"] == ["legal_dataset_parser"]
    assert parser_row["supporting_steps"] == [2]
    assert authority_row["supporting_sources"] == ["authority_list"]
    assert authority_row["supporting_steps"] == [1]
    assert chained_follow_up_execution["final_results"][0]["id"] == "state_law_hit_1"
    assert chained_follow_up_execution["proof_evidence_bundle"]["bundle_kind"] == "packaged_docket_proof_evidence"
    assert chained_follow_up_execution["proof_evidence_bundle"]["summary"]["evidence_item_count"] == 2
    assert chained_follow_up_execution["proof_evidence_bundle"]["summary"]["best_support_sources"] == [
        "legal_dataset_parser",
        "authority_list",
    ]
    assert chained_follow_up_execution["proof_evidence_bundle"]["evidence_items"][0]["evidence_id"] == "state_law_hit_1"
    assert chained_follow_up_execution["proof_evidence_bundle"]["retrieval_trace"][1]["source_type"] == "legal_dataset_parser"
    assert proof_evidence_bundle["dataset_id"] == dataset.dataset_id
    assert proof_evidence_bundle["docket_id"] == dataset.docket_id
    assert proof_evidence_bundle["summary"]["steps_executed"] == 2
    assert proof_evidence_bundle["evidence_items"][1]["evidence_id"] == "auth_1"
    assert proof_assistant_packet["packet_kind"] == "packaged_docket_proof_assistant_packet"
    assert proof_assistant_packet["dataset_id"] == dataset.dataset_id
    assert proof_assistant_packet["docket_id"] == dataset.docket_id
    assert proof_assistant_packet["matched_work_item"]["work_item_id"]
    assert proof_assistant_packet["matched_work_item"]["plan"]
    assert "Discovery Motion" in proof_assistant_packet["matched_work_item"]["title"]
    assert proof_assistant_packet["packet_version"] == 1
    assert proof_assistant_packet["is_current"] is True
    assert proof_assistant_packet["superseded"] is False
    assert proof_assistant_packet["supersedes_proof_ids"] == []
    assert proof_assistant_packet["support_strength"] == "strong"
    assert proof_assistant_packet["proof_store"]["summary"]["proof_count"] == 1
    assert proof_assistant_packet["proof_store"]["summary"]["evidence_item_count"] == 2
    assert proof_assistant_packet["proof_store"]["metadata"]["backend"] == "packaged_docket_follow_up_proof_packet"
    stored_proof = proof_assistant_packet["proof_store"]["proofs"][proof_assistant_packet["proof_id"]]
    assert stored_proof["work_item_id"] == proof_assistant_packet["matched_work_item"]["work_item_id"]
    assert stored_proof["packet_version"] == 1
    assert stored_proof["is_current"] is True
    assert stored_proof["superseded"] is False
    assert stored_proof["support_strength"] == "strong"
    assert stored_proof["evidence_ids"] == ["state_law_hit_1", "auth_1"]
    assert stored_proof["matched_plan"]["work_item_id"] == proof_assistant_packet["matched_work_item"]["work_item_id"]
    assert stored_proof["evidence_bundle"]["bundle_kind"] == "packaged_docket_proof_evidence"
    assert attached_package_view["metadata"]["proof_packet_attached"] is True
    assert attached_package_view["attached_proof_assistant_packet"]["proof_id"] == proof_assistant_packet["proof_id"]
    assert attached_package_view["metadata"]["latest_proof_packet_version"] == 1
    assert attached_package_view["proof_assistant"]["summary"]["latest_proof_packet_support_strength"] == "strong"
    assert attached_package_view["proof_assistant"]["summary"]["proof_packet_count"] == 1
    assert attached_package_view["proof_assistant"]["summary"]["current_proof_packet_count"] == 1
    assert attached_package_view["proof_assistant"]["summary"]["superseded_proof_packet_count"] == 0
    assert attached_package_view["proof_assistant"]["summary"]["proof_count"] == 1
    assert attached_package_view["proof_assistant"]["summary"]["evidence_item_count"] == 2
    assert attached_package_view["proof_assistant"]["proof_store"]["summary"]["packet_count"] == 1
    assert attached_package_view["proof_assistant"]["proof_store"]["summary"]["current_packet_count"] == 1
    assert attached_package_view["proof_assistant"]["proof_store"]["summary"]["superseded_packet_count"] == 0
    attached_agenda_item = next(
        item
        for item in attached_package_view["proof_assistant"]["agenda"]
        if item["work_item_id"] == proof_assistant_packet["matched_work_item"]["work_item_id"]
    )
    assert attached_agenda_item["attached_evidence_count"] == 2
    assert attached_agenda_item["latest_proof_packet_id"] == proof_assistant_packet["proof_id"]
    assert attached_agenda_item["current_proof_packet_id"] == proof_assistant_packet["proof_id"]
    assert attached_agenda_item["current_proof_packet_version"] == 1
    assert attached_agenda_item["current_proof_packet_support_strength"] == "strong"
    assert attached_agenda_item["evidence_status"] == "collected_evidence"
    assert proof_assistant_packet["proof_id"] in attached_agenda_item["evidence_packet_ids"]
    assert restored_attached_view["proof_assistant"]["summary"]["proof_packet_count"] == 1
    assert restored_attached_view["proof_assistant"]["summary"]["current_proof_packet_count"] == 1
    assert restored_attached_view["proof_assistant"]["summary"]["superseded_proof_packet_count"] == 0
    assert restored_attached_view["proof_assistant"]["summary"]["proof_count"] == 1
    assert restored_attached_view["proof_assistant"]["evidence_packets"][0]["proof_id"] == proof_assistant_packet["proof_id"]
    assert restored_attached_view["proof_assistant"]["evidence_packets"][0]["packet_version"] == 1
    assert restored_attached_view["proof_assistant"]["evidence_packets"][0]["is_current"] is True
    assert restored_attached_view["proof_assistant"]["evidence_packets"][0]["support_strength"] == "strong"
    assert proof_assistant_packet["proof_id"] in restored_attached_view["proof_assistant"]["proof_store"]["proofs"]
    restored_proof = restored_attached_view["proof_assistant"]["proof_store"]["proofs"][proof_assistant_packet["proof_id"]]
    assert restored_proof["evidence_ids"] == ["state_law_hit_1", "auth_1"]
    assert restored_proof["packet_version"] == 1
    assert restored_proof["is_current"] is True
    assert restored_proof["support_strength"] == "strong"
    restored_agenda_item = next(
        item
        for item in restored_attached_view["proof_assistant"]["agenda"]
        if item["work_item_id"] == proof_assistant_packet["matched_work_item"]["work_item_id"]
    )
    assert restored_agenda_item["latest_proof_packet_id"] == proof_assistant_packet["proof_id"]
    assert restored_agenda_item["current_proof_packet_id"] == proof_assistant_packet["proof_id"]
    assert restored_agenda_item["current_proof_packet_support_strength"] == "strong"
    assert proof_assistant_packet["proof_id"] in restored_agenda_item["evidence_packet_ids"]
    assert persisted_proof_plan["target"] == "proof_tasks"
    assert persisted_proof_plan["piece_ids"] == [
        "proof_agenda",
        "proof_tactician_plans",
        "deontic_trigger_entries",
        "proof_evidence_packets",
        "proof_store_entries",
    ]
    assert persisted_proof_result["result_count"] >= 1
    assert persisted_proof_result["results"][0]["source_type"] == "proof_packet"
    assert persisted_proof_result["results"][0]["proof_id"] == proof_assistant_packet["proof_id"]
    assert persisted_proof_result["results"][0]["packet_version"] == 1
    assert persisted_proof_result["results"][0]["is_current"] is True
    assert persisted_proof_result["results"][0]["plan"]
    assert persisted_proof_result["results"][0]["authority_backed"] is True
    assert persisted_proof_result["escalation"]["should_escalate"] is False
    assert persisted_follow_up_execution["executed"] is True
    assert persisted_follow_up_execution["source_type"] == "proof_packet"
    assert persisted_follow_up_execution["action_type"] == "reuse_current_packet"
    assert persisted_follow_up_execution["source"] == "packaged_proof_packet"
    assert persisted_follow_up_execution["result_count"] == 2
    assert persisted_follow_up_execution["proof_packet"]["proof_id"] == proof_assistant_packet["proof_id"]
    assert persisted_follow_up_execution["proof_packet"]["packet_version"] == 1
    assert persisted_follow_up_execution["proof_packet"]["is_current"] is True
    assert persisted_follow_up_execution["proof_packet"]["matched_plan"]["work_item_id"] == proof_assistant_packet["matched_work_item"]["work_item_id"]
    refreshed_packet = refreshed_attached_package_view["attached_proof_assistant_packet"]
    assert refreshed_packet["proof_id"] != proof_assistant_packet["proof_id"]
    assert refreshed_packet["packet_version"] == 2
    assert refreshed_packet["is_current"] is True
    assert refreshed_packet["supersedes_proof_ids"] == [proof_assistant_packet["proof_id"]]
    assert refreshed_packet["support_strength"] == "strong"
    refreshed_packet_rows = restored_refreshed_view["proof_assistant"]["evidence_packets"]
    assert len(refreshed_packet_rows) == 2
    old_packet_row = next(item for item in refreshed_packet_rows if item["proof_id"] == proof_assistant_packet["proof_id"])
    new_packet_row = next(item for item in refreshed_packet_rows if item["proof_id"] == refreshed_packet["proof_id"])
    assert old_packet_row["is_current"] is False
    assert old_packet_row["superseded"] is True
    assert old_packet_row["superseded_by_proof_id"] == refreshed_packet["proof_id"]
    assert new_packet_row["is_current"] is True
    assert new_packet_row["superseded"] is False
    assert new_packet_row["packet_version"] == 2
    assert new_packet_row["supersedes_proof_ids"] == [proof_assistant_packet["proof_id"]]
    assert new_packet_row["support_strength"] == "strong"
    assert restored_refreshed_view["proof_assistant"]["summary"]["proof_packet_count"] == 2
    assert restored_refreshed_view["proof_assistant"]["summary"]["current_proof_packet_count"] == 1
    assert restored_refreshed_view["proof_assistant"]["summary"]["superseded_proof_packet_count"] == 1
    assert restored_refreshed_view["proof_assistant"]["proof_store"]["summary"]["packet_count"] == 2
    assert restored_refreshed_view["proof_assistant"]["proof_store"]["summary"]["current_packet_count"] == 1
    assert restored_refreshed_view["proof_assistant"]["proof_store"]["summary"]["superseded_packet_count"] == 1
    refreshed_agenda_item = next(
        item
        for item in restored_refreshed_view["proof_assistant"]["agenda"]
        if item["work_item_id"] == proof_assistant_packet["matched_work_item"]["work_item_id"]
    )
    assert refreshed_agenda_item["latest_proof_packet_id"] == refreshed_packet["proof_id"]
    assert refreshed_agenda_item["current_proof_packet_id"] == refreshed_packet["proof_id"]
    assert refreshed_agenda_item["current_proof_packet_version"] == 2
    assert refreshed_agenda_item["current_proof_packet_support_strength"] == "strong"
    assert proof_assistant_packet["proof_id"] in refreshed_agenda_item["evidence_packet_ids"]
    assert refreshed_packet["proof_id"] in refreshed_agenda_item["evidence_packet_ids"]
    refreshed_old_proof = restored_refreshed_view["proof_assistant"]["proof_store"]["proofs"][proof_assistant_packet["proof_id"]]
    refreshed_new_proof = restored_refreshed_view["proof_assistant"]["proof_store"]["proofs"][refreshed_packet["proof_id"]]
    assert refreshed_old_proof["is_current"] is False
    assert refreshed_old_proof["superseded"] is True
    assert refreshed_old_proof["superseded_by_proof_id"] == refreshed_packet["proof_id"]
    assert refreshed_new_proof["is_current"] is True
    assert refreshed_new_proof["packet_version"] == 2
    assert refreshed_new_proof["supersedes_proof_ids"] == [proof_assistant_packet["proof_id"]]
    assert refreshed_new_proof["support_strength"] == "strong"
    assert refreshed_proof_result["results"][0]["source_type"] == "proof_packet"
    assert refreshed_proof_result["results"][0]["proof_id"] == refreshed_packet["proof_id"]
    assert refreshed_proof_result["results"][0]["packet_version"] == 2
    assert refreshed_proof_result["results"][0]["is_current"] is True
    assert refreshed_proof_result["escalation"]["next_action_summary"]["action_type"] == "reuse_current_packet"
    assert refreshed_proof_result["escalation"]["next_action_summary"]["source_type"] == "proof_packet"
    assert refreshed_proof_result["escalation"]["next_action_summary"]["source_id"] == refreshed_packet["proof_id"]
    assert "current" in refreshed_proof_result["escalation"]["next_action_summary"]["selection_rationale"]
    assert "strong support" in refreshed_proof_result["escalation"]["next_action_summary"]["selection_rationale"]
    assert refreshed_proof_result["escalation"]["next_action_summary"]["execution_hint"]["job_kind"] == "proof_retrieval_follow_up"
    assert refreshed_proof_result["escalation"]["next_action_summary"]["execution_hint"]["source_type"] == "proof_packet"
    assert refreshed_proof_result["escalation"]["next_action_summary"]["execution_hint"]["action_type"] == "reuse_current_packet"
    assert refreshed_proof_result["escalation"]["next_action_summary"]["execution_hint"]["source_id"] == refreshed_packet["proof_id"]
    assert refreshed_next_action_execution["executed"] is True
    assert refreshed_next_action_execution["action_type"] == "reuse_current_packet"
    assert refreshed_next_action_execution["source_type"] == "proof_packet"
    assert refreshed_next_action_execution["proof_packet"]["proof_id"] == refreshed_packet["proof_id"]
    assert refreshed_next_action_execution["successful_action_summary"]["source_type"] == "proof_packet"
    assert refreshed_next_action_execution["successful_action_summary"]["action_type"] == "reuse_current_packet"
    assert refreshed_next_action_execution["successful_action_summary"]["source_id"] == refreshed_packet["proof_id"]
    assert refreshed_next_action_execution["successful_action_summary"]["support_strength"] == "strong"
    assert refreshed_next_action_execution["successful_action_summary"]["evidence_preview"]["kind"] == "proof_evidence_item"
    assert refreshed_next_action_execution["successful_action_summary"]["evidence_preview"]["id"] == "state_law_hit_1"
    assert competing_proof_result["results"][0]["proof_id"] == refreshed_packet["proof_id"]
    assert competing_proof_result["results"][0]["support_strength"] == "strong"
    assert "strong support" in competing_proof_result["results"][0]["selection_rationale"]
    assert competing_proof_result["results"][1]["proof_id"] == weak_packet["proof_id"]
    assert competing_proof_result["results"][1]["support_strength"] == "weak"
    assert "weak support" in competing_proof_result["results"][1]["selection_rationale"]
    assert competing_proof_result["escalation"]["packet_candidates"][0]["proof_id"] == refreshed_packet["proof_id"]
    assert competing_proof_result["escalation"]["packet_candidates"][0]["support_strength"] == "strong"
    assert "strong support" in competing_proof_result["escalation"]["packet_candidates"][0]["selection_rationale"]
    assert competing_proof_result["escalation"]["packet_candidates"][1]["proof_id"] == weak_packet["proof_id"]
    assert competing_proof_result["escalation"]["packet_candidates"][1]["support_strength"] == "weak"
    assert competing_proof_result["escalation"]["action_candidates"][0]["source_type"] == "proof_packet"
    assert competing_proof_result["escalation"]["action_candidates"][0]["source_id"] == refreshed_packet["proof_id"]
    assert competing_proof_result["escalation"]["action_candidates"][0]["support_strength"] == "strong"
    assert competing_proof_result["escalation"]["action_candidates"][1]["source_id"] == weak_packet["proof_id"]
    assert competing_proof_result["escalation"]["next_action_summary"]["source_id"] == refreshed_packet["proof_id"]
    assert "strong support" in competing_proof_result["escalation"]["next_action_summary"]["selection_rationale"]
    assert competing_reuse_job["job"]["source_id"] == refreshed_packet["proof_id"]
    assert competing_reuse_job["action_type"] == "reuse_current_packet"
    assert persisted_reuse_job["job_ready"] is True
    assert persisted_reuse_job["source_type"] == "proof_packet"
    assert persisted_reuse_job["action_type"] == "reuse_current_packet"
    assert persisted_reuse_job["job"]["action_type"] == "reuse_current_packet"
    assert persisted_reuse_job["job"]["source_id"] == refreshed_packet["proof_id"]
    assert persisted_reuse_execution["executed"] is True
    assert persisted_reuse_execution["source_type"] == "proof_packet"
    assert persisted_reuse_execution["action_type"] == "reuse_current_packet"
    assert persisted_reuse_execution["proof_packet"]["proof_id"] == refreshed_packet["proof_id"]
    reused_packet = reused_packet_view["attached_proof_assistant_packet"]
    assert reused_packet_view["proof_packet_refresh"]["decision"] == "reused_current_packet"
    assert reused_packet_view["proof_packet_refresh"]["material_change_detected"] is False
    assert reused_packet_view["metadata"]["proof_packet_reused"] is True
    assert reused_packet["proof_id"] == refreshed_packet["proof_id"]
    assert reused_packet["packet_version"] == 2
    assert reused_packet["refresh_decision"] == "reused_current_packet"
    assert reused_packet["material_change_detected"] is False
    assert len(reused_packet_view["proof_assistant"]["evidence_packets"]) == 2
    assert document_job_execution["executed"] is True
    assert document_job_execution["source_type"] == "local_docket_documents"
    assert document_job_execution["result_count"] >= 1
    assert document_job_execution["results"][0]["title"] == "Complaint"
    assert bm25_job_execution["executed"] is True
    assert bm25_job_execution["source_type"] == "local_bm25_index"
    assert bm25_job_execution["source"] == "packaged_local_bm25"
    assert bm25_job_execution["result_count"] >= 1
    assert bm25_job_execution["results"][0]["id"] == "doc_1"
    assert vector_job_execution["executed"] is True
    assert vector_job_execution["source_type"] == "local_vector_index"
    assert vector_job_execution["source"] == "packaged_vector_items"
    assert vector_job_execution["result_count"] >= 1
    assert vector_job_execution["results"][0]["title"] == "Complaint"


def test_docket_deontic_artifacts_capture_party_and_authority_triggers():
    graph, triggers = build_docket_deontic_artifacts(
        dataset_id="dataset_x",
        docket_id="1:24-cv-1001",
        plaintiff_docket=[{"id": "pl_1", "title": "Notice", "text": "Plaintiff must serve notice."}],
        defendant_docket=[{"id": "df_1", "title": "Order", "text": "Defendant is ordered to produce records."}],
        authorities=[{"id": "auth_1", "title": "Rule 26", "text": "Parties shall disclose witnesses."}],
    )

    assert graph.summary()["total_rules"] >= 3
    assert triggers["summary"]["authority_trigger_count"] == 1
    assert "plaintiff" in triggers["summary"]["parties_requiring_analysis"]
    assert "defendant" in triggers["summary"]["parties_requiring_analysis"]
    assert triggers["summary"]["rule_count_by_party"]["plaintiff"] >= 1
    assert triggers["summary"]["rule_count_by_party"]["defendant"] >= 1
    assert "plaintiff" in triggers["party_analysis"]
    assert "defendant" in triggers["party_analysis"]
    assert triggers["party_analysis"]["plaintiff"]["obligations"]
    assert triggers["party_analysis"]["defendant"]["obligations"]
    assert "Rule 26" in triggers["party_analysis"]["plaintiff"]["authority_labels"]


def test_docket_dataset_refreshes_deontic_triggers_when_new_items_are_added():
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-1003",
            "case_name": "Doe v. Example",
            "documents": [{"id": "doc_1", "title": "Complaint", "text": "Initial complaint text."}],
        }
    )

    assert dataset.summary()["deontic_rule_count"] == 0

    dataset.append_party_docket_item(
        "plaintiff",
        {"id": "pl_new", "title": "Motion for Discovery", "text": "Plaintiff must respond to discovery deadlines."},
    )
    dataset.append_authority(
        {"id": "auth_new", "title": "Case Management Order", "text": "The parties shall meet and confer."}
    )

    refreshed_summary = summarize_docket_dataset(dataset)
    assert refreshed_summary["deontic_rule_count"] >= 1
    assert refreshed_summary["authority_count"] == 1
    assert refreshed_summary["proof_assistant_work_item_count"] >= 2
    assert refreshed_summary["proof_assistant_formula_count"] >= 2
    assert refreshed_summary["proof_tactician_plan_count"] >= 2
    assert "plaintiff" in refreshed_summary["parties_requiring_deontic_analysis"]
    assert "defendant" in refreshed_summary["parties_requiring_deontic_analysis"]
    assert dataset.deontic_triggers["party_analysis"]["plaintiff"]["rule_count"] >= 1
    assert dataset.deontic_triggers["party_analysis"]["defendant"]["rule_count"] >= 1
    assert dataset.deontic_triggers["party_analysis"]["defendant"]["authority_labels"] == [
        "Case Management Order"
    ]
    assert dataset.proof_assistant["summary"]["party_count"] >= 2
    assert dataset.proof_assistant["summary"]["extractor_count"] == 6
    assert dataset.proof_assistant["party_analysis"]["plaintiff"]["proof_work_item_count"] >= 1
    assert dataset.proof_assistant["party_analysis"]["defendant"]["proof_work_item_count"] >= 1
    assert dataset.proof_assistant["deontic_cognitive_event_calculus"]["formulas"]
    assert dataset.proof_assistant["temporal_fol"]["formulas"]
    assert dataset.proof_assistant["extractors"]["trigger_monitor"]["pending_work_item_count"] >= 2
    assert dataset.proof_assistant["extractors"]["proof_tactician"]["plan_count"] >= 1
    assert dataset.proof_assistant["tactician"]["plans"]
    assert dataset.proof_assistant["summary"]["tactician_plan_count"] >= 2
    assert dataset.proof_assistant["tactician"]["plans"][0]["proof_gap_focus"]
    assert dataset.proof_assistant["tactician"]["plans"][0]["search_stages"][0]["stage"] == "local"


def test_docket_dataset_can_be_packaged_into_parquet_and_car_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_SAFE_ROOT", str(tmp_path))
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-1004",
            "case_name": "Doe v. Archive",
            "court": "D. Example",
            "plaintiff_docket": [
                {"id": "pl_1", "title": "Motion", "text": "Plaintiff must provide disclosures."}
            ],
            "authorities": [
                {"id": "auth_1", "title": "Scheduling Order", "text": "The parties shall exchange disclosures."}
            ],
            "documents": [
                {
                    "id": "doc_1",
                    "title": "Complaint",
                    "text": "Complaint text with contract allegations.",
                    "date_filed": "2024-01-01",
                    "source_url": "/records/complaint.pdf",
                    "source_path": "/records/complaint.pdf",
                }
            ],
        }
    )
    dataset.documents[0].metadata["raw"] = {
        "attachment_paths": ["/records/complaint.pdf", "/records/complaint.ocr.txt"]
    }

    package_result = dataset.write_package(tmp_path / "bundles", package_name="test_bundle")
    package_result_via_function = package_docket_dataset(
        dataset.to_dict(),
        tmp_path / "bundles_function",
        package_name="test_bundle_2",
    )
    package_result_via_class = DocketDatasetPackager().package(
        dataset,
        tmp_path / "bundles_class",
        package_name="test_bundle_3",
    )

    manifest_path = tmp_path / "bundles" / "test_bundle" / "bundle_manifest.json"
    assert manifest_path.exists()
    bundle_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    piece_ids = {piece["piece_id"] for piece in bundle_manifest["pieces"]}
    assert "dataset_core" in piece_ids
    assert "documents" in piece_ids
    assert "attachments" in piece_ids
    assert "knowledge_graph_entities" in piece_ids
    assert "deontic_rules" in piece_ids
    assert "proof_tactician_plans" in piece_ids
    assert bundle_manifest["root_piece_id"] == "dataset_core"
    assert bundle_manifest["chain_load_order"][0] == "dataset_core"
    assert any(piece["car_path"] for piece in bundle_manifest["pieces"])
    assert all((tmp_path / "bundles" / "test_bundle" / piece["parquet_path"]).exists() for piece in bundle_manifest["pieces"])

    loaded = load_packaged_docket_dataset(manifest_path)
    restored = DocketDatasetObject.from_package(manifest_path)
    assert loaded["dataset_id"] == dataset.dataset_id
    assert restored.docket_id == dataset.docket_id
    assert loaded["package_manifest"]["attachments"]
    assert package_result["summary"]["attachment_count"] >= 2
    assert package_result["manifest_parquet_path"].endswith("bundle_manifest.parquet")
    assert package_result["manifest_car_path"].endswith("bundle_manifest.car")
    assert package_result_via_function["piece_count"] == package_result["piece_count"]
    assert package_result_via_class["piece_count"] == package_result["piece_count"]


def test_docket_dataset_can_roundtrip_from_json_parquet_car_and_zip_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_SAFE_ROOT", str(tmp_path))
    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-1005",
            "case_name": "Doe v. Roundtrip",
            "court": "D. Example",
            "documents": [
                {
                    "id": "doc_1",
                    "title": "Complaint",
                    "text": "Complaint text with contract allegations.",
                    "date_filed": "2024-01-01",
                },
                {
                    "id": "doc_2",
                    "title": "Order",
                    "text": "Defendant shall file an answer by 4/7/2026.",
                    "date_filed": "2024-01-02",
                },
            ],
        }
    )

    package_result = dataset.write_package(tmp_path / "bundle_formats", package_name="roundtrip_bundle")
    bundle_dir = Path(package_result["bundle_dir"])
    manifest_json_path = Path(package_result["manifest_json_path"])
    manifest_parquet_path = Path(package_result["manifest_parquet_path"])
    manifest_car_path = Path(package_result["manifest_car_path"])
    zip_path = bundle_dir.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle_dir.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path.relative_to(bundle_dir.parent)))

    loaded_from_json = load_packaged_docket_dataset(manifest_json_path)
    loaded_from_parquet = load_packaged_docket_dataset(manifest_parquet_path)
    loaded_from_car = load_packaged_docket_dataset(manifest_car_path)
    loaded_from_zip = load_packaged_docket_dataset(zip_path)

    for loaded in (loaded_from_json, loaded_from_parquet, loaded_from_car, loaded_from_zip):
        assert loaded["dataset_id"] == dataset.dataset_id
        assert loaded["docket_id"] == dataset.docket_id
        assert len(loaded["documents"]) == 2
        assert loaded["documents"][1]["title"] == "Order"

    components_from_parquet = load_packaged_docket_dataset_components(
        manifest_parquet_path,
        piece_ids=["documents", "bm25_documents"],
    )
    components_from_car = load_packaged_docket_dataset_components(
        manifest_car_path,
        piece_ids=["documents", "bm25_documents"],
    )
    components_from_zip = load_packaged_docket_dataset_components(
        zip_path,
        piece_ids=["documents", "bm25_documents"],
    )

    assert len(components_from_parquet["documents"]) == 2
    assert len(components_from_car["documents"]) == 2
    assert len(components_from_zip["documents"]) == 2


def test_packaged_docket_logic_artifact_queries_execute_via_direct_and_planned_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_SAFE_ROOT", str(tmp_path))

    def _fake_enrichment(documents, **kwargs):  # noqa: ANN001
        doc_id = documents[0].document_id
        return {
            "document_analyses": {
                doc_id: {
                    "classification": {"label": "motion", "backend": "llm_router"},
                }
            },
            "knowledge_graph": {"entities": [], "relationships": []},
            "temporal_fol": {"formulas": ["Filed(doc_1, t1)."]},
            "deontic_cognitive_event_calculus": {
                "formulas": [
                    "Happens(DocumentFiled(doc_1), t1).",
                    "Ought(Filed(doc_1, t1)).",
                ]
            },
            "frame_logic": {
                f"{doc_id}:frame:1": {
                    "frame_id": f"{doc_id}:frame:1",
                    "label": "MotionFrame",
                    "slots": {"party": "plaintiff"},
                }
            },
            "proof_store": {
                "proofs": {},
                "summary": {"proof_count": 0},
                "metadata": {"backend": "router_enriched_proof_store"},
            },
            "summary": {"processed_document_count": 1, "proof_count": 0},
        }

    monkeypatch.setattr(
        "ipfs_datasets_py.processors.legal_data.docket_dataset.enrich_docket_documents_with_routers",
        _fake_enrichment,
    )

    dataset = DocketDatasetBuilder().build_from_docket(
        {
            "docket_id": "1:24-cv-logic",
            "case_name": "Doe v. Logic Artifacts",
            "court": "D. Example",
            "documents": [
                {"id": "doc_1", "title": "Motion", "text": "Plaintiff filed a motion."},
            ],
        }
    )

    package_info = dataset.write_package(tmp_path / "logic_bundle", include_car=False)
    manifest_path = package_info["manifest_json_path"]
    adapter = PackagedDocketQueryAdapter(manifest_path)
    logic_components = load_packaged_docket_dataset_components(
        manifest_path,
        piece_ids=["temporal_formulas", "dcec_formulas", "frame_logic_frames"],
    )
    direct_result = search_packaged_docket_logic_artifacts(manifest_path, "filed document motionframe", top_k=5)
    adapter_result = adapter.execute_plan(
        adapter.plan_query("temporal formulas filed document motionframe"),
        top_k=5,
    )
    planned_result = execute_packaged_docket_query(
        manifest_path,
        "temporal formulas filed document motionframe",
        top_k=5,
    )

    assert logic_components["temporal_formulas"][0]["formula"] == "Filed(doc_1, t1)."
    assert logic_components["dcec_formulas"][0]["formula"] == "Happens(DocumentFiled(doc_1), t1)."
    assert logic_components["frame_logic_frames"][0]["label"] == "MotionFrame"
    assert direct_result["result_count"] >= 1
    assert any(result.get("artifact_type") == "temporal_formula" for result in direct_result["results"])
    assert adapter_result["execution_plan"]["target"] == "logic_artifacts"
    assert adapter_result["result_count"] >= 1
    assert any(result.get("artifact_type") in {"temporal_formula", "dcec_formula", "frame_logic_frame"} for result in adapter_result["results"])
    assert planned_result["execution_plan"]["target"] == "logic_artifacts"
    assert planned_result["result_count"] >= 1
    assert any(result.get("artifact_type") in {"temporal_formula", "dcec_formula", "frame_logic_frame"} for result in planned_result["results"])
