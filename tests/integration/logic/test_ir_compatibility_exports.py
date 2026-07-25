"""Integration contracts for the reviewed IR-family package facades."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess
import sys
import warnings

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SECURITY_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "security_ir" / "v1"
LEGACY_CRYPTO_EXPORTS = [
    "DEFAULT_THREAT_MODEL_ASSUMPTIONS",
    "ProofReceipt",
    "ProofReport",
    "ReleasePolicyEntry",
    "RuntimeMTLMonitor",
    "SecurityIRFeatureLoopProjector",
    "SecurityModelIR",
    "Z3Runner",
    "calculate_model_cid",
    "canonicalize_ir",
    "canonicalize_ir_json",
    "check_runtime_properties",
    "default_claims",
    "evaluate_assumption_registry",
    "evaluate_evidence_promotion_workflow",
    "evaluate_release_policy",
    "example_minimal_exchange_model",
    "release_policy_entries",
    "validate_ir",
]
DEPRECATION_MESSAGE = (
    "ipfs_datasets_py.logic.security_models.crypto_exchange is a legacy "
    "compatibility path; use ipfs_datasets_py.logic.security_ir for new "
    "declarations and adapters."
)


def _leaf_exports(*module_names: str) -> set[str]:
    exports: set[str] = set()
    for module_name in module_names:
        module = importlib.import_module(module_name)
        exports.update(module.__all__)
    return exports


def test_shared_facades_export_exactly_reviewed_leaf_contracts() -> None:
    import ipfs_datasets_py.logic.formalization as formalization
    import ipfs_datasets_py.logic.ir_core as ir_core
    import ipfs_datasets_py.logic.legal_ir as legal_ir

    assert set(ir_core.__all__) == _leaf_exports(
        "ipfs_datasets_py.logic.ir_core.artifacts",
        "ipfs_datasets_py.logic.ir_core.canonical",
        "ipfs_datasets_py.logic.ir_core.claims",
        "ipfs_datasets_py.logic.ir_core.diagnostics",
        "ipfs_datasets_py.logic.ir_core.evidence",
        "ipfs_datasets_py.logic.ir_core.identity",
        "ipfs_datasets_py.logic.ir_core.protocols",
        "ipfs_datasets_py.logic.ir_core.provenance",
        "ipfs_datasets_py.logic.ir_core.schema_registry",
    )
    assert set(formalization.__all__) == _leaf_exports(
        "ipfs_datasets_py.logic.formalization.compiler",
        "ipfs_datasets_py.logic.formalization.samples",
        "ipfs_datasets_py.logic.formalization.views",
    )
    assert set(legal_ir.__all__) == _leaf_exports(
        "ipfs_datasets_py.logic.legal_ir.adapter",
    )

    assert ir_core.CanonicalizationSchema is ir_core.CollectionSchema
    assert ir_core.compute_identity is ir_core.identity_for is ir_core.canonical_identity
    assert ir_core.IRProvenance is ir_core.Provenance
    assert ir_core.IRDiagnostics is ir_core.IRDiagnosticReport is ir_core.DiagnosticReport
    assert ir_core.IRObligation is ir_core.Obligation is ir_core.ProofObligation
    assert ir_core.RunManifest is ir_core.ArtifactManifest
    assert legal_ir.LegalIRAdapter is legal_ir.LegalIRFormalizationAdapter
    assert (
        legal_ir.LEGAL_IR_VIEW_REGISTRY
        is legal_ir.LEGAL_IR_FORMALIZATION_VIEW_REGISTRY
    )

    assert "FormalizationAdvisor" not in formalization.__all__
    assert "CheckpointManifest" not in formalization.__all__


def test_security_facade_exports_reviewed_contracts_without_name_collisions() -> None:
    import ipfs_datasets_py.logic.security_ir as security_ir

    expected = _leaf_exports(
        "ipfs_datasets_py.logic.security_ir.model",
        "ipfs_datasets_py.logic.security_ir.adapter",
        "ipfs_datasets_py.logic.security_ir.results",
        "ipfs_datasets_py.logic.security_ir.result_policy",
        "ipfs_datasets_py.logic.security_ir.artifact_migration",
        "ipfs_datasets_py.logic.security_ir.formalization_adapter",
        "ipfs_datasets_py.logic.security_ir.exchange.adapter",
        "ipfs_datasets_py.logic.security_ir.exchange.vocabulary",
        "ipfs_datasets_py.logic.security_ir.xaman.adapter",
        "ipfs_datasets_py.logic.security_ir.xaman.config",
    )
    # These generic aliases exist in both the shared and exchange adapters.
    # The package root deliberately gives the shared legacy adapter ownership.
    assert set(security_ir.__all__) == expected
    assert security_ir.from_legacy is security_ir.adapt_legacy_security_ir
    assert security_ir.to_legacy is security_ir.to_legacy_security_ir

    assert security_ir.SecurityIRV1 is security_ir.SecurityIR
    assert security_ir.LegacySecurityIRAdapter is security_ir.SecurityIRLegacyAdapter
    assert security_ir.SecurityIRAdapter is security_ir.SecurityIRFormalizationAdapter
    assert security_ir.ExchangeAdapter is security_ir.ExchangeSecurityAdapter
    assert security_ir.XamanSecurityAdapterConfig is security_ir.XamanAdapterConfig
    assert security_ir.ResultPolicy is security_ir.ResultSelectionPolicy
    assert "Z3Runner" not in security_ir.__all__


def test_intent_facade_adds_versioned_decoder_without_runtime_exports() -> None:
    import ipfs_datasets_py.logic.intent_ir as intent_ir

    reviewed = _leaf_exports(
        "ipfs_datasets_py.logic.intent_ir.canonicalize",
        "ipfs_datasets_py.logic.intent_ir.decoder",
        "ipfs_datasets_py.logic.intent_ir.protocols",
        "ipfs_datasets_py.logic.intent_ir.schema",
    )
    assert set(intent_ir.__all__) == reviewed
    assert intent_ir.GroundingKind is intent_ir.NodeGrounding
    assert (
        intent_ir.INTENT_IR_SCHEMA_REGISTRY[
            intent_ir.INTENT_IR_SCHEMA_VERSION
        ].schema_id
        == intent_ir.INTENT_IR_SCHEMA_VERSION
    )
    assert "SkillCenterIntentNormalizer" not in intent_ir.__all__
    assert "SkillCenterBundleReader" not in intent_ir.__all__


def test_plain_facade_imports_do_not_load_legacy_or_optional_runtimes() -> None:
    script = """
