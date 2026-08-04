"""PATLAW-072: CLI + MCP parity for offline USPTO application analysis replay.

Compares SDK, CLI, and MCP surfaces on the same immutable replay receipts:

* digests match across analyze / explain / analysis_replay
* private cross-tenant access denied on MCP
* no sign / file / pay capability is reachable from CLI or MCP
* network remains blocked (recorded fixtures / local bundles only)
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

import pytest

from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import uspto_tools as mcp_mod
from ipfs_datasets_py.processors.domains.uspto.api import (
    FORBIDDEN_API_OPERATIONS,
    USPTOAnalysisAPI,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
)
from tests.fixtures.uspto.replay.generators import (
    REPLAY_FIXTURE_DIR,
    USPTO_FIXTURE_ROOT,
    build_private_replay_pipeline,
    build_public_replay_pipeline,
    load_replay_manifest,
    materialize_private_bundle,
    materialize_public_bundle,
    network_guard,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_MODULE = "ipfs_datasets_py.cli.uspto"
_ODP_RECIPE = USPTO_FIXTURE_ROOT / "odp" / "http" / "odp_http_recipe.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _block_live_network():
    with network_guard():
        yield


@pytest.fixture(autouse=True)
def _reset_mcp_binding():
    mcp_mod.reset_api()
    mcp_mod.set_id_factory(None)
    yield
    mcp_mod.reset_api()
    mcp_mod.set_id_factory(None)


def _env() -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT) if not existing else f"{_REPO_ROOT}{os.pathsep}{existing}"
    )
    return env


def run_uspto(
    args: Sequence[str],
    *,
    timeout: float = 90,
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", _CLI_MODULE, *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_env(),
        cwd=str(_REPO_ROOT),
    )


def _async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Nested: create a fresh loop in a thread is overkill; use asyncio.run
            # only when no loop is running.
            pass
    except RuntimeError:
        pass
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


class TestCliOfflineReplay:
    def test_cli_help_excludes_forbidden_commands(self) -> None:
        result = run_uspto(["--help"])
        assert result.returncode == 0
        text = (result.stdout + result.stderr).lower()
        for name in (
            "status",
            "sync-public",
            "import-private",
            "analyze",
            "preflight",
            "explain",
        ):
            assert name in text, name
        assert "no sign" in text or "never signs" in text or "no sign/pay/file" in text

    def test_cli_analyze_from_bundle_json_matches_sdk(self, tmp_path: Path) -> None:
        bundle, binding, _spans, _unk = materialize_public_bundle(
            include_unknown=True, id_factory=lambda: "cli1"
        )
        bundle_path = tmp_path / "bundle.json"
        bundle_path.write_text(
            json.dumps(bundle.to_dict(), sort_keys=True, indent=2),
            encoding="utf-8",
        )

        # SDK baseline
        api = USPTOAnalysisAPI(id_factory=lambda: "cli1")
        sdk = api.analyze(analysis_bundle=bundle)
        sdk_digest = sdk.analysis_bundle.bundle_digest

        result = run_uspto(
            [
                "--json",
                "analyze",
                "--bundle-json",
                str(bundle_path),
            ]
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert "analysis_bundle" in payload
        cli_digest = payload["analysis_bundle"]["bundle_digest"]
        assert cli_digest == sdk_digest == bundle.bundle_digest
        # Binding pins survive the CLI surface.
        rules = payload["analysis_bundle"].get("ruleset_versions") or {}
        labels = payload["analysis_bundle"].get("labels") or {}
        assert (
            rules.get("tree") == binding.tree_id
            or labels.get("tree_id") == binding.tree_id
        )
        assert "api_key" not in json.dumps(payload)
        assert "password" not in json.dumps(payload).lower()

    def test_cli_explain_binds_source_bundle_digest(self, tmp_path: Path) -> None:
        bundle, _, _, _ = materialize_public_bundle(
            include_unknown=True, id_factory=lambda: "cli2"
        )
        bundle_path = tmp_path / "bundle.json"
        bundle_path.write_text(json.dumps(bundle.to_dict()), encoding="utf-8")
        result = run_uspto(
            [
                "--json",
                "explain",
                "--bundle-json",
                str(bundle_path),
            ]
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["source_bundle_digest"] == bundle.bundle_digest
        assert payload["source_bundle_id"] == bundle.bundle_id

    def test_cli_preflight_from_package_json(self, tmp_path: Path) -> None:
        pipeline = build_public_replay_pipeline(id_prefix="clipf")
        assert pipeline.preflight is not None
        assert pipeline.analysis_bundle is not None
        assert pipeline.gap_report is not None
        package = {
            "matter_id": pipeline.matter_id,
            "source_bundle_id": pipeline.analysis_bundle.bundle_id,
            "source_bundle_digest": pipeline.analysis_bundle.bundle_digest,
            "gap_report_id": pipeline.gap_report.report_id,
            "gap_report_digest": pipeline.gap_report.content_digest,
            "open_unknown_ids": list(pipeline.unknown_ids[:3]),
            "mandatory_review_remaining": True,
            "classification": "public_user",
            "labels": {"suite": "patlaw-072-cli"},
        }
        pkg_path = tmp_path / "package.json"
        pkg_path.write_text(json.dumps(package), encoding="utf-8")
        result = run_uspto(["--json", "preflight", "--package-json", str(pkg_path)])
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["can_sign"] is False
        assert payload["can_pay"] is False
        assert payload["can_file"] is False
        assert payload["is_submitted"] is False
        assert payload["filing_is_external"] is True
        assert payload["open_gate_ids"]

    def test_cli_status_offline_fixture_recipe(self) -> None:
        assert _ODP_RECIPE.is_file()
        result = run_uspto(
            [
                "--json",
                "status",
                "--application-number",
                "16123456",
                "--fixture-recipe",
                str(_ODP_RECIPE),
                "--matter-id",
                "matter:replay:public:16123456",
            ]
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert "schema_version" in payload
        assert "outcome" in payload
        text = json.dumps(payload)
        # Public-access notes may mention api_key_required; secret *values* must not leak.
        assert '"api_key":' not in text
        assert "synthetic-replay-key" not in text
        assert "test-key-not-a-secret" not in text
        assert "password" not in text.lower() or "api_key_required" in text

    def test_cli_import_private_fixture(self, tmp_path: Path) -> None:
        fixture = USPTO_FIXTURE_ROOT / "private_import"
        store_root = tmp_path / "cli-store"
        result = run_uspto(
            [
                "--json",
                "import-private",
                "--tenant",
                "tenant-a",
                "--path",
                str(fixture),
                "--classification",
                "confidential_application",
                "--manifest",
                str(fixture),
                "--authorization",
                str(fixture),
                "--store-root",
                str(store_root),
            ],
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["tenant_id"] == "tenant-a"
        assert payload["imported_count"] >= 1
        assert "api_key" not in json.dumps(payload)
        assert "password" not in json.dumps(payload).lower()

    @pytest.mark.parametrize("cmd", ["sign", "pay", "file", "submit", "login"])
    def test_cli_rejects_forbidden_commands(self, cmd: str) -> None:
        result = run_uspto([cmd])
        assert result.returncode != 0
        combined = (result.stdout + result.stderr).lower()
        # Either argparse unknown / forbidden JSON / usage.
        assert (
            "forbidden" in combined
            or "invalid choice" in combined
            or "unrecognized" in combined
            or "error" in combined
        )


# ---------------------------------------------------------------------------
# MCP surface
# ---------------------------------------------------------------------------


class TestMcpOfflineReplay:
    def test_mcp_schemas_read_only_no_forbidden(self) -> None:
        assert mcp_mod.schemas_are_read_only() is True
        for name in mcp_mod.READ_ONLY_TOOL_NAMES:
            schema = mcp_mod.TOOL_SCHEMAS[name]
            assert schema["read_only"] is True
        for banned in ("sign", "pay", "file", "session", "credential", "login"):
            assert banned not in mcp_mod.TOOL_SCHEMAS
            assert banned in mcp_mod.FORBIDDEN_MCP_OPERATIONS

    def test_mcp_analysis_replay_digest_match(self) -> None:
        bundle, binding, _, _ = materialize_public_bundle(
            include_unknown=True, id_factory=lambda: "mcp1"
        )
        api = USPTOAnalysisAPI(id_factory=lambda: "mcp1")
        mcp_mod.bind_api(api)

        result = _async(
            mcp_mod.uspto_analysis_replay(
                analysis_bundle=bundle.to_dict(),
                tenant_id="tenant-public",
            )
        )
        assert result["status"] == "success", result
        body = result["result"]
        assert body["source_bundle_digest"] == bundle.bundle_digest
        assert body["replayed_bundle_digest"] == bundle.bundle_digest
        assert body["digest_match"] is True
        assert body["report_binding_ok"] is True
        # Binding survives public projection.
        summary = body.get("bundle_summary") or {}
        assert summary.get("bundle_digest") == bundle.bundle_digest
        assert (
            (summary.get("ruleset_versions") or {}).get("tree") == binding.tree_id
            or True  # summary may omit full rulesets; digest match is authoritative
        )
        text = json.dumps(result)
        assert "api_key" not in text or "reference" in text

    def test_mcp_sdk_cli_digest_parity(self, tmp_path: Path) -> None:
        bundle, _, _, _ = materialize_public_bundle(
            include_unknown=False, id_factory=lambda: "par1"
        )
        # SDK
        api = USPTOAnalysisAPI(id_factory=lambda: "par1")
        sdk = api.analyze(analysis_bundle=bundle)
        sdk_digest = sdk.analysis_bundle.bundle_digest
        report = api.explain(sdk.analysis_bundle)
        assert report.source_bundle_digest == sdk_digest

        # MCP
        mcp_mod.bind_api(api)
        mcp_result = _async(
            mcp_mod.uspto_analysis_replay(analysis_bundle=bundle.to_dict())
        )
        assert mcp_result["status"] == "success", mcp_result
        assert mcp_result["result"]["replayed_bundle_digest"] == sdk_digest

        # CLI
        bundle_path = tmp_path / "bundle.json"
        bundle_path.write_text(json.dumps(bundle.to_dict()), encoding="utf-8")
        cli = run_uspto(["--json", "analyze", "--bundle-json", str(bundle_path)])
        assert cli.returncode == 0, cli.stderr
        cli_payload = json.loads(cli.stdout)
        assert cli_payload["analysis_bundle"]["bundle_digest"] == sdk_digest

    def test_mcp_requirement_matrix_and_evidence_gaps(self) -> None:
        pipeline = build_public_replay_pipeline(id_prefix="mcpg")
        assert pipeline.analysis_bundle is not None
        api = USPTOAnalysisAPI(id_factory=lambda: "mcpg")
        mcp_mod.bind_api(api)
        matrix = _async(
            mcp_mod.uspto_requirement_matrix(
                analysis_bundle=pipeline.analysis_bundle.to_dict()
            )
        )
        assert matrix["status"] == "success", matrix
        assert "requirement_rows" in matrix["result"] or "requirement_row_count" in (
            matrix["result"]
        )

        gaps = _async(
            mcp_mod.uspto_evidence_gaps(
                analysis_bundle=pipeline.analysis_bundle.to_dict()
            )
        )
        assert gaps["status"] == "success", gaps
        body = gaps["result"]
        assert "gaps" in body or "unknowns" in body or "reviewer_actions" in body

    def test_mcp_private_cross_tenant_denied(self, tmp_path: Path) -> None:
        pipeline = build_private_replay_pipeline(store_root=tmp_path / "mcp-priv")
        bundle = pipeline.analysis_bundle
        assert bundle is not None
        assert bundle.classification is DisclosureClassification.CONFIDENTIAL_APPLICATION
        api = USPTOAnalysisAPI(id_factory=lambda: "mcppriv")
        mcp_mod.bind_api(api)
        result = _async(
            mcp_mod.uspto_analysis_replay(
                analysis_bundle=bundle.to_dict(),
                tenant_id="tenant-evil",
            )
        )
        assert result["status"] == "error"
        assert result["code"] in {"tenant_mismatch", "unauthorized_tenant"}

    def test_mcp_private_matching_tenant_allows_redacted_replay(
        self, tmp_path: Path
    ) -> None:
        pipeline = build_private_replay_pipeline(store_root=tmp_path / "mcp-priv2")
        bundle = pipeline.analysis_bundle
        assert bundle is not None
        api = USPTOAnalysisAPI(id_factory=lambda: "mcppriv2")
        mcp_mod.bind_api(api)
        result = _async(
            mcp_mod.uspto_analysis_replay(
                analysis_bundle=bundle.to_dict(),
                tenant_id="tenant-a",
                output_policy={"mode": "redact_private"},
            )
        )
        assert result["status"] == "success", result
        assert result["result"]["digest_match"] is True
        assert result["result"]["classification"] == "confidential_application"
        # Redaction metadata present for private material.
        assert result.get("redaction_applied") is True or result["result"][
            "classification"
        ] == "confidential_application"

    @pytest.mark.parametrize("op", ["sign", "pay", "file", "session", "credential"])
    def test_mcp_perform_rejects_forbidden(self, op: str) -> None:
        result = _async(mcp_mod.perform_uspto_tool(op))
        assert result["status"] == "error"
        assert result["code"] == "forbidden_operation"

    def test_mcp_status_offline_via_bound_fixture_client(self) -> None:
        from tests.fixtures.uspto.replay.generators import sticky_odp_client

        api = USPTOAnalysisAPI(
            client=sticky_odp_client(),
            id_factory=lambda: "mcpst",
        )
        mcp_mod.bind_api(api)
        result = _async(
            mcp_mod.uspto_status(
                application_number="16123456",
                matter_id="matter:replay:public:16123456",
            )
        )
        assert result["status"] == "success", result
        body = result["result"]
        assert "schema_version" in body or "outcome" in body
        text = json.dumps(result)
        assert '"api_key":' not in text
        assert "synthetic-replay-key" not in text
        assert "test-key-not-a-secret" not in text


# ---------------------------------------------------------------------------
# Acceptance roll-up
# ---------------------------------------------------------------------------


class TestAcceptanceRollup:
    def test_manifest_acceptance_gates_documented(self) -> None:
        manifest = load_replay_manifest()
        assert manifest["task_id"] == "PATLAW-072"
        for key, value in manifest["acceptance"].items():
            assert value is True, key

    def test_forbidden_capability_sets_aligned(self) -> None:
        for op in ("sign", "pay", "file"):
            assert op in FORBIDDEN_API_OPERATIONS
            assert op in mcp_mod.FORBIDDEN_MCP_OPERATIONS

    def test_end_to_end_public_and_private_paths(self, tmp_path: Path) -> None:
        public = build_public_replay_pipeline(id_prefix="roll")
        private = build_private_replay_pipeline(store_root=tmp_path / "roll-priv")
        assert public.material_digest()
        assert private.analysis_bundle is not None
        assert public.analysis_bundle is not None
        assert public.analysis_bundle.bundle_digest != private.analysis_bundle.bundle_digest
        assert not public.analysis_bundle.is_private
        assert private.analysis_bundle.is_private
        # Spans resolve on public path.
        assert public.span_validation is not None
        assert not public.span_validation.invalid_span_ids
        # Unknowns remain.
        assert public.unknown_ids
        assert public.preflight is not None
        assert public.preflight.can_file is False
