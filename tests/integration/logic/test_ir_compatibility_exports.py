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
        "ipfs_datasets_py.logic.ir_core.source_lineage",
    )
    assert set(formalization.__all__) == _leaf_exports(
        "ipfs_datasets_py.logic.formalization.compiler",
        "ipfs_datasets_py.logic.formalization.samples",
        "ipfs_datasets_py.logic.formalization.views",
    )
    # Legal IR package root re-exports the formalization adapter plus the
    # reviewed canonical compiler/decompiler/roundtrip surface (LIG Legal
    # measured path).  The set is curated at package root (not a full union of
    # every leaf __all__).
    legal_adapter = _leaf_exports("ipfs_datasets_py.logic.legal_ir.adapter")
    assert legal_adapter <= set(legal_ir.__all__)
    assert set(legal_ir.__all__) == {
        *legal_adapter,
        "CANONICAL_PARITY_POLICY_CID",
        "CANONICAL_SEMANTIC_ROUNDTRIP_CONFIG_CID",
        "CANONICAL_SEMANTIC_ROUNDTRIP_INTERFACE",
        "CanonicalAtomVocabulary",
        "CanonicalCompiler",
        "CanonicalContractError",
        "CanonicalDecompiler",
        "CanonicalRoundTrip",
        "CanonicalRoundTripIR",
        "CanonicalRule",
        "CanonicalSemanticRoundTrip",
        "CanonicalSemanticRoundTripResult",
        "CompilerRequest",
        "CompilerResult",
        "DecompilerRequest",
        "DecompilerResult",
        "OperationStatus",
        "SourceWithheldCanonicalDecompiler",
        "SourceWithheldCanonicalParaphraser",
        "TYPED_DEONTIC_COMPILER_CONFIG_CID",
        "TypedDeonticCanonicalCompiler",
        "compiler_configuration",
        "frozen_decompiler_config",
        "load_parity_policy",
        "measured_parity_compiler_request",
        "roundtrip_configuration",
    }

    assert ir_core.CanonicalizationSchema is ir_core.CollectionSchema
    assert ir_core.compute_identity is ir_core.identity_for is ir_core.canonical_identity
    assert ir_core.IRProvenance is ir_core.Provenance
    assert ir_core.IRDiagnostics is ir_core.IRDiagnosticReport is ir_core.DiagnosticReport
    assert ir_core.IRObligation is ir_core.Obligation is ir_core.ProofObligation
    assert ir_core.RunManifest is ir_core.ArtifactManifest
    assert legal_ir.LegalIRAdapter is legal_ir.LegalIRFormalizationAdapter
    assert legal_ir.LEGAL_IR_VIEW_REGISTRY is legal_ir.LEGAL_IR_FORMALIZATION_VIEW_REGISTRY

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
        intent_ir.INTENT_IR_SCHEMA_REGISTRY[intent_ir.INTENT_IR_SCHEMA_VERSION].schema_id
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
import ipfs_datasets_py.logic.semantic

for forbidden in ("z3", "cvc5", "torch", "transformers"):
    assert forbidden not in sys.modules, forbidden
