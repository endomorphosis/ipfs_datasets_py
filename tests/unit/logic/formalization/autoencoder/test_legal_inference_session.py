"""Existing packages retain identities and checks under default acceleration."""
import copy
import importlib.util
from pathlib import Path
from contextlib import contextmanager
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_384_package as package
from ipfs_datasets_py.logic.formalization.autoencoder.checkpoint_hub import HubAutoencoder
from ipfs_datasets_py.logic.formalization.autoencoder.legal_inference_session import optimize_autoencoder

spec = importlib.util.spec_from_file_location("legal_package_fixture", Path(__file__).with_name("test_legal_384_package.py"))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
packaged = fixtures.packaged


def open_pair(packaged):
    receipt, rows = packaged
    runtime = package.load_package(receipt["path"], expected_sha256=receipt["sha256"])
    ordinary = HubAutoencoder("legal_ir", runtime, {}, None)
    return ordinary, optimize_autoencoder(ordinary), rows


def without_inference_evidence(result):
    result = copy.deepcopy(result)
    result.pop("inference_implementation", None)
    result["result"].pop("inference_implementation", None)
    return result


def test_existing_package_and_scalar_result_are_preserved(packaged):
    ordinary, optimized, rows = open_pair(packaged)
    original_decoder = ordinary.runtime.model._joint_formula_decoder
    assert without_inference_evidence(optimized.infer(rows)) == ordinary.infer(rows)
    assert optimized.describe()["runtime"]["checkpoint_sha256"] == ordinary.describe()["runtime"]["checkpoint_sha256"]
    assert ordinary.runtime.model._joint_formula_decoder is original_decoder
    assert optimize_autoencoder(optimized) is optimized


def test_fresh_package_samples_skip_only_empty_embedding_heads(packaged, monkeypatch):
    ordinary, optimized, rows = open_pair(packaged)
    expected = ordinary.infer(rows)
    model = ordinary.runtime.model
    names = (
        "compiler_quality", "logic_signature", "round_trip_signal", "decompiler_plan",
        "predicate_argument", "family", "semantic_slot", "family_semantic_slot",
        "semantic_slot_legal_ir_view", "family_semantic_slot_legal_ir_view",
        "family_legal_ir_view", "legal_ir_view", "feature",
    )
    def unused(*args, **options):
        raise AssertionError("unused empty embedding head was evaluated")
    for name in names:
        assert not getattr(model.state, name + "_embedding_weights")
        monkeypatch.setattr(model._implementation_class, "_" + name + "_embedding_adjustment", unused)
    assert without_inference_evidence(optimized.infer(rows)) == expected
    with pytest.raises(AssertionError, match="unused empty embedding head"):
        ordinary.infer(rows)


def test_package_without_formula_head_preserves_abstention(packaged, tmp_path):
    ordinary, _, rows = open_pair(packaged)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages import current_v2
    model = current_v2.Autoencoder(**ordinary.runtime._payload["core_options"])
    receipt = package.build_package(tmp_path / "without-head", model=model,
        core_options=ordinary.runtime._payload["core_options"],
        embedding_contract=ordinary.runtime._payload["embedding_contract"],
        fixture_rows=rows, provenance={"synthetic_vectors": True})
    base = HubAutoencoder("legal_ir", package.load_package(receipt["path"], expected_sha256=receipt["sha256"]), {}, None)
    optimized = optimize_autoencoder(base)
    result = optimized.infer(rows)
    assert without_inference_evidence(result) == base.infer(rows)
    assert result["result"]["rows"][0]["reason"] == "learned_formula_head_absent"


def test_mutated_core_is_rejected(packaged):
    ordinary, optimized, rows = open_pair(packaged)
    ordinary.runtime.model.state.feature_embedding_weights["tampered"] = [1.] * 384
    with pytest.raises(ValueError, match="core changed"):
        optimized.infer(rows)


@pytest.mark.parametrize("owner", [False, True])
def test_tensor_data_mutation_is_rejected(packaged, owner):
    ordinary, optimized, rows = open_pair(packaged)
    decoder = (ordinary.runtime.model._joint_formula_decoder if owner
               else optimized.runtime._session._decoder)
    next(decoder.model.parameters()).data.add_(1.)
    with pytest.raises(ValueError, match="cached decoder weights differ"):
        optimized.infer(rows)


def test_source_text_entrypoint_uses_cached_embedding_api(packaged, monkeypatch):
    _, optimized, rows = open_pair(packaged)
    from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_384
    calls = []
    def embed(texts, **options):
        calls.append(texts)
        return [rows[0]["embedding"]]
    monkeypatch.setattr(source_embeddings_384, "embed_texts", embed)
    result = optimized.infer_texts([rows[0]["source_text"]])
    assert calls == [[rows[0]["source_text"]]]
    assert result["result"]["rows"][0]["id"] == "input-0"
    assert result["provider_calls"] == result["training_steps"] == 0


