"""Contracts for separation, heap, ownership, and resource-logic semantics."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from fractions import Fraction

import pytest
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.logic.software_verification.heap import (
    HEAP_MODEL_INTERFACE,
    AliasClass,
    AliasClassKind,
    HeapLocation,
    HeapModel,
    HeapValidationError,
    HeapValue,
    LocationKind,
    OwnershipKind,
    OwnershipRecord,
    Permission,
    PointsToCell,
    ResourceAlgebra,
    ResourceAlgebraKind,
    ResourceUnit,
    ValueKind,
    combine_permissions,
)
from ipfs_datasets_py.logic.software_verification.separation import (
    SEPARATION_LOGIC_IR_INTERFACE,
    FormulaKind,
    FrameObligation,
    FrameObligationKind,
    HeapTheory,
    OwnershipTransfer,
    OwnershipTransferKind,
    SeparationFormula,
    SeparationLogicIR,
    SeparationLoweringError,
    SeparationValidationError,
    emp_formula,
    infer_frame_obligation,
    ordinary_and,
    points_to_formula,
    pure_formula,
    sep_conj,
)

SOURCE_ID = "source:list"
SPAN_ID = "span:list"


def _source() -> SourceRef:
    return SourceRef(
        ref_id=SOURCE_ID,
        source_uri="file:///src/list.sl",
        source_id="list.sl",
        source_revision="git:0123456789abcdef",
        content_sha256="a" * 64,
    )


def _span() -> SourceSpan:
    return SourceSpan(
        span_id=SPAN_ID,
        source_ref_id=SOURCE_ID,
        start_byte=0,
        end_byte=256,
        start_line=1,
        start_column=1,
        end_line=20,
        end_column=2,
    )


def _mapped() -> dict[str, tuple[str, ...]]:
    return {"source_ref_ids": (SOURCE_ID,), "span_ids": (SPAN_ID,)}


def _heap(
    *,
    cells: tuple[PointsToCell, ...] | None = None,
    ownership: tuple[OwnershipRecord, ...] | None = None,
    aliases: tuple[AliasClass, ...] = (),
) -> HeapModel:
    locations = (
        HeapLocation(
            "loc:head",
            "head",
            LocationKind.ADDRESS,
            "Node*",
            owner_id="owner:main",
            **_mapped(),
        ),
        HeapLocation(
            "loc:next",
            "next",
            LocationKind.FIELD,
            "Node*",
            owner_id="owner:main",
            **_mapped(),
        ),
        HeapLocation(
            "loc:payload",
            "payload",
            LocationKind.FIELD,
            "integer",
            **_mapped(),
        ),
    )
    values = (
        HeapValue(
            "val:node",
            ValueKind.STRUCT,
            "Node*",
            literal="node0",
            **_mapped(),
        ),
        HeapValue(
            "val:null",
            ValueKind.NULL,
            "Node*",
            literal="null",
            **_mapped(),
        ),
        HeapValue(
            "val:payload",
            ValueKind.INTEGER,
            "integer",
            literal="42",
            **_mapped(),
        ),
        HeapValue(
            "val:ptr-next",
            ValueKind.POINTER,
            "Node*",
            points_to_location_id="loc:next",
            **_mapped(),
        ),
    )
    if cells is None:
        cells = (
            PointsToCell(
                "cell:head",
                "loc:head",
                "val:node",
                Permission.full(),
                **_mapped(),
            ),
            PointsToCell(
                "cell:payload",
                "loc:payload",
                "val:payload",
                Permission.half(),
                **_mapped(),
            ),
        )
    if ownership is None:
        ownership = (
            OwnershipRecord(
                "own:head",
                "loc:head",
                "owner:main",
                OwnershipKind.EXCLUSIVE,
                Permission.full(),
                **_mapped(),
            ),
            OwnershipRecord(
                "own:payload",
                "loc:payload",
                "owner:reader",
                OwnershipKind.SHARED,
                Permission.half(),
                **_mapped(),
            ),
        )
    units = (
        ResourceUnit(
            "unit:head",
            "head-cell",
            ResourceAlgebraKind.DISJOINT_HEAP,
            location_id="loc:head",
            **_mapped(),
        ),
        ResourceUnit(
            "unit:payload-share",
            "payload-share",
            ResourceAlgebraKind.FRACTIONAL_PERMISSION,
            location_id="loc:payload",
            permission=Permission.half(),
            **_mapped(),
        ),
    )
    algebras = (
        ResourceAlgebra(
            "algebra:heap",
            ResourceAlgebraKind.DISJOINT_HEAP,
            unit_ids=("unit:head",),
            composition="disjoint_sum",
            **_mapped(),
        ),
        ResourceAlgebra(
            "algebra:frac",
            ResourceAlgebraKind.FRACTIONAL_PERMISSION,
            unit_ids=("unit:payload-share",),
            composition="permission_sum",
            **_mapped(),
        ),
    )
    return HeapModel(
        locations=locations,
        values=values,
        cells=cells,
        ownership=ownership,
        aliases=aliases,
        resource_units=units,
        resource_algebras=algebras,
        metadata={"example": "singly-linked-list"},
    )


def _document(
    *,
    heap: HeapModel | None = None,
    formulas: tuple[SeparationFormula, ...] | None = None,
    root_formula_id: str = "formula:root",
    frame_obligations: tuple[FrameObligation, ...] = (),
    ownership_transfers: tuple[OwnershipTransfer, ...] = (),
    heap_theory: HeapTheory | str = HeapTheory.FRACTIONAL_PERMISSION,
    observations: dict[str, object] | None = None,
) -> SeparationLogicIR:
    mapped = _mapped()
    if formulas is None:
        pure = pure_formula(
            "formula:pure",
            "head != null",
            expression_id="expr:nonnull",
            **mapped,
        )
        head = points_to_formula(
            "formula:head",
            "loc:head",
            "val:node",
            permission=Permission.full(),
            **mapped,
        )
        payload = points_to_formula(
            "formula:payload",
            "loc:payload",
            "val:payload",
            permission=Permission.half(),
            **mapped,
        )
        spatial = sep_conj(
            "formula:spatial",
            "formula:head",
            "formula:payload",
            **mapped,
        )
        root = ordinary_and(
            "formula:root",
            "formula:pure",
            "formula:spatial",
            **mapped,
        )
        # Root uses ordinary AND of pure and spatial; spatial itself is SEP_CONJ.
        # For a fully spatial root used in frame tests we keep formula:spatial.
        formulas = (pure, head, payload, spatial, root)
        # Default root is the separating conjunction alone for spatial tests;
        # override via root_formula_id when pure FOL lowering is desired.
        if root_formula_id == "formula:root":
            root_formula_id = "formula:spatial"
            formulas = (pure, head, payload, spatial)
    if frame_obligations is None:
        frame_obligations = ()
    return SeparationLogicIR(
        sources=(_source(),),
        spans=(_span(),),
        heap=heap or _heap(),
        formulas=formulas,
        root_formula_id=root_formula_id,
        frame_obligations=frame_obligations,
        ownership_transfers=ownership_transfers,
        heap_theory=heap_theory,
        metadata={"property": "heap_safety"},
        observations=observations or {},
    )


def test_permissions_are_bounded_and_conserved() -> None:
    full = Permission.full()
    half = Permission.half()
    assert full.is_full
    assert half.fraction == Fraction(1, 2)
    assert combine_permissions(half, half) == full
    assert half.compatible_with(half)
    assert not half.compatible_with(full)

    with pytest.raises(HeapValidationError, match="bounded to \\[0, 1\\]"):
        Permission(2, 1)
    with pytest.raises(HeapValidationError, match="conservation violated"):
        combine_permissions(full, half)
    with pytest.raises(HeapValidationError, match="conservation violated"):
        half + full


def test_heap_model_types_ownership_and_aliasing() -> None:
    heap = _heap(
        aliases=(
            AliasClass(
                "alias:fields",
                AliasClassKind.MUST_NOT_ALIAS,
                ("loc:head", "loc:payload"),
                type_name="",
                **_mapped(),
            ),
        )
    )
    assert heap.interface == HEAP_MODEL_INTERFACE
    assert heap.permission_at("loc:head").is_full
    assert heap.permission_at("loc:payload") == Permission.half()
    exclusive = [item for item in heap.ownership if item.kind is OwnershipKind.EXCLUSIVE]
    shared = [item for item in heap.ownership if item.kind is OwnershipKind.SHARED]
    assert exclusive and exclusive[0].permission.is_full
    assert shared and not shared[0].permission.is_full
    assert heap.aliases[0].kind is AliasClassKind.MUST_NOT_ALIAS

    with pytest.raises(HeapValidationError, match="type mismatch"):
        _heap(
            cells=(
                PointsToCell(
                    "cell:bad",
                    "loc:head",
                    "val:payload",
                    Permission.full(),
                    **_mapped(),
                ),
            )
        )

    with pytest.raises(HeapValidationError, match="multiple exclusive owners"):
        _heap(
            ownership=(
                OwnershipRecord(
                    "own:a",
                    "loc:head",
                    "owner:a",
                    OwnershipKind.EXCLUSIVE,
                    **_mapped(),
                ),
                OwnershipRecord(
                    "own:b",
                    "loc:head",
                    "owner:b",
                    OwnershipKind.EXCLUSIVE,
                    **_mapped(),
                ),
            )
        )

    with pytest.raises(HeapValidationError, match="permission conservation"):
        _heap(
            cells=(
                PointsToCell(
                    "cell:1",
                    "loc:head",
                    "val:node",
                    Permission.full(),
                    **_mapped(),
                ),
                PointsToCell(
                    "cell:2",
                    "loc:head",
                    "val:node",
                    Permission.half(),
                    **_mapped(),
                ),
            )
        )


def test_separating_and_ordinary_conjunction_differ() -> None:
    mapped = _mapped()
    left = points_to_formula(
        "formula:a", "loc:head", "val:node", **mapped
    )
    right = points_to_formula(
        "formula:b", "loc:payload", "val:payload", permission=Permission.half(), **mapped
    )
    spatial = sep_conj("formula:star", "formula:a", "formula:b", **mapped)
    classical = ordinary_and("formula:and", "formula:a", "formula:b", **mapped)

    assert spatial.kind is FormulaKind.SEP_CONJ
    assert classical.kind is FormulaKind.AND
    assert spatial.is_separating_conjunction
    assert classical.is_ordinary_conjunction
    assert spatial.is_spatial
    assert not classical.is_spatial
    assert spatial.to_dict()["kind"] != classical.to_dict()["kind"]
    assert spatial.to_dict() != classical.to_dict()

    star_doc = _document(
        formulas=(left, right, spatial),
        root_formula_id="formula:star",
    )
    and_doc = _document(
        formulas=(left, right, classical),
        root_formula_id="formula:and",
    )
    assert star_doc.document_id != and_doc.document_id
    assert star_doc.semantic_dict() != and_doc.semantic_dict()


def test_frame_inference_emits_explicit_obligations() -> None:
    mapped = _mapped()
    emp = emp_formula("formula:emp", **mapped)
    head = points_to_formula(
        "formula:head", "loc:head", "val:node", **mapped
    )
    payload = points_to_formula(
        "formula:payload",
        "loc:payload",
        "val:payload",
        permission=Permission.half(),
        **mapped,
    )
    frame = points_to_formula(
        "formula:frame",
        "loc:payload",
        "val:payload",
        permission=Permission.half(),
        **mapped,
    )
    pre = sep_conj(
        "formula:pre", "formula:head", "formula:payload", **mapped
    )
    obligation = infer_frame_obligation(
        obligation_id="frame:write-head",
        precondition_formula_id="formula:pre",
        footprint_location_ids=("loc:payload",),
        modified_location_ids=("loc:head",),
        frame_formula_id="formula:frame",
        kind=FrameObligationKind.FRAME_RULE,
        command_id="command:store",
        source_ref_ids=(SOURCE_ID,),
        span_ids=(SPAN_ID,),
    )
    assert obligation.frame_formula_id == "formula:frame"
    assert obligation.kind is FrameObligationKind.FRAME_RULE
    assert "loc:payload" in obligation.footprint_location_ids
    assert "loc:head" in obligation.modified_location_ids
    assert obligation.statement

    document = _document(
        formulas=(emp, head, payload, frame, pre),
        root_formula_id="formula:pre",
        frame_obligations=(obligation,),
    )
    assert len(document.frame_obligations) == 1
    assert document.frame_obligations[0].obligation_id == "frame:write-head"

    with pytest.raises(SeparationValidationError, match="disjoint"):
        infer_frame_obligation(
            obligation_id="frame:bad",
            precondition_formula_id="formula:pre",
            footprint_location_ids=("loc:head",),
            modified_location_ids=("loc:head",),
            frame_formula_id="formula:emp",
            source_ref_ids=(SOURCE_ID,),
            span_ids=(SPAN_ID,),
        )

    with pytest.raises(SeparationValidationError, match="frame_formula_id"):
        FrameObligation(
            "frame:missing",
            FrameObligationKind.MANUAL,
            "",
            **mapped,
        )


def test_ownership_transfer_is_typed_and_permission_aware() -> None:
    mapped = _mapped()
    move = OwnershipTransfer(
        "xfer:move",
        OwnershipTransferKind.MOVE,
        "loc:head",
        "owner:main",
        "owner:callee",
        Permission.full(),
        formula_id="formula:head",
        **mapped,
    )
    share = OwnershipTransfer(
        "xfer:share",
        OwnershipTransferKind.SHARE,
        "loc:payload",
        "owner:main",
        "owner:reader",
        Permission.half(),
        **mapped,
    )
    head = points_to_formula(
        "formula:head", "loc:head", "val:node", **mapped
    )
    document = _document(
        formulas=(head,),
        root_formula_id="formula:head",
        ownership_transfers=(move, share),
    )
    kinds = {item.kind for item in document.ownership_transfers}
    assert kinds == {OwnershipTransferKind.MOVE, OwnershipTransferKind.SHARE}

    with pytest.raises(SeparationValidationError, match="full permission"):
        OwnershipTransfer(
            "xfer:bad-move",
            OwnershipTransferKind.MOVE,
            "loc:head",
            "owner:a",
            "owner:b",
            Permission.half(),
            **mapped,
        )
    with pytest.raises(SeparationValidationError, match="fractional permission"):
        OwnershipTransfer(
            "xfer:bad-share",
            OwnershipTransferKind.SHARE,
            "loc:payload",
            "owner:a",
            "owner:b",
            Permission.full(),
            **mapped,
        )
    with pytest.raises(SeparationValidationError, match="must differ"):
        OwnershipTransfer(
            "xfer:same",
            OwnershipTransferKind.MOVE,
            "loc:head",
            "owner:a",
            "owner:a",
            **mapped,
        )


def test_unsupported_heap_theories_cannot_silently_lower_to_fol() -> None:
    mapped = _mapped()
    pure = pure_formula("formula:pure", "x > 0", **mapped)
    head = points_to_formula(
        "formula:head", "loc:head", "val:node", **mapped
    )

    # Spatial root: always rejected.
    spatial_doc = _document(
        formulas=(head,),
        root_formula_id="formula:head",
        heap_theory=HeapTheory.CLASSICAL_SL,
    )
    with pytest.raises(SeparationLoweringError, match="spatial"):
        spatial_doc.lower_to_fol()
    assert spatial_doc.can_lower_to_fol() is False

    # Pure-only document under a supported theory lowers.
    pure_doc = _document(
        formulas=(pure,),
        root_formula_id="formula:pure",
        heap_theory=HeapTheory.CLASSICAL_SL,
    )
    sketch = pure_doc.lower_to_fol()
    assert sketch["encoding"] == "fol-sketch/v1"
    assert sketch["spatial_lowered"] is False
    assert sketch["root"]["kind"] == "predicate"
    assert pure_doc.can_lower_to_fol() is True

    # Custom / wand / higher-order theories never lower, even for pure roots.
    for theory in (
        HeapTheory.CUSTOM,
        HeapTheory.SEPARATION_LOGIC_WITH_WAND,
        HeapTheory.HIGHER_ORDER_SL,
        HeapTheory.COUNTING_PERMISSION,
    ):
        blocked = _document(
            formulas=(pure,),
            root_formula_id="formula:pure",
            heap_theory=theory,
        )
        with pytest.raises(SeparationLoweringError, match="cannot silently lower|cannot lower"):
            blocked.lower_to_fol()

    # Wand formulas require an admitting theory at document validation time.
    with pytest.raises(SeparationValidationError, match="wand"):
        _document(
            formulas=(
                head,
                points_to_formula(
                    "formula:b",
                    "loc:payload",
                    "val:payload",
                    permission=Permission.half(),
                    **mapped,
                ),
                SeparationFormula(
                    "formula:wand",
                    FormulaKind.WAND,
                    operand_ids=("formula:head", "formula:b"),
                    **mapped,
                ),
            ),
            root_formula_id="formula:wand",
            heap_theory=HeapTheory.CLASSICAL_SL,
        )


def test_wand_requires_admitting_heap_theory() -> None:
    mapped = _mapped()
    left = points_to_formula("formula:a", "loc:head", "val:node", **mapped)
    right = points_to_formula(
        "formula:b",
        "loc:payload",
        "val:payload",
        permission=Permission.half(),
        **mapped,
    )
    wand = SeparationFormula(
        "formula:wand",
        FormulaKind.WAND,
        operand_ids=("formula:a", "formula:b"),
        **mapped,
    )
    with pytest.raises(SeparationValidationError, match="wand"):
        _document(
            formulas=(left, right, wand),
            root_formula_id="formula:wand",
            heap_theory=HeapTheory.CLASSICAL_SL,
        )
    admitted = _document(
        formulas=(left, right, wand),
        root_formula_id="formula:wand",
        heap_theory=HeapTheory.SEPARATION_LOGIC_WITH_WAND,
    )
    assert admitted.heap_theory is HeapTheory.SEPARATION_LOGIC_WITH_WAND
    with pytest.raises(SeparationLoweringError):
        admitted.lower_to_fol()


def test_document_is_immutable_content_addressed_and_round_trips() -> None:
    document = _document(
        observations={"started_at": "2026-07-29T00:00:00Z", "host": "runner-a"}
    )
    encoded = document.to_json()
    restored = SeparationLogicIR.from_json(encoded)

    assert document.interface == SEPARATION_LOGIC_IR_INTERFACE
    assert restored == document
    assert restored.document_id == document.document_id
    assert restored.semantic_bytes() == document.semantic_bytes()
    assert "runner-a" not in document.semantic_bytes().decode()
    assert restored.to_dict()["observations"]["host"] == "runner-a"

    reordered = replace(
        _document(
            observations={"started_at": "2030-01-01T00:00:00Z", "host": "runner-b"}
        ),
        formulas=tuple(reversed(document.formulas)),
    )
    assert reordered.document_id == document.document_id

    with pytest.raises(TypeError):
        document.metadata["changed"] = True  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        document.root_formula_id = "changed"  # type: ignore[misc]
    with pytest.raises(SeparationValidationError, match="does not match"):
        replace(document, document_id="bafkbad")


def test_resource_algebras_and_disjointness() -> None:
    heap = _heap()
    assert any(
        item.kind is ResourceAlgebraKind.DISJOINT_HEAP
        for item in heap.resource_algebras
    )
    assert heap.is_disjoint(("loc:head",), ("loc:payload",))
    assert not heap.is_disjoint(("loc:head", "loc:next"), ("loc:next",))

    with pytest.raises(HeapValidationError, match="custom.algebra_name"):
        ResourceUnit(
            "unit:custom",
            "mystery",
            ResourceAlgebraKind.CUSTOM,
            **_mapped(),
        )
    custom = ResourceUnit(
        "unit:custom",
        "mystery",
        ResourceAlgebraKind.CUSTOM,
        attributes={"custom.algebra_name": "credits"},
        **_mapped(),
    )
    assert custom.algebra_kind is ResourceAlgebraKind.CUSTOM


def test_source_maps_and_references_fail_closed() -> None:
    mapped = _mapped()
    with pytest.raises(SeparationValidationError, match="source mapped"):
        SeparationFormula("formula:x", FormulaKind.EMP)

    with pytest.raises(SeparationValidationError, match="unknown location"):
        _document(
            formulas=(
                points_to_formula(
                    "formula:bad",
                    "loc:missing",
                    "val:node",
                    **mapped,
                ),
            ),
            root_formula_id="formula:bad",
        )

    with pytest.raises(SeparationValidationError, match="unknown operand"):
        _document(
            formulas=(
                sep_conj("formula:bad", "formula:missing", "formula:also", **mapped),
            ),
            root_formula_id="formula:bad",
        )

    with pytest.raises(HeapValidationError, match="source mapped"):
        HeapLocation("loc:x", "x", LocationKind.ADDRESS, "int")


def test_binary_permission_theory_rejects_fractions() -> None:
    mapped = _mapped()
    fractional = points_to_formula(
        "formula:frac",
        "loc:payload",
        "val:payload",
        permission=Permission.half(),
        **mapped,
    )
    with pytest.raises(SeparationValidationError, match="binary_permission"):
        _document(
            formulas=(fractional,),
            root_formula_id="formula:frac",
            heap_theory=HeapTheory.BINARY_PERMISSION,
        )


def test_complete_model_covers_separation_vocabulary() -> None:
    mapped = _mapped()
    emp = emp_formula("formula:emp", **mapped)
    pure = pure_formula("formula:pure", "invariant(head)", **mapped)
    head = points_to_formula(
        "formula:head", "loc:head", "val:node", **mapped
    )
    payload = points_to_formula(
        "formula:payload",
        "loc:payload",
        "val:payload",
        permission=Permission.half(),
        **mapped,
    )
    spatial = sep_conj(
        "formula:spatial", "formula:head", "formula:payload", **mapped
    )
    classical = ordinary_and(
        "formula:and", "formula:pure", "formula:spatial", **mapped
    )
    obligation = infer_frame_obligation(
        obligation_id="frame:call",
        precondition_formula_id="formula:spatial",
        footprint_location_ids=("loc:payload",),
        modified_location_ids=("loc:head",),
        frame_formula_id="formula:payload",
        kind=FrameObligationKind.CALLER_CONTEXT,
        source_ref_ids=(SOURCE_ID,),
        span_ids=(SPAN_ID,),
    )
    transfer = OwnershipTransfer(
        "xfer:move",
        OwnershipTransferKind.MOVE,
        "loc:head",
        "owner:main",
        "owner:callee",
        **mapped,
    )
    document = _document(
        formulas=(emp, pure, head, payload, spatial, classical),
        root_formula_id="formula:and",
        frame_obligations=(obligation,),
        ownership_transfers=(transfer,),
        heap_theory=HeapTheory.FRACTIONAL_PERMISSION,
    )

    kinds = {item.kind for item in document.formulas}
    assert FormulaKind.EMP in kinds
    assert FormulaKind.PURE in kinds
    assert FormulaKind.POINTS_TO in kinds
    assert FormulaKind.SEP_CONJ in kinds
    assert FormulaKind.AND in kinds
    assert document.heap.resource_algebras
    assert document.frame_obligations
    assert document.ownership_transfers
    assert document.spatial_formula_ids()
    # Ordinary AND of pure + spatial still fails FOL lowering due to spatial child.
    with pytest.raises(SeparationLoweringError, match="spatial"):
        document.lower_to_fol()
