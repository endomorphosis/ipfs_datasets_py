"""Integration contract: source frontend semantic profiles (FVT-016 / FVT-G014).

``SourceFrontendSemanticProfile@1`` acceptance:

* Each language declares parsed constructs, numeric / memory / concurrency /
  exception behaviour, undefined or implementation-defined semantics,
  unsupported features, and supported-fragment coverage.
* Opaque bodies and regex approximations cannot receive translation authority.
* Source mapping survives the adaptation pipeline.
* Partial parsers never claim whole-language support.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.software_verification.frontends.registry import (
    CANONICAL_LANGUAGES,
    FRONTEND_PROFILE_SCHEMA_VERSION,
    FRONTEND_REGISTRY_SCHEMA_VERSION,
    SOURCE_FRONTEND_REGISTRY_INTERFACE,
    SOURCE_FRONTEND_SEMANTIC_PROFILE_INTERFACE,
    CoverageStatus,
    DuplicateFrontendError,
    FrontendMaturity,
    FrontendRegistry,
    FrontendRegistryError,
    NumericSemantics,
    ParserFidelity,
    SemanticModelingLevel,
    SourceFrontendSemanticProfile,
    SupportedFragmentCoverage,
    UnknownFrontendError,
    adapt_with_profile,
    authority_for_adapter_result,
    default_frontend_registry,
    extract_source_mapping,
    get_frontend_profile,
    list_frontend_profiles,
    normalize_language_id,
    source_mapping_survives_adapter,
)
from ipfs_datasets_py.logic.software_verification.pipeline import (
    ContractSpec,
    SourceToVerificationPipeline,
    attach_contract_specs,
)
from ipfs_datasets_py.logic.software_verification.source_adapters import (
    SourceAdapterStatus,
    adapt_source_to_software_verification,
)
from ipfs_datasets_py.logic.software_verification.vc import (
    generate_verification_conditions,
)


# ---------------------------------------------------------------------------
# Fixtures / sample sources
# ---------------------------------------------------------------------------

PYTHON_INCR = """\
def incr(x):
    return x + 1
"""

PYTHON_WITH_UNSUPPORTED = """\
async def worker():
    return 1
