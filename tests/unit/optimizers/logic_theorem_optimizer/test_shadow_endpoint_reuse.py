"""Synthetic full checkpoints exercise private endpoint reuse; no training.

The public shadow remains the independent three-load reference. Only timing
observations and output paths are removed when comparing its persisted evidence.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
from dataclasses import replace
import gc
from pathlib import Path
from types import SimpleNamespace
import weakref

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation_contracts as c
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_sparse_shadow as shadow
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS, ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import serialize_checkpoint
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_patch_codec import decode_patch
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_state_diff import exact_state_snapshot


def _populated():
    state = ModalAutoencoderTrainingState()
    for name in MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS:
        value = getattr(state, name)
        if isinstance(value, dict):
            if name == "proof_auxiliary_head_logits":
                value = {"obligation_family": {"__global__": {"mandatory": -0.0, "permissive": 0.25}}}
            elif name == "legal_ir_view_logits":
                value = {"deontic": -0.0, "flogic": 0.25}
            elif "embedding" in name:
                value = {"keep": [-0.0, 0.125], "delete": [0.25]}
            else:
                value = {"keep": {"deontic": -0.0}, "delete": {"flogic": 0.25}}
            setattr(state, name, value)
        elif isinstance(value, list):
            setattr(state, name, ["before", "before", "last"])
    state.proof_feedback_version_fingerprint = "synthetic-proof-v1"
    return state


def _endpoints(tmp_path, *, change="multifield", legacy_base=False):
    base = _populated()
    # Load the exact serialized base first: legacy JSON intentionally normalizes
    # its revision to zero, and compact loading preserves the sealed revision.
    base_path = tmp_path / "base.checkpoint"
    base_path.write_bytes((base.to_json() + "\n").encode() if legacy_base else
                          serialize_checkpoint(base, metadata={"endpoint": "base", "fixture": True}))
    base_ref = c.describe(base_path)
    final = c.load_full_checkpoint(base_ref).state
    if change == "multifield":
        final.feature_embedding_weights.pop("delete")
        final.feature_embedding_weights["keep"][0] = 0.0
        # Keep the inserted row after the surviving row in the canonical
        # compact order so this case exercises row deletion/insertion, rather
        # than the separately supported whole-component reorder replacement.
        final.feature_embedding_weights["z-insert"] = [-0.0, 0.5]
        final.feature_family_logits["keep"]["deontic"] = 0.125
        final.applied_todo_ids[:] = ["last", "last", "new"]
        final.applied_leanstral_guidance_ids.append("synthetic-guidance")
        final.proof_auxiliary_head_logits["obligation_family"]["__global__"]["mandatory"] = 0.5
    elif change == "revision_only":
        final.legal_ir_view_logits["temporary"] = 1.0
        del final.legal_ir_view_logits["temporary"]
    else:
        assert change == "unchanged"
    final_path = tmp_path / "final.checkpoint"
    final_path.write_bytes(serialize_checkpoint(final,
        metadata={"endpoint": "final", "fixture": True, "signed_zero": -0.0},
        metric_lineage={"schema": "synthetic-lineage", "order": ["b", "a"]}))
    return base_ref, c.describe(final_path)


def _holder(base, final):
    handoff = shadow._VerifiedCheckpointEndpoints(base)
    handoff.load_final(final)
    return handoff


def _write(handoff, base, final, directory):
    directory.mkdir()
    return shadow._write_checkpoint_shadow_from_verified_endpoints(
        handoff, base, final, base_version_id="synthetic-registered-base", output_directory=directory,
        provenance={"fixture": "loaded-endpoint-reuse", "admitted": False})


def _semantic_evidence(value):
    result = copy.deepcopy(value)
    del result["timings"]
    del result["capture_report"]["timings"]
    del result["replay_report"]["identity_hashing_seconds"]
    del result["receipt_ref"]  # Its hash includes timing and the output path.
    del result["patch_ref"]["path"]
    return result


def _assert_closed(handoff):
    # First establish automatic cleanup; explicit close must not mask its loss.
    with pytest.raises(shadow.SparseShadowError, match="closed|consumed"):
        _ = handoff.base
    handoff.close()
    handoff.close()
    with pytest.raises(shadow.SparseShadowError, match="closed|consumed"):
        _ = handoff.base


@pytest.mark.parametrize("change,legacy_base", [
    ("multifield", False), ("multifield", True), ("revision_only", False), ("unchanged", False),
])
def test_reused_endpoints_match_public_patch_and_all_38_field_evidence(tmp_path, change, legacy_base):
    base, final = _endpoints(tmp_path, change=change, legacy_base=legacy_base)
    before = {ref["path"]: c.verify(ref) for ref in (base, final)}
    public_directory = tmp_path / "public"
    public_directory.mkdir()
    public = shadow.write_checkpoint_shadow(base, final, base_version_id="synthetic-registered-base",
        output_directory=public_directory, provenance={"fixture": "loaded-endpoint-reuse", "admitted": False})
    handoff = _holder(base, final)
    expected_base = exact_state_snapshot(handoff.base.state)
    expected_final = exact_state_snapshot(c.load_full_checkpoint(final).state)
    reused = _write(handoff, base, final, tmp_path / "reused")
    assert c.verify(public["patch_ref"]) == c.verify(reused["patch_ref"])
    assert _semantic_evidence(public) == _semantic_evidence(reused)
    assert reused["capture_report"]["base_snapshot"] == expected_base
    assert reused["capture_report"]["result_snapshot"] == expected_final
    assert expected_base["component_count"] == expected_final["component_count"] == 38
    assert all(reused["checks"].values())
    assert reused["checks"]["independent_base_reload"] is True
    assert reused["checks"]["compact_final_bytes_exact"] is True
    assert reused["regenerated_compact_checkpoint"] == {key: final[key] for key in ("sha256", "bytes")}
    assert {ref["path"]: c.verify(ref) for ref in (base, final)} == before
    saved = c.parse_json(c.verify(reused["receipt_ref"]))
    assert saved == {key: value for key, value in reused.items() if key != "receipt_ref"}
    patch = decode_patch(c.verify(reused["patch_ref"]))
    assert patch.provenance["context"] == {"fixture": "loaded-endpoint-reuse", "admitted": False}
    if change == "multifield":
        assert reused["capture_report"]["counts"]["deleted_rows"] == 1
        assert reused["capture_report"]["counts"]["inserted_rows"] == 1
    else:
        assert reused["capture_report"]["revision_only"] is (change == "revision_only")
    _assert_closed(handoff)


@pytest.mark.parametrize("reuse", [False, True])
def test_standalone_and_private_paths_load_three_endpoints_without_three_live_graphs(tmp_path, monkeypatch, reuse):
    base, final = _endpoints(tmp_path)
    real_load = c.load_full_checkpoint
    graphs, loaded_paths = [], []

    def observed_load(ref, *args, **kwargs):
        gc.collect()  # Native state tracking can contain normal GC cycles.
        assert sum(item() is not None for item in graphs) <= 1
        loaded = real_load(ref, *args, **kwargs)
        loaded_paths.append(ref["path"])
        graphs.append(weakref.ref(loaded.state))
        assert sum(item() is not None for item in graphs) <= 2
        return loaded

    monkeypatch.setattr(c, "load_full_checkpoint", observed_load)
    monkeypatch.setattr(shadow, "load_full_checkpoint", observed_load)
    if reuse:
        handoff = _holder(base, final)
        result = _write(handoff, base, final, tmp_path / "private")
        _assert_closed(handoff)
    else:
        directory = tmp_path / "public"
        directory.mkdir()
        result = shadow.write_checkpoint_shadow(base, final, base_version_id="base", output_directory=directory)
    assert loaded_paths == [base["path"], final["path"], base["path"]]
    assert result["checks"]["independent_base_reload"] is True
    gc.collect()
    assert all(item() is None for item in graphs)


@pytest.mark.parametrize("endpoint", ["base", "final"])
@pytest.mark.parametrize("mutation", ["ordinary", "hidden_proof", "metadata"])
def test_handoff_rejects_loaded_endpoint_mutation_even_when_identity_normalizes_it(tmp_path, endpoint, mutation):
    base, final = _endpoints(tmp_path)
    handoff = shadow._VerifiedCheckpointEndpoints(base)
    loaded_final = handoff.load_final(final)
    loaded = handoff.base if endpoint == "base" else loaded_final
    original_digest = loaded.state.state_identity()
    if mutation == "metadata":
        loaded.manifest.metadata["endpoint"] = "tampered in process"
    elif mutation == "hidden_proof":
        # Unknown proof heads are normalized away by model identity. Tracked
        # revision drift must still reject the modified raw native endpoint.
        loaded.state.proof_auxiliary_head_logits["unrecognized-head"] = {"f": {"x": 0.125}}
        assert loaded.state.state_identity() == original_digest
    else:
        loaded.state.feature_embedding_weights["keep"][0] = 0.75
    with pytest.raises(shadow.SparseShadowError):
        _write(handoff, base, final, tmp_path / "failed")
    assert not list((tmp_path / "failed").iterdir())
    _assert_closed(handoff)


@pytest.mark.parametrize("endpoint", ["base", "final"])
def test_changed_descriptor_bytes_at_handoff_entry_fail_before_capture(tmp_path, monkeypatch, endpoint):
    base, final = _endpoints(tmp_path)
    handoff = _holder(base, final)
    ref = base if endpoint == "base" else final
    Path(ref["path"]).write_bytes(c.verify(ref) + b"changed")
    monkeypatch.setattr(shadow, "capture_endpoint_patch", lambda *a, **k: pytest.fail("capture ran on changed source"))
    with pytest.raises(ValueError):
        _write(handoff, base, final, tmp_path / "failed")
    assert not list((tmp_path / "failed").iterdir())
    _assert_closed(handoff)


@pytest.mark.parametrize("wrong", ["base", "final", "path"])
def test_same_content_or_other_endpoint_cannot_change_bound_handoff_descriptor(tmp_path, wrong):
    base, final = _endpoints(tmp_path)
    handoff = _holder(base, final)
    supplied_base, supplied_final = dict(base), dict(final)
    if wrong == "base":
        supplied_base = final
    elif wrong == "final":
        supplied_final = base
    else:
        other_path = tmp_path / "identical-base"
        other_path.write_bytes(c.verify(base))
        supplied_base = c.describe(other_path)
    with pytest.raises(shadow.SparseShadowError, match="descriptors differ"):
        _write(handoff, supplied_base, supplied_final, tmp_path / "failed")
    assert not list((tmp_path / "failed").iterdir())
    _assert_closed(handoff)


@pytest.mark.parametrize("kind", ["missing_final", "closed", "reused", "fake"])
def test_handoff_requires_one_complete_loader_origin_transfer(tmp_path, kind):
    base, final = _endpoints(tmp_path)
    handoff = shadow._VerifiedCheckpointEndpoints(base)
    if kind != "missing_final":
        handoff.load_final(final)
    if kind == "closed":
        handoff.close()
    elif kind == "reused":
        consumed = handoff.consume(base, final)
        del consumed
    elif kind == "fake":
        handoff.close()
        handoff = SimpleNamespace(consume=lambda *a: pytest.fail("accepted arbitrary object"), close=lambda: None)
    with pytest.raises(shadow.SparseShadowError):
        _write(handoff, base, final, tmp_path / "failed")
    assert not list((tmp_path / "failed").iterdir())
    if kind != "fake":
        _assert_closed(handoff)


@pytest.mark.parametrize("boundary", ["thread", "process"])
def test_handoff_cannot_cross_creating_thread_or_process(tmp_path, monkeypatch, boundary):
    base, final = _endpoints(tmp_path)
    handoff = _holder(base, final)
    if boundary == "thread":
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_write, handoff, base, final, tmp_path / "failed")
            with pytest.raises(shadow.SparseShadowError, match="process and thread"):
                future.result(timeout=5)
    else:
        pid = shadow.os.getpid()
        monkeypatch.setattr(shadow.os, "getpid", lambda: pid + 1)
        with pytest.raises(shadow.SparseShadowError, match="process and thread"):
            _write(handoff, base, final, tmp_path / "failed")
        monkeypatch.undo()
    assert not list((tmp_path / "failed").iterdir())
    _assert_closed(handoff)


@pytest.mark.parametrize("bad", ["wrong_state_type", "float32", "delta", "applied_delta", "recovered_tail", "bool_revision"])
def test_loader_origin_still_requires_exact_native_full_lossless_endpoint(tmp_path, monkeypatch, bad):
    base, final = _endpoints(tmp_path)
    real_load = c.load_full_checkpoint

    def substituted(ref, **kwargs):
        loaded = real_load(ref, **kwargs)
        if bad == "wrong_state_type":
            return replace(loaded, state=SimpleNamespace())
        if bad in {"float32", "delta", "bool_revision"}:
            field, value = {"float32": ("float_precision", "float32"),
                            "delta": ("kind", "delta"), "bool_revision": ("revision", True)}[bad]
            return replace(loaded, manifest=replace(loaded.manifest, **{field: value}))
        return replace(loaded, **{"applied_delta_count" if bad == "applied_delta" else "recovered_tail_bytes": 1})

    monkeypatch.setattr(c, "load_full_checkpoint", substituted)
    with pytest.raises(shadow.SparseShadowError):
        shadow._VerifiedCheckpointEndpoints(base)


@pytest.mark.parametrize("failure", ["load_final", "capture", "publication"])
def test_failure_closes_handoff_and_releases_owned_graphs_without_masking_primary(tmp_path, monkeypatch, failure):
    base, final = _endpoints(tmp_path)
    real_load = c.load_full_checkpoint
    graphs = []
    primary = OSError("synthetic endpoint reuse failure")

    def observed_load(ref, **kwargs):
        if failure == "load_final" and ref == final:
            raise primary
        loaded = real_load(ref, **kwargs)
        graphs.append(weakref.ref(loaded.state))
        return loaded

    def fail(*args, **kwargs):
        raise primary

    monkeypatch.setattr(c, "load_full_checkpoint", observed_load)
    monkeypatch.setattr(shadow, "load_full_checkpoint", observed_load)
    handoff = shadow._VerifiedCheckpointEndpoints(base)
    with pytest.raises(OSError) as caught:
        handoff.load_final(final)
        if failure == "capture":
            monkeypatch.setattr(shadow, "capture_endpoint_patch", fail)
        elif failure == "publication":
            monkeypatch.setattr(shadow, "_publish_receipt", fail)
        _write(handoff, base, final, tmp_path / "failed")
    assert caught.value is primary
    assert not (tmp_path / "failed" / "receipt.json").exists()
    _assert_closed(handoff)
    # Exceptions intentionally keep their traceback locals while held. Release
    # that normal lifetime before checking for global/holder retention.
    primary.__traceback__ = None
    del caught, primary
    gc.collect()
    assert all(item() is None for item in graphs)
