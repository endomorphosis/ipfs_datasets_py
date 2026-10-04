"""Synthetic fixtures for independent source-control accounting."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[5] / "scripts/ops/autoencoder/summarize_gte_native_source_controls.py"
SPEC = importlib.util.spec_from_file_location("source_analysis_test", SCRIPT)
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def sources():
    rows = []
    for identity, value in (("b", 2.), ("a", 1.), ("c", 3.)):
        donor, native = [value] * 8, [value] * 768
        rows.append({"id": identity, "source_sha256": identity * 64,
            "generation_input": {"input_vector": donor, "input_sha256": analysis.digest(donor)},
            "native_generation_input": {"input_vector": native, "input_sha256": analysis.digest(native)}})
    return rows


@pytest.mark.parametrize("donor,width", [(True, 8), (False, 768)])
@pytest.mark.parametrize("control,expected_value", [("source", 2.), ("zero", 0.), ("cross_source", 3.)])
def test_interventions_reconstruct_source_zero_and_identity_sorted_donor(donor, width, control, expected_value):
    rows = sources(); saved = deepcopy(rows)
    vector, receipt = analysis.expected_intervention(rows, 0, control, donor=donor)
    assert vector == [expected_value] * width
    assert receipt["effective_input_sha256"] == analysis.digest(vector)
    assert receipt["receiving_id"] == "b"
    assert receipt["donor"] is None if control != "cross_source" else receipt["donor"]["id"] == "c"
    assert receipt["target_access"] is False and receipt["zero_input_is_disabled_context"] is False
    assert rows == saved


def test_cross_source_permutation_rejects_duplicate_source_hash():
    rows = sources(); rows[2]["source_sha256"] = rows[0]["source_sha256"]
    with pytest.raises(ValueError, match="repeats source"):
        analysis.expected_intervention(rows, 0, "cross_source", donor=False)


def test_first_divergence_reports_token_not_only_index():
    assert analysis.first_difference([1, 3, 2], [1, 4, 2], ["pad", "bos", "eos", "P", "O"]) == {
        "token_index_including_bos": 1, "generated_token": "P", "reference_token": "O"}
    assert analysis.first_difference([1, 2], [1, 2], ["pad", "bos", "eos"]) is None
    assert analysis.first_difference([1], [1, 2], ["pad", "bos", "eos"])["generated_token"] is None


def test_invalid_rows_remain_in_facet_denominators_and_diversity_counts():
    target = {"rules": [{field: [] if field in ("conditions", "exceptions", "temporal") else "synthetic"
                          for field in analysis.FACETS}]}
    good = {"id": "synthetic-good", "reference": {"target": target}, "first_difference": None,
        "score": {"syntax_valid": True, "exact_target_match": True, "generated_ids_sha256": "a" * 64,
                  "decoded_target_sha256": "b" * 64, "decoded_target": target,
                  "terminated": True, "truncated": False, "reason": None}}
    bad = deepcopy(good); bad["id"] = "synthetic-bad"
    bad["score"].update(syntax_valid=False, exact_target_match=False, decoded_target=None,
        decoded_target_sha256=None, generated_ids_sha256="c" * 64, reason="invalid_canonical_target")
    bad["first_difference"] = {"reference_token": "O"}
    result = analysis.panel_statistics([good, bad])
    assert result["count"] == 2 and result["syntax_valid"] == result["exact_target_match"] == 1
    assert all(count == 1 for count in result["facet_matches_over_all_rows"].values())
    assert result["unique_generated_token_sequences"] == 2
    assert result["unique_syntax_valid_targets"] == 1
    assert result["invalid_reasons"] == {"invalid_canonical_target": 1}


def test_duplicate_rows_cannot_inflate_panel_counts():
    with pytest.raises(ValueError, match="unique nonempty"):
        analysis.panel_statistics([{"id": "same"}, {"id": "same"}])
