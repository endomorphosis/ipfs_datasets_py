"""Complete codec observations preserve evidence without claiming learned inference."""

from __future__ import annotations

import hashlib
import importlib
from types import SimpleNamespace


def test_full_codec_capture_keeps_all_formulas_raw_text_and_measured_losses(
    monkeypatch,
):
    reports = importlib.import_module("ipfs_datasets_py.logic.autoformal.repair_report")
    raw_text = "  Decoded\n text " * 100
    structural = "Structural details " * 100
    full_ir = {
        "formulas": [{"index": i, "arguments": list(range(8))} for i in range(12)]
    }

    class Value:
        def __init__(self, value):
            self.value = value

        def to_dict(self):
            return self.value

    formulas = [
        SimpleNamespace(
            operator=Value({"symbol": "O"}),
            predicate=Value(
                {"name": "retain", "arguments": [str(i) for i in range(8)]}
            ),
            metadata={},
        )
        for _ in range(12)
    ]
    losses = {
        "cross_entropy_loss": 0.25,
        "text_reconstruction_loss": 0.5,
        "source_decompiled_text_embedding_cosine_similarity": 0.9,
    }
    encoded = SimpleNamespace(
        modal_ir=SimpleNamespace(formulas=formulas, to_dict=lambda: full_ir),
        losses=losses,
        decoded_text=raw_text,
        metadata={
            "modal_decompiler_structural_text": structural,
            "parser_backend": "test-backend",
        },
    )
    calls = []

    def encode(text, *, document_id):
        calls.append((text, document_id))
        return encoded

    monkeypatch.setattr(reports, "_CODEC", SimpleNamespace(encode=encode))
    source = "The agency shall retain records."
    compact = reports.codec_capture(source)
    full = reports.codec_capture(source, include_full_evidence=True)
    assert "codec_observation" not in compact
    assert len(compact["formulas"]) == 6 and len(compact["structural"]) == 180
    assert full["decoded_text"] == " ".join(raw_text.split())
    observation = full["codec_observation"]
    assert observation["modal_ir"] == full_ir
    assert observation["full_decoded_text"] == raw_text
    assert observation["full_structural_text"] == structural
    assert observation["raw_losses"] == losses
    assert observation["learned_autoencoder_execution"] is False
    assert observation["codec_kind"] == "DeterministicModalLogicCodec"
    assert (
        observation["source_text_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    )
    assert len(calls) == 2


def test_full_codec_capture_records_failure_without_fabricating_outputs(monkeypatch):
    reports = importlib.import_module("ipfs_datasets_py.logic.autoformal.repair_report")

    def fail_encode(*args, **kwargs):
        raise TimeoutError("test deadline")

    monkeypatch.setattr(reports, "_CODEC", SimpleNamespace(encode=fail_encode))
    result = reports.codec_capture(
        "The agency shall retain records.", include_full_evidence=True
    )
    assert result["decoded_text"] == "" and result["formulas"] == []
    observation = result["codec_observation"]
    assert (
        observation["status"] == "error" and observation["error_type"] == "TimeoutError"
    )
    assert observation["learned_autoencoder_execution"] is False
    assert "raw_losses" not in observation and "modal_ir" not in observation
