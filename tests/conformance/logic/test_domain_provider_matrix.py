"""Conformance: domain-view-family-provider cross-product suite (LFP-040).

Acceptance:

* Suite contains every exact provider ID and domain
* Unexplained registry/matrix gaps are rejected
* Suite executes hermetically or emits typed unavailable evidence
* No false skips
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.registry import EXECUTABLE_PROVIDER_IDS
from ipfs_datasets_py.logic.conformance.matrix import (
    DOMAIN_IDS,
    AvailabilityStatus,
    SupportStatus,
    build_default_matrix,
)
from ipfs_datasets_py.logic.conformance.runner import (
    DEFAULT_CONFORMANCE_RUNNER,
    LOGIC_CONFORMANCE_RECEIPT_INTERFACE,
    LOGIC_CONFORMANCE_RUNNER_INTERFACE,
    REQUIRED_DOMAIN_IDS,
    REQUIRED_PROVIDER_IDS,
    CellDisposition,
    CellExecutionStatus,
    ConformanceCellEvidence,
    ConformanceGapError,
    FalseSkipError,
    LogicConformanceRunner,
    UnavailableEvidence,
    build_conformance_runner,
    map_support_to_disposition,
    run_domain_provider_matrix,
)
from ipfs_datasets_py.logic.families.providers import (
    ADVISORY_PROVIDER_IDS,
    BASELINE_PROVIDER_IDS,
)
from ipfs_datasets_py.logic.parsers.catalog import DEFAULT_PARSER_CATALOG


def test_runner_interface_identity() -> None:
    runner = DEFAULT_CONFORMANCE_RUNNER
    assert runner.INTERFACE == LOGIC_CONFORMANCE_RUNNER_INTERFACE
    assert runner.INTERFACE == "LogicConformanceRunner@1"
    assert runner.task_id == "LFP-040"
    payload = runner.to_dict()
    assert payload["interface"] == "LogicConformanceRunner@1"


def test_suite_contains_every_exact_provider_id_and_domain() -> None:
    runner = build_conformance_runner(validate=True)
    matrix = runner.matrix

    assert tuple(matrix.domains) == DOMAIN_IDS
    assert set(matrix.domains) == set(REQUIRED_DOMAIN_IDS)
    for domain_id in (
        "crypto_ir",
        "intent_ir",
        "legal_ir",
        "security_ir",
        "software_verification",
        "ui_ux_ir",
    ):
        assert domain_id in matrix.domains

    required_providers = (
        set(EXECUTABLE_PROVIDER_IDS)
        | set(ADVISORY_PROVIDER_IDS)
        | set(BASELINE_PROVIDER_IDS)
    )
    assert set(REQUIRED_PROVIDER_IDS) == required_providers
    assert required_providers <= set(matrix.provider_ids)

    for provider_id in (
        "z3",
        "cvc5",
        "tla_tlc",
        "apalache",
        "datalog_secpal",
        "proverif",
        "tamarin",
        "hyperltl_autohyper_mchyper",
        "vampire",
        "eprover",
        "hammer",
        "lean",
        "rocq",
        "isabelle",
        "runtime_mtl",
        "ergoai",
        "symbolicai",
    ):
        assert provider_id in matrix.provider_ids


def test_hermetic_run_covers_every_matrix_cell_without_false_skips() -> None:
    receipt = run_domain_provider_matrix(validate=True)
    matrix = build_default_matrix()

    assert receipt.INTERFACE == LOGIC_CONFORMANCE_RECEIPT_INTERFACE
    assert receipt.INTERFACE == "LogicConformanceReceipt@1"
    assert receipt.hermetic is True
    assert receipt.false_skips == 0
    assert receipt.cell_count == len(matrix.cells)
    assert receipt.cell_count > 0

    statuses = {cell.execution_status for cell in receipt.cells}
    assert CellExecutionStatus.SKIPPED not in statuses

    for cell in receipt.cells:
        assert cell.hermetic is True
        assert cell.reason
        assert cell.disposition in set(CellDisposition)
        if cell.execution_status is CellExecutionStatus.UNAVAILABLE:
            assert cell.unavailable is not None
            assert cell.disposition is CellDisposition.UNAVAILABLE


def test_disposition_vocabulary_covers_cross_product_policy() -> None:
    assert set(CellDisposition) == {
        CellDisposition.NATIVE,
        CellDisposition.LOSSLESS,
        CellDisposition.APPROXIMATE,
        CellDisposition.BOUNDED,
        CellDisposition.DECLARATION_ONLY,
        CellDisposition.ADVISOR_ONLY,
        CellDisposition.UNAVAILABLE,
        CellDisposition.UNSUPPORTED,
    }
    assert map_support_to_disposition(SupportStatus.NATIVE) is CellDisposition.NATIVE
    assert (
        map_support_to_disposition(SupportStatus.TRANSLATED, translation_lossless=True)
        is CellDisposition.LOSSLESS
    )
    assert (
        map_support_to_disposition(SupportStatus.TRANSLATED, translation_lossless=False)
        is CellDisposition.APPROXIMATE
    )
    assert (
        map_support_to_disposition(SupportStatus.ADVISORY)
        is CellDisposition.ADVISOR_ONLY
    )
    assert (
        map_support_to_disposition(SupportStatus.DECLARATION_ONLY)
        is CellDisposition.DECLARATION_ONLY
    )


def test_ui_domain_cells_are_declaration_only_with_source_missing() -> None:
    receipt = run_domain_provider_matrix(validate=True)
    ui_cells = [cell for cell in receipt.cells if cell.domain_id == "ui_ux_ir"]
    assert ui_cells
    for cell in ui_cells:
        assert cell.disposition is CellDisposition.DECLARATION_ONLY
        assert cell.availability is AvailabilityStatus.SOURCE_MISSING
        assert cell.execution_status is CellExecutionStatus.EXECUTED


def test_typed_unavailable_evidence_without_false_skip() -> None:
    # Inject an explicit hermetic unavailability for z3.
    runner = build_conformance_runner(
        provider_availability={"z3": False},
        validate=True,
    )
    receipt = runner.run(validate=True)
    assert receipt.false_skips == 0

    z3_cells = [cell for cell in receipt.cells if cell.provider_id == "z3"]
    assert z3_cells
    unavailable = [
        cell
        for cell in z3_cells
        if cell.disposition is CellDisposition.UNAVAILABLE
    ]
    # At least native/translated/bounded/advisor routes for z3 become unavailable.
    assert unavailable
    for cell in unavailable:
        assert cell.execution_status is CellExecutionStatus.UNAVAILABLE
        assert isinstance(cell.unavailable, UnavailableEvidence)
        assert cell.unavailable.provider_id == "z3"
        assert cell.unavailable.reason
        assert cell.unavailable.capability_gap


def test_false_skip_is_rejected() -> None:
    with pytest.raises(FalseSkipError, match="skipped"):
        ConformanceCellEvidence(
            cell_id="security_ir::view::first_order::default::z3",
            domain_id="security_ir",
            formal_view_id="view",
            family_id="first_order",
            profile_id="default",
            provider_id="z3",
            disposition=CellDisposition.NATIVE,
            execution_status=CellExecutionStatus.SKIPPED,
            reason="should not skip",
            support=SupportStatus.NATIVE,
            availability=AvailabilityStatus.DECLARED,
            authority_ceiling="exact",
        )


def test_unavailable_without_evidence_is_rejected() -> None:
    with pytest.raises(FalseSkipError, match="unavailable"):
        ConformanceCellEvidence(
            cell_id="security_ir::view::first_order::default::z3",
            domain_id="security_ir",
            formal_view_id="view",
            family_id="first_order",
            profile_id="default",
            provider_id="z3",
            disposition=CellDisposition.UNAVAILABLE,
            execution_status=CellExecutionStatus.UNAVAILABLE,
            reason="missing tool",
            support=SupportStatus.NATIVE,
            availability=AvailabilityStatus.DECLARED,
            authority_ceiling="exact",
            unavailable=None,
        )


def test_unexplained_unknown_matrix_gap_is_rejected() -> None:
    matrix = build_default_matrix()
    # Find or synthesize a path: validate_axes rejects unknown support without notes.
    # Mutate a copy of one cell via from_dict with empty notes and unknown support.
    sample = matrix.cells[0]
    bad = sample.to_dict()
    bad["support"] = SupportStatus.UNKNOWN.value
    bad["notes"] = ""
    bad["authority_ceiling"] = "unknown"
    bad["availability"] = AvailabilityStatus.UNKNOWN.value

    from ipfs_datasets_py.logic.conformance.matrix import CapabilityCell, LogicCapabilityMatrix

    poisoned = LogicCapabilityMatrix(
        domains=matrix.domains,
        formal_views=matrix.formal_views,
        families=matrix.families,
        providers=matrix.providers,
        cells=tuple(
            CapabilityCell.from_dict(bad) if item.id == sample.id else item
            for item in matrix.cells
        ),
        metadata=dict(matrix.metadata),
        notes=matrix.notes,
    )
    runner = LogicConformanceRunner(
        matrix=poisoned,
        generated_catalog=DEFAULT_CONFORMANCE_RUNNER.generated_catalog,
        parser_catalog=DEFAULT_PARSER_CATALOG,
        registry=DEFAULT_CONFORMANCE_RUNNER.registry,
    )
    with pytest.raises(ConformanceGapError, match="unexplained unknown|without a reason"):
        runner.validate_axes()


def test_missing_required_domain_is_rejected() -> None:
    matrix = build_default_matrix()
    reduced_domains = tuple(item for item in matrix.domains if item != "legal_ir")
    reduced_views = tuple(
        item for item in matrix.formal_views if item.domain_id != "legal_ir"
    )
    reduced_cells = tuple(item for item in matrix.cells if item.domain_id != "legal_ir")
    from ipfs_datasets_py.logic.conformance.matrix import LogicCapabilityMatrix

    reduced = LogicCapabilityMatrix(
        domains=reduced_domains,
        formal_views=reduced_views,
        families=matrix.families,
        providers=matrix.providers,
        cells=reduced_cells,
        metadata=dict(matrix.metadata),
        notes=matrix.notes,
    )
    runner = LogicConformanceRunner(
        matrix=reduced,
        generated_catalog=DEFAULT_CONFORMANCE_RUNNER.generated_catalog,
        parser_catalog=DEFAULT_PARSER_CATALOG,
        registry=DEFAULT_CONFORMANCE_RUNNER.registry,
    )
    with pytest.raises(ConformanceGapError, match="missing required domains"):
        runner.validate_axes()


def test_missing_required_provider_is_rejected() -> None:
    matrix = build_default_matrix()
    reduced_providers = tuple(
        item for item in matrix.providers if item.provider_id != "vampire"
    )
    reduced_cells = tuple(
        item for item in matrix.cells if item.provider_id != "vampire"
    )
    from ipfs_datasets_py.logic.conformance.matrix import LogicCapabilityMatrix

    reduced = LogicCapabilityMatrix(
        domains=matrix.domains,
        formal_views=matrix.formal_views,
        families=matrix.families,
        providers=reduced_providers,
        cells=reduced_cells,
        metadata=dict(matrix.metadata),
        notes=matrix.notes,
    )
    runner = LogicConformanceRunner(
        matrix=reduced,
        generated_catalog=DEFAULT_CONFORMANCE_RUNNER.generated_catalog,
        parser_catalog=DEFAULT_PARSER_CATALOG,
        registry=DEFAULT_CONFORMANCE_RUNNER.registry,
    )
    with pytest.raises(ConformanceGapError, match="missing required providers"):
        runner.validate_axes()


def test_receipt_round_trip_and_histogram() -> None:
    receipt = run_domain_provider_matrix(validate=True)
    payload = receipt.to_dict()
    assert payload["false_skips"] == 0
    assert payload["hermetic"] is True
    assert payload["cell_count"] == receipt.cell_count
    histogram = receipt.disposition_histogram()
    assert sum(histogram.values()) == receipt.cell_count
    assert all(value >= 0 for value in histogram.values())
    # UI domain alone guarantees declaration_only cells exist.
    assert histogram[CellDisposition.DECLARATION_ONLY.value] > 0


def test_parser_catalog_is_joined_by_runner() -> None:
    runner = DEFAULT_CONFORMANCE_RUNNER
    assert runner.parser_catalog is not None
    assert runner.parser_catalog.is_inert() is True
    runner.parser_catalog.validate_closure()
    assert set(DEFAULT_PARSER_CATALOG.descriptor_ids) == set(
        runner.parser_catalog.descriptor_ids
    )
