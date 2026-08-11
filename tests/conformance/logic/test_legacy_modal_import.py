"""Conformance tests for LegacyLogicImporter@1 (LFP-028).

Evidence subset:

* TDFOL / DCEC / CEC / legal / modal import routes
* unknown characters and sorts no longer disappear
* implication associativity and O/P/F ambiguity are explicit on receipts
* substitutions are capture-safe
* legacy golden vectors remain traceable
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.legacy_modal import (
    CODE_OPF_AMBIGUITY,
    CODE_UNKNOWN_CHARACTER,
    CODE_UNKNOWN_SORT,
    DCEC_PROFILE_INTERFACE,
    LEGACY_LOGIC_IMPORTER_INTERFACE,
    TDFOL_PROFILE_INTERFACE,
    DCECProfile,
    LegacyFamilyKind,
    LegacyImportError,
    LegacyLogicImporter,
    TDFOLProfile,
    capture_safe_substitute,
    detect_legacy_family,
    golden_vector_catalog,
    import_legacy,
    import_legacy_dcec,
    import_legacy_tdfol,
    list_builtin_golden_vectors,
    match_golden_vector,
    profile_dcec,
    profile_tdfol,
    scan_opf_occurrences,
    scan_unknown_characters,
)
from ipfs_datasets_py.logic.syntax_core.algebra import free_variables
from ipfs_datasets_py.logic.syntax_core.ast import NodeKind, mk_constant
from ipfs_datasets_py.logic.syntax_core.contracts import (
    ParseStatus,
    SyntaxContractError,
)
from ipfs_datasets_py.logic.syntax_core.signatures import atomic_sort


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    assert LEGACY_LOGIC_IMPORTER_INTERFACE == "LegacyLogicImporter@1"
    assert TDFOL_PROFILE_INTERFACE == "TDFOLProfile@1"
    assert DCEC_PROFILE_INTERFACE == "DCECProfile@1"
    importer = LegacyLogicImporter()
    assert importer.interface == LEGACY_LOGIC_IMPORTER_INTERFACE


def test_profiles_reject_left_associativity() -> None:
    with pytest.raises(SyntaxContractError, match="right"):
        TDFOLProfile(implication_associativity="left")
    with pytest.raises(SyntaxContractError, match="right"):
        DCECProfile(implication_associativity="left")


# ---------------------------------------------------------------------------
# TDFOL import
# ---------------------------------------------------------------------------


def test_import_tdfol_obligation() -> None:
    result = import_legacy_tdfol("O(report)")
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.receipt is not None
    assert result.receipt.family == "tdfol"
    assert result.receipt.implication_associativity == "right"
    assert result.receipt.status == "ok"
    # O/P/F ambiguity is explicit even when resolved as deontic.
    assert any(a.code == CODE_OPF_AMBIGUITY for a in result.receipt.ambiguities)
    assert any(a.resolution == "deontic" for a in result.receipt.ambiguities)


def test_import_tdfol_implies_right_assoc() -> None:
    result = import_legacy_tdfol("p -> q -> r")
    assert result.ok, [d.message for d in result.diagnostics]
    root = result.root
    assert root is not None
    assert root.kind is NodeKind.IMPLIES
    assert root.arguments[1].kind is NodeKind.IMPLIES
    assert root.metadata.get("associativity") == "right"
    assert result.receipt is not None
    assert result.receipt.implication_associativity == "right"


def test_import_tdfol_forall_with_sort() -> None:
    result = import_legacy_tdfol("forall x:Agent. Person(x) -> O(Report(x))")
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root.kind is NodeKind.FORALL


def test_tdfol_unknown_sort_does_not_disappear() -> None:
    result = import_legacy_tdfol("forall x:Widget. P(x)")
    assert not result.ok
    assert any(d.code == CODE_UNKNOWN_SORT for d in result.diagnostics)
    assert result.receipt is not None
    assert result.receipt.status == "failed"
    assert any(loss.code == CODE_UNKNOWN_SORT for loss in result.receipt.losses)


def test_tdfol_opf_rejected_when_profile_disallows() -> None:
    importer = LegacyLogicImporter(tdfol=profile_tdfol(admit_classic_opf=False))
    result = importer.import_text("O(report)", family=LegacyFamilyKind.TDFOL)
    assert not result.ok
    assert any(d.code == CODE_OPF_AMBIGUITY for d in result.diagnostics)


# ---------------------------------------------------------------------------
# DCEC / event-calculus import
# ---------------------------------------------------------------------------


def test_import_dcec_happens_holds() -> None:
    result = import_legacy_dcec("happens(turn_on, 1) and holds_at(light_on, 2)")
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.receipt is not None
    assert result.receipt.family == "dcec"
    assert result.receipt.implication_associativity == "right"


def test_import_dcec_sexpr_and() -> None:
    result = import_legacy_dcec("(and P Q)")
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root.kind is NodeKind.AND


def test_import_dcec_sexpr_obligation() -> None:
    result = import_legacy_dcec("(O report)")
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.receipt is not None
    assert any(a.code == CODE_OPF_AMBIGUITY for a in result.receipt.ambiguities)


def test_import_event_calculus_family() -> None:
    result = import_legacy(
        "initiates(turn_on, light_on, t)",
        family=LegacyFamilyKind.EVENT_CALCULUS,
    )
    assert result.ok, [d.message for d in result.diagnostics]


# ---------------------------------------------------------------------------
# Modal / legal
# ---------------------------------------------------------------------------


def test_import_modal_box_diamond() -> None:
    result = import_legacy(
        "box p implies diamond p",
        family=LegacyFamilyKind.MODAL,
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.receipt is not None
    assert result.receipt.family == "modal"


def test_import_legal_obligation() -> None:
    result = import_legacy(
        "obligated file_report",
        family=LegacyFamilyKind.LEGAL,
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.receipt is not None
    assert result.receipt.family == "legal"


# ---------------------------------------------------------------------------
# Unknown characters never disappear
# ---------------------------------------------------------------------------


def test_unknown_character_scan() -> None:
    hits = scan_unknown_characters("O(report) ☃")
    assert hits
    assert hits[0][1] == "☃"


def test_unknown_character_fails_closed_on_import() -> None:
    result = import_legacy_tdfol("O(report) ☃")
    assert not result.ok
    assert any(d.code == CODE_UNKNOWN_CHARACTER for d in result.diagnostics)
    assert result.receipt is not None
    assert any(loss.code == CODE_UNKNOWN_CHARACTER for loss in result.receipt.losses)


# ---------------------------------------------------------------------------
# Capture-safe substitution
# ---------------------------------------------------------------------------


def test_capture_safe_substitute_on_imported_ast() -> None:
    result = import_legacy_tdfol("forall x:Object. Person(x)")
    assert result.ok, [d.message for d in result.diagnostics]
    replacement = mk_constant("c:legacy:1", "alice", atomic_sort("Object"))
    rewritten = capture_safe_substitute(result.root, "x", replacement)
    # Bound x must not be freely captured by naive replacement at top level.
    assert rewritten.kind is NodeKind.FORALL
    free = free_variables(rewritten)
    # alice may appear only if algebra renames; free set must not silently
    # introduce capture of free vars of replacement under the binder.
    assert "alice" not in free or "x" not in free


def test_rebind_capture_unsafe_rejected() -> None:
    result = import_legacy_tdfol("forall x:Object. forall x:Object. P")
    assert not result.ok
    assert any("capture" in d.message.casefold() or "rebind" in d.message.casefold()
               for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Golden vector traceability
# ---------------------------------------------------------------------------


def test_builtin_golden_vectors_are_traceable() -> None:
    catalog = list_builtin_golden_vectors()
    assert len(catalog) >= 8
    ids = {item["vector_id"] for item in catalog}
    assert "legacy:tdfol:obligation_simple" in ids
    assert "legacy:dcec:happens_holds" in ids
    assert "legacy:modal:box_diamond" in ids

    digests = golden_vector_catalog()
    assert all("surface_sha256" in item for item in digests)
    assert all(len(item["surface_sha256"]) == 64 for item in digests)


def test_golden_vector_match_on_import() -> None:
    surface = "O(report)"
    trace = match_golden_vector(surface)
    assert trace is not None
    assert trace.matched is True
    assert trace.vector_id == "legacy:tdfol:obligation_simple"

    result = import_legacy_tdfol(surface)
    assert result.ok
    assert result.receipt is not None
    assert result.receipt.golden_traces
    assert result.receipt.golden_traces[0].matched is True
    assert result.receipt.surface_sha256
    assert len(result.receipt.surface_sha256) == 64


def test_all_builtin_golden_surfaces_import_or_are_documented() -> None:
    """Every golden surface either imports cleanly or has a stable failure code."""

    importer = LegacyLogicImporter()
    for item in list_builtin_golden_vectors():
        family = {
            "tdfol": LegacyFamilyKind.TDFOL,
            "dcec": LegacyFamilyKind.DCEC,
            "modal": LegacyFamilyKind.MODAL,
            "legal": LegacyFamilyKind.LEGAL,
        }.get(str(item["family"]), LegacyFamilyKind.AUTO)
        result = importer.import_text(str(item["surface"]), family=family)
        assert result.receipt is not None
        assert result.receipt.surface_sha256
        # Receipt always carries golden traceability.
        assert result.receipt.golden_traces
        if result.ok:
            assert result.root is not None
        else:
            assert result.diagnostics


# ---------------------------------------------------------------------------
# Family detection / OPF scan
# ---------------------------------------------------------------------------


def test_detect_legacy_family() -> None:
    assert detect_legacy_family("happens(e, t)") is LegacyFamilyKind.EVENT_CALCULUS
    assert detect_legacy_family("(and P Q)") is LegacyFamilyKind.DCEC
    assert detect_legacy_family("box p") is LegacyFamilyKind.MODAL
    assert detect_legacy_family("obligated p") is LegacyFamilyKind.LEGAL
    assert detect_legacy_family("O(p)") is LegacyFamilyKind.TDFOL


def test_scan_opf_occurrences() -> None:
    hits = scan_opf_occurrences("O(p) and F(q) and P(r)")
    letters = {letter for _, letter in hits}
    assert letters == {"O", "F", "P"}


def test_import_or_raise() -> None:
    importer = LegacyLogicImporter()
    node = importer.import_or_raise("O(report)", family=LegacyFamilyKind.TDFOL)
    assert node is not None
    with pytest.raises(LegacyImportError):
        importer.import_or_raise("O(report) ☃", family=LegacyFamilyKind.TDFOL)


def test_receipt_to_dict_is_json_friendly() -> None:
    result = import_legacy_tdfol("O(report)")
    assert result.ok
    payload = result.receipt.to_dict()
    assert payload["schema_version"]
    assert payload["implication_associativity"] == "right"
    assert isinstance(payload["ambiguities"], list)
    assert isinstance(payload["golden_traces"], list)
