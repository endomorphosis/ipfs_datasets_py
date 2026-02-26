"""Tests for interactive refinement UI endpoint module."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi.testclient import TestClient

from ipfs_datasets_py.optimizers.graphrag.refinement_ui_endpoint import create_refinement_ui_app


class _FakeMediator:
    def suggest_refinement_strategy(self, ontology: Dict[str, Any], score: Any, context: Any) -> Dict[str, Any]:
        return {
            "action": "add_missing_properties",
            "priority": "medium",
            "estimated_impact": 0.1,
            "rationale": "Properties missing on several entities.",
            "alternative_actions": ["normalize_names"],
        }

    def compare_strategies(self, strategies: List[Dict[str, Any]]) -> Dict[str, Any]:
        ranked = []
        for idx, strategy in enumerate(strategies, start=1):
            ranked.append({"rank": idx, "strategy": strategy})
        return {
            "best_strategy": strategies[0] if strategies else None,
            "ranked_strategies": ranked,
            "summary": {"count": len(strategies)},
        }

    def refine_ontology(self, ontology: Dict[str, Any], feedback: Any, context: Any) -> Dict[str, Any]:
        recommendations = [r.lower() for r in getattr(feedback, "recommendations", [])]
        updated = {
            "entities": [dict(entity) for entity in ontology.get("entities", [])],
            "relationships": [dict(rel) for rel in ontology.get("relationships", [])],
        }
        if any("property" in rec for rec in recommendations):
            for entity in updated["entities"]:
                props = dict(entity.get("properties", {}))
                props.setdefault("autofilled", True)
                entity["properties"] = props
        return updated


def _build_client() -> tuple[TestClient, Dict[str, Dict[str, Any]]]:
    store = {
        "ont_001": {
            "entities": [
                {"id": "e1", "text": "Acme Corp", "type": "Organization", "properties": {}},
                {"id": "e2", "text": "Jane Doe", "type": "Person", "properties": {}},
            ],
            "relationships": [],
        }
    }
    app = create_refinement_ui_app(_FakeMediator(), ontology_store=store)
    return TestClient(app), store


def test_refinement_ui_page_serves() -> None:
    client, _ = _build_client()
    response = client.get("/refinement")
    assert response.status_code == 200
    assert "Interactive Refinement Preview" in response.text
    assert "strategy-list" in response.text


def test_refinement_ui_for_ontology_serves() -> None:
    client, _ = _build_client()
    response = client.get("/refinement/ont_001")
    assert response.status_code == 200
    assert "Refining: ont_001" in response.text


def test_get_strategy_suggestions_returns_primary_and_alternative() -> None:
    client, _ = _build_client()
    response = client.get("/api/refinement/ont_001/suggestions")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ontology_id"] == "ont_001"
    assert len(payload["suggestions"]) == 2
    assert payload["suggestions"][0]["action"] == "add_missing_properties"


def test_preview_strategy_returns_preview_payload() -> None:
    client, _ = _build_client()
    response = client.post(
        "/api/refinement/ont_001/preview",
        json={"strategy_id": "s1", "action": "add_missing_properties"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["preview"]["changes"] == 1
    assert payload["preview"]["estimated_property_fixes"] == 2


def test_compare_strategies_uses_mediator() -> None:
    client, _ = _build_client()
    response = client.post(
        "/api/refinement/ont_001/compare",
        json=[
            {"strategy_id": "s1", "action": "add_missing_properties"},
            {"strategy_id": "s2", "action": "normalize_names"},
        ],
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["comparison"]["summary"]["count"] == 2
    assert payload["comparison"]["best_strategy"]["strategy_id"] == "s1"


def test_apply_and_apply_batch_update_ontology_store() -> None:
    client, store = _build_client()

    apply_response = client.post(
        "/api/refinement/ont_001/apply",
        json={"strategy_id": "single", "action": "add_missing_properties"},
    )
    assert apply_response.status_code == 200
    for entity in store["ont_001"]["entities"]:
        assert entity["properties"].get("autofilled") is True

    batch_response = client.post(
        "/api/refinement/ont_001/apply-batch",
        json=[
            {"strategy_id": "b1", "action": "add_missing_properties"},
            {"strategy_id": "b2", "action": "normalize_names"},
        ],
    )
    assert batch_response.status_code == 200
    payload = batch_response.json()
    assert payload["batch_result"]["success"] is True
    assert payload["batch_result"]["strategies_count"] == 2
