"""JSON Schema vectors for closed semantic-state payload envelopes."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import (
    stable_symbol_id,
    symbol_version_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    ArtifactRecord,
    SymbolKind,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    AnalysisLimitation,
    ArtifactFactNode,
    BindingKind,
    BindingScope,
    CapsuleFreshness,
    EnvironmentBinding,
    EnvironmentBindingSet,
    FreshnessState,
    AdmissionDecision,
    NormalizedTestStatus,
    OracleApplicability,
    RelevantBindingProjection,
    SelectionPolicy,
    SemanticCapsule,
    SemanticStateProducer,
    SemanticStateRoot,
    SortedPairIndex,
    SymbolFactNode,
    SymbolMerkleNode,
    TestOracleComparison,
    TestOutcome,
    TestRunFacts,
    TestSelection,
    VerifiedSourceEvidence,
)

jsonschema = pytest.importorskip("jsonschema")


SCHEMA_PATH = (
    Path(__file__).resolve().parents[5]
    / "ipfs_datasets_py"
    / "logic"
    / "software_contracts"
    / "semantic_state"
    / "schemas"
    / "semantic-state.payload.schema.json"
)


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _symbol() -> SymbolRecord:
    stable = stable_symbol_id(
        "repo:example",
        "python",
        "pkg/mod.py",
        "pkg.mod.answer",
        SymbolKind.FUNCTION,
        "pkg",
    )
    node = ast.parse("def answer():\n    return 1\n").body[0]
    version = symbol_version_cid(stable, node)
    return SymbolRecord(
        stable,
        version,
        "repo:example",
        "python",
        "pkg/mod.py",
        "pkg.mod.answer",
        SymbolKind.FUNCTION,
        "pkg",
        cid_for_bytes(b"source"),
        None,
        AnalysisConfidence.EXACT,
        normalized_ast=node,
    )


def _sample_payloads() -> list[dict]:
    symbol = _symbol()
    fact = SymbolFactNode(symbol=symbol)
    artifact = ArtifactFactNode(
        artifact=ArtifactRecord("artifact:db", "external", "config/db.json")
    )
    capsule = SemanticCapsule(
        stable_symbol_id=symbol.stable_id,
        version_cid=symbol.version_cid,
        semantic_index_schema="ipfs-datasets.software-contracts.semantic-index@2",
        extractor_version="1",
        source_slice_path="pkg/mod.py",
        source_cid=symbol.source_cid,
        symbol_fact_cid=fact.fact_cid,
    )
    node = SymbolMerkleNode(
        stable_symbol_id=symbol.stable_id,
        version_cid=symbol.version_cid,
        symbol_fact_cid=fact.fact_cid,
        capsule_cid=capsule.capsule_cid,
    )
    index = SortedPairIndex(
        pairs=[
            (symbol.stable_id, fact.fact_cid),
            ("artifact:db", artifact.fact_cid),
        ]
    )
    binding = EnvironmentBinding(
        binding_id="toolchain:python",
        kind=BindingKind.PYTHON_TOOLCHAIN,
        version_cid=_cid("py312"),
        scope=BindingScope.GLOBAL,
        extraction_authority="injected",
    )
    binding_set = EnvironmentBindingSet(bindings=[binding])
    projection = RelevantBindingProjection(
        stable_symbol_id=symbol.stable_id,
        binding_ids=[binding.binding_id],
        includes_global=True,
        binding_set_cid=binding_set.binding_set_cid,
    )
    producer = SemanticStateProducer(
        repository_state_cid=_cid("state"),
        repository_snapshot_cid=_cid("snapshot"),
        git_commit_oid_or_null=None,
        git_tree_oid_or_null=None,
        source_manifest_cid=_cid("manifest"),
        semantic_index_schema="ipfs-datasets.software-contracts.semantic-index@2",
        extractor_name="python-cpython-ast",
        extractor_version="1",
    )
    root = SemanticStateRoot(
        repository_id="repo:example",
        producer=producer,
        symbol_fact_index_cid=index.index_cid,
        artifact_fact_index_cid=index.index_cid,
        semantic_link_index_cid=index.index_cid,
        symbol_node_index_cid=index.index_cid,
        capsule_index_cid=index.index_cid,
        environment_binding_set_cid=binding_set.binding_set_cid,
        analysis_limitation_index_cid=index.index_cid,
    )
    policy = SelectionPolicy(policy_id="default")
    selection = TestSelection(
        previous_root_cid=None,
        current_root_cid=root.root_cid,
        selected_pytest_node_ids=["tests/test_mod.py::test_answer"],
        policy_cid=policy.policy_cid,
    )
    outcome = TestOutcome(
        node_id="tests/test_mod.py::test_answer",
        status=NormalizedTestStatus.PASSED,
    )
    facts = TestRunFacts(run_id="full-1", outcomes=[outcome])
    oracle = TestOracleComparison(
        selection_cid=selection.selection_cid,
        baseline_facts_cid=facts.facts_cid,
        selected_facts_cid=facts.facts_cid,
        candidate_full_facts_cid=facts.facts_cid,
        applicability=OracleApplicability.NOT_APPLICABLE,
        selected_count=1,
        full_count=1,
    )
    freshness = CapsuleFreshness(
        capsule_cid=capsule.capsule_cid,
        root_cid=root.root_cid,
        capsule_schema=capsule.capsule_schema,
        capsule_compiler_version=capsule.capsule_compiler_version,
        producer_repository_state_cid=producer.repository_state_cid,
        relevant_binding_projection_cid=projection.projection_cid,
        freshness=FreshnessState.FRESH,
        admission=AdmissionDecision.EXACT_SUBSTITUTE,
    )
    evidence = VerifiedSourceEvidence(
        stable_symbol_id=symbol.stable_id,
        producer_state_cid=producer.repository_state_cid,
        source_cid=symbol.source_cid or _cid("source"),
        source_slice_path="pkg/mod.py",
        start_offset=0,
        end_offset=10,
        extractor_name="python-cpython-ast",
        extractor_version="1",
    )
    limitation = AnalysisLimitation(
        code="opaque_native",
        message="native extension call",
    )
    return [
        root.to_dict(),
        producer.to_dict(),
        index.to_dict(),
        fact.to_dict(),
        artifact.to_dict(),
        capsule.to_dict(),
        node.to_dict(),
        binding.to_dict(),
        binding_set.to_dict(),
        projection.to_dict(),
        policy.to_dict(),
        selection.to_dict(),
        outcome.to_dict(),
        facts.to_dict(),
        oracle.to_dict(),
        freshness.to_dict(),
        evidence.to_dict(),
        limitation.to_dict(),
    ]


def test_payload_schema_is_valid_draft_2020_12() -> None:
    schema = _load_schema()
    jsonschema.Draft202012Validator.check_schema(schema)


def test_closed_payloads_validate_against_schema() -> None:
    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    for payload in _sample_payloads():
        validator.validate(payload)


def test_schema_rejects_unknown_fields_and_versions() -> None:
    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    root = _sample_payloads()[0]
    with_extra = dict(root)
    with_extra["history"] = []
    errors = list(validator.iter_errors(with_extra))
    assert errors

    bad_version = dict(root)
    bad_version["schema"] = "ipfs-datasets.software-contracts.semantic-state-root@99"
    errors = list(validator.iter_errors(bad_version))
    assert errors

    # Unknown top-level envelope shape must fail closed.
    errors = list(validator.iter_errors({"schema": "not-a-payload", "x": 1}))
    assert errors


def test_schema_file_is_packaged_next_to_models() -> None:
    assert SCHEMA_PATH.is_file()
    models_dir = SCHEMA_PATH.parents[1]
    assert (models_dir / "models.py").is_file()
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    assert "semantic-state-root@1" in text
    assert "additionalProperties" in text
