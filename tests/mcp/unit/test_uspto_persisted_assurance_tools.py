"""PATLAW-141: Read-only MCP persisted assurance queries.

Acceptance focus:
  - Unauthorized tenants receive no existence oracle
  - MCP does not trigger filing/payment or implicit live sync
  - Queries return dossier summaries / findings / provenance only from store
  - Private body content is never embedded in tool results
"""

from __future__ import annotations

import inspect
import json
from typing import Any

import pytest

from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import uspto_tools as mod


@pytest.fixture(autouse=True)
def _reset_bindings():
    mod.reset_api()
    mod.reset_assurance_store()
    mod.set_id_factory(None)
    yield
    mod.reset_api()
    mod.reset_assurance_store()
    mod.set_id_factory(None)


def _seed_record(
    store: mod.InMemoryPersistedAssuranceStore,
    *,
    tenant_id: str = "tenant-a",
    matter_id: str = "matter:priv-1",
    assurance_id: str = "assurance:1",
    dossier_id: str = "dossier:abc",
    **extra: Any,
) -> dict[str, Any]:
    record = {
        "tenant_id": tenant_id,
        "matter_id": matter_id,
        "assurance_id": assurance_id,
        "dossier_id": dossier_id,
        "classification": "confidential_application",
        "disposition": "completed",
        "review_state": "review_only",
        "bundle_digest": "a" * 64,
        "parser_digest": "b" * 64,
        "content_digest": "c" * 64,
        "reason_codes": ["ok"],
        "opaque_matter_ref": "opaque:seeded-ref-1",
        "dossier_link": f"protected://dossier/{dossier_id}",
        "summary": {
            "status": "ready",
            "text": "SHOULD_NOT_APPEAR",
            "body": "private body",
        },
        "findings": [
            {
                "item_id": "f1",
                "kind": "missing",
                "code": "IDS_MISSING",
                "text": "secret finding narrative",
                "body": "nope",
            },
            {
                "item_id": "f2",
                "kind": "satisfied",
                "code": "CLAIMS_OK",
            },
        ],
        "provenance": {
            "stage": "dossier",
            "receipt_id": "rcpt:1",
            "content": "private provenance blob",
        },
        "stage_input_digests": {"dossier": "d" * 64},
        "stage_output_digests": {"dossier": "e" * 64},
        "committed_stages": ["preflight", "dossier"],
        "is_review_only": True,
    }
    record.update(extra)
    return store.put(record)


# ---------------------------------------------------------------------------
# Schema / surface contracts
# ---------------------------------------------------------------------------


class TestPersistedAssuranceSurface:
    def test_tool_names_stable(self) -> None:
        assert set(mod.PERSISTED_ASSURANCE_TOOL_NAMES) == {
            "uspto_persisted_assurance_summary",
            "uspto_persisted_assurance_findings",
            "uspto_persisted_assurance_provenance",
        }

    def test_schemas_are_read_only_and_non_mutating(self) -> None:
        for name in mod.PERSISTED_ASSURANCE_TOOL_NAMES:
            schema = mod.PERSISTED_ASSURANCE_TOOL_SCHEMAS[name]
            assert schema["read_only"] is True
            assert schema["triggers_live_sync"] is False
            assert schema["triggers_filing_or_payment"] is False
            assert schema["python_operation"] == "persisted_read"
            assert schema["name"] == name

    def test_v1_read_only_surface_unchanged(self) -> None:
        # PATLAW-061 contract must remain stable.
        assert set(mod.READ_ONLY_TOOL_NAMES) == {
            "uspto_status",
            "uspto_dossier_summary",
            "uspto_requirement_matrix",
            "uspto_evidence_gaps",
            "uspto_citation_explanation",
            "uspto_analysis_replay",
        }
        assert len(mod.USPTO_MCP_TOOLS) == len(mod.READ_ONLY_TOOL_NAMES)

    def test_list_helpers(self) -> None:
        listed = mod.list_persisted_assurance_tools()
        assert {t["name"] for t in listed} == set(mod.PERSISTED_ASSURANCE_TOOL_NAMES)
        all_tools = mod.list_all_uspto_tools()
        names = {t["name"] for t in all_tools}
        assert set(mod.READ_ONLY_TOOL_NAMES).issubset(names)
        assert set(mod.PERSISTED_ASSURANCE_TOOL_NAMES).issubset(names)

    def test_forbidden_includes_live_workflow_ops(self) -> None:
        for op in (
            "sign",
            "pay",
            "file",
            "submission_assurance",
            "assure",
            "sync_public",
            "live_sync",
        ):
            assert op in mod.FORBIDDEN_MCP_OPERATIONS
            with pytest.raises(mod.ForbiddenMCPOperationError):
                mod.assert_mcp_operation_allowed(op)

    def test_registry_functions_are_async(self) -> None:
        for fn in mod.PERSISTED_ASSURANCE_MCP_TOOLS:
            assert inspect.iscoroutinefunction(fn)


