"""Bounded actual-device GTE768 and fresh native768 source-span qualification.

No historical training owners are opened. Two explicitly reported setup fits
create a small diagnostic head, or their exact checkpoint is replayed without
another fit. Inference fitting is forbidden. This establishes
numeric/device execution, never production model quality or proof authority.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import gc
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import resource
import statistics
import time
import traceback


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def _pin(path):
    path = Path(path).absolute()
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _write(path, value):
    with path.open("xb") as stream:
        stream.write(_raw(value))
    path.chmod(0o444)
    return _pin(path)


def _parity(left, right):
    if len(left) != len(right) or any(len(a) != 768 or len(b) != 768 for a, b in zip(left, right)):
        raise ValueError("actual768 vector coverage/shape differs")
    error = max(abs(a-b) for aa, bb in zip(left, right) for a, b in zip(aa, bb))
    if not math.isfinite(error) or error > 5e-5:
        raise ValueError("actual768 CPU/CUDA parity exceeds absolute5e-5")
    return error


def _decisions(result):
    keys = ("source_sha256", "latent_sha256", "status", "reason", "detail", "canonical_ir", "formula_text",
            "formal_outputs", "family_syntax_checked", "latent_input_enabled")
    return [{key: row.get(key) for key in keys} for row in result["rows"]]


def _cleanup_owned_cuda(torch, device, result):
    """Close this finite process's CUDA work after either success or early refusal."""
    if device is None:
        result["cuda_cleanup_status"] = "no_owned_cuda_device_initialized"
        return
    torch.cuda.synchronize(device)
    result["gpu_allocated_after_owned_sessions_closed_bytes"] = torch.cuda.memory_allocated(device)
    result["gpu_reserved_after_owned_sessions_closed_bytes"] = torch.cuda.memory_reserved(device)
    # cuBLAS retains process-local workspaces after GRU execution. All owned
    # sessions have closed and synchronized before this finite process clears them.
    result["framework_cuda_workspace_clear_supported"] = hasattr(torch._C, "_cuda_clearCublasWorkspaces")
    if result["framework_cuda_workspace_clear_supported"]:
        torch._C._cuda_clearCublasWorkspaces()
        torch.cuda.synchronize(device)
    result["gpu_allocated_after_framework_workspace_clear_bytes"] = torch.cuda.memory_allocated(device)
    baseline = result.get("gpu_allocated_before_owned_sessions_bytes")
    if baseline is None:
        raise ValueError("CUDA allocation baseline unavailable; cleanup cannot establish release")
    if result["gpu_allocated_after_framework_workspace_clear_bytes"] != baseline:
        raise ValueError("GPU allocations remained after owned sessions/framework workspaces closed")
    torch.cuda.empty_cache()
    torch.cuda.synchronize(device)
    result["gpu_reserved_after_cache_release_bytes"] = torch.cuda.memory_reserved(device)
    result["cuda_cleanup_status"] = "owned_allocations_restored_to_baseline"


