"""Interactive refinement UI endpoints for ontology strategy preview and application.

Provides a lightweight FastAPI router that exposes:
- HTML refinement preview page
- Strategy suggestions
- Strategy impact preview
- Strategy comparison
- Single and batch strategy application
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, MutableMapping, Optional

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import HTMLResponse


def create_refinement_ui_router(
    mediator: Any,
    ontology_store: Optional[MutableMapping[str, Dict[str, Any]]] = None,
) -> APIRouter:
    """Create a router exposing interactive refinement endpoints.

    Args:
        mediator: OntologyMediator-compatible object.
        ontology_store: Mutable mapping from ontology_id to ontology payload.

    Returns:
        Configured APIRouter instance.
    """
    store = ontology_store if ontology_store is not None else {}
    router = APIRouter()

    @router.get("/refinement", response_class=HTMLResponse)
    async def get_refinement_ui() -> str:
        return """
<!DOCTYPE html>
<html>
<head><title>Interactive Refinement Preview</title></head>
<body>
  <h1>Ontology Refinement Preview</h1>
  <div id=\"strategy-list\"></div>
</body>
</html>
""".strip()

    @router.get("/refinement/{ontology_id}", response_class=HTMLResponse)
    async def get_refinement_ui_for_ontology(ontology_id: str) -> str:
        _ensure_ontology(store, ontology_id)
        return f'<div class="ontology-id" data-id="{ontology_id}">Refining: {ontology_id}</div>'

    @router.get("/api/refinement/{ontology_id}/suggestions")
    async def get_suggestions(ontology_id: str) -> Dict[str, Any]:
        ontology = _ensure_ontology(store, ontology_id)
        score = _build_proxy_score(ontology)
        context = SimpleNamespace(domain="general")

        strategy = mediator.suggest_refinement_strategy(ontology, score, context)
        suggestions = [
            {
                "id": "primary",
                "action": strategy.get("action", "no_action_needed"),
                "priority": strategy.get("priority", "low"),
                "estimated_impact": float(strategy.get("estimated_impact", 0.0)),
                "rationale": strategy.get("rationale", ""),
            }
        ]
        for idx, action in enumerate(strategy.get("alternative_actions", []), start=1):
            suggestions.append(
                {
                    "id": f"alt_{idx}",
                    "action": action,
                    "priority": strategy.get("priority", "low"),
                    "estimated_impact": max(0.0, float(strategy.get("estimated_impact", 0.0)) * 0.75),
                    "rationale": "Alternative strategy from mediator recommendation.",
                }
            )

        return {"ontology_id": ontology_id, "suggestions": suggestions}

    @router.post("/api/refinement/{ontology_id}/preview")
    async def preview_strategy(ontology_id: str, strategy: Dict[str, Any]) -> Dict[str, Any]:
        ontology = _ensure_ontology(store, ontology_id)
        entities = ontology.get("entities", [])
        relationships = ontology.get("relationships", [])
        missing_properties = sum(1 for e in entities if not e.get("properties"))

        return {
            "ontology_id": ontology_id,
            "strategy_id": strategy.get("strategy_id", strategy.get("id", "preview")),
            "preview": {
                "changes": 1,
                "new_entities": 0,
                "merged_entities": 0,
                "relationship_changes": 1 if strategy.get("action") == "add_missing_relationships" else 0,
                "estimated_property_fixes": missing_properties,
                "entity_count": len(entities),
                "relationship_count": len(relationships),
            },
        }

    @router.post("/api/refinement/{ontology_id}/compare")
    async def compare_strategies(ontology_id: str, strategies: List[Dict[str, Any]]) -> Dict[str, Any]:
        _ensure_ontology(store, ontology_id)
        comparison = mediator.compare_strategies(strategies)
        return {"ontology_id": ontology_id, "comparison": comparison}

    @router.post("/api/refinement/{ontology_id}/apply")
    async def apply_strategy(ontology_id: str, strategy: Dict[str, Any]) -> Dict[str, Any]:
        ontology = _ensure_ontology(store, ontology_id)
        before_entities = len(ontology.get("entities", []))
        before_relationships = len(ontology.get("relationships", []))

        action = str(strategy.get("action", "")).strip() or "add_missing_properties"
        recommendation = _action_to_recommendation(action)
        feedback = SimpleNamespace(recommendations=[recommendation])
        context = SimpleNamespace(domain="general")

        refined = mediator.refine_ontology(ontology, feedback, context)
        store[ontology_id] = refined

        after_entities = len(refined.get("entities", []))
        after_relationships = len(refined.get("relationships", []))
        return {
            "ontology_id": ontology_id,
            "result": {
                "success": True,
                "strategy_id": strategy.get("strategy_id", strategy.get("id", "applied")),
                "changes_applied": 1,
                "entity_delta": after_entities - before_entities,
                "relationship_delta": after_relationships - before_relationships,
                "ontology": refined,
            },
        }

    @router.post("/api/refinement/{ontology_id}/apply-batch")
    async def apply_strategy_batch(ontology_id: str, strategies: List[Dict[str, Any]]) -> Dict[str, Any]:
        _ensure_ontology(store, ontology_id)
        results: List[Dict[str, Any]] = []

        for order, strategy in enumerate(strategies, start=1):
            response = await apply_strategy(ontology_id, strategy)
            result = dict(response["result"])
            result["order"] = order
            results.append(result)

        return {
            "ontology_id": ontology_id,
            "batch_result": {
                "success": True,
                "strategies_count": len(strategies),
                "results": results,
            },
        }

    return router


def create_refinement_ui_app(
    mediator: Any,
    ontology_store: Optional[MutableMapping[str, Dict[str, Any]]] = None,
) -> FastAPI:
    """Create a FastAPI app serving the interactive refinement endpoints."""
    app = FastAPI(title="Ontology Refinement UI")
    app.include_router(create_refinement_ui_router(mediator, ontology_store=ontology_store))
    return app


def _ensure_ontology(
    ontology_store: MutableMapping[str, Dict[str, Any]],
    ontology_id: str,
) -> Dict[str, Any]:
    if ontology_id not in ontology_store:
        raise HTTPException(status_code=404, detail="Ontology not found")
    return ontology_store[ontology_id]


def _build_proxy_score(ontology: Dict[str, Any]) -> Any:
    entities = ontology.get("entities", [])
    relationships = ontology.get("relationships", [])
    entity_count = len(entities)
    relationship_count = len(relationships)

    coverage = min(1.0, relationship_count / max(1, entity_count))
    clarity = 1.0 - (sum(1 for e in entities if not e.get("properties")) / max(1, entity_count))
    consistency = 0.75
    overall = (coverage + clarity + consistency) / 3.0

    recommendations: List[str] = []
    if clarity < 0.7:
        recommendations.append("Add missing property definitions for entities")
    if coverage < 0.7:
        recommendations.append("Add missing relationships for unlinked entities")

    return SimpleNamespace(
        completeness=coverage,
        consistency=consistency,
        clarity=clarity,
        overall=overall,
        recommendations=recommendations,
    )


def _action_to_recommendation(action: str) -> str:
    mapping = {
        "add_missing_properties": "Improve clarity and add property definitions",
        "normalize_names": "Normalize naming conventions",
        "prune_orphans": "Prune orphan entities with no coverage",
        "merge_duplicates": "Remove duplicate entities for consistency",
        "add_missing_relationships": "Add missing relationships for unlinked entities",
        "split_entity": "Split broad entities into granular parts",
        "rename_entity": "Normalize naming conventions",
    }
    return mapping.get(action, "Improve ontology quality")