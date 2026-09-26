"""Hints from real learned APIs must not become symbolic truth or validation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.autoformal.learned_feedback import compact_guidance, _read_receipt, attach_guidance, SCHEMA


class Model:
    def __init__(self):
        self.distribution = {"deontic": 0.6, "temporal": 0.4}
        self.memory = False
        self.name = "sample-1"
        self.similarity = 0.3

    def introspect_sample(self, sample, **kwargs):
        assert kwargs == {"use_sample_memory": False, "top_k": 4, "include_causal_attribution": False}
        return SimpleNamespace(sample_id=self.name, sample_memory_used=self.memory,
                               cosine_similarity=self.similarity, reconstruction_loss=0.2)

    def compiler_guidance_for_sample(self, sample, **kwargs):
        assert kwargs["use_sample_memory"] is False and kwargs["include_causal_attribution"] is False
        assert kwargs["introspection"].sample_id == self.name
        return {"sample_id": self.name, "sample_memory_used": self.memory,
                "family_distribution": self.distribution,
                "decoded_embedding": [1, 2, 3],
                "legal_ir_target_view_distribution": {"not_prediction": 1},
                "feature_groups": {"compiler_contract": ["x", "y", "z", "a", "b"]}}


def test_native_guidance_is_bounded_without_vectors_or_teacher_targets():
    result = compact_guidance(Model(), SimpleNamespace(sample_id="sample-1"))
    assert result["family_distribution"] == {"deontic": 0.6, "temporal": 0.4}
    assert result["counts_as_validation"] is result["symbolic_decoder_output"] is False
    assert result["source_derived_feature_groups"] == {"compiler_contract": ["x", "y", "z", "a"]}
    assert "decoded_embedding" not in result and "not_prediction" not in json.dumps(result)


@pytest.mark.parametrize("attribute,value", [
    ("name", "wrong"), ("memory", True), ("similarity", float("nan")), ("similarity", 1.1),
    ("distribution", {}), ("distribution", {"x": 1.1}), ("distribution", {"x": 0.5}),
    ("distribution", {"x": True}), ("distribution", {"x": float("inf")}),
])
def test_invalid_or_leaky_guidance_is_rejected(attribute, value):
    model = Model()
    setattr(model, attribute, value)
    with pytest.raises(ValueError):
        compact_guidance(model, SimpleNamespace(sample_id="sample-1"))


def test_receipt_requires_checked_canonical_regular_bytes(tmp_path):
    path = tmp_path / "worker.json"
    raw = b'{"execution_mode":"native_training"}'
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    assert _read_receipt(path, digest)["execution_mode"] == "native_training"
    with pytest.raises(ValueError, match="integrity"):
        _read_receipt(path, "0" * 64)
    alias = tmp_path / "alias.json"
    alias.symlink_to(path)
    with pytest.raises(ValueError, match="canonical"):
        _read_receipt(alias, digest)


def feedback_case():
    text = "The officer shall retain records."
    row = {"id": "source-1", "source_span_id": "source-1", "text": text,
           "agrees": False, "reason": "dropped_clause", "capture": {"triples": []}}
    hint = {"source_span_id": "source-1", "source_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            **compact_guidance(Model(), SimpleNamespace(sample_id="sample-1"))}
    report = {"schema": SCHEMA, "candidate": {"sha256": "a" * 64},
              "worker_receipt_sha256": "b" * 64, "code_hashes": {"parser": "c" * 64},
              "code_changed_since_training": [], "training_selection_only": True,
              "sample_memory_used": False, "state_changed": False, "counts_as_validation": False,
              "symbolic_decoder_output": False, "admitted": False, "formalized": False,
              "production_promotion": False, "observations": [hint], "observation_count": 1}
    return {"agrees": False, "rows": [row]}, report


def test_attached_hints_cannot_change_compiler_agreement_or_source_captures():
    agreement, report = feedback_case()
    result = attach_guidance(agreement, report, "sha256:" + "a" * 64)
    assert result["agrees"] is False and result["rows"][0]["agrees"] is False
    assert result["rows"][0]["capture"] == agreement["rows"][0]["capture"]
    assert "learned_guidance" not in agreement["rows"][0]


@pytest.mark.parametrize("mutation", ["source", "model", "memory", "promotion", "duplicate", "missing"])
def test_feedback_binding_rejects_wrong_source_model_or_authority(mutation):
    agreement, report = feedback_case()
    model = "sha256:" + "a" * 64
    if mutation == "source":
        agreement["rows"][0]["text"] += " changed"
    elif mutation == "model":
        model = "sha256:" + "d" * 64
    elif mutation == "memory":
        report["observations"][0]["sample_memory_used"] = True
    elif mutation == "promotion":
        report["production_promotion"] = True
    elif mutation == "duplicate":
        report["observations"] *= 2
    else:
        report["observations"] = []
        report["observation_count"] = 0
    with pytest.raises(ValueError):
        attach_guidance(agreement, report, model)


def test_hints_are_sealed_but_do_not_reopen_identical_compiler_failures(tmp_path):
    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource
    from ipfs_datasets_py.logic.autoformal.supervisor_queue import repair_packets, enqueue_repairs, read_packet, replay_packet
    agreement, report = feedback_case()
    def packets(value, model):
        return repair_packets(value, release_id="release", code_identity="code", model_identity=model)
    with DatabaseTaskSource(tmp_path / "control.duckdb") as source:
        old = enqueue_repairs(source, packets(agreement, "old-model"), packet_directory=tmp_path / "packets")
        task = source.get(old["inserted"][0])
        attached = attach_guidance(agreement, report, "sha256:" + "a" * 64)
        new = packets(attached, "sha256:" + "a" * 64)
        observed = enqueue_repairs(source, new, packet_directory=tmp_path / "packets")
        assert observed["task_count"] == 0 and observed["covered"][0]["task_id"] == task.task_alias
        assert source.get(task.task_cid).revision == task.revision
        sealed = observed["covered"][0]
        packet = read_packet(Path(sealed["packet_path"]), sealed["observation_sha256"])
        assert packet["row"]["learned_guidance"]["counts_as_validation"] is False
        def census(samples, inference):
            assert inference["captures"] == [{"sample_id": "source-1", "triples": []}]
            return {"rows": [{"id": "source-1", "agrees": False, "skipped": False}]}
        assert not replay_packet(packet, census=census)["passed"]
