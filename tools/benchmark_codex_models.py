import json
import os
import subprocess
import select
import sys
import time
from pathlib import Path
from typing import Dict, List

from ipfs_datasets_py.utils.model_manager import load_model_config


DEFAULT_MODELS: List[str] = []

DEFAULT_BACKENDS: List[str] = []

DEFAULT_HF_MODELS: List[str] = []

DEFAULT_COPILOT_CLI_MODELS: List[str] = []
DEFAULT_COPILOT_SDK_MODELS: List[str] = []


def _parse_model_list(value: str) -> List[str]:
    if not value:
        return []
    models = [item.strip() for item in value.split(",")]
    return [m for m in models if m]


def _parse_list(value: str) -> List[str]:
    if not value:
        return []
    items = [item.strip() for item in value.split(",")]
    return [item for item in items if item]


def _parse_summary(output: str) -> Dict[str, int]:
    passed = 0
    total = 0
    for line in output.splitlines():
        if "Summary:" in line and "/" in line:
            parts = line.split("Summary:")[-1].strip().split()[0]
            if "/" in parts:
                left, right = parts.split("/", 1)
                if left.isdigit() and right.isdigit():
                    passed = max(passed, int(left))
                    total = max(total, int(right))
    return {"passed": passed, "total": total}


def _run_test(test_path: Path, env: Dict[str, str], log) -> Dict[str, object]:
    output_lines: List[str] = []
    heartbeat_seconds = int(os.environ.get("IPFS_DATASETS_PY_CODEX_BENCHMARK_HEARTBEAT", "30"))
    start_time = time.monotonic()
    last_heartbeat = start_time
    proc = subprocess.Popen(
        [sys.executable, str(test_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        bufsize=1,
    )
    if proc.stdout:
        while True:
            ready, _, _ = select.select([proc.stdout], [], [], 1.0)
            if ready:
                line = proc.stdout.readline()
                if line:
                    output_lines.append(line)
                    log(f"  | {line.rstrip()}")
                elif proc.poll() is not None:
                    break
            else:
                if proc.poll() is not None:
                    break

            now = time.monotonic()
            if heartbeat_seconds > 0 and now - last_heartbeat >= heartbeat_seconds:
                log(f"  | ... still running ({now - start_time:.0f}s elapsed)")
                last_heartbeat = now

        remainder = proc.stdout.read()
        if remainder:
            output_lines.append(remainder)
            for line in remainder.splitlines():
                log(f"  | {line}")
    proc.wait()
    output = "".join(output_lines)
    summary = _parse_summary(output)
    return {
        "exit_code": proc.returncode,
        "passed": summary["passed"],
        "total": summary["total"],
        "output": output[-4000:],
    }


def _collect_tests(workspace: Path) -> List[Path]:
    test_glob = os.environ.get(
        "IPFS_DATASETS_PY_CODEX_BENCHMARK_TESTS",
        "tests/top_level_dir_tests/_test_symbolicai_*.py",
    )
    return sorted(workspace.glob(test_glob))


def main() -> int:
    workspace = Path(__file__).resolve().parents[1]
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    log_path = Path(os.environ.get(
        "IPFS_DATASETS_PY_CODEX_BENCHMARK_LOG",
        workspace / "outputs" / "codex_model_benchmark.log",
    ))
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}"
        print(line, flush=True)
        try:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:
            pass
    config = load_model_config()
    env_models = _parse_model_list(os.environ.get("IPFS_DATASETS_PY_CODEX_MODEL_LIST", ""))
    models = env_models or config.get("codex_models") or DEFAULT_MODELS
    env_backends = _parse_list(os.environ.get("IPFS_DATASETS_PY_CODEX_BENCHMARK_BACKENDS", ""))
    backends = env_backends or config.get("backends") or DEFAULT_BACKENDS
    env_hf_models = _parse_list(os.environ.get("IPFS_DATASETS_PY_SYMAI_HF_MODEL_LIST", ""))
    hf_models = env_hf_models or config.get("hf_models") or DEFAULT_HF_MODELS
    env_copilot_models = _parse_list(os.environ.get("IPFS_DATASETS_PY_COPILOT_CLI_MODEL_LIST", ""))
    copilot_models = env_copilot_models or config.get("copilot_cli_models") or DEFAULT_COPILOT_CLI_MODELS
    env_copilot_sdk_models = _parse_list(os.environ.get("IPFS_DATASETS_PY_COPILOT_SDK_MODEL_LIST", ""))
    copilot_sdk_models = (
        env_copilot_sdk_models
        or config.get("copilot_sdk_models")
        or copilot_models
        or DEFAULT_COPILOT_SDK_MODELS
    )

    tests = _collect_tests(workspace)
    if not tests:
        log("No tests found to run.")
        return 1

    log(f"Starting benchmark with {len(backends)} backends and {len(tests)} tests.")

    runs = int(os.environ.get("IPFS_DATASETS_PY_CODEX_BENCHMARK_RUNS", "1"))
    results = {
        "backends": backends,
        "codex_models": models,
        "hf_models": hf_models,
        "copilot_cli_models": copilot_models,
        "copilot_sdk_models": copilot_sdk_models,
        "tests": [str(p) for p in tests],
        "runs": runs,
        "entries": [],
    }

    base_env = os.environ.copy()
    base_env["PYTHONUNBUFFERED"] = "1"
    base_env["IPFS_DATASETS_PY_USE_SYMAI_ENGINE_ROUTER"] = "1"

    variants: List[Dict[str, str]] = []
    for backend in backends:
        if backend == "codex":
            for model in models:
                variants.append({
                    "label": f"codex:{model}",
                    "backend": "codex",
                    "model": model,
                })
            continue

        if backend == "huggingface":
            for model in hf_models:
                variants.append({
                    "label": f"huggingface:{model}",
                    "backend": "huggingface",
                    "model": model,
                })
            continue

        if backend == "copilot_cli":
            for model in copilot_models:
                variants.append({
                    "label": f"copilot_cli:{model}",
                    "backend": "copilot_cli",
                    "model": model,
                })
            continue

        if backend == "copilot_sdk":
            for model in copilot_sdk_models:
                variants.append({
                    "label": f"copilot_sdk:{model}",
                    "backend": "copilot_sdk",
                    "model": model,
                })
            continue

        variants.append({
            "label": backend,
            "backend": backend,
            "model": "",
        })

    for variant in variants:
        model_entry = {
            "label": variant["label"],
            "backend": variant["backend"],
            "model": variant.get("model", ""),
            "runs": [],
        }
        log(f"=== Variant: {variant['label']} ===")
        for run_idx in range(runs):
            run_entry = {
                "index": run_idx,
                "tests": [],
                "exit_code": 0,
                "passed": 0,
                "total": 0,
                "failures": 0,
            }
            log(f"Run {run_idx + 1}/{runs}")
            env = base_env.copy()

            if variant["backend"] == "codex":
                env["IPFS_DATASETS_PY_USE_CODEX_FOR_SYMAI"] = "1"
                env["IPFS_DATASETS_PY_CODEX_MODEL"] = variant["model"]
                env.pop("IPFS_DATASETS_PY_SYMAI_BACKEND", None)
            else:
                env["IPFS_DATASETS_PY_USE_CODEX_FOR_SYMAI"] = "0"
                env["IPFS_DATASETS_PY_SYMAI_BACKEND"] = variant["backend"]
                if variant["backend"] == "huggingface" and variant["model"]:
                    env["IPFS_DATASETS_PY_SYMAI_HF_MODEL"] = variant["model"]
                if variant["backend"] == "copilot_cli" and variant["model"]:
                    env["IPFS_DATASETS_PY_COPILOT_CLI_CMD"] = (
                        f"npx --yes @github/copilot --model {variant['model']} -p {{prompt}}"
                    )
                if variant["backend"] == "copilot_sdk" and variant["model"]:
                    env["IPFS_DATASETS_PY_COPILOT_SDK_MODEL"] = variant["model"]

            for test_path in tests:
                start_time = time.monotonic()
                log(f"- {test_path}")
                test_result = _run_test(test_path, env, log)
                elapsed = time.monotonic() - start_time
                log(
                    f"  exit={test_result['exit_code']} passed={test_result['passed']} "
                    f"total={test_result['total']} time={elapsed:.1f}s"
                )
                run_entry["tests"].append(
                    {
                        "path": str(test_path),
                        **test_result,
                    }
                )
                run_entry["exit_code"] |= int(test_result["exit_code"] != 0)
                run_entry["passed"] += test_result["passed"]
                run_entry["total"] += test_result["total"]
                if test_result["exit_code"] != 0:
                    run_entry["failures"] += 1

            model_entry["runs"].append(run_entry)

        results["entries"].append(model_entry)

    output_path = Path(os.environ.get(
        "IPFS_DATASETS_PY_CODEX_BENCHMARK_OUTPUT",
        workspace / "outputs" / "codex_model_benchmark.json",
    ))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    log(f"Wrote benchmark results to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
