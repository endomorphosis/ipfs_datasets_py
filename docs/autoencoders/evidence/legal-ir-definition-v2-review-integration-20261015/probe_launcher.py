"""Prepare real-source V2 review subjects against frozen qualified inputs.

This launcher removes ambient application credentials and records local custody.
It does not establish legal review, proof admission or training qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def binding(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    assert root == Path(__file__).resolve().parents[4], "guard and probe checkout roots must match"
    qualification_path = args.qualification.resolve() / "receipt.json"
    qualification_raw = qualification_path.read_bytes()
    qualification_pin = {"bytes": len(qualification_raw), "sha256": hashlib.sha256(qualification_raw).hexdigest()}
    qualified = json.loads(qualification_raw)
    launcher_pin = binding(Path(__file__).resolve())
    assert qualified["receipt_passed"] is True, "passing qualification required"
    inventory = qualified["input_inventory"]
    before = {name: binding(root / name) for name in inventory}
    assert before == inventory, "qualified input bytes must match"
    assert git("rev-parse", "HEAD") == qualified["head"], "qualified HEAD required"
    assert git("write-tree") == qualified["index_tree"], "qualified index required"
    output = args.output_directory.resolve()
    assert not output.exists(), "probe requires an exclusive output directory"
    launch = output.with_name(output.name + "-launch")
    os.umask(0o077)
    launch.mkdir(mode=0o700, exist_ok=False)
    private = launch / "private"
    private.mkdir()
    driver = Path(__file__).with_name("real_source_review_subject_probe.py").resolve()
    reused_driver = root / "docs/autoencoders/evidence/legal-ir-definition-v2-integration-20261015/real_source_probe.py"
    reused_driver_pin = binding(reused_driver)
    driver_before = binding(driver)
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "LD_LIBRARY_PATH") if key in os.environ}
    env.update({"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1",
        "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0", "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0",
        "HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "GITHUB_TOKEN": "offline-probe-sentinel-not-a-credential", "PYTHONPATH": str(root),
        "TMPDIR": str(private), "XDG_CACHE_HOME": str(private / "cache"), "HF_HOME": str(private / "hf")})
    command = [sys.executable, str(driver), "--output-directory", str(output)]
    started = time.monotonic()
    stop_reason = None
    with (launch / "stdout.txt").open("xb") as stdout, (launch / "stderr.txt").open("xb") as stderr:
        process = subprocess.Popen(command, cwd=root, env=env, stdout=stdout, stderr=stderr,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            exit_code = process.wait(timeout=600)
        except subprocess.TimeoutExpired:
            stop_reason = "bounded_600_second_probe_timeout"
            os.killpg(process.pid, signal.SIGTERM)
            try:
                exit_code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                exit_code = process.wait()
    unchanged = (before == {name: binding(root / name) for name in inventory}
        and qualification_pin == binding(qualification_path)
        and launcher_pin == binding(Path(__file__).resolve())
        and driver_before == binding(driver) and reused_driver_pin == binding(reused_driver)
        and git("rev-parse", "HEAD") == qualified["head"]
        and git("write-tree") == qualified["index_tree"])
    receipt_path = output / "probe-receipt.json"
    probe = json.loads(receipt_path.read_bytes()) if receipt_path.is_file() else {}
    report = {"schema": "legal-definition-v2-review-subject-probe-launch/v1", "head": qualified["head"],
        "index_tree": qualified["index_tree"], "command": command, "exit_code": exit_code,
        "elapsed_seconds": time.monotonic() - started, "stop_reason": stop_reason,
        "qualification_receipt": qualification_pin, "launcher": launcher_pin,
        "guard_root_matches_probe_root": True,
        "qualified_input_count": len(inventory), "qualified_inputs_and_driver_unchanged": unchanged,
        "driver": driver_before, "reused_base_driver": reused_driver_pin, "probe_status": probe.get("status"),
        "probe_receipt": binding(receipt_path) if receipt_path.is_file() else None,
        "output_directory": str(output), "stdout": binding(launch / "stdout.txt"),
        "stderr": binding(launch / "stderr.txt"), "timeout_seconds": 600,
        "environment_policy": "allow PATH/LANG/LC_ALL/LD_LIBRARY_PATH only; offline flags and private caches added",
        "receipt_passed": exit_code == 0 and stop_reason is None and unchanged and probe.get("status") == "pass"}
    (launch / "receipt.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: report[key] for key in ("exit_code", "probe_status", "receipt_passed")}))
    return 0 if report["receipt_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
