"""Exact published Legal384 package replay with an additive private CUDA head.

Read-only immutable Hub download into a fresh cache, copied into fresh regular
release files before native loading. The released core remains CPU-bound; CUDA
is separately recorded for its private formula head and real GTE encoder.
"""
from __future__ import annotations

from copy import deepcopy
import gc
import hashlib
import importlib
import json
import os
from pathlib import Path
import resource
import sys
import time
import traceback

from qualify_modal_formula_cuda import _compare_numbers, _decision, _pin, _raw, _write


def run(output, configuration_path):
    output.mkdir()
    started = time.monotonic()
    result = {"schema": "published-legal384-private-cuda-qualification/v1", "qualified": False,
              "error": None, "training_calls": 0, "source_semantics_verified": False,
              "proof_authority": False, "execution_attestation": False, "whole_model_cuda": False,
              "codebase_384d_qualification": False, "core_device": "cpu", "pid": os.getpid()}
    scheduler, lease, original_train = None, None, None
    wrappers = []
    try:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler, ResourceSchedulerConfig, ResourceLane
        configuration = json.loads(configuration_path.read_bytes())
        scheduler = GlobalResourceScheduler(ResourceSchedulerConfig(**configuration["persisted_config"],
            state_path=configuration["state_path"], lease_ttl_seconds=configuration["lease_ttl_seconds"],
            auto_renew_leases=configuration["auto_renew_leases"]))
        result["shared_configuration"] = _pin(configuration_path)
        result["resources_before"] = scheduler.snapshot()
        lease = scheduler.acquire(ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=1, memory_mb=2048,
            gpu_memory_mb=2048, requires_gpu=True, timeout=30,
            request_id="published-legal384-private-cuda-qualification")
        result["admission"] = dict(lease_id=lease.lease_id, cpu_slots=lease.cpu_slots,
            memory_mb=lease.memory_mb, gpu_memory_mb=lease.gpu_memory_mb, requires_gpu=lease.requires_gpu,
            state_path=str(scheduler.state_path), wait_seconds=lease.wait_seconds)
        print("ADMITTED", lease.lease_id, flush=True)
        import torch
        previous_threads = torch.get_num_threads()
        torch.set_num_threads(1)
        if not torch.cuda.is_available():
            raise RuntimeError("actual CUDA unavailable")
        torch.cuda.init()
        torch.cuda.reset_peak_memory_stats()
        probe = torch.tensor([2.], device="cuda:0")
        assert (probe*probe).cpu().tolist() == [4.]
        del probe
        result["hardware"] = dict(torch=str(torch.__version__), cuda_runtime=torch.version.cuda,
            name=torch.cuda.get_device_name(), capability=list(torch.cuda.get_device_capability()),
            physical_memory_bytes=torch.cuda.get_device_properties(0).total_memory,
            free_total_device_bytes=list(torch.cuda.mem_get_info()))
        os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "30"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        from ipfs_datasets_py.logic.formalization.autoencoder import checkpoint_hub as hub
        from ipfs_datasets_py.logic.formalization.autoencoder.legal_device_inference_session import DeviceLegalAutoencoder
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as learning
        descriptor = hub.default_descriptor("legal_ir")
        result["descriptor"] = descriptor
        cache = output.with_name(output.name.replace("qualification", "download"))
        if cache.exists():
            raise ValueError("published download cache must be new")
        cache.mkdir()
        result["download_cache"] = str(cache)
        from huggingface_hub import hf_hub_download
        def fetch(name):
            if lease.cancelled or time.monotonic()-started > 300:
                raise TimeoutError("published fixture cancelled or exhausted bounded deadline")
            path = Path(hf_hub_download(repo_id=descriptor["repository_id"], repo_type="model",
                revision=descriptor["revision"], filename=descriptor["release_prefix"] + "/" + name,
                cache_dir=cache, local_files_only=False))
            return hub._read(path)
        manifest_raw = fetch("manifest.json")
        assert hashlib.sha256(manifest_raw).hexdigest() == descriptor["manifest_sha256"]
        manifest = hub.validate_manifest(json.loads(manifest_raw), domain="legal_ir")
        release = output/"release"
        release.mkdir()
        (release/"manifest.json").write_bytes(manifest_raw)
        (release/"manifest.json").chmod(0o444)
        for name, pin in manifest["files"].items():
            raw = fetch(name)
            assert len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"]
            destination = release/name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            destination.chmod(0o444)
        result["downloaded_release"] = manifest
        result["download_seconds"] = time.monotonic()-started
        names = ["ipfs_datasets_py.logic.formalization.autoencoder." + name for name in (
            "legal_device_inference_session", "legal_384_package", "legal_inference_session", "checkpoint_hub",
            "published_384_checkpoints", "source_embeddings_device_384")]
        names += ["ipfs_datasets_py.optimizers.logic_theorem_optimizer." + name for name in (
            "modal_latent_formula_device_inference", "modal_latent_formula_inference", "modal_joint_formula_inference",
            "modal_joint_formula", "modal_latent_formula", "legal_formula_codec", "checkpoint_content_guard")]
        producers = output/"producers"
        producers.mkdir()
        result["source_pins"] = []
        for index, path in enumerate([Path(__file__), *[Path(importlib.import_module(name).__file__) for name in names]]):
            pin = _pin(path)
            target = producers/(str(index).zfill(2)+"-"+path.name)
            target.write_bytes(path.read_bytes())
            target.chmod(0o444)
            pin["copy"] = str(target.relative_to(output))
            result["source_pins"].append(pin)
        result["producer_scope"] = "listed modules and original released package binding; not full transitive dependency attestation"
        loaded = hub.open_local_autoencoder("legal_ir", release,
            manifest_sha256=descriptor["manifest_sha256"], optimized=False)
        loaded.descriptor = descriptor
        payload_before = deepcopy(loaded.runtime._payload)
        core_before = loaded.runtime.describe()["core_binding"]
        assert payload_before["formula_checkpoint"] is not None
        fixture = payload_before["fixture"]["rows"]
        assert 1 <= len(fixture) <= 128
        _write(output/"retained-fixture.json", fixture)
        original_train = learning.train
        def forbidden(*args, **kwargs):
            result["training_calls"] += 1
            raise AssertionError("published inference attempted training")
        learning.train = forbidden
        cpu = DeviceLegalAutoencoder(loaded, optimized=False)
        cuda = DeviceLegalAutoencoder(loaded, optimized=True)
        wrappers.extend([cpu,cuda])
        replays = []
        for count in (1, 17, 128):
            rows = [{**fixture[index%len(fixture)], "id": "published-"+str(index)} for index in range(count)]
            reports, durations = {}, {}
            for label, wrapper in (("cpu",cpu),("cuda",cuda)):
                t0 = time.monotonic()
                reports[label] = wrapper.infer(rows)
                torch.cuda.synchronize()
                durations[label] = time.monotonic()-t0
            a,b = reports["cpu"]["result"],reports["cuda"]["result"]
            assert [_decision(row) for row in a["rows"]] == [_decision(row) for row in b["rows"]]
            profile = b["inference_implementation"]["formula_decoder"]
            assert profile["cuda_executed"] is True and profile["actual_forward_executed"] is True
            error = _compare_numbers(list(a["decoded_embeddings"].values()),list(b["decoded_embeddings"].values()))
            replays.append(dict(count=count,cpu=reports["cpu"],cuda=reports["cuda"],inference_seconds=durations,
                exact_decision_parity=True,max_absolute_error=error))
        result["direct_inference"] = replays
        texts = [row["source_text"] for row in fixture[:2]]
        cpu_texts = cpu.infer_texts(texts)
        cpu.close()
        cuda_texts = cuda.infer_texts(texts)
        def source_decision(row):
            value = _decision(row)
            value.pop("latent_sha256")
            return value
        result["source_text_inference"] = dict(cpu=cpu_texts,cuda=cuda_texts,
            latent_identity_parity="finite_numerical_not_bitwise",
            exact_source_token_identity=cpu_texts["embedding_execution"]["tokens"] == cuda_texts["embedding_execution"]["tokens"])
        assert [source_decision(row) for row in cpu_texts["result"]["rows"]] == [source_decision(row) for row in cuda_texts["result"]["rows"]]
        assert cpu_texts["embedding_execution"]["cuda_executed"] is False
        assert cuda_texts["embedding_execution"]["cuda_executed"] is True
        result["source_text_inference"].update(exact_decision_parity=True,
            max_absolute_error=_compare_numbers(list(cpu_texts["result"]["decoded_embeddings"].values()),
                                                list(cuda_texts["result"]["decoded_embeddings"].values())))
        assert loaded.runtime._payload == payload_before
        assert loaded.runtime.describe()["core_binding"] == core_before
        result.update(checkpoint_and_adam_unchanged=True,native_core_unchanged=True,
            formula_checkpoint_sha256=hashlib.sha256(_raw(payload_before["formula_checkpoint"])).hexdigest(),
            release_package_sha256=hashlib.sha256(_raw(payload_before)).hexdigest(),
            retained_formula_progress=payload_before["formula_checkpoint"]["progress"])
        for pin in result["source_pins"]:
            assert _pin(pin["path"])["sha256"] == pin["sha256"]
        result["qualified"] = True
        print("PUBLISHED_EXACT_PACKAGE_CUDA_REPLAY_PASSED",flush=True)
    except BaseException as error:
        result["error"] = dict(type=type(error).__name__,message=str(error),traceback=traceback.format_exc()[-16384:])
        print("PUBLISHED_QUALIFICATION_FAILED",type(error).__name__,str(error),flush=True)
    finally:
        if original_train is not None:
            learning.train = original_train
        for wrapper in wrappers:
            wrapper.close()
        wrappers.clear()
        if "cpu" in locals():
            del cpu
        if "cuda" in locals():
            del cuda
        gc.collect()
        if "torch" in locals():
            if torch.cuda.is_available():
                result["peak_gpu_allocated_bytes"] = torch.cuda.max_memory_allocated()
                result["peak_gpu_reserved_bytes"] = torch.cuda.max_memory_reserved()
                torch.cuda.empty_cache()
                result["gpu_allocated_after_close"] = torch.cuda.memory_allocated()
            if "previous_threads" in locals():
                torch.set_num_threads(previous_threads)
        if lease is not None:
            lease.release()
            result["own_lease_released"] = lease.released
        if scheduler is not None:
            result["resources_after"] = scheduler.snapshot()
        result["peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
        result["elapsed_seconds"] = time.monotonic()-started
        _write(output/"result.json",result)
    return result


if __name__ == "__main__":
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--shared-configuration",required=True,type=Path)
    args=parser.parse_args()
    value=run(args.output.resolve(),args.shared_configuration.resolve())
    raise SystemExit(0 if value["qualified"] else 1)
