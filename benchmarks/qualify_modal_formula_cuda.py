"""Fresh actual-device qualification; never opens historical training owners.

Run with an exact shared host configuration and a new output directory. The
fixture trains two native Legal heads explicitly (30 epochs each), then freezes
training during CPU/CUDA inference. This is bounded numerical execution, not
general CodebaseIR decoding, a published-weight replay, or proof admission.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
import gc
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import resource
import statistics
import sys
import time
import traceback


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode()


def _write(path, value):
    path.write_bytes(_raw(value))
    path.chmod(0o444)
    return {"path": str(path), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _pin(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _compare_numbers(left, right):
    if len(left) != len(right) or any(len(a) != len(b) for a, b in zip(left, right)):
        raise ValueError("device vector dimensions differ")
    error = max((abs(a-b) for aa, bb in zip(left, right) for a, b in zip(aa, bb)), default=0.)
    if not math.isfinite(error) or error > 5e-5:
        raise ValueError("CPU/CUDA numerical parity exceeded 5e-5 absolute tolerance")
    return error


def _decision(row):
    return {key: row.get(key) for key in ("id", "source_sha256", "latent_sha256", "status",
            "reason", "canonical_ir", "formula_text", "formal_outputs", "generated_token_ids")}


def _guard(call, *, name, expected=ValueError):
    try:
        call()
    except expected as error:
        return {"name": name, "rejected": True, "exception": type(error).__name__, "message": str(error)}
    raise AssertionError(name + " did not reject")


def run(output, config_path):
    output.mkdir(parents=False)
    started = time.monotonic()
    result = {"schema": "native-legal-formula-cuda-qualification/v1", "qualified": False,
              "pid": os.getpid(), "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "scope": "fresh_native_legal_8d_and_384d_formula_heads_and_pinned_gte384_numerical_device_execution",
              "released_weight_qualification": False, "codebase_feature_cuda_qualification": False,
              "general_codebase_384d_qualification": False, "proof_authority": False,
              "source_semantics_verified": False, "execution_attestation": False,
              "kernel_resource_enforcement": False, "setup_training_calls": 0,
              "inference_training_calls": 0, "controls": [], "error": None}
    lease, scheduler = None, None
    sessions, decoders = [], []
    train_original = None
    try:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
            GlobalResourceScheduler, ResourceSchedulerConfig, ResourceLane)
        config_raw = config_path.read_bytes()
        configuration = json.loads(config_raw)
        config = ResourceSchedulerConfig(**configuration["persisted_config"],
            state_path=configuration["state_path"], lease_ttl_seconds=configuration["lease_ttl_seconds"],
            auto_renew_leases=configuration["auto_renew_leases"])
        scheduler = GlobalResourceScheduler(config)
        result["shared_configuration"] = _pin(config_path)
        result["resources_before"] = scheduler.snapshot()
        lease = scheduler.acquire(ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=1, memory_mb=2048,
            gpu_memory_mb=2048, requires_gpu=True, child_process_slots=0, timeout=30,
            request_id="native-legal-formula-cuda-qualification")
        result["admission"] = {"lease_id": lease.lease_id, "cpu_slots": lease.cpu_slots,
            "memory_mb": lease.memory_mb, "gpu_memory_mb": lease.gpu_memory_mb,
            "unified_memory_mb": lease.unified_memory_mb, "requires_gpu": lease.requires_gpu,
            "state_path": str(scheduler.state_path), "wait_seconds": lease.wait_seconds}
        print("ADMITTED", lease.lease_id, flush=True)
        import torch
        previous_threads = torch.get_num_threads()
        torch.set_num_threads(1)
        result["hardware"] = {"torch": str(torch.__version__), "cuda_runtime": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(), "device_count": torch.cuda.device_count(),
            "nvidia_smi_memory_scope": "N/A on unified GB10; Torch physical capacity recorded separately"}
        if not torch.cuda.is_available():
            raise RuntimeError("actual CUDA unavailable; no CPU or mocked CUDA qualification")
        device = torch.cuda.current_device()
        properties = torch.cuda.get_device_properties(device)
        result["hardware"].update(device_index=device, name=torch.cuda.get_device_name(device),
            capability=list(torch.cuda.get_device_capability(device)),
            physical_device_memory_bytes=properties.total_memory)
        # CUDA discovery does not initialize an execution context. Create and
        # execute a real tiny tensor before loading CPU encoder dependencies.
        # On a busy unified-memory host, late context creation can fail even
        # when that earlier hardware discovery succeeded.
        torch.cuda.init()
        result["hardware"]["free_total_device_bytes_before_models"] = list(torch.cuda.mem_get_info(device))
        probe = torch.tensor([2.], device="cuda:" + str(device))
        assert (probe * probe).cpu().tolist() == [4.]
        del probe
        torch.cuda.synchronize(device)
        result["actual_initial_cuda_kernel"] = True
        result["gpu_allocated_before"] = torch.cuda.memory_allocated(device)
        torch.cuda.reset_peak_memory_stats(device)
        torch.backends.cuda.matmul.allow_tf32 = False
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        names = [
            "ipfs_datasets_py.logic.formalization.autoencoder.source_embeddings_device_384",
            "ipfs_datasets_py.logic.formalization.autoencoder.source_embeddings_384",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_latent_formula_device_inference",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_latent_formula_inference",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_latent_formula",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_formula_codec",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.checkpoint_content_guard",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_runtime",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_joint_formula",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_cuda",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages._contract",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.current_v2",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1",
        ]
        modules = [importlib.import_module(name) for name in names]
        result["producer_scope"] = "listed modules, native binding sources and fixture only; not full transitive dependency attestation"
        producers = output / "producers"
        producers.mkdir()
        pins = []
        for index, path in enumerate([Path(__file__), *[Path(module.__file__) for module in modules]]):
            pin = _pin(path)
            copied = producers / (str(index).zfill(2) + "-" + path.name)
            copied.write_bytes(path.read_bytes())
            copied.chmod(0o444)
            pin["copy"] = str(copied.relative_to(output))
            pins.append(pin)
        result["source_pins"] = pins
        from ipfs_datasets_py.logic.formalization.autoencoder.source_embeddings_device_384 import SourceEmbeddingDeviceSession384
        from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_384 as old_embeddings
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as learning, modal_joint_formula as joint
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_latent_formula_device_inference import DeviceLatentFormulaDecoder
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages import current_v2, legacy_v1
        texts = ["The agency must disclose records.", "The agency must not disclose records."]
        texts += ["def compare_" + str(i) + "(a: int, b: int) -> bool:\n    return a < b\n" for i in range(30)]
        def checkpoint():
            if lease.cancelled:
                raise RuntimeError("shared host admission cancelled")
            if time.monotonic() - started > 300:
                raise TimeoutError("qualification exhausted 300 second cooperative deadline")
        lanes = {}
        for optimized, label in ((False, "cpu"), (True, "cuda")):
            checkpoint()
            t0 = time.monotonic()
            session = SourceEmbeddingDeviceSession384(optimized=optimized)
            sessions.append(session)
            cold_load = time.monotonic()-t0
            samples, latest = [], None
            for _ in range(3):
                checkpoint()
                t0 = time.monotonic()
                latest = session.infer(texts)
                torch.cuda.synchronize(device)
                samples.append(time.monotonic()-t0)
            assert latest["cuda_executed"] is optimized
            lanes[label] = {"report": latest, "cold_load_seconds": cold_load,
                            "warm_boundary_seconds": samples, "median_seconds": statistics.median(samples)}
            if label == "cpu":
                # The fixture compares retained values, not simultaneous
                # residency. Release its CPU twin before loading CUDA weights.
                session.close()
        embedding_error = _compare_numbers(lanes["cpu"]["report"]["vectors"], lanes["cuda"]["report"]["vectors"])
        assert lanes["cpu"]["report"]["tokens"] == lanes["cuda"]["report"]["tokens"]
        result["embeddings"] = {"count": len(texts), "cpu": lanes["cpu"], "cuda": lanes["cuda"],
                                "max_absolute_error": embedding_error, "absolute_tolerance": 5e-5}
        checkpoint()
        original_vectors = old_embeddings.embed_texts(texts[:2])
        original_device = str(next(iter(old_embeddings._MODEL_CACHE.values())).device)
        assert original_device == "cuda:" + str(device)
        result["existing_default_gte_path"] = {"actual_model_device": original_device,
            "max_absolute_error": _compare_numbers(original_vectors, lanes["cuda"]["report"]["vectors"][:2]),
            "cuda_executed": True, "count": 2}
        old_embeddings.clear_embedding_cache()
        formulas = []
        trained_heads = []
        for lineage in (legacy_v1, current_v2):
            checkpoint()
            width = lineage.DIMENSION
            core = lineage.Autoencoder(compute_device="cpu", initial_embedding_scale=.2,
                                       initial_embedding_rotation_scale=1.)
            core_before = joint._core_binding(core)
            vectors = (lanes["cpu"]["report"]["vectors"][:2] if width == 384
                       else [[.5] + [0.] * 7, [-.5] + [0.] * 7])
            sample_rows, targets = [], []
            for index, (text, vector) in enumerate(zip(texts[:2], vectors)):
                sample = lineage.build_sample(title="native-device-qualification", section=str(index), text=text,
                    embedding_model="thenlper/gte-small" if width == 384 else "authored-native-8d-diagnostic/v1",
                    embedding_vector=vector, top_k_frames=0)
                sample = replace(sample, sample_id="training-" + str(index),
                                 modal_ir=replace(sample.modal_ir, document_id="training-" + str(index)))
                sample_rows.append(sample)
                targets.append({"id": sample.sample_id, "source_text": text, "canonical_ir": {"rules": [dict(
                    modality="O" if index == 0 else "F", actor="agency", action="disclose", object="records",
                    conditions=[], exceptions=[], temporal=[])]}})
            rows = joint._rows(core, sample_rows, targets)
            initial = learning.build_checkpoint(core_before, rows, [], hidden_size=16, token_embedding_dim=8,
                projection_width=4, batch_size=2, learning_rate=.03)
            t0 = time.monotonic()
            trained = learning.train(initial, rows, [], epochs=30, max_seconds=30)
            result["setup_training_calls"] += 1
            assert joint._core_binding(core) == core_before
            artifact = _write(output / ("legal-" + str(width) + "-checkpoint.json"), trained["checkpoint"])
            _write(output / ("legal-" + str(width) + "-training-inputs.json"), rows)
            _write(output / ("legal-" + str(width) + "-training-report.json"), trained["report"])
            trained_heads.append((width, trained["checkpoint"], rows))
            formulas.append({"dimension": width, "checkpoint": artifact, "binding": core_before,
                "training_seconds": time.monotonic()-t0, "training_progress": trained["checkpoint"]["progress"],
                "actual_native_core_unchanged": True,
                "input_scope": "real_gte384_and_native_modal_core" if width == 384 else "authored8d_diagnostic_and_native_frozen_modal_core"})
        train_original = learning.train
        def no_train(*args, **kwargs):
            result["inference_training_calls"] += 1
            raise AssertionError("inference attempted training")
        learning.train = no_train
        for formula, (width, trained, authored) in zip(formulas, trained_heads):
            saved = deepcopy(trained)
            outputs = []
            for count in (1, 17, 128):
                checkpoint()
                rows = [{"id": "inference-" + str(index), "source_text": authored[index % 2]["source_text"],
                         "latent": list(authored[index % 2]["latent"])} for index in range(count)]
                reports, times, projected = {}, {}, {}
                for optimized, label in ((False, "cpu"), (True, "cuda")):
                    decoder = DeviceLatentFormulaDecoder(trained, optimized=optimized)
                    decoders.append(decoder)
                    torch.cuda.synchronize(device)
                    t0 = time.monotonic()
                    reports[label], projected[label] = decoder.infer_with_projection(rows)
                    torch.cuda.synchronize(device)
                    times[label] = time.monotonic()-t0
                    assert reports[label]["inference_implementation"]["cuda_executed"] is optimized
                assert [_decision(row) for row in reports["cpu"]["rows"]] == [_decision(row) for row in reports["cuda"]["rows"]]
                error = _compare_numbers(projected["cpu"], projected["cuda"])
                outputs.append({"count": count, "inference_seconds": times, "cpu": reports["cpu"],
                    "cuda": reports["cuda"], "cpu_projected": projected["cpu"], "cuda_projected": projected["cuda"],
                    "exact_decision_parity": True, "max_absolute_error": error})
            assert trained == saved
            formula["inference"] = outputs
            formula["checkpoint_and_adam_unchanged"] = True
        result["formulas"] = formulas
        result["controls"].append(_guard(lambda: sessions[1].infer(["legal " * 600]), name="overlong_token_input"))
        result["controls"].append(_guard(lambda: sessions[1].infer([texts[0]] * 129), name="129_embedding_rows"))
        saved_process = sessions[1]._process
        sessions[1]._process += 1
        result["controls"].append(_guard(lambda: sessions[1].infer([texts[0]]), name="foreign_process_embedding_session"))
        sessions[1]._process = saved_process
        with torch.no_grad():
            next(sessions[1]._model.parameters()).data.flatten()[0] += .125
        result["controls"].append(_guard(lambda: sessions[1].infer([texts[0]]), name="embedding_tensor_data_mutation"))
        guarded = decoders[-1]
        source = {"id": "control", "source_text": texts[0], "latent": trained_heads[-1][2][0]["latent"]}
        result["controls"].append(_guard(lambda: guarded.infer([{**source, "canonical_ir": {"rules": []}}]), name="formula_target_access"))
        with torch.no_grad():
            next(guarded.model.parameters()).data.flatten()[0] += .125
        result["controls"].append(_guard(lambda: guarded.infer([source]), name="formula_tensor_data_mutation"))
        result["peak_gpu_allocated_bytes"] = torch.cuda.max_memory_allocated(device)
        result["peak_gpu_reserved_bytes"] = torch.cuda.max_memory_reserved(device)
        result["peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        for pin in pins:
            assert _pin(pin["path"])["sha256"] == pin["sha256"]
        assert result["inference_training_calls"] == 0
        result["qualified"] = True
        print("NUMERICAL_PARITY_AND_CONTROLS_PASSED", flush=True)
    except BaseException as error:
        result["error"] = {"type": type(error).__name__, "message": str(error),
                           "traceback": traceback.format_exc()[-16384:]}
        print("QUALIFICATION_FAILED", type(error).__name__, str(error), flush=True)
    finally:
        try:
            if train_original is not None:
                learning.train = train_original
            for session in sessions:
                session.close()
            sessions.clear()
            decoders.clear()
            if "decoder" in locals():
                del decoder
            if "guarded" in locals():
                del guarded
            gc.collect()
            if "torch" in locals():
                torch.cuda.empty_cache()
                result["gpu_allocated_after_close"] = torch.cuda.memory_allocated()
                if "previous_threads" in locals():
                    torch.set_num_threads(previous_threads)
        finally:
            if lease is not None:
                lease.release()
                result["own_lease_released"] = lease.released
            if scheduler is not None:
                result["resources_after"] = scheduler.snapshot()
            result["peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
            result["elapsed_seconds"] = time.monotonic()-started
            _write(output / "result.json", result)
    return result


def main():
    # Direct script execution otherwise permits an older installed package to
    # win over this source tree. The recorded producers must be this checkout.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shared-configuration", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output.resolve(), args.shared_configuration.resolve())
    raise SystemExit(0 if result["qualified"] else 1)


if __name__ == "__main__":
    main()
