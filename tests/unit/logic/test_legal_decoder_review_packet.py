"""Source-bound review packets retain uncertainty and exact prediction lineage."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/build_legal_decoder_review_packet.py"
SPEC = importlib.util.spec_from_file_location("legal_decoder_review_packet", SCRIPT)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def fixture_files(tmp_path, texts=("L.", "L.", "The officer shall file if notified.")):
    entries, rows = [], []
    for index, text in enumerate(texts):
        entries.append({"source_span_id": f"span-{index}", "source_text_variants": [text],
                        "occurrences": [], "training_qualified": False, "gold_target": None,
                        "documented_span_issues": ["documented defect"] if index == 0 else []})
        rows.append({"source_sha256": builder._sha(text), "target_access": False,
                     "teacher_forcing": False, "latent_input_enabled": False,
                     "source_input_conditioned": True, "qualified": False,
                     "admitted": False, "semantic_correctness_verified": False,
                     "status": "abstained", "canonical_ir": None})
    queue = {"schema": "legal-decoder-pilot-review-queue/v1", "revision": "a" * 40,
             "repository": "owner/repo", "scope": "small sample", "entries": entries}
    transfer = {"generation": {"generation_inputs_contained_references": False,
                               "rows": rows, "reports": [{"checkpoint_sha256": "b" * 64, "rows": rows}]}}
    queue_path, transfer_path = tmp_path / "queue.json", tmp_path / "transfer.json"
    queue_path.write_text(json.dumps(queue))
    transfer_path.write_text(json.dumps(transfer))
    return queue_path, transfer_path


def change_transfer(path, change):
    transfer = json.loads(path.read_text())
    change(transfer["generation"]["rows"])
    transfer["generation"]["reports"][0]["rows"] = deepcopy(transfer["generation"]["rows"])
    path.write_text(json.dumps(transfer))


def test_exact_text_dedup_preserves_contexts_multiplicity_and_all_seeds(tmp_path):
    queue, transfer = fixture_files(tmp_path)
    result = builder.build_packet(queue, {1729: transfer, 1730: transfer, 1731: transfer})
    assert result["deduplication"]["source_observations"] == 3
    assert result["deduplication"]["unique_text_groups"] == 2
    assert result["deduplication"]["contexts_merged"] is False
    fragment = result["groups"][0]
    assert fragment["source_text"] == "L."
    assert len(fragment["source_observations"]) == 2
    assert [len(seed["predictions"]) for seed in fragment["model_predictions_by_seed"]] == [2, 2, 2]
    assert all(group["review_status"] == "unreviewed" and not group["training_qualified"]
               and group["gold_target"] is None for group in result["groups"])


def test_join_uses_hash_not_row_order(tmp_path):
    queue, transfer = fixture_files(tmp_path)
    change_transfer(transfer, lambda rows: rows.reverse())
    result = builder.build_packet(queue, {1: transfer})
    for group in result["groups"]:
        for item in group["model_predictions_by_seed"][0]["predictions"]:
            assert item["prediction"]["source_sha256"] == group["source_text_sha256"]


@pytest.mark.parametrize("change", [lambda rows: rows.pop(), lambda rows: rows[0].update(source_sha256="c" * 64)])
def test_missing_or_unbound_predictions_fail(tmp_path, change):
    queue, transfer = fixture_files(tmp_path)
    change_transfer(transfer, change)
    with pytest.raises(builder.ReviewPacketError, match="coverage or multiplicity"):
        builder.build_packet(queue, {1: transfer})


@pytest.mark.parametrize("field", ["qualified", "semantic_correctness_verified", "admitted", "target_access", "teacher_forcing", "latent_input_enabled"])
def test_unreviewed_or_source_only_claims_cannot_be_bypassed(tmp_path, field):
    queue, transfer = fixture_files(tmp_path)
    change_transfer(transfer, lambda rows: rows[0].update({field: True}))
    with pytest.raises(builder.ReviewPacketError):
        builder.build_packet(queue, {1: transfer})


def test_invalid_source_offsets_are_rejected(tmp_path):
    queue, transfer = fixture_files(tmp_path)
    change_transfer(transfer, lambda rows: rows[0].update(span_diagnostics={"tokens": [{"start": 0, "end": 1, "text": "X"}]}))
    with pytest.raises(builder.ReviewPacketError, match="token offsets"):
        builder.build_packet(queue, {1: transfer})


def test_no_text_normalization_and_no_input_mutation(tmp_path):
    queue, transfer = fixture_files(tmp_path, ("L.", " L.", "L. "))
    originals = queue.read_bytes(), transfer.read_bytes()
    result = builder.build_packet(queue, {1: transfer})
    assert result["deduplication"]["unique_text_groups"] == 3
    assert originals == (queue.read_bytes(), transfer.read_bytes())


def test_triage_cues_are_grounded_and_do_not_assert_rule_count():
    text = "Definitions. The officer shall file if notified, unless exempt, within 30 days; the clerk may retain it."
    triage = builder.triage_text(text)
    assert triage["status"] == "unreviewed"
    assert triage["rule_count"] is None
    assert triage["multi_rule_assessment"] == "unresolved"
    assert "heading_or_mixed_fragment_candidate" in triage["categories"]
    assert "condition_attachment_review_needed" in triage["categories"]
    assert "exception_attachment_review_needed" in triage["categories"]
    assert "temporal_context_review_needed" in triage["categories"]
    assert all(text[cue["char_start"]:cue["char_end"]] == cue["text"] for cue in triage["evidence_spans"])


def test_submission_schema_supports_rejection_and_scoped_multi_rule_annotations():
    jsonschema = pytest.importorskip("jsonschema")
    schema = builder.review_submission_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    fields = schema["$defs"]["rule"]["properties"]
    assert {"conditions", "exceptions", "temporal", "quantifier_and_negation_scope"} <= fields.keys()
    assert "reject" in schema["$defs"]["reviewer"]["properties"]["decision"]["enum"]
    assert schema["properties"]["training_qualified"] == {"const": False}
    assert schema["properties"]["reviews"]["minItems"] == 2


def test_total_input_budget_is_enforced(tmp_path):
    queue, transfer = fixture_files(tmp_path)
    with pytest.raises(builder.ReviewPacketError, match="byte budget"):
        builder.build_packet(queue, {1: transfer}, max_bytes=queue.stat().st_size + 1)
