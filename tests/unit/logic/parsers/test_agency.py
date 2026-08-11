"""Unit tests for AgencyLogicProfiles@1 (LFP2-040).

Evidence subset:

* BDI, epistemic-temporal, agency, and intention profiles
* agent / time indices are explicit and enforced
* frame / introspection assumptions are explicit profile fields
* BDI and DCEC profiles are not conflated
* DCEC surface requires an explicit DCECImporterHook
* parse/print/parse semantic round-trip
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.parsers.agency import (
    AGENCY_FAMILY_ID,
    AGENCY_LOGIC_PROFILES_INTERFACE,
    AGENCY_PROFILE_INTERFACE,
    BDI_FAMILY_ID,
    CODE_AGENT_REQUIRED,
    CODE_DCEC_HOOK_REQUIRED,
    CODE_OPERATOR_FORBIDDEN,
    CODE_OVERLOADED_SYMBOL,
    CODE_PROFILE_MISMATCH,
    CODE_PROFILE_REQUIRED,
    CODE_TIME_FORBIDDEN,
    CODE_TIME_REQUIRED,
    DCEC_FAMILY_ID,
    DCEC_IMPORTER_HOOK_INTERFACE,
    EPISTEMIC_TEMPORAL_FAMILY_ID,
    INTENTION_FAMILY_ID,
    AccessibilityFrame,
    AgencyFamilyKind,
    AgencyLogicProfile,
    AgencyLogicProfiles,
    AgencyParser,
    AgencyPrinter,
    DCECImporterHook,
    IntrospectionAssumption,
    agency_semantic_identity,
    parse_agency,
    parse_print_parse,
    print_agency,
    profile_agency,
    profile_bdi,
    profile_epistemic_temporal,
    profile_intention,
    reject_bdi_dcec_conflation,
)
from ipfs_datasets_py.logic.syntax_core.algebra import alpha_equivalent
from ipfs_datasets_py.logic.syntax_core.ast import NodeKind
from ipfs_datasets_py.logic.syntax_core.contracts import (
    ParseStatus,
    SyntaxContractError,
)


def _bdi() -> AgencyLogicProfile:
    return profile_bdi()


def _et() -> AgencyLogicProfile:
    return profile_epistemic_temporal()


def _agency() -> AgencyLogicProfile:
    return profile_agency()


def _intention() -> AgencyLogicProfile:
    return profile_intention()


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_and_module_identity() -> None:
    assert AGENCY_LOGIC_PROFILES_INTERFACE == "AgencyLogicProfiles@1"
    assert AGENCY_PROFILE_INTERFACE == "AgencyLogicProfile@1"
    assert DCEC_IMPORTER_HOOK_INTERFACE == "DCECImporterHook@1"
    assert BDI_FAMILY_ID == "bdi"
    assert EPISTEMIC_TEMPORAL_FAMILY_ID == "epistemic_temporal"
    assert AGENCY_FAMILY_ID == "agency"
    assert INTENTION_FAMILY_ID == "intention_agency"
    assert DCEC_FAMILY_ID == "dcec"
    # Non-conflation: BDI family is never DCEC.
    assert BDI_FAMILY_ID != DCEC_FAMILY_ID

    logic = AgencyLogicProfiles(_bdi())
    assert logic.interface == AGENCY_LOGIC_PROFILES_INTERFACE
    assert isinstance(logic.parser, AgencyParser)
    assert isinstance(logic.printer, AgencyPrinter)


def test_profiles_expose_explicit_agent_time_frame_introspection() -> None:
    bdi = _bdi()
    assert bdi.family is AgencyFamilyKind.BDI
    assert bdi.family_id == BDI_FAMILY_ID
    assert bdi.require_agent_index is True
    assert bdi.require_time_index is False
    assert bdi.allow_time_index is False
    assert bdi.frame is AccessibilityFrame.KD45
    assert bdi.introspection is IntrospectionAssumption.POSITIVE_AND_NEGATIVE
    assert bdi.frame_axioms["serial"] is True
    assert bdi.frame_axioms["transitive"] is True
    assert bdi.frame_axioms["euclidean"] is True
    assert bdi.introspection_flags["positive_introspection"] is True
    assert bdi.introspection_flags["negative_introspection"] is True
    assert bdi.semantic_identity["dcec_conflated"] is False
    assert bdi.semantic_identity["is_dcec_profile"] is False
    assert bdi.semantic_identity["family_id"] == BDI_FAMILY_ID
    assert bdi.semantic_identity["require_agent_index"] is True
    assert bdi.semantic_identity["frame"] == "kd45"
    assert bdi.semantic_identity["introspection"] == "positive_and_negative"

    et = _et()
    assert et.family is AgencyFamilyKind.EPISTEMIC_TEMPORAL
    assert et.family_id == EPISTEMIC_TEMPORAL_FAMILY_ID
    assert et.require_agent_index is True
    assert et.require_time_index is True
    assert et.allow_time_index is True
    assert et.frame is AccessibilityFrame.S5
    assert et.introspection is IntrospectionAssumption.FULL
    assert et.frame_axioms["reflexive"] is True
    assert et.frame_axioms["euclidean"] is True
    assert et.introspection_flags["positive_introspection"] is True
    assert et.introspection_flags["negative_introspection"] is True

    agency = _agency()
    assert agency.family is AgencyFamilyKind.AGENCY
    assert agency.family_id == AGENCY_FAMILY_ID
    assert agency.admit_action_atoms is True
    assert agency.frame is AccessibilityFrame.D

    intention = _intention()
    assert intention.family is AgencyFamilyKind.INTENTION
    assert intention.family_id == INTENTION_FAMILY_ID
    assert intention.introspection is IntrospectionAssumption.POSITIVE


def test_profile_rejects_dcec_family_conflation() -> None:
    with pytest.raises(SyntaxContractError, match="dcec"):
        AgencyLogicProfile(
            profile_id="dcec",
            family=AgencyFamilyKind.BDI,
            frame=AccessibilityFrame.KD45,
            introspection=IntrospectionAssumption.NONE,
        )
    with pytest.raises(SyntaxContractError, match="dcec"):
        DCECImporterHook(dcec_family_id="bdi")
    with pytest.raises(SyntaxContractError, match="preserve_source_family"):
        DCECImporterHook(preserve_source_family=False)
    with pytest.raises(SyntaxContractError, match="not conflated|dcec"):
        reject_bdi_dcec_conflation(bdi_family=DCEC_FAMILY_ID)
    reject_bdi_dcec_conflation(bdi_family=BDI_FAMILY_ID, dcec_family=DCEC_FAMILY_ID)


def test_epistemic_temporal_requires_time_and_frame() -> None:
    with pytest.raises(SyntaxContractError, match="allow_time_index"):
        AgencyLogicProfile(
            profile_id="bad_et",
            family=AgencyFamilyKind.EPISTEMIC_TEMPORAL,
            frame=AccessibilityFrame.S5,
            introspection=IntrospectionAssumption.FULL,
            allow_time_index=False,
            require_time_index=False,
        )
    with pytest.raises(SyntaxContractError, match="frame"):
        AgencyLogicProfile(
            profile_id="bad_et_frame",
            family=AgencyFamilyKind.EPISTEMIC_TEMPORAL,
            frame=AccessibilityFrame.NONE,
            introspection=IntrospectionAssumption.FULL,
            allow_time_index=True,
            require_time_index=True,
        )


# ---------------------------------------------------------------------------
# Happy-path BDI
# ---------------------------------------------------------------------------


def test_parse_bdi_belief_desire_intention() -> None:
    result = parse_agency(
        "believes[alice] p and desires[alice] q and intends[alice] r",
        _bdi(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.AND
    assert result.profile is not None
    assert result.profile.family_id == BDI_FAMILY_ID
    printed = print_agency(result.root)
    assert "believes[alice]" in printed
    assert "desires[alice]" in printed
    assert "intends[alice]" in printed


def test_parse_bdi_goal_atom() -> None:
    result = parse_agency(
        "believes[bob] safe and goal(bob, evacuate)",
        _bdi(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    printed = print_agency(result.root)
    assert "goal(bob, evacuate)" in printed


def test_bdi_requires_agent_index() -> None:
    result = parse_agency("believes p", _bdi())
    assert not result.ok
    assert any(d.code == CODE_AGENT_REQUIRED for d in result.diagnostics)


def test_bdi_rejects_time_index() -> None:
    result = parse_agency("believes[alice]@t0 p", _bdi())
    assert not result.ok
    assert any(d.code == CODE_TIME_FORBIDDEN for d in result.diagnostics)


def test_bdi_rejects_knows() -> None:
    result = parse_agency("knows[alice] p", _bdi())
    assert not result.ok
    assert any(d.code == CODE_OPERATOR_FORBIDDEN for d in result.diagnostics)


def test_classic_letters_require_admission() -> None:
    result = parse_agency("B[alice] p", _bdi())
    assert not result.ok
    assert any(d.code == CODE_OVERLOADED_SYMBOL for d in result.diagnostics)

    admitted = profile_bdi(admit_classic_letters=True)
    result2 = parse_agency("B[alice] p", admitted)
    assert result2.ok, [d.message for d in result2.diagnostics]


# ---------------------------------------------------------------------------
# Epistemic-temporal
# ---------------------------------------------------------------------------


def test_parse_epistemic_temporal_with_time() -> None:
    result = parse_agency("knows[alice]@t0 safe", _et())
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.EXTENSION
    payload = dict(result.root.extension.payload)  # type: ignore[union-attr]
    assert payload["agent"] == "alice"
    assert payload["time"] == "t0"
    assert payload["agent_indexed"] is True
    assert payload["time_indexed"] is True
    assert payload["frame"] == "s5"
    assert payload["introspection"] == "full"
    assert payload["is_dcec"] is False
    assert payload["family"] == EPISTEMIC_TEMPORAL_FAMILY_ID
    printed = print_agency(result.root)
    assert "knows[alice]@t0" in printed


def test_epistemic_temporal_requires_time_index() -> None:
    result = parse_agency("knows[alice] safe", _et())
    assert not result.ok
    assert any(d.code == CODE_TIME_REQUIRED for d in result.diagnostics)


def test_epistemic_temporal_believes_with_time() -> None:
    result = parse_agency("believes[carol]@5 raining", _et())
    assert result.ok, [d.message for d in result.diagnostics]
    payload = dict(result.root.extension.payload)  # type: ignore[union-attr]
    assert payload["time"] == "5"
    assert payload["attitude"] == "believes"


# ---------------------------------------------------------------------------
# Agency profile
# ---------------------------------------------------------------------------


def test_parse_agency_does_and_action() -> None:
    result = parse_agency(
        "does[alice]@t0 open_door and action(alice, open_door, t0) and agent(alice)",
        _agency(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    printed = print_agency(result.root)
    assert "does[alice]@t0" in printed
    assert "action(alice, open_door, t0)" in printed
    assert "agent(alice)" in printed


def test_agency_profile_rejects_believes() -> None:
    result = parse_agency("believes[alice] p", _agency())
    assert not result.ok
    assert any(d.code == CODE_OPERATOR_FORBIDDEN for d in result.diagnostics)


def test_bdi_rejects_action_atoms() -> None:
    result = parse_agency("action(alice, run)", _bdi())
    assert not result.ok
    assert any(d.code == CODE_PROFILE_MISMATCH for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Intention profile
# ---------------------------------------------------------------------------


def test_parse_intention_profile() -> None:
    result = parse_agency(
        "intends[alice] report and goal(alice, compliance)",
        _intention(),
    )
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.profile is not None
    assert result.profile.family_id == INTENTION_FAMILY_ID
    identity = agency_semantic_identity(result.root, result.profile)  # type: ignore[arg-type]
    assert identity["family"] == INTENTION_FAMILY_ID
    assert identity["profile"]["frame"] == "d"
    assert identity["profile"]["introspection"] == "positive"
    assert identity["profile"]["dcec_conflated"] is False


# ---------------------------------------------------------------------------
# DCEC non-conflation / importer hooks
# ---------------------------------------------------------------------------


def test_dcec_surface_rejected_without_hook() -> None:
    result = parse_agency("happens(turn_on, 1)", _bdi())
    assert not result.ok
    assert any(d.code == CODE_DCEC_HOOK_REQUIRED for d in result.diagnostics)
    # Family identity on the BDI profile remains non-DCEC.
    assert _bdi().family_id != DCEC_FAMILY_ID


def test_dcec_surface_admitted_via_explicit_hook() -> None:
    hook = DCECImporterHook.enabled_bridge(dcec_profile_id="dcec_default")
    assert hook.enabled is True
    assert hook.dcec_family_id == DCEC_FAMILY_ID
    assert hook.preserve_source_family is True
    # Source family stays BDI; imported family is DCEC.
    profile = profile_bdi(dcec_hook=hook)
    assert profile.family_id == BDI_FAMILY_ID
    assert profile.dcec_surface_admitted is True
    assert profile.semantic_identity["is_dcec_profile"] is False
    assert profile.semantic_identity["dcec_hook"]["dcec_family_id"] == DCEC_FAMILY_ID

    result = parse_agency("happens(turn_on, 1)", profile)
    assert result.ok, [d.message for d in result.diagnostics]
    assert result.root is not None
    assert result.root.kind is NodeKind.EXTENSION
    # Extension family remains the source BDI family, not dcec.
    assert result.root.extension is not None
    family_value = result.root.extension.family
    assert getattr(family_value, "value", None) == BDI_FAMILY_ID
    payload = dict(result.root.extension.payload)
    assert payload["is_dcec_import"] is True
    assert payload["is_dcec"] is False
    assert payload["imported_family"] == DCEC_FAMILY_ID
    assert payload["source_family"] == BDI_FAMILY_ID
    assert payload["source_family"] != payload["imported_family"]
    # Explicit non-conflation: source and imported families remain distinct.
    assert profile.family_id != DCEC_FAMILY_ID
    assert profile.semantic_identity["dcec_conflated"] is False


def test_profile_free_parse_rejected() -> None:
    parser = AgencyParser(profile=None)
    from ipfs_datasets_py.logic.syntax_core.contracts import SourceDocument

    doc = SourceDocument.from_text("doc:1", "believes[alice] p")
    result = parser.parse_document(doc, profile=None)
    assert not result.ok
    assert any(d.code == CODE_PROFILE_REQUIRED for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Round-trip / implication
# ---------------------------------------------------------------------------


def test_parse_print_parse_round_trip() -> None:
    text = "believes[alice] p implies intends[alice] q"
    first, second, equivalent = parse_print_parse(text, _bdi())
    assert first.ok, [d.message for d in first.diagnostics]
    assert second.ok, [d.message for d in second.diagnostics]
    assert equivalent
    assert alpha_equivalent(first.root, second.root)  # type: ignore[arg-type]


def test_epistemic_temporal_round_trip() -> None:
    text = "knows[alice]@t0 safe implies believes[bob]@t1 safe"
    first, second, equivalent = parse_print_parse(text, _et())
    assert first.ok, [d.message for d in first.diagnostics]
    assert second.ok, [d.message for d in second.diagnostics]
    assert equivalent


def test_implication_is_right_associative() -> None:
    result = parse_agency("p -> q -> r", _bdi())
    assert result.ok, [d.message for d in result.diagnostics]
    root = result.root
    assert root is not None
    assert root.kind is NodeKind.IMPLIES
    right = root.arguments[1]
    assert right.kind is NodeKind.IMPLIES
    assert root.metadata.get("associativity") == "right"


def test_semantic_identity_includes_profile() -> None:
    result = parse_agency("believes[alice] p", _bdi())
    assert result.ok
    identity = agency_semantic_identity(result.root, _bdi())  # type: ignore[arg-type]
    assert identity["family"] == BDI_FAMILY_ID
    assert identity["profile"]["require_agent_index"] is True
    assert identity["profile"]["frame"] == "kd45"
    assert identity["profile"]["introspection_flags"]["positive_introspection"] is True
    assert identity["profile"]["dcec_conflated"] is False
    assert identity["profile"]["is_dcec_profile"] is False


def test_profile_to_dict_round_trip() -> None:
    original = profile_epistemic_temporal()
    restored = AgencyLogicProfile.from_dict(original.to_dict())
    assert restored.profile_id == original.profile_id
    assert restored.family == original.family
    assert restored.frame == original.frame
    assert restored.introspection == original.introspection
    assert restored.require_time_index is True
    assert restored.family_id != DCEC_FAMILY_ID


def test_empty_input_rejected() -> None:
    result = parse_agency("   ", _bdi())
    assert not result.ok
    assert result.status is not ParseStatus.OK
