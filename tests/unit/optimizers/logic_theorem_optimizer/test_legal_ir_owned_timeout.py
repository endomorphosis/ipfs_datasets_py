"""Target deadlines cross adapter error handlers and remain owner observations."""
import signal

import pytest

from ipfs_datasets_py.logic.bridge import multiview
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample


@pytest.mark.parametrize("nested_handler", [False, True])
def test_owned_timeout_crosses_adapter_handlers_and_restores_signal(monkeypatch, nested_handler):
    if not modal._legal_ir_target_timeout_enabled(15.0):
        pytest.skip("requires main-thread SIGALRM target deadline")
    sample = build_us_code_sample(
        title="5", section="owned-timeout-boundary",
        text="The agency shall publish the owned timeout boundary fixture notice.",
    )
    original_handler = signal.getsignal(signal.SIGALRM)
    original_timer = signal.getitimer(signal.ITIMER_REAL)
    assert original_timer == (0.0, 0.0)
    calls, finalized = [], []
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_TARGET_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE", "0")
    monkeypatch.setattr(modal, "_LEGAL_IR_TARGET_CACHE", {})
    monkeypatch.setattr(multiview, "_MULTIVIEW_EVALUATION_CACHE", {})
    monkeypatch.setattr(multiview, "load_logic_bridge_adapter", lambda name: name)

    def interrupted_adapter(name, *args, **kwargs):
        calls.append(name)
        try:
            handler = signal.getsignal(signal.SIGALRM)
            assert callable(handler) and handler is not original_handler
            if nested_handler:
                try:
                    handler(signal.SIGALRM, None)
                except Exception:
                    return None
            handler(signal.SIGALRM, None)
        finally:
            finalized.append(name)

    monkeypatch.setattr(multiview, "_evaluate_adapter", interrupted_adapter)
    target = modal._legal_ir_target_items(
        [sample], bridge_names=("modal_frame_logic", "deontic_norms"),
        evaluate_provers=False, legal_ir_targets=None, parallel_workers=1,
    )[0][1]
    assert target.accepted is False
    assert target.losses["legal_ir_target_timeout_loss"] == 1.0
    assert target.document.canonical_hash().startswith("timeout-fallback:")
    assert calls == finalized == ["modal_frame_logic"]
    assert signal.getsignal(signal.SIGALRM) is original_handler
    assert signal.getitimer(signal.ITIMER_REAL) == original_timer


def test_ordinary_adapter_exception_still_becomes_reported_failure(monkeypatch):
    monkeypatch.setattr(multiview, "load_logic_bridge_adapter", lambda name: name)

    def ordinary_failure(*args, **kwargs):
        raise RuntimeError("ordinary adapter failure")

    monkeypatch.setattr(multiview, "_evaluate_adapter", ordinary_failure)
    report = multiview.evaluate_legal_ir_multiview(
        "ordinary error fixture", bridge_names=("modal_frame_logic",),
        evaluate_provers=False, cache=False,
    )
    assert report.failures == {"modal_frame_logic": "RuntimeError: ordinary adapter failure"}
    assert report.reports == {}
    assert report.accepted is False
