"""Contract vectors for program-world domain adapters."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_obj,
    cid_for_structured,
    cid_vectors_document,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    SEMANTIC_INDEX_SCHEMA,
    STATE_SCHEMA,
    RepositoryState,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.models import (
    CAPSULE_COMPILER_VERSION,
    SEMANTIC_CAPSULE_SCHEMA,
    SEMANTIC_STATE_ROOT_SCHEMA,
    CapsuleFreshness,
    SemanticCapsule,
    SemanticStateProducer,
    SemanticStateRoot,
    SortedPairIndex,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_domain_adapters import (
    ADMITTED_DOMAIN_KINDS,
    DOMAIN_CAPABILITY_UNAVAILABLE_INTERFACE,
    DOMAIN_CAPABILITY_UNAVAILABLE_SCHEMA,
    PROGRAM_WORLD_DOMAIN_ADAPTER_INTERFACE,
    PROGRAM_WORLD_DOMAIN_ADAPTER_SCHEMA,
    SOURCE_AUTHORITY_DATASETS,
    SOURCE_AUTHORITY_KIT,
    UNSUPPORTED_DOMAIN_KINDS,
    DatasetStateAdapter,
    DomainAdapterError,
    DomainCapabilityUnavailable,
    DomainKind,
    DomainUnavailabilityReason,
    IntentIRAdapter,
    LegalIRAdapter,
    ProgramWorldDomainAdapter,
    ProofContextAdapter,
    RepositorySemanticStateAdapter,
    SecurityIRAdapter,
    SemanticCapsuleAdapter,
    UnsupportedDomainKind,
    VFSNamespaceAdapter,
    adapt_program_world_domain,
    adapter_for,
    domain_identity_preserved,
    unavailable_domain,
)


EXISTING_V1_SOURCE_HELLO_CID = (
    "bafkreibm6jg3ux5qumhcn2b3flc3tyu6dmlb4xa7u5bf44yegnrjhc4yeq"
)
EXISTING_V1_STRUCTURED_AB_CID = (
    "baguqeera2nrgvqykq7tppjscqiz3hructglwqzp2kueoijt4kqk4o2xxu5za"
)
EXISTING_V1_STRUCTURED_AB_BYTES = b'{"a":2,"b":1}'

_PACKAGE = (
    "ipfs_datasets_py.logic.software_contracts.semantic_state.program_domain_adapters"
)
_OPT_OUTS = {
    "IPFS_DATASETS_AUTO_INSTALL": "0",
    "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0",
    "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
    "IPFS_KIT_AUTO_INSTALL_DEPS": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def _cid(label: str) -> str:
    return cid_for_bytes(label.encode("utf-8"))


def _digest(label: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _hex_digest(label: str) -> str:
    import hashlib

    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _assert_adapter_retains(
    adapted: ProgramWorldDomainAdapter,
    *,
    domain_kind: str,
    domain_identity: str,
    source_authority: str,
    limitations_subset: tuple[str, ...],
) -> None:
    assert isinstance(adapted, ProgramWorldDomainAdapter)
    assert adapted.domain_kind == domain_kind
    assert adapted.domain_identity == domain_identity
    assert adapted.adapter_cid != adapted.domain_identity
    assert adapted.retains_domain_authority is True
    assert adapted.adapter_may_replace_domain_identity is False
    assert adapted.scope.source_authority == source_authority
    assert adapted.availability == "available"
    for item in limitations_subset:
        assert item in adapted.limitations
    round_trip = ProgramWorldDomainAdapter.from_dict(adapted.to_dict())
    assert round_trip == adapted
    assert round_trip.adapter_cid == cid_for_structured(adapted.identity_payload())


def _repository_state() -> RepositoryState:
    return RepositoryState("repo:adapter-example")


def _capsule() -> SemanticCapsule:
    return SemanticCapsule(
        stable_symbol_id=_cid("symbol"),
        version_cid=_cid("version"),
        semantic_index_schema="ipfs-datasets.software-contracts.semantic-index@2",
        extractor_version="1",
        source_cid=_cid("source"),
    )


def _root() -> SemanticStateRoot:
    index = SortedPairIndex(pairs=[("k", _cid("block"))])
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
    return SemanticStateRoot(
        repository_id="repo:example",
        producer=producer,
        symbol_fact_index_cid=index.index_cid,
        artifact_fact_index_cid=index.index_cid,
        semantic_link_index_cid=index.index_cid,
        symbol_node_index_cid=index.index_cid,
        capsule_index_cid=index.index_cid,
        environment_binding_set_cid=index.index_cid,
        analysis_limitation_index_cid=index.index_cid,
    )


def _intent_document():
    from ipfs_datasets_py.logic.intent_ir import (
        ControlEdgeKind,
        IntentAction,
        IntentControlEdge,
        IntentIRDocument,
        IntentKind,
        IntentModality,
        IntentStatement,
        ReviewStatus,
        SourceRef,
        StatementKind,
    )

    source = SourceRef(
        ref_id="source:skill-1",
        source_uri="https://example.test/skills/one",
        source_id="skill-1",
        source_revision="snapshot-abc",
        content_sha256="a" * 64,
        container_uri="hf://datasets/example/skills@snapshot-abc/bundle.sqlite#skill-1",
        container_sha256="b" * 64,
        review_status=ReviewStatus.TRUSTED_FIXTURE,
    )
    statements = (
        IntentStatement(
            statement_id="statement:goal",
            kind=StatementKind.GOAL,
            modality=IntentModality.INTENDED,
            normalized_text="Produce a verified artifact.",
            predicate="produce",
            arguments=("artifact",),
            source_ref_ids=(source.ref_id,),
            review_status=ReviewStatus.TRUSTED_FIXTURE,
        ),
        IntentStatement(
            statement_id="statement:precondition",
            kind=StatementKind.PRECONDITION,
            modality=IntentModality.REQUIRED,
            normalized_text="The input exists.",
            source_ref_ids=(source.ref_id,),
            review_status=ReviewStatus.TRUSTED_FIXTURE,
        ),
        IntentStatement(
            statement_id="statement:effect",
            kind=StatementKind.EFFECT,
            modality=IntentModality.ASSERTED,
            normalized_text="The artifact exists.",
            source_ref_ids=(source.ref_id,),
            review_status=ReviewStatus.TRUSTED_FIXTURE,
        ),
        IntentStatement(
            statement_id="statement:verify",
            kind=StatementKind.VERIFICATION,
            modality=IntentModality.REQUIRED,
            normalized_text="The artifact passes validation.",
            source_ref_ids=(source.ref_id,),
            review_status=ReviewStatus.TRUSTED_FIXTURE,
        ),
    )
    actions = (
        IntentAction(
            action_id="action:build",
            actor="agent",
            verb="build",
            object_refs=("artifact",),
            source_ref_ids=(source.ref_id,),
            precondition_ids=("statement:precondition",),
            effect_ids=("statement:effect",),
        ),
        IntentAction(
            action_id="action:validate",
            actor="agent",
            verb="validate",
            object_refs=("artifact",),
            source_ref_ids=(source.ref_id,),
            verification_ids=("statement:verify",),
        ),
    )
    return IntentIRDocument(
        document_id="intent:skill-1",
        title="Build and validate an artifact",
        intent_kind=IntentKind.PROCEDURE,
        sources=(source,),
        statements=statements,
        actions=actions,
        control_edges=(
            IntentControlEdge(
                edge_id="edge:build-validate",
                source_action_id="action:build",
                target_action_id="action:validate",
                kind=ControlEdgeKind.ON_SUCCESS,
                source_ref_ids=(source.ref_id,),
            ),
        ),
        entry_action_ids=("action:build",),
        terminal_action_ids=("action:validate",),
        tags=("fixture", "intent"),
    )


def _proof_graph():
    from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
        AuthorityCeiling,
        GraphEdgeKind,
        GraphNodeKind,
        HoleStatus,
        ProofGraphEdge,
        ProofGraphNode,
        ProofObligationGraph,
        ResourceBounds,
    )

    root = ProofGraphNode(
        node_id="node:root",
        kind=GraphNodeKind.ROOT,
        obligation_id="obl:root",
        label="root",
        status=HoleStatus.OPEN,
        authority=AuthorityCeiling.NONE,
    )
    leaf = ProofGraphNode(
        node_id="node:leaf",
        kind=GraphNodeKind.LEAF,
        obligation_id="obl:leaf",
        hole_id="hole:one",
        label="leaf",
        status=HoleStatus.OPEN,
        authority=AuthorityCeiling.CANDIDATE,
    )
    edge = ProofGraphEdge(
        edge_id="edge:root-leaf",
        source_node_id="node:root",
        target_node_id="node:leaf",
        kind=GraphEdgeKind.DEPENDS_ON,
        inference_rule="and_intro",
        reconstruction_method="kernel",
    )
    return ProofObligationGraph(
        graph_id="graph:adapter-1",
        formal_goal_id="formal:adapter",
        root_node_id="node:root",
        nodes=(root, leaf),
        edges=(edge,),
        tree_id="tree:repo@abc",
        bounds=ResourceBounds(max_nodes=32),
        status="open",
        authority=AuthorityCeiling.NONE,
        proof_claimed=False,
        completion_claimed=False,
    )


def test_public_interfaces_are_versioned() -> None:
    assert PROGRAM_WORLD_DOMAIN_ADAPTER_INTERFACE == "ProgramWorldDomainAdapter@1"
    assert DOMAIN_CAPABILITY_UNAVAILABLE_INTERFACE == "DomainCapabilityUnavailable@1"
    assert ProgramWorldDomainAdapter.SCHEMA == PROGRAM_WORLD_DOMAIN_ADAPTER_SCHEMA
    assert DomainCapabilityUnavailable.SCHEMA == DOMAIN_CAPABILITY_UNAVAILABLE_SCHEMA
    assert DomainCapabilityUnavailable.INTERFACE == DOMAIN_CAPABILITY_UNAVAILABLE_INTERFACE
    predicted = {
        "RepositorySemanticStateAdapter",
        "SemanticCapsuleAdapter",
        "LegalIRAdapter",
        "SecurityIRAdapter",
        "IntentIRAdapter",
        "ProofContextAdapter",
        "DatasetStateAdapter",
        "VFSNamespaceAdapter",
    }
    import ipfs_datasets_py.logic.software_contracts.semantic_state.program_domain_adapters as module

    assert predicted <= set(module.__all__)
    for kind in DomainKind:
        assert adapter_for(kind.value) is not None
        assert kind.value in ADMITTED_DOMAIN_KINDS


def test_public_api_import_does_not_reexport_domain_types() -> None:
    import ipfs_datasets_py.logic.software_contracts.semantic_state.program_domain_adapters as module

    banned = {
        "RepositoryState",
        "SemanticCapsule",
        "SecurityIR",
        "IntentIRDocument",
        "ProofObligationGraph",
        "NamespaceRouter",
        "ModalIRDocument",
    }
    leaked = banned.intersection(module.__all__)
    assert not leaked


def test_adapter_module_import_is_hermetic_and_does_not_load_domain_packages() -> None:
    script = f"""\