assert "ipfs_datasets_py.logic.security_models.crypto_exchange" not in sys.modules
assert "ipfs_datasets_py.logic.legal_ir.canonical_compiler" not in sys.modules
assert "ipfs_datasets_py.logic.semantic.operations" not in sys.modules
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
        "semantic": (
            "SemanticAPI",
            "discover_semantic_operations",
            "semantic_api_manifest",
            "compile",
            "decompile",
            "evaluate",
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

def _same_owner(left: object, right: object) -> bool:
    return getattr(left, "__func__", left) is getattr(right, "__func__", right)


def test_semantic_api_discovery_is_versioned_and_closed() -> None:
    import ipfs_datasets_py.logic.semantic as semantic

    names = (
        "corpus",
        "split",
        "example",
        "compile",
        "decompile",
        "translate",
        "pair",
        "evaluate",
        "verify",
        "publish",
    )
    assert semantic.SEMANTIC_API_INTERFACE == "SemanticPublicAPI@1"
    assert semantic.SEMANTIC_API_SCHEMA_VERSION == "pgir-semantic-api/v1"
    assert semantic.SEMANTIC_API_VERSION == "1.0.0"
    assert semantic.SEMANTIC_API_TASK_ID == "PGIR-080"
    assert semantic.SEMANTIC_OPERATION_NAMES == names
    discovered = semantic.discover_semantic_operations()
    assert tuple(spec.name for spec in discovered) == names
    manifest = semantic.semantic_api_manifest()
    assert manifest["interface"] == "SemanticPublicAPI@1"
    assert manifest["task_id"] == "PGIR-080"
    assert manifest["import_side_effects"] == "none"
    assert manifest["operation_names"] == list(names)
    for spec in discovered:
        assert spec.import_side_effects == "none"
        assert spec.signature.startswith(spec.name)
    with pytest.raises(KeyError, match="unknown semantic operation"):
        semantic.semantic_operation_spec("promote")
    facade = semantic.SemanticAPI()
    assert facade.interface == semantic.SEMANTIC_API_INTERFACE
    assert facade.operations() == discovered
    assert facade.manifest() == manifest


def test_semantic_api_delegates_to_canonical_owners() -> None:
    import ipfs_datasets_py.logic.semantic as semantic
    from ipfs_datasets_py.logic.bridge.translation import (
        catalog_default_receipt,
        issue_translation_receipt,
    )
    from ipfs_datasets_py.logic.formalization.training_examples import (
        IRHardNegative,
        IRPositivePair,
        validate_training_example,
    )
    from ipfs_datasets_py.logic.ir_core.artifacts import verify_artifact_integrity
    from ipfs_datasets_py.logic.ir_core.source_lineage import CorpusManifest
    from ipfs_datasets_py.logic.legal_ir.canonical_compiler import TypedDeonticCanonicalCompiler
    from ipfs_datasets_py.logic.legal_ir.canonical_decompiler import (
        SourceWithheldCanonicalDecompiler,
    )
    from ipfs_datasets_py.logic.legal_ir.canonical_roundtrip import CanonicalSemanticRoundTrip
    from ipfs_datasets_py.logic.proof_corpus.store import put_envelope
    from ipfs_datasets_py.logic.proof_corpus.verifier import verify_selected_item
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_eval_splits import (
        LegalIRSplitManifest,
        validate_legal_ir_eval_splits,
    )

    owners = semantic.canonical_owners()
    assert _same_owner(owners["compile"], TypedDeonticCanonicalCompiler.compile)
    assert owners["compile_type"] is TypedDeonticCanonicalCompiler
    assert _same_owner(owners["corpus"], CorpusManifest.from_dict)
    assert _same_owner(owners["decompile"], SourceWithheldCanonicalDecompiler.decompile)
    assert owners["decompile_type"] is SourceWithheldCanonicalDecompiler
    assert _same_owner(owners["evaluate"], CanonicalSemanticRoundTrip.run)
    assert owners["evaluate_type"] is CanonicalSemanticRoundTrip
    assert owners["example"] is validate_training_example
    assert _same_owner(owners["pair_hard_negative"], IRHardNegative.from_dict)
    assert _same_owner(owners["pair_positive"], IRPositivePair.from_dict)
    assert owners["publish"] is put_envelope
    assert _same_owner(owners["split"], LegalIRSplitManifest.from_mapping)
    assert owners["split_validate"] is validate_legal_ir_eval_splits
    assert owners["translate"] is issue_translation_receipt
    assert owners["translate_default"] is catalog_default_receipt
    assert owners["verify_artifact"] is verify_artifact_integrity
    assert owners["verify_proof"] is verify_selected_item
    assert type(semantic.compiler()) is TypedDeonticCanonicalCompiler
    assert semantic.TypedDeonticCanonicalCompiler is TypedDeonticCanonicalCompiler
    assert semantic.CorpusManifest is CorpusManifest


def _rights():
    from ipfs_datasets_py.logic.ir_core.source_lineage import RightsDisposition, RightsRecord

    return RightsRecord(
        disposition=RightsDisposition.QUARANTINED,
        license_expression="cc0-1.0",
        source_rights_status="unresolved",
        transformation_rights_status="unresolved",
        scope="pgir-080",
    )


def _split_payload() -> dict:
    return {
        "assignments": {"sample:1": "train"},
        "config_digest": "a" * 64,
        "examples": [
            {
                "sample_id": "sample:1",
                "content_hash": "b" * 64,
                "citation_clusters": ("usc:1",),
                "source_span_key": "span:1",
                "amendment_key": "amd:1",
                "statute_family": "usc",
                "jurisdiction": "US",
                "effective_date": "2020-01-01",
                "source_label": "pilot",
                "lineage_group_id": "lineage:1",
            }
        ],
        "schema_version": "legal-ir-eval-splits-v1",
    }


def _positive_pair():
    from ipfs_datasets_py.logic.formalization.training_contracts import (
        EvidenceStatus,
        IRPositivePair,
        LabelAuthority,
        LabelEvidence,
        LineageBinding,
        LogicFamily,
        RepresentationKind,
        SemanticRelationship,
        StatementAuthority,
        StatementBinding,
    )
    from ipfs_datasets_py.logic.ir_core.source_lineage import RightsDisposition

    digest_a = f"sha256:{'a' * 64}"
    digest_b = f"sha256:{'b' * 64}"
    digest_f = f"sha256:{'f' * 64}"
    cid = "bafkreiaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    lineage = LineageBinding(
        corpus_manifest_id="corpus:pgir-080",
        corpus_manifest_cid=cid,
        lineage_graph_id="lineage-graph:pgir-080",
        lineage_graph_cid=cid,
        split_manifest_id="split:pgir-080",
        split_manifest_digest=digest_a,
        split_name="train",
        lineage_group_ids=("lineage:1",),
        rights_disposition=RightsDisposition.ADMITTED,
        source_record_ids=("source:1",),
    )
    left = StatementBinding(
        statement_id="statement:source",
        statement_digest=digest_a,
        representation=RepresentationKind.SOURCE_TEXT,
        logic_family=LogicFamily.FIRST_ORDER,
        artifact_id="artifact:source",
        artifact_digest=digest_a,
        lineage_group_ids=("lineage:1",),
        source_record_ids=("source:1",),
        source_ref_ids=("source-ref:source",),
    )
    right = StatementBinding(
        statement_id="statement:ir",
        statement_digest=digest_b,
        representation=RepresentationKind.CANONICAL_IR,
        logic_family=LogicFamily.FIRST_ORDER,
        artifact_id="artifact:ir",
        artifact_digest=digest_b,
        lineage_group_ids=("lineage:1",),
        source_record_ids=("source:1",),
        source_ref_ids=("source-ref:ir",),
    )
    evidence = LabelEvidence(
        evidence_id="evidence:relation",
        evidence_digest=digest_f,
        authority=LabelAuthority.CANONICAL_VALIDATOR,
        status=EvidenceStatus.VERIFIED,
        subject_statement_ids=(left.statement_id, right.statement_id),
        subject_statement_digests=(left.statement_digest, right.statement_digest),
        producer_id="checker:semantic",
        producer_version="1.0",
        independent=False,
        relationship=SemanticRelationship.EXACT,
    )
    return IRPositivePair(
        pair_id="pair:pgir-080",
        lineage=lineage,
        left=left,
        right=right,
        left_authority=StatementAuthority.SOURCE_ASSERTED,
        right_authority=StatementAuthority.CANONICALLY_VALIDATED,
        relationship=SemanticRelationship.EXACT,
        equivalence_class_id="equivalence:1",
        evidence=(evidence,),
    )


