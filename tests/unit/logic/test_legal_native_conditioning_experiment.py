from copy import deepcopy
import hashlib
import pytest
from scripts.ops.legal_ir import prepare_legal_native_conditioning_experiment as preparation
from scripts.ops.legal_ir import run_legal_native_conditioning_experiment as experiment


def corpus():
    panels = preparation.make_panels({"splits": {"train": []}})
    splits = {name: [deepcopy(panels[name][0])] for name in ("challenge", "train", "tuning")}
    splits["oov"] = []
    for name, rows in splits.items():
        for row in rows:
            row["embedding"] = [0.] * 384
            if name == "challenge":
                row.pop("canonical_ir")
                row.pop("source_spans")
    return {"splits": splits}


def verify(data):
    experiment.verify_source_inputs(data, expected_counts={"train": 1, "tuning": 1, "challenge": 1, "oov": 0})


def test_challenge_first_source_overlap_is_rejected():
    data = corpus()
    verify(data)
    for field in ("source_text", "source_sha256"):
        data["splits"]["challenge"][0][field] = data["splits"]["train"][0][field]
    with pytest.raises(ValueError, match="source overlaps"):
        verify(data)


def test_tuning_challenge_family_overlap_is_rejected():
    data = corpus()
    data["splits"]["tuning"][0]["family_group"] = data["splits"]["challenge"][0]["family_group"]
    with pytest.raises(ValueError, match="family overlaps"):
        verify(data)


@pytest.mark.parametrize("change,message", [("target", "target fields"), ("nan", "finite native384"),
                                            ("source", "source hash")])
def test_rejects_evaluation_leakage_and_invalid_source_vectors(change, message):
    data = corpus()
    row = data["splits"]["challenge"][0]
    if change == "target":
        row["canonical_ir"] = {}
    elif change == "nan":
        row["embedding"][0] = float("nan")
    else:
        row["source_text"] += " changed"
    with pytest.raises(ValueError, match=message):
        verify(data)


def test_native_donor_receipts_are_not_attributed_to_receivers():
    queries, contexts = [], []
    for index in range(4):
        text = f"source {index}"
        source_sha = hashlib.sha256(text.encode()).hexdigest()
        vector = [float(index + 1)] * 384
        queries.append({"id": str(index), "source_text": text, "embedding": vector,
                        "family_group": f"family-{index // 2}"})
        contexts.append({"id": str(index), "source_sha256": source_sha, "context": vector,
                         "context_sha256": experiment.digest(vector),
                         "native_stage_receipt": {"id": str(index), "source_sha256": source_sha}})
    before = deepcopy(contexts)
    swapped = experiment.native_cross_family_contexts(queries, contexts)
    assert contexts == before
    assert {r["donor_query_id"] for r in swapped} == {r["id"] for r in queries}
    for original, row in zip(contexts, swapped):
        assert row["source_sha256"] == original["source_sha256"]
        assert row["donor_family_group"] != row["query_family_group"]
        assert "native_stage_receipt" not in row
        assert row["donor_native_stage_receipt"]["id"] == row["donor_query_id"]
        assert row["donor_native_stage_receipt"]["source_sha256"] == row["donor_source_sha256"]
        assert row["context_provenance"] == "donor_source_native_stage; receiving_source_remains_original"
