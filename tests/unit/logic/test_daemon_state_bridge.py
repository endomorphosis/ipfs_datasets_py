"""A bridge-on daemon-state measurement is not a training step."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    path = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "ops"
        / "legal_ir"
        / "evaluate_daemon_state_bridge.py"
    )
    spec = importlib.util.spec_from_file_location("evaluate_daemon_state_bridge_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Evaluation:
    sample_count = 3
    legal_ir_target_count = 3
    legal_ir_losses = {"legal_ir_view_cross_entropy_loss": 0.4}
    legal_ir_view_distribution = {"deontic.ir": 0.5}
    legal_ir_view_family_metrics = {"deontic": {"ir_cosine_similarity": 0.9}}


def test_receipt_records_targets_and_does_not_admit() -> None:
    module = _module()
    receipt = module.measurement_receipt(_Evaluation(), state_path=Path("state.json"))
    assert receipt["optimizer_step"] is False
    assert receipt["admitted"] is False
    assert receipt["legal_ir_target_count"] == 3
    assert receipt["lift"]["status"] == "measured_no_lift"
    assert receipt["training_allowed"] is True
    assert "decoded_embeddings" not in receipt


def test_zero_targets_do_not_allow_training() -> None:
    module = _module()

    class Empty(_Evaluation):
        legal_ir_target_count = 0
        legal_ir_losses = {}

    receipt = module.measurement_receipt(Empty(), state_path=Path("state.json"))
    assert receipt["training_allowed"] is False
    assert receipt["lift"]["status"] == "measured_no_lift"
