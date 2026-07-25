"""Conformance tests for domain-neutral formalization contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from ipfs_datasets_py.logic.formalization.compiler import (
    FormalizationArtifact,
    FormalizationCompiler,
    FormalizationCompilerConfig,
    UnsupportedSemanticsDiagnostic,
    UnsupportedSemanticsPolicy,
)
from ipfs_datasets_py.logic.formalization.samples import (
    FormalizationSample,
    FormalizationValidationError,
)
from ipfs_datasets_py.logic.formalization.views import (
    CrossViewLink,
    CrossViewRelation,
    FormalFormula,
    FormalSymbol,
    FormalizationView,
    SymbolTable,
    ViewRegistry,
)
from ipfs_datasets_py.logic.ir_core.claims import Assumption, ProofObligation
from ipfs_datasets_py.logic.ir_core.diagnostics import (
    DiagnosticReport,
    DiagnosticSeverity,
)
from ipfs_datasets_py.logic.ir_core.provenance import (
    ConfigBinding,
    ProducerBinding,
    Provenance,
    ProvenanceBinding,
    SourceRef,
    SourceSpan,
)


SHA_A = "a" * 64


def _compiler_config() -> FormalizationCompilerConfig:
    return FormalizationCompilerConfig(
        compiler_id="compiler:test",
        compiler_version="1.0",
        config_id="config:test",
        producer_id="compiler:test",
        target_view_ids=("view:modal", "view:facts"),
        options={"normalization": "v1"},
    )


def _source_map(
    *,
    include_opaque: bool = False,
    config: FormalizationCompilerConfig | None = None,
) -> Provenance:
    resolved_config = config or _compiler_config()
    subjects = [
        ("sample:1", (), False),
        ("node:goal", (), False),
        ("symbol:actor", (), False),
        ("symbol:action", (), False),
        ("formula:fact", ("node:goal",), True),
        ("formula:modal", ("node:goal",), True),
    ]
    if include_opaque:
        subjects.extend(
            [
                ("node:unsupported", (), False),
                ("formula:opaque", ("node:unsupported",), True),
            ]
        )
    return Provenance(
        provenance_id="provenance:compile:1",
        sources=(
            SourceRef(
                ref_id="source:1",
                source_uri="ipfs://example",
                source_id="fixture",
                source_revision="v1",
                content_sha256=SHA_A,
            ),
        ),
        spans=(
            SourceSpan(
                span_id="span:goal",
                source_ref_id="source:1",
                start_byte=0,
                end_byte=24,
            ),
        ),
        producers=(
            ProducerBinding(
                producer_id="compiler:test",
                name="test compiler",
                version="1",
            ),
        ),
        configs=(
            ConfigBinding(
                config_id="config:test",
                content_sha256=resolved_config.identity.hexdigest,
                schema_id="formalization-compiler-config/v1",
            ),
        ),
        bindings=tuple(
            ProvenanceBinding(
                binding_id=f"binding:{subject.replace(':', '-')}",
                subject_id=subject,
                source_ref_ids=("source:1",),
                span_ids=("span:goal",),
                producer_id="compiler:test" if derived else "",
                config_id="config:test" if derived else "",
                parent_subject_ids=parents,
                derived=derived,
            )
            for subject, parents, derived in subjects
        ),
    )


def _sample(*, payload: dict | None = None) -> FormalizationSample:
    return FormalizationSample(
        sample_id="sample:1",
        domain="example",
        declaration_id="node:goal",
        declaration_digest=f"sha256:{SHA_A}",
        payload=payload or {"goal": {"actor": "agent", "action": "publish"}},
        provenance=_source_map(),
        source_ref_ids=("source:1",),
        span_ids=("span:goal",),
        assumptions=(
            Assumption(
                assumption_id="assumption:1",
                statement="the actor exists",
                source_refs=("source:1",),
            ),
        ),
        tags=("fixture", "reviewed"),
    )


def _registry() -> ViewRegistry:
    return ViewRegistry(
        (
            FormalizationView(
                view_id="view:facts",
                logic_family="first_order",
                capabilities=("typed_symbols",),
            ),
            FormalizationView(
                view_id="view:modal",
                logic_family="deontic",
                capabilities=("modality",),
            ),
        ),
        registry_id="registry:test",
    )


def _symbols() -> SymbolTable:
    return SymbolTable(
        table_id="symbols:1",
        symbols=(
            FormalSymbol(
                symbol_id="symbol:action",
                name="publish",
                kind="predicate",
                sort="action",
                source_ref_ids=("source:1",),
                span_ids=("span:goal",),
            ),
            FormalSymbol(
                symbol_id="symbol:actor",
                name="agent",
                kind="constant",
                sort="principal",
                source_ref_ids=("source:1",),
                span_ids=("span:goal",),
            ),
        ),
    )


def _formulas() -> tuple[FormalFormula, ...]:
    return (
        FormalFormula(
            formula_id="formula:fact",
            view_id="view:facts",
            expression={
                "predicate": "publish",
                "arguments": ["agent"],
            },
            symbol_ids=("symbol:actor", "symbol:action"),
            source_ref_ids=("source:1",),
            span_ids=("span:goal",),
            input_node_ids=("node:goal",),
        ),
        FormalFormula(
            formula_id="formula:modal",
            view_id="view:modal",
            expression={
                "operator": "intended",
                "body": {"predicate": "publish", "arguments": ["agent"]},
            },
            symbol_ids=("symbol:actor", "symbol:action"),
            source_ref_ids=("source:1",),
            span_ids=("span:goal",),
            assumption_ids=("assumption:1",),
            input_node_ids=("node:goal",),
        ),
    )


def _artifact(
    *,
    formulas: tuple[FormalFormula, ...] | None = None,
    source_map: Provenance | None = None,
    diagnostics: DiagnosticReport | None = None,
    config: FormalizationCompilerConfig | None = None,
) -> FormalizationArtifact:
    sample = _sample()
    resolved_formulas = formulas or _formulas()
    resolved_config = config or _compiler_config()
    resolved_source_map = source_map or _source_map(config=resolved_config)
    return FormalizationArtifact.from_sample(
        sample,
        compiler_config=resolved_config,
        view_registry=_registry(),
        symbol_table=_symbols(),
        formulas=resolved_formulas,
        cross_view_links=(
            CrossViewLink(
                link_id="link:fact-modal",
                source_formula_id="formula:fact",
                target_formula_id="formula:modal",
                relation=CrossViewRelation.LOWERS_TO,
                preserved_properties=("actor", "action"),
                source_ref_ids=("source:1",),
                span_ids=("span:goal",),
            ),
        ),
        proof_obligations=(
            ProofObligation(
                obligation_id="obligation:goal",
                statement="publish(agent)",
                assumption_ids=("assumption:1",),
                logic_family="first_order",
                source_refs=("source:1",),
            ),
        ),
        source_map=resolved_source_map,
        diagnostics=diagnostics
        or DiagnosticReport(
            report_id="diagnostics:1",
            diagnostics=(),
            provenance_id=resolved_source_map.provenance_id,
        ),
    )


def test_sample_is_domain_neutral_grounded_immutable_and_round_trips() -> None:
    caller_payload = {"goal": {"arguments": ["agent"]}}
    sample = _sample(payload=caller_payload)
    caller_payload["goal"]["arguments"].append("mutated")

    assert sample.payload.to_dict() == {"goal": {"arguments": ["agent"]}}
    assert sample.domain == "example"
    assert sample.digest.startswith("sha256:")
    assert FormalizationSample.from_json(sample.to_json()) == sample
    with pytest.raises(FrozenInstanceError):
        sample.domain = "legal"  # type: ignore[misc]


def test_sample_rejects_ungrounded_or_dangling_source_contracts() -> None:
    with pytest.raises(FormalizationValidationError, match="at least one source"):
        replace(_sample(), source_ref_ids=(), span_ids=())
    with pytest.raises(FormalizationValidationError, match="unknown sources"):
        replace(_sample(), source_ref_ids=("source:missing",))
    with pytest.raises(FormalizationValidationError, match="bind"):
        replace(
            _sample(),
            sample_id="sample:unbound",
            declaration_id="node:unbound",
        )


def test_view_registry_has_exact_ids_stable_identity_and_no_alias_resolution() -> None:
    registry = _registry()

    assert registry.view_ids == ("view:facts", "view:modal")
    assert registry.resolve("view:modal").logic_family == "deontic"
    assert registry.identity.digest == ViewRegistry.from_dict(
        registry.to_dict()
    ).identity.digest
    with pytest.raises(KeyError):
        registry.resolve("modal")
    with pytest.raises(FormalizationValidationError, match="unique"):
        ViewRegistry((registry["view:facts"], registry["view:facts"]))


def test_symbol_formula_and_cross_view_references_fail_closed() -> None:
    bad_formula = replace(_formulas()[0], symbol_ids=("symbol:missing",))
    with pytest.raises(FormalizationValidationError, match="unknown identifiers"):
        _artifact(formulas=(bad_formula, _formulas()[1]))

    same_view = replace(_formulas()[1], view_id="view:facts")
    with pytest.raises(FormalizationValidationError, match="same view"):
        FormalizationArtifact.from_sample(
            _sample(),
            compiler_config=FormalizationCompilerConfig(
                compiler_id="compiler:test",
                compiler_version="1.0",
                target_view_ids=("view:facts",),
            ),
            view_registry=_registry(),
            symbol_table=_symbols(),
            formulas=(_formulas()[0], same_view),
            cross_view_links=(
                CrossViewLink(
                    link_id="link:bad",
                    source_formula_id="formula:fact",
                    target_formula_id="formula:modal",
                    relation=CrossViewRelation.EQUIVALENT,
                ),
            ),
            source_map=_source_map(),
            diagnostics=DiagnosticReport(
                report_id="diagnostics:bad",
                diagnostics=(),
                provenance_id="provenance:compile:1",
            ),
        )


def test_unsupported_semantics_is_grounded_and_required_for_opaque_formula() -> None:
    source_map = _source_map(include_opaque=True)
    opaque = FormalFormula(
        formula_id="formula:opaque",
        view_id="view:modal",
        expression={"opaque_construct": "human_confirmation"},
        source_ref_ids=("source:1",),
        span_ids=("span:goal",),
        input_node_ids=("node:unsupported",),
        opaque=True,
    )
    with pytest.raises(FormalizationValidationError, match="unsupported diagnostic"):
        _artifact(
            formulas=(*_formulas(), opaque),
            source_map=source_map,
            diagnostics=DiagnosticReport(
                report_id="diagnostics:opaque:missing",
                diagnostics=(),
                provenance_id=source_map.provenance_id,
            ),
        )

    unsupported = UnsupportedSemanticsDiagnostic(
        construct_id="node:unsupported",
        reason="human confirmation has no declared formal semantics",
        view_id="view:modal",
        opaque_formula_id="formula:opaque",
        source_ref_ids=("source:1",),
        span_ids=("span:goal",),
    ).to_diagnostic()
    artifact = _artifact(
        formulas=(*_formulas(), opaque),
        source_map=source_map,
        diagnostics=DiagnosticReport(
            report_id="diagnostics:opaque",
            diagnostics=(unsupported,),
            provenance_id=source_map.provenance_id,
        ),
    )

    assert artifact.unsupported_diagnostics == (unsupported,)
    assert artifact.formulas[-1].opaque


def test_proof_obligations_are_declarations_not_solver_results() -> None:
    artifact = _artifact()
    obligation = artifact.proof_obligations[0]

    assert obligation.assumption_ids == ("assumption:1",)
    assert "status" not in obligation.to_dict()
    assert "solver" not in artifact.to_dict()
    with pytest.raises(FormalizationValidationError, match="unknown assumptions"):
        replace(
            artifact,
            proof_obligations=(
                replace(obligation, assumption_ids=("assumption:missing",)),
            ),
        )


def test_artifact_identity_binds_views_config_sources_and_semantics() -> None:
    first = _artifact()
    reordered = replace(
        first,
        formulas=tuple(reversed(first.formulas)),
        cross_view_links=tuple(reversed(first.cross_view_links)),
        assumptions=tuple(reversed(first.assumptions)),
    )
    changed_config = replace(
        first.compiler_config,
        options={"normalization": "v2"},
    )
    changed = replace(
        first,
        compiler_config=changed_config,
        source_map=_source_map(config=changed_config),
    )

    assert first.artifact_id == reordered.artifact_id
    assert first.digest == reordered.digest
    assert first.digest != changed.digest
    assert first.artifact_id.startswith("b")
    assert first.manifest()["artifact_identity"]["digest"] == first.digest


def test_artifact_round_trip_verifies_embedded_dependency_identities() -> None:
    artifact = _artifact()
    restored = FormalizationArtifact.from_json(artifact.to_json())
    tampered = artifact.to_dict()
    tampered["compiler_config_identity"]["digest"] = f"sha256:{'0' * 64}"

    assert restored == artifact
    assert restored.artifact_id == artifact.artifact_id
    with pytest.raises(FormalizationValidationError, match="does not match"):
        FormalizationArtifact.from_dict(tampered)


def test_compiler_protocol_is_structural() -> None:
    class Compiler:
        def compile(self, sample, config):
            return _artifact(config=config)

    compiler = Compiler()
    assert isinstance(compiler, FormalizationCompiler)
    result = compiler.compile(
        _sample(),
        FormalizationCompilerConfig(
            compiler_id="compiler:test",
            compiler_version="1.0",
            config_id="config:test",
            producer_id="compiler:test",
            target_view_ids=("view:facts", "view:modal"),
            unsupported_policy=UnsupportedSemanticsPolicy.ERROR,
        ),
    )
    assert isinstance(result, FormalizationArtifact)
    assert result.compiler_config.strict_unsupported


def test_unknown_fields_and_schema_versions_are_rejected() -> None:
    sample = _sample().to_dict()
    sample["legal_citation"] = "not generic"
    with pytest.raises(FormalizationValidationError, match="unknown"):
        FormalizationSample.from_dict(sample)
    with pytest.raises(FormalizationValidationError, match="unsupported"):
        replace(_registry()["view:facts"], schema_version="formalization-view/v2")
