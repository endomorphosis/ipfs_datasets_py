"""Temporal coordinates, action attachment, case splits and source exclusions."""
import copy

import pytest

from scripts.ops.legal_ir import prepare_legal_temporal_curriculum as corpus


@pytest.fixture(scope="module")
def panels():
    return corpus.make_panels()


def test_exact_split_counts_and_six_variants_per_case(panels):
    rows, ledger = panels
    assert {s: len(v) for s, v in rows.items()} == {"train": 600, "tuning": 120, "challenge": 180}
    assert {s: len({a["case_group"] for a in ledger if a["split"] == s}) for s in rows} == {"train": 100, "tuning": 20, "challenge": 30}
    corpus.validate_panels(rows, ledger)


def test_rendering_and_annotations_are_deterministic(panels):
    assert corpus.make_panels() == panels


def test_every_action_and_exception_presence_has_all_modalities(panels):
    rules = [r["canonical_ir"]["rules"][0] for r in panels[0]["train"]]
    for action in {r["action"] for r in rules}:
        assert {r["modality"] for r in rules if r["action"] == action} == {"O", "P", "F"}
    for present in (False, True):
        assert {r["modality"] for r in rules if bool(r["exceptions"]) is present} == {"O", "P", "F"}


def test_numerals_do_not_keep_the_case_index_modality_proxy():
    counts = {}
    for i in range(100):
        case = corpus.case_values("train", i)
        remainder = int(case["temporal"].split()[1]) % 3
        counts.setdefault(remainder, set()).add(case["modality"])
    assert all(modalities == {"O", "P", "F"} for modalities in counts.values())


def test_end_deadline_attaches_to_action_before_trailing_conditions_and_exceptions():
    for i in range(100):
        row, annotation = corpus.render("train", i, "deadline_end")
        spans = row["facet_spans"]
        assert annotation["placement"] == "after_action_object"
        assert spans["temporal"][0] >= spans["object"][1]
        for field in ("conditions", "exceptions"):
            if spans[field] and spans[field][0] > spans["object"][1]:
                assert spans["temporal"][1] <= spans[field][0]


@pytest.mark.parametrize("variant", ["applicability_front", "applicability_end"])
def test_temporal_applicability_remains_one_condition_not_a_deadline(variant):
    row, annotation = corpus.render("tuning", 3, variant)
    rule = row["canonical_ir"]["rules"][0]
    assert rule["temporal"] == [] and row["facet_spans"]["temporal"] is None
    assert len(rule["conditions"]) == 1 and "within " in rule["conditions"][0]
    assert row["source_text"][slice(*row["facet_spans"]["conditions"])] == rule["conditions"][0]
    assert annotation["role"] == "temporal_applicability_condition"


def test_absent_deadline_is_explicitly_unspecified():
    row, annotation = corpus.render("tuning", 7, "deadline_absent")
    assert row["canonical_ir"]["rules"][0]["temporal"] == []
    assert row["facet_spans"]["temporal"] is None and annotation["role"] == "absent"


def test_front_and_interleaved_deadline_positions():
    front, _ = corpus.render("train", 2, "deadline_front")
    middle, _ = corpus.render("train", 2, "deadline_interleaved")
    assert front["facet_spans"]["temporal"][1] <= front["facet_spans"]["actor"][0]
    assert middle["facet_spans"]["actor"][1] <= middle["facet_spans"]["temporal"][0]
    assert middle["facet_spans"]["temporal"][1] <= middle["trigger_span"][0]


def test_case_modality_and_action_are_invariant_across_variants():
    rows = [corpus.render("train", 14, v)[0] for v in corpus.VARIANTS]
    core = [{k: r["canonical_ir"]["rules"][0][k] for k in ("actor", "action", "object", "modality", "exceptions")} for r in rows]
    assert all(x == core[0] for x in core)


@pytest.mark.parametrize("change", ["group", "variant", "coordinate", "hash"])
def test_annotation_or_case_group_corruption_rejected(panels, change):
    rows, ledger = copy.deepcopy(panels)
    if change == "group":
        next(a for a in ledger if a["split"] == "challenge")["case_group"] = ledger[0]["case_group"]
    elif change == "variant":
        ledger[0]["variant"] = "deadline_end"
    elif change == "coordinate":
        ledger[0]["facet_spans"] = {**ledger[0]["facet_spans"], "actor": [0, 1]}
    else:
        ledger[0]["source_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        corpus.validate_panels(rows, ledger)


def test_source_exclusions_cover_exact_and_normalized_duplicates(panels):
    rows = panels[0]
    text = rows["train"][0]["source_text"]
    with pytest.raises(ValueError, match="overlaps"):
        corpus.verify_new_source_disjointness(rows, {text})
    with pytest.raises(ValueError, match="overlaps"):
        corpus.verify_new_source_disjointness(rows, {text.upper().replace(" ", "   ")})


def test_unsupported_nested_temporal_variant_is_rejected():
    with pytest.raises(ValueError, match="unsupported temporal variant"):
        corpus.render("train", 0, "nested_deadline_scope")
