from __future__ import annotations

from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.intent_ir.graphrag.corpus_projector import (
    CorpusProjector,
)
from ipfs_datasets_py.logic.intent_ir.graphrag.semantic_projector import (
    SEMANTIC_GRAPH_SCHEMA_VERSION,
    SEMANTIC_ONTOLOGY,
    SEMANTIC_ONTOLOGY_VERSION,
    SemanticEdgeClass,
    SemanticEdgeType,
    SemanticGraphValidationError,
    SemanticIntentGraphProjector,
    SemanticNodeType,
    SemanticProjectionError,
)
from ipfs_datasets_py.logic.intent_ir.schema import (
    ControlEdgeKind,
    IntentAction,
    IntentControlEdge,
    IntentIRDocument,
    IntentKind,
    IntentModality,
    IntentStatement,
    NodeGrounding,
    ReviewStatus,
    SourceRef,
    StatementKind,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.skillcenter import (
    SkillCenterSkillRecord,
)
from ipfs_datasets_py.logic.ir_core.identity import cid_v1


class RecordingStore:
    def __init__(self) -> None:
        self.blocks: dict[str, tuple[bytes, str]] = {}

    def put_bytes(self, payload: bytes, *, media_type: str) -> str:
        cid = cid_v1(payload)
        self.blocks[cid] = (payload, media_type)
        return cid


def _document() -> IntentIRDocument:
    source = SourceRef(
        ref_id="source:fixture",
        source_uri="https://example.test/skills/fixture",
        source_id="primary-fixture",
        source_revision="revision-1",
        content_sha256="a" * 64,
        container_uri="hf://datasets/example/fixtures@revision-1/bundle.sqlite",
        container_sha256="b" * 64,
        review_status=ReviewStatus.TRUSTED_FIXTURE,
    )
    statements = (
        IntentStatement(
            statement_id="statement:goal",
            kind=StatementKind.GOAL,
            modality=IntentModality.INTENDED,
            normalized_text="Produce a verified artifact.",
            source_ref_ids=(source.ref_id,),
            predicate="artifact.produced",
            arguments=("artifact",),
            review_status=ReviewStatus.TRUSTED_FIXTURE,
        ),
        IntentStatement(
            statement_id="statement:precondition",
            kind=StatementKind.PRECONDITION,
            modality=IntentModality.REQUIRED,
            normalized_text="The source input exists.",
            source_ref_ids=(source.ref_id,),
            review_status=ReviewStatus.TRUSTED_FIXTURE,
        ),
        IntentStatement(
            statement_id="statement:guard",
            kind=StatementKind.GUARD,
            modality=IntentModality.REQUIRED,
            normalized_text="Validation is enabled.",
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
            statement_id="statement:failure",
            kind=StatementKind.FAILURE,
            modality=IntentModality.PROHIBITED,
            normalized_text="Invalid output must not be published.",
            source_ref_ids=(source.ref_id,),
            review_status=ReviewStatus.TRUSTED_FIXTURE,
        ),
        IntentStatement(
            statement_id="statement:verify",
            kind=StatementKind.VERIFICATION,
            modality=IntentModality.RECOMMENDED,
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
            tool_refs=("builder",),
            input_refs=("source-input",),
            output_refs=("candidate-artifact",),
            precondition_ids=("statement:precondition",),
            effect_ids=("statement:effect",),
        ),
        IntentAction(
            action_id="action:validate",
            actor="agent",
            verb="validate",
            object_refs=("artifact",),
            source_ref_ids=(source.ref_id,),
            tool_refs=("validator",),
            verification_ids=("statement:verify",),
        ),
    )
    return IntentIRDocument(
        document_id="intent:fixture",
        title="Build and validate an artifact",
        intent_kind=IntentKind.PROCEDURE,
        sources=(source,),
        statements=statements,
        actions=actions,
        control_edges=(
            IntentControlEdge(
                edge_id="control:build-validate",
                source_action_id="action:build",
                target_action_id="action:validate",
                kind=ControlEdgeKind.CONDITIONAL,
                guard_statement_id="statement:guard",
                source_ref_ids=(source.ref_id,),
            ),
        ),
        entry_action_ids=("action:build",),
        terminal_action_ids=("action:validate",),
        tags=("fixture", "semantic"),
    )


def _corpus_record() -> SkillCenterSkillRecord:
    return SkillCenterSkillRecord(
        skill_id="skill-fixture",
        domain="testing",
        profile="testing",
        source_type="github",
        source_url="https://example.test/skills/fixture",
        title="Semantic fixture",
        overall_score=4.0,
        skill_kind="github",
        language="en",
        source_id="source-fixture",
        primary_source_id="primary-fixture",
        metadata_yaml='license_spdx: "MIT"\n',
        skill_md="# Goal\n\nProduce a verified artifact.\n",
        library_md="",
        dataset_id="example/fixtures",
        dataset_revision="revision-1",
        repository_file="fixtures.sqlite",
        bundle_sha256="b" * 64,
    )


def test_versioned_ontology_separates_similarity_from_semantic_edges() -> None:
    assert SEMANTIC_ONTOLOGY.version == SEMANTIC_ONTOLOGY_VERSION
    assert set(SEMANTIC_ONTOLOGY.node_types) == {
        item.value for item in SemanticNodeType
    }
    assert set(SEMANTIC_ONTOLOGY.edge_types) == {
        item.value for item in SemanticEdgeType
    }
    SEMANTIC_ONTOLOGY.validate_edge(
        SemanticEdgeType.USES,
        SemanticNodeType.ACTION,
        SemanticNodeType.TOOL,
        edge_class=SemanticEdgeClass.SEMANTIC,
    )
    with pytest.raises(SemanticGraphValidationError, match="classified"):
        SEMANTIC_ONTOLOGY.validate_edge(
            SemanticEdgeType.SIMILAR_TO,
            SemanticNodeType.ACTION,
            SemanticNodeType.ACTION,
            edge_class=SemanticEdgeClass.SEMANTIC,
        )


def test_projector_preserves_semantics_modalities_and_grounding() -> None:
    store = RecordingStore()
    graph = SemanticIntentGraphProjector(store).project(_document())

    assert graph.schema_version == SEMANTIC_GRAPH_SCHEMA_VERSION
    assert graph.ontology_version == SEMANTIC_ONTOLOGY_VERSION
    assert graph.graph_cid == cid_v1(graph.canonical_bytes())
    assert graph.graph_cid in store.blocks
    assert graph.similarity_edges == ()
    assert all(
        edge.edge_class is not SemanticEdgeClass.SIMILARITY
        for edge in graph.semantic_edges
    )
    assert {
        SemanticNodeType.INTENT_DOCUMENT,
        SemanticNodeType.SOURCE_REFERENCE,
        SemanticNodeType.GOAL,
        SemanticNodeType.STATEMENT,
        SemanticNodeType.ACTION,
        SemanticNodeType.ACTOR,
        SemanticNodeType.RESOURCE,
        SemanticNodeType.TOOL,
        SemanticNodeType.INPUT,
        SemanticNodeType.OUTPUT,
        SemanticNodeType.FAILURE,
        SemanticNodeType.VERIFICATION_CRITERION,
        SemanticNodeType.FORMAL_SYMBOL,
    } <= {node.node_type for node in graph.nodes}
    assert {
        SemanticEdgeType.HAS_GOAL,
        SemanticEdgeType.REQUIRES,
        SemanticEdgeType.GUARDED_BY,
        SemanticEdgeType.PERFORMS,
        SemanticEdgeType.USES,
        SemanticEdgeType.CONSUMES,
        SemanticEdgeType.PRODUCES,
        SemanticEdgeType.CAUSES,
        SemanticEdgeType.VERIFIED_BY,
        SemanticEdgeType.CONDITIONAL,
        SemanticEdgeType.GROUNDED_IN,
        SemanticEdgeType.LOWERS_TO,
    } <= {edge.edge_type for edge in graph.semantic_edges}

    statement_nodes = {
        node.properties.get("statement_id"): node
        for node in graph.nodes
        if "statement_id" in node.properties
    }
    assert statement_nodes["statement:goal"].properties["modality"] == "intended"
    assert (
        statement_nodes["statement:failure"].properties["modality"]
        == "prohibited"
    )
    assert (
        statement_nodes["statement:verify"].properties["modality"]
        == "recommended"
    )
    control = next(
        edge
        for edge in graph.semantic_edges
        if edge.edge_class is SemanticEdgeClass.CONTROL
    )
    assert control.edge_type is SemanticEdgeType.CONDITIONAL
    assert control.properties["control_edge_kind"] == "conditional"

    for node in graph.nodes:
        assert node.intent_ir_digest == graph.intent_ir_digest
        assert node.graph_digest == graph.graph_digest
        assert node.source_ref_ids
    for edge in graph.semantic_edges:
        assert edge.intent_ir_digest == graph.intent_ir_digest
        assert edge.graph_digest == graph.graph_digest
        assert edge.source_ref_ids


@pytest.mark.parametrize(
    ("control_kind", "projected_kind"),
    (
        (ControlEdgeKind.NEXT, SemanticEdgeType.NEXT),
        (ControlEdgeKind.ON_SUCCESS, SemanticEdgeType.ON_SUCCESS),
        (ControlEdgeKind.ON_FAILURE, SemanticEdgeType.ON_FAILURE),
        (ControlEdgeKind.CONDITIONAL, SemanticEdgeType.CONDITIONAL),
        (ControlEdgeKind.RETRY, SemanticEdgeType.RETRIES),
        (ControlEdgeKind.PARALLEL, SemanticEdgeType.PARALLEL_WITH),
        (ControlEdgeKind.JOIN, SemanticEdgeType.JOINS),
    ),
)
def test_every_control_edge_kind_is_preserved(
    control_kind: ControlEdgeKind, projected_kind: SemanticEdgeType
) -> None:
    document = _document()
    control = replace(
        document.control_edges[0],
        kind=control_kind,
        guard_statement_id=(
            "statement:guard"
            if control_kind is ControlEdgeKind.CONDITIONAL
            else ""
        ),
    )
    graph = SemanticIntentGraphProjector().project(
        replace(document, control_edges=(control,))
    )

    projected = next(
        edge
        for edge in graph.semantic_edges
        if edge.edge_class is SemanticEdgeClass.CONTROL
    )
    assert projected.edge_type is projected_kind
    assert projected.properties["control_edge_kind"] == control_kind.value


def test_rebuild_is_deterministic_for_canonical_set_orderings() -> None:
    document = _document()
    reordered = replace(
        document,
        statements=tuple(reversed(document.statements)),
        actions=tuple(reversed(document.actions)),
        tags=tuple(reversed(document.tags)),
    )

    first = SemanticIntentGraphProjector().project(document)
    second = SemanticIntentGraphProjector().project(reordered)

    assert first == second
    assert first.graph_digest == second.graph_digest
    assert first.graph_cid == second.graph_cid
    assert first.canonical_bytes() == second.canonical_bytes()


def test_optional_corpus_binding_requires_and_records_exact_evidence() -> None:
    record = _corpus_record()
    corpus = CorpusProjector(RecordingStore()).project(record)
    document = _document()

    with pytest.raises(SemanticProjectionError, match="absent"):
        SemanticIntentGraphProjector().project(document, corpus)

    source = replace(
        document.sources[0], content_sha256=record.content_sha256
    )
    with pytest.raises(SemanticProjectionError, match="exact grounding"):
        SemanticIntentGraphProjector().project(
            replace(
                document,
                sources=(
                    replace(
                        source,
                        source_id="unrelated-source",
                        source_uri="https://unrelated.test/source",
                    ),
                ),
            ),
            corpus,
        )

    graph = SemanticIntentGraphProjector().project(
        replace(document, sources=(source,)), corpus
    )

    assert graph.corpus_graph_digest == corpus.graph_digest
    assert graph.corpus_graph_cid == corpus.graph_cid
    source_node = next(
        node
        for node in graph.nodes
        if node.node_type is SemanticNodeType.SOURCE_REFERENCE
    )
    assert source_node.properties["corpus_node_id"]


def test_projector_rejects_inferred_or_dangling_projections() -> None:
    document = _document()
    inferred = replace(
        document.statements[0], grounding=NodeGrounding.INFERRED
    )
    with pytest.raises(SemanticProjectionError, match="ungrounded"):
        SemanticIntentGraphProjector().project(
            replace(
                document,
                statements=(inferred, *document.statements[1:]),
            )
        )

    dangling = replace(
        document.control_edges[0], target_action_id="action:missing"
    )
    with pytest.raises(SemanticProjectionError, match="unknown ids"):
        SemanticIntentGraphProjector().project(
            replace(document, control_edges=(dangling,))
        )


def test_artifact_rejects_dangling_edges_and_tampered_identity() -> None:
    graph = SemanticIntentGraphProjector().project(_document())
    edge = graph.semantic_edges[0]

    with pytest.raises(SemanticGraphValidationError, match="dangling"):
        replace(
            graph,
            graph_cid="",
            semantic_edges=(
                replace(edge, target="semantic:node:action:missing"),
                *graph.semantic_edges[1:],
            ),
        )
    with pytest.raises(SemanticGraphValidationError, match="intent_ir_cid"):
        replace(graph, graph_cid="", intent_ir_cid=cid_v1(b"other intent"))


def test_store_must_return_the_fixed_content_address() -> None:
    class BadStore:
        def put_bytes(self, payload: bytes, *, media_type: str) -> str:
            return cid_v1(b"different bytes")

    with pytest.raises(SemanticProjectionError, match="does not match"):
        SemanticIntentGraphProjector(BadStore()).project(_document())