# ---------------------------------------------------------------------------
# Existence oracle + tenant isolation
# ---------------------------------------------------------------------------


class TestNoExistenceOracle:
    @pytest.mark.asyncio
    async def test_wrong_tenant_denied_same_as_missing_shape(self) -> None:
        store = mod.InMemoryPersistedAssuranceStore()
        mod.bind_assurance_store(store)
        _seed_record(store, tenant_id="tenant-a", matter_id="matter:secret")

        foreign = await mod.uspto_persisted_assurance_summary(
            tenant_id="tenant-evil",
            matter_id="matter:secret",
        )
        missing = await mod.uspto_persisted_assurance_summary(
            tenant_id="tenant-evil",
            matter_id="matter:does-not-exist",
        )
        # Unauthorized callers must not distinguish existence.
        # foreign → access_denied; missing-for-wrong-tenant may be not_found OR
        # access_denied; foreign must never reveal the private matter exists via
        # a success payload or distinct success-shaped leak.
        assert foreign["status"] == "error"
        assert foreign["code"] == mod.ACCESS_DENIED_CODE
        assert "matter:secret" not in foreign.get("error", "")
        assert missing["status"] == "error"
        # Missing foreign key: either not_found (own tenant scope) or access_denied.
        assert missing["code"] in {mod.ACCESS_DENIED_CODE, "not_found"}

    @pytest.mark.asyncio
    async def test_missing_tenant_denied_even_when_record_exists(self) -> None:
        store = mod.InMemoryPersistedAssuranceStore()
        mod.bind_assurance_store(store)
        _seed_record(store, tenant_id="tenant-a")

        result = await mod.uspto_persisted_assurance_summary(
            tenant_id=None,
            matter_id="matter:priv-1",
        )
        assert result["status"] == "error"
        assert result["code"] == mod.ACCESS_DENIED_CODE

    @pytest.mark.asyncio
    async def test_authorized_tenant_not_found_is_explicit(self) -> None:
        store = mod.InMemoryPersistedAssuranceStore()
        mod.bind_assurance_store(store)
        result = await mod.uspto_persisted_assurance_summary(
            tenant_id="tenant-a",
            matter_id="matter:absent",
        )
        assert result["status"] == "error"
        assert result["code"] == "not_found"

    @pytest.mark.asyncio
    async def test_authorized_tenant_can_read(self) -> None:
        store = mod.InMemoryPersistedAssuranceStore()
        mod.bind_assurance_store(store)
        _seed_record(store, tenant_id="tenant-a", matter_id="matter:ok")

        result = await mod.uspto_persisted_assurance_summary(
            tenant_id="tenant-a",
            matter_id="matter:ok",
        )
        assert result["status"] == "success", result
        assert result["result"]["matter_id"] == "matter:ok"
        assert result["result"]["tenant_id"] == "tenant-a"
        assert result["read_only"] is True
        assert result["api_operation"] == "persisted_read"


# ---------------------------------------------------------------------------
# No live sync / filing / payment
# ---------------------------------------------------------------------------