def _compiler_request():
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
        CanonicalAtomVocabulary,
        CompilerRequest,
    )

    return CompilerRequest(
        source_text="Company A shall submit backup report within 10 days unless emergency.",
        request_id="pgir-080",
        atom_vocabulary=CanonicalAtomVocabulary(
            actors=("agency", "company_a"),
            actions=("file", "submit", "withdraw"),
            objects=("backup_report", "notice"),
            qualifiers=("emergency", "natural_disaster", "within_10_days"),
        ),
    )


def test_semantic_api_data_plane_and_translation_delegate() -> None:
    import ipfs_datasets_py.logic.semantic as semantic
    from ipfs_datasets_py.logic.formalization.training_examples import IRTrainingExample
    from ipfs_datasets_py.logic.ir_core.source_lineage import CorpusManifest
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
        DecompilerRequest,
        OperationStatus,
    )
    from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json

    corpus = semantic.corpus(
        {
            "manifest_id": "corp:pgir-080",
            "source_record_ids": ("src:1",),
            "derived_artifact_ids": ("drv:1",),
            "lineage_graph_id": "lin:1",
            "rights": _rights().to_dict(),
        }
    )
    assert isinstance(corpus, CorpusManifest)
    assert semantic.corpus(corpus) is corpus
    split = semantic.split(_split_payload())
    assert split.assignments["sample:1"] == "train"
    pair = _positive_pair()
    assert semantic.pair(pair.to_dict()).to_dict() == pair.to_dict()
    example = IRTrainingExample.classify(
        example_id="example:pgir-080",
        record=pair,
        selected_evidence_id="evidence:relation",
    )
    assert semantic.example(example.to_dict()).to_dict() == example.to_dict()
    source_cid = cid_for_dag_json({"pgir080": "source"})
    target_cid = cid_for_dag_json({"pgir080": "target"})
    receipt = semantic.translate(
        direction_id="A4-TYPED-002",
        source_cid=source_cid,
        target_cid=target_cid,
    )
    assert receipt.direction_id == "A4-TYPED-002"
    request = _compiler_request()
    compiled = semantic.compile(request)
    assert compiled.status is OperationStatus.SUCCESS
    decompiled = semantic.decompile(
        DecompilerRequest(canonical_ir=compiled.canonical_ir, request_id="pgir-080-decompile")
    )
    assert decompiled.status is OperationStatus.SUCCESS
    evaluated = semantic.evaluate(request)
    assert evaluated.status is OperationStatus.SUCCESS
    mapped = semantic.compile(
        {
            "source_text": request.source_text,
            "atom_vocabulary": request.atom_vocabulary.to_dict(),
            "request_id": "pgir-080-mapping",
        }
    )
    assert mapped.status is OperationStatus.SUCCESS