import sys
import ipfs_datasets_py.logic.ir_core
import ipfs_datasets_py.logic.formalization
import ipfs_datasets_py.logic.legal_ir
import ipfs_datasets_py.logic.security_ir

for forbidden in ("z3", "cvc5", "torch", "transformers"):
    assert forbidden not in sys.modules, forbidden
assert "ipfs_datasets_py.logic.security_models.crypto_exchange" not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_legacy_crypto_surface_and_transitional_aliases_are_preserved() -> None:
    import ipfs_datasets_py.logic.security_ir as security_ir
    import ipfs_datasets_py.logic.security_models.crypto_exchange as legacy

    assert legacy.__all__ == LEGACY_CRYPTO_EXPORTS
    assert legacy.__deprecated__ is True
    assert legacy.__deprecated_since__ == "IRFamilyExports@1"
    assert legacy.__replacement__ == "ipfs_datasets_py.logic.security_ir"

    transitional_names = (
        "SecurityIR",
        "LegacyAdapterResult",
        "LegacyVerificationData",
        "SecurityIRLegacyAdapter",
        "adapt_legacy_security_ir",
        "to_legacy_security_ir",
    )
    for name in transitional_names:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            value = getattr(legacy, name)
        assert value is getattr(security_ir, name)
        assert len(caught) == 1
        assert caught[0].category is DeprecationWarning
        assert str(caught[0].message) == DEPRECATION_MESSAGE
    assert set(transitional_names) <= set(dir(legacy))
    assert set(transitional_names).isdisjoint(legacy.__all__)


@pytest.mark.parametrize("fixture_name", ("exchange_model.json", "xaman_model.json"))
def test_legacy_payloads_round_trip_through_the_new_facade(fixture_name: str) -> None:
    import ipfs_datasets_py.logic.security_ir as security_ir
    from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import (
        SecurityModelIR,
    )

    payload = json.loads((SECURITY_FIXTURES / fixture_name).read_text(encoding="utf-8"))
    adapted = security_ir.adapt_legacy_security_ir(payload)

    assert isinstance(adapted.declaration, security_ir.SecurityIR)
    assert adapted.lossless is True
    assert security_ir.to_legacy_security_ir(adapted) == payload
    legacy_model = security_ir.to_legacy_security_ir(adapted, as_model=True)
    assert isinstance(legacy_model, SecurityModelIR)
    assert legacy_model.to_dict() == payload


def test_registry_discovers_new_families_and_preserves_legacy_entry() -> None:
    from ipfs_datasets_py.logic import submodule_registry

    expected_symbols = {
        "ir_core": (
            "CanonicalIdentity",
            "Provenance",
            "IRSchemaRegistry",
            "IRClaim",
            "ProofBackend",
            "ArtifactManifest",
        ),
        "formalization": (
            "FormalizationSample",
            "FormalizationView",
            "FormalizationCompiler",
            "FormalizationArtifact",
        ),
        "legal_ir": ("LegalIRFormalizationAdapter", "adapt_legal_sample"),
        "security_ir": (
            "SecurityIR",
            "SecurityIRLegacyAdapter",
            "ExchangeSecurityAdapter",
            "XamanSecurityAdapter",
            "SecurityResultAuthority",
            "SecurityIRFormalizationAdapter",
        ),
        "intent_ir": (
            "IntentIRDocument",
            "decode_intent_ir",
            "canonical_intent_ir_bytes",
            "IntentNormalizer",
            "IntentFormalizer",
        ),
    }
    manifest = submodule_registry.logic_integration_manifest()
    manifest_by_name = {item["name"]: item for item in manifest["submodules"]}

    for name, public_symbols in expected_symbols.items():
        spec = submodule_registry.logic_submodule_spec(name)
        assert spec.public_symbols == public_symbols
        assert manifest_by_name[name] == spec.to_dict()

    legacy = submodule_registry.logic_submodule_spec("security_models")
    assert legacy.module == "ipfs_datasets_py.logic.security_models"
    assert legacy.roles == ("security_models", "proof", "policy", "runtime_monitor")
    assert legacy.optimizer_components == ("security_models.crypto_exchange",)
    assert legacy.public_symbols == (
        "SecurityModelIR",
        "ProofReport",
        "ProofReceipt",
        "RuntimeMTLMonitor",
    )

    report = submodule_registry.logic_submodule_import_report()
    for name in (*expected_symbols, "security_models"):
        assert report[name] == {
            "module": submodule_registry.logic_submodule_spec(name).module,
            "ok": True,
            "skipped": False,
            "version": None,
        }