class TestNoLiveSideEffects:
    @pytest.mark.asyncio
    async def test_queries_do_not_increment_side_effect_counters(self) -> None:
        store = mod.InMemoryPersistedAssuranceStore()
        mod.bind_assurance_store(store)
        _seed_record(store)

        assert store.live_sync_calls == 0
        assert store.filing_calls == 0
        assert store.payment_calls == 0
        assert store.assurance_run_calls == 0

        await mod.uspto_persisted_assurance_summary(
            tenant_id="tenant-a", matter_id="matter:priv-1"
        )
        await mod.uspto_persisted_assurance_findings(
            tenant_id="tenant-a", matter_id="matter:priv-1"
        )
        await mod.uspto_persisted_assurance_provenance(
            tenant_id="tenant-a", matter_id="matter:priv-1"
        )

        assert store.live_sync_calls == 0
        assert store.filing_calls == 0
        assert store.payment_calls == 0
        assert store.assurance_run_calls == 0

    @pytest.mark.asyncio
    async def test_result_flags_declare_no_live_triggers(self) -> None:
        store = mod.InMemoryPersistedAssuranceStore()
        mod.bind_assurance_store(store)
        _seed_record(store)
        result = await mod.uspto_persisted_assurance_summary(
            tenant_id="tenant-a", matter_id="matter:priv-1"
        )
        assert result["status"] == "success"
        assert result["result"]["live_sync_triggered"] is False
        assert result["result"]["filing_or_payment_triggered"] is False

    @pytest.mark.asyncio
    async def test_perform_dispatch_refuses_submission_assurance(self) -> None:
        out = await mod.perform_uspto_tool("submission_assurance", tenant_id="t")
        assert out["status"] == "error"
        assert out["code"] == "forbidden_operation"

    @pytest.mark.asyncio
    async def test_perform_dispatch_refuses_sync_public(self) -> None:
        out = await mod.perform_uspto_tool("sync_public")
        assert out["status"] == "error"
        assert out["code"] == "forbidden_operation"


# ---------------------------------------------------------------------------
# Projection content safety
# ---------------------------------------------------------------------------


class TestProjectionSafety:
    @pytest.mark.asyncio
    async def test_summary_strips_body_text(self) -> None:
        store = mod.InMemoryPersistedAssuranceStore()
        mod.bind_assurance_store(store)
        _seed_record(store)
        result = await mod.uspto_persisted_assurance_summary(
            tenant_id="tenant-a", matter_id="matter:priv-1"
        )
        assert result["status"] == "success"
        blob = json.dumps(result)
        assert "SHOULD_NOT_APPEAR" not in blob
        assert "private body" not in blob
        assert result["result"]["dossier_link"] == "protected://dossier/dossier:abc"
        assert result["result"]["bundle_digest"] == "a" * 64

    @pytest.mark.asyncio
    async def test_findings_are_codes_only(self) -> None:
        store = mod.InMemoryPersistedAssuranceStore()
        mod.bind_assurance_store(store)
        _seed_record(store)
        result = await mod.uspto_persisted_assurance_findings(
            tenant_id="tenant-a", assurance_id="assurance:1"
        )
        assert result["status"] == "success"
        findings = result["result"]["findings"]
        assert result["result"]["finding_count"] == 2
        codes = {f["code"] for f in findings}
        assert codes == {"IDS_MISSING", "CLAIMS_OK"}
        blob = json.dumps(result)
        assert "secret finding narrative" not in blob
        assert "nope" not in blob

    @pytest.mark.asyncio
    async def test_provenance_links_protected_dossier(self) -> None:
        store = mod.InMemoryPersistedAssuranceStore()
        mod.bind_assurance_store(store)
        _seed_record(store)
        result = await mod.uspto_persisted_assurance_provenance(
            tenant_id="tenant-a", dossier_id="dossier:abc"
        )
        assert result["status"] == "success"
        assert result["result"]["dossier_link"].startswith("protected://dossier/")
        assert "private provenance blob" not in json.dumps(result)
        assert result["result"]["stage_input_digests"]["dossier"] == "d" * 64

    @pytest.mark.asyncio
    async def test_missing_lookup_key(self) -> None:
        result = await mod.uspto_persisted_assurance_summary(tenant_id="tenant-a")
        assert result["status"] == "error"
        assert result["code"] == "missing_lookup_key"
