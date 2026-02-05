import json
import os
import subprocess
import select
import sys
import time
from pathlib import Path
from typing import Dict, List


DEFAULT_MODELS = [
    "gpt-5.2-codex",
    "gpt-5.1-codex-mini",
    "gpt-5.1-codex-max",
    "gpt-5.2",
    "gpt-5.1",
    "gpt-5.1-codex",
    "gpt-5-codex",
    "gpt-5-codex-mini",
    "gpt-5",
]


def _parse_model_list(value: str) -> List[str]:
    if not value:
        return []
    models = [item.strip() for item in value.split(",")]
    return [m for m in models if m]


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
    env_models = _parse_model_list(os.environ.get("IPFS_DATASETS_PY_CODEX_MODEL_LIST", ""))
    models = env_models or DEFAULT_MODELS

    tests = _collect_tests(workspace)
    if not tests:
        log("No tests found to run.")
        return 1

    log(f"Starting benchmark with {len(models)} models and {len(tests)} tests.")

    runs = int(os.environ.get("IPFS_DATASETS_PY_CODEX_BENCHMARK_RUNS", "1"))
    results = {
        "models": models,
        "tests": [str(p) for p in tests],
        "runs": runs,
        "entries": [],
    }

    base_env = os.environ.copy()
    base_env["IPFS_DATASETS_PY_USE_CODEX_FOR_SYMAI"] = "1"
    base_env["PYTHONUNBUFFERED"] = "1"

    for model in models:
        model_entry = {
            "model": model,
            "runs": [],
        }
        log(f"=== Model: {model} ===")
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
            env["IPFS_DATASETS_PY_CODEX_MODEL"] = model

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
