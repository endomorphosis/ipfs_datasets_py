"""Census cache opt-out keeps complete targets without retaining other batches."""
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE", "0")
    monkeypatch.setattr(modal, "_LEGAL_IR_TARGET_CACHE", {})
    monkeypatch.setattr(modal, "_legal_ir_target_cache_key", lambda sample, **kw: sample.sample_id)
    calls = []
    def generate(callback, **kw):
        calls.append(kw["document_id"])
        target = SimpleNamespace(bridge_names=("deontic_norms",), native_cache_enabled=kw["cache"],
            document=SimpleNamespace(document_id=kw["document_id"], version="fixture",
                                     canonical_hash=lambda: "a" * 64),
            losses={"fixture_loss": .5}, adapter_losses={}, view_distribution={"deontic.ir": 1.},
            accepted=False)
        return SimpleNamespace(training_target=lambda: target)
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", generate)
    sample = SimpleNamespace(sample_id="one", text="Agency shall file.", citation="usc:1:1",
                             source="fixture", embedding_vector=[.1] * 8)
    return sample, calls


def targets(samples, **kwargs):
    return modal._legal_ir_target_items(samples, bridge_names=("deontic_norms",),
        evaluate_provers=False, legal_ir_targets=None, **kwargs)


def test_default_reuses_target_unchanged(native):
    sample, calls = native
    first = targets([sample])
    observed = {}
    assert targets([sample], observation=observed) == first
    assert calls == ["one"]
    assert first[0][1].native_cache_enabled is True
    assert observed["memory_cache_hit_count"] == 1
    assert observed["process_target_cache_enabled"] is True


def test_optout_bypasses_existing_target_without_destroying_foreign_cache(native):
    sample, calls = native
    old = object()
    modal._LEGAL_IR_TARGET_CACHE["one"] = old
    for _ in range(3):
        observed = {}
        result = targets([sample], use_process_cache=False, observation=observed)
        assert result[0][1] is not old
        assert result[0][1].native_cache_enabled is False
        assert result[0][1].document.canonical_hash() == "a" * 64
        assert result[0][1].losses == {"fixture_loss": .5}
        assert observed["memory_cache_hit_count"] == 0
        assert observed["process_target_cache_enabled"] is False
        assert observed["native_bridge_report_cache_enabled"] is False
        assert observed["process_target_cache_entries_at_start"] == 1
        assert observed["process_target_cache_entries_at_end"] == 1
    assert modal._LEGAL_IR_TARGET_CACHE == {"one": old}
    assert len(calls) == 3


def test_threaded_optout_retains_no_targets(native):
    sample, calls = native
    samples = [SimpleNamespace(**{**vars(sample), "sample_id": str(i)}) for i in range(8)]
    observed = {}
    result = targets(samples, use_process_cache=False, parallel_workers=4, observation=observed)
    assert [item[0] for item in result] == [s.sample_id for s in samples]
    assert len(calls) == 8
    assert observed["generated_target_count"] == 8
    assert observed["process_target_cache_entries_at_end"] == 0
    assert not modal._LEGAL_IR_TARGET_CACHE


def test_disk_cache_writes_cannot_repopulate_disabled_process_cache(native, monkeypatch, tmp_path):
    sample, calls = native
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE", "1")
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_METRIC_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(modal, "_legal_ir_target_code_fingerprint", lambda: "fixture")
    targets([sample], use_process_cache=False)
    assert not modal._LEGAL_IR_TARGET_CACHE
    observed = {}
    targets([sample], use_process_cache=False, observation=observed)
    assert calls == ["one"]
    assert observed["disk_cache_hit_count"] == 1
    assert not modal._LEGAL_IR_TARGET_CACHE


@pytest.mark.parametrize("value", [0, 1, None, "false"])
def test_cache_switch_requires_boolean(native, value):
    with pytest.raises(ValueError, match="must be a bool"):
        targets([native[0]], use_process_cache=value)