def run(output, config_path, manifest_path, assets_path, head_source=None, expected_head_source_sha256=None,
        admission_timeout_seconds=30):
    if type(admission_timeout_seconds) is not int or not 1 <= admission_timeout_seconds <= 300:
        raise ValueError("admission wait must be1..300seconds")
    output.mkdir(parents=False)
    started = time.monotonic()
    result = {"schema": "native768-device-qualification/v1", "qualified": False,
              "scope": "pinned_complete_gte768_encoder_and_fresh_diagnostic_native768_source_span_head",
              "production_model_quality_qualified": False, "codebase768_scan_qualified": False,
              "leanstral4096_qualified": False, "proof_authority": False, "source_semantics_verified": False,
              "execution_attestation": False, "kernel_resource_enforcement": False,
              "setup_training_calls": 0, "inference_training_calls": 0,
              "pid": os.getpid(), "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "admission_timeout_seconds": admission_timeout_seconds,
              "error": None, "source_pins": []}
    scheduler, lease, session = None, None, None
    device, probe = None, None
    old_threads, originals = None, []
    close_safe = True
    try:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
            GlobalResourceScheduler, ResourceSchedulerConfig, ResourceLane)
        configuration = json.loads(config_path.read_bytes())
        scheduler = GlobalResourceScheduler(ResourceSchedulerConfig(**configuration["persisted_config"],
            state_path=configuration["state_path"], lease_ttl_seconds=configuration["lease_ttl_seconds"],
            auto_renew_leases=configuration["auto_renew_leases"]))
        result["shared_configuration"] = _pin(config_path)
        result["resources_before"] = scheduler.snapshot()
        lease = scheduler.acquire(ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=2, memory_mb=6144,
            gpu_memory_mb=3072, unified_memory_mb=9216, requires_gpu=True,
            timeout=admission_timeout_seconds, request_id="native768-device-qualification")
        result["admission"] = lease.to_dict()
        print("ADMITTED", lease.lease_id, flush=True)
        import torch
        old_threads = torch.get_num_threads()
        torch.set_num_threads(1)
        if not torch.cuda.is_available():
            raise RuntimeError("actual CUDA required; mocked device or CPU fallback cannot qualify")
        torch.cuda.init()
        device = torch.cuda.current_device()
        # Capture before the first allocation: even a one-element probe can
        # fail on a shared device, and its refusal still needs safe lease cleanup.
        result["gpu_allocated_before_owned_sessions_bytes"] = torch.cuda.memory_allocated(device)
        result["gpu_reserved_before_owned_sessions_bytes"] = torch.cuda.memory_reserved(device)
        probe = torch.tensor([2.], device=f"cuda:{device}")
        assert (probe * probe).cpu().tolist() == [4.]
        probe = None
        torch.cuda.synchronize(device)
        torch.cuda.reset_peak_memory_stats(device)
        result["hardware"] = {"torch": str(torch.__version__), "cuda_runtime": torch.version.cuda,
            "name": torch.cuda.get_device_name(device), "capability": list(torch.cuda.get_device_capability(device)),
            "device_index": device, "actual_initial_cuda_kernel": True,
            "physical_memory_bytes": torch.cuda.get_device_properties(device).total_memory,
            "free_total_device_bytes_before_models": list(torch.cuda.mem_get_info(device)),
            "persistent_precision_policy_mutated": False,
            "precision_scope": "owned worker process; strict head GRU scope restores ambient CuDNN policy"}
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        names = [
            "ipfs_datasets_py.logic.formalization.autoencoder.source_embeddings_device_768",
            "ipfs_datasets_py.logic.formalization.autoencoder.source_embeddings_768_complete",
            "ipfs_datasets_py.logic.formalization.autoencoder.source_embeddings_768",
            "ipfs_datasets_py.logic.formalization.autoencoder.gte_multilingual_profile",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_device_inference",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_dimensions",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_formula",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_formula_codec",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.checkpoint_content_guard",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler",
            "ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_device_batch_inference",
        ]
        modules = [importlib.import_module(name) for name in names]
        result["producer_pin_scope"] = "listed source files; no full dependency or process-origin attestation"
        producers = output / "producers"
        producers.mkdir()
        for index, path in enumerate([Path(__file__), *[Path(module.__file__) for module in modules]]):
            raw = path.read_bytes()
            pin = {"path": str(path.absolute()), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            copy = producers / (f"{index:02d}-" + path.name)
            copy.write_bytes(raw)
            copy.chmod(0o444)
            pin["copy"] = str(copy.relative_to(output))
            result["source_pins"].append(pin)
        enc, complete, _, _, head, dims, span = modules[:7]
        expected = "8beb874aa7b06599346173fde12e95f9f926b3028942d5014cdd2f99c4385166"
        if _pin(manifest_path)["sha256"] != expected:
            raise ValueError("fixed native768 asset manifest differs")
        arguments = dict(manifest_path=manifest_path, expected_manifest_sha256=expected,
            model_directory=assets_path / "model", code_directory=assets_path / "code")
        rows = [{"id": f"native768-{i}", "source_text": text} for i, text in enumerate([
            "Lark must retain books.", "Wren may publish records.", "Finch must not destroy files.",
            *[f"def compare_{i}(a: int, b: int) -> bool:\n    return a < b\n" for i in range(29)]])]
        _write(output / "source-rows.json", rows)

        def poll():
            if lease.cancelled:
                raise RuntimeError("shared qualification lease cancelled")
            if time.monotonic() - started > 600:
                raise TimeoutError("bounded qualification exceeded600seconds")

        class QualificationCancellation:
            def is_set(self):
                return lease.cancelled or time.monotonic() - started > 600
        cancellation = QualificationCancellation()

        def timed(call, repetitions=3):
            values, latest = [], None
            for _ in range(repetitions):
                poll()
                cpu_rng, cuda_rng = torch.random.get_rng_state(), torch.cuda.get_rng_state(device)
                t0 = time.monotonic()
                latest = call()
                torch.cuda.synchronize(device)
                values.append(time.monotonic() - t0)
                if not torch.equal(cpu_rng, torch.random.get_rng_state()) or not torch.equal(cuda_rng, torch.cuda.get_rng_state(device)):
                    raise ValueError("inference changed CPU/CUDA RNG state")
            return {"samples_seconds": values, "median_seconds": statistics.median(values)}, latest

        # One ordinary complete producer call is the reload/full-hash reference.
        print("ENCODER_REFERENCE_CPU", flush=True)
        poll()
        t0 = time.monotonic()
        baseline = complete.embed_rows(rows, **arguments, batch_size=16)
        result["encoder_reference"] = {"elapsed_seconds": time.monotonic()-t0,
            "repetitions": 1, "profile_id": baseline["profile_id"],
            "result": _write(output / "encoder-reference.json", baseline)}
        baseline_vectors = [receipt["embedding"] for receipt in baseline["receipts"]]
        lanes = {}
        result["encoder"] = lanes
        cuda_result = None
        for optimized, label in ((False, "cpu"), (True, "cuda")):
            print("ENCODER", label, flush=True)
            poll()
            t0 = time.monotonic()
            session = enc.SourceEmbeddingDeviceSession768(**arguments, optimized=optimized, cancel_event=cancellation)
            cold_seconds = time.monotonic()-t0
            warmup = session.infer(rows, batch_size=16, cancel_event=cancellation)
            lane = {"cold_admission_seconds": cold_seconds, "profile": session.describe(),
                    "warmup": _write(output / f"encoder-{label}-warmup.json", warmup), "batches": {}}
            for count in (1, 16, 32):
                timing, actual = timed(lambda: session.infer(rows[:count], batch_size=16, cancel_event=cancellation))
                lane["batches"][str(count)] = {**timing,
                    "result": _write(output / f"encoder-{label}-batch{count}.json", actual)}
                lane["batches"][str(count)]["reference_max_abs_error"] = _parity(
                    baseline_vectors[:count], actual["vectors"])
                if any(a["token_input_sha256"] != b["token_input_sha256"] or
                       a["token_count_including_special_tokens"] != b["token_count_including_special_tokens"]
                       for a, b in zip(baseline["receipts"][:count], actual["receipts"])):
                    raise ValueError("encoder exact token inputs differ at batch" + str(count))
                if actual["input_row_count"] != count or any(
                    batch["input_device"] != label if label == "cpu" else not batch["input_device"].startswith("cuda:")
                    for batch in actual["actual_forward_batches"]):
                    raise ValueError("actual encoder device/coverage differs")
            lane["reference_max_abs_error"] = _parity(baseline_vectors, actual["vectors"])
            lane["token_parity_with_reference"] = all(
                a["token_input_sha256"] == b["token_input_sha256"] and
                a["token_count_including_special_tokens"] == b["token_count_including_special_tokens"]
                for a, b in zip(baseline["receipts"], actual["receipts"]))
            if not lane["token_parity_with_reference"]:
                raise ValueError("encoder exact token inputs differ")
            if optimized:
                if not actual["cuda_executed"]:
                    raise ValueError("new default encoder did not execute CUDA")
                cuda_result = actual
            session.close()
            session = None
            gc.collect()
            lanes[label] = lane
        result["encoder"] = lanes
        result["encoder_warm_speedups_cpu_over_cuda"] = {
            count: lanes["cpu"]["batches"][count]["median_seconds"] / lanes["cuda"]["batches"][count]["median_seconds"]
            for count in ("1", "16", "32")}
        result["encoder_resident_cpu_speedup_over_single_reload_reference"] = (
            result["encoder_reference"]["elapsed_seconds"] / lanes["cpu"]["batches"]["32"]["median_seconds"])

        print("DIAGNOSTIC_HEAD_SETUP_OR_AUTHENTICATED_REPLAY", flush=True)
        training = []
        for i, (actor, modality, action, obj) in enumerate((
            ("Lark", "O", "retain", "books"), ("Wren", "P", "publish", "records"),
            ("Finch", "F", "destroy", "files"))):
            training.append({"id": rows[i]["id"], "source_text": rows[i]["source_text"],
                "latent": deepcopy(cuda_result["vectors"][i]), "canonical_ir": {"rules": [{
                    "actor": actor, "modality": modality, "action": action, "object": obj,
                    "conditions": [], "exceptions": [], "temporal": []}]}})
        training_pin = _write(output / "diagnostic-training-index.json", training)
        setup_start = time.monotonic()
        source_training = [{key: deepcopy(value) for key, value in row.items() if key != "latent"}
                           for row in training]
        source_training_pin = _write(output / "diagnostic-source-training-index.json", source_training)
        if head_source is not None:
            raw = (head_source / "result.json").read_bytes()
            if not expected_head_source_sha256 or hashlib.sha256(raw).hexdigest() != expected_head_source_sha256:
                raise ValueError("external diagnostic head source result pin differs")
            inherited = json.loads(raw)
            inherited_setup = inherited["head_setup"]
            if inherited["setup_training_calls"] != 2 or inherited["inference_training_calls"] != 0:
                raise ValueError("inherited diagnostic setup accounting differs")
            def adopt(name, expected_sha):
                content = (head_source / name).read_bytes()
                if hashlib.sha256(content).hexdigest() != expected_sha:
                    raise ValueError("inherited diagnostic artifact pin differs:" + name)
                target = output / name
                with target.open("xb") as stream:
                    stream.write(content)
                target.chmod(0o444)
                return _pin(target), json.loads(content)
            parent_pin, parent = adopt("diagnostic-source-parent.json", inherited_setup["source_parent"]["sha256"])
            child_pin, child = adopt("diagnostic-native768-head.json", inherited_setup["child"]["sha256"])
            context = child["context_contract"]
            if context != {"dimension": 768, "representation_id": cuda_result["profile_id"],
                           "producer_sha256": cuda_result["profile"]["profile_sha256"],
                           "training_index_sha256": training_pin["sha256"]}:
                raise ValueError("inherited diagnostic native inputs/profile/index differ")
            parent_report_pin, _ = adopt("diagnostic-parent-fit-report.json", inherited_setup["parent_fit_report"]["sha256"])
            child_report_pin, _ = adopt("diagnostic-child-fit-report.json", inherited_setup["child_fit_report"]["sha256"])
            retained_parent_result = output / "inherited-head-source-result.json"
            retained_parent_result.write_bytes(raw)
            retained_parent_result.chmod(0o444)
            result["inherited_setup_training_calls"] = 2
            result["inherited_head_source_result"] = _pin(retained_parent_result)
        else:
            with torch.random.fork_rng(devices=[device]):
                parent = span.build_checkpoint(source_training, latent_dimension=0, latent_enabled=False,
                    hidden_size=8, embedding_dim=4, projection_width=4, batch_size=2)
                result["setup_training_calls"] += 1
                parent_fit = span.train_decoder(parent, source_training, max_steps=3, max_seconds=30)
                parent = parent_fit["checkpoint"]
                context = {"dimension": 768, "representation_id": cuda_result["profile_id"],
                    "producer_sha256": cuda_result["profile"]["profile_sha256"],
                    "training_index_sha256": training_pin["sha256"]}
                child = dims.build_checkpoint(parent, training, latent_dimension=768,
                    context_contract=context, batch_size=2)
                result["setup_training_calls"] += 1
                child_fit = dims.train_decoder(child, training, max_steps=1, max_seconds=30)
                child = child_fit["checkpoint"]
                parent_pin = _write(output / "diagnostic-source-parent.json", parent)
                child_pin = _write(output / "diagnostic-native768-head.json", child)
                parent_report_pin = _write(output / "diagnostic-parent-fit-report.json", parent_fit["report"])
                child_report_pin = _write(output / "diagnostic-child-fit-report.json", child_fit["report"])
        result["head_setup"] = {"source_parent": parent_pin, "child": child_pin,
            "parent_optimizer_steps": parent["progress"]["optimizer_steps"],
            "child_optimizer_steps": child["progress"]["optimizer_steps"],
            "source_training_index": source_training_pin,
            "parent_fit_report": parent_report_pin,
            "child_fit_report": child_report_pin,
            "elapsed_seconds": time.monotonic()-setup_start, "targets": "three authored diagnostic legal examples",
            "production_selected": False, "native_inputs": "actual CUDA GTE768 output", "context": context}
        before = span.checkpoint_digest(child)
        adam_before = span.checkpoint_digest(child["optimizer_state"])
        if parent["progress"]["optimizer_steps"] != 3 or child["progress"]["optimizer_steps"] != 1:
            raise ValueError("diagnostic setup did not complete the declared3/1optimizersteps")

        def forbidden_fit(*args, **kwargs):
            result["inference_training_calls"] += 1
            raise RuntimeError("fitting is forbidden during768 inference qualification")
        for module in (span, dims):
            originals.append((module, module.train_decoder))
            module.train_decoder = forbidden_fit
        heads = {}
        result["head"] = heads
        texts = [row["source_text"] for row in rows]
        receipt_pins = [span.checkpoint_digest(receipt) for receipt in cuda_result["receipts"]]
        with torch.random.fork_rng(devices=[device]):
            native_reference = dims.DimensionalSpanDecoder(child)
        native_decisions = native_reference.decode_formal_logic(texts, cuda_result["vectors"])
        result["head_native_reference"] = _write(output / "head-native-reference.json", native_decisions)
        numeric_rows = [{"tokens": span.tokenize_source(text), "latent": vector}
                        for text, vector in zip(texts[:16], cuda_result["vectors"][:16])]
        with torch.inference_mode():
            native_logits = native_reference.model(*span._batch(torch, numeric_rows), enabled=True)
        native_logits = {name: value.detach().cpu().tolist() for name, value in native_logits.items()}
        result["head_native_reference_logits"] = _write(output / "head-native-reference-logits.json", native_logits)
        for optimized, label, session_type in ((False, "cpu", head.DeviceDimensionalSpanSession),
                (True, "cuda", head.DeviceDimensionalSpanSession),
                (True, "cuda_batched", modules[10].DeviceBatchedDimensionalSpanSession)):
            print("HEAD", label, flush=True)
            poll()
            cpu_rng, cuda_rng = torch.random.get_rng_state(), torch.cuda.get_rng_state(device)
            t0 = time.monotonic()
            session = session_type(child, expected_checkpoint_sha256=before,
                optimized=optimized, scheduler=scheduler, parent_lease=lease,
                max_seconds=120, memory_mb=1024, gpu_memory_mb=256, unified_memory_mb=1280,
                cancel_event=cancellation)
            cold_seconds = time.monotonic()-t0
            if not torch.equal(cpu_rng, torch.random.get_rng_state()) or not torch.equal(cuda_rng, torch.cuda.get_rng_state(device)):
                raise ValueError("private head admission changed CPU/CUDA RNG")
            with torch.inference_mode():
                private_logits = session._model(*span._batch(session._tensor_factory, numeric_rows), enabled=True)
            private_logits = {name: value.detach().cpu().tolist() for name, value in private_logits.items()}
            def flatten(value):
                return [number for part in value for number in flatten(part)] if isinstance(value, list) else [value]
            logit_errors = {}
            for name in native_logits:
                a, b = flatten(native_logits[name]), flatten(private_logits[name])
                if len(a) != len(b):
                    raise ValueError("private head native numeric shape differs")
                error = max(abs(x-y) for x,y in zip(a,b))
                if not math.isfinite(error) or error > 5e-5:
                    raise ValueError("private head native numeric parity exceeds5e-5")
                logit_errors[name] = error
            def infer(count):
                return session.decode_formal_logic(texts[:count], cuda_result["vectors"][:count],
                    embedding_receipts=cuda_result["receipts"][:count], expected_receipt_sha256s=receipt_pins[:count])
            infer(1)
            lane = {"cold_admission_seconds": cold_seconds, "profile": session.describe(), "batches": {},
                    "native_logit_max_abs_errors": logit_errors,
                    "native_logits": _write(output / f"head-{label}-logits.json", private_logits)}
            for count in (1, 16, 32):
                timing, actual = timed(lambda: infer(count))
                lane["batches"][str(count)] = {**timing,
                    "result": _write(output / f"head-{label}-batch{count}.json", actual)}
                expected_forwards = 1 if label == "cuda_batched" else count
                if (len(actual["rows"]) != count or len(actual["actual_forward_batches"]) != expected_forwards
                        or sum(batch["rows"] for batch in actual["actual_forward_batches"]) != count):
                    raise ValueError("native head coverage/forward count differs")
                if _decisions(actual) != _decisions(native_decisions)[:count]:
                    raise ValueError("private head canonical decisions differ from unchanged native decoder")
                expected_device = "cpu" if label == "cpu" else f"cuda:{device}"
                if any(batch["input_device"] != expected_device or
                       batch["output_dtype"] != "float32" or
                       any(value != expected_device for value in batch["output_devices"].values())
                       for batch in actual["actual_forward_batches"]):
                    raise ValueError("native head actual forward device differs")
                if actual["cuda_executed"] is not optimized or actual["execution_profile"]["device"] != expected_device:
                    raise ValueError("native head CUDA execution/profile differs")
            lane["decisions"] = _decisions(actual)
            lane["checkpoint_unchanged"] = span.checkpoint_digest(session.checkpoint) == before
            if not lane["checkpoint_unchanged"]:
                raise ValueError("private head checkpoint changed")
            session.close()
            session = None
            gc.collect()
            heads[label] = lane
        if heads["cpu"]["decisions"] != heads["cuda"]["decisions"]:
            raise ValueError("CPU/CUDA native head canonical decisions differ")
        if heads["cpu"]["decisions"] != heads["cuda_batched"]["decisions"]:
            raise ValueError("CPU/batchedCUDA native head canonical decisions differ")
        result["head"] = heads
        result["head_canonical_decision_parity"] = True
        result["head_warm_speedups_cpu_over_cuda"] = {
            count: heads["cpu"]["batches"][count]["median_seconds"] / heads["cuda"]["batches"][count]["median_seconds"]
            for count in ("1", "16", "32")}
        result["head_batched_speedups_cpu_over_cuda"] = {
            count: heads["cpu"]["batches"][count]["median_seconds"] / heads["cuda_batched"]["batches"][count]["median_seconds"]
            for count in ("1", "16", "32")}
        result["head_batched_speedups_singleton_cuda_over_batched_cuda"] = {
            count: heads["cuda"]["batches"][count]["median_seconds"] / heads["cuda_batched"]["batches"][count]["median_seconds"]
            for count in ("1", "16", "32")}
        result["checkpoint_unchanged"] = span.checkpoint_digest(child) == before
        result["adam_unchanged"] = span.checkpoint_digest(child["optimizer_state"]) == adam_before
        result["gpu_peak_allocated_bytes"] = torch.cuda.max_memory_allocated(device)
        result["process_peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        for pin in result["source_pins"]:
            if _pin(pin["path"])["sha256"] != pin["sha256"]:
                raise ValueError("producer source changed during qualification")
        poll()
        if not result["checkpoint_unchanged"] or not result["adam_unchanged"] or result["inference_training_calls"]:
            raise ValueError("inference checkpoint/Adam/fit boundary failed")
        result["qualified"] = True
    except BaseException as error:
        result["error"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
    finally:
        for module, original in originals:
            module.train_decoder = original
        if session is not None:
            try:
                session.close()
            except BaseException as error:
                result["qualified"] = False
                close_safe = False
                result["close_error"] = {"type": type(error).__name__, "message": str(error)}
        if old_threads is not None:
            try:
                torch.set_num_threads(old_threads)
            except BaseException as error:
                result["qualified"] = False
                result["thread_restore_error"] = {"type": type(error).__name__, "message": str(error)}
            try:
                probe = None
                gc.collect()
                _cleanup_owned_cuda(torch, device, result)
            except BaseException as error:
                result["qualified"], close_safe = False, False
                result["cuda_cleanup_error"] = {"type": type(error).__name__, "message": str(error)}
        gc.collect()
        if lease is not None:
            try:
                if close_safe:
                    lease.release()
                result["own_root_lease_released"] = lease.released
                if not lease.released:
                    result["qualified"] = False
            except BaseException as error:
                result["qualified"] = False
                result["lease_cleanup_error"] = {"type": type(error).__name__, "message": str(error)}
        if scheduler is not None:
            try:
                result["resources_after"] = scheduler.snapshot()
            except BaseException as error:
                result["qualified"] = False
                result["resource_snapshot_error"] = {"type": type(error).__name__, "message": str(error)}
        result["elapsed_seconds"] = time.monotonic()-started
        pin = _write(output / "result.json", result)
        print(json.dumps({"qualified": result["qualified"], "result": pin, "error": result["error"]}), flush=True)
    return 0 if result["qualified"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--head-source", type=Path)
    parser.add_argument("--expected-head-source-sha256")
    parser.add_argument("--admission-timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    raise SystemExit(run(args.output.absolute(), args.configuration.absolute(), args.manifest.absolute(), args.assets.absolute(),
                         args.head_source.absolute() if args.head_source else None, args.expected_head_source_sha256,
                         args.admission_timeout_seconds))
