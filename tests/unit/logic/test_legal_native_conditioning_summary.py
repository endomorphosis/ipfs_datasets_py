from copy import deepcopy
import hashlib
import json
import re
import pytest
from scripts.ops.legal_ir import summarize_legal_native_conditioning_experiment as summary


def prediction_without_object():
    text = "Agency shall act."
    source = {"id": "case", "source_text": text, "family_group": "test"}
    tokens = [{"text": m.group(), "start": m.start(), "end": m.end()} for m in re.finditer(r"\w+|[^\w\s]", text)]
    facets = {}
    for facet in summary.SPAN_FIELDS:
        token = {"actor": 0, "action": 2}.get(facet)
        facets[facet] = {"present": token is not None, "token_start": token, "token_end_inclusive": token,
            "char_start": tokens[token]["start"] if token is not None else None,
            "char_end": tokens[token]["end"] if token is not None else None,
            "text": tokens[token]["text"] if token is not None else None}
    rule = {"modality": "O", "actor": "Agency", "action": "act", "object": "",
            "conditions": [], "exceptions": [], "temporal": []}
    ir = {"rules": [rule]}
    prediction = {"source_sha256": hashlib.sha256(text.encode()).hexdigest(), "target_access": False,
        "teacher_forcing": False, "status": "decoded", "canonical_ir": ir,
        "span_diagnostics": {"tokens": tokens, "facets": facets},
        "formal_outputs": [{"family": "deontic", "payload": rule}], "formula_text": json.dumps(ir)}
    return source, prediction


def test_optional_empty_object_is_valid_copy_and_evaluation():
    source, prediction = prediction_without_object()
    assert summary.assert_source_copy(prediction, source) == 2
    known = {f: set() for f in summary.FIELDS}
    result = summary.evaluate([prediction], [source], {"case": prediction["canonical_ir"]}, known)
    assert result["exact"] == 1 and result["facet_correct"]["object"] == 1


@pytest.mark.parametrize("mutation", ["invented_object", "false_present", "missing_actor", "source"])
def test_optional_object_does_not_relax_source_binding(mutation):
    source, prediction = prediction_without_object()
    if mutation == "invented_object":
        prediction["canonical_ir"]["rules"][0]["object"] = "records"
    elif mutation == "false_present":
        prediction["span_diagnostics"]["facets"]["object"]["present"] = True
    elif mutation == "missing_actor":
        prediction["canonical_ir"]["rules"][0]["actor"] = ""
    else:
        source["source_text"] += " altered"
    with pytest.raises(ValueError):
        summary.assert_source_copy(prediction, source)


def test_all_heads_parents_and_generation_panels_required():
    heads = [{"name": f"{arm}-{seed}"} for arm in summary.ARMS for seed in summary.SEEDS]
    models = heads + [{"name": f"parent_source-{seed}"} for seed in summary.SEEDS]
    freeze = {r["name"]: {} for r in models}
    assert len(summary.verify_coverage({"runs": models}, heads, freeze)) == 15
    with pytest.raises(ValueError, match="all12 selected"):
        summary.verify_coverage({"runs": models[:-1]}, heads, freeze)
    with pytest.raises(ValueError, match="unique selected"):
        summary.verify_coverage({"runs": models}, heads[:-1] + heads[:1], freeze)


def test_context_cannot_relabel_a_different_native_stage():
    vector = [1.] * 384
    source = {"id": "case", "source_sha256": "a" * 64}
    entry = {"vector": vector, "receipt": {"stage": "core384"}}
    vectors = {"case": {"stages": {"core384": entry}}}
    record = {**source, "context": vector, "context_sha256": summary.digest(vector), "native_stage_receipt": entry["receipt"]}
    summary.verify_context_records([record], [source], vectors, "core384")
    edited = deepcopy(record)
    edited["native_stage_receipt"]["stage"] = "trained384"
    with pytest.raises(ValueError, match="authentic recorded stage"):
        summary.verify_context_records([edited], [source], vectors, "core384")


def test_no_sealed_targets_without_completed_run(tmp_path, monkeypatch):
    reads = []
    monkeypatch.setattr(summary, "read", lambda path: reads.append(path))
    with pytest.raises(ValueError, match="completed summary"):
        summary.summarize(tmp_path, tmp_path / "result.json")
    assert reads == []
