"""Whole-source fidelity and exact replay for the additive UI logic target."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import ui_declared_logic_source as owner
from ipfs_datasets_py.logic.formalization.autoencoder import ui_declared_source_fidelity as old


def fixture():
    path = Path(__file__).resolve().parents[4] / "fixtures/logic/ui_modal_logic_v1/dcec_cases.py"
    spec = importlib.util.spec_from_file_location("compound_ui_source_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.base_case()


@pytest.fixture(scope="module")
def prepared():
    row = fixture()
    packet = owner.prepare_family_targets(row["source_text"], row["candidate"])
    return row, packet


def test_exact_candidate_keeps_modal_declarations_and_no_decoder_claim(prepared):
    row, packet = prepared
    audit = packet["audit"]["source_audit"]
    assert audit["source_agreement"] and audit["candidate"] == row["candidate"]
    assert audit["target_token_window"]["tokens_with_boundaries"] > 64
    assert audit["target_token_window"]["model_target_token_limit"] == 64
    assert audit["current_learned_decoder_compatible"] is False
    assert audit["neural_rich_document_generation_verified"] is False
    assert packet["audit"]["candidate_rewritten"] is False


@pytest.mark.parametrize("field", ["document", "logic"])
def test_audit_does_not_repair_original_model_prediction(prepared, field):
    row, _ = prepared
    candidate = deepcopy(row["candidate"])
    if field == "document":
        candidate["document"]["title"] = "Different source title"
    else:
        candidate["logic"]["dcec"]["formulas"][0]["formula"] = "B(Operator,P(Happens(Close,Tick12)))"
    before = deepcopy(candidate)
    audit = owner.audit_candidate(row["source_text"], candidate)
    assert audit["status"] == "source_disagreement" and audit["differences"]
    assert audit["candidate"] == before == candidate
    with pytest.raises(ValueError, match="source_disagreement"):
        owner.prepare_family_targets(row["source_text"], candidate)


def test_plain_ui_candidate_cannot_acquire_source_only_formulas(prepared):
    row, _ = prepared
    candidate = {"kind": "document", "document": deepcopy(row["candidate"]["document"])}
    audit = owner.audit_candidate(row["source_text"], candidate)
    assert audit["status"] == "native_invalid"
    assert audit["candidate"] == candidate and "logic" not in candidate


@pytest.mark.parametrize("mutation", ["extra", "duplicate", "nonfinite", "missing_event", "wrong_schema"])
def test_closed_original_source_contract(prepared, mutation):
    row, _ = prepared
    source = json.loads(row["source_text"])
    if mutation == "extra": source["inferred_context"] = {}
    if mutation == "missing_event": source["interpretations"]["event"] = None
    if mutation == "wrong_schema": source["schema"] = old.SOURCE_SCHEMA
    text = json.dumps(source)
    if mutation == "duplicate": text = '{"schema":"duplicate",' + text[1:]
    if mutation == "nonfinite": text = text[:-1] + ',"untrusted":NaN}'
    assert owner.audit_candidate(text, row["candidate"])["status"] == "source_unsupported"


def test_old_source_schema_is_not_silently_upgraded(prepared):
    row, _ = prepared
    old_candidate = {"kind": "document", "document": row["candidate"]["document"]}
    assert old.audit_candidate(row["source_text"], old_candidate)["status"] == "source_unsupported"


def test_every_original_projection_is_preserved(prepared):
    _, packet = prepared
    report = packet["report"]
    assert len(report["requested_families"]) == len(report["family_inventory"]) == 40
    rows = {row["projection_id"]: row for row in report["projections"]}
    original = report["base_ui_report"]
    retained = lambda value: {k: v for k, v in value.items() if k not in {"source_digest", "target_sha256"}}
    for row in original["projections"]:
        assert owner.core._wire(retained(rows[row["projection_id"]])) == owner.core._wire(retained(row))
    assert report["all_requested_families_available"] is False
    assert report["source_decoder_trained"] is False
    assert report["base_ui_report"]["superseded_bounded_event_observations"]


def test_replay_binds_whole_original_source(prepared):
    _, packet = prepared
    assert owner.validate_family_training_report(packet["report"], **packet["source_inputs"]) is packet["report"]
    inputs = deepcopy(packet["source_inputs"])
    inputs["source_text"] += " "
    with pytest.raises(ValueError, match="replay differs"):
        owner.validate_family_training_report(packet["report"], **inputs)


def test_coherently_rehashed_boolean_coercion_is_rejected(prepared):
    _, packet = prepared
    report = deepcopy(packet["report"])
    report["declared_logic_source_binding"]["candidate"]["logic"]["dcec"]["times"][0]["clock_time"] = 12.0
    report["report_sha256"] = owner.digest({k: v for k, v in report.items() if k != "report_sha256"})
    with pytest.raises(ValueError, match="replay differs"):
        owner.validate_family_training_report(report, **packet["source_inputs"])


def test_declared_family_cannot_be_dropped_from_requested_scope(prepared):
    row, packet = prepared
    requested = [name for name in packet["report"]["requested_families"] if name != "dcec"]
    with pytest.raises(ValueError, match="declared logic family cannot be omitted"):
        owner.prepare_family_targets(row["source_text"], row["candidate"], requested)


def test_altered_native_leaf_cannot_be_rehashed_into_replay(prepared):
    _, packet = prepared
    report = deepcopy(packet["report"])
    row = next(row for row in report["projections"] if row["logic_family"] == "dcec")
    row["payload"]["source_semantics_verified"] = True
    row["target_sha256"] = owner.digest({k: v for k, v in row.items() if k != "target_sha256"})
    report["report_sha256"] = owner.digest({k: v for k, v in report.items() if k != "report_sha256"})
    with pytest.raises(ValueError, match="replay differs"):
        owner.validate_family_training_report(report, **packet["source_inputs"])
