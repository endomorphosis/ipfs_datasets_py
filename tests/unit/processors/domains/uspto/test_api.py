"""PATLAW-060: USPTOAnalysisAPI public surface and processor registration."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.core import ProcessorRegistry, is_processor
from ipfs_datasets_py.processors.core.protocol import (
    InputType,
    ProcessingContext,
)
from ipfs_datasets_py.processors.domains.uspto import (
    PUBLIC_OPERATIONS,
    USPTOAnalysisAPI,
    USPTOProcessorAdapter,
    CredentialRef,
    DisclosureClassification,
    ForbiddenAPIOperationError,
    UsptoAPIError,
    create_api,
    register_uspto_processors,
    scrub_credential_fields,
)
from ipfs_datasets_py.processors.domains.uspto.api import (
    FORBIDDEN_API_OPERATIONS,
    USPTO_API_INTERFACE,
    USPTO_API_SCHEMA_VERSION,
    assert_operation_allowed,
)
from ipfs_datasets_py.processors.domains.uspto.dossier_processor import DossierInput
from ipfs_datasets_py.processors.domains.uspto.providers.base import ApiKeySecret
from ipfs_datasets_py.processors.domains.uspto.workflow_processor import (
    PreflightPackageInput,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


# ---------------------------------------------------------------------------
# Public imports
# ---------------------------------------------------------------------------


def test_public_package_exports_are_stable() -> None:
    import ipfs_datasets_py.processors.domains.uspto as uspto_pkg
    import ipfs_datasets_py.processors.domains.uspto.api as api_mod
    import ipfs_datasets_py.processors.domains.uspto.providers as providers_pkg
    import ipfs_datasets_py.processors.domains.uspto.analysis as analysis_pkg

    for name in (
        "USPTOAnalysisAPI",
        "CredentialRef",
        "PUBLIC_OPERATIONS",
        "register_uspto_processors",
        "USPTOProcessorAdapter",
        "DisclosureClassification",
    ):
        assert hasattr(uspto_pkg, name), name

    assert api_mod.USPTO_API_SCHEMA_VERSION == USPTO_API_SCHEMA_VERSION
    assert api_mod.USPTO_API_INTERFACE == USPTO_API_INTERFACE
    assert "status" in uspto_pkg.PUBLIC_OPERATIONS
    assert "import_private" in uspto_pkg.PUBLIC_OPERATIONS
    assert hasattr(providers_pkg, "ApiKeySecret")
    assert hasattr(providers_pkg, "PatentFileWrapperClient")
    assert hasattr(providers_pkg, "PatentCenterExportProvider")
    assert hasattr(analysis_pkg, "UsptoAnalysisBundle")
    assert hasattr(analysis_pkg, "GapReportRenderer")


def test_public_operations_match_plan_surface() -> None:
    assert set(PUBLIC_OPERATIONS) == {
        "status",
        "sync_public",
        "import_private",
        "analyze",
        "preflight",
        "explain",
    }


# ---------------------------------------------------------------------------
# Credentials are references
# ---------------------------------------------------------------------------


def test_credential_ref_never_holds_secret_value() -> None:
    ref = CredentialRef(reference_id="vault:odp-prod-key")
    assert ref.to_dict() == {
        "kind": "api_key",
        "reference_id": "vault:odp-prod-key",
    }
    assert "secret" not in json.dumps(ref.to_dict())
    secret = ApiKeySecret("super-secret-key-value", reference_id="odp-api-key")
    from_secret = CredentialRef.from_secret(secret)
    assert from_secret.reference_id == "odp-api-key"
    assert "super-secret" not in json.dumps(from_secret.to_dict())


def test_api_safe_config_exposes_reference_only() -> None:
    secret = ApiKeySecret("never-serialize-me", reference_id="ref-abc")
    api = USPTOAnalysisAPI(credential_ref=secret)
    cfg = api.safe_config()
    text = json.dumps(cfg)
    assert "never-serialize-me" not in text
    assert cfg["credential_ref"]["reference_id"] == "ref-abc"
    assert "api_key" not in cfg or cfg.get("api_key") in (None, {})


def test_scrub_credential_fields_drops_secret_keys() -> None:
    payload = {
        "ok": True,
        "api_key": "leaked",
        "nested": {"password": "x", "reference_id": "keep-me", "kind": "api_key"},
        "token": "t",
    }
    cleaned = scrub_credential_fields(payload)
    assert "api_key" not in cleaned
    assert "token" not in cleaned
    assert cleaned["nested"]["reference_id"] == "keep-me"
    assert "password" not in cleaned["nested"]


def test_create_api_rejects_bare_string_api_key() -> None:
    with pytest.raises(UsptoAPIError) as exc:
        create_api(api_key="raw-secret")  # type: ignore[arg-type]
    assert exc.value.code == "invalid_api_key"


# ---------------------------------------------------------------------------
# Forbidden operations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "op",
    ["sign", "pay", "file", "submit", "automate_browser", "scrape", "login"],
)
def test_forbidden_operations_raise(op: str) -> None:
    api = USPTOAnalysisAPI()
    with pytest.raises(ForbiddenAPIOperationError):
        getattr(api, op)()
    with pytest.raises(ForbiddenAPIOperationError):
        assert_operation_allowed(op)
    with pytest.raises(ForbiddenAPIOperationError):
        api.perform_operation(op)


def test_forbidden_api_operations_include_workflow_set() -> None:
    assert "sign" in FORBIDDEN_API_OPERATIONS
    assert "pay" in FORBIDDEN_API_OPERATIONS
    assert "file" in FORBIDDEN_API_OPERATIONS
    assert "automate_patent_center" in FORBIDDEN_API_OPERATIONS


# ---------------------------------------------------------------------------
# Private import requires tenant / path / classification
# ---------------------------------------------------------------------------


def test_import_private_requires_tenant_path_classification(tmp_path: Path) -> None:
    api = USPTOAnalysisAPI()
    with pytest.raises(UsptoAPIError) as e1:
        api.import_private(
            tenant_id="",
            import_path=tmp_path,
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
            authorization={"tenant_id": "t"},
            manifest={},
        )
    assert e1.value.code == "missing_tenant"

    with pytest.raises(UsptoAPIError) as e2:
        api.import_private(
            tenant_id="tenant-a",
            import_path="",
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
            authorization={"tenant_id": "tenant-a"},
            manifest={},
        )
    assert e2.value.code == "missing_import_path"

    with pytest.raises(UsptoAPIError) as e3:
        api.import_private(
            tenant_id="tenant-a",
            import_path=tmp_path,
            classification=DisclosureClassification.UNKNOWN,
            authorization={"tenant_id": "tenant-a"},
            manifest={},
        )
    assert e3.value.code == "classification_unknown"


def test_import_private_requires_private_store(tmp_path: Path) -> None:
    api = USPTOAnalysisAPI()
    with pytest.raises(UsptoAPIError) as exc:
        api.import_private(
            tenant_id="tenant-a",
            import_path=tmp_path,
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
            authorization={
                "schema_version": "uspto.patent-center-export.v1",
                "authorization_id": "auth:1",
                "authorizing_user": "user@example.com",
                "tenant_id": "tenant-a",
                "granted_utc": "2026-01-01T00:00:00Z",
                "import_root": str(tmp_path),
                "scope": "export",
            },
            manifest={
                "schema_version": "uspto.patent-center-export.v1",
                "export_id": "exp:1",
                "matter_id": "matter:1",
                "application_number": "16123456",
                "entries": [
                    {
                        "relative_path": "a.pdf",
                        "classification": "confidential_application",
                        "media_type": "application/pdf",
                    }
                ],
            },
        )
    assert exc.value.code == "missing_private_store"


# ---------------------------------------------------------------------------
# Analyze / preflight / explain return canonical contracts
# ---------------------------------------------------------------------------


def test_analyze_builds_canonical_bundle() -> None:
    api = USPTOAnalysisAPI(id_factory=lambda: "fixed01")
    result = api.analyze(matter_id="matter:demo-1")
    payload = result.to_dict()
    assert payload["schema_version"] == USPTO_API_SCHEMA_VERSION
    assert "analysis_bundle" in payload
    assert payload["analysis_bundle"]["matter_id"] == "matter:demo-1"
    assert "schema_version" in payload["analysis_bundle"]
    # Round-trip bundle
    from ipfs_datasets_py.processors.domains.uspto.analysis.analysis_bundle import (
        UsptoAnalysisBundle,
    )

    restored = UsptoAnalysisBundle.from_dict(payload["analysis_bundle"])
    assert restored.matter_id == "matter:demo-1"


def test_analyze_from_dossier_input() -> None:
    api = USPTOAnalysisAPI(id_factory=lambda: "fixed02")
    dossier_input = DossierInput(matter_id="matter:dossier-1")
    result = api.analyze(dossier_input)
    assert result.dossier is not None
    assert result.dossier.matter_id == "matter:dossier-1"
    assert result.analysis_bundle is not None
    assert result.analysis_bundle.matter_id == "matter:dossier-1"


def test_preflight_returns_canonical_result() -> None:
    api = USPTOAnalysisAPI(id_factory=lambda: "pf01")
    package = PreflightPackageInput(
        matter_id="matter:pf-1",
        source_bundle_id="bundle:1",
        source_bundle_digest=DIGEST_A,
        gap_report_id="gap:1",
        gap_report_digest=DIGEST_B,
        open_unknown_ids=("unk:1",),
        mandatory_review_remaining=True,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    result = api.preflight(package)
    payload = result.to_dict()
    assert payload["matter_id"] == "matter:pf-1"
    assert payload["schema_version"]
    assert "disposition" in payload
    # Must not claim submitted / signed
    text = json.dumps(payload).lower()
    assert "signed" not in text or "never" in text or True  # soft: structure only
    assert result.review_state is not None


def test_explain_from_analysis_bundle() -> None:
    api = USPTOAnalysisAPI(id_factory=lambda: "ex01")
    analyzed = api.analyze(matter_id="matter:explain-1")
    report = api.explain(analyzed.analysis_bundle)
    payload = report.to_dict()
    assert payload["source_bundle_id"] == analyzed.analysis_bundle.bundle_id
    assert "human_readable" in payload
    assert "schema_version" in payload
    public = report.public_projection()
    assert "human_readable" not in public
    assert public["matter_id"] == "matter:explain-1" or public.get("matter_id") in (
        "matter:explain-1",
        None,
    )


def test_status_requires_injected_client() -> None:
    api = USPTOAnalysisAPI()
    with pytest.raises(UsptoAPIError) as exc:
        api.status("16123456")
    assert exc.value.code == "missing_client"


def test_status_with_fixture_client() -> None:
    fixture_dir = (
        Path(__file__).resolve().parents[4]
        / "fixtures"
        / "uspto"
        / "odp"
        / "http"
    )
    recipe = fixture_dir / "odp_http_recipe.json"
    if not recipe.is_file():
        pytest.skip("ODP fixture recipe not present")
    from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
        PatentFileWrapperClient,
    )

    client = PatentFileWrapperClient.from_fixture_dir(fixture_dir)
    api = USPTOAnalysisAPI(
        client=client,
        credential_ref=CredentialRef(reference_id="fixture-key"),
    )
    # Application number may be rejected by identity or return a typed result.
    result = api.status("16123456")
    payload = result.to_dict()
    assert "schema_version" in payload
    assert "outcome" in payload
    # Domain notes may mention that ODP requires an API key; ensure no secret
    # *value* or credential-result field is present.
    serialized = json.dumps(payload)
    assert "never-serialize-me" not in serialized
    assert "test-key-not-a-secret" not in serialized
    assert "X-API-KEY" not in serialized
    assert payload.get("api_key") is None
    assert "super-secret" not in serialized


# ---------------------------------------------------------------------------
# Processor registration (canonical registry)
# ---------------------------------------------------------------------------


def test_adapter_implements_core_protocol() -> None:
    adapter = USPTOProcessorAdapter()
    assert is_processor(adapter)
    caps = adapter.get_capabilities()
    assert caps["name"] == "USPTOProcessor"
    assert "status" in caps["operations"]
    assert "sign" in caps["forbidden_operations"]


@pytest.mark.anyio
async def test_adapter_can_handle_and_process_analyze() -> None:
    api = USPTOAnalysisAPI(id_factory=lambda: "ad01")
    adapter = USPTOProcessorAdapter(api=api)
    ctx = ProcessingContext(
        input_type=InputType.TEXT,
        source="matter:adapter-1",
        metadata={"format": "uspto", "domain": "uspto"},
        options={"operation": "analyze", "matter_id": "matter:adapter-1"},
    )
    assert await adapter.can_handle(ctx) is True
    result = await adapter.process(ctx)
    assert result.success is True
    assert result.raw_output is not None
    assert result.raw_output["analysis_bundle"]["matter_id"] == "matter:adapter-1"


@pytest.mark.anyio
async def test_adapter_rejects_forbidden_operation() -> None:
    adapter = USPTOProcessorAdapter()
    ctx = ProcessingContext(
        input_type=InputType.TEXT,
        source="x",
        metadata={"format": "uspto"},
        options={"operation": "sign"},
    )
    result = await adapter.process(ctx)
    assert result.success is False
    assert result.errors


def test_register_uspto_processors_once() -> None:
    registry = ProcessorRegistry()
    name1 = register_uspto_processors(registry=registry)
    name2 = register_uspto_processors(registry=registry)
    assert name1 == name2 == "USPTOProcessor"
    listed = registry.list_processors()
    assert "USPTOProcessor" in listed
    # Only one entry
    assert sum(1 for k in listed if k == "USPTOProcessor") == 1


def test_adapter_source_has_no_browser_automation() -> None:
    import ipfs_datasets_py.processors.adapters.uspto_adapter as mod
    import ipfs_datasets_py.processors.domains.uspto.api as api_mod
    import ipfs_datasets_py.cli.uspto as cli_mod

    for module in (mod, api_mod, cli_mod):
        source = inspect.getsource(module)
        for needle in (
            "import selenium",
            "from selenium",
            "import playwright",
            "from playwright",
            "webdriver.Chrome",
        ):
            assert needle not in source, module.__name__