def test_semantic_api_verify_publish_and_fail_closed_paths() -> None:
    import ipfs_datasets_py.logic.semantic as semantic
    from ipfs_datasets_py.logic.formalization.training_shared import (
        TrainingContractValidationError,
    )
    from ipfs_datasets_py.logic.proof_corpus.schemas import ArtifactEnvelope
    from ipfs_datasets_py.logic.proof_corpus.store import ProofCorpusStore
    from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json

    with pytest.raises(semantic.SemanticAPIError, match="mapping or a reviewed owner record"):
        semantic.corpus("not-a-manifest")
    with pytest.raises(semantic.SemanticAPIError, match="CompilerRequest"):
        semantic.compile(object())
    with pytest.raises(semantic.SemanticAPIError, match="DecompilerRequest"):
        semantic.decompile(object())
    with pytest.raises(semantic.SemanticAPIError, match="explicit translate"):
        semantic.translate(
            direction_id="A4-TYPED-002",
            source_cid=cid_for_dag_json({"pgir080": "source"}),
            target_cid=cid_for_dag_json({"pgir080": "target"}),
            reconstruction_mode="controlled_semantic",
        )
    with pytest.raises(TrainingContractValidationError, match="neither a positive pair"):
        semantic.pair({"schema_version": "unknown"})
    with pytest.raises(semantic.SemanticAPIError, match="verifier context"):
        semantic.verify({"claim": "producer-said-so"})

    fixture = REPO_ROOT / "tests" / "fixtures" / "legal_ir" / "proof_cache" / "us_code_552_record.json"
    record = json.loads(fixture.read_text(encoding="utf-8"))
    store = ProofCorpusStore()
    envelope = semantic.publish(store, ArtifactEnvelope.from_legal_record(record))
    assert envelope.content_cid
    replayed = semantic.publish(store, envelope)
    assert replayed.content_cid == envelope.content_cid
    assert store.get(envelope.content_cid).content_cid == envelope.content_cid
