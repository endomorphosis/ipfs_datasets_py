"""Authority-boundary tests for the generic formalization advisor."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from ipfs_datasets_py.logic.formalization.advisor import (
    AdviceKind,
    AdvisorCandidate,
    AdvisorConfig,
    AdvisorModel,
    AdvisorResult,
    AdvisorValidationError,
    BoundedFormalizationAdvisor,
    FormalizationAdvisor,
    FormalizationAdvisorRequest,
    FormulaRepair,
    FormulaSuggestion,
    RepairScope,
)
from ipfs_datasets_py.logic.formalization.checkpoints import CheckpointManifest
from ipfs_datasets_py.logic.formalization.compiler import (
    FormalizationArtifact,
    FormalizationCompilerConfig,
)
from ipfs_datasets_py.logic.formalization.features import FormalizationFeatures
from ipfs_datasets_py.logic.formalization.samples import (
    FormalizationValidationError,
)
from ipfs_datasets_py.logic.formalization.views import (
    FormalFormula,
    FormalSymbol,
    FormalizationView,
    SymbolTable,
    ViewRegistry,
)
from ipfs_datasets_py.logic.ir_core.claims import Assumption
from ipfs_datasets_py.logic.ir_core.diagnostics import DiagnosticReport
from ipfs_datasets_py.logic.ir_core.provenance import (
    ConfigBinding,
    ProducerBinding,
    Provenance,
    ProvenanceBinding,
    SourceRef,
    SourceSpan,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
ONTOLOGY_IDENTITY = f"sha256:{SHA_B}"


def _registry() -> ViewRegistry:
    return ViewRegistry(
        (
            FormalizationView(
                view_id="view:modal",
                logic_family="deontic",
                capabilities=("modality", "typed_symbols"),
            ),
        ),
        registry_id="registry:intent:v1",
    )


def _compiler_config() -> FormalizationCompilerConfig:
    return FormalizationCompilerConfig(
        compiler_id="intent:compiler",
        compiler_version="1",
        config_id="intent:compiler-config",
        producer_id="intent:compiler",
        target_view_ids=("view:modal",),
    )


def _source_map() -> Provenance:
    config = _compiler_config()
    return Provenance(
        provenance_id="intent:provenance:1",
        sources=(
            SourceRef(
                ref_id="source:1",
                source_uri="ipfs://fixture",
                source_id="fixture",
                source_revision="v1",
                content_sha256=SHA_A,
            ),
        ),
        spans=(
            SourceSpan(
                span_id="span:1",
                source_ref_id="source:1",
                start_byte=0,
                end_byte=10,
            ),
        ),
        producers=(
            ProducerBinding(
                producer_id="intent:compiler",
                name="Intent compiler",
                version="1",
            ),
        ),
        configs=(
            ConfigBinding(
                config_id="intent:compiler-config",
                content_sha256=config.identity.hexdigest,
                schema_id=config.schema_version,
            ),
        ),
        bindings=(
            ProvenanceBinding(
                binding_id="binding:sample",
                subject_id="sample:1",
                source_ref_ids=("source:1",),
                span_ids=("span:1",),
            ),
            ProvenanceBinding(
                binding_id="binding:node",
                subject_id="node:goal",
                source_ref_ids=("source:1",),
                span_ids=("span:1",),
            ),
            ProvenanceBinding(
                binding_id="binding:formula",
                subject_id="formula:goal",
                source_ref_ids=("source:1",),
                span_ids=("span:1",),
                producer_id="intent:compiler",
                config_id="intent:compiler-config",
                parent_subject_ids=("node:goal",),
                derived=True,
            ),
        ),
    )


def _expression(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "operator": "intended",
        "body": {"predicate": "publish", "arguments": ["agent"]},
        "policy": {
            "assumptions": ["actor-exists"],
            "license_expression": "MIT",
            "trust_status": "human_reviewed",
        },
    }
    value.update(changes)
    return value


def _artifact() -> FormalizationArtifact:
    source_map = _source_map()
    return FormalizationArtifact(
        sample_id="sample:1",
        domain="intent",
        declaration_id="node:goal",
        declaration_digest=f"sha256:{SHA_A}",
        compiler_config=_compiler_config(),
        view_registry=_registry(),
        symbol_table=SymbolTable(
            table_id="symbols:1",
            symbols=(
                FormalSymbol(
                    symbol_id="symbol:actor",
                    name="agent",
                    kind="constant",
                    sort="principal",
                    source_ref_ids=("source:1",),
                    span_ids=("span:1",),
                ),
                FormalSymbol(
                    symbol_id="symbol:publish",
                    name="publish",
                    kind="predicate",
                    sort="action",
                    source_ref_ids=("source:1",),
                    span_ids=("span:1",),
                ),
            ),
        ),
        formulas=(
            FormalFormula(
                formula_id="formula:goal",
                view_id="view:modal",
                expression=_expression(),
                symbol_ids=("symbol:actor", "symbol:publish"),
                source_ref_ids=("source:1",),
                span_ids=("span:1",),
                assumption_ids=("assumption:1",),
                input_node_ids=("node:goal",),
                metadata={"review_status": "human_reviewed"},
            ),
        ),
        cross_view_links=(),
        assumptions=(
            Assumption(
                assumption_id="assumption:1",
                statement="the actor exists",
                source_refs=("source:1",),
            ),
        ),
        proof_obligations=(),
        source_map=source_map,
        diagnostics=DiagnosticReport(
            report_id="diagnostics:1",
            diagnostics=(),
            provenance_id=source_map.provenance_id,
        ),
        metadata={
            "license_expression": "MIT",
            "trust_status": "human_reviewed",
        },
    )


def _features(**changes: object) -> FormalizationFeatures:
    values: dict[str, object] = {
        "sample_id": "sample:1",
        "domain": "intent",
        "declaration_digest": f"sha256:{SHA_A}",
        "features": {
            "statement.count": 1.0,
            "statement.modality.intended.count": 1.0,
        },
        "extractor_id": "intent:feature-extractor",
        "extractor_version": "1",
    }
    values.update(changes)
    return FormalizationFeatures.from_values(**values)  # type: ignore[arg-type]


def _checkpoint(**changes: object) -> CheckpointManifest:
    values: dict[str, object] = {
        "checkpoint_id": "intent:checkpoint:advisor-v1",
        "domain": "intent",
        "head_id": "intent:head:formula",
        "model_id": "shared:formalization-encoder",
        "model_version": "1",
        "weights_digest": f"sha256:{SHA_C}",
        "training_config_identity": f"sha256:{SHA_A}",
        "ontology_identity": ONTOLOGY_IDENTITY,
        "view_registry_identity": _registry().identity.digest,
        "feature_schema_version": _features().schema_version,
    }
    values.update(changes)
    return CheckpointManifest(**values)  # type: ignore[arg-type]


def _scope(**changes: object) -> RepairScope:
    values: dict[str, object] = {
        "formula_ids": ("formula:goal",),
        "allowed_paths": ("/body/predicate",),
        "max_operations": 1,
    }
    values.update(changes)
    return RepairScope(**values)  # type: ignore[arg-type]


def _request(**changes: object) -> FormalizationAdvisorRequest:
    values: dict[str, object] = {
        "artifact": _artifact(),
        "features": _features(),
        "checkpoint": _checkpoint(),
        "ontology_identity": ONTOLOGY_IDENTITY,
        "repair_scope": _scope(),
    }
    values.update(changes)
    return FormalizationAdvisorRequest(**values)  # type: ignore[arg-type]


class _FakeModel:
    def __init__(self, output: object) -> None:
        self.output = output
        self.requests = []

    def generate_candidates(self, request):
        self.requests.append(request)
        return self.output


def _advisor(output: object, **config_changes: object):
    values: dict[str, object] = {
        "advisor_id": "advisor:generic",
        "advisor_version": "1",
    }
    values.update(config_changes)
    model = _FakeModel(output)
    return BoundedFormalizationAdvisor(
        model,
        AdvisorConfig(**values),  # type: ignore[arg-type]
    ), model


def test_checkpoint_manifest_is_namespaced_versioned_and_round_trips() -> None:
    manifests = tuple(
        _checkpoint(
            domain=domain,
            checkpoint_id=f"{domain}:checkpoint:v1",
            head_id=f"{domain}:head:formula",
        )
        for domain in ("legal", "security", "intent")
    )

    assert len({item.digest for item in manifests}) == 3
    assert CheckpointManifest.from_json(manifests[-1].to_json()) == manifests[-1]
    assert manifests[-1].model_identity.startswith("sha256:")
    with pytest.raises(FormalizationValidationError, match="namespaced"):
        _checkpoint(checkpoint_id="shared:checkpoint:v1")
    with pytest.raises(FormalizationValidationError, match="namespaced"):
        _checkpoint(head_id="legal:head:formula")
    with pytest.raises(FrozenInstanceError):
        manifests[-1].domain = "legal"  # type: ignore[misc]


def test_checkpoint_compatibility_fails_closed_on_every_dependency() -> None:
    checkpoint = _checkpoint()
    checkpoint.require_compatible(
        domain="intent",
        ontology_identity=ONTOLOGY_IDENTITY,
        view_registry_identity=_registry().identity.digest,
        feature_schema_version=_features().schema_version,
    )

    for changes in (
        {"domain": "security"},
        {"ontology_identity": f"sha256:{'0' * 64}"},
        {"view_registry_identity": f"sha256:{'0' * 64}"},
        {"feature_schema_version": "formalization-features/v2"},
    ):
        values = {
            "domain": "intent",
            "ontology_identity": ONTOLOGY_IDENTITY,
            "view_registry_identity": _registry().identity.digest,
            "feature_schema_version": _features().schema_version,
        }
        values.update(changes)
        with pytest.raises(FormalizationValidationError, match="incompatible"):
            checkpoint.require_compatible(**values)


def test_formula_candidate_is_bounded_typed_and_records_all_identities() -> None:
    changed = _expression(
        body={"predicate": "submit", "arguments": ["agent"]}
    )
    advisor, model = _advisor(
        (
            {
                "candidate_id": "candidate:1",
                "kind": "formula_candidate",
                "suggestions": [
                    {
                        "formula_id": "formula:goal",
                        "expression": changed,
                    }
                ],
                "repairs": [],
            },
        )
    )
    request = _request()
    result = advisor.advise(request)

    candidate = result.candidates[0]
    assert candidate.formulas[0].expression["body"]["predicate"] == "submit"
    assert candidate.formulas[0].source_ref_ids == ("source:1",)
    assert candidate.formulas[0].assumption_ids == ("assumption:1",)
    assert candidate.formulas[0].metadata == request.artifact.formulas[0].metadata
    assert request.artifact.formulas[0].expression["body"]["predicate"] == "publish"
    assert result.authority == "unverified_candidate_only"
    assert result.model_identity == request.checkpoint.model_identity
    assert result.config_identity == advisor.config.digest
    assert result.checkpoint_identity == request.checkpoint.digest
    assert result.input_identity == model.requests[0].digest
    assert result.input_artifact_identity == request.artifact.digest
    assert result.input_features_identity == request.features.digest
    assert result.ontology_identity == ONTOLOGY_IDENTITY
    assert result.digest.startswith("sha256:")
    assert AdvisorResult.from_json(result.to_json()) == result
    assert AdvisorConfig.from_json(advisor.config.to_json()) == advisor.config
    assert RepairScope.from_json(request.repair_scope.to_json()) == request.repair_scope

    # The backend receives numeric features and formula expressions, but no
    # source map, assumptions collection, license/trust metadata, or proofs.
    model_payload = model.requests[0].to_dict()
    assert "source_map" not in model_payload
    assert "proof_obligations" not in model_payload
    assert "metadata" not in model_payload["formulas"][0]
    assert model_payload["feature_values"] == [1.0, 1.0]


def test_repair_candidate_changes_only_an_existing_scoped_path() -> None:
    advisor, _ = _advisor(
        (
            AdvisorCandidate(
                candidate_id="candidate:repair",
                kind=AdviceKind.REPAIR,
                repairs=(
                    FormulaRepair(
                        formula_id="formula:goal",
                        path="/body/predicate",
                        replacement="submit",
                    ),
                ),
            ),
        )
    )

    result = advisor.advise(_request())

    assert result.candidates[0].changed_formula_ids == ("formula:goal",)
    assert (
        result.candidates[0].formulas[0].expression["body"]["predicate"]
        == "submit"
    )


@pytest.mark.parametrize(
    ("path", "replacement"),
    (
        ("/operator", "required"),
        ("/policy/assumptions/0", "model-invented"),
        ("/policy/license_expression", "UNKNOWN"),
        ("/policy/trust_status", "trusted"),
    ),
)
def test_protected_semantics_cannot_be_added_or_changed(
    path: str, replacement: object
) -> None:
    advisor, _ = _advisor(
        (
            AdvisorCandidate(
                candidate_id="candidate:unsafe",
                kind=AdviceKind.REPAIR,
                repairs=(
                    FormulaRepair(
                        formula_id="formula:goal",
                        path=path,
                        replacement=replacement,
                    ),
                ),
            ),
        )
    )

    with pytest.raises(AdvisorValidationError, match="cannot alter"):
        advisor.advise(
            _request(
                repair_scope=_scope(allowed_paths=(path,))
            )
        )


def test_candidate_cannot_escape_scope_or_change_formula_grounding() -> None:
    expression = _expression(
        body={"predicate": "publish", "arguments": ["model-added"]}
    )
    advisor, _ = _advisor(
        (
            AdvisorCandidate(
                candidate_id="candidate:wide",
                kind=AdviceKind.FORMULA_CANDIDATE,
                suggestions=(
                    FormulaSuggestion(
                        formula_id="formula:goal",
                        expression=expression,
                    ),
                ),
            ),
        )
    )

    with pytest.raises(AdvisorValidationError, match="exceeds repair scope"):
        advisor.advise(_request())

    raw = AdvisorCandidate(
        candidate_id="candidate:typed",
        kind=AdviceKind.FORMULA_CANDIDATE,
        suggestions=(
            FormulaSuggestion(
                formula_id="formula:goal",
                expression=_expression(
                    body={"predicate": "submit", "arguments": ["agent"]}
                ),
            ),
        ),
    ).to_dict()
    raw["suggestions"][0]["source_ref_ids"] = ["source:model"]
    advisor, _ = _advisor((raw,))
    with pytest.raises(FormalizationValidationError, match="unknown"):
        advisor.advise(_request())


def test_candidate_count_operation_and_expression_bounds_fail_closed() -> None:
    repair = AdvisorCandidate(
        candidate_id="candidate:1",
        kind=AdviceKind.REPAIR,
        repairs=(
            FormulaRepair(
                formula_id="formula:goal",
                path="/body/predicate",
                replacement="submit",
            ),
        ),
    )
    advisor, _ = _advisor((repair, replace(repair, candidate_id="candidate:2")), max_candidates=1)
    with pytest.raises(AdvisorValidationError, match="more than 1"):
        advisor.advise(_request())

    two_repairs = replace(
        repair,
        repairs=(
            *repair.repairs,
            FormulaRepair(
                formula_id="formula:goal",
                path="/body/arguments/0",
                replacement="operator",
            ),
        ),
    )
    advisor, _ = _advisor((two_repairs,))
    with pytest.raises(AdvisorValidationError, match="operation bound"):
        advisor.advise(
            _request(
                repair_scope=_scope(
                    allowed_paths=("/body",),
                    max_operations=1,
                )
            )
        )

    advisor, _ = _advisor((repair,), max_expression_bytes=20)
    with pytest.raises(AdvisorValidationError, match="byte bound"):
        advisor.advise(_request())


def test_output_schema_types_and_authority_claims_are_rejected() -> None:
    advisor, _ = _advisor({"candidate_id": "candidate:not-a-sequence"})
    with pytest.raises(AdvisorValidationError, match="sequence"):
        advisor.advise(_request())

    advisor, _ = _advisor(
        (
            {
                "candidate_id": "candidate:unknown-field",
                "kind": "repair",
                "repairs": [],
                "suggestions": [],
                "proof_status": "proved",
            },
        )
    )
    with pytest.raises(FormalizationValidationError, match="unknown"):
        advisor.advise(_request())

    authority_expression = _expression(
        body={
            "predicate": "submit",
            "arguments": ["agent"],
            "proof_status": "proved",
        }
    )
    advisor, _ = _advisor(
        (
            AdvisorCandidate(
                candidate_id="candidate:false-proof",
                kind=AdviceKind.FORMULA_CANDIDATE,
                suggestions=(
                    FormulaSuggestion(
                        formula_id="formula:goal",
                        expression=authority_expression,
                    ),
                ),
            ),
        )
    )
    with pytest.raises(AdvisorValidationError, match="authority"):
        advisor.advise(
            _request(repair_scope=_scope(allowed_paths=("/body",)))
        )


def test_request_rejects_stale_or_cross_domain_inputs() -> None:
    with pytest.raises(AdvisorValidationError, match="features do not identify"):
        _request(
            features=_features(declaration_digest=f"sha256:{'0' * 64}")
        )
    with pytest.raises(FormalizationValidationError, match="incompatible"):
        _request(ontology_identity=f"sha256:{'0' * 64}")
    with pytest.raises(AdvisorValidationError, match="unknown formulas"):
        _request(
            repair_scope=RepairScope(
                formula_ids=("formula:missing",),
                allowed_paths=("/body",),
            )
        )


def test_advisor_and_model_protocols_are_structural() -> None:
    advisor, model = _advisor(())

    assert isinstance(model, AdvisorModel)
    assert isinstance(advisor, FormalizationAdvisor)
    assert advisor.advise(_request()).candidates == ()
