"""Admitted small CUDA allocation probe; never a model/head qualification."""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import time
import traceback


CONFIG_SHA = "c60d91943187515915b8c4c0d0ace3f3703f7de4da1960f09e49371a8cdf6575"
QUALIFIER_SHA = "73a7997a82a71c30d71773dbb50374d30564a40e6630d885ee2e7845ee70ce1c"


def pin(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def run(output, configuration):
    output.mkdir()
    started = time.monotonic()
    result = {"schema": "owned-cuda-small-allocation-probe/v1",
        "probe_passed": False, "head_qualified": False, "encoder_qualified": False,
        "production_qualified": False, "proof_authority": False, "execution_attestation": False,
        "models_loaded": False, "training_calls": 0, "foreign_process_actions": False,
        "scope": "small allocation/kernel and own-process cleanup only",
        "observed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "error": None}
    scheduler = lease = torch = device = probe = None
    old_threads, safe_close = None, True
    qualifier_path = Path(__file__).with_name("qualify_native_768_device.py")
    try:
        result["configuration"] = pin(configuration)
        result["qualifier"] = pin(qualifier_path)
        result["probe_source"] = pin(Path(__file__).resolve())
        if result["configuration"]["sha256"] != CONFIG_SHA or result["qualifier"]["sha256"] != QUALIFIER_SHA:
            raise ValueError("pinned probe configuration or cleanup implementation differs")
        spec = importlib.util.spec_from_file_location("owned_cuda_probe_cleanup", qualifier_path)
        qualifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(qualifier)
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
            GlobalResourceScheduler, ResourceSchedulerConfig, ResourceLane)
        settings = json.loads(configuration.read_bytes())
        scheduler = GlobalResourceScheduler(ResourceSchedulerConfig(**settings["persisted_config"],
            state_path=settings["state_path"], lease_ttl_seconds=settings["lease_ttl_seconds"],
            auto_renew_leases=settings["auto_renew_leases"]))
        result["resources_before"] = scheduler.snapshot()
        lease = scheduler.acquire(ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=1,
            memory_mb=1024, gpu_memory_mb=256, unified_memory_mb=1280, requires_gpu=True,
            timeout=30, request_id="owned-cuda-small-allocation-probe")
        result["admission"] = lease.to_dict()
        import torch as torch_runtime
        torch = torch_runtime
        old_threads = torch.get_num_threads()
        torch.set_num_threads(1)
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable")
        torch.cuda.init()
        device = torch.cuda.current_device()
        result["gpu_allocated_before_owned_sessions_bytes"] = torch.cuda.memory_allocated(device)
        result["gpu_reserved_before_owned_sessions_bytes"] = torch.cuda.memory_reserved(device)
        result["free_total_device_bytes_before_probe"] = list(torch.cuda.mem_get_info(device))
        result["torch"] = str(torch.__version__)
        result["cuda_runtime"] = torch.version.cuda
        result["device"] = torch.cuda.get_device_name(device)
        result["device_index"] = device
        probe = torch.tensor([2.], device=f"cuda:{device}")
        observed = (probe * probe).cpu().tolist()
        if observed != [4.]:
            raise ValueError("actual small CUDA kernel output differs")
        torch.cuda.synchronize(device)
        result["actual_initial_cuda_kernel"] = True
        result["probe_output"] = observed
        result["probe_passed"] = True
    except BaseException as error:
        result["error"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
    finally:
        probe = None
        gc.collect()
        if torch is not None:
            try:
                qualifier._cleanup_owned_cuda(torch, device, result)
            except BaseException as error:
                result["probe_passed"], safe_close = False, False
                result["cuda_cleanup_error"] = {"type": type(error).__name__, "message": str(error)}
            if old_threads is not None:
                torch.set_num_threads(old_threads)
        if lease is not None:
            if safe_close:
                lease.release()
            result["own_root_lease_released"] = lease.released
        if scheduler is not None:
            result["resources_after"] = scheduler.snapshot()
        for key, path in (("configuration", configuration), ("qualifier", qualifier_path),
                          ("probe_source", Path(__file__).resolve())):
            if key in result and pin(path) != result[key]:
                result["probe_passed"] = False
                result["source_currentness_error"] = key
        result["elapsed_seconds"] = time.monotonic() - started
        path = output / "result.json"
        with path.open("xb") as stream:
            stream.write(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
        path.chmod(0o444)
        print(json.dumps({"probe_passed": result["probe_passed"], "result": pin(path),
                          "error": result["error"], "own_root_lease_released": result.get("own_root_lease_released")}))
    return 0 if result["probe_passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--configuration", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.output.absolute(), args.configuration.absolute()))
