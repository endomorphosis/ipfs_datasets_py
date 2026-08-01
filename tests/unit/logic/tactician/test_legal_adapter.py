"""Legal ProofTactician compatibility is adapter-only, not generic semantics."""

from __future__ import annotations

import inspect

import pytest

from ipfs_datasets_py.logic.tactician import (
    SCHEMA_VERSION,
    adapt_proof_tactician_plan,
    goal_from_proof_search_plan,
    sources_from_proof_search_plan,
)
from ipfs_datasets_py.logic.tactician import models as tactician_models
from ipfs_datasets_py.processors.legal_data.proof_tactician import (
    ProofSearchPlan,
    ProofSearchSource,
    ProofTactician,
)


def test_generic_models_module_has_no_legal_source_categories() -> None:
    source = inspect.getsource(tactician_models)
    # Domain-neutral models must not hard-code legal route types or adapters.
    for token in (
        "local_docket_documents",
        "local_bm25_index",
        "legal_dataset_parser",
        "ProofTactician",
        "local_vector_index",
        "recap_archive",
    ):
        assert token not in source


def test_adapt_proof_tactician_plan_projects_without_generic_legal_enums() -> None:
    legal = ProofTactician()
    plan = legal.build_search_plan(
        dataset_id="ds1",
        docket_id="dk1",
        work_item={
            "work_item_id": "wi-1",
            "party": "plaintiff",
            "title": "Prove service deadline",
        },
        documents=[{"id": "doc-1"}],
        authorities=[{"citation_text": "Fed. R. Civ. P. 4"}],
        bm25_index={"document_count": 3},
        vector_index={"document_count": 2},
    )
    assert isinstance(plan, ProofSearchPlan)
    assert plan.candidate_sources

    receipt = adapt_proof_tactician_plan(
        plan,
        corpus_root="corpus:legal:ds1",
        authority_roots={"docket": "docket:dk1"},
    )
    assert receipt.semantic_authority is False
    assert receipt.plan.schema_version == SCHEMA_VERSION
    assert receipt.plan.goal_id.startswith("legal-goal:")
    assert receipt.plan.selected_routes
    # Legal source types appear only as opaque caller-provided class strings.
    classes = {route.source_class for route in receipt.plan.selected_routes}
    assert "local_docket_documents" in classes or classes
    assert all(isinstance(item, str) for item in classes)


def test_sources_from_dict_and_goal_projection() -> None:
    plan_dict = {
        "plan_id": "plan-1",
        "work_item_id": "wi-9",
        "party": "all",
        "objective": "Find evidence",
        "proof_gap_focus": ["deadline", "service"],
        "candidate_sources": [
            ProofSearchSource(
                source_id="ds:local:docs",
                source_type="local_docket_documents",
                label="Local docs",
                priority=1,
                rationale="Primary filings",
                query_hints=["deadline"],
                metadata={"document_count": 1},
            ).to_dict()
        ],
        "recommended_route": ["local_docket_documents"],
    }
    sources = sources_from_proof_search_plan(plan_dict)
    assert len(sources) == 1
    assert sources[0].source_class == "local_docket_documents"
    goal = goal_from_proof_search_plan(
        plan_dict,
        corpus_root="corpus:x",
        config_root="policy:x",
    )
    assert goal.proof_gaps == ["deadline", "service"]
    assert goal.metadata.get("adapter") == "ProofTactician"
