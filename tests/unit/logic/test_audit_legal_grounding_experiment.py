"""Independent evidence checks reject corrupt coordinates and count abstentions."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load(name):
    path = ROOT / "scripts/ops/legal_ir" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load("audit_legal_grounding_experiment")
curriculum = load("prepare_legal_grounding_curriculum")


def example():
    row = curriculum.render_row("challenge", "actor_condition_insertion", 4, "P")
    source = {"id": row["id"], "source_text": row["source_text"],
              "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest()}
    text = row["source_text"]
    tokens = [{"text": m.group(), "start": m.start(), "end": m.end()} for m in re.finditer(r"\w+|[^\w\s]", text)]
    starts, ends = {t["start"]: i for i, t in enumerate(tokens)}, {t["end"]: i for i, t in enumerate(tokens)}
    facets = {}
    for field, span in row["facet_spans"].items():
        facets[field] = {"present": span is not None, "token_start": starts[span[0]] if span else None,
            "token_end_inclusive": ends[span[1]] if span else None,
            "char_start": span[0] if span else None, "char_end": span[1] if span else None,
            "text": text[slice(*span)] if span else None}
    pred = {"source_sha256": source["source_sha256"], "target_access": False, "teacher_forcing": False,
        "status": "decoded", "canonical_ir": row["canonical_ir"], "formula_text": json.dumps(row["canonical_ir"]),
        "formal_outputs": [{"family": "deontic", "payload": row["canonical_ir"]["rules"][0]}],
        "span_diagnostics": {"tokens": tokens, "facets": facets},
        "grounding_diagnostics": {"trigger": {"char_start": row["trigger_span"][0], "char_end": row["trigger_span"][1]}}}
    return row, source, pred


def test_independent_exact_coordinates_and_metrics():
    row, source, pred = example()
    audit.verify_coordinate_targets([row], curriculum.TRIGGER_MEANINGS)
    measured = audit.independent_metrics({"rows": [pred]}, [source], [row])
    assert measured["count"] == measured["decoded"] == measured["exact"] == 1
    assert measured["decoded_facet_coordinate_exact"] == {f: 1 for f in audit.FIELDS}


def test_abstention_retained_and_partial_diagnostics_separate():
    row, source, pred = example()
    pred.update(status="abstained", canonical_ir=None, formal_outputs=[])
    measured = audit.independent_metrics({"rows": [pred]}, [source], [row])
    assert measured["count"] == measured["abstained"] == 1
    assert measured["decoded"] == measured["exact"] == 0
    assert measured["decoded_facet_coordinate_exact"] == {f: 0 for f in audit.FIELDS}
    assert measured["abstained_with_correct_actor_span"] == 1


@pytest.mark.parametrize("mutation", ["source", "coordinate", "formula", "teacher_forcing"])
def test_corrupt_prediction_rejected(mutation):
    row, source, pred = example()
    if mutation == "source":
        pred["source_sha256"] = "f" * 64
    elif mutation == "coordinate":
        pred["span_diagnostics"]["facets"]["actor"]["char_end"] -= 1
    elif mutation == "formula":
        pred["formula_text"] = "{}"
    else:
        pred["teacher_forcing"] = True
    with pytest.raises(ValueError):
        audit.verify_prediction(pred, source)


def test_gold_coordinate_corruption_rejected():
    row, _, _ = example()
    row["facet_spans"]["actor"][0] += 1
    with pytest.raises(ValueError, match="token aligned"):
        audit.verify_coordinate_targets([row], curriculum.TRIGGER_MEANINGS)


def test_gold_trigger_semantics_corruption_rejected():
    row, _, _ = example()
    row["canonical_ir"]["rules"][0]["modality"] = "O"
    with pytest.raises(ValueError, match="coordinate binding"):
        audit.verify_coordinate_targets([row], curriculum.TRIGGER_MEANINGS)


def test_tensor_changes_keep_exact_element_and_norm_evidence():
    result = audit.tensor_difference([[1., 2.], [3., 4.]], [[1., 5.], [7., 4.]])
    assert result == {"elements": 4, "changed_elements": 2, "delta_l2": 5.0}
    with pytest.raises(ValueError, match="counts differ"):
        audit.tensor_difference([1.], [1., 2.])


def test_construction_errors_retain_wrong_and_abstained_rows():
    rows = [{"id": "a", "exact": False, "status": "abstained", "facet_errors": ["actor", "modality"],
             "actor_start_exact": False, "actor_end_exact": True}]
    groups = audit.construction_errors(rows, {"a": "held_out"})
    assert groups["held_out"] == {"count": 1, "exact": 0, "abstained": 1,
        "actor_start_errors": 1, "actor_end_errors": 0, "facet_errors": {"actor": 1, "modality": 1}}