@pytest.mark.parametrize("options", [{}, {"optimized": True}, {"optimized": False}])
def test_legal_open_defaults_to_optimization_and_forwards_opt_out(packaged, monkeypatch, options):
    ordinary, _, _ = open_pair(packaged)
    from ipfs_datasets_py.logic.legal_ir.autoencoder import open_autoencoder
    from ipfs_datasets_py.logic.formalization.autoencoder import checkpoint_hub
    calls = []
    def load(domain, **options):
        calls.append((domain, options))
        return checkpoint_hub._loaded_autoencoder(domain, ordinary.runtime, {}, None,
                                                 optimized=options["optimized"])
    monkeypatch.setattr(checkpoint_hub, "open_autoencoder", load)
    loaded = open_autoencoder(local_files_only=True, **options)
    optimized = options.get("optimized", True)
    assert (loaded.runtime is ordinary.runtime) is (not optimized)
    assert calls == [("legal_ir", {"local_files_only": True, "optimized": optimized})]
    with pytest.raises(ValueError, match="boolean"):
        open_autoencoder(optimized="yes")


@pytest.mark.parametrize("optimized", [True, False])
@pytest.mark.parametrize("local", [True, False])
def test_hub_legal_loaders_select_acceleration_and_preserve_release(packaged, tmp_path, monkeypatch,
                                                                  optimized, local):
    import hashlib
    from ipfs_datasets_py.logic.formalization.autoencoder import checkpoint_hub as hub
    from ipfs_datasets_py.logic.formalization.autoencoder.legal_inference_session import OptimizedRuntime
    receipt, rows = packaged
    directory = tmp_path / "hub-release"
    hub.build_package("legal_ir", receipt["path"], directory,
                      provenance={"scope": "fixture"}, validation={"scope": "fixture"})
    digest = hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest()
    # Omit the option for True to exercise the public defaults directly.
    options = {} if optimized else {"optimized": False}
    if local:
        loaded = hub.open_local_autoencoder("legal_ir", directory, manifest_sha256=digest, **options)
    else:
        selection = {"schema": hub.DESCRIPTOR_SCHEMA, "domain_id": "legal_ir",
                     "repository_id": "Publicus/legal-ir-autoencoder", "revision": "a" * 40,
                     "release_prefix": "releases/fixture", "manifest_sha256": digest}
        calls = []
        def download(**options):
            calls.append(options)
            return str(directory / options["filename"].rsplit("/", 1)[-1])
        monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(hf_hub_download=download))
        loaded = hub.open_autoencoder("legal_ir", descriptor=selection, local_files_only=True, **options)
        assert loaded.descriptor == selection
        assert all(call["local_files_only"] and call["revision"] == selection["revision"] for call in calls)
    assert isinstance(loaded.runtime, OptimizedRuntime) is optimized
    result = loaded.infer(rows)
    assert result["checkpoint_sha256"] == receipt["sha256"]
    assert ("inference_implementation" in result) is optimized
    ordinary = hub.open_local_autoencoder("legal_ir", directory, manifest_sha256=digest, optimized=False)
    assert without_inference_evidence(result) == ordinary.infer(rows)


@pytest.mark.parametrize("local", [True, False])
@pytest.mark.parametrize("optimized", [None, 1, "yes"])
def test_hub_rejects_invalid_optimization_flag_before_loading(monkeypatch, local, optimized):
    from ipfs_datasets_py.logic.formalization.autoencoder import checkpoint_hub as hub
    def unexpected(*args, **options):
        raise AssertionError("invalid option must fail before file or network access")
    monkeypatch.setattr(hub, "verify_package", unexpected)
    monkeypatch.setattr(hub, "default_descriptor", unexpected)
    with pytest.raises(ValueError, match="optimized must be a boolean"):
        if local:
            hub.open_local_autoencoder("legal_ir", "/unused", manifest_sha256="unused", optimized=optimized)
        else:
            hub.open_autoencoder("legal_ir", optimized=optimized)


def test_blas_limits_restore_caller_settings_on_success_and_failure(monkeypatch):
    import torch
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_inference_session as subject
    events = []
    original_threads = torch.get_num_threads()
    @contextmanager
    def limits(**options):
        assert options == {"limits": 1, "user_api": "blas"}
        assert torch.get_num_threads() == 1
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")
    monkeypatch.setitem(sys.modules, "threadpoolctl", SimpleNamespace(threadpool_limits=limits))
    @subject._cpu_inference
    def call(fail=False):
        assert events[-1] == "enter"
        if fail:
            raise ValueError("failed inference")
        return "ok"
    assert call() == "ok"
    assert torch.get_num_threads() == original_threads
    with pytest.raises(ValueError, match="failed inference"):
        call(True)
    assert torch.get_num_threads() == original_threads
    assert events == ["enter", "exit", "enter", "exit"]


def test_blas_dependency_is_optional(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_inference_session as subject
    monkeypatch.setitem(sys.modules, "threadpoolctl", None)
    with subject._blas_limits():
        pass
