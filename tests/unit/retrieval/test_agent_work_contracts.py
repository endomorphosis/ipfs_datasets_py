"""Unit tests for EAAEF-060 federated retrieval request/plan/result contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.retrieval.agent_work_contracts import (
    CONTRACT_VERSION,
    EVIDENCE_CLASSES,
    FEDERATED_RETRIEVAL_PLAN_INTERFACE,
    FEDERATED_RETRIEVAL_REQUEST_INTERFACE,
    FEDERATED_RETRIEVAL_RESULT_INTERFACE,
    SOURCE_DOMAINS,
    EvidenceClass,
    FederatedRetrievalContractError,
    SourceDomain,
    TrustClass,
    compile_plan,
    compile_request,
    compile_result,
)


def _payload(**overrides):
    body = {
        "objectives": ["compose provenance-preserving federated retrieval"],
        "symbols": ["compile_request", "FederatedRetrievalRequest"],
        "evidence_classes": [
            "repository_truth",
            "imported_claim",
            "verified_receipt",
        ],
        "source_domains": [
            "repository_truth",
            "imported_claims",
            "verified_receipts",
        ],
        "engine_budgets": {
            "ast": {"max_hits": 8, "max_bytes": 4096, "timeout_ms": 50},
            "bm25": {"max_hits": 16, "max_bytes": 8192, "timeout_ms": 75},
        },
        "max_graph_depth": 3,
        "max_ast_depth": 8,
        "proof_policy": {"mode": "context_only"},
        "max_bytes": 16384,
        "min_trust": "imported_unverified",
        "recency": {"max_age_seconds": 86400},
        "effective_dates": {
            "effective_from": "2026-01-01T00:00:00Z",
            "effective_until": "2026-12-31T23:59:59Z",
        },
    }
    body.update(overrides)
    return body


def test_compile_request() -> None:
    request = compile_request(_payload())
    assert request.interface == FEDERATED_RETRIEVAL_REQUEST_INTERFACE
    assert request.schema.endswith("@1")
    assert request.contract_version == CONTRACT_VERSION
    assert request.objectives == (
        "compose provenance-preserving federated retrieval",
    )
    assert "compile_request" in request.symbols
    assert request.evidence_classes == (
        EvidenceClass.REPOSITORY_TRUTH,
        EvidenceClass.IMPORTED_CLAIM,
        EvidenceClass.VERIFIED_RECEIPT,
    )
    assert request.source_domains == (
        SourceDomain.REPOSITORY_TRUTH,
        SourceDomain.IMPORTED_CLAIMS,
        SourceDomain.VERIFIED_RECEIPTS,
    )
    assert [item.engine.value for item in request.engine_budgets] == ["ast", "bm25"]
    assert all(item.max_hits > 0 and item.max_bytes > 0 for item in request.engine_budgets)
    assert request.max_graph_depth == 3
    assert request.max_ast_depth == 8
    assert request.proof_policy.imported_history_is_authority is False
    assert request.max_bytes == 16384
    assert request.min_trust is TrustClass.IMPORTED_UNVERIFIED
    assert request.recency.max_age_seconds == 86400
    assert request.effective_dates.effective_from == "2026-01-01T00:00:00Z"
    assert request.content_id.startswith("sha256:")
    with pytest.raises(FrozenInstanceError):
        request.max_bytes = 1  # type: ignore[misc]

    plan = compile_plan(request)
    assert plan.interface == FEDERATED_RETRIEVAL_PLAN_INTERFACE
    assert plan.request_content_id == request.content_id
    assert [engine.value for engine in plan.engines] == ["ast", "bm25"]
    assert plan.max_graph_depth == request.max_graph_depth
    assert plan.max_ast_depth == request.max_ast_depth

    digest = "sha256:" + ("ab" * 32)
    result = compile_result(
        {
            "hits": [
                {
                    "identity": digest,
                    "engine": "ast",
                    "evidence_class": "repository_truth",
                    "source_domain": "repository_truth",
                    "path": "ipfs_datasets_py/retrieval/agent_work_contracts.py",
                    "bytes_used": 128,
                    "trust": "locally_reverified",
                    "retrieved_at": "2026-08-22T00:00:00Z",
                    "effective_from": "2026-01-01T00:00:00Z",
                    "reason": "current repository truth",
                }
            ],
        },
        request=request,
        plan=plan,
    )
    assert result.schema.endswith("@1")
    assert result.interface == FEDERATED_RETRIEVAL_RESULT_INTERFACE
    assert result.request_content_id == request.content_id
    assert result.plan_content_id == plan.content_id
    assert result.bytes_used == 128
    assert result.hits[0].source_domain is SourceDomain.REPOSITORY_TRUTH


def test_reject_missing_budget() -> None:
    with pytest.raises(FederatedRetrievalContractError, match="missing budget"):
        compile_request(_payload(engine_budgets=None))
    missing = _payload()
    del missing["engine_budgets"]
    with pytest.raises(FederatedRetrievalContractError, match="missing budget"):
        compile_request(missing)
    with pytest.raises(FederatedRetrievalContractError, match="missing budget"):
        compile_request(_payload(engine_budgets={}))
    with pytest.raises(FederatedRetrievalContractError, match="missing budget"):
        compile_request(
            _payload(
                engines=["ast", "bm25", "vector"],
                engine_budgets={
                    "ast": {"max_hits": 8, "max_bytes": 4096, "timeout_ms": 50},
                    "bm25": {"max_hits": 16, "max_bytes": 8192, "timeout_ms": 75},
                },
            )
        )
    with pytest.raises(FederatedRetrievalContractError, match="positive integer"):
        compile_request(
            _payload(
                engine_budgets={
                    "ast": {"max_hits": 0, "max_bytes": 4096, "timeout_ms": 50},
                },
                max_bytes=4096,
            )
        )


def test_reject_unknown_domain() -> None:
    with pytest.raises(FederatedRetrievalContractError, match="unknown domain"):
        compile_request(
            _payload(source_domains=["repository_truth", "web_search"])
        )
    request = compile_request(_payload())
    digest = "sha256:" + ("cd" * 32)
    with pytest.raises(FederatedRetrievalContractError, match="unknown domain"):
        compile_result(
            {
                "hits": [
                    {
                        "identity": digest,
                        "engine": "ast",
                        "evidence_class": "repository_truth",
                        "source_domain": "web_search",
                        "path": "imported.txt",
                        "bytes_used": 32,
                        "trust": "imported_unverified",
                        "retrieved_at": "2026-08-22T00:00:00Z",
                        "effective_from": "2026-01-01T00:00:00Z",
                    }
                ],
            },
            request=request,
        )


def test_evidence_classes_and_source_domains_remain_distinct() -> None:
    assert EVIDENCE_CLASSES == {
        "repository_truth",
        "imported_claim",
        "verified_receipt",
    }
    assert SOURCE_DOMAINS >= {
        "repository_truth",
        "imported_claims",
        "verified_receipts",
    }
    assert "imported_claim" in EVIDENCE_CLASSES
    assert "imported_claims" in SOURCE_DOMAINS
    assert "imported_claim" not in SOURCE_DOMAINS
    assert "imported_claims" not in EVIDENCE_CLASSES
    assert EvidenceClass is not SourceDomain
    request = compile_request(
        _payload(
            source_domains=[
                "repository_truth",
                "imported_claims",
                "verified_receipts",
                "legal_policy",
                "model_hypotheses",
            ]
        )
    )
    assert SourceDomain.LEGAL_POLICY in request.source_domains
    assert SourceDomain.MODEL_HYPOTHESES in request.source_domains