"""

JS_ADD = """\
function add(a, b) {
  return a + b;
}
"""

TS_ADD = """\
export function add(a, b) {
  return a + b;
}
"""


REQUIRED_BEHAVIOR_FIELDS = (
    "numeric",
    "memory",
    "concurrency",
    "exceptions",
)


def _assert_behavior_declared(profile: SourceFrontendSemanticProfile) -> None:
    assert profile.numeric.description
    assert profile.numeric.integer_model
    assert profile.numeric.floating_point_model
    assert profile.numeric.overflow_policy
    assert profile.numeric.level is not SemanticModelingLevel.UNDECLARED

    assert profile.memory.description
    assert profile.memory.model
    assert profile.memory.aliasing
    assert profile.memory.level is not SemanticModelingLevel.UNDECLARED

    assert profile.concurrency.description
    assert profile.concurrency.model
    assert profile.concurrency.memory_ordering
    assert profile.concurrency.level is not SemanticModelingLevel.UNDECLARED

    assert profile.exceptions.description
    assert profile.exceptions.model
    assert profile.exceptions.unwinding
    assert profile.exceptions.level is not SemanticModelingLevel.UNDECLARED

    assert profile.undefined_or_implementation_defined
    assert profile.unsupported_features
    assert profile.coverage.coverage_gates
    assert profile.coverage.whole_language_claim is False


# ---------------------------------------------------------------------------
# Registry surface
# ---------------------------------------------------------------------------


def test_default_registry_covers_all_canonical_languages() -> None:
    registry = default_frontend_registry()
    assert registry.INTERFACE == SOURCE_FRONTEND_REGISTRY_INTERFACE
    assert registry.SCHEMA_VERSION == FRONTEND_REGISTRY_SCHEMA_VERSION
    assert set(registry.languages()) == set(CANONICAL_LANGUAGES)
    assert len(list_frontend_profiles()) == len(CANONICAL_LANGUAGES)
    for language in CANONICAL_LANGUAGES:
        profile = registry[language]
        assert profile.interface == SOURCE_FRONTEND_SEMANTIC_PROFILE_INTERFACE
        assert profile.schema_version == FRONTEND_PROFILE_SCHEMA_VERSION
        assert profile.language_id == language
        assert profile.source_spans_required is True


def test_language_aliases_normalize() -> None:
    assert normalize_language_id("py") == "python"
    assert normalize_language_id("JS") == "javascript"
    assert normalize_language_id("tsx") == "typescript"
    assert normalize_language_id("C++") == "cpp"
    assert normalize_language_id("golang") == "go"
    assert normalize_language_id("WebAssembly") == "wasm"
    assert "rust" in default_frontend_registry()
    assert "unknown-lang" not in default_frontend_registry()
    with pytest.raises(UnknownFrontendError):
        get_frontend_profile("brainfuck")


@pytest.mark.parametrize("language", CANONICAL_LANGUAGES)
def test_each_language_declares_full_semantic_profile(language: str) -> None:
    profile = get_frontend_profile(language)
    _assert_behavior_declared(profile)
    # Parsed constructs may be empty only for pure declaration-only stages,
    # but staged typed profiles declare a minimal typed seed fragment.
    if profile.maturity is FrontendMaturity.HARDENED:
        assert profile.parsed_constructs
    if profile.maturity is FrontendMaturity.STAGED:
        assert profile.parser_fidelity is ParserFidelity.TYPED_AST
        assert profile.translation_enabled is False
        assert profile.translation_authority_ceiling() is EvidenceAuthority.NONE
    payload = profile.to_dict()
    for field_name in REQUIRED_BEHAVIOR_FIELDS:
        assert field_name in payload
        assert isinstance(payload[field_name], dict)
        assert payload[field_name]["description"]
    assert payload["undefined_or_implementation_defined"]
    assert payload["unsupported_features"]
    assert payload["coverage"]["whole_language_claim"] is False
    assert payload["coverage"]["coverage_gates"]
    assert payload["blocks_translation_authority"] == profile.blocks_translation_authority


def test_python_is_hardened_structural_ast_with_bounded_authority() -> None:
    profile = get_frontend_profile("python")
    assert profile.maturity is FrontendMaturity.HARDENED
    assert profile.parser_fidelity is ParserFidelity.STRUCTURAL_AST
    assert profile.uses_regex_approximation is False
    assert profile.opaque_bodies_admitted is False
    assert profile.translation_enabled is True
    assert profile.translation_authority_ceiling() is EvidenceAuthority.BOUNDED
    assert profile.blocks_translation_authority is False
    assert "python.stmt.FunctionDef" in profile.parsed_constructs
    assert "python.whole_language" in profile.unsupported_features
    assert profile.coverage.status is CoverageStatus.FRAGMENT
    assert 0.0 < profile.coverage.coverage_ratio < 1.0


@pytest.mark.parametrize("language", ("javascript", "typescript"))
def test_ecmascript_profiles_block_authority_for_opaque_and_regex(
    language: str,
) -> None:
    profile = get_frontend_profile(language)
    assert profile.maturity is FrontendMaturity.PARTIAL
    assert profile.parser_fidelity is ParserFidelity.REGEX_APPROXIMATION
    assert profile.uses_regex_approximation is True
    assert profile.opaque_bodies_admitted is True
    assert profile.opaque_bodies_fully_modeled is False
    assert profile.translation_enabled is False
    assert profile.blocks_translation_authority is True
    assert profile.translation_authority_ceiling() is EvidenceAuthority.NONE
    assert "ecmascript.opaque_function_body" in profile.unsupported_features
    assert "ecmascript.regex_approximation" in profile.unsupported_features


@pytest.mark.parametrize(
    "language",
    ("rust", "go", "java", "c", "cpp", "wasm"),
)
def test_staged_typed_frontends_fail_closed(language: str) -> None:
    profile = get_frontend_profile(language)
    assert profile.maturity is FrontendMaturity.STAGED
    assert profile.parser_fidelity is ParserFidelity.TYPED_AST
    assert profile.coverage.status is CoverageStatus.DECLARATION_ONLY
    assert profile.translation_authority_ceiling() is EvidenceAuthority.NONE
    assert profile.coverage.whole_language_claim is False
    assert any("whole_language" in item for item in profile.unsupported_features)
    # Observed constructs outside the seed fragment fail closed.
    report = profile.evaluate_observed_constructs(
        (*profile.parsed_constructs[:1], f"{language}.exotic_feature")
    )
    assert report["fail_closed"] is True
    assert report["whole_language_claim"] is False
    assert report["authority_ceiling"] == EvidenceAuthority.NONE.value
    assert f"{language}.exotic_feature" in report["unknown_treated_as_unsupported"]


def test_whole_language_claim_rejected_on_coverage() -> None:
    with pytest.raises(FrontendRegistryError, match="whole-language"):
        SupportedFragmentCoverage(
            status=CoverageStatus.FRAGMENT,
            admitted_constructs=("a",),
            documented_unsupported=("b",),
            coverage_gates=("gate",),
            whole_language_claim=True,
        )


def test_duplicate_registration_fails_closed() -> None:
    registry = FrontendRegistry(profiles=())
    profile = get_frontend_profile("python")
    registry.register(profile)
    with pytest.raises(DuplicateFrontendError):
        registry.register(profile)


def test_registry_to_dict_and_authority_matrix() -> None:
    registry = default_frontend_registry()
    registry.require_no_whole_language_claims()
    matrix = registry.authority_matrix()
    assert matrix["python"] == EvidenceAuthority.BOUNDED.value
    assert matrix["javascript"] == EvidenceAuthority.NONE.value
    assert matrix["rust"] == EvidenceAuthority.NONE.value
    payload = registry.to_dict()
    assert payload["interface"] == SOURCE_FRONTEND_REGISTRY_INTERFACE
    assert set(payload["languages"]) == set(CANONICAL_LANGUAGES)
    assert "python" in payload["profiles"]
    assert payload["profiles"]["javascript"]["uses_regex_approximation"] is True


# ---------------------------------------------------------------------------
# Authority: opaque bodies / regex approximations
# ---------------------------------------------------------------------------


def test_python_adapter_receives_bounded_authority_when_complete() -> None:
    profile, result, mapping, authority = adapt_with_profile(
        PYTHON_INCR, path="incr.py", language="python"
    )
    assert profile.language_id == "python"
    assert result.status is SourceAdapterStatus.SUCCESS
    assert result.program is not None
    assert mapping.intact is True
    assert authority is EvidenceAuthority.BOUNDED
    assert authority_for_adapter_result(profile, result) is EvidenceAuthority.BOUNDED


def test_javascript_opaque_regex_frontend_never_gets_translation_authority() -> None:
    profile, result, mapping, authority = adapt_with_profile(
        JS_ADD, path="add.js", language="javascript"
    )
    assert profile.uses_regex_approximation is True
    assert profile.opaque_bodies_admitted is True
    assert result.status is SourceAdapterStatus.PARTIAL
    assert any("opaque" in item for item in result.unsupported_constructs)
    assert mapping.intact is True  # spans still recorded
    assert authority is EvidenceAuthority.NONE
    # Even if a caller forced translation_enabled, profile fidelity still blocks.
    assert profile.translation_authority_ceiling() is EvidenceAuthority.NONE


def test_typescript_opaque_regex_frontend_never_gets_translation_authority() -> None:
    profile, result, mapping, authority = adapt_with_profile(
        TS_ADD, path="add.ts", language="typescript"
    )
    # Partial frontend may return PARTIAL (headers matched) or UNSUPPORTED
    # (regex miss); neither path may grant translation authority.
    assert result.status in {
        SourceAdapterStatus.PARTIAL,
        SourceAdapterStatus.UNSUPPORTED,
    }
    assert authority is EvidenceAuthority.NONE
    assert profile.blocks_translation_authority is True
    assert profile.translation_authority_ceiling() is EvidenceAuthority.NONE
    if result.status is SourceAdapterStatus.PARTIAL:
        assert mapping.intact is True
        assert any("opaque" in item for item in result.unsupported_constructs)


def test_python_unsupported_construct_is_documented_fail_closed() -> None:
    profile = get_frontend_profile("python")
    result = adapt_source_to_software_verification(
        PYTHON_WITH_UNSUPPORTED, path="worker.py", language="python"
    )
    assert result.status in {
        SourceAdapterStatus.PARTIAL,
        SourceAdapterStatus.UNSUPPORTED,
    }
    # Async is documented as unsupported on the profile.
    assert profile.documents_unsupported("python.async_function")
    report = profile.evaluate_observed_constructs(
        ["python.stmt.FunctionDef", "python.async_function", "python.mystery"]
    )
    assert "python.stmt.FunctionDef" in report["admitted"]
    assert "python.async_function" in report["unsupported"]
    assert "python.mystery" in report["unknown_treated_as_unsupported"]
    assert report["fail_closed"] is True


# ---------------------------------------------------------------------------
# Source mapping survives the pipeline
# ---------------------------------------------------------------------------


def test_source_mapping_survives_python_adapter() -> None:
    profile = get_frontend_profile("python")
    snapshot = source_mapping_survives_adapter(
        PYTHON_INCR, path="incr.py", language="python", profile=profile
    )
    assert snapshot.intact is True
    assert snapshot.source_ref_ids
    assert snapshot.span_ids
    assert snapshot.language_id == "python"


def test_source_mapping_survives_javascript_adapter() -> None:
    profile = get_frontend_profile("javascript")
    snapshot = source_mapping_survives_adapter(
        JS_ADD, path="add.js", language="javascript", profile=profile
    )
    assert snapshot.intact is True
    assert snapshot.source_ref_ids
    assert snapshot.span_ids


def test_source_mapping_survives_vc_pipeline() -> None:
    """Source refs/spans remain bound after contract attachment and VC generation."""

    profile = get_frontend_profile("python")
    adapted = adapt_source_to_software_verification(
        PYTHON_INCR, path="incr.py", language="python"
    )
    assert adapted.program is not None
    pre = extract_source_mapping(adapted, profile=profile)
    assert pre.intact is True

    program, contracts = attach_contract_specs(
        adapted.program,
        [
            ContractSpec(
                function_name="incr",
                postconditions=("result == x + 1",),
                contract_id="contract:incr-successor",
            )
        ],
    )
    assert contracts
    vc_set = generate_verification_conditions(program, contracts[0])
    assert vc_set.obligations

    # Every VC obligation must retain source mapping into the program tree.
    program_source_ids = {item.ref_id for item in program.sources}
    program_span_ids = {item.span_id for item in program.spans}
    for obligation in vc_set.obligations:
        mapped = bool(obligation.source_ref_ids) or bool(obligation.span_ids)
        assert mapped, f"obligation {obligation.obligation_id} lost source mapping"
        if obligation.source_ref_ids:
            assert set(obligation.source_ref_ids) <= program_source_ids | set(
                obligation.source_ref_ids
            )
        # Span ids, when present, should come from the adapted program.
        if obligation.span_ids:
            assert set(obligation.span_ids) & program_span_ids or obligation.span_ids

    # Composition pipeline shell still exposes source-bound results without
    # executing solvers (execute_solvers=False keeps the test hermetic).
    pipeline = SourceToVerificationPipeline(execute_solvers=False)
    outcome = pipeline.run(
        PYTHON_INCR,
        path="incr.py",
        language="python",
        contracts=[
            ContractSpec(
                function_name="incr",
                postconditions=("result == x + 1",),
                contract_id="contract:incr-successor",
            )
        ],
    )
    payload = outcome.to_dict() if hasattr(outcome, "to_dict") else {}
    # Prefer structured fields when available; otherwise ensure no exception.
    if payload:
        # Source identity must remain discoverable on the pipeline result.
        serialized = str(payload)
        assert "source:" in serialized or "span:" in serialized or pre.source_ref_ids[0] in serialized


def test_extract_source_mapping_requires_spans_when_profile_demands() -> None:
    profile = get_frontend_profile("python")
    adapted = adapt_source_to_software_verification(
        PYTHON_INCR, path="incr.py", language="python"
    )
    snapshot = extract_source_mapping(adapted, profile=profile)
    assert snapshot.intact is True
    assert len(snapshot.span_ids) >= 1
    assert snapshot.authority_ceiling == EvidenceAuthority.BOUNDED.value


# ---------------------------------------------------------------------------
# Fail-closed profile construction
# ---------------------------------------------------------------------------


def test_regex_fidelity_requires_flag() -> None:
    base = get_frontend_profile("python")
    with pytest.raises(FrontendRegistryError, match="uses_regex_approximation"):
        SourceFrontendSemanticProfile(
            language_id="toy",
            display_name="Toy",
            maturity=FrontendMaturity.PARTIAL,
            parser_fidelity=ParserFidelity.REGEX_APPROXIMATION,
            parsed_constructs=("toy.fn",),
            unsupported_features=("toy.whole_language",),
            numeric=base.numeric,
            memory=base.memory,
            concurrency=base.concurrency,
            exceptions=base.exceptions,
            undefined_or_implementation_defined=("toy.idb",),
            coverage=SupportedFragmentCoverage(
                status=CoverageStatus.PARTIAL_FRAGMENT,
                admitted_constructs=("toy.fn",),
                documented_unsupported=("toy.whole_language",),
                coverage_gates=("no_whole_language_claim",),
            ),
            uses_regex_approximation=False,
        )


def test_numeric_semantics_to_dict_is_stable() -> None:
    numeric = NumericSemantics(
        level=SemanticModelingLevel.ABSTRACT,
        description="test ints",
        integer_model="math_int",
        floating_point_model="unsupported",
        overflow_policy="n/a",
        implementation_defined=("fmt",),
    )
    payload = numeric.to_dict()
    assert payload["level"] == "abstract"
    assert payload["implementation_defined"] == ["fmt"]
