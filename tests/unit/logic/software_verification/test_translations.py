"""Executable contract for loss-aware cross-logic translation receipts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest
from ipfs_datasets_py.logic.families.models import (
    BoundednessKind,
    EvidenceAuthority,
    TranslationKind,
)
from ipfs_datasets_py.logic.software_verification.receipts import (
    LOGIC_TRANSLATION_RECEIPT_INTERFACE,
    LogicTranslationReceipt,
    MissingTranslationReceiptError,
    ReceiptIssueCode,
    StaleTranslationReceiptError,
    TranslationReceiptError,
    TranslationReceiptExpectation,
    require_current_translation_receipt,
    validate_translation_receipt,
)
from ipfs_datasets_py.logic.software_verification.translations import (
    ApproximationDirection,
    CompilerBinding,
    PreservationClaim,
    PreservationKind,
    SemanticMutation,
    SemanticMutationKind,
    TranslationBound,
    TranslationValidationError,
    TranslationWitness,
    UnsupportedConstruct,
    UnsupportedHandling,
    maximum_authority_for,
    taxonomy_translation_kind,
)

SOURCE_ID = "bafkreiaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
TARGET_ID = "bafkreibbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _compiler(
    *,
    version: str = "2.1.0",
    implementation: str = "sha256:" + "c" * 64,
    configuration: str = "sha256:" + "d" * 64,
) -> CompilerBinding:
    return CompilerBinding(
        compiler_id="compiler:semantic-smt",
        compiler_version=version,
        implementation_identity=implementation,
        configuration_identity=configuration,
        stage="lower",
    )


def _witness() -> TranslationWitness:
    return TranslationWitness(
        witness_id="witness:translation-check",
        witness_kind="differential_fixture",
        artifact_identity="sha256:" + "e" * 64,
        checker_id="checker:translation-conformance",
        checker_version="1.0.0",
        metadata={"fixture_set": "software-verification-v1"},
    )


def _bound(limit: int = 32) -> TranslationBound:
    return TranslationBound(
        bound_id="bound:trace-length",
        kind=BoundednessKind.FINITE_TRACE,
        limits={"steps": limit},
        description="Only prefixes through the configured step bound are translated.",
    )


def _receipt(**overrides: object) -> LogicTranslationReceipt:
    values: dict[str, object] = {
        "source_identity": SOURCE_ID,
        "target_identity": TARGET_ID,
        "source_family_id": "first_order",
        "source_family_version": "1.0.0",
        "target_family_id": "smt",
        "target_family_version": "2.6",
        "compilers": (_compiler(),),
        "preservation_claim": PreservationClaim(
            kind=PreservationKind.EXACT,
            preserved_property_ids=("property:safety",),
            permitted_result_classes=("proved", "disproved"),
            description="The reviewed fragment is structurally preserved.",
        ),
        "authority_ceiling": EvidenceAuthority.AUTHORITATIVE,
        "witnesses": (_witness(),),
        "metadata": {"route": "fol-to-smt"},
    }
    values.update(overrides)
    return LogicTranslationReceipt(**values)  # type: ignore[arg-type]


def test_exact_receipt_binds_every_required_dimension_and_round_trips() -> None:
    receipt = _receipt()
    payload = receipt.to_dict()

    assert receipt.INTERFACE == LOGIC_TRANSLATION_RECEIPT_INTERFACE
    assert receipt.content_id == receipt.receipt_id == receipt.translation_id
    assert receipt.receipt_id.startswith("bafkrei")
    assert payload["interface"] == "LogicTranslationReceipt@1"
    assert payload["source_identity"] == SOURCE_ID
    assert payload["target_identity"] == TARGET_ID
    assert payload["source_family_id"] == "first_order"
    assert payload["source_family_version"] == "1.0.0"
    assert payload["target_family_id"] == "smt"
    assert payload["target_family_version"] == "2.6"
    assert payload["compilers"][0]["implementation_identity"].startswith("sha256:")
    assert payload["assumptions"] == []
    assert payload["bounds"] == []
    assert payload["unsupported_constructs"] == []
    assert payload["preservation_claim"]["kind"] == "exact"
    assert payload["witnesses"][0]["witness_id"] == "witness:translation-check"
    assert payload["semantic_mutations"] == []
    assert payload["authority_ceiling"] == "authoritative"
    assert LogicTranslationReceipt.from_dict(payload) == receipt
    assert receipt.to_json().encode() == receipt.canonical_bytes()


def test_receipt_is_deeply_immutable_and_content_addressed() -> None:
    metadata = {"nested": {"values": ["original"]}}
    receipt = _receipt(metadata=metadata)
    metadata["nested"]["values"].append("mutated")

    assert receipt.metadata["nested"]["values"] == ("original",)
    with pytest.raises(TypeError):
        receipt.metadata["new"] = True  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        receipt.receipt_id = "changed"  # type: ignore[misc]

    reordered = _receipt(
        preservation_claim=PreservationClaim(
            kind="exact",
            preserved_property_ids=("property:z", "property:a"),
            permitted_result_classes=("proved", "disproved"),
        )
    )
    alternate_order = _receipt(
        preservation_claim=PreservationClaim(
            kind="exact",
            preserved_property_ids=("property:a", "property:z"),
            permitted_result_classes=("disproved", "proved"),
        )
    )
    assert reordered.receipt_id == alternate_order.receipt_id
    assert replace(receipt, target_family_version="2.7", receipt_id="").receipt_id != (
        receipt.receipt_id
    )


@pytest.mark.parametrize(
    ("kind", "maximum", "taxonomy_kind"),
    [
        (
            PreservationKind.EXACT,
            EvidenceAuthority.AUTHORITATIVE,
            TranslationKind.LOSSLESS,
        ),
        (
            PreservationKind.EQUISATISFIABLE,
            EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            TranslationKind.EQUISATISFIABLE,
        ),
        (
            PreservationKind.BOUNDED,
            EvidenceAuthority.BOUNDED,
            TranslationKind.SOUND_OVER_APPROXIMATION,
        ),
        (
            PreservationKind.APPROXIMATE,
            EvidenceAuthority.ADVISORY,
            TranslationKind.SOUND_OVER_APPROXIMATION,
        ),
        (
            PreservationKind.HEURISTIC,
            EvidenceAuthority.NONE,
            TranslationKind.HEURISTIC,
        ),
    ],
)
def test_preservation_classes_have_closed_authority_ceilings(
    kind: PreservationKind,
    maximum: EvidenceAuthority,
    taxonomy_kind: TranslationKind,
) -> None:
    claim = PreservationClaim(kind)
    assert claim.maximum_authority is maximum
    assert maximum_authority_for(kind) is maximum
    assert taxonomy_translation_kind(kind) is taxonomy_kind
    assert claim.taxonomy_kind is taxonomy_kind


def test_supervisor_translation_class_names_are_accepted() -> None:
    assert PreservationKind("lossless") is PreservationKind.EXACT
    assert PreservationKind("conservative_approximation") is PreservationKind.CONSERVATIVE
    assert PreservationKind("bounded_abstraction") is PreservationKind.BOUNDED


@pytest.mark.parametrize(
    ("direction", "taxonomy_kind"),
    [
        (
            ApproximationDirection.OVER,
            TranslationKind.SOUND_OVER_APPROXIMATION,
        ),
        (
            ApproximationDirection.UNDER,
            TranslationKind.SOUND_UNDER_APPROXIMATION,
        ),
    ],
)
def test_conservative_direction_is_explicit(
    direction: ApproximationDirection, taxonomy_kind: TranslationKind
) -> None:
    claim = PreservationClaim(
        PreservationKind.CONSERVATIVE,
        approximation_direction=direction,
        permitted_result_classes=("candidate", "counterexample"),
    )
    assert claim.taxonomy_kind is taxonomy_kind
    assert claim.maximum_authority is EvidenceAuthority.INDEPENDENTLY_CHECKABLE

    with pytest.raises(TranslationValidationError, match="requires an approximation direction"):
        PreservationClaim(PreservationKind.CONSERVATIVE)
    with pytest.raises(TranslationValidationError, match="only valid for conservative"):
        PreservationClaim(
            PreservationKind.EXACT,
            approximation_direction=ApproximationDirection.OVER,
        )


def test_bounded_receipt_binds_assumptions_bounds_mutations_and_witnesses() -> None:
    bound = _bound()
    mutation = SemanticMutation(
        mutation_id="mutation:finite-prefix",
        kind=SemanticMutationKind.BOUND_INTRODUCED,
        description="Infinite executions are projected to finite prefixes.",
        source_construct_ids=("construct:infinite-trace",),
        target_construct_ids=("construct:finite-prefix",),
        assumption_ids=("assumption:finite-observation",),
        bound_ids=(bound.bound_id,),
    )
    receipt = _receipt(
        preservation_claim=PreservationClaim(
            PreservationKind.BOUNDED,
            preserved_property_ids=("property:bounded-safety",),
            permitted_result_classes=("bounded_proved", "bounded_disproved"),
        ),
        authority_ceiling=EvidenceAuthority.BOUNDED,
        assumptions=("assumption:finite-observation",),
        bounds=(bound,),
        semantic_mutations=(mutation,),
    )

    payload = receipt.to_dict()
    assert payload["assumptions"] == ["assumption:finite-observation"]
    assert payload["bounds"][0]["limits"] == {"steps": 32}
    assert payload["semantic_mutations"][0]["bound_ids"] == ["bound:trace-length"]
    assert LogicTranslationReceipt.from_dict(payload) == receipt

    with pytest.raises(TranslationReceiptError, match="require at least one"):
        _receipt(
            preservation_claim=PreservationClaim(PreservationKind.BOUNDED),
            authority_ceiling=EvidenceAuthority.BOUNDED,
        )
    with pytest.raises(TranslationReceiptError, match="unknown assumptions"):
        _receipt(
            preservation_claim=PreservationClaim(PreservationKind.BOUNDED),
            authority_ceiling=EvidenceAuthority.BOUNDED,
            bounds=(bound,),
            semantic_mutations=(mutation,),
        )


def test_unsupported_constructs_and_mutations_cannot_hide_loss() -> None:
    unsupported = UnsupportedConstruct(
        construct_id="construct:higher-order-quantifier",
        construct_kind="higher_order_quantifier",
        description="The target fragment has only first-order quantification.",
        handling=UnsupportedHandling.APPROXIMATED,
        source_ref_ids=("source:module",),
    )
    mutation = SemanticMutation(
        mutation_id="mutation:quantifier-abstraction",
        kind=SemanticMutationKind.QUANTIFIER_CHANGED,
        description="Higher-order quantification is replaced by an uninterpreted sort.",
        source_construct_ids=(unsupported.construct_id,),
        target_construct_ids=("construct:uninterpreted-sort",),
    )
    receipt = _receipt(
        preservation_claim=PreservationClaim(
            PreservationKind.APPROXIMATE,
            permitted_result_classes=("candidate",),
        ),
        authority_ceiling=EvidenceAuthority.ADVISORY,
        unsupported_constructs=(unsupported,),
        semantic_mutations=(mutation,),
    )
    assert receipt.to_dict()["unsupported_constructs"][0]["handling"] == ("approximated")

    with pytest.raises(TranslationReceiptError, match="exact translations"):
        _receipt(semantic_mutations=(mutation,))
    with pytest.raises(TranslationReceiptError, match="cap.*advisory"):
        _receipt(
            preservation_claim=PreservationClaim(
                PreservationKind.CONSERVATIVE,
                approximation_direction=ApproximationDirection.OVER,
            ),
            authority_ceiling=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
            unsupported_constructs=(unsupported,),
            semantic_mutations=(mutation,),
        )
    with pytest.raises(TranslationReceiptError, match="require authority_ceiling=none"):
        _receipt(
            preservation_claim=PreservationClaim(PreservationKind.APPROXIMATE),
            authority_ceiling=EvidenceAuthority.ADVISORY,
            unsupported_constructs=(replace(unsupported, handling=UnsupportedHandling.OMITTED),),
            semantic_mutations=(mutation,),
        )


@pytest.mark.parametrize(
    ("kind", "too_high"),
    [
        (PreservationKind.EQUISATISFIABLE, EvidenceAuthority.AUTHORITATIVE),
        (PreservationKind.BOUNDED, EvidenceAuthority.INDEPENDENTLY_CHECKABLE),
        (PreservationKind.APPROXIMATE, EvidenceAuthority.BOUNDED),
        (PreservationKind.HEURISTIC, EvidenceAuthority.ADVISORY),
    ],
)
def test_receipt_rejects_authority_above_preservation_ceiling(
    kind: PreservationKind, too_high: EvidenceAuthority
) -> None:
    kwargs: dict[str, object] = {}
    if kind is PreservationKind.BOUNDED:
        kwargs["bounds"] = (_bound(),)
    with pytest.raises(TranslationReceiptError, match="cannot carry"):
        _receipt(
            preservation_claim=PreservationClaim(kind),
            authority_ceiling=too_high,
            **kwargs,
        )


def test_missing_receipt_fails_closed() -> None:
    receipt = _receipt()
    expectation = TranslationReceiptExpectation.from_receipt(receipt)
    validation = validate_translation_receipt(None, expectation)

    assert not validation.current
    assert not validation.promotion_allowed
    assert validation.effective_authority_ceiling is EvidenceAuthority.NONE
    assert [issue.code for issue in validation.issues] == [ReceiptIssueCode.MISSING_RECEIPT]
    with pytest.raises(MissingTranslationReceiptError):
        require_current_translation_receipt(None, expectation)


def test_current_receipt_preserves_its_declared_ceiling() -> None:
    receipt = _receipt()
    expectation = TranslationReceiptExpectation.from_receipt(receipt)
    validation = validate_translation_receipt(receipt, expectation)

    assert validation.current
    assert validation.promotion_allowed
    assert validation.effective_authority_ceiling is EvidenceAuthority.AUTHORITATIVE
    assert validation.permits(EvidenceAuthority.INDEPENDENTLY_CHECKABLE)
    assert require_current_translation_receipt(receipt, expectation) is receipt
    assert receipt.require_current(expectation) is receipt
    assert TranslationReceiptExpectation.from_dict(expectation.to_dict()) == expectation
    assert type(validation).from_dict(validation.to_dict()) == validation


@pytest.mark.parametrize(
    ("change", "expected_code"),
    [
        (
            {"source_identity": "sha256:" + "1" * 64},
            ReceiptIssueCode.SOURCE_IDENTITY_MISMATCH,
        ),
        (
            {"target_identity": "sha256:" + "2" * 64},
            ReceiptIssueCode.TARGET_IDENTITY_MISMATCH,
        ),
        (
            {"source_family_id": "higher_order"},
            ReceiptIssueCode.SOURCE_FAMILY_MISMATCH,
        ),
        (
            {"source_family_version": "1.1.0"},
            ReceiptIssueCode.SOURCE_FAMILY_VERSION_MISMATCH,
        ),
        (
            {"target_family_id": "tptp"},
            ReceiptIssueCode.TARGET_FAMILY_MISMATCH,
        ),
        (
            {"target_family_version": "2.7"},
            ReceiptIssueCode.TARGET_FAMILY_VERSION_MISMATCH,
        ),
        (
            {"compilers": (_compiler(version="2.2.0"),)},
            ReceiptIssueCode.COMPILER_CHAIN_MISMATCH,
        ),
        (
            {"assumptions": ("assumption:new",)},
            ReceiptIssueCode.ASSUMPTION_MISMATCH,
        ),
        (
            {"bounds": (_bound(64),)},
            ReceiptIssueCode.BOUND_MISMATCH,
        ),
    ],
)
def test_every_stale_binding_fails_closed(
    change: dict[str, object], expected_code: ReceiptIssueCode
) -> None:
    receipt = _receipt()
    expectation = replace(TranslationReceiptExpectation.from_receipt(receipt), **change)
    validation = receipt.validate_current(expectation)

    assert not validation.current
    assert validation.stale
    assert validation.effective_authority_ceiling is EvidenceAuthority.NONE
    assert expected_code in {issue.code for issue in validation.issues}
    with pytest.raises(StaleTranslationReceiptError, match=expected_code.value):
        require_current_translation_receipt(receipt, expectation)


def test_tampered_or_unknown_wire_fields_are_rejected() -> None:
    receipt = _receipt()
    tampered = receipt.to_dict()
    tampered["target_family_version"] = "999"
    with pytest.raises(TranslationReceiptError, match="receipt_id does not match"):
        LogicTranslationReceipt.from_dict(tampered)

    unknown = receipt.to_dict()
    unknown["observed_success"] = True
    with pytest.raises(TranslationReceiptError, match="unknown translation receipt"):
        LogicTranslationReceipt.from_dict(unknown)

    bad_compiler = receipt.compilers[0].to_dict()
    bad_compiler["host"] = "runner-a"
    with pytest.raises(TranslationValidationError, match="unknown compiler binding"):
        CompilerBinding.from_dict(bad_compiler)

    with pytest.raises(TranslationValidationError, match="non-negative"):
        _bound(-1)
