"""All-family inventories backed by actual four-domain native projections."""
from copy import deepcopy
from dataclasses import replace
import importlib.util
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import family_training as api
from ipfs_datasets_py.logic.families.canonical_catalog import DEFAULT_CANONICAL_CATALOG_SNAPSHOT
from ipfs_datasets_py.logic.intent_ir.formalize.rich_grammar import parse_instruction
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRoundTripIR, CanonicalRule
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument, ModalIRFormula, ModalIROperator, ModalIRPredicate,
    ModalIRProvenance, ModalIRFrameLogic, ModalIRFrameLogicTriple,
)
from tests.unit.logic.formalization.autoencoder.family_native_fixtures import multiview_document

def _fixtures(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_HERE = Path(__file__).resolve().parent
_domains = _fixtures("family_domain_fixtures", _HERE.parent / "test_autoencoder_domain_targets.py")
_security = _fixtures("family_security_fixtures", _HERE.parent.parent / "security_ir/test_code_logic_projection.py")
_ui = _fixtures("family_ui_fixtures", _HERE / "test_autoencoder_ui_targets.py")
_ui_rows = _fixtures("family_ui_row_fixtures", _HERE / "test_ui_training_inputs.py")
intent, security, BODY = _domains.intent, _domains.security, _domains.BODY
binding, evidence = _security.binding, _security.evidence
_document, native_row = _ui._document, _ui_rows.native_row


def legal_document(index=0):
    """Actual canonical legal declaration; IDs vary by semantic source fields."""
    return CanonicalRoundTripIR((CanonicalRule("O", "agency", "publish", f"notice-{index}",
        conditions=("request_received",), exceptions=("emergency",), temporal=("within 10 days",)),))


def modal_document():
    text = "Agency must publish notice before deadline."
    provenance = ModalIRProvenance("document:law", 0, len(text))
    return ModalIRDocument("document:law", "authored", text, formulas=[
        ModalIRFormula("norm:one", ModalIROperator("deontic", "D", "O", "obligation"),
            ModalIRPredicate("publish", ["agency", "notice"], "clause"), provenance,
            conditions=["request_received"], exceptions=["emergency"]),
        ModalIRFormula("time:one", ModalIROperator("temporal", "LTL", "F", "eventually"),
            ModalIRPredicate("publish", ["agency", "notice"], "clause"), provenance,
            conditions=["before deadline"]),
    ], frame_logic=ModalIRFrameLogic(selected_frame="notice", graph_id="graph:law",
        triples=[ModalIRFrameLogicTriple("agency", "publishes", "notice")]))


def _inventory(report):
    return {row["family_id"]: row for row in report["family_inventory"]}


def _rehash(report):
    report["report_sha256"] = api._sha({key: value for key, value in report.items() if key != "report_sha256"})


@pytest.mark.parametrize("domain", api.DOMAINS)
def test_catalog_lists_baseline_and_published_extensions_without_claiming_readiness(domain):
    report = api.family_training_catalog(domain)
    inventory = _inventory(report)
    assert set(inventory) == set(DEFAULT_CANONICAL_CATALOG_SNAPSHOT.family_ids)
    assert len(inventory) == 40
    assert sum(row["registry_layer"] == "baseline_v2" for row in inventory.values()) == 35
    assert set(inventory) >= {"bdi", "agency", "linear_logic", "process_calculus", "epistemic_temporal"}
    assert not any(row["ready_for_training"] for row in inventory.values())
    assert all(row["requires"] and row["frontier"] for row in inventory.values())
    assert not report["registry_presence_establishes_support"]


def test_rich_atom_uses_real_native_views_and_replays_typed_source():
    text = "agent must inspect cache."
    ast = parse_instruction(text)
    report = api.prepare_family_training_targets("intent_ir", document=ast, source_text=text)
    assert len(report["projections"]) >= 12
    families = {row["logic_family"] for row in report["projections"]}
    assert families >= {"program", "dcec", "tdfol", "higher_order", "frame_logic", "deontic"}
    assert not report["all_requested_families_available"]
    assert _inventory(report)["cryptographic_protocol"]["status"] == "unsupported"
    assert all(row["payload"] and row["validation"] and row["ready_for_training"] for row in report["projections"])
    assert api.validate_family_training_report(report, document=ast, source_text=text) == report
    assert report["provider_calls"] == report["external_backend_calls"] == 0
    assert not any(report[key] for key in api.AUTHORITY)


def test_conditional_targets_never_flatten_into_unconditional_native_program():
    text = "if cache is not empty, agent must not delete cache."
    report = api.prepare_family_training_targets("intent_ir", document=parse_instruction(text), source_text=text)
    assert {row["logic_family"] for row in report["projections"]} == {"higher_order", "dcec", "tdfol"}
    assert all(row["projection_id"].startswith("rich-intent/") for row in report["projections"])
    dcec = next(row for row in report["projections"] if row["logic_family"] == "dcec")
    assert "implies" in dcec["payload"]["source"] and "not" in dcec["payload"]["source"]
    assert _inventory(report)["program"]["target_count"] == 0


def test_sequence_uses_abstract_state_views_without_orderless_lean():
    text = "agent must inspect cache then reviewer may approve report."
    report = api.prepare_family_training_targets("intent_ir", document=parse_instruction(text), source_text=text)
    assert {row["logic_family"] for row in report["projections"]} == {"transition_system"}
    assert len(report["projections"]) == 2
    assert any("abstract_control_flow" in gap for gap in report["qualification_gaps"])
    assert not _inventory(report)["higher_order"]["ready_for_training"]


def test_atom_and_sequence_training_heads_keep_distinct_producer_identities():
    descriptors = {}
    state_ids = set()
    for text in ("agent must inspect cache.", "agent must inspect cache then reviewer may approve report."):
        report = api.prepare_family_training_targets("intent_ir", document=parse_instruction(text), source_text=text)
        for row in report["projections"]:
            identity = row["projection_id"]
            descriptor = tuple(row[key] for key in ("logic_family", "representation_kind", "profile", "producer_id"))
            assert descriptors.setdefault(identity, descriptor) == descriptor
            if row["logic_family"] == "transition_system":
                state_ids.add(identity)
        assert api.validate_family_training_report(report, document=parse_instruction(text), source_text=text) == report
    assert state_ids == {f"{producer}/transition_system/{profile}/v1"
                         for producer in ("intent-extended", "rich-intent")
                         for profile in ("default", "tla_plus")}


def test_native_intent_document_remains_supported(intent):
    report = api.prepare_family_training_targets("intent_ir", document=intent, requested_families=["deontic"])
    assert {row["logic_family"] for row in report["projections"]} == {"deontic"}
    assert report["all_requested_families_available"]
    assert api.validate_family_training_report(report, document=intent) == report


@pytest.mark.parametrize("families", [["smt"], ["TLA+"], ["fol"], ["dcec", "dcec"], []])
def test_profiles_aliases_duplicates_and_empty_selection_are_not_families(families):
    with pytest.raises(ValueError):
        api.prepare_family_training_targets("legal_ir", document=legal_document(), requested_families=families)


def test_changed_source_cannot_relabel_a_rich_ast():
    with pytest.raises(ValueError, match="complete source agreement"):
        api.prepare_family_training_targets("intent_ir", document=parse_instruction("agent must inspect cache."),
            source_text="agent may inspect cache.")


def test_security_missing_other_models_does_not_invalidate_actual_program_target(security):
    unit, program = security
    report = api.prepare_family_training_targets("security_ir", code_unit=unit, source_bytes=BODY, typed_inputs=[program])
    assert len(report["projections"]) == 1
    assert report["projections"][0]["logic_family"] == "program" and report["projections"][0]["ready_for_training"]
    assert any(row.get("kind") == "contract" and row["reason"] == "missing_typed_evidence" for row in report["frontier"])
    assert not _inventory(report)["separation_logic"]["ready_for_training"]
    assert api.validate_family_training_report(report, code_unit=unit, source_bytes=BODY, typed_inputs=[program]) == report


def test_security_all_supplied_native_models_keep_seven_views_and_five_families(binding):
    unit, source = binding
    report = api.prepare_family_training_targets("security_ir", code_unit=unit, source_bytes=BODY, typed_inputs=evidence(source))
    assert len(report["projections"]) == 7
    assert {row["logic_family"] for row in report["projections"]} == {
        "program", "transition_system", "temporal", "separation_logic", "hyperproperty"}
    assert all(row["ready_for_training"] for row in report["projections"])
    assert report["external_backend_calls"] == 0


def test_security_labels_without_typed_models_create_no_training_targets(security):
    unit, _ = security
    report = api.prepare_family_training_targets("security_ir", code_unit=unit, source_bytes=BODY)
    assert not report["projections"] and not report["ready_for_training"]
    with pytest.raises(ValueError, match="SHA differs"):
        api.prepare_family_training_targets("security_ir", code_unit=unit, source_bytes=BODY + b"\n")


def test_ui_native_structure_does_not_invent_temporal_or_cognitive_targets():
    report = api.prepare_family_training_targets("ui_ux_ir", document=_document())
    assert {row["logic_family"] for row in report["projections"]} == {"frame_logic"}
    assert _inventory(report)["tdfol"]["status"] == "unsupported"
    assert any(gap.get("code") == "ui_ux.family_syntax_not_checked" for gap in report["qualification_gaps"] if isinstance(gap, dict))


def test_verified_ui_input_retains_actual_interface_bindings_and_source_identity():
    row = native_row()
    report = api.prepare_family_training_targets("ui_ux_ir", ui_training_row=row)
    assert len(report["projections"]) == 5
    assert len({target["logic_family"] for target in report["projections"]}) == 4
    contract = next(target for target in report["projections"] if target["projection_id"] == "ui_ux_ir:interface_bindings")
    assert contract["payload"]["interface_cid"] == row["interface"]["claimed_interface_cid"]
    assert contract["logic_family"] == "frame_logic"
    assert api.validate_family_training_report(report, ui_training_row=row) == report
    changed = deepcopy(row); changed["provenance"]["revision"] = "fixture-v2"
    assert api.prepare_family_training_targets("ui_ux_ir", ui_training_row=changed)["source_digest"] != report["source_digest"]
    changed["interface"]["descriptor"]["version"] = "2.0.0"
    with pytest.raises(ValueError): api.prepare_family_training_targets("ui_ux_ir", ui_training_row=changed)


def test_legal_canonical_target_preserves_all_facets_without_inventing_temporal_logic():
    document = legal_document()
    report = api.prepare_family_training_targets("legal_ir", document=document)
    assert len(report["projections"]) == 1
    row = report["projections"][0]
    assert row["logic_family"] == "deontic" and row["payload"] == document.to_dict()
    assert not _inventory(report)["tdfol"]["ready_for_training"]
    assert not _inventory(report)["dcec"]["ready_for_training"]
    assert "existing_modal_and_legal_bridge" in _inventory(report)["dcec"]["frontier"]
    assert api.validate_family_training_report(report, document=document) == report


def test_native_modal_legal_views_validate_contracts_and_ignore_metadata_override():
    document = modal_document()
    report = api.prepare_family_training_targets("legal_ir", document=document, source_text=document.normalized_text)
    assert {row["logic_family"] for row in report["projections"]} == {"deontic", "tdfol", "frame_logic"}
    assert all(row["ready_for_training"] for row in report["projections"])
    changed = replace(document, metadata={"legal_ir_views": {"cec": {"formula": "InventedTrue"}}})
    other = api.prepare_family_training_targets("legal_ir", document=changed)
    assert {row["logic_family"] for row in other["projections"]} == {"deontic", "tdfol", "frame_logic"}
    assert [row["payload"] for row in other["projections"]] == [row["payload"] for row in report["projections"]]
    assert api.validate_family_training_report(report, document=document, source_text=document.normalized_text) == report
    with pytest.raises(ValueError, match="exact source differs"):
        api.prepare_family_training_targets("legal_ir", document=document, source_text="different source")


def test_legal_modal_stale_provenance_is_refused():
    document = modal_document()
    changed = replace(document, formulas=[replace(document.formulas[0], provenance=ModalIRProvenance("different", 0, 5))])
    with pytest.raises(ValueError, match="provenance differs"):
        api.prepare_family_training_targets("legal_ir", document=changed)


def test_native_multiview_legal_records_enable_event_calculus_without_claiming_dcec():
    document = multiview_document()
    report = api.prepare_family_training_targets("legal_ir", document=document, source_text=document.document.source_text)
    assert {row["logic_family"] for row in report["projections"]} == {"deontic", "tdfol", "frame_logic", "event_calculus"}
    assert all(row["ready_for_training"] for row in report["projections"])
    assert _inventory(report)["dcec"]["target_count"] == 0
    assert not report["proof_authority"] and report["external_backend_calls"] == 0
    assert api.validate_family_training_report(report, document=document, source_text=document.document.source_text) == report


def test_multiview_missing_or_failed_cec_stage_never_creates_cec_target():
    document = multiview_document()
    reports = dict(document.reports)
    reports["cec_dcec"] = replace(reports["cec_dcec"], status="failed")
    changed = replace(document, reports=reports)
    report = api.prepare_family_training_targets("legal_ir", document=changed)
    assert not any(row["logic_family"] == "event_calculus" for row in report["projections"])
    assert any(row["reason"] == "failed_native_bridge_stage_not_training_evidence" for row in report["frontier"])
    reports.pop("cec_dcec")
    missing = replace(document, reports=reports, failures={"cec_dcec": "unavailable"})
    report = api.prepare_family_training_targets("legal_ir", document=missing)
    assert not any(row["logic_family"] == "event_calculus" for row in report["projections"])
    assert {"adapter": "cec_dcec", "reason": "native_bridge_failure", "details": "unavailable"} in report["qualification_gaps"]


@pytest.mark.parametrize("mutation", ["source", "adapter", "view", "overlap"])
def test_multiview_stale_or_inconsistent_native_stage_is_refused(mutation):
    document = multiview_document()
    reports = dict(document.reports)
    stage = reports["cec_dcec"]
    if mutation == "source":
        stage = replace(stage, ir_document=replace(stage.ir_document, source_text="another law"))
    elif mutation == "adapter": stage = replace(stage, adapter_name="different")
    elif mutation == "view":
        views = dict(stage.ir_document.views)
        key = next(iter(views)); views[key] = replace(views[key], name="different")
        stage = replace(stage, ir_document=replace(stage.ir_document, views=views))
    reports["cec_dcec"] = stage
    document = replace(document, reports=reports, failures={"cec_dcec": "failed"} if mutation == "overlap" else {})
    with pytest.raises(ValueError): api.prepare_family_training_targets("legal_ir", document=document)


def test_rehashed_readiness_and_inventory_forgery_fail_structural_validation():
    report = api.prepare_family_training_targets("legal_ir", document=legal_document())
    for alteration in ("target", "inventory", "complete", "authority", "pin"):
        forged = deepcopy(report)
        if alteration == "target":
            forged["projections"][0]["ready_for_training"] = False
            forged["projections"][0]["target_sha256"] = api._sha({key: value for key, value in forged["projections"][0].items() if key != "target_sha256"})
        elif alteration == "inventory": _inventory(forged)["bdi"]["ready_for_training"] = True
        elif alteration == "complete": forged["all_requested_families_available"] = True
        elif alteration == "authority": forged["proof_authority"] = True
        else: forged["producer_pins"][api.__name__] = "0" * 64
        _rehash(forged)
        with pytest.raises(ValueError): api.validate_family_training_report(forged)


def test_exact_source_replay_refuses_semantically_changed_resigned_payload():
    document = legal_document()
    report = api.prepare_family_training_targets("legal_ir", document=document)
    report["projections"][0]["payload"]["rules"][0]["modality"] = "P"
    row = report["projections"][0]
    row["target_sha256"] = api._sha({key: value for key, value in row.items() if key != "target_sha256"})
    _rehash(report)
    # Selfhash/pins are structural checks, not evidence of authentic source.
    assert api.validate_family_training_report(report) == report
    with pytest.raises(ValueError, match="typed source replay"):
        api.validate_family_training_report(report, document=document)


@pytest.mark.parametrize("kwargs", [
    {"domain_id": "ui_ux_ir", "document": _document(), "ui_training_row": {}},
    {"domain_id": "legal_ir", "document": legal_document(), "source_bytes": BODY},
    {"domain_id": "legal_ir", "document": legal_document(), "context": {}},
    {"domain_id": "security_ir", "document": {}},
])
def test_cross_domain_or_unused_inputs_are_rejected(kwargs):
    with pytest.raises(ValueError): api.prepare_family_training_targets(**kwargs)
