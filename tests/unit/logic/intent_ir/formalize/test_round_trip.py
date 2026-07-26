"""Proof-obligation and semantic round-trip tests for Intent formalization."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.backends.registry import (
    BackendRunnerOutput,
    CallableProofBackend,
    CompiledBackendRequest,
    ProofBackendRegistry,
)
from ipfs_datasets_py.logic.intent_ir.formalize.compiler import (
    INTENT_ACTION_VIEW_ID,
    INTENT_MODAL_VIEW_ID,
    INTENT_WORKFLOW_VIEW_ID,
    IntentFormalizationCompiler,
)
from ipfs_datasets_py.logic.intent_ir.formalize.decompiler import (
    DecompiledIntentReview,
    IntentDecompiler,
    IntentRoundTripReport,
    IntentSemanticMutationKind,
)
from ipfs_datasets_py.logic.intent_ir.formalize.obligations import (
    INTENT_SEMANTIC_ENCODING,
    IntentObligationKind,
    IntentProofAuthorityPolicy,
    IntentProofDisposition,
    IntentProofObligationError,
    IntentProofObligations,
    IntentProofPacket,
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
    SourceRef,
    StatementKind,
)
from ipfs_datasets_py.logic.ir_core.protocols import (
    AttemptStatus,
    BackendCapabilities,
    ExecutionBounds,
    QueryKind,
    ResultStatus,
)


def _document(*, opaque_goal: bool = False) -> IntentIRDocument:
    document = IntentIRDocument(
        document_id="intent:round-trip",
        title="Publish and archive a result",
        intent_kind=IntentKind.PROCEDURE,
        sources=(
            SourceRef(
                ref_id="source:one",
                source_uri="urn:test:one",
                source_id="one",
                source_revision="v1",
                content_sha256="a" * 64,
            ),
            SourceRef(
                ref_id="source:two",
                source_uri="urn:test:two",
                source_id="two",
                source_revision="v1",
                content_sha256="b" * 64,
            ),
        ),
        statements=(
            IntentStatement(
                statement_id="statement:goal",
                kind=StatementKind.GOAL,
                modality=IntentModality.INTENDED,
                normalized_text="Publish the result",
                predicate="" if opaque_goal else "publish",
                arguments=("result",),
                source_ref_ids=("source:one",),
            ),
            IntentStatement(
                statement_id="statement:assumption",
                kind=StatementKind.ASSUMPTION,
                modality=IntentModality.ASSERTED,
                normalized_text="The result exists",
                predicate="exists",
                arguments=("result",),
                source_ref_ids=("source:one",),
            ),
            IntentStatement(
                statement_id="statement:effect",
                kind=StatementKind.EFFECT,
                modality=IntentModality.ASSERTED,
                normalized_text="The result is published",
                predicate="published",
                arguments=("result",),
                source_ref_ids=("source:two",),
            ),
            IntentStatement(
                statement_id="statement:guard",
                kind=StatementKind.GUARD,
                modality=IntentModality.REQUIRED,
                normalized_text="Publication is allowed",
                predicate="allowed",
                arguments=("result",),
                source_ref_ids=("source:one",),
            ),
            IntentStatement(
                statement_id="statement:invariant",
                kind=StatementKind.INVARIANT,
                modality=IntentModality.REQUIRED,
                normalized_text="The source remains available",
                predicate="available",
                arguments=("source",),
                source_ref_ids=("source:one",),
            ),
            IntentStatement(
                statement_id="statement:failure",
                kind=StatementKind.FAILURE,
                modality=IntentModality.PROHIBITED,
                normalized_text="Publication must not fail",
                predicate="publication_failed",
                arguments=("result",),
                source_ref_ids=("source:two",),
            ),
            IntentStatement(
                statement_id="statement:verify",
                kind=StatementKind.VERIFICATION,
                modality=IntentModality.REQUIRED,
                normalized_text="Observe the published result",
                predicate="observed",
                arguments=("result",),
                source_ref_ids=("source:two",),
                grounding=NodeGrounding.INFERRED,
            ),
        ),
        actions=(
            IntentAction(
                action_id="action:publish",
                actor="agent",
                verb="publish",
                object_refs=("result",),
                source_ref_ids=("source:one",),
                precondition_ids=("statement:assumption",),
                effect_ids=("statement:effect",),
                verification_ids=(
                    "statement:verify",
                    "statement:invariant",
                ),
            ),
            IntentAction(
                action_id="action:archive",
                actor="agent",
                verb="archive",
                object_refs=("result",),
                source_ref_ids=("source:two",),
            ),
        ),
        control_edges=(
            IntentControlEdge(
                edge_id="edge:publish-archive",
                source_action_id="action:publish",
                target_action_id="action:archive",
                kind=ControlEdgeKind.ON_SUCCESS,
                guard_statement_id="statement:guard",
                source_ref_ids=("source:one",),
            ),
        ),
        entry_action_ids=("action:publish",),
        terminal_action_ids=("action:archive",),
    )
    document.validate()
    return document


_ALL_LOGIC_FAMILIES = (
    "dynamic_hoare",
    "first_order_temporal",
    "intention_deontic",
    "safety",
    "safety_liveness",
    "verification_condition",
)


def _backend(
    *,
    stdout: str = "unsat\n",
    available: bool = True,
    timeout: bool = False,
) -> CallableProofBackend:
    def compile_request(request):
        assert request.payload["encoding"] == INTENT_SEMANTIC_ENCODING
        return CompiledBackendRequest(
            request_digest=request.digest,
            backend_id="intent-test",
            source="(check-sat)\n",
        )

    def run_request(_compiled, request):
        if timeout:
            raise TimeoutError(f"exceeded {request.bounds.timeout_ms} ms")
        return BackendRunnerOutput(stdout=stdout)

    return CallableProofBackend(
        backend_id="intent-test",
        backend_version="intent-test/v1",
        capabilities=BackendCapabilities(
            logic_families=_ALL_LOGIC_FAMILIES,
            query_kinds=(QueryKind.THEOREM_PROOF,),
            deterministic=True,
        ),
        compiler=compile_request,
        runner=run_request,
        availability_probe=lambda: available,
    )


def _artifact(*, opaque_goal: bool = False):
    return IntentFormalizationCompiler().compile(
        _document(opaque_goal=opaque_goal),
        graph_context={
            "authority": "context_only",
            "premises": (
                {
                    "authority": "context_only",
                    "node_id": "graph:neighbor",
                    "proof_authority": False,
                    "source_ids": ("source:one",),
                },
            ),
        },
    )


def test_bounded_obligations_are_explicit_grounded_and_non_authorizing() -> None:
    artifact = _artifact()
    bounds = ExecutionBounds(
        timeout_ms=250,
        max_steps=500,
        max_memory_bytes=1024 * 1024,
        max_output_bytes=4096,
    )

    packet = IntentProofObligations().generate(
        artifact,
        bounds=bounds,
        requested_backend_id="intent-test",
    )

    kinds = {IntentObligationKind(item) for item in packet.obligation_kinds.values()}
    assert kinds == set(IntentObligationKind)
    assert packet.requests
    assert all(item.bounds == bounds for item in packet.requests)
    assert all(item.query_kind is QueryKind.THEOREM_PROOF for item in packet.requests)
    assert all(item.source_refs for item in packet.obligations)
    assert all(
        item.metadata["retrieved_premises_excluded"] is True
        for item in packet.obligations
    )
    assert all(
        item.metadata.get("authority") != "context_only"
        for item in packet.assumptions
    )
    assert not any(
        item.metadata.get("proof_authority") is False
        for item in packet.assumptions
    )
    assert IntentProofPacket.from_dict(packet.to_dict()).to_dict() == packet.to_dict()

    with pytest.raises(IntentProofObligationError, match="exceeding"):
        IntentProofObligations(
            IntentProofAuthorityPolicy(max_obligations=1)
        ).generate(artifact)


def test_positive_and_counterexample_results_keep_exact_theorem_authority() -> None:
    packet = IntentProofObligations().generate(
        _artifact(), requested_backend_id="intent-test"
    )

    positive = IntentProofObligations().execute(
        packet, ProofBackendRegistry((_backend(stdout="unsat\n"),))
    )
    negative = IntentProofObligations().execute(
        packet, ProofBackendRegistry((_backend(stdout="sat\n(model)\n"),))
    )

    assert positive.passed
    assert all(item.disposition is IntentProofDisposition.POSITIVE for item in positive.outcomes)
    assert all(item.authoritative for item in positive.outcomes)
    assert all(item.result.status is ResultStatus.PROVED for item in positive.outcomes)
    assert not negative.passed
    assert all(item.counterexample for item in negative.outcomes)
    assert all(item.authoritative for item in negative.outcomes)
    assert all(item.result.status is ResultStatus.DISPROVED for item in negative.outcomes)

    rejected_policy_packet = IntentProofObligations().generate(
        _artifact(),
        requested_backend_id="intent-test",
        authority_policy=IntentProofAuthorityPolicy(
            accepted_backend_ids=("different-backend",)
        ),
    )
    rejected = IntentProofObligations().execute(
        rejected_policy_packet,
        ProofBackendRegistry((_backend(),)),
    )
    assert not rejected.passed
    assert all(not item.authoritative for item in rejected.outcomes)


def test_unsupported_unavailable_timeout_and_opaque_paths_fail_closed() -> None:
    obligations = IntentProofObligations()
    packet = obligations.generate(_artifact())

    unsupported = obligations.execute(packet, ProofBackendRegistry())
    assert {
        item.disposition for item in unsupported.outcomes
    } == {IntentProofDisposition.UNSUPPORTED}
    assert all(item.attempt is None for item in unsupported.outcomes)

    requested = obligations.generate(
        _artifact(), requested_backend_id="intent-test"
    )
    unavailable = obligations.execute(
        requested, ProofBackendRegistry((_backend(available=False),))
    )
    assert {
        item.disposition for item in unavailable.outcomes
    } == {IntentProofDisposition.UNAVAILABLE}
    assert all(
        item.attempt.status is AttemptStatus.UNAVAILABLE
        for item in unavailable.outcomes
    )

    timed_out = obligations.execute(
        requested, ProofBackendRegistry((_backend(timeout=True),))
    )
    assert {
        item.disposition for item in timed_out.outcomes
    } == {IntentProofDisposition.TIMEOUT}
    assert all(
        item.attempt.status is AttemptStatus.TIMED_OUT
        for item in timed_out.outcomes
    )

    opaque = obligations.generate(
        _artifact(opaque_goal=True), requested_backend_id="intent-test"
    )
    opaque_execution = obligations.execute(
        opaque, ProofBackendRegistry((_backend(),))
    )
    assert any(
        item.disposition is IntentProofDisposition.UNSUPPORTED
        and item.attempt is None
        for item in opaque_execution.outcomes
    )
    assert not opaque_execution.passed


def test_semantic_decompilation_round_trip_is_byte_stable() -> None:
    document = _document()
    artifact = IntentFormalizationCompiler().compile(document)
    decompiler = IntentDecompiler()

    first = decompiler.decompile(artifact)
    second = decompiler.decompile(artifact)
    report = decompiler.compare(document, artifact)

    assert first.canonical_bytes() == second.canonical_bytes()
    assert report.passed
    assert report.mutations == ()
    assert DecompiledIntentReview.from_dict(first.to_dict()) == first
    assert IntentRoundTripReport.from_dict(report.to_dict()) == report
    assert decompiler.compare(artifact, document).passed
    assert first.goals["statement:goal"]["predicate"] == "publish"
    assert first.modalities["statement:goal"] == "intended"
    assert first.action_order["edge:publish-archive"]["source_action_id"] == "action:publish"
    assert first.guards["edge:publish-archive"]["guard_statement_id"] == "statement:guard"
    assert first.effects["action:publish"]["action_effect_ids"] == ("statement:effect",)


def _mutate_expression(artifact, view_id, semantic_id, transform):
    formulas = []
    for formula in artifact.formulas:
        ids = tuple(formula.metadata.get("intent_node_ids", ()))
        if formula.view_id == view_id and semantic_id in ids:
            formulas.append(
                replace(formula, expression=transform(formula.expression.to_dict()))
            )
        else:
            formulas.append(formula)
    return replace(artifact, formulas=tuple(formulas))


@pytest.mark.parametrize(
    ("kind", "view_id", "semantic_id", "transform"),
    (
        (
            IntentSemanticMutationKind.GOAL,
            INTENT_MODAL_VIEW_ID,
            "statement:goal",
            lambda value: {
                **value,
                "body": {**value["body"], "predicate": "mutated_goal"},
            },
        ),
        (
            IntentSemanticMutationKind.MODALITY,
            INTENT_MODAL_VIEW_ID,
            "statement:goal",
            lambda value: {**value, "operator": "prohibited"},
        ),
        (
            IntentSemanticMutationKind.ACTION_ORDER,
            INTENT_WORKFLOW_VIEW_ID,
            "edge:publish-archive",
            lambda value: {
                **value,
                "edge": {
                    **value["edge"],
                    "source_action_id": "action:archive",
                },
            },
        ),
        (
            IntentSemanticMutationKind.GUARD,
            INTENT_WORKFLOW_VIEW_ID,
            "edge:publish-archive",
            lambda value: {
                **value,
                "guard": {
                    **value["guard"],
                    "predicate": "mutated_guard",
                },
            },
        ),
        (
            IntentSemanticMutationKind.EFFECT,
            INTENT_ACTION_VIEW_ID,
            "action:publish",
            lambda value: {**value, "effects": []},
        ),
    ),
)
def test_decompiler_detects_semantic_mutations(
    kind, view_id, semantic_id, transform
) -> None:
    document = _document()
    artifact = IntentFormalizationCompiler().compile(document)
    mutated = _mutate_expression(
        artifact, view_id, semantic_id, transform
    )

    report = IntentDecompiler().compare(document, mutated)

    assert not report.passed
    assert kind in report.mutation_kinds
    assert report.mutations_of(kind)


def test_decompiler_detects_source_grounding_and_unsupported_mutations() -> None:
    document = _document()
    artifact = IntentFormalizationCompiler().compile(document)
    formulas = []
    for formula in artifact.formulas:
        ids = tuple(formula.metadata.get("intent_node_ids", ()))
        if (
            formula.view_id == INTENT_ACTION_VIEW_ID
            and "action:publish" in ids
        ):
            formulas.append(
                replace(
                    formula,
                    source_ref_ids=("source:one",),
                    opaque=True,
                )
            )
        else:
            formulas.append(formula)
    # Preserve the compiler's required opaque diagnostic by using an artifact
    # that was originally opaque for the unsupported assertion.
    source_mutated = replace(artifact, formulas=tuple(
        replace(item, opaque=False) if item.opaque else item
        for item in formulas
    ))
    source_report = IntentDecompiler().compare(document, source_mutated)
    assert IntentSemanticMutationKind.SOURCE_GROUNDING in source_report.mutation_kinds

    opaque_artifact = IntentFormalizationCompiler().compile(
        _document(opaque_goal=True)
    )
    opaque_report = IntentDecompiler().compare(
        _document(opaque_goal=True), opaque_artifact
    )
    assert IntentSemanticMutationKind.UNSUPPORTED in opaque_report.mutation_kinds
    assert not opaque_report.passed