import json
import os
import sys
import threading

before = dict(os.environ)
effects = []

def forbidden(name):
    def call(*args, **kwargs):
        effects.append(name)
        raise AssertionError(f"forbidden import side effect: {{name}}")
    return call

os.system = forbidden("os.system")
_orig_thread_start = threading.Thread.start

def _thread_start(self, *args, **kwargs):
    effects.append("threading.Thread.start")
    raise AssertionError("forbidden import side effect: threading.Thread.start")

threading.Thread.start = _thread_start

def audit(event, args):
    if event == "open" and len(args) > 2:
        flags = args[2]
        if isinstance(flags, int) and flags & (
            os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        ):
            effects.append("write:" + str(args[0]))
            raise AssertionError("forbidden import write")
    if event in {{
        "os.mkdir",
        "os.remove",
        "os.rmdir",
        "os.rename",
        "os.replace",
        "socket.connect",
        "subprocess.Popen",
    }}:
        effects.append(event)
        raise AssertionError(f"forbidden import side effect: {{event}}")

sys.addaudithook(audit)
import {_PACKAGE} as adapters
assert adapters.PROGRAM_WORLD_DOMAIN_ADAPTER_INTERFACE == "ProgramWorldDomainAdapter@1"
loaded = set(sys.modules)
banned = {{
    "ipfs_datasets_py.logic.legal_ir",
    "ipfs_datasets_py.logic.legal_ir.adapter",
    "ipfs_datasets_py.logic.security_ir",
    "ipfs_datasets_py.logic.security_ir.model",
    "ipfs_datasets_py.logic.intent_ir",
    "ipfs_datasets_py.logic.intent_ir.schema",
    "ipfs_datasets_py.logic.ui_ux_ir",
    "ipfs_datasets_py.logic.software_verification.tactician.contracts",
    "ipfs_kit_py.core.vfs",
    "ipfs_kit_py.core.vfs.namespace",
    "ipfs_kit_py.core.vfs.service",
}}
assert not (loaded & banned), sorted(loaded & banned)
assert os.environ == before
assert not effects
print(json.dumps({{"ok": True}}, sort_keys=True))
"""
    environment = dict(os.environ)
    environment.update(_OPT_OUTS)
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert json.loads(result.stdout.splitlines()[-1]) == {"ok": True}


def test_existing_v1_content_vectors_remain_byte_identical() -> None:
    assert cid_for_bytes(b"hello") == EXISTING_V1_SOURCE_HELLO_CID
    assert canonical_dag_json_bytes({"b": 1, "a": 2}) == EXISTING_V1_STRUCTURED_AB_BYTES
    assert cid_for_obj({"a": 2, "b": 1}) == EXISTING_V1_STRUCTURED_AB_CID
    live = cid_vectors_document()
    by_id = {item["id"]: item for item in live["vectors"]}
    assert by_id["source.hello"]["expected_cid"] == EXISTING_V1_SOURCE_HELLO_CID
    assert by_id["structured.simple_map"]["expected_cid"] == EXISTING_V1_STRUCTURED_AB_CID


def test_existing_semantic_state_root_v1_encoder_is_unchanged() -> None:
    root = _root()
    payload = root.identity_payload()
    assert payload["schema"] == SEMANTIC_STATE_ROOT_SCHEMA
    assert root.root_cid == cid_for_structured(payload)
    before = dict(payload)
    adapted = DatasetStateAdapter().adapt(root)
    assert isinstance(adapted, ProgramWorldDomainAdapter)
    assert root.identity_payload() == before
    assert root.root_cid == cid_for_structured(before)
    assert adapted.domain_identity == root.root_cid


def test_repository_semantic_state_identity_is_preserved() -> None:
    state = _repository_state()
    before_payload = state.to_dict()
    before_identity_payload = state.identity_payload()
    before_cid = state.state_cid
    adapted = RepositorySemanticStateAdapter().adapt(state)
    assert state.to_dict() == before_payload
    assert state.identity_payload() == before_identity_payload
    assert state.state_cid == before_cid
    assert before_payload["schema"] == SEMANTIC_INDEX_SCHEMA
    assert before_identity_payload["schema"] == STATE_SCHEMA
    assert adapted.domain_schema == STATE_SCHEMA
    _assert_adapter_retains(
        adapted,
        domain_kind=DomainKind.REPOSITORY_SEMANTIC_STATE.value,
        domain_identity=before_cid,
        source_authority=SOURCE_AUTHORITY_DATASETS,
        limitations_subset=("adapter_does_not_recompute_state_cid",),
    )
    assert domain_identity_preserved(
        state, adapted, before_payload=before_payload, before_identity=before_cid
    )


def test_semantic_capsule_identity_and_freshness_are_retained() -> None:
    capsule = _capsule()
    before_payload = capsule.to_dict()
    before_cid = capsule.capsule_cid
    assessment = CapsuleFreshness(
        capsule_cid=before_cid,
        root_cid=_cid("root"),
        capsule_schema=SEMANTIC_CAPSULE_SCHEMA,
        capsule_compiler_version=CAPSULE_COMPILER_VERSION,
        producer_repository_state_cid=_cid("state"),
        relevant_binding_projection_cid=None,
        freshness="fresh",
        admission="exact_substitute",
        caveats=("visible_caveat",),
    )
    adapted = SemanticCapsuleAdapter().adapt(capsule, freshness=assessment)
    assert capsule.to_dict() == before_payload
    assert capsule.capsule_cid == before_cid
    assert adapted.freshness.state == "fresh"
    assert adapted.freshness.assessment_cid == assessment.assessment_cid
    assert adapted.freshness.producer_state_cid == assessment.producer_repository_state_cid
    assert "visible_caveat" in adapted.freshness.caveats
    assert "freshness_is_separate_from_capsule_identity" in adapted.limitations
    _assert_adapter_retains(
        adapted,
        domain_kind=DomainKind.SEMANTIC_CAPSULE.value,
        domain_identity=before_cid,
        source_authority=SOURCE_AUTHORITY_DATASETS,
        limitations_subset=("adapter_does_not_recompute_capsule_cid",),
    )


def test_legal_ir_public_digest_is_preserved_without_recompilation() -> None:
    digest = _hex_digest("legal-modal-document")
    payload = {
        "sample_id": "legal:usc-fixture",
        "declaration_digest": digest,
        "schema_version": "legal-ir/v1",
        "limitations": ("raw_source_bodies_are_externalized",),
    }
    before = dict(payload)
    adapted = LegalIRAdapter().adapt(payload)
    assert payload == before
    _assert_adapter_retains(
        adapted,
        domain_kind=DomainKind.LEGAL_IR.value,
        domain_identity=digest,
        source_authority=SOURCE_AUTHORITY_DATASETS,
        limitations_subset=(
            "adapter_does_not_replace_modal_canonical_hash",
            "embeddings_are_not_legal_identity",
        ),
    )


def test_security_ir_cid_is_preserved() -> None:
    from ipfs_datasets_py.logic.security_ir.model import SecurityIR

    declaration = SecurityIR(declaration_id="security:adapter-test")
    before_payload = declaration.to_dict()
    before_cid = declaration.cid
    adapted = SecurityIRAdapter().adapt(declaration)
    assert declaration.to_dict() == before_payload
    assert declaration.cid == before_cid
    _assert_adapter_retains(
        adapted,
        domain_kind=DomainKind.SECURITY_IR.value,
        domain_identity=before_cid,
        source_authority=SOURCE_AUTHORITY_DATASETS,
        limitations_subset=("adapter_does_not_decide_authorization",),
    )


def test_intent_ir_digest_is_preserved_without_rehashing_payload() -> None:
    from ipfs_datasets_py.logic.intent_ir import intent_ir_sha256

    document = _intent_document()
    document.validate()
    before_payload = document.to_dict()
    before_digest = intent_ir_sha256(document)
    adapted = IntentIRAdapter().adapt(document)
    assert document.to_dict() == before_payload
    assert intent_ir_sha256(document) == before_digest
    _assert_adapter_retains(
        adapted,
        domain_kind=DomainKind.INTENT_IR.value,
        domain_identity=before_digest,
        source_authority=SOURCE_AUTHORITY_DATASETS,
        limitations_subset=("adapter_does_not_authorize_or_execute",),
    )


def test_proof_context_identity_is_preserved_and_cannot_claim_proof() -> None:
    graph = _proof_graph()
    before_payload = graph.to_dict()
    before_id = graph.content_id
    adapted = ProofContextAdapter().adapt(graph)
    assert graph.to_dict() == before_payload
    assert graph.content_id == before_id
    assert graph.proof_claimed is False
    _assert_adapter_retains(
        adapted,
        domain_kind=DomainKind.PROOF_CONTEXT.value,
        domain_identity=before_id,
        source_authority=SOURCE_AUTHORITY_DATASETS,
        limitations_subset=("adapter_does_not_claim_proof_or_completion",),
    )
    claimed = dict(graph.to_record())
    claimed["proof_claimed"] = True
    with pytest.raises(DomainAdapterError):
        ProofContextAdapter().adapt(claimed)


def test_dataset_state_root_cid_is_preserved() -> None:
    root = _root()
    before_payload = root.to_dict()
    before_cid = root.root_cid
    adapted = DatasetStateAdapter().adapt(root)
    assert root.to_dict() == before_payload
    assert root.root_cid == before_cid
    _assert_adapter_retains(
        adapted,
        domain_kind=DomainKind.DATASET_STATE.value,
        domain_identity=before_cid,
        source_authority=SOURCE_AUTHORITY_DATASETS,
        limitations_subset=("operational_root_fields_remain_excluded",),
    )


def test_vfs_namespace_reference_retains_kit_authority_without_storage() -> None:
    snapshot = _cid("vfs-snapshot")
    reference = {
        "namespace_id": "ns:default",
        "snapshot_cid": snapshot,
        "schema": "ipfs_kit_py/core/vfs/namespace/namespace-router@1",
        "generation": 7,
        "freshness": "fresh",
    }
    before = dict(reference)
    adapted = VFSNamespaceAdapter().adapt(reference)
    assert reference == before
    assert adapted.scope.namespace_id == "ns:default"
    assert adapted.scope.source_authority == SOURCE_AUTHORITY_KIT
    assert adapted.freshness.generation == 7
    assert adapted.freshness.state == "fresh"
    _assert_adapter_retains(
        adapted,
        domain_kind=DomainKind.VFS_NAMESPACE.value,
        domain_identity=snapshot,
        source_authority=SOURCE_AUTHORITY_KIT,
        limitations_subset=(
            "adapter_does_not_own_vfs_storage",
            "generation_is_freshness_not_domain_identity",
        ),
    )


def test_vfs_adapter_refuses_live_mutation_surfaces() -> None:
    class _LiveVFS:
        namespace_id = "ns:default"
        snapshot_cid = _cid("snap")

        def put(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("must not mutate")

    with pytest.raises(DomainAdapterError, match="live VFS"):
        VFSNamespaceAdapter().adapt(_LiveVFS())


@pytest.mark.parametrize("kind", sorted(ADMITTED_DOMAIN_KINDS))
def test_admitted_domains_return_typed_unavailability_when_source_absent(
    kind: str,
) -> None:
    result = adapt_program_world_domain(kind, None)
    assert isinstance(result, DomainCapabilityUnavailable)
    assert result.domain_kind == kind
    assert result.reason == DomainUnavailabilityReason.SOURCE_ABSENT.value
    assert result.availability == "unavailable"
    assert "absent_domains_are_never_simulated" in result.limitations
    assert DomainCapabilityUnavailable.from_dict(result.to_dict()) == result


@pytest.mark.parametrize("kind", sorted(UNSUPPORTED_DOMAIN_KINDS))
def test_unsupported_domain_matrix_never_simulates_or_reimplements(
    kind: str,
) -> None:
    fake_payload = {
        "domain_identity": _cid(f"fake-{kind}"),
        "simulated": True,
        "reconstructed_payload": {"kind": kind},
    }
    result = adapt_program_world_domain(kind, fake_payload)
    assert isinstance(result, DomainCapabilityUnavailable)
    assert result.domain_kind == kind
    assert result.availability == "unavailable"
    assert "absent_domains_are_never_simulated" in result.limitations
    dumped = result.to_dict()
    assert "simulated" not in dumped
    assert "reconstructed_payload" not in dumped
    assert dumped.get("domain_identity") is None
    if kind in {
        UnsupportedDomainKind.REPOSITORY_WORLD_MODEL.value,
        UnsupportedDomainKind.PROOF_CARRYING_PROCEDURE_COMPILER.value,
        UnsupportedDomainKind.VERIFIED_RESIDUAL_INTELLIGENCE_FOUNDRY.value,
        UnsupportedDomainKind.AUTONOMOUS_META_CONTROLLER.value,
    }:
        assert result.reason == DomainUnavailabilityReason.HISTORICAL_ONLY.value
    elif kind in {
        "javascript",
        "typescript",
        "rust",
        "c",
        "cpp",
        "java",
        "shell",
    }:
        assert result.reason == DomainUnavailabilityReason.LANGUAGE_UNAVAILABLE.value
    assert adapter_for(kind) is None


def test_unknown_domain_is_typed_unavailable() -> None:
    result = unavailable_domain("not-a-domain")
    assert result.reason == DomainUnavailabilityReason.UNSUPPORTED_DOMAIN.value
    assert result.availability == "unavailable"


def test_adapter_rejects_embedding_and_payload_smuggling() -> None:
    with pytest.raises(DomainAdapterError, match="non-identity"):
        RepositorySemanticStateAdapter().adapt(
            {
                "state_cid": _cid("state"),
                "embedding": [0.1, 0.2],
            }
        )
    with pytest.raises(DomainAdapterError, match="non-identity"):
        LegalIRAdapter().adapt(
            {
                "declaration_digest": _digest("legal"),
                "payload": {"modal_ir": {}},
            }
        )


def test_dispatcher_routes_admitted_kinds_and_skips_unsupported_sources() -> None:
    state = _repository_state()
    adapted = adapt_program_world_domain("repository_semantic_state", state)
    assert isinstance(adapted, ProgramWorldDomainAdapter)
    assert adapted.domain_identity == state.state_cid
    skipped = adapt_program_world_domain("ui_ux_ir", state)
    assert isinstance(skipped, DomainCapabilityUnavailable)
    assert skipped.domain_kind == "ui_ux_ir"


def test_closed_records_reject_unknown_fields_and_authority_weakening() -> None:
    adapted = RepositorySemanticStateAdapter().adapt(_repository_state())
    payload = adapted.to_dict()
    payload["extra"] = True
    with pytest.raises(DomainAdapterError):
        ProgramWorldDomainAdapter.from_dict(payload)
    weakened = adapted.to_dict()
    weakened["retains_domain_authority"] = False
    with pytest.raises(DomainAdapterError):
        ProgramWorldDomainAdapter.from_dict(weakened)
    replacement = adapted.to_dict()
    replacement["adapter_may_replace_domain_identity"] = True
    with pytest.raises(DomainAdapterError):
        ProgramWorldDomainAdapter.from_dict(replacement)
