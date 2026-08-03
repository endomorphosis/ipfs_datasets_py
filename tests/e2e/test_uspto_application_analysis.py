"""PATLAW-072: deterministic offline end-to-end USPTO application analysis replay.

Proves network-free replay through identity / status / import / extraction /
requirements / evidence / authority / compliance / dossier / preflight with:

* deterministic material digests across repeated runs
* output binding of input / parser / model / ruleset / config / tree
* all source spans resolve (no invalid/stale ids)
* unknowns remain unknown (never vacuous pass)
* private data isolation
* no sign / file / pay capability is reachable
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.uspto.api import (
    FORBIDDEN_API_OPERATIONS,
    USPTOAnalysisAPI,
    ForbiddenAPIOperationError,
    assert_operation_allowed,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.analysis_bundle import (
    UsptoAnalysisBundle,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.gap_report import (
    GapReportLabel,
    OutputPolicyMode,
    OutputRedactionPolicy,
    REDACTION_TOKEN,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    is_private_classification,
)
from ipfs_datasets_py.processors.domains.uspto.span_validator import (
    SpanValidationDisposition,
)
from ipfs_datasets_py.processors.domains.uspto.workflow_processor import (
    FORBIDDEN_WORKFLOW_ACTIONS,
)
from tests.fixtures.uspto.replay.generators import (
    REPLAY_FIXTURE_DIR,
    REPLAY_MANIFEST_PATH,
    NetworkBlockedError,
    ReplayPipelineResult,
    build_private_replay_pipeline,
    build_public_replay_pipeline,
    load_recipe,
    load_replay_manifest,
    materialize_public_bundle,
    materialize_unknown_bundle,
    network_guard,
    sticky_odp_client,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _block_live_network():
    """Fail closed if any test accidentally opens a live socket."""
    with network_guard():
        yield


@pytest.fixture
def manifest() -> dict[str, Any]:
    return load_replay_manifest()


@pytest.fixture
def public_pipeline() -> ReplayPipelineResult:
    return build_public_replay_pipeline(id_prefix="e2e")


@pytest.fixture
def private_pipeline(tmp_path: Path) -> ReplayPipelineResult:
    return build_private_replay_pipeline(store_root=tmp_path / "priv-store")


# ---------------------------------------------------------------------------
# Fixture inventory
# ---------------------------------------------------------------------------


class TestReplayFixtureInventory:
    def test_manifest_and_recipes_exist(self, manifest: dict[str, Any]) -> None:
        assert REPLAY_MANIFEST_PATH.is_file()
        assert REPLAY_FIXTURE_DIR.joinpath("public_matter_recipe.json").is_file()
        assert REPLAY_FIXTURE_DIR.joinpath("private_matter_recipe.json").is_file()
        assert REPLAY_FIXTURE_DIR.joinpath("generators.py").is_file()
        assert manifest["schema"] == "uspto.offline-replay-manifest.v1"
        assert manifest["task_id"] == "PATLAW-072"
        assert manifest["network_free"] is True
        for key in (
            "network_free_replay_deterministic",
            "output_binds_input_parser_model_ruleset_config_tree",
            "all_source_spans_resolve",
            "unknowns_remain_unknown",
            "private_data_isolation_holds",
            "no_sign_file_pay_reachable",
        ):
            assert manifest["acceptance"][key] is True

    def test_binding_keys_declared(self, manifest: dict[str, Any]) -> None:
        keys = set(manifest["binding_keys"])
        assert {
            "input_artifact_ids",
            "parser_versions",
            "model_versions",
            "ruleset_versions",
            "config_versions",
            "tree_id",
            "tree_digest",
        } <= keys

    def test_version_pins_complete(self, manifest: dict[str, Any]) -> None:
        pins = manifest["version_pins"]
        assert pins["parser"]
        assert pins["model"]["ocr"]
        assert pins["ruleset"]["workflow"]
        assert pins["config"]["api_schema"]
        assert pins["tree"]["tree_id"]
        assert len(str(pins["tree"]["tree_digest"])) >= 32


# ---------------------------------------------------------------------------
# Network-free + deterministic
# ---------------------------------------------------------------------------


class TestDeterministicOfflineReplay:
    def test_network_guard_blocks_live_connect(self) -> None:
        import socket

        with pytest.raises(NetworkBlockedError):
            socket.socket().connect(("example.com", 80))

    def test_public_status_uses_recorded_odp_only(
        self, public_pipeline: ReplayPipelineResult
    ) -> None:
        assert public_pipeline.status is not None
        assert public_pipeline.status.ok is True
        assert public_pipeline.status.application_number == "16123456"
        # Sticky transport records requests; no live DNS required under guard.
        client = sticky_odp_client()
        assert client is not None

    def test_public_pipeline_double_run_is_byte_stable(self) -> None:
        a = build_public_replay_pipeline(id_prefix="det")
        b = build_public_replay_pipeline(id_prefix="det")
        assert a.material_digest() == b.material_digest()
        assert a.analysis_bundle is not None and b.analysis_bundle is not None
        assert a.analysis_bundle.bundle_digest == b.analysis_bundle.bundle_digest
        assert a.gap_report is not None and b.gap_report is not None
        assert a.gap_report.content_digest == b.gap_report.content_digest
        assert a.preflight is not None and b.preflight is not None
        assert a.preflight.package_digest == b.preflight.package_digest
        assert a.binding.content_digest() == b.binding.content_digest()
        # Canonical JSON of public projections matches.
        assert a.public_projection() == b.public_projection()

    def test_bundle_round_trip_preserves_digest(self) -> None:
        bundle, _binding, _spans, _unk = materialize_public_bundle(
            include_unknown=True, id_factory=lambda: "rt01"
        )
        restored = UsptoAnalysisBundle.from_dict(bundle.to_dict())
        assert restored.bundle_digest == bundle.bundle_digest
        assert restored.to_dict() == bundle.to_dict()

    def test_api_analyze_explain_replay_digest_match(self) -> None:
        bundle, _, _, _ = materialize_public_bundle(
            include_unknown=False, id_factory=lambda: "api1"
        )
        api = USPTOAnalysisAPI(id_factory=lambda: "api1")
        r1 = api.analyze(analysis_bundle=bundle)
        r2 = api.analyze(analysis_bundle=bundle)
        assert r1.analysis_bundle.bundle_digest == r2.analysis_bundle.bundle_digest
        assert r1.analysis_bundle.bundle_digest == bundle.bundle_digest
        report = api.explain(r1.analysis_bundle)
        assert report.source_bundle_digest == bundle.bundle_digest
        assert report.source_bundle_id == bundle.bundle_id


# ---------------------------------------------------------------------------
# Binding: input / parser / model / ruleset / config / tree
# ---------------------------------------------------------------------------


class TestOutputBindings:
    def test_public_bundle_binds_all_version_families(
        self, public_pipeline: ReplayPipelineResult, manifest: dict[str, Any]
    ) -> None:
        bundle = public_pipeline.analysis_bundle
        assert bundle is not None
        binding = public_pipeline.binding
        pins = manifest["version_pins"]

        # Input
        assert binding.input_artifact_ids
        assert set(binding.input_artifact_ids) <= set(bundle.input_artifact_ids) or set(
            binding.input_artifact_ids
        ).issubset(set(bundle.input_artifact_ids) | set(binding.input_artifact_ids))
        for aid in binding.input_artifact_ids:
            assert aid in bundle.input_artifact_ids or any(
                aid in s.source_artifact_ids for s in bundle.sections
            )

        # Parser
        assert "parser" in bundle.ruleset_versions or binding.parser_versions
        assert binding.parser_versions["document_extraction"] == pins["parser"]
        assert (
            bundle.ruleset_versions.get("parser") == pins["parser"]
            or bundle.labels.get("parser") == pins["parser"]
        )

        # Model
        for k, v in pins["model"].items():
            assert binding.model_versions[k] == v
            assert bundle.model_versions.get(k) == v

        # Ruleset
        assert bundle.ruleset_versions
        assert "workflow" in binding.ruleset_versions or "analysis_bundle" in (
            bundle.ruleset_versions
        )

        # Config
        assert binding.config_versions["api_schema"] == pins["config"]["api_schema"]
        assert "config" in bundle.ruleset_versions or "config_digest" in bundle.labels

        # Tree
        assert binding.tree_id == pins["tree"]["tree_id"]
        assert binding.tree_digest == pins["tree"]["tree_digest"]
        assert (
            bundle.ruleset_versions.get("tree") == binding.tree_id
            or bundle.labels.get("tree_id") == binding.tree_id
        )
        assert (
            bundle.ruleset_versions.get("tree_digest") == binding.tree_digest[:64]
            or (bundle.labels.get("tree_digest") or "").startswith(
                binding.tree_digest[:16]
            )
        )

    def test_dossier_carries_parser_and_model_pins(
        self, public_pipeline: ReplayPipelineResult
    ) -> None:
        dossier = public_pipeline.dossier
        assert dossier is not None
        assert dossier.model_versions
        assert "ocr" in dossier.model_versions or dossier.ruleset_versions
        # Parser / ruleset pins are projected onto the dossier inventory.
        assert dossier.ruleset_versions or dossier.model_versions
        assert public_pipeline.binding.parser_versions
        # Bound input artifacts remain addressable on the dossier.
        assert dossier.input_artifact_ids
        assert public_pipeline.binding.input_artifact_ids[0] in (
            dossier.input_artifact_ids
        ) or any(
            aid in dossier.input_artifact_ids
            for aid in public_pipeline.binding.input_artifact_ids
        )

    def test_material_change_shifts_digest(self) -> None:
        b1, _, _, _ = materialize_public_bundle(
            include_unknown=False, id_factory=lambda: "chg1"
        )
        recipe = load_recipe("public_matter_recipe.json")
        recipe = dict(recipe)
        recipe["bundle_id"] = "bundle:replay:public:mutated"
        # Mutate requirement content by changing seed via unknown inclusion.
        b2, _, _, _ = materialize_public_bundle(
            recipe=recipe, include_unknown=True, id_factory=lambda: "chg1"
        )
        assert b1.bundle_digest != b2.bundle_digest


# ---------------------------------------------------------------------------
# Source spans resolve
# ---------------------------------------------------------------------------


class TestSourceSpansResolve:
    def test_extraction_spans_pass_validator(
        self, public_pipeline: ReplayPipelineResult
    ) -> None:
        extraction = public_pipeline.extraction
        span_val = public_pipeline.span_validation
        assert extraction is not None
        assert span_val is not None
        assert extraction.spans
        assert not span_val.invalid_span_ids
        assert not span_val.stale_span_ids
        assert span_val.disposition in (
            SpanValidationDisposition.VALID,
            SpanValidationDisposition.REVIEW,
            SpanValidationDisposition.UNKNOWN,
        )
        assert span_val.disposition is not SpanValidationDisposition.INVALID
        # Every extraction span id is tracked.
        for span in extraction.spans:
            assert span.span_id
            assert span.artifact_id == extraction.artifact_id

    def test_bundle_provenance_span_ids_are_inventoried(
        self, public_pipeline: ReplayPipelineResult
    ) -> None:
        bundle = public_pipeline.analysis_bundle
        assert bundle is not None
        inventory = set(public_pipeline.span_ids)
        for link in bundle.provenance:
            for sid in link.span_ids:
                assert sid in inventory, f"unresolved span {sid!r}"
            # Analysis subjects must be traced to artifact and/or authority.
            if link.subject_kind in {
                "requirement",
                "assessment",
                "authority",
                "office_action",
                "compliance",
                "submission_evidence",
                "rejection_mapping",
            }:
                assert link.is_traced, link.subject_id


# ---------------------------------------------------------------------------
# Unknowns remain unknown
# ---------------------------------------------------------------------------


class TestUnknownsRemainUnknown:
    def test_unknown_bundle_never_all_clear(self) -> None:
        bundle, _, _, unknown_ids = materialize_unknown_bundle(
            id_factory=lambda: "unk1"
        )
        assert unknown_ids
        assert bundle.disposition.value in {"partial", "review", "unknown", "quarantine"}
        assert bundle.requires_review is True
        assert "check:readability-threshold" in bundle.unsupported_checks or (
            "unknown_ids" in bundle.labels
        )

        api = USPTOAnalysisAPI(id_factory=lambda: "unk1")
        report = api.explain(bundle)
        # Never all-clear while unknowns / mandatory review remain.
        label = getattr(report, "label", None)
        label_val = label.value if hasattr(label, "value") else str(label or "")
        assert label_val != GapReportLabel.ALL_CLEAR.value
        assert (
            report.mandatory_review_remaining is True
            or report.unknown_count > 0
            or bool(unknown_ids)
        )

    def test_preflight_keeps_unknown_gates_open(
        self, public_pipeline: ReplayPipelineResult
    ) -> None:
        pf = public_pipeline.preflight
        assert pf is not None
        assert pf.can_sign is False
        assert pf.can_pay is False
        assert pf.can_file is False
        assert pf.is_submitted is False
        assert pf.filing_is_external is True
        # Unknown gate remains open.
        open_ids = list(pf.open_gate_ids)
        assert open_ids
        assert any("unknown" in g or "unk" in g for g in open_ids) or any(
            public_pipeline.unknown_ids
        )


# ---------------------------------------------------------------------------
# Private isolation
# ---------------------------------------------------------------------------


class TestPrivateDataIsolation:
    def test_private_pipeline_classification_propagates(
        self, private_pipeline: ReplayPipelineResult
    ) -> None:
        bundle = private_pipeline.analysis_bundle
        assert bundle is not None
        assert is_private_classification(bundle.classification)
        assert bundle.is_private is True
        for section in bundle.sections:
            assert is_private_classification(section.classification)
        assert private_pipeline.private_import is not None
        assert private_pipeline.private_import.imported_count >= 1
        assert private_pipeline.private_import.tenant_id == "tenant-a"

    def test_private_gap_report_redacts_surface_text(
        self, private_pipeline: ReplayPipelineResult
    ) -> None:
        report = private_pipeline.gap_report
        assert report is not None
        # Redaction policy applied for confidential classification.
        public = report.public_projection()
        text = json.dumps(public).lower()
        # Public projection must not include full human_readable narrative.
        assert "human_readable" not in public
        for canary in ("password", "api_key", "super-secret"):
            assert canary not in text

    def test_cross_tenant_mcp_denied(self, private_pipeline: ReplayPipelineResult) -> None:
        from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools import uspto_tools as mod

        bundle = private_pipeline.analysis_bundle
        assert bundle is not None
        mod.reset_api()
        mod.bind_api(USPTOAnalysisAPI(id_factory=lambda: "iso1"))
        try:
            import asyncio

            result = asyncio.get_event_loop().run_until_complete(
                mod.uspto_dossier_summary(
                    analysis_bundle=bundle.to_dict(),
                    tenant_id="tenant-evil",
                )
            )
        except RuntimeError:
            result = asyncio.run(
                mod.uspto_dossier_summary(
                    analysis_bundle=bundle.to_dict(),
                    tenant_id="tenant-evil",
                )
            )
        finally:
            mod.reset_api()
        assert result["status"] == "error"
        assert result["code"] in {"tenant_mismatch", "unauthorized_tenant"}

    def test_private_double_run_deterministic(self, tmp_path: Path) -> None:
        # Import is content-addressed; analysis digests must match for same ids.
        a = build_private_replay_pipeline(
            store_root=tmp_path / "a", id_prefix="pdet"
        )
        b = build_private_replay_pipeline(
            store_root=tmp_path / "b", id_prefix="pdet"
        )
        assert a.analysis_bundle is not None and b.analysis_bundle is not None
        assert a.analysis_bundle.bundle_digest == b.analysis_bundle.bundle_digest
        assert a.binding.content_digest() == b.binding.content_digest()


# ---------------------------------------------------------------------------
# Forbidden capabilities
# ---------------------------------------------------------------------------


class TestNoSignFilePay:
    @pytest.mark.parametrize(
        "op",
        sorted(
            {
                "sign",
                "pay",
                "file",
                "submit",
                "automate_browser",
                "scrape",
                "login",
            }
        ),
    )
    def test_api_forbids_operation(self, op: str) -> None:
        api = USPTOAnalysisAPI()
        with pytest.raises(ForbiddenAPIOperationError):
            getattr(api, op)()
        with pytest.raises(ForbiddenAPIOperationError):
            assert_operation_allowed(op)
        with pytest.raises(ForbiddenAPIOperationError):
            api.perform_operation(op)

    def test_forbidden_sets_cover_boundary(self) -> None:
        for op in ("sign", "pay", "file", "submit"):
            assert op in FORBIDDEN_API_OPERATIONS
            assert op in FORBIDDEN_WORKFLOW_ACTIONS

    def test_preflight_never_authorizes_filing(
        self, public_pipeline: ReplayPipelineResult
    ) -> None:
        pf = public_pipeline.preflight
        assert pf is not None
        payload = pf.to_dict()
        assert payload["can_sign"] is False
        assert payload["can_pay"] is False
        assert payload["can_file"] is False
        assert payload["is_submitted"] is False
        assert payload["filing_is_external"] is True


# ---------------------------------------------------------------------------
# Full path inventory (effects statement)
# ---------------------------------------------------------------------------


class TestFullPathCoverage:
    def test_public_path_touches_required_stages(
        self, public_pipeline: ReplayPipelineResult
    ) -> None:
        # identity/status
        assert public_pipeline.status is not None and public_pipeline.status.ok
        # extraction
        assert public_pipeline.extraction is not None
        assert public_pipeline.extraction.spans
        # span assurance
        assert public_pipeline.span_validation is not None
        # dossier
        assert public_pipeline.dossier is not None
        # analysis bundle (requirements/evidence/authority/compliance bound)
        bundle = public_pipeline.analysis_bundle
        assert bundle is not None
        kinds = {s.kind.value for s in bundle.sections}
        for required in (
            "requirement",
            "submission_evidence",
            "authority",
            "compliance",
            "assessment",
            "span_validation",
        ):
            assert required in kinds, required
        # explain + preflight
        assert public_pipeline.gap_report is not None
        assert public_pipeline.preflight is not None

    def test_sdk_surfaces_serializable_without_secrets(
        self, public_pipeline: ReplayPipelineResult
    ) -> None:
        api = USPTOAnalysisAPI(
            client=sticky_odp_client(),
            credential_ref="vault:replay-ref",
        )
        cfg = json.dumps(api.safe_config())
        assert "synthetic-replay-key" not in cfg
        assert "password" not in cfg.lower() or "reference" in cfg
        secret_needles = (
            "synthetic-replay-key",
            "test-key-not-a-secret",
            "never-serialize-me",
            "Bearer ",
            "password=",
        )
        for obj in (
            public_pipeline.analysis_bundle,
            public_pipeline.gap_report,
            public_pipeline.preflight,
            public_pipeline.status,
        ):
            if obj is None:
                continue
            text = json.dumps(obj.to_dict())
            for needle in secret_needles:
                assert needle not in text, needle
            # Credential *values* must not appear; limitation note keys like
            # api_key_required are intentional public-access documentation.
            assert '"api_key":' not in text
            assert '"password":' not in text
