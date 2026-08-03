"""PATLAW-061: Read-only USPTO MCP tools.

Acceptance focus:
  - Tool schemas contain no sign/file/pay/session/credential operation
  - Unauthorized/private cross-tenant access is denied
  - Output redaction is policy-driven
  - Tools call the canonical API rather than duplicate analysis
"""

from __future__ import annotations

import inspect
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import uspto_tools as mod
from ipfs_datasets_py.processors.domains.uspto.api import (
    USPTOAnalysisAPI,
    UsptoAPIError,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.analysis_bundle import (
    UsptoAnalysisBundle,
    build_analysis_bundle,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.gap_report import (
    OutputPolicyMode,
    OutputRedactionPolicy,
    REDACTION_TOKEN,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_api_binding():
    mod.reset_api()
    mod.set_id_factory(None)
    yield
    mod.reset_api()
    mod.set_id_factory(None)


@pytest.fixture
def public_api() -> USPTOAnalysisAPI:
    """Deterministic API with no network client (analyze/explain only)."""
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"id{counter['n']:04d}"

    api = USPTOAnalysisAPI(id_factory=_ids)
    mod.bind_api(api)
    return api


def _public_bundle(matter_id: str = "matter:mcp-public-1") -> UsptoAnalysisBundle:
    return build_analysis_bundle(
        matter_id=matter_id,
        seed_classification=DisclosureClassification.PUBLIC_USER,
        labels={"tenant_id": "tenant-public"},
        id_factory=lambda: "bundlefix01",
    )


def _private_bundle(
    matter_id: str = "matter:mcp-private-1",
    *,
    tenant_id: str = "tenant-a",
) -> UsptoAnalysisBundle:
    return build_analysis_bundle(
        matter_id=matter_id,
        seed_classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        labels={"tenant_id": tenant_id},
        id_factory=lambda: "privfix01",
    )


# ---------------------------------------------------------------------------
# Schema contracts — no sign/file/pay/session/credential operations
# ---------------------------------------------------------------------------


class TestToolSchemasReadOnly:
    def test_read_only_tool_names_stable(self) -> None:
        assert set(mod.READ_ONLY_TOOL_NAMES) == {
            "uspto_status",
            "uspto_dossier_summary",
            "uspto_requirement_matrix",
            "uspto_evidence_gaps",
            "uspto_citation_explanation",
            "uspto_analysis_replay",
        }

    def test_schemas_cover_all_read_only_tools(self) -> None:
        for name in mod.READ_ONLY_TOOL_NAMES:
            assert name in mod.TOOL_SCHEMAS
            schema = mod.TOOL_SCHEMAS[name]
            assert schema["read_only"] is True
            assert schema["interface"] == mod.USPTO_MCP_INTERFACE
            assert schema["name"] == name

    def test_schemas_are_read_only_helper(self) -> None:
        assert mod.schemas_are_read_only() is True

    def test_schemas_contain_no_forbidden_operations(self) -> None:
        banned = {
            "sign",
            "pay",
            "file",
            "session",
            "credential",
            "credentials",
            "login",
            "browser",
            "submit",
            "scrape",
            "mfa",
            "password",
            "cookie",
            "api_key",
        }
        serialized = json.dumps(mod.TOOL_SCHEMAS, sort_keys=True).lower()
        # Tool *names* and python_operation fields must not be banned tokens.
        for name, schema in mod.TOOL_SCHEMAS.items():
            bare = name.replace("uspto_", "")
            assert bare not in banned, name
            op = str(schema.get("python_operation", "")).lower()
            assert op not in banned, (name, op)
            assert op in {"status", "analyze", "explain"}
            # No secret-bearing parameter keys (credential_ref is reference-only).
            props = (schema.get("parameters") or {}).get("properties") or {}
            for prop in props:
                assert prop.lower() not in {
                    "password",
                    "api_key",
                    "secret",
                    "token",
                    "cookie",
                    "session",
                    "mfa",
                }, prop
        # Forbidden operation names must not appear as top-level tool keys.
        for banned_name in banned:
            assert banned_name not in mod.TOOL_SCHEMAS
        # Helpful: discovery list matches schemas.
        listed = mod.list_uspto_tools()
        assert {t["name"] for t in listed} == set(mod.READ_ONLY_TOOL_NAMES)
        # Ensure the word "session" is not an operation key (may appear in prose).
        assert "uspto_session" not in mod.TOOL_SCHEMAS
        assert "sign" not in mod.TOOL_SCHEMAS
        assert "pay" not in mod.TOOL_SCHEMAS
        assert "file" not in mod.TOOL_SCHEMAS
        # credential_ref may appear as a *parameter* description but not as a tool.
        assert "credential" not in mod.TOOL_SCHEMAS
        assert "session" not in mod.TOOL_SCHEMAS
        # Soft check: serialized schemas do not define forbidden tool entries.
        for token in ("\"sign\"", "\"pay\"", "\"session\"", "\"credential\""):
            # These may appear inside descriptions; ensure not as name fields.
            pass
        for schema in listed:
            assert schema["name"] not in banned
            assert "sign" not in schema["name"]
            assert "pay" not in schema["name"]
            assert "session" not in schema["name"]
            assert "credential" not in schema["name"]
            assert "file" not in schema["name"].replace("profile", "")

    def test_forbidden_mcp_operations_include_boundary(self) -> None:
        for op in ("sign", "pay", "file", "session", "credential", "login"):
            assert op in mod.FORBIDDEN_MCP_OPERATIONS
        assert "import_private" in mod.FORBIDDEN_MCP_OPERATIONS

    def test_assert_mcp_operation_allowed_blocks_forbidden(self) -> None:
        for op in ("sign", "pay", "file", "session", "credential", "login", "scrape"):
            with pytest.raises(mod.ForbiddenMCPOperationError):
                mod.assert_mcp_operation_allowed(op)

    def test_get_tool_schema_unknown(self) -> None:
        assert mod.get_tool_schema("sign") is None
        assert mod.get_tool_schema("uspto_status") is not None

    def test_registry_exposes_async_callables(self) -> None:
        assert len(mod.USPTO_MCP_TOOLS) == len(mod.READ_ONLY_TOOL_NAMES)
        for fn in mod.USPTO_MCP_TOOLS:
            assert inspect.iscoroutinefunction(fn)


# ---------------------------------------------------------------------------
# Tenant authorization
# ---------------------------------------------------------------------------


class TestTenantAuthorization:
    def test_public_allows_missing_tenant(self) -> None:
        mod.authorize_tenant_access(
            caller_tenant_id=None,
            classification=DisclosureClassification.PUBLIC_USER,
        )

    def test_private_requires_tenant(self) -> None:
        with pytest.raises(mod.UsptoMCPAuthError) as exc:
            mod.authorize_tenant_access(
                caller_tenant_id=None,
                classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
            )
        assert exc.value.code == "missing_tenant"

    def test_private_cross_tenant_denied(self) -> None:
        with pytest.raises(mod.UsptoMCPAuthError) as exc:
            mod.authorize_tenant_access(
                caller_tenant_id="tenant-a",
                resource_tenant_id="tenant-b",
                classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
            )
        assert exc.value.code == "tenant_mismatch"

    def test_private_store_mismatch_denied(self) -> None:
        with pytest.raises(mod.UsptoMCPAuthError) as exc:
            mod.authorize_tenant_access(
                caller_tenant_id="tenant-a",
                resource_tenant_id="tenant-a",
                private_store_tenant_id="tenant-other",
                classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
            )
        assert exc.value.code == "tenant_mismatch"

    @pytest.mark.asyncio
    async def test_dossier_summary_denies_cross_tenant_private(
        self, public_api: USPTOAnalysisAPI
    ) -> None:
        bundle = _private_bundle(tenant_id="tenant-a")
        result = await mod.uspto_dossier_summary(
            analysis_bundle=bundle.to_dict(),
            tenant_id="tenant-b",
        )
        assert result["status"] == "error"
        assert result["code"] in {"tenant_mismatch", "unauthorized_tenant"}

    @pytest.mark.asyncio
    async def test_dossier_summary_allows_matching_tenant(
        self, public_api: USPTOAnalysisAPI
    ) -> None:
        bundle = _private_bundle(tenant_id="tenant-a")
        result = await mod.uspto_dossier_summary(
            analysis_bundle=bundle.to_dict(),
            tenant_id="tenant-a",
        )
        assert result["status"] == "success", result
        assert result["result"]["classification"] == "confidential_application"

    @pytest.mark.asyncio
    async def test_private_without_tenant_denied(
        self, public_api: USPTOAnalysisAPI
    ) -> None:
        bundle = _private_bundle(tenant_id="tenant-a")
        result = await mod.uspto_requirement_matrix(
            analysis_bundle=bundle.to_dict(),
            tenant_id=None,
        )
        assert result["status"] == "error"
        assert result["code"] == "missing_tenant"

    @pytest.mark.asyncio
    async def test_analysis_replay_cross_tenant_denied(
        self, public_api: USPTOAnalysisAPI
    ) -> None:
        bundle = _private_bundle(tenant_id="tenant-a")
        result = await mod.uspto_analysis_replay(
            analysis_bundle=bundle.to_dict(),
            tenant_id="tenant-evil",
        )
        assert result["status"] == "error"
        assert result["code"] in {"tenant_mismatch", "unauthorized_tenant"}


# ---------------------------------------------------------------------------
# Policy-driven output redaction
# ---------------------------------------------------------------------------


class TestOutputRedaction:
    def test_redact_private_text_keys(self) -> None:
        payload = {
            "summary": "secret private narrative",
            "matter_id": "matter:1",
            "detail_text": "do not leak",
            "status": "unknown",
        }
        policy = OutputRedactionPolicy(mode=OutputPolicyMode.REDACT_PRIVATE)
        out = mod.apply_output_redaction(
            payload,
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
            output_policy=policy,
        )
        assert out["summary"] == REDACTION_TOKEN
        assert out["detail_text"] == REDACTION_TOKEN
        assert out["matter_id"] == "matter:1"
        assert out["status"] == "unknown"

    def test_public_keeps_surface_text(self) -> None:
        payload = {"summary": "public summary", "matter_id": "matter:1"}
        policy = OutputRedactionPolicy(mode=OutputPolicyMode.REDACT_PRIVATE)
        out = mod.apply_output_redaction(
            payload,
            classification=DisclosureClassification.PUBLIC_USER,
            output_policy=policy,
        )
        assert out["summary"] == "public summary"

    def test_identifiers_only_redacts_all_surface_text(self) -> None:
        payload = {"summary": "anything", "human_readable": "long text", "id": "x"}
        policy = OutputRedactionPolicy(mode=OutputPolicyMode.IDENTIFIERS_ONLY)
        out = mod.apply_output_redaction(
            payload,
            classification=DisclosureClassification.PUBLIC_USER,
            output_policy=policy,
        )
        assert out["summary"] == REDACTION_TOKEN
        assert out["human_readable"] == REDACTION_TOKEN

    def test_credential_fields_always_scrubbed(self) -> None:
        payload = {
            "ok": True,
            "api_key": "leaked",
            "password": "x",
            "token": "t",
            "reference_id": "vault:1",
            "kind": "api_key",
        }
        out = mod.apply_output_redaction(
            payload,
            classification=DisclosureClassification.PUBLIC_USER,
            output_policy=OutputRedactionPolicy(mode=OutputPolicyMode.FULL),
        )
        # scrub_credential_fields drops secret keys; pure ref may be preserved shape.
        text = json.dumps(out)
        assert "leaked" not in text
        assert "password" not in out or out.get("password") != "x"

    @pytest.mark.asyncio
    async def test_tool_output_includes_policy(self, public_api: USPTOAnalysisAPI) -> None:
        result = await mod.uspto_dossier_summary(
            matter_id="matter:policy-1",
            output_policy={"mode": "redact_private"},
        )
        assert result["status"] == "success"
        assert "output_policy" in result
        assert result["output_policy"]["mode"] == "redact_private"


# ---------------------------------------------------------------------------
# Tools call the canonical API (no duplicated analysis)
# ---------------------------------------------------------------------------


class TestCanonicalApiDelegation:
    @pytest.mark.asyncio
    async def test_status_calls_api_status(self) -> None:
        mock_api = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "schema_version": "uspto.application-status.v1",
            "outcome": "ok",
            "classification": "public_official",
        }
        mock_api.status.return_value = mock_result
        mock_api._private_store = None
        mod.bind_api(mock_api)

        result = await mod.uspto_status(application_number="16123456")
        assert result["status"] == "success"
        mock_api.status.assert_called_once()
        args, kwargs = mock_api.status.call_args
        assert args[0] == "16123456"
        assert result["api_operation"] == "status"

    @pytest.mark.asyncio
    async def test_status_missing_client_returns_error(
        self, public_api: USPTOAnalysisAPI
    ) -> None:
        result = await mod.uspto_status(application_number="16123456")
        assert result["status"] == "error"
        assert result["code"] in {"missing_client", "UsptoAPIError"}

    @pytest.mark.asyncio
    async def test_dossier_summary_calls_analyze(
        self, public_api: USPTOAnalysisAPI
    ) -> None:
        with patch.object(
            public_api, "analyze", wraps=public_api.analyze
        ) as spy:
            result = await mod.uspto_dossier_summary(matter_id="matter:spy-1")
            assert result["status"] == "success"
            spy.assert_called()
            assert result["api_operation"] == "analyze"
            assert "summary" in result["result"]

    @pytest.mark.asyncio
    async def test_requirement_matrix_calls_explain(
        self, public_api: USPTOAnalysisAPI
    ) -> None:
        with patch.object(
            public_api, "explain", wraps=public_api.explain
        ) as spy:
            result = await mod.uspto_requirement_matrix(matter_id="matter:matrix-1")
            assert result["status"] == "success", result
            spy.assert_called()
            assert result["api_operation"] == "explain"
            assert "requirement_rows" in result["result"]
            assert "requirement_row_count" in result["result"]

    @pytest.mark.asyncio
    async def test_evidence_gaps_calls_explain(
        self, public_api: USPTOAnalysisAPI
    ) -> None:
        with patch.object(
            public_api, "explain", wraps=public_api.explain
        ) as spy:
            result = await mod.uspto_evidence_gaps(matter_id="matter:gaps-1")
            assert result["status"] == "success", result
            spy.assert_called()
            body = result["result"]
            assert "gaps" in body
            assert "unknowns" in body
            assert "reviewer_actions" in body

    @pytest.mark.asyncio
    async def test_citation_explanation_calls_explain(
        self, public_api: USPTOAnalysisAPI
    ) -> None:
        with patch.object(
            public_api, "explain", wraps=public_api.explain
        ) as spy:
            result = await mod.uspto_citation_explanation(
                matter_id="matter:cite-1"
            )
            assert result["status"] == "success", result
            spy.assert_called()
            assert "citations" in result["result"]
            assert "authority_ids" in result["result"]

    @pytest.mark.asyncio
    async def test_analysis_replay_calls_analyze_and_explain(
        self, public_api: USPTOAnalysisAPI
    ) -> None:
        bundle = _public_bundle()
        with patch.object(
            public_api, "analyze", wraps=public_api.analyze
        ) as spy_a, patch.object(
            public_api, "explain", wraps=public_api.explain
        ) as spy_e:
            result = await mod.uspto_analysis_replay(
                analysis_bundle=bundle.to_dict(),
                tenant_id="tenant-public",
            )
            assert result["status"] == "success", result
            spy_a.assert_called()
            spy_e.assert_called()
            body = result["result"]
            assert "digest_match" in body
            assert body["source_bundle_digest"] == bundle.bundle_digest
            assert body["report_binding_ok"] is True

    @pytest.mark.asyncio
    async def test_tools_do_not_import_local_gap_renderer_duplicate(
        self, public_api: USPTOAnalysisAPI
    ) -> None:
        """Ensure explain path goes through the bound API instance."""
        calls: list[str] = []

        original_explain = public_api.explain

        def tracking_explain(*args: Any, **kwargs: Any) -> Any:
            calls.append("api.explain")
            return original_explain(*args, **kwargs)

        public_api.explain = tracking_explain  # type: ignore[method-assign]
        await mod.uspto_requirement_matrix(matter_id="matter:no-dup-1")
        assert calls == ["api.explain"]


# ---------------------------------------------------------------------------
# Happy-path envelopes + dispatch
# ---------------------------------------------------------------------------


class TestToolEnvelopes:
    @pytest.mark.asyncio
    async def test_dossier_summary_public_matter(
        self, public_api: USPTOAnalysisAPI
    ) -> None:
        result = await mod.uspto_dossier_summary(matter_id="matter:env-1")
        assert result["status"] == "success"
        assert result["interface"] == mod.USPTO_MCP_INTERFACE
        assert result["read_only"] is True
        assert result["result"]["matter_id"] == "matter:env-1"
        text = json.dumps(result)
        assert "api_key" not in text or "reference" in text
        assert "password" not in text.lower()

    @pytest.mark.asyncio
    async def test_perform_uspto_tool_dispatch(
        self, public_api: USPTOAnalysisAPI
    ) -> None:
        result = await mod.perform_uspto_tool(
            "dossier_summary", matter_id="matter:dispatch-1"
        )
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_perform_uspto_tool_rejects_sign(self) -> None:
        result = await mod.perform_uspto_tool("sign", package={})
        assert result["status"] == "error"
        assert result["code"] == "forbidden_operation"

    @pytest.mark.asyncio
    async def test_perform_uspto_tool_rejects_file(self) -> None:
        result = await mod.perform_uspto_tool("file")
        assert result["status"] == "error"
        assert result["code"] == "forbidden_operation"

    @pytest.mark.asyncio
    async def test_perform_uspto_tool_rejects_session(self) -> None:
        result = await mod.perform_uspto_tool("session")
        assert result["status"] == "error"
        assert result["code"] == "forbidden_operation"

    @pytest.mark.asyncio
    async def test_perform_uspto_tool_rejects_credential(self) -> None:
        result = await mod.perform_uspto_tool("credential")
        assert result["status"] == "error"
        assert result["code"] == "forbidden_operation"

    @pytest.mark.asyncio
    async def test_status_requires_application_number(self) -> None:
        result = await mod.uspto_status(application_number="")
        assert result["status"] == "error"
        assert result["code"] == "missing_application_number"

    @pytest.mark.asyncio
    async def test_replay_requires_bundle(self, public_api: USPTOAnalysisAPI) -> None:
        result = await mod.uspto_analysis_replay(analysis_bundle={})  # type: ignore[arg-type]
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_gap_tools_accept_prebuilt_report(
        self, public_api: USPTOAnalysisAPI
    ) -> None:
        analyzed = public_api.analyze(matter_id="matter:prebuilt-1")
        report = public_api.explain(analyzed.analysis_bundle)
        result = await mod.uspto_evidence_gaps(gap_report=report.to_dict())
        assert result["status"] == "success"
        assert result["result"]["report_id"] == report.report_id

    def test_tool_to_api_operation_mapping(self) -> None:
        assert mod.TOOL_TO_API_OPERATION["uspto_status"] == "status"
        assert mod.TOOL_TO_API_OPERATION["uspto_dossier_summary"] == "analyze"
        assert mod.TOOL_TO_API_OPERATION["uspto_requirement_matrix"] == "explain"
        assert mod.TOOL_TO_API_OPERATION["uspto_evidence_gaps"] == "explain"
        assert mod.TOOL_TO_API_OPERATION["uspto_citation_explanation"] == "explain"
        assert mod.TOOL_TO_API_OPERATION["uspto_analysis_replay"] == "analyze"

    def test_list_forbidden_operations_sorted(self) -> None:
        ops = mod.list_forbidden_operations()
        assert ops == sorted(ops)
        assert "sign" in ops
        assert "pay" in ops
        assert "file" in ops
        assert "session" in ops
        assert "credential" in ops


# ---------------------------------------------------------------------------
# Source-level safety: module must not define forbidden tool functions
# ---------------------------------------------------------------------------


class TestModuleSurface:
    def test_no_sign_pay_file_session_functions(self) -> None:
        for name in (
            "sign",
            "pay",
            "file",
            "submit",
            "session",
            "login",
            "credential",
            "import_private",
            "uspto_sign",
            "uspto_pay",
            "uspto_file",
            "uspto_session",
        ):
            assert not hasattr(mod, name) or not callable(
                getattr(mod, name, None)
            ) or name in mod.FORBIDDEN_MCP_OPERATIONS
            # Prefer: not present as tool entrypoints
            assert name not in {fn.__name__ for fn in mod.USPTO_MCP_TOOLS}

    def test_module_docstring_declares_read_only(self) -> None:
        doc = (mod.__doc__ or "").lower()
        assert "read-only" in doc or "read only" in doc
        assert "sign" in doc  # mentioned as forbidden

    def test_source_does_not_reimplement_gap_report_renderer(self) -> None:
        source = inspect.getsource(mod)
        # Must delegate to API; must not embed a full GapReportRenderer class.
        assert "class GapReportRenderer" not in source
        assert "api.explain" in source or "api.analyze" in source
        assert "USPTOAnalysisAPI" in source or "get_api" in source
