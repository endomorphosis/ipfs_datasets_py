"""Cross-agent owner composition; authored fixtures establish no legal gold."""
from copy import deepcopy
from hashlib import sha256

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_scope_span_proposal as proposal
from ipfs_datasets_py.logic.legal_ir import canonical_qualifier_training_preflight as preflight
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec as word


SOURCE = "The clerk shall submit notice if ready."
AUTHORITY_FIELDS = (
    "train_eligible", "qualified", "admitted", "Lean_admitted", "formalized",
    "proof_authority", "source_semantics_verified", "training_executed",
    "model_executed", "encoder_executed", "Lake_executed", "downloads_performed",
)


def fixture(modality="O", attachment="rule", *, condition=True, split="train"):
    def span(text):
        start = SOURCE.index(text)
        return [start, start + len(text)]

    predicted = {
        "schema": proposal.PREDICTION_SCHEMA,
        "interpretation_profile": proposal.INTERPRETATION_PROFILE,
        "modality": modality,
        "spans": {"modality": span("shall"), "actor": span("clerk"),
                  "action": span("submit"), "object": span("notice"),
                  "condition": span("ready") if condition else None},
        "condition_attachment": attachment if condition else None,
    }
    result = proposal.propose_scope_from_spans(
        SOURCE, predicted, expected_source_sha256=sha256(SOURCE.encode()).hexdigest())
    declaration = result["declaration"]
    # Separate caller-authored transport premise, never derived as an admitted
    # target from predicted occurrences. P/F against "shall" remain unreviewed.
    row = {
        "id": "unreviewed-proposal", "split": split, "source_text": SOURCE,
        "context": deepcopy(declaration["input"]["context"]),
        "scope_declaration": deepcopy(declaration),
        "canonical_ir": {"rules": [{"modality": modality, "actor": "clerk",
            "action": "submit", "object": "notice", "conditions": ["ready"] if condition else [],
            "exceptions": [], "temporal": []}]},
    }
    return result, row


def transport_control():
    return {"id": "authored-control", "split": "train",
            "source_text": "The clerk must retain evidence if ready.",
            "canonical_ir": {"rules": [{"modality": "O", "actor": "clerk",
                "action": "retain", "object": "evidence", "conditions": ["ready"],
                "exceptions": [], "temporal": []}]}}


def assert_no_authority(report):
    assert all(report[field] is False for field in AUTHORITY_FIELDS)
    assert report["review"]["train_eligible"] is False
    assert report["review_to_cohort_binding_assessed"] is False
    assert report["review_replay_is_training_authority"] is False
    assert report["native_family_floor_assessed"] is False
    assert report["normalization_performed"] is False
    assert report["rows_discarded"] == 0
    for row in report["rows"]:
        assert all(row[field] is False for field in AUTHORITY_FIELDS)


@pytest.mark.parametrize("modality", ["O", "P", "F"])
@pytest.mark.parametrize("attachment,condition", [("rule", True), ("statement", True), (None, False)])
def test_occurrence_transport_cannot_supply_context_or_training_authority(monkeypatch, modality, attachment, condition):
    result, row = fixture(modality, attachment, condition=condition)
    before = deepcopy((result, row))

    def forbidden(*args, **kwargs):
        raise AssertionError("An unresolved proposal cannot fit a training vocabulary")

    monkeypatch.setattr(word, "fit_codec", forbidden)
    report = preflight.preflight_qualifier_cohort([row])
    assert (result, row) == before
    assert all(mask == 0 for mask in result["masks"].values())
    assert report["reported_row_count"] == report["cohort_row_count"] == 1
    assert report["complete_rule_count_observed"] == 1
    assert report["qualifier_value_counts_observed"] == dict(conditions=int(condition), exceptions=0, temporal=0)
    recorded = report["rows"][0]
    assert recorded["id"] == row["id"] and recorded["split"] == row["split"]
    assert "context resolution" in recorded["issues"][0]
    # Context refusal precedes scope compatibility assessment in this owner.
    assert recorded["scope_transport"] == {"supplied": False}
    assert report["word_codec_sha256"] is None
    assert report["word_supported_rows"] == report["byte_supported_rows"] == 0
    assert_no_authority(report)


@pytest.mark.parametrize("split", ["train", "tuning"])
def test_unresolved_rows_remain_counted_without_contaminating_or_shrinking_train(split):
    _, unresolved = fixture(split=split)
    rows = [transport_control(), unresolved]
    before = deepcopy(rows)
    report = preflight.preflight_qualifier_cohort(rows)
    assert rows == before
    assert [r["id"] for r in report["rows"]] == [r["id"] for r in rows]
    assert report["reported_row_count"] == report["cohort_row_count"] == 2
    assert report["complete_rule_count_observed"] == 2
    assert report["qualifier_value_counts_observed"] == dict(conditions=2, exceptions=0, temporal=0)
    assert report["rows"][1]["structure_supported"] is False
    if split == "train":
        assert report["word_codec_sha256"] is None
        assert "no failed row was discarded" in report["word_codec_error"]
        assert report["word_supported_rows"] == 0
    else:
        assert report["word_codec_sha256"] is not None
        assert report["word_supported_rows"] == 1
    assert_no_authority(report)


def test_supplied_vocabulary_cannot_admit_unresolved_occurrences():
    control = transport_control()
    codec = word.fit_codec([{key: control[key] for key in ("id", "source_text", "canonical_ir")}])
    _, row = fixture()
    report = preflight.preflight_qualifier_cohort([row], word_codec=codec)
    assert report["word_vocabulary_origin"] == "explicit_supplied_codec"
    assert report["word_codec_sha256"] is not None
    assert report["word_supported_rows"] == report["byte_supported_rows"] == 0
    assert_no_authority(report)


def test_omitting_context_cannot_rebind_existing_occurrence_declaration():
    result, row = fixture()
    original = deepcopy(result)
    del row["context"]
    report = preflight.preflight_qualifier_cohort([row])
    assert result == original
    assert report["rows"][0]["input_sha256"] != result["declaration"]["input_sha256"]
    assert report["rows"][0]["structure_supported"] is False
    assert report["rows"][0]["issues"] == ["declaration source/context input binding differs"]
    assert report["word_codec_sha256"] is None
    assert_no_authority(report)


def test_proposal_envelope_cannot_be_used_as_a_cohort_target():
    result, _ = fixture()
    before = deepcopy(result)
    report = preflight.preflight_qualifier_cohort([result])
    assert result == before
    assert report["reported_row_count"] == 1
    assert report["rows_with_unavailable_qualifier_counts"] == 1
    assert report["complete_rule_count_observed"] == 0
    assert report["word_codec_sha256"] is None
    assert_no_authority(report)


def test_no_seven_facet_target_is_inferred_from_valid_occurrences():
    result, row = fixture()
    del row["canonical_ir"]
    report = preflight.preflight_qualifier_cohort([row])
    assert report["reported_row_count"] == 1
    assert report["rows_with_unavailable_qualifier_counts"] == 1
    assert report["word_supported_rows"] == report["byte_supported_rows"] == 0
    assert report["word_codec_sha256"] is None
    assert all(mask == 0 for mask in result["masks"].values())
    assert_no_authority(report)
