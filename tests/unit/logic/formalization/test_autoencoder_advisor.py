"""Authority-boundary tests for the domain-neutral autoencoder advisor."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.formalization.advisor import (
    AdviceKind,
    AdvisorCandidate,
    AdvisorResult,
    FormulaRepair,
    RepairScope,
)
from ipfs_datasets_py.logic.formalization.autoencoder_advisor import (
    UNVERIFIED_AUTHORITY,
    AutoencoderAdviceResult,
    AutoencoderAdvisorConfig,
    AutoencoderAdvisorValidationError,
    AutoencoderCheckpointBinding,
    CompressionPlan,
    FormalizationAutoencoderAdvisor,
    FormalizationAutoencoderRequest,
    FormalizationIntrospection,
    FormalizationSplitExample,
    FormalizationSplitManifest,
    RankedPremise,
    RankedView,
    SplitLeakageError,
    build_code_fingerprint,
    build_data_snapshot_identity,
)
from ipfs_datasets_py.logic.formalization.checkpoints import CheckpointManifest
from ipfs_datasets_py.logic.formalization.compiler import (
    FormalizationArtifact,
    FormalizationCompilerConfig,
)
from ipfs_datasets_py.logic.formalization.features import FormalizationFeatures
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
SHA_D = "d" * 64
SHA_E = "e" * 64
ONTOLOGY_IDENTITY = f"sha256:{SHA_B}"
CODE_FINGERPRINT = f"sha256:{SHA_D}"
DATA_SNAPSHOT = f"sha256:{SHA_E}"


def _registry() -> ViewRegistry:
    return ViewRegistry(
        (
            FormalizationView(
                view_id="view:modal",
                logic_family="deontic",
                capabilities=("modality", "typed_symbols"),
            ),
            FormalizationView(
                view_id="view:smt",
                logic_family="smt",
                capabilities=("quantifiers", "theories"),
            ),
        ),
        registry_id="registry:software-verification:v1",
    )


def _compiler_config() -> FormalizationCompilerConfig:
    return FormalizationCompilerConfig(
        compiler_id="sv:compiler",
        compiler_version="1",
        config_id="sv:compiler-config",
        producer_id="sv:compiler",
        target_view_ids=("view:modal", "view:smt"),
    )


def _source_map() -> Provenance:
    config = _compiler_config()
    return Provenance(
        provenance_id="sv:provenance:1",
        sources=(
            SourceRef(
                ref_id="source:1",
                source_uri="ipfs://fixture",
                source_id="fixture",
                source_revision="v1",
                content_sha256=SHA_A,
            ),
            SourceRef(
                ref_id="source:2",
                source_uri="ipfs://fixture-2",
                source_id="fixture-2",
                source_revision="v1",
                content_sha256=SHA_B,
            ),
        ),
        spans=(
            SourceSpan(
                span_id="span:1",
                source_ref_id="source:1",
                start_byte=0,
                end_byte=10,
            ),
            SourceSpan(
                span_id="span:2",
                source_ref_id="source:2",
                start_byte=0,
                end_byte=8,
            ),
        ),
        producers=(
            ProducerBinding(
                producer_id="sv:compiler",
                name="SV compiler",
                version="1",
            ),
        ),
        configs=(
            ConfigBinding(
                config_id="sv:compiler-config",
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
                producer_id="sv:compiler",
                config_id="sv:compiler-config",
                parent_subject_ids=("node:goal",),
                derived=True,
            ),
            ProvenanceBinding(
                binding_id="binding:formula-smt",
                subject_id="formula:vc",
                source_ref_ids=("source:2",),
                span_ids=("span:2",),
                producer_id="sv:compiler",
                config_id="sv:compiler-config",
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
        domain="software_verification",
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
            FormalFormula(
                formula_id="formula:vc",
                view_id="view:smt",
                expression={
                    "operator": "assert",
                    "body": {"predicate": "safe", "arguments": ["state"]},
                },
                symbol_ids=("symbol:actor",),
                source_ref_ids=("source:2",),
                span_ids=("span:2",),
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
        "domain": "software_verification",
        "declaration_digest": f"sha256:{SHA_A}",
        "features": {
            "statement.count": 2.0,
            "statement.modality.intended.count": 1.0,
            "view.smt.occupancy": 1.0,
            "view.modal.occupancy": 1.0,
            "noise.unused.signal": 0.01,
        },
        "extractor_id": "sv:feature-extractor",
        "extractor_version": "1",
    }
    values.update(changes)
    return FormalizationFeatures.from_values(**values)  # type: ignore[arg-type]


def _checkpoint(**changes: object) -> CheckpointManifest:
    values: dict[str, object] = {
        "checkpoint_id": "software_verification:checkpoint:autoencoder-v1",
        "domain": "software_verification",
        "head_id": "software_verification:head:autoencoder",
        "model_id": "shared:formalization-autoencoder",
        "model_version": "1",
        "weights_digest": f"sha256:{SHA_C}",
        "training_config_identity": f"sha256:{SHA_A}",
        "ontology_identity": ONTOLOGY_IDENTITY,
        "view_registry_identity": _registry().identity.digest,
        "feature_schema_version": _features().schema_version,
    }
    values.update(changes)
    return CheckpointManifest(**values)  # type: ignore[arg-type]


def _config(**changes: object) -> AutoencoderAdvisorConfig:
    values: dict[str, object] = {
        "advisor_id": "formalization:autoencoder-advisor",
        "advisor_version": "formalization-autoencoder-advisor/v1",
        "config_id": "software_verification:default",
        "max_compression_features": 3,
    }
    values.update(changes)
    return AutoencoderAdvisorConfig(**values)  # type: ignore[arg-type]


def _binding(
    config: AutoencoderAdvisorConfig | None = None, **changes: object
) -> AutoencoderCheckpointBinding:
    cfg = config or _config()
    values: dict[str, object] = {
        "checkpoint": _checkpoint(),
        "feature_schema_version": _features().schema_version,
        "advisor_config_identity": cfg.digest,
        "code_fingerprint": CODE_FINGERPRINT,
        "data_snapshot_identity": DATA_SNAPSHOT,
    }
    values.update(changes)
    return AutoencoderCheckpointBinding(**values)  # type: ignore[arg-type]


def _scope(**changes: object) -> RepairScope:
    values: dict[str, object] = {
        "formula_ids": ("formula:goal",),
        "allowed_paths": ("/body/predicate",),
        "max_operations": 1,
    }
    values.update(changes)
    return RepairScope(**values)  # type: ignore[arg-type]


def _request(
    config: AutoencoderAdvisorConfig | None = None, **changes: object
) -> FormalizationAutoencoderRequest:
    cfg = config or _config()
    values: dict[str, object] = {
        "artifact": _artifact(),
        "features": _features(),
        "checkpoint_binding": _binding(cfg),
        "ontology_identity": ONTOLOGY_IDENTITY,
        "repair_scope": None,
        "target_logic_family": "deontic",
    }
    values.update(changes)
    return FormalizationAutoencoderRequest(**values)  # type: ignore[arg-type]


class _FakeModel:
    def __init__(self, output: object) -> None:
        self.output = output
        self.requests = []

    def generate_candidates(self, request):
        self.requests.append(request)
        return self.output


class _ScoringBackend:
    def score_views(self, *, features, view_ids, logic_families):
        return {
            "view:modal": 0.2,
            "view:smt": 3.5,
        }

    def score_premises(self, *, features, premise_ids):
        return {premise_id: float(index) for index, premise_id in enumerate(premise_ids)}


def test_config_and_checkpoint_binding_round_trip() -> None:
    config = _config()
    binding = _binding(config)

    assert AutoencoderAdvisorConfig.from_json(config.to_json()) == config
    assert AutoencoderCheckpointBinding.from_dict(binding.to_dict()) == binding
    assert binding.digest.startswith("sha256:")
    assert config.digest.startswith("sha256:")
    with pytest.raises(FrozenInstanceError):
        config.max_candidates = 99  # type: ignore[misc]


def test_checkpoint_binding_requires_schema_code_and_data_match() -> None:
    config = _config()
    binding = _binding(config)
    binding.require_compatible(
        domain="software_verification",
        ontology_identity=ONTOLOGY_IDENTITY,
        view_registry_identity=_registry().identity.digest,
        feature_schema_version=_features().schema_version,
        advisor_config_identity=config.digest,
        code_fingerprint=CODE_FINGERPRINT,
        data_snapshot_identity=DATA_SNAPSHOT,
    )
    with pytest.raises(AutoencoderAdvisorValidationError, match="incompatible"):
        binding.require_compatible(
            domain="software_verification",
            ontology_identity=ONTOLOGY_IDENTITY,
            view_registry_identity=_registry().identity.digest,
            feature_schema_version=_features().schema_version,
            advisor_config_identity=config.digest,
            code_fingerprint=f"sha256:{'0' * 64}",
            data_snapshot_identity=DATA_SNAPSHOT,
        )
    with pytest.raises(AutoencoderAdvisorValidationError, match="incompatible"):
        binding.require_compatible(
            domain="software_verification",
            ontology_identity=ONTOLOGY_IDENTITY,
            view_registry_identity=_registry().identity.digest,
            feature_schema_version=_features().schema_version,
            advisor_config_identity=config.digest,
            code_fingerprint=CODE_FINGERPRINT,
            data_snapshot_identity=f"sha256:{'1' * 64}",
        )


def test_rank_views_and_premises_are_candidate_only() -> None:
    config = _config()
    advisor = FormalizationAutoencoderAdvisor(
        config,
        scoring_backend=_ScoringBackend(),
        code_fingerprint=CODE_FINGERPRINT,
        data_snapshot_identity=DATA_SNAPSHOT,
    )
    result = advisor.advise(_request(config))

    assert result.authority == UNVERIFIED_AUTHORITY
    assert result.ranked_views
    assert result.ranked_views[0].view_id == "view:smt"
    assert all(item.authority == UNVERIFIED_AUTHORITY for item in result.ranked_views)
    assert result.ranked_premises
    assert all(item.source_ref_ids for item in result.ranked_premises)
    assert all(item.authority == UNVERIFIED_AUTHORITY for item in result.ranked_premises)
    assert result.repair_result is None
    assert AutoencoderAdviceResult.from_dict(result.to_dict()) == result
    assert result.digest.startswith("sha256:")


def test_compression_plan_drops_low_mass_features() -> None:
    config = _config(max_compression_features=2)
    advisor = FormalizationAutoencoderAdvisor(
        config,
        code_fingerprint=CODE_FINGERPRINT,
        data_snapshot_identity=DATA_SNAPSHOT,
    )
    result = advisor.advise(_request(config))

    plan = result.compression_plan
    assert plan.authority == UNVERIFIED_AUTHORITY
    assert len(plan.retained_feature_names) == 2
    assert plan.dropped_feature_names
    assert plan.estimated_compression_ratio >= 1.0
    assert 0.0 <= plan.reconstruction_score <= 1.0
    assert CompressionPlan.from_dict(plan.to_dict()) == plan


def test_introspection_records_family_margin_and_focus() -> None:
    config = _config()
    advisor = FormalizationAutoencoderAdvisor(
        config,
        scoring_backend=_ScoringBackend(),
        code_fingerprint=CODE_FINGERPRINT,
        data_snapshot_identity=DATA_SNAPSHOT,
    )
    result = advisor.advise(_request(config, target_logic_family="deontic"))
    intro = result.introspection

    assert intro.authority == UNVERIFIED_AUTHORITY
    assert intro.sample_id == "sample:1"
    assert intro.domain == "software_verification"
    assert intro.top_feature_contributions
    assert intro.synthesis_focus
    assert FormalizationIntrospection.from_json(intro.to_json()) == intro


def test_bounded_repair_preserves_protected_semantics() -> None:
    config = _config()
    model = _FakeModel(
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
    advisor = FormalizationAutoencoderAdvisor(
        config,
        model=model,
        code_fingerprint=CODE_FINGERPRINT,
        data_snapshot_identity=DATA_SNAPSHOT,
    )
    result = advisor.advise(_request(config, repair_scope=_scope()))

    assert result.repair_result is not None
    assert result.repair_result.authority == UNVERIFIED_AUTHORITY
    candidate = result.repair_result.candidates[0]
    formula = candidate.formulas[0]
    assert formula.expression["body"]["predicate"] == "submit"
    assert formula.expression["operator"] == "intended"
    assert formula.expression["policy"]["trust_status"] == "human_reviewed"
    assert list(formula.expression["policy"]["assumptions"]) == ["actor-exists"]
    assert formula.source_ref_ids == ("source:1",)
    assert formula.assumption_ids == ("assumption:1",)
    # Deterministic baseline is unchanged.
    baseline = _artifact().formulas[0]
    assert baseline.expression["body"]["predicate"] == "publish"


@pytest.mark.parametrize(
    ("path", "replacement"),
    (
        ("/operator", "required"),
        ("/policy/assumptions/0", "model-invented"),
        ("/policy/license_expression", "UNKNOWN"),
        ("/policy/trust_status", "trusted"),
    ),
)
def test_protected_fields_cannot_be_repaired(
    path: str, replacement: object
) -> None:
    config = _config()
    model = _FakeModel(
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
    advisor = FormalizationAutoencoderAdvisor(
        config,
        model=model,
        code_fingerprint=CODE_FINGERPRINT,
        data_snapshot_identity=DATA_SNAPSHOT,
    )
    with pytest.raises(Exception, match="cannot alter|exceeds"):
        advisor.advise(
            _request(
                config,
                repair_scope=_scope(allowed_paths=(path,)),
            )
        )


def test_repair_scope_without_model_fails_closed() -> None:
    config = _config()
    advisor = FormalizationAutoencoderAdvisor(
        config,
        code_fingerprint=CODE_FINGERPRINT,
        data_snapshot_identity=DATA_SNAPSHOT,
    )
    with pytest.raises(AutoencoderAdvisorValidationError, match="no AdvisorModel"):
        advisor.advise(_request(config, repair_scope=_scope()))


def test_ungrounded_premise_is_rejected() -> None:
    with pytest.raises(AutoencoderAdvisorValidationError, match="ungrounded"):
        RankedPremise(
            premise_id="premise:bad",
            statement="invented",
            source_ref_ids=(),
            logic_family="smt",
            rank=0,
            score=1.0,
        )


def test_ranked_output_cannot_claim_authority() -> None:
    with pytest.raises(AutoencoderAdvisorValidationError, match="candidate-only"):
        RankedView(
            view_id="view:modal",
            logic_family="deontic",
            rank=0,
            score=1.0,
            authority="proved",
        )


def test_source_family_safe_splits_reject_leakage() -> None:
    ok = FormalizationSplitManifest(
        manifest_id="split:sv:v1",
        domain="software_verification",
        examples=(
            FormalizationSplitExample(
                sample_id="sample:train",
                domain="software_verification",
                partition="train",
                source_family_id="repo:alpha",
                content_digest=f"sha256:{SHA_A}",
                duplicate_family_id="dup:1",
            ),
            FormalizationSplitExample(
                sample_id="sample:test",
                domain="software_verification",
                partition="test",
                source_family_id="repo:beta",
                content_digest=f"sha256:{SHA_B}",
                duplicate_family_id="dup:2",
            ),
        ),
    )
    assert ok.partition_samples("train") == ("sample:train",)
    assert ok.digest.startswith("sha256:")
    assert FormalizationSplitManifest.from_dict(ok.to_dict()) == ok

    with pytest.raises(SplitLeakageError, match="leaks"):
        FormalizationSplitManifest(
            manifest_id="split:leaky",
            domain="software_verification",
            examples=(
                FormalizationSplitExample(
                    sample_id="sample:train",
                    domain="software_verification",
                    partition="train",
                    source_family_id="repo:shared",
                    content_digest=f"sha256:{SHA_A}",
                ),
                FormalizationSplitExample(
                    sample_id="sample:test",
                    domain="software_verification",
                    partition="test",
                    source_family_id="repo:shared",
                    content_digest=f"sha256:{SHA_B}",
                ),
            ),
        )

    with pytest.raises(SplitLeakageError, match="leaks"):
        FormalizationSplitManifest(
            manifest_id="split:dup-leaky",
            domain="software_verification",
            examples=(
                FormalizationSplitExample(
                    sample_id="sample:train",
                    domain="software_verification",
                    partition="train",
                    source_family_id="repo:a",
                    content_digest=f"sha256:{SHA_A}",
                    duplicate_family_id="dup:same",
                ),
                FormalizationSplitExample(
                    sample_id="sample:test",
                    domain="software_verification",
                    partition="test",
                    source_family_id="repo:b",
                    content_digest=f"sha256:{SHA_B}",
                    duplicate_family_id="dup:same",
                ),
            ),
        )


def test_duplicate_content_digest_cannot_cross_partitions() -> None:
    with pytest.raises(SplitLeakageError, match="leaks"):
        FormalizationSplitManifest(
            manifest_id="split:content-leaky",
            domain="software_verification",
            examples=(
                FormalizationSplitExample(
                    sample_id="sample:train",
                    domain="software_verification",
                    partition="train",
                    source_family_id="repo:a",
                    content_digest=f"sha256:{SHA_A}",
                ),
                FormalizationSplitExample(
                    sample_id="sample:test",
                    domain="software_verification",
                    partition="test",
                    source_family_id="repo:b",
                    content_digest=f"sha256:{SHA_A}",
                ),
            ),
        )


def test_code_and_data_snapshot_helpers_are_deterministic() -> None:
    left = build_code_fingerprint(
        ("ipfs_datasets_py/logic/formalization/autoencoder_advisor.py",),
        "body-v1",
    )
    right = build_code_fingerprint(
        ("ipfs_datasets_py/logic/formalization/autoencoder_advisor.py",),
        "body-v1",
    )
    assert left == right
    assert left.startswith("sha256:")
    snap = build_data_snapshot_identity(
        ("sample:1", "sample:2"),
        domain="software_verification",
        split_manifest_digest=f"sha256:{SHA_A}",
    )
    assert snap.startswith("sha256:")
    assert snap == build_data_snapshot_identity(
        ("sample:2", "sample:1"),
        domain="software_verification",
        split_manifest_digest=f"sha256:{SHA_A}",
    )


def test_features_must_match_artifact_declaration() -> None:
    config = _config()
    with pytest.raises(AutoencoderAdvisorValidationError, match="features do not"):
        FormalizationAutoencoderRequest(
            artifact=_artifact(),
            features=_features(sample_id="sample:other"),
            checkpoint_binding=_binding(config),
            ontology_identity=ONTOLOGY_IDENTITY,
        )


def test_premise_candidates_must_use_known_sources() -> None:
    config = _config()
    with pytest.raises(AutoencoderAdvisorValidationError, match="unknown sources"):
        FormalizationAutoencoderRequest(
            artifact=_artifact(),
            features=_features(),
            checkpoint_binding=_binding(config),
            ontology_identity=ONTOLOGY_IDENTITY,
            premise_candidates=(
                RankedPremise(
                    premise_id="premise:ghost",
                    statement="ungrounded invention",
                    source_ref_ids=("source:missing",),
                    logic_family="smt",
                    rank=0,
                    score=1.0,
                ),
            ),
        )


def test_advice_result_rejects_authority_claims_in_payload() -> None:
    config = _config()
    advisor = FormalizationAutoencoderAdvisor(
        config,
        code_fingerprint=CODE_FINGERPRINT,
        data_snapshot_identity=DATA_SNAPSHOT,
    )
    result = advisor.advise(_request(config))
    payload = result.to_dict()
    payload["authority"] = "verified"
    with pytest.raises(AutoencoderAdvisorValidationError):
        AutoencoderAdviceResult.from_dict(payload)


def test_scoring_backend_failure_fails_closed() -> None:
    class _Boom:
        def score_views(self, *, features, view_ids, logic_families):
            raise RuntimeError("backend down")

        def score_premises(self, *, features, premise_ids):
            return {}

    config = _config()
    advisor = FormalizationAutoencoderAdvisor(
        config,
        scoring_backend=_Boom(),
        code_fingerprint=CODE_FINGERPRINT,
        data_snapshot_identity=DATA_SNAPSHOT,
    )
    with pytest.raises(AutoencoderAdvisorValidationError, match="scoring backend"):
        advisor.advise(_request(config))
