"""Offline acceptance tests for Abby response-template GraphRAG."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.voice import (
    EvidenceRecord,
    GraphRAGIngestionError,
    GraphRAGVoiceTemplateProvider,
    SlottedResponseIndex,
    UnsafeSlotBindingError,
)
from ipfs_datasets_py.voice.schema import (
    ABBY_VOICE_TEMPLATE_V2,
    AbbyVoiceAudio,
    AbbyVoiceProvenance,
    AbbyVoiceResponse,
    AbbyVoiceTemplate,
)

FOOD_CID = "bafybeigcurrentfoodrecord20260723"
FOOD_CONTACT_CID = "bafybeigcurrentfoodcontact20260723"
SHELTER_CID = "bafybeigcurrentshelterrecord20260723"
FOOD_AUDIO_CID = "bafybeigabbyfoodaudiorecord20260723"


def _food_template(**overrides: Any) -> AbbyVoiceTemplate:
    values: dict[str, Any] = {
        "template_id": "food-frame",
        "template_text": "{program} can help. Call {phone}.",
        "spoken_template": "{program} can help. Call {phone}.",
        "intent": "food_assistance",
        "locale": "en-US",
        "slot_names": ("program", "phone"),
        "required_slot_names": ("program", "phone"),
        "factual_slot_names": ("program", "phone"),
        "source_cids": (FOOD_CID, FOOD_CONTACT_CID),
        "provenance_ids": ("prov-food-template",),
        "safety_labels": ("public_service",),
        "license_id": "CC-BY-4.0",
        "consent_status": "not_required",
        "created_at": "2026-07-23T12:00:00Z",
    }
    values.update(overrides)
    return AbbyVoiceTemplate(**values)


def _shelter_template(**overrides: Any) -> AbbyVoiceTemplate:
    values: dict[str, Any] = {
        "template_id": "shelter-frame",
        "template_text": "{shelter} has an opening. Call {phone}.",
        "spoken_template": "{shelter} has an opening. Call {phone}.",
        "intent": "emergency_shelter",
        "locale": "en-US",
        "slot_names": ("shelter", "phone"),
        "required_slot_names": ("shelter", "phone"),
        "factual_slot_names": ("shelter", "phone"),
        "source_cids": (SHELTER_CID,),
        "license_id": "CC-BY-4.0",
        "consent_status": "not_required",
    }
    values.update(overrides)
    return AbbyVoiceTemplate(**values)


def _food_response(**overrides: Any) -> AbbyVoiceResponse:
    values: dict[str, Any] = {
        "response_id": "food-example",
        "text": "Old Food Program can help. Call 503-555-0000.",
        "spoken_text": "Old Food Program can help. Call five zero three five five five zero zero zero zero.",
        "template_id": "food-frame",
        "intent": "food_assistance",
        "utterance": "I need meals and groceries near me.",
        "slot_names": ("program", "phone"),
        "slot_values": ("Old Food Program", "503-555-0000"),
        "slot_source_cids": (FOOD_CID, FOOD_CONTACT_CID),
        "audio_ids": ("food-audio",),
        "provenance_ids": ("prov-food-response",),
        "source_cids": (FOOD_CID,),
        "service_tags": ("food", "groceries"),
        "license_id": "CC-BY-4.0",
        "consent_status": "not_required",
    }
    values.update(overrides)
    return AbbyVoiceResponse(**values)


def _food_audio() -> AbbyVoiceAudio:
    return AbbyVoiceAudio(
        audio_id="food-audio",
        spoken_text="Historical response audio.",
        content_sha256="a" * 64,
        uri=f"ipfs://{FOOD_AUDIO_CID}",
        ipfs_cid=FOOD_AUDIO_CID,
        response_id="food-example",
        template_id="food-frame",
        source_cids=(FOOD_CID,),
        license_id="CC-BY-4.0",
        consent_status="granted",
    )


def _provenance(
    provenance_id: str,
    subject_id: str,
    subject_schema_version: str,
) -> AbbyVoiceProvenance:
    return AbbyVoiceProvenance(
        provenance_id=provenance_id,
        subject_id=subject_id,
        subject_schema_version=subject_schema_version,
        transformation_name="normalize_abby_voice",
        transformation_version="2.0.0",
        source_uri="https://example.test/public-211-source",
        source_revision="2026-07-23",
        source_sha256="b" * 64,
        source_cids=(FOOD_CID,),
        generated_at="2026-07-23T12:00:00Z",
        license_id="CC-BY-4.0",
        consent_status="not_required",
    )


def _rows() -> dict[str, tuple[Any, ...]]:
    return {
        "templates": (_food_template(), _shelter_template()),
        "responses": (_food_response(),),
        "audio": (_food_audio(),),
        "provenance": (
            _provenance("prov-food-template", "food-frame", ABBY_VOICE_TEMPLATE_V2),
            _provenance(
                "prov-food-response",
                "food-example",
                "abby_voice_response_v2",
            ),
        ),
    }


def _current_food(
    *,
    phone: str = "503-555-0111",
    source_id: str = "food-current",
    cid: str = FOOD_CID,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "cid": cid,
        "uri": f"ipfs://{cid}",
        "text": "Current Community Food Network public service record.",
        "facts": {
            "program": "Community Food Network",
            "phone": phone,
        },
        "metadata": {
            "title": "Current public food record",
            "revision": "2026-07-23",
        },
    }


def _current_shelter() -> dict[str, Any]:
    return {
        "source_id": "shelter-current",
        "cid": SHELTER_CID,
        "facts": {
            "shelter": "Night Owl Shelter",
            "phone": "503-555-0222",
        },
    }


def test_ingest_builds_ipld_template_intent_evidence_graph() -> None:
    index = SlottedResponseIndex.from_rows(**_rows())

    node_kinds = {node.kind for node in index.graph.nodes}
    edge_kinds = {edge.kind for edge in index.graph.edges}
    assert {
        "intent",
        "template",
        "slot",
        "evidence",
        "response",
        "audio",
        "provenance",
    } <= node_kinds
    assert {
        "ROUTES_TO",
        "DECLARES_SLOT",
        "REQUIRES_EVIDENCE",
        "SUPPORTED_BY",
        "INSTANCE_OF",
        "HISTORICAL_BINDING",
        "HAS_AUDIO",
        "DESCRIBES",
        "DERIVED_FROM",
    } <= edge_kinds
    evidence = next(
        node for node in index.graph.nodes if node.node_id == f"evidence:{FOOD_CID}"
    )
    assert evidence.properties == {"cid": FOOD_CID, "facts_persisted": False}
    response = next(
        node for node in index.graph.nodes if node.node_id == "response:food-example"
    )
    serialized_response = json.dumps(response.to_dict(), sort_keys=True)
    assert "503-555-0000" not in serialized_response
    assert response.properties["historical_example"] is True
    assert index.graph_cid.startswith("bafk")
    assert index.index_cid.startswith("bafk")


def test_ingestion_is_order_independent_content_addressed_and_non_mutating() -> None:
    rows = _rows()
    payload = {
        key: [row.to_dict() for row in values] for key, values in rows.items()
    }
    before = json.dumps(payload, sort_keys=True)

    forward = SlottedResponseIndex.from_rows(**payload)
    reverse = SlottedResponseIndex.from_rows(
        **{key: list(reversed(values)) for key, values in payload.items()}
    )

    assert json.dumps(payload, sort_keys=True) == before
    assert forward.to_dict() == reverse.to_dict()
    assert forward.index_cid == reverse.index_cid
    assert forward.graph_cid == reverse.graph_cid
    assert [node.node_id for node in forward.graph.nodes] == sorted(
        node.node_id for node in forward.graph.nodes
    )
    assert [edge.edge_id for edge in forward.graph.edges] == sorted(
        edge.edge_id for edge in forward.graph.edges
    )


def test_exact_duplicate_is_idempotent_but_conflicting_id_is_rejected() -> None:
    template = _food_template(provenance_ids=())
    index = SlottedResponseIndex.from_rows(templates=(template,))
    receipt = index.ingest(templates=(template,))

    assert receipt.added_templates == 0
    assert receipt.duplicate_rows == 1
    with pytest.raises(GraphRAGIngestionError, match="conflicting template"):
        index.ingest(
            templates=(
                _food_template(
                    template_text="Use {program}; phone {phone}.",
                    spoken_template="Use {program}; phone {phone}.",
                    provenance_ids=(),
                ),
            )
        )


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (
            {
                "templates": (_food_template(),),
                "responses": (_food_response(template_id="unknown-template", audio_ids=(), provenance_ids=()),),
            },
            "missing template",
        ),
        (
            {
                "templates": (_food_template(provenance_ids=()),),
                "audio": (
                    AbbyVoiceAudio(
                        audio_id="orphan-audio",
                        spoken_text="orphan",
                        content_sha256="c" * 64,
                        uri="ipfs://bafy-orphan",
                        template_id="unknown-template",
                    ),
                ),
            },
            "missing template",
        ),
        (
            {
                "templates": (
                    _food_template(source_cids=(), provenance_ids=()),
                ),
            },
            "must declare source_cids",
        ),
    ],
)
def test_ingestion_rejects_broken_or_ungroundable_relationships(
    kwargs: dict[str, Any], message: str
) -> None:
    with pytest.raises(GraphRAGIngestionError, match=message):
        SlottedResponseIndex.from_rows(**kwargs)


def test_provider_returns_router_compatible_response_plan() -> None:
    provider = GraphRAGVoiceTemplateProvider(
        SlottedResponseIndex.from_rows(**_rows()),
        minimum_confidence=0.30,
    )

    plan = provider.retrieve(
        "I need food and groceries",
        language="en-US",
        grounding={"current_evidence": [_current_food()]},
    )

    assert plan is not None
    assert set(plan) == {
        "template_id",
        "template",
        "slots",
        "sources",
        "confidence",
        "intent",
        "metadata",
    }
    assert plan["template_id"] == "food-frame"
    assert plan["template"] == "{program} can help. Call {phone}."
    assert plan["slots"] == [
        {
            "name": "program",
            "value": "Community Food Network",
            "source_ids": ["food-current"],
        },
        {
            "name": "phone",
            "value": "503-555-0111",
            "source_ids": ["food-current"],
        },
    ]
    assert plan["sources"][0]["cid"] == FOOD_CID
    assert plan["metadata"]["response_plan_only"] is True
    assert plan["metadata"]["retrieval"] == "hybrid"


def test_provider_exposes_accelerator_backend_method_aliases() -> None:
    backend = GraphRAGVoiceTemplateProvider(
        SlottedResponseIndex.from_rows(**_rows()), minimum_confidence=0.30
    )
    result = backend.retrieve_voice_template(
        "food assistance",
        language="en-US",
        grounding={"sources": [_current_food()]},
    )

    assert result is not None
    assert result["template_id"] == "food-frame"
    assert result["template"] == "{program} can help. Call {phone}."
    assert result["slots"][1]["value"] == "503-555-0111"
    assert result["slots"][1]["source_ids"] == ["food-current"]
    assert result["sources"][0]["cid"] == FOOD_CID
    assert backend.retrieve_template(
        "food assistance",
        language="en-US",
        grounding={"sources": [_current_food()]},
    ) == result


def test_historical_example_values_are_never_current_facts() -> None:
    provider = GraphRAGVoiceTemplateProvider(
        SlottedResponseIndex.from_rows(**_rows()), minimum_confidence=0.30
    )
    plan = provider.retrieve(
        "food assistance",
        language="en-US",
        grounding={"sources": [_current_food(phone="503-555-0999")]},
    )

    assert plan is not None
    serialized = json.dumps(plan, sort_keys=True)
    assert "503-555-0999" in serialized
    assert "503-555-0000" not in serialized
    assert plan["metadata"]["historical_example_values_used_as_facts"] is False


def test_missing_or_contradictory_current_evidence_fails_closed() -> None:
    provider = GraphRAGVoiceTemplateProvider(
        SlottedResponseIndex.from_rows(**_rows()), minimum_confidence=0.30
    )

    assert (
        provider.retrieve("food assistance", language="en-US", grounding={}) is None
    )
    assert (
        provider.retrieve(
            "food assistance",
            language="en-US",
            grounding={"sources": []},
        )
        is None
    )
    incomplete = _current_food()
    incomplete["facts"] = {"program": "Community Food Network"}
    assert (
        provider.retrieve(
            "food assistance",
            language="en-US",
            grounding={"sources": [incomplete]},
        )
        is None
    )
    assert (
        provider.retrieve(
            "food assistance",
            language="en-US",
            grounding={
                "sources": [
                    _current_food(phone="503-555-0111", source_id="source-a"),
                    _current_food(phone="503-555-0999", source_id="source-b"),
                ]
            },
        )
        is None
    )


def test_evidence_requires_source_identity_cid_and_valid_facts() -> None:
    with pytest.raises(UnsafeSlotBindingError, match="source_id"):
        EvidenceRecord(source_id="", cid=FOOD_CID, facts={})
    with pytest.raises(UnsafeSlotBindingError, match="source CID"):
        EvidenceRecord(source_id="current", cid="", facts={})
    with pytest.raises(UnsafeSlotBindingError, match="invalid fact name"):
        EvidenceRecord(
            source_id="current",
            cid=FOOD_CID,
            facts={"bad slot!": "unsafe"},
        )
    with pytest.raises(UnsafeSlotBindingError, match="facts must be a mapping"):
        EvidenceRecord.from_mapping(
            {"source_id": "current", "cid": FOOD_CID, "facts": ["not", "facts"]}
        )
    with pytest.raises(UnsafeSlotBindingError, match="JSON scalar"):
        EvidenceRecord(
            source_id="current",
            cid=FOOD_CID,
            facts={"phone": {"uncited": "nested value"}},
        )


@dataclass
class RecordingVectorStore:
    scores: dict[str, float]
    documents: list[Any] = field(default_factory=list)
    queries: list[tuple[tuple[float, ...], int]] = field(default_factory=list)

    def upsert_documents(self, documents: list[Any]) -> None:
        self.documents.extend(documents)

    def search(self, vector: tuple[float, ...], *, top_k: int) -> list[dict[str, Any]]:
        self.queries.append((tuple(vector), top_k))
        return [
            {
                "chunk_id": template_id,
                "score": score,
                "metadata": {"template_id": template_id},
            }
            for template_id, score in self.scores.items()
        ]


def test_hybrid_retrieval_uses_injected_vector_store_without_model_dependencies() -> None:
    store = RecordingVectorStore({"food-frame": 0.10, "shelter-frame": 0.99})
    index = SlottedResponseIndex.from_rows(
        templates=(_food_template(provenance_ids=()), _shelter_template()),
        vector_store=store,
        lexical_weight=0,
        vector_weight=1,
        graph_weight=0,
    )

    matches = index.search(
        "semantically encoded query",
        current_source_cids=(FOOD_CID, SHELTER_CID),
        max_results=2,
    )

    assert [match.template.template_id for match in matches] == [
        "shelter-frame",
        "food-frame",
    ]
    assert matches[0].vector_score == 0.99
    assert len(store.documents) == 2
    assert store.queries and store.queries[0][1] >= 20


def test_ranking_ties_have_stable_template_id_tiebreak() -> None:
    left = _food_template(
        template_id="frame-a",
        provenance_ids=(),
    )
    right = _food_template(
        template_id="frame-b",
        provenance_ids=(),
    )
    first = SlottedResponseIndex.from_rows(templates=(right, left))
    second = SlottedResponseIndex.from_rows(templates=(left, right))

    assert [
        item.template.template_id
        for item in first.search("food assistance", max_results=2)
    ] == ["frame-a", "frame-b"]
    assert [
        item.template.template_id
        for item in second.search("food assistance", max_results=2)
    ] == ["frame-a", "frame-b"]


def test_confidence_boundary_locale_intent_and_result_limit_are_enforced() -> None:
    spanish = _food_template(
        template_id="food-frame-es",
        locale="es-US",
        intent="asistencia_alimentaria",
        provenance_ids=(),
    )
    index = SlottedResponseIndex.from_rows(
        templates=(_food_template(provenance_ids=()), _shelter_template(), spanish)
    )
    exact = index.search(
        "food assistance",
        locale="en-US",
        intent="food_assistance",
        max_results=1,
    )

    assert len(exact) == 1
    assert exact[0].template.template_id == "food-frame"
    assert exact[0].confidence >= 0.95
    assert (
        index.search(
            "food assistance",
            locale="en-US",
            minimum_score=exact[0].confidence,
        )[0].template.template_id
        == "food-frame"
    )
    assert index.search(
        "asistencia alimentaria", locale="es-US", intent="asistencia_alimentaria"
    )[0].template.template_id == "food-frame-es"
    with pytest.raises(ValueError, match="positive integer"):
        index.search("food", max_results=0)
    with pytest.raises(ValueError, match="between 0 and 1"):
        index.search("food", minimum_score=1.01)


def test_retrieval_provenance_is_complete_and_stably_ordered() -> None:
    provider = GraphRAGVoiceTemplateProvider(
        SlottedResponseIndex.from_rows(**_rows()), minimum_confidence=0.30
    )
    second = _current_food(source_id="aaa-food-current")
    plan = provider.retrieve(
        "food assistance",
        language="en-US",
        grounding={"sources": [_current_food(source_id="zzz-food-current"), second]},
    )

    assert plan is not None
    assert [source["source_id"] for source in plan["sources"]] == [
        "aaa-food-current",
        "zzz-food-current",
    ]
    assert all(source["cid"] == FOOD_CID for source in plan["sources"])
    metadata = plan["metadata"]
    assert metadata["index_cid"].startswith("bafk")
    assert metadata["graph_cid"].startswith("bafk")
    assert metadata["provenance_ids"] == ["prov-food-template"]
    assert metadata["audio_ids"] == ["food-audio"]
    assert set(metadata["scores"]) == {"lexical", "vector", "graph"}
    assert all(
        slot["source_ids"] == ["aaa-food-current", "zzz-food-current"]
        for slot in plan["slots"]
    )


def test_slotless_template_is_still_a_plan_not_generated_final_prose() -> None:
    template = AbbyVoiceTemplate(
        template_id="clarify-frame",
        template_text="What city or ZIP code should I search?",
        spoken_template="What city or ZIP code should I search?",
        intent="clarify_location",
        source_cids=(),
        license_id="CC0-1.0",
        consent_status="not_required",
    )
    provider = GraphRAGVoiceTemplateProvider.from_rows(
        templates=(template,), minimum_confidence=0.30
    )

    plan = provider.retrieve(
        "clarify location",
        context={"intent": "clarify_location"},
        language="en-US",
    )

    assert plan is not None
    assert plan["template"] == template.template_text
    assert plan["slots"] == []
    assert plan["sources"] == []
    assert plan["metadata"]["response_plan_only"] is True


def test_json_export_restore_preserves_identity_graph_and_retrieval() -> None:
    original = SlottedResponseIndex.from_rows(**_rows())
    payload = json.loads(json.dumps(original.to_dict(), sort_keys=True))
    restored = SlottedResponseIndex.from_dict(payload)

    assert restored.index_cid == original.index_cid
    assert restored.graph_cid == original.graph_cid
    assert restored.to_dict() == original.to_dict()
    assert [
        match.to_dict() for match in restored.search("I need groceries", max_results=2)
    ] == [
        match.to_dict() for match in original.search("I need groceries", max_results=2)
    ]
    payload["templates"][0]["template_text"] = "tampered"
    with pytest.raises((GraphRAGIngestionError, ValueError)):
        SlottedResponseIndex.from_dict(payload)

    graph_tamper = original.to_dict()
    graph_tamper["graph"]["nodes"][0]["label"] = "tampered"
    with pytest.raises(GraphRAGIngestionError, match="graph snapshot"):
        SlottedResponseIndex.from_dict(graph_tamper)


@dataclass
class RecordingKnowledgeGraph:
    entities: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    root_cid: str = "bafyexternalgraphroot"

    def add_entity(self, **kwargs: Any) -> None:
        self.entities.append(kwargs)

    def add_relationship(self, **kwargs: Any) -> None:
        self.relationships.append(kwargs)


@dataclass
class QueryExpander:
    queries: list[str] = field(default_factory=list)

    def expand_query(self, query: str) -> dict[str, Any]:
        self.queries.append(query)
        # A collaborator may expand retrieval vocabulary, but final-answer or
        # slot fields are intentionally ignored by the index.
        return {
            "expanded_query": "food groceries meals",
            "final_answer": "Call an uncited stale number.",
            "slots": {"phone": "503-555-0000"},
        }


def test_injected_ipld_graph_and_graphrag_query_expansion_are_bounded() -> None:
    graph = RecordingKnowledgeGraph()
    expander = QueryExpander()
    index = SlottedResponseIndex.from_rows(
        templates=(_food_template(provenance_ids=()),),
        knowledge_graph=graph,
        graphrag_processor=expander,
    )

    matches = index.search("I am hungry", max_results=1)

    assert matches[0].template.template_id == "food-frame"
    assert graph.entities
    assert graph.relationships
    assert all(item["entity_id"] for item in graph.entities)
    assert all(item["relationship_id"] for item in graph.relationships)
    assert expander.queries == ["I am hungry"]
    assert "503-555-0000" not in json.dumps(matches[0].to_dict(), sort_keys=True)


def test_module_import_is_dependency_light_and_offline() -> None:
    package_root = Path(__file__).resolve().parents[3]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root)
    script = (
        "import sys; import ipfs_datasets_py.voice.graphrag; "
        "heavy=('transformers','faiss','networkx','ipld_car'); "
        "print(','.join(name for name in heavy if name in sys.modules))"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.stdout.strip() == ""
