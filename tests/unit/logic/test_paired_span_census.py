"""Paired outputs, honest comparison, deferred native goals and bounded storage."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal.paired_span_census import (
    FORMAL_FORMAT, PairedCensusError, arrow_schemas, build_paired_census,
    decode_artifact, load_paired_census_bundle, write_paired_census_bundle,
    capture_learned_formula_observations, validate_learned_formula_observation,
)


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _rule(**extra):
    return {"modality": "Obligation", "actor": "agency", "action": "retain", "object": "record",
            "temporal": {"kind": "minimum_duration", "quantity": 20, "unit": "days"}, **extra}


def _row(span_id="span1", *, rule=None):
    text = "The agency shall retain the record for at least 20 days."
    return {"source_span_id": span_id, "text": text, "legal_id": "usc:5:1",
            "compiler_result": {"compiler_status": "compiled", "rules": [_rule() if rule is None else rule],
                "components": [], "compilation_complete": True, "decompiled": text, "roundtrip": True},
            "autoencoder_observation": {"raw_decoder": {"embedding": [0.1, 0.2], "cosine_similarity": 0.8,
                "reconstruction_loss": 0.1}, "embedding_representation": {"embedding_model": "mock:stable-sha256", "semantic_embeddings": False}}}


def _formal(rule, origin="autoencoder_decoder", *, independent=True, syntax="passed"):
    return {"family": "typed_deontic", "format": FORMAL_FORMAT, "payload": rule,
            "origin": origin, "independent": independent, "target_conditioned": not independent,
            "syntax_status": syntax}


def _with_ae(row, rules=None, *, origin="autoencoder_decoder", independent=True, syntax="passed"):
    row["model_formal_outputs"] = [_formal(rule, origin, independent=independent, syntax=syntax)
                                    for rule in (rules if rules is not None else row["compiler_result"]["rules"])]
    row["model_formal_output_provenance"] = {"source_text_sha256": _sha(row["text"]),
                                            "model_identity": "model", "complete": True}
    return row


def _build(rows, **kwargs):
    return build_paired_census(rows, code_identity="code", model_identity="model", **kwargs)


def test_vectors_and_shared_bridge_targets_never_count_as_model_formulas():
    row = _row()
    row["autoencoder_observation"]["logic_target_observation"] = {"document": {"rules": [_rule()]}}
    bundle = _build([row])
    span = bundle["paired_spans"][0]
    assert span["autoencoder"]["formal_outputs"] == []
    assert span["autoencoder"]["status"] == "unsupported_symbolic_decoder"
    assert span["comparison"]["status"] == "autoencoder_unavailable"
    assert span["comparison"]["agrees"] is None
    assert span["autoencoder"]["raw_vector"] == [0.1, 0.2]
    assert span["admitted"] is False and span["lake"]["admitted"] is False


@pytest.mark.parametrize("altered", [
    _rule(modality="Prohibition"),
    _rule(temporal={"kind": "within_duration", "quantity": 20, "unit": "days"}),
    _rule(temporal={"kind": "minimum_duration", "quantity": 21, "unit": "days"}),
    _rule(exceptions=["emergency"]),
    _rule(actor="officer"),
])
def test_real_formal_differences_generate_native_repair_packets(altered, tmp_path):
    bundle = _build([_with_ae(_row(), [altered])])
    assert bundle["paired_spans"][0]["comparison"]["status"] == "disagree"
    assert len(bundle["goals"]) == 1
    assert bundle["goals"][0]["record_kind"] == "repair_packet"
    written = write_paired_census_bundle(bundle, tmp_path)
    loaded = load_paired_census_bundle(written["manifest"]["path"])
    packet = json.loads(loaded["portable_goal_rows"][0]["packet_json"])
    assert packet["row"]["capture"]["comparison"]["status"] == "disagree"
    assert packet["row"]["capture"]["census_sha256"] == loaded["paired_spans"][0]["observation_id"]
    assert packet["allowed_edit_paths"]
    assert packet["regression_tests"]


def test_equal_complete_independent_formulas_agree_without_admission():
    bundle = _build([_with_ae(_row())])
    row = bundle["paired_spans"][0]
    assert row["comparison"]["status"] == "agree"
    assert row["comparison"]["independent"] is True
    assert row["admitted"] is False and row["formalized"] is False
    assert bundle["goals"] == []


def test_duplicate_components_and_sequence_are_preserved():
    source = _row()
    source["compiler_result"]["rules"] *= 2
    row = _build([_with_ae(source, [_rule()])])["paired_spans"][0]
    assert len(row["compiler"]["formal_outputs"]) == 2
    assert row["comparison"]["status"] == "disagree"
    assert row["comparison"]["mismatches"] == ["1"]


@pytest.mark.parametrize("failure,expected", [("partial", "partial"), ("source_binding", "incomparable"),
                                            ("syntax", "incomparable"), ("target", "incomparable")])
def test_missing_evidence_cannot_be_agreement(failure, expected):
    row = _with_ae(_row())
    if failure == "partial":
        row["compiler_result"]["compilation_complete"] = False
    elif failure == "source_binding":
        row["model_formal_output_provenance"]["source_text_sha256"] = "bad"
    elif failure == "syntax":
        row["model_formal_outputs"][0]["syntax_status"] = "not_run"
    elif failure == "target":
        row["model_formal_outputs"][0]["origin"] = "source_bridge_target"
    actual = _build([row])["paired_spans"][0]["comparison"]
    assert actual["status"] == expected
    assert actual["agrees"] is None


def test_guided_route_compares_diagnostically_without_syntax_or_independence_claim():
    row = _with_ae(_row(), origin="autoencoder_guided_compiler", independent=False, syntax="not_checked")
    result = _build([row])["paired_spans"][0]
    assert result["comparison"]["status"] == "diagnostic_agree"
    assert result["comparison"]["independent"] is False
    assert result["autoencoder"]["status"] == "guided_output"
    assert result["autoencoder"]["formal_outputs"][0]["syntax_status"] == "not_checked"
    assert result["admitted"] is False


def test_direct_modal_formula_agreement_does_not_hide_canonical_abstention():
    row = _row()
    row["compiler_result"].update(rules=[], compiler_status="abstain", reason="no_parser_elements", compilation_complete=False)
    row["direct_formal_outputs"] = [_formal(_rule(), "deterministic_codec", independent=False, syntax="not_checked")]
    row["direct_formal_output_provenance"] = {"source_text_sha256": _sha(row["text"]), "complete": True}
    row = _with_ae(row, [_rule()], origin="autoencoder_guided_compiler", independent=False, syntax="not_checked")
    bundle = _build([row])
    result = bundle["paired_spans"][0]
    assert result["comparison"]["status"] == "diagnostic_agree"
    assert result["compiler"]["canonical_complete"] is False
    assert result["compiler"]["canonical_formal_outputs"] == []
    assert bundle["goals"][0]["record_kind"] == "repair_packet"


def test_missing_both_outputs_produces_unavailable_and_source_bound_repair():
    row = _row()
    row["compiler_result"].update(rules=[], compiler_status="abstain", compilation_complete=False, reason="no_parser_elements")
    bundle = _build([row])
    assert bundle["paired_spans"][0]["comparison"]["status"] == "both_unavailable"
    assert {goal["record_kind"] for goal in bundle["goals"]} == {"capability_gap", "repair_packet"}


def test_capability_gap_identity_deduplicates_per_model_across_batches():
    first = _build([_row("1"), _row("2")])
    second = _build([_row("3")])
    assert len(first["goals"]) == len(second["goals"]) == 1
    assert first["goals"][0]["goal_id"] == second["goals"][0]["goal_id"]
    assert first["goals"][0]["source_span_ids"] == ["1", "2"]


def test_complete_receipt_archived_once_with_target_and_component_pointers(tmp_path):
    row = _row()
    target = {"document": {"large": "x" * 100000}}
    row["autoencoder_observation"]["logic_target_observation"] = target
    row["compiler_result"]["components"] = [{"rules": [_rule()], "source_text": row["text"]}]
    receipt = {"rows": [{"source_span_id": row["source_span_id"], "text": row["text"],
                          "compiler": row["compiler_result"], **row["autoencoder_observation"]}],
               "raw_evaluation": {"retained_metric": 0.123}}
    bundle = _build([row], original_receipt=receipt)
    assert len(bundle["artifacts"]) == 1
    span = bundle["paired_spans"][0]
    assert span["source_target_artifact_sha256"] == span["compiler"]["components_artifact_sha256"]
    assert span["source_target_artifact_pointer"] == "/rows/0/logic_target_observation"
    written = write_paired_census_bundle(bundle, tmp_path)
    loaded = load_paired_census_bundle(written["manifest"]["path"])
    assert loaded["original_receipt"] == receipt
    assert loaded["manifest"]["tables"]["paired_spans"]["row_count"] == 1


def test_empty_tables_have_same_arrow_schema_and_no_synthetic_rows(tmp_path):
    bundle = _build([])
    written = write_paired_census_bundle(bundle, tmp_path)
    for name, schema in arrow_schemas().items():
        table = pq.read_table(written[name]["path"])
        assert table.schema == schema
        assert table.num_rows == 0
    loaded = load_paired_census_bundle(written["manifest"]["path"])
    assert loaded["paired_spans"] == loaded["goals"] == loaded["artifacts"] == []


def test_corrupt_published_table_is_rejected(tmp_path):
    written = write_paired_census_bundle(_build([_row()]), tmp_path)
    with open(written["paired_spans"]["path"], "ab") as handle:
        handle.write(b"corrupt")
    with pytest.raises(PairedCensusError, match="differs"):
        load_paired_census_bundle(written["manifest"]["path"])


def test_artifact_decompression_bound_and_hash_are_enforced():
    row = _row()
    row["autoencoder_observation"]["logic_target_observation"] = {"document": {"blob": "x" * 10000}}
    artifact = _build([row])["artifacts"][0]
    with pytest.raises(PairedCensusError, match="bound"):
        decode_artifact(artifact, max_bytes=20)
    corrupted = {**artifact, "artifact_sha256": "0" * 64}
    with pytest.raises(PairedCensusError, match="hash differs"):
        decode_artifact(corrupted)


def test_source_row_bounds_duplicates_nonfinite_and_constitution():
    with pytest.raises(PairedCensusError, match="row count"):
        _build([_row("1"), _row("2")], max_rows=1)
    with pytest.raises(PairedCensusError, match="duplicate source"):
        _build([_row(), _row()])
    with pytest.raises(PairedCensusError, match="bytes"):
        _build([_row()], max_bytes=100)
    bad = _row()
    bad["autoencoder_observation"]["raw_decoder"]["embedding"] = [float("nan")]
    with pytest.raises(PairedCensusError, match="finite"):
        _build([bad])
    constitution = _row()
    constitution["legal_id"] = "us-constitution:article1"
    result = _build([constitution])["paired_spans"][0]
    assert result["compiler"]["roundtrip_ok"] is False
    assert result["admitted"] is False and result["formalized"] is False


def test_field_order_is_lossless_but_rule_fields_are_not_discarded():
    rule = _rule()
    row = _with_ae(_row(), [dict(reversed(list(rule.items())))])
    assert _build([row])["paired_spans"][0]["comparison"]["status"] == "agree"
    changed = deepcopy(row)
    changed["model_formal_outputs"][0]["payload"]["new_constraint"] = "only when authorized"
    assert _build([changed])["paired_spans"][0]["comparison"]["status"] == "disagree"


def test_repo_layout_loader_returns_verified_paths_and_manifest_hash(tmp_path):
    written = write_paired_census_bundle(_build([_with_ae(_row(), [_rule(modality="Prohibition")])]), tmp_path / "local")
    stage = tmp_path / "repo"
    for name in ("paired_spans", "goals", "artifacts", "manifest"):
        target = stage / written[name]["path_in_repo"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(written[name]["path"], target)
    manifest_path = stage / written["manifest"]["path_in_repo"]
    loaded = load_paired_census_bundle(manifest_path)
    assert loaded["manifest_sha256"] == written["manifest"]["sha256"]
    assert Path(loaded["table_paths"]["goals"]) == stage / written["goals"]["path_in_repo"]
    assert len(loaded["portable_goal_rows"]) == 1


def test_original_receipt_must_cover_every_paired_source():
    row = _row()
    with pytest.raises(PairedCensusError, match="missing observed span"):
        _build([row], original_receipt={"rows": []})
    with pytest.raises(PairedCensusError, match="source differs"):
        _build([row], original_receipt={"rows": [{"source_span_id": row["source_span_id"], "text": "another source"}]})


def test_modal_checkpoint_binding_matches_exact_archived_checkpoint(tmp_path):
    row = _with_ae(_row(), origin="autoencoder_guided_compiler", independent=False, syntax="not_checked")
    checkpoint = {"sha256": "f" * 64, "bytes": 123}
    row["model_formal_output_provenance"]["model_identity"] = checkpoint
    receipt = {"checkpoint": checkpoint, "rows": [{"source_span_id": row["source_span_id"], "text": row["text"]}]}
    bundle = build_paired_census([row], original_receipt=receipt, code_identity="code", model_identity="legacy-mock-diagnostic:sha256:" + "f" * 64)
    assert bundle["paired_spans"][0]["comparison"]["status"] == "diagnostic_agree"
    row["model_formal_output_provenance"]["model_identity"] = {**checkpoint, "bytes": 456}
    bundle = build_paired_census([row], original_receipt=receipt, code_identity="code", model_identity="legacy-mock-diagnostic:sha256:" + "f" * 64)
    assert bundle["paired_spans"][0]["comparison"]["status"] == "incomparable"


def test_distinct_batch_closures_do_not_share_empty_table_files(tmp_path):
    first = write_paired_census_bundle(_build([_with_ae(_row("first"))]), tmp_path)
    second = write_paired_census_bundle(_build([_with_ae(_row("second"))]), tmp_path)
    assert first["goals"]["sha256"] == second["goals"]["sha256"]
    assert first["artifacts"]["sha256"] == second["artifacts"]["sha256"]
    assert first["goals"]["path"] != second["goals"]["path"]
    assert first["artifacts"]["path"] != second["artifacts"]["path"]
    for kind in ("paired_spans", "goals", "artifacts", "manifest"):
        Path(first[kind]["path"]).unlink()
    assert load_paired_census_bundle(second["manifest"]["path"])["paired_spans"][0]["source"]["span_id"] == "second"


def _empty_guided(row, *, complete=True):
    row["model_formal_outputs"] = []
    row["model_formal_output_provenance"] = {"source_text_sha256": _sha(row["text"]),
        "model_identity": "model", "complete": complete, "origin": "autoencoder_guided_compiler"}
    return row


def test_captured_empty_guided_route_is_not_a_missing_decoder_capability():
    row = _empty_guided(_row())
    row["direct_formal_outputs"] = []
    row["direct_formal_output_provenance"] = {"source_text_sha256": _sha(row["text"]), "complete": True}
    bundle = _build([row])
    observation = bundle["paired_spans"][0]
    assert observation["autoencoder"]["status"] == "guided_no_formulas"
    assert observation["comparison"]["status"] == "both_unavailable"
    assert observation["comparison"]["agrees"] is None
    assert not bundle["goals"]


def test_empty_guided_but_present_direct_formulas_get_source_repair_not_capability(tmp_path):
    row = _empty_guided(_row())
    bundle = _build([row])
    assert bundle["paired_spans"][0]["comparison"]["status"] == "autoencoder_unavailable"
    assert {goal["record_kind"] for goal in bundle["goals"]} == {"repair_packet"}
    written = write_paired_census_bundle(bundle, tmp_path)
    loaded = load_paired_census_bundle(written["manifest"]["path"])
    packet = json.loads(loaded["portable_goal_rows"][0]["packet_json"])
    assert packet["row"]["reason"] == "strict_roundtrip_failed"
    assert loaded["manifest"]["exporter_sha256"]


def test_incomplete_or_unbound_empty_guided_route_is_explicitly_unavailable():
    for complete, source_hash in ((False, None), (True, "wrong_source")):
        row = _empty_guided(_row(), complete=complete)
        if source_hash:
            row["model_formal_output_provenance"]["source_text_sha256"] = source_hash
        bundle = _build([row])
        assert bundle["paired_spans"][0]["autoencoder"]["status"] == "guided_unavailable"
        assert all(goal["record_kind"] != "capability_gap" for goal in bundle["goals"])


def _canonical_rule(**extra):
    return {"modality": "O", "actor": "agency", "action": "retain", "object": "the record",
            "conditions": [], "exceptions": [], "temporal": ["within 20 days"], **extra}


def _temporal_row(**extra):
    core = _canonical_rule(**extra)
    compiler = {**core, "temporal_records": [{"temporal_kind": "within_duration", "quantity": 20, "value": "20 days"}]}
    return _with_ae(_row(rule=compiler), [core])


def test_redundant_temporal_metadata_has_separate_raw_and_core_equality(tmp_path):
    original = _temporal_row()
    bundle = _build([original])
    span = bundle["paired_spans"][0]
    assert span["comparison"]["status"] == "disagree"
    assert span["comparison"]["raw_agrees"] is False
    assert span["comparison"]["canonical_core_agrees"] is True
    assert span["comparison"]["difference_kind"] == "validated_temporal_metadata_only"
    assert json.loads(span["compiler"]["formal_outputs"][0]["payload_json"]) == original["compiler_result"]["rules"][0]
    assert bundle["goals"] == []
    files = write_paired_census_bundle(bundle, tmp_path)
    assert load_paired_census_bundle(files["manifest"]["path"])["paired_spans"] == bundle["paired_spans"]


@pytest.mark.parametrize("mutation", ["quantity", "kind", "unit", "unknown", "anchor", "reversed", "empty"])
def test_temporal_metadata_is_not_discarded_without_exact_redundancy(mutation):
    row = _temporal_row()
    rule = row["compiler_result"]["rules"][0]
    record = rule["temporal_records"][0]
    if mutation == "quantity":
        record["quantity"] = 21
    elif mutation == "kind":
        record["temporal_kind"] = "minimum_duration"
    elif mutation == "unit":
        record["value"] = "20 hours"
    elif mutation in {"unknown", "anchor"}:
        record[mutation] = "receipt"
    elif mutation == "reversed":
        rule["temporal"] = ["within 10 days", "within 20 days"]
        row["model_formal_outputs"][0]["payload"]["temporal"] = list(rule["temporal"])
        rule["temporal_records"].append({"temporal_kind": "within_duration", "quantity": 10, "value": "10 days"})
    else:
        rule["temporal_records"] = []
    bundle = _build([row])
    assert bundle["paired_spans"][0]["comparison"]["canonical_core_agrees"] is False
    assert bundle["goals"][0]["record_kind"] == "repair_packet"


def test_minimum_duration_kind_is_only_redundant_when_already_explicit():
    for atom, obj, expected in (("at least 20 days", "record", True),
                               ("20 days", "record for at least 20 days", True),
                               ("20 days", "record", False)):
        row = _temporal_row(temporal=[atom], object=obj)
        row["compiler_result"]["rules"][0]["temporal_records"][0]["temporal_kind"] = "minimum_duration"
        assert _build([row])["paired_spans"][0]["comparison"]["canonical_core_agrees"] is expected


@pytest.mark.parametrize("changed", [
    {"exceptions": ["emergency"]}, {"conditions": ["court order"]}, {"actor": "officer"},
    {"modality": "F"}, {"temporal": ["within 21 days"]}, {"unknown_facet": "retained"},
])
def test_core_comparison_preserves_all_changed_facets_and_unknown_fields(changed):
    row = _temporal_row()
    row["model_formal_outputs"][0]["payload"].update(changed)
    bundle = _build([row])
    assert bundle["paired_spans"][0]["comparison"]["canonical_core_agrees"] is False
    assert bundle["goals"][0]["record_kind"] == "repair_packet"


@pytest.fixture(scope="module")
def actual_formula_runtime():
    torch = pytest.importorskip("torch")
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_runtime_registry import open_runtime
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    runtime = open_runtime("legal_ir", "source_conditioned_formula_v1")
    examples = [{"id": "train", "source_text": "The agency shall retain the record within 20 days.",
                 "canonical_ir": {"rules": [_canonical_rule()]}}]
    try:
        runtime.train(examples, validation_samples=[], epochs=20, max_seconds=30,
                      hidden_size=8, embedding_dim=8, batch_size=1, learning_rate=0.02)
        yield runtime, examples[0]["source_text"]
    finally:
        torch.set_num_threads(previous)


def test_real_runtime_capture_compares_compiler_and_preserves_native_receipt(actual_formula_runtime, tmp_path, monkeypatch):
    runtime, text = actual_formula_runtime
    from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_learning, legal_formula_codec
    compiler = compile_span(AutoformalSession(), text, "actual")
    before = runtime.describe()["checkpoint_sha256"]
    def forbidden(*args, **kwargs):
        raise AssertionError("capture attempted teacher encoding or training")
    monkeypatch.setattr(legal_formula_codec, "encode_target", forbidden)
    monkeypatch.setattr(legal_formula_learning, "train_decoder", forbidden)
    capture = capture_learned_formula_observations(runtime, [{"source_span_id": "actual", "text": text}])[0]
    decoded = validate_learned_formula_observation(capture, text, source_span_id="actual", expected_checkpoint_sha256=before)
    assert decoded["canonical_ir"] == {"rules": [_canonical_rule()]}
    assert runtime.describe()["checkpoint_sha256"] == before
    assert decoded["target_access"] is decoded["teacher_forcing"] is False
    observation = {"source_span_id": "actual", "text": text, "legal_id": "authored:actual",
                   "compiler_result": compiler, "learned_formula_observation": capture}
    bundle = build_paired_census([observation], code_identity="test", model_identity=capture["model_identity"])
    span = bundle["paired_spans"][0]
    assert span["comparison"]["independent"] is True
    assert span["compiler"]["canonical_complete"] is True
    assert span["comparison"]["canonical_core_agrees"] is True
    assert span["autoencoder"]["status"] == "learned_decoded"
    assert span["autoencoder"]["formal_outputs"][0]["origin"] == "learned_source_conditioned_formula_decoder"
    assert span["autoencoder"]["formal_outputs"][0]["family"] == "deontic"
    assert json.loads(span["autoencoder"]["formal_outputs"][0]["payload_json"]) == decoded["formal_outputs"][0]["payload"]
    assert not span["admitted"] and not span["formalized"] and not span["lake"]["admitted"]
    files = write_paired_census_bundle(bundle, tmp_path)
    loaded = load_paired_census_bundle(files["manifest"]["path"])
    artifact = next(row for row in loaded["artifacts"] if row["kind"] == "learned_formula_observation")
    assert json.loads(decode_artifact(artifact)) == capture


@pytest.mark.parametrize("mutation", ["source", "checkpoint", "target", "authority", "payload", "unknown_ir", "forged_origin",
                                      "boolean_count", "margin", "detail", "tokens"])
def test_forged_or_unbound_learned_receipts_fail_closed(actual_formula_runtime, mutation):
    runtime, text = actual_formula_runtime
    capture = capture_learned_formula_observations(runtime, [{"source_span_id": "actual", "text": text}])[0]
    if mutation == "source":
        capture["source_text_sha256"] = "0" * 64
    elif mutation == "checkpoint":
        capture["inference"]["checkpoint_sha256"] = "0" * 64
    elif mutation == "target":
        capture["inference"]["rows"][0]["target_access"] = True
    elif mutation == "authority":
        capture["inference"]["admitted"] = True
    elif mutation == "payload":
        capture["inference"]["rows"][0]["formal_outputs"][0]["payload"]["exceptions"] = ["emergency"]
    elif mutation == "unknown_ir":
        capture["inference"]["rows"][0]["canonical_ir"]["rules"][0]["unknown"] = "semantic"
    elif mutation == "forged_origin":
        capture["inference"]["rows"][0]["formal_outputs"][0]["origin"] = "autoencoder_guided_compiler"
    elif mutation == "boolean_count":
        capture["inference"]["decoded_count"] = True
    elif mutation == "margin":
        capture["inference"]["rows"][0]["minimum_decision_logit_margin"] = {}
    elif mutation == "detail":
        capture["inference"]["rows"][0]["detail"] = {}
    else:
        capture["inference"]["rows"][0]["generated_token_ids"] = [1, True, 2]
    # Rehashing a malformed payload must not bypass the contract validator.
    capture["inference_sha256"] = _sha(json.dumps(capture["inference"], sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    with pytest.raises(ValueError):
        validate_learned_formula_observation(capture, text, source_span_id="actual")


def test_abstention_is_recorded_without_inventing_decoder_capability_gap(actual_formula_runtime):
    runtime, _ = actual_formula_runtime
    text = "A spacecraft shall orbit Mars."
    capture = capture_learned_formula_observations(runtime, [{"source_span_id": "unknown", "text": text}])[0]
    observation = {"source_span_id": "unknown", "text": text, "learned_formula_observation": capture,
                   "compiler_result": {"rules": [], "compilation_complete": True}}
    bundle = build_paired_census([observation], model_identity=capture["model_identity"])
    assert bundle["paired_spans"][0]["autoencoder"]["status"] == "learned_abstained"
    assert bundle["paired_spans"][0]["comparison"]["agrees"] is None
    assert not bundle["goals"]


def test_capture_rejects_fake_runtime_and_target_bearing_input(actual_formula_runtime):
    runtime, text = actual_formula_runtime
    with pytest.raises(ValueError, match="installed learned formula runtime"):
        capture_learned_formula_observations(object(), [{"source_span_id": "1", "text": text}])
    with pytest.raises(ValueError, match="target-free"):
        capture_learned_formula_observations(runtime, [{"source_span_id": "1", "text": text, "canonical_ir": {}}])


@pytest.mark.parametrize("mutation", ["model", "agent", "repository", "schema"])
def test_rehashed_bundle_cannot_change_learned_producer_identity(actual_formula_runtime, tmp_path, mutation):
    runtime, text = actual_formula_runtime
    capture = capture_learned_formula_observations(runtime, [{"source_span_id": "span1", "text": text}])[0]
    original = _row(rule=_canonical_rule())
    original.update(text=text, learned_formula_observation=capture)
    bundle = build_paired_census([original], model_identity=capture["model_identity"])
    row = bundle["paired_spans"][0]
    assert not row["goal_ids"]
    if mutation == "model":
        row["provenance"]["model_identity"] = "wrong-checkpoint-producer"
    elif mutation == "agent":
        row["provenance"]["agent_id"] = "wrong-agent"
    elif mutation == "repository":
        row["repository_id"] = "wrong-repository"
    else:
        row["schema_version"] = "wrong-schema"
    row["observation_id"] = _sha(json.dumps({key: value for key, value in row.items() if key != "observation_id"},
                                           sort_keys=True, ensure_ascii=True, separators=(",", ":")))
    written = write_paired_census_bundle(bundle, tmp_path)
    with pytest.raises(PairedCensusError, match="differs from"):
        load_paired_census_bundle(written["manifest"]["path"])


def test_abstained_capture_rejects_malformed_token_evidence(actual_formula_runtime):
    runtime, _ = actual_formula_runtime
    text = "A spacecraft shall orbit Mars."
    capture = capture_learned_formula_observations(runtime, [{"source_span_id": "unknown", "text": text}])[0]
    capture["inference"]["rows"][0]["generated_token_ids"] = {"untrusted": "prefix"}
    capture["inference_sha256"] = _sha(json.dumps(capture["inference"], sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    with pytest.raises(ValueError, match="token evidence"):
        validate_learned_formula_observation(capture, text)
