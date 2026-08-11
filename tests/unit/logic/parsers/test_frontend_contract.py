"""Unit tests for the common frontend descriptor contract (LFP2-010).

Acceptance:

* A frontend cannot register without shared artifact output, declared limits,
  stable diagnostics, and feature-scoped fixtures.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.frontend_contract import (
    FRONTEND_CONTRACT_GOAL_ID,
    FRONTEND_CONTRACT_MODULE_VERSION,
    FRONTEND_CONTRACT_TASK_ID,
    LOGIC_FRONTEND_DESCRIPTOR_INTERFACE,
    REQUIRED_ELABORATION_ARTIFACT_INTERFACE,
    REQUIRED_PARSE_ARTIFACT_INTERFACE,
    SHARED_FRONTEND_CONFORMANCE_INTERFACE,
    ArtifactOutputContract,
    ArtifactRole,
    DuplicateFrontendError,
    ExpectedDisposition,
    FeatureScopedFixture,
    FixtureKind,
    FrontendAdmissionError,
    FrontendContractError,
    FrontendFeature,
    FrontendLimits,
    LogicFrontendDescriptor,
    MissingArtifactOutputError,
    MissingDiagnosticsError,
    MissingFeatureFixturesError,
    MissingLimitsError,
    PrinterContract,
    PrinterGuarantee,
    RecoveryPolicy,
    SharedFrontendConformance,
    UnsupportedBehavior,
    build_baseline_fixture_set,
    make_elaboration_artifact_output,
    make_parse_artifact_output,
    validate_frontend_descriptor,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    ParseLimits,
    ParseMode,
    SyntaxContractError,
)
from ipfs_datasets_py.logic.syntax_core.registry import ParserKey


def _key(
    notation_id: str = "smtlib2",
    notation_version: str = "2.6.0",
    semantic_profile_id: str = "smt_core",
) -> ParserKey:
    return ParserKey(
        notation_id=notation_id,
        notation_version=notation_version,
        semantic_profile_id=semantic_profile_id,
    )


def _diagnostics(*codes: str) -> tuple[str, ...]:
    if codes:
        return codes
    return (
        "frontend.empty_input",
        "frontend.unsupported_construct",
        "frontend.resource_limit",
    )


def _artifact_outputs(
    *,
    elaborate: bool = False,
) -> tuple[ArtifactOutputContract, ...]:
    outputs = [make_parse_artifact_output()]
    if elaborate:
        outputs.append(make_elaboration_artifact_output())
    return tuple(outputs)


def _valid_descriptor(
    *,
    descriptor_id: str = "frontend:test:smtlib2",
    features: tuple[str, ...] = (
        FrontendFeature.PARSE.value,
        FrontendFeature.PRINT.value,
        FrontendFeature.ELABORATE.value,
    ),
    notation_id: str = "smtlib2",
    notation_version: str = "2.6.0",
    semantic_profile_id: str = "smt_core",
    family_id: str = "first_order",
    include_artifacts: bool = True,
    include_limits: bool = True,
    include_diagnostics: bool = True,
    include_fixtures: bool = True,
    fixtures: tuple[FeatureScopedFixture, ...] | None = None,
    parse_modes: tuple[ParseMode, ...] = (ParseMode.STRICT,),
    recovery: RecoveryPolicy = RecoveryPolicy.NONE,
    unsupported_nodes: tuple[str, ...] = ("vendor_extension",),
) -> LogicFrontendDescriptor:
    kwargs: dict = {
        "descriptor_id": descriptor_id,
        "key": _key(notation_id, notation_version, semantic_profile_id),
        "family_id": family_id,
        "features": features,
        "parse_modes": parse_modes,
        "recovery": recovery,
        "unsupported_behavior": UnsupportedBehavior.REJECT_WITH_DIAGNOSTIC,
        "unsupported_nodes": unsupported_nodes,
        "implementation": "ipfs_datasets_py.logic.parsers.smtlib:SMTLIB2Parser",
        "printer": PrinterContract(
            guarantee=PrinterGuarantee.SEMANTIC,
            features=(FrontendFeature.PRINT.value,)
            if FrontendFeature.PRINT.value in features
            else (),
        ),
    }
    if include_limits:
        kwargs["limits"] = FrontendLimits(
            parse_limits=ParseLimits(
                max_input_bytes=65_536,
                max_tokens=16_384,
                max_depth=512,
                max_diagnostics=256,
                max_time_ms=30_000,
                max_memory_bytes=16_777_216,
            ),
            max_output_bytes=65_536,
            max_print_depth=512,
        )
    else:
        # Construction still needs a limits object; admission tests that want
        # missing limits use a direct validate path with a mutated copy.
        kwargs["limits"] = FrontendLimits()

    if include_diagnostics:
        kwargs["diagnostics"] = _diagnostics()
    else:
        kwargs["diagnostics"] = ()

    if include_artifacts:
        kwargs["artifact_outputs"] = _artifact_outputs(
            elaborate=FrontendFeature.ELABORATE.value in features
        )
    else:
        kwargs["artifact_outputs"] = ()

    if fixtures is not None:
        kwargs["fixtures"] = fixtures
    elif include_fixtures:
        kwargs["fixtures"] = build_baseline_fixture_set(
            features=features, prefix=descriptor_id.replace(":", "-")
        )
    else:
        kwargs["fixtures"] = ()

    return LogicFrontendDescriptor(**kwargs)


# ---------------------------------------------------------------------------
# Interface identities
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    assert LOGIC_FRONTEND_DESCRIPTOR_INTERFACE == "LogicFrontendDescriptor@1"
    assert SHARED_FRONTEND_CONFORMANCE_INTERFACE == "SharedFrontendConformance@1"
    assert REQUIRED_PARSE_ARTIFACT_INTERFACE == "ParseArtifact@2"
    assert REQUIRED_ELABORATION_ARTIFACT_INTERFACE == "ElaborationArtifact@2"
    assert FRONTEND_CONTRACT_TASK_ID == "LFP2-010"
    assert FRONTEND_CONTRACT_GOAL_ID == "LFP2-G030"
    assert FRONTEND_CONTRACT_MODULE_VERSION == "1.0.0"


def test_shared_artifact_helpers() -> None:
    parse_out = make_parse_artifact_output()
    elab_out = make_elaboration_artifact_output()
    assert parse_out.role is ArtifactRole.PARSE
    assert parse_out.interface == "ParseArtifact@2"
    assert elab_out.role is ArtifactRole.ELABORATION
    assert elab_out.interface == "ElaborationArtifact@2"


# ---------------------------------------------------------------------------
# Happy path: construction, validation, registration
# ---------------------------------------------------------------------------


def test_valid_descriptor_validates_and_registers() -> None:
    descriptor = _valid_descriptor()
    validate_frontend_descriptor(descriptor)

    registry = SharedFrontendConformance()
    admitted = registry.register(descriptor)
    assert admitted.descriptor_id == descriptor.descriptor_id
    assert len(registry) == 1
    assert descriptor.descriptor_id in registry
    assert registry.get(descriptor.descriptor_id).notation_id == "smtlib2"
    resolved = registry.resolve("smtlib2", "2.6.0", "smt_core")
    assert resolved.descriptor_id == descriptor.descriptor_id


def test_descriptor_round_trip() -> None:
    descriptor = _valid_descriptor()
    payload = descriptor.to_dict()
    restored = LogicFrontendDescriptor.from_dict(payload)
    assert restored.to_dict() == payload
    assert restored.interface == LOGIC_FRONTEND_DESCRIPTOR_INTERFACE
    assert restored.has_feature(FrontendFeature.PARSE)
    assert restored.has_feature("elaborate")
    assert REQUIRED_PARSE_ARTIFACT_INTERFACE in restored.artifact_interfaces()
    assert REQUIRED_ELABORATION_ARTIFACT_INTERFACE in restored.artifact_interfaces()


def test_conformance_registry_round_trip() -> None:
    registry = SharedFrontendConformance(conformance_id="conformance:test-frontends")
    registry.register(_valid_descriptor())
    registry.register(
        _valid_descriptor(
            descriptor_id="frontend:test:tptp",
            notation_id="tptp",
            notation_version="7.0.0",
            semantic_profile_id="fof",
            features=(FrontendFeature.PARSE.value, FrontendFeature.PRINT.value),
        )
    )
    payload = registry.to_dict()
    restored = SharedFrontendConformance.from_dict(payload)
    assert restored.conformance_id == "conformance:test-frontends"
    assert len(restored) == 2
    assert restored.interface == SHARED_FRONTEND_CONFORMANCE_INTERFACE
    ids = {item.descriptor_id for item in restored}
    assert ids == {"frontend:test:smtlib2", "frontend:test:tptp"}


def test_to_parser_descriptor_projection() -> None:
    descriptor = _valid_descriptor()
    parser_desc = descriptor.to_parser_descriptor()
    assert parser_desc.descriptor_id == descriptor.descriptor_id
    assert parser_desc.key.as_tuple == descriptor.key.as_tuple
    assert "parse" in parser_desc.features
    assert parser_desc.metadata["frontend_interface"] == (
        LOGIC_FRONTEND_DESCRIPTOR_INTERFACE
    )


def test_build_baseline_fixture_set_covers_required_kinds() -> None:
    features = (
        FrontendFeature.PARSE.value,
        FrontendFeature.PRINT.value,
        FrontendFeature.ELABORATE.value,
    )
    fixtures = build_baseline_fixture_set(features=features, prefix="fx")
    assert fixtures
    kinds_by_feature: dict[str, set[str]] = {feature: set() for feature in features}
    for fixture in fixtures:
        for feature in fixture.features:
            if feature in kinds_by_feature:
                kind = (
                    fixture.kind.value
                    if isinstance(fixture.kind, FixtureKind)
                    else str(fixture.kind)
                )
                kinds_by_feature[feature].add(kind)
    assert {"positive", "negative", "round_trip", "resource"} <= kinds_by_feature[
        "parse"
    ]
    assert {"positive", "negative"} <= kinds_by_feature["elaborate"]
    assert "round_trip" in kinds_by_feature["print"]


# ---------------------------------------------------------------------------
# Admission gate: shared artifact output
# ---------------------------------------------------------------------------


def test_cannot_register_without_shared_artifact_output() -> None:
    descriptor = _valid_descriptor(include_artifacts=False)
    with pytest.raises(MissingArtifactOutputError, match="ParseArtifact@2"):
        validate_frontend_descriptor(descriptor)
    registry = SharedFrontendConformance()
    with pytest.raises(MissingArtifactOutputError):
        registry.register(descriptor)


def test_cannot_register_elaborate_without_elaboration_artifact() -> None:
    descriptor = LogicFrontendDescriptor(
        descriptor_id="frontend:test:no-elab-out",
        key=_key(),
        family_id="first_order",
        features=(
            FrontendFeature.PARSE.value,
            FrontendFeature.ELABORATE.value,
        ),
        parse_modes=(ParseMode.STRICT,),
        limits=FrontendLimits(),
        diagnostics=_diagnostics(),
        artifact_outputs=(make_parse_artifact_output(),),
        fixtures=build_baseline_fixture_set(
            features=(
                FrontendFeature.PARSE.value,
                FrontendFeature.ELABORATE.value,
            )
        ),
    )
    with pytest.raises(MissingArtifactOutputError, match="ElaborationArtifact@2"):
        validate_frontend_descriptor(descriptor)


def test_artifact_output_rejects_wrong_interface() -> None:
    with pytest.raises(MissingArtifactOutputError, match="ParseArtifact@2"):
        ArtifactOutputContract(
            role=ArtifactRole.PARSE,
            interface="ParseArtifact@1",
        )
    with pytest.raises(MissingArtifactOutputError, match="ElaborationArtifact@2"):
        ArtifactOutputContract(
            role=ArtifactRole.ELABORATION,
            interface="ElaborationResult@1",
        )


# ---------------------------------------------------------------------------
# Admission gate: declared limits
# ---------------------------------------------------------------------------


def test_cannot_construct_limits_with_non_positive_bounds() -> None:
    with pytest.raises(SyntaxContractError):
        ParseLimits(max_input_bytes=0)  # type: ignore[arg-type]
    with pytest.raises(MissingLimitsError, match="max_output_bytes"):
        FrontendLimits(max_output_bytes=0)
    with pytest.raises(MissingLimitsError, match="max_print_depth"):
        FrontendLimits(max_print_depth=0)


def test_limits_round_trip() -> None:
    limits = FrontendLimits(
        parse_limits=ParseLimits(max_input_bytes=1024, max_tokens=256),
        max_output_bytes=2048,
        max_print_depth=64,
    )
    restored = FrontendLimits.from_dict(limits.to_dict())
    assert restored.to_dict() == limits.to_dict()
    assert restored.parse_limits.max_input_bytes == 1024


def test_descriptor_requires_limits_object() -> None:
    # Construction path rejects None limits.
    with pytest.raises((TypeError, MissingLimitsError, FrontendContractError)):
        LogicFrontendDescriptor(
            descriptor_id="frontend:test:no-limits",
            key=_key(),
            family_id="first_order",
            features=(FrontendFeature.PARSE.value,),
            parse_modes=(ParseMode.STRICT,),
            limits=None,  # type: ignore[arg-type]
            diagnostics=_diagnostics(),
            artifact_outputs=_artifact_outputs(),
            fixtures=build_baseline_fixture_set(
                features=(FrontendFeature.PARSE.value,)
            ),
        )


# ---------------------------------------------------------------------------
# Admission gate: stable diagnostics
# ---------------------------------------------------------------------------


def test_cannot_register_without_stable_diagnostics() -> None:
    descriptor = _valid_descriptor(include_diagnostics=False)
    with pytest.raises(MissingDiagnosticsError, match="stable diagnostics"):
        validate_frontend_descriptor(descriptor)
    registry = SharedFrontendConformance()
    with pytest.raises(MissingDiagnosticsError):
        registry.register(descriptor)


def test_diagnostic_codes_must_be_namespaced() -> None:
    with pytest.raises(FrontendContractError, match="namespaced"):
        LogicFrontendDescriptor(
            descriptor_id="frontend:test:bad-diag",
            key=_key(),
            family_id="first_order",
            features=(FrontendFeature.PARSE.value,),
            parse_modes=(ParseMode.STRICT,),
            limits=FrontendLimits(),
            diagnostics=("NotNamespaced",),
            artifact_outputs=_artifact_outputs(),
            fixtures=build_baseline_fixture_set(
                features=(FrontendFeature.PARSE.value,)
            ),
        )


def test_diagnostic_codes_reject_duplicates() -> None:
    with pytest.raises(FrontendContractError, match="duplicates"):
        LogicFrontendDescriptor(
            descriptor_id="frontend:test:dup-diag",
            key=_key(),
            family_id="first_order",
            features=(FrontendFeature.PARSE.value,),
            parse_modes=(ParseMode.STRICT,),
            limits=FrontendLimits(),
            diagnostics=("frontend.empty_input", "frontend.empty_input"),
            artifact_outputs=_artifact_outputs(),
            fixtures=build_baseline_fixture_set(
                features=(FrontendFeature.PARSE.value,)
            ),
        )


# ---------------------------------------------------------------------------
# Admission gate: feature-scoped fixtures
# ---------------------------------------------------------------------------


def test_cannot_register_without_feature_scoped_fixtures() -> None:
    descriptor = _valid_descriptor(include_fixtures=False)
    with pytest.raises(MissingFeatureFixturesError, match="feature-scoped fixtures"):
        validate_frontend_descriptor(descriptor)
    registry = SharedFrontendConformance()
    with pytest.raises(MissingFeatureFixturesError):
        registry.register(descriptor)


def test_fixtures_must_scope_declared_features_only() -> None:
    with pytest.raises(MissingFeatureFixturesError, match="unknown features"):
        validate_frontend_descriptor(
            _valid_descriptor(
                features=(FrontendFeature.PARSE.value,),
                fixtures=(
                    FeatureScopedFixture(
                        fixture_id="fx:rogue",
                        kind=FixtureKind.POSITIVE,
                        features=("parse", "not_a_declared_feature"),
                        expected_disposition=ExpectedDisposition.ACCEPT,
                    ),
                    FeatureScopedFixture(
                        fixture_id="fx:parse-negative",
                        kind=FixtureKind.NEGATIVE,
                        features=("parse",),
                        expected_disposition=ExpectedDisposition.REJECT,
                    ),
                    FeatureScopedFixture(
                        fixture_id="fx:parse-round-trip",
                        kind=FixtureKind.ROUND_TRIP,
                        features=("parse",),
                        expected_disposition=ExpectedDisposition.ACCEPT,
                    ),
                    FeatureScopedFixture(
                        fixture_id="fx:parse-resource",
                        kind=FixtureKind.RESOURCE,
                        features=("parse",),
                        expected_disposition=ExpectedDisposition.REJECT,
                    ),
                ),
            )
        )


def test_parse_feature_requires_kind_coverage() -> None:
    incomplete = (
        FeatureScopedFixture(
            fixture_id="fx:only-positive",
            kind=FixtureKind.POSITIVE,
            features=("parse",),
            expected_disposition=ExpectedDisposition.ACCEPT,
        ),
    )
    with pytest.raises(MissingFeatureFixturesError, match="required fixture kinds"):
        validate_frontend_descriptor(
            _valid_descriptor(
                features=(FrontendFeature.PARSE.value,),
                fixtures=incomplete,
            )
        )


def test_fixture_requires_non_empty_feature_scope() -> None:
    with pytest.raises(MissingFeatureFixturesError, match="feature scope"):
        FeatureScopedFixture(
            fixture_id="fx:unscoped",
            kind=FixtureKind.POSITIVE,
            features=(),
        )


def test_declared_feature_without_any_fixture_rejected() -> None:
    fixtures = build_baseline_fixture_set(
        features=(FrontendFeature.PARSE.value,),
        prefix="fx",
    )
    # Drop any fixture that mentions print, then declare print.
    with pytest.raises(MissingFeatureFixturesError, match="without any feature-scoped"):
        validate_frontend_descriptor(
            _valid_descriptor(
                features=(
                    FrontendFeature.PARSE.value,
                    FrontendFeature.PRINT.value,
                ),
                fixtures=fixtures,
            )
        )


# ---------------------------------------------------------------------------
# Parse modes, recovery, unsupported behavior, printer
# ---------------------------------------------------------------------------


def test_parse_modes_required() -> None:
    with pytest.raises(FrontendContractError, match="parse mode"):
        LogicFrontendDescriptor(
            descriptor_id="frontend:test:no-modes",
            key=_key(),
            family_id="first_order",
            features=(FrontendFeature.PARSE.value,),
            parse_modes=(),
            limits=FrontendLimits(),
            diagnostics=_diagnostics(),
            artifact_outputs=_artifact_outputs(),
            fixtures=build_baseline_fixture_set(
                features=(FrontendFeature.PARSE.value,)
            ),
        )


def test_recovery_policy_requires_recovery_mode() -> None:
    with pytest.raises(FrontendContractError, match="recovery"):
        LogicFrontendDescriptor(
            descriptor_id="frontend:test:recovery-mismatch",
            key=_key(),
            family_id="first_order",
            features=(FrontendFeature.PARSE.value, FrontendFeature.RECOVER.value),
            parse_modes=(ParseMode.STRICT,),
            limits=FrontendLimits(),
            diagnostics=_diagnostics(),
            artifact_outputs=_artifact_outputs(),
            fixtures=build_baseline_fixture_set(
                features=(
                    FrontendFeature.PARSE.value,
                    FrontendFeature.RECOVER.value,
                )
            ),
            recovery=RecoveryPolicy.BOUNDED,
        )


def test_recovery_mode_with_policy_registers() -> None:
    descriptor = _valid_descriptor(
        features=(
            FrontendFeature.PARSE.value,
            FrontendFeature.RECOVER.value,
        ),
        parse_modes=(ParseMode.STRICT, ParseMode.RECOVERY),
        recovery=RecoveryPolicy.BOUNDED,
    )
    validate_frontend_descriptor(descriptor)
    registry = SharedFrontendConformance()
    registry.register(descriptor)
    assert registry.get(descriptor.descriptor_id).recovery is RecoveryPolicy.BOUNDED


def test_unsupported_behavior_and_nodes_round_trip() -> None:
    descriptor = _valid_descriptor(
        unsupported_nodes=("phase", "table", "diff"),
    )
    assert descriptor.unsupported_behavior is (
        UnsupportedBehavior.REJECT_WITH_DIAGNOSTIC
    )
    assert descriptor.unsupported_nodes == ("diff", "phase", "table")
    restored = LogicFrontendDescriptor.from_dict(descriptor.to_dict())
    assert restored.unsupported_nodes == descriptor.unsupported_nodes


def test_printer_contract_defaults_for_print_feature() -> None:
    descriptor = LogicFrontendDescriptor(
        descriptor_id="frontend:test:printer-default",
        key=_key(),
        family_id="first_order",
        features=(FrontendFeature.PARSE.value, FrontendFeature.PRINT.value),
        parse_modes=(ParseMode.STRICT,),
        limits=FrontendLimits(),
        diagnostics=_diagnostics(),
        artifact_outputs=_artifact_outputs(),
        fixtures=build_baseline_fixture_set(
            features=(FrontendFeature.PARSE.value, FrontendFeature.PRINT.value)
        ),
        printer=None,
    )
    assert descriptor.printer is not None
    assert descriptor.printer.guarantee is PrinterGuarantee.SEMANTIC
    assert "print" in descriptor.printer.features


# ---------------------------------------------------------------------------
# Registry collisions and lifecycle
# ---------------------------------------------------------------------------


def test_duplicate_descriptor_id_rejected() -> None:
    registry = SharedFrontendConformance()
    registry.register(_valid_descriptor())
    with pytest.raises(DuplicateFrontendError, match="already registered"):
        registry.register(
            _valid_descriptor(
                notation_id="tptp",
                notation_version="7.0.0",
                semantic_profile_id="fof",
            )
        )


def test_duplicate_key_rejected() -> None:
    registry = SharedFrontendConformance()
    registry.register(_valid_descriptor())
    with pytest.raises(DuplicateFrontendError, match="collides"):
        registry.register(
            _valid_descriptor(descriptor_id="frontend:test:other")
        )


def test_replace_allows_update() -> None:
    registry = SharedFrontendConformance()
    registry.register(_valid_descriptor())
    updated = _valid_descriptor(
        features=(FrontendFeature.PARSE.value,),
        unsupported_nodes=("new_node",),
    )
    registry.register(updated, replace=True)
    assert len(registry) == 1
    assert registry.get(updated.descriptor_id).unsupported_nodes == ("new_node",)


def test_unregister_and_missing_lookup() -> None:
    registry = SharedFrontendConformance()
    descriptor = _valid_descriptor()
    registry.register(descriptor)
    registry.unregister(descriptor.descriptor_id)
    assert len(registry) == 0
    with pytest.raises(FrontendAdmissionError):
        registry.get(descriptor.descriptor_id)
    with pytest.raises(FrontendAdmissionError):
        registry.resolve("smtlib2", "2.6.0", "smt_core")


def test_register_from_mapping() -> None:
    registry = SharedFrontendConformance()
    payload = _valid_descriptor().to_dict()
    admitted = registry.register(payload)
    assert admitted.descriptor_id == payload["descriptor_id"]


def test_missing_baseline_parse_feature_rejected() -> None:
    with pytest.raises(FrontendAdmissionError, match="baseline"):
        validate_frontend_descriptor(
            LogicFrontendDescriptor(
                descriptor_id="frontend:test:no-parse",
                key=_key(),
                family_id="first_order",
                features=(FrontendFeature.PRINT.value,),
                parse_modes=(ParseMode.STRICT,),
                limits=FrontendLimits(),
                diagnostics=_diagnostics(),
                artifact_outputs=_artifact_outputs(),
                fixtures=build_baseline_fixture_set(
                    features=(FrontendFeature.PRINT.value,)
                ),
            )
        )


def test_notation_profile_features_standardized() -> None:
    descriptor = _valid_descriptor()
    assert descriptor.notation_id == "smtlib2"
    assert descriptor.notation_version == "2.6.0"
    assert descriptor.semantic_profile_id == "smt_core"
    assert FrontendFeature.PARSE.value in descriptor.features
    assert ParseMode.STRICT in descriptor.parse_modes
    assert isinstance(descriptor.limits, FrontendLimits)
    assert descriptor.printer.deterministic is True
    assert descriptor.unsupported_behavior is (
        UnsupportedBehavior.REJECT_WITH_DIAGNOSTIC
    )
