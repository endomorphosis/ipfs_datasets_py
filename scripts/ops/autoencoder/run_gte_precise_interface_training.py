"""Run existing bounded interface training with explicitly recorded clipping.

Use in a fresh CPU process. The original CLI applies resource limits, verifies
every original input/source pin, trains, and verifies its saved checkpoint. A
private helper factory wraps only the numerical training call, after budgeting,
in the float64-clipping context. No original source file is modified. The outer
receipt is authoritative for this additional runtime algorithm; the inner
checkpoint's implementation pins alone do not describe the full execution.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[3]
ADAPTER = REPOSITORY / "ipfs_datasets_py/logic/formalization/autoencoder/gte_precise_gradient_clipping.py"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ref(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def run(*, config, expected_config_sha256, output_directory, receipt_path,
        expected_adapter_sha256, expected_runner_sha256, aligned=False,
        memory_limit_mib=16384, cpu_time_limit_seconds=120):
    if any(name in sys.modules for name in ("torch", "transformers", "tensorflow", "jax")):
        raise ValueError("fresh worker required; model libraries already imported")
    adapter_ref, runner_ref = _ref(ADAPTER), _ref(__file__)
    if (adapter_ref["sha256"] != expected_adapter_sha256
            or runner_ref["sha256"] != expected_runner_sha256):
        raise ValueError("numerical adapter or runner pin mismatch")
    receipt_path = Path(receipt_path).resolve()
    if receipt_path.exists() or not receipt_path.parent.is_dir():
        raise ValueError("new receipt path with existing parent required")
    output = Path(output_directory).resolve()
    if receipt_path.is_relative_to(output):
        raise ValueError("outer runtime receipt must be outside the closed inner output")
    cli_path = Path(__file__).with_name("run_gte_aligned_interface_training.py" if aligned
                                      else "run_gte_decoder_interface_training.py")
    numerical_name = "gte_aligned_interface_training" if aligned else "gte_decoder_interface_training"
    numerical_ref = _ref(ADAPTER.with_name(numerical_name + ".py"))
    cli_ref = _ref(cli_path)
    adapter = _load(ADAPTER, "_precise_gradient_adapter")
    cli = _load(cli_path, "_precise_existing_interface_cli")
    native = cli._native_cli()
    original_helper, original_factory = native._helper, cli._native_cli
    records, executions = [], []

    def helper(name):
        module = original_helper(name)
        if name == numerical_name:
            original_train = module.train_decoder_interfaces
            def train(*args, **kwargs):
                # Original CLI configure_cpu_process has run before this call.
                with adapter.installed_clipper(records):
                    result = original_train(*args, **kwargs)
                executions.append(result["report"]["optimizer_steps"])
                return result
            module.train_decoder_interfaces = train
        return module

    native._helper = helper
    cli._native_cli = lambda: native
    try:
        entry = cli.run_aligned_decoder_interface_training if aligned else cli.run_decoder_interface_training
        result = entry(config, expected_config_sha256=expected_config_sha256,
                       output_directory=str(output), threads=1,
                       memory_limit_mib=memory_limit_mib,
                       cpu_time_limit_seconds=cpu_time_limit_seconds)
    finally:
        native._helper, cli._native_cli = original_helper, original_factory
    if (result["status"] != "trained_unqualified" or executions != [result["optimizer_steps"]]
            or len(records) != result["optimizer_steps"]):
        raise ValueError("one successful bounded training run and one clipping call per step required")
    for ref in (adapter_ref, runner_ref, cli_ref, numerical_ref):
        if _ref(ref["path"]) != ref:
            raise ValueError("runtime implementation changed during training")
    import torch
    receipt = {"schema": "gte-precise-interface-runtime-receipt/v1", "completed": True,
               "captured_at_utc": datetime.now(timezone.utc).isoformat(),
               "algorithm": adapter.ALGORITHM,
               "runtime_injection": "isolated private helper wrapper; temporary torch.nn.utils.clip_grad_norm_ substitution after CPU budget admission; restored before reload verification",
               "inner_implementation_pins_alone_are_complete": False,
               "original_source_files_modified": False, "gradient_dtype": "float32",
               "norm_dtype": "float64", "configured_bound_relaxed": False,
               "torch_version": str(torch.__version__), "python_version": sys.version,
               "implementation_files": [runner_ref, adapter_ref, cli_ref, numerical_ref],
               "config": _ref(config), "manifest": _ref(output / "manifest.json"),
               "checkpoint": _ref(output / "trained-interfaces.json"),
               "training_report": _ref(output / "training-report.json"),
               "reload_verification": _ref(output / "reload-verification.json"),
               "clipping_calls": records, "optimizer_steps": result["optimizer_steps"],
               "training_executed": True, "source_fidelity_qualified": False,
               "proof_authority": False, "result": result}
    with receipt_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
    return {**result, "runtime_receipt": _ref(receipt_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "expected-config-sha256", "output-directory", "receipt-path",
                 "expected-adapter-sha256", "expected-runner-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--aligned", action="store_true")
    parser.add_argument("--memory-limit-mib", type=int, default=16384)
    parser.add_argument("--cpu-time-limit-seconds", type=int, default=120)
    result = run(**vars(parser.parse_args()))
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
