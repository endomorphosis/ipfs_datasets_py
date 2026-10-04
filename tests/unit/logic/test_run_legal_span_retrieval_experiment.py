"""Test reference isolation and ordered context interventions in the runner."""
import hashlib

import pytest

from scripts.ops.legal_ir import run_legal_span_retrieval_experiment as runner


def example(index):
    text = f"Office {index} shall retain file {index}."
    return {"id": str(index), "source_text": text,
        "source_sha256": hashlib.sha256(text.encode()).hexdigest(), "family_group": f"family-{index}",
        "canonical_ir": {"rules": [{"modality": "O", "actor": f"Office {index}", "action": "retain",
            "object": f"file {index}", "conditions": [], "exceptions": [], "temporal": []}]},
        "embedding": [float(index)] * 384, "formal_embedding": [float(index + 1)] * 384,
        "spans": "reference-only annotations"}


def context(row, value):
    return {"id": row["id"], "source_sha256": row["source_sha256"], "context": [float(value)] * 384,
            "retrieved_ids": ["train-neighbor"], "scores": [1.]}


class SpyDecoder:
    def __init__(self):
        self.calls = []

    def decode_formal_logic(self, texts, latents, *, latent_ablation):
        self.calls.append((texts, latents, latent_ablation))
        assert all(type(text) is str for text in texts)
        assert all(type(vector) is list and len(vector) == 384 for vector in latents)
        return {"rows": [{"source_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "target_access": False, "teacher_forcing": False, "status": "abstained", "canonical_ir": None}
            for text in texts], "target_access": False, "teacher_forcing": False}


def test_only_query_source_vectors_cross_retrieval_boundary():
    rows = runner.queries([example(1)])
    assert set(rows[0]) == {"id", "source_text", "embedding", "family_group"}


def test_only_source_and_context_cross_decoder_boundary():
    row = example(1)
    decoder = SpyDecoder()
    result = runner.generate(decoder, [row], [context(row, 3)])
    assert decoder.calls == [([row["source_text"]], [[3.] * 384], "none")]
    assert result["generation_inputs_contained_references"] is False


def test_training_targets_stay_in_training_and_metadata_is_removed():
    row = example(1)
    actual = runner.fitting_rows([row], [context(row, 3)])
    assert set(actual[0]) == {"id", "source_text", "canonical_ir", "latent"}
    assert actual[0]["canonical_ir"] == row["canonical_ir"]


def test_rotation_is_global_across_batch_boundary():
    rows = [example(i) for i in range(130)]
    decoder = SpyDecoder()
    runner.generate(decoder, rows, [context(row, i) for i, row in enumerate(rows)], "rotated_context")
    values = [vector[0] for _, vectors, _ in decoder.calls for vector in vectors]
    assert values == list(range(1, 130)) + [0]
    assert [text for texts, _, _ in decoder.calls for text in texts] == [row["source_text"] for row in rows]


@pytest.mark.parametrize("control,expected,ablation", [("zero_context", 0., "none"),
                                                      ("disabled_context", 3., "disabled")])
def test_context_intervention(control, expected, ablation):
    row = example(1)
    decoder = SpyDecoder()
    runner.generate(decoder, [row], [context(row, 3)], control)
    assert decoder.calls[0][1] == [[expected] * 384]
    assert decoder.calls[0][2] == ablation


@pytest.mark.parametrize("field,value", [("id", "wrong"), ("source_sha256", "0" * 64)])
def test_retrieval_identity_drift_rejected(field, value):
    row = example(1)
    retrieved = context(row, 3)
    retrieved[field] = value
    with pytest.raises(ValueError, match="identity"):
        runner.generate(SpyDecoder(), [row], [retrieved])


def test_inference_target_access_rejected():
    class Invalid(SpyDecoder):
        def decode_formal_logic(self, *args, **kwargs):
            result = super().decode_formal_logic(*args, **kwargs)
            result["target_access"] = True
            return result
    row = example(1)
    with pytest.raises(ValueError, match="query targets"):
        runner.generate(Invalid(), [row], [context(row, 3)])


def test_retrieval_metric_is_structural_not_exact_pair_recall():
    row, neighbor = example(1), example(2)
    record = context(row, 3)
    record["retrieved_ids"] = [neighbor["id"]]
    result = runner.retrieval_metrics([row], [row], [record], [neighbor])
    assert result["top1_profile_match"] == 1
    assert row["canonical_ir"] != neighbor["canonical_ir"]
    assert "not semantic equivalence" in result["metric_scope"]


def test_missing_retrieval_metric_rows_rejected():
    row = example(1)
    with pytest.raises(ValueError, match="coverage"):
        runner.retrieval_metrics([row], [row], [], [example(2)])
